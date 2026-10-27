"""SQLAlchemy (SQLite) data layer for LokiShift.

Two engines back one SQLite file:
- an **async** engine (``aiosqlite``) for profiles, resumes and tasks;
- a **sync** engine for the ``ai_connections`` table, which is read on the
  synchronous LLM path (``get_llm_config`` reads the AI connections).

Every method returns plain dicts, never ORM rows.
"""

import logging
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db_engine import init_models_sync, make_async_engine, make_sync_engine
from app.models import (
    RUNNING_STATUSES,
    AIConnection,
    ModelUsage,
    Profile,
    ProfileResume,
    Task,
    utcnow_iso,
)

logger = logging.getLogger(__name__)

PROFILE_FIELDS = (
    "title",
    "full_name",
    "email",
    "phone",
    "linkedin",
    "location",
    "total_experience",
    "summary",
    "experience",
)

# Columns left out of task list rows (large or only needed on the detail page).
_TASK_HEAVY = {"job_description", "tailored_docx", "ranking", "tailoring"}


class DatabaseBusyError(RuntimeError):
    """A write reservation could not be obtained; retry the unchanged request."""


@contextmanager
def _translate_write_errors() -> Iterator[None]:
    try:
        yield
    except OperationalError as error:
        code = getattr(error.orig, "sqlite_errorcode", None)
        if isinstance(code, int) and code & 0xFF in (
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
        ):
            raise DatabaseBusyError("Database is busy") from error
        raise


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def week_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Monday 00:00 UTC to the next Monday, for the weekly usage meter."""
    now = now or datetime.now(timezone.utc)
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start, start + timedelta(days=7)


def _adopt_previous_name(db_path: Path) -> None:
    """Move the database from its pre-LokiShift name (``lokicv.db``) once.

    Runs at startup, before any connection is opened, so a still-running old
    process is never pulled out from under. Safe to delete once every install
    has started LokiShift at least once.
    """
    old = db_path.with_name("lokicv.db")
    if db_path.exists() or not old.exists():
        return
    for suffix in ("", "-wal", "-shm"):
        source = old.with_name(old.name + suffix)
        if source.exists():
            source.rename(db_path.with_name(db_path.name + suffix))
    logger.info("Renamed %s to %s", old.name, db_path.name)


class Database:
    """Async SQLAlchemy facade."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or settings.sqlite_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        _adopt_previous_name(self.db_path)
        self._async_engine = None
        self._async_session_factory: async_sessionmaker[AsyncSession] | None = None
        self._sync_engine = None
        self._sync_session_factory: sessionmaker[Session] | None = None
        self._initialized = False

    # -- plumbing ------------------------------------------------------------

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._sync_engine = make_sync_engine(self.db_path)
        self._sync_session_factory = sessionmaker(self._sync_engine, expire_on_commit=False)
        init_models_sync(self._sync_engine)
        self._async_engine = make_async_engine(self.db_path)
        self._async_session_factory = async_sessionmaker(
            self._async_engine, expire_on_commit=False
        )
        self._initialized = True

    @property
    def _session(self) -> async_sessionmaker[AsyncSession]:
        self._ensure_initialized()
        assert self._async_session_factory is not None
        return self._async_session_factory

    @asynccontextmanager
    async def _write_session(self) -> AsyncIterator[AsyncSession]:
        with _translate_write_errors():
            async with self._session() as session:
                await session.execute(text("BEGIN IMMEDIATE"))
                yield session

    @property
    def _sync(self) -> sessionmaker[Session]:
        self._ensure_initialized()
        assert self._sync_session_factory is not None
        return self._sync_session_factory

    @contextmanager
    def _sync_write_session(self) -> Iterator[Session]:
        with _translate_write_errors():
            with self._sync() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                yield session

    async def close(self) -> None:
        if self._async_engine is not None:
            await self._async_engine.dispose()
            self._async_engine = None
            self._async_session_factory = None
        if self._sync_engine is not None:
            self._sync_engine.dispose()
            self._sync_engine = None
            self._sync_session_factory = None
        self._initialized = False

    # -- converters ------------------------------------------------------------

    @staticmethod
    def _profile_to_dict(row: Profile) -> dict[str, Any]:
        return {
            "profile_id": row.profile_id,
            **{field: getattr(row, field) for field in PROFILE_FIELDS},
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _resume_to_dict(row: ProfileResume, include_docx: bool = False) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "resume_id": row.resume_id,
            "profile_id": row.profile_id,
            "name": row.name,
            "filename": row.filename,
            "text": row.text,
            "size_bytes": len(row.docx or b""),
            "word_count": len((row.text or "").split()),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        if include_docx:
            doc["docx"] = row.docx
        return doc

    @staticmethod
    def _task_to_dict(row: Task, light: bool = False) -> dict[str, Any]:
        doc = {
            column.name: getattr(row, column.name)
            for column in Task.__table__.columns
            if not (light and column.name in _TASK_HEAVY)
        }
        doc.pop("tailored_docx", None)
        doc["has_tailored_docx"] = row.tailored_docx is not None
        return doc

    # -- profiles --------------------------------------------------------------

    async def list_profiles(self) -> list[dict[str, Any]]:
        async with self._session() as session:
            rows = (await session.execute(select(Profile).order_by(Profile.created_at))).scalars()
            profiles = [self._profile_to_dict(r) for r in rows]
            counts = dict(
                (
                    await session.execute(
                        select(ProfileResume.profile_id, func.count()).group_by(
                            ProfileResume.profile_id
                        )
                    )
                ).all()
            )
            task_counts = dict(
                (
                    await session.execute(
                        select(Task.profile_id, func.count()).group_by(Task.profile_id)
                    )
                ).all()
            )
        for p in profiles:
            p["resume_count"] = int(counts.get(p["profile_id"], 0))
            p["task_count"] = int(task_counts.get(p["profile_id"], 0))
        return profiles

    async def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        async with self._session() as session:
            row = await session.get(Profile, profile_id)
            return self._profile_to_dict(row) if row else None

    async def create_profile(self, values: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        row = Profile(profile_id=str(uuid4()), created_at=now, updated_at=now)
        for field in PROFILE_FIELDS:
            if field in values:
                setattr(row, field, values[field])
        async with self._write_session() as session:
            session.add(row)
            await session.commit()
        return self._profile_to_dict(row)

    async def update_profile(
        self, profile_id: str, values: dict[str, Any]
    ) -> dict[str, Any] | None:
        async with self._write_session() as session:
            row = await session.get(Profile, profile_id)
            if row is None:
                return None
            for field in PROFILE_FIELDS:
                if field in values:
                    setattr(row, field, values[field])
            row.updated_at = utcnow_iso()
            if "title" in values:
                await session.execute(
                    update(Task)
                    .where(Task.profile_id == profile_id)
                    .values(profile_title=values["title"])
                )
            await session.commit()
            return self._profile_to_dict(row)

    async def delete_profile(self, profile_id: str) -> bool:
        async with self._write_session() as session:
            await session.execute(
                delete(ProfileResume).where(ProfileResume.profile_id == profile_id)
            )
            result = await session.execute(delete(Profile).where(Profile.profile_id == profile_id))
            await session.commit()
            return bool(result.rowcount)

    # -- resumes ---------------------------------------------------------------

    async def list_resumes(
        self, profile_id: str, include_docx: bool = False
    ) -> list[dict[str, Any]]:
        async with self._session() as session:
            rows = (
                await session.execute(
                    select(ProfileResume)
                    .where(ProfileResume.profile_id == profile_id)
                    .order_by(ProfileResume.created_at)
                )
            ).scalars()
            return [self._resume_to_dict(r, include_docx) for r in rows]

    async def get_resume(
        self, resume_id: str, include_docx: bool = False
    ) -> dict[str, Any] | None:
        async with self._session() as session:
            row = await session.get(ProfileResume, resume_id)
            return self._resume_to_dict(row, include_docx) if row else None

    async def create_resume(
        self, profile_id: str, name: str, filename: str, docx: bytes, text_: str
    ) -> dict[str, Any]:
        now = utcnow_iso()
        row = ProfileResume(
            resume_id=str(uuid4()),
            profile_id=profile_id,
            name=name,
            filename=filename,
            docx=docx,
            text=text_,
            created_at=now,
            updated_at=now,
        )
        async with self._write_session() as session:
            session.add(row)
            await session.commit()
        return self._resume_to_dict(row)

    async def update_resume(self, resume_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        async with self._write_session() as session:
            row = await session.get(ProfileResume, resume_id)
            if row is None:
                return None
            for field in ("name", "profile_id", "filename", "docx", "text"):
                if field in values:
                    setattr(row, field, values[field])
            row.updated_at = utcnow_iso()
            await session.commit()
            return self._resume_to_dict(row)

    async def delete_resume(self, resume_id: str) -> bool:
        async with self._write_session() as session:
            result = await session.execute(
                delete(ProfileResume).where(ProfileResume.resume_id == resume_id)
            )
            await session.commit()
            return bool(result.rowcount)

    # -- tasks -----------------------------------------------------------------

    async def create_task(self, values: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        row = Task(
            task_id=str(uuid4()),
            status="matching",
            seen=True,
            created_at=now,
            updated_at=now,
            **values,
        )
        async with self._write_session() as session:
            session.add(row)
            await session.commit()
        return self._task_to_dict(row)

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        async with self._session() as session:
            row = await session.get(Task, task_id)
            return self._task_to_dict(row) if row else None

    async def get_tailored_docx(self, task_id: str) -> tuple[bytes | None, str | None]:
        async with self._session() as session:
            row = await session.get(Task, task_id)
            if row is None:
                return None, None
            return row.tailored_docx, row.tailored_filename

    async def list_tasks(
        self,
        *,
        profile_id: str | None = None,
        status: str | None = None,
        search: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = select(Task).order_by(Task.created_at.desc()).limit(limit).offset(offset)
        # Timestamps are stored as UTC ISO strings, so compare in the same form.
        if created_from:
            query = query.where(Task.created_at >= _utc_iso(created_from))
        if created_to:
            query = query.where(Task.created_at < _utc_iso(created_to))
        if profile_id:
            query = query.where(Task.profile_id == profile_id)
        if status:
            query = query.where(Task.status == status)
        if search:
            like = f"%{search.strip()}%"
            query = query.where(
                Task.job_title.ilike(like) | Task.vendor_company.ilike(like)
            )
        async with self._session() as session:
            rows = (await session.execute(query)).scalars()
            return [self._task_to_dict(r, light=True) for r in rows]

    async def update_task(self, task_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        async with self._write_session() as session:
            row = await session.get(Task, task_id)
            if row is None:
                return None
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utcnow_iso()
            await session.commit()
            return self._task_to_dict(row)

    async def delete_task(self, task_id: str) -> bool:
        async with self._write_session() as session:
            result = await session.execute(delete(Task).where(Task.task_id == task_id))
            await session.commit()
            return bool(result.rowcount)

    async def running_tasks(self) -> list[tuple[str, str]]:
        """``(task_id, status)`` for tasks a restart interrupted."""
        async with self._session() as session:
            rows = await session.execute(
                select(Task.task_id, Task.status)
                .where(Task.status.in_(RUNNING_STATUSES))
                .order_by(Task.created_at)
            )
            return [(r[0], r[1]) for r in rows.all()]

    async def mark_seen(self, task_ids: list[str] | None = None) -> int:
        async with self._write_session() as session:
            query = update(Task).where(Task.seen.is_(False)).values(seen=True)
            if task_ids is not None:
                query = query.where(Task.task_id.in_(task_ids))
            result = await session.execute(query)
            await session.commit()
            return int(result.rowcount or 0)

    async def unseen_tasks(self) -> list[dict[str, Any]]:
        async with self._session() as session:
            rows = (
                await session.execute(
                    select(Task).where(Task.seen.is_(False)).order_by(Task.updated_at.desc())
                )
            ).scalars()
            return [self._task_to_dict(r, light=True) for r in rows]

    async def task_stats(self) -> dict[str, Any]:
        start, end = week_bounds()
        async with self._session() as session:
            by_status = dict(
                (await session.execute(select(Task.status, func.count()).group_by(Task.status))).all()
            )
            this_week = await session.scalar(
                select(func.count())
                .select_from(Task)
                .where(Task.created_at >= start.isoformat(), Task.created_at < end.isoformat())
            )
            resumes = await session.scalar(select(func.count()).select_from(ProfileResume))
            profiles = await session.scalar(select(func.count()).select_from(Profile))
        total = sum(int(v) for v in by_status.values())
        return {
            "total": total,
            "completed": int(by_status.get("finished", 0)),
            "failed": int(by_status.get("failed", 0)),
            "in_progress": int(by_status.get("matching", 0)) + int(by_status.get("tailoring", 0)),
            "ready_to_tailor": int(by_status.get("matched", 0)),
            "week_start": start.date().isoformat(),
            "week_end": (end - timedelta(days=1)).date().isoformat(),
            "week_count": int(this_week or 0),
            "profiles": int(profiles or 0),
            "resumes": int(resumes or 0),
        }

    # -- AI connections -----------------------------------------------------------
    # Rows include ``key_ciphertext`` only for internal callers; the router
    # strips it and returns ``has_api_key`` instead.

    @staticmethod
    def _connection_to_dict(row: AIConnection) -> dict[str, Any]:
        return {
            "connection_id": row.connection_id,
            "name": row.name,
            "provider": row.provider,
            "model": row.model,
            "api_base": row.api_base,
            "reasoning_effort": row.reasoning_effort,
            "key_ciphertext": row.key_ciphertext,
            "is_default": row.is_default,
            "use_as_backup": row.use_as_backup,
            "position": row.position,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def list_connections_sync(self) -> list[dict[str, Any]]:
        """Read on the synchronous LLM path (``get_llm_config``)."""
        with self._sync() as session:
            rows = session.execute(select(AIConnection).order_by(AIConnection.position)).scalars()
            return [self._connection_to_dict(r) for r in rows]

    async def list_connections(self) -> list[dict[str, Any]]:
        async with self._session() as session:
            rows = (await session.execute(select(AIConnection).order_by(AIConnection.position))).scalars()
            return [self._connection_to_dict(r) for r in rows]

    async def get_connection(self, connection_id: str) -> dict[str, Any] | None:
        async with self._session() as session:
            row = await session.get(AIConnection, connection_id)
            return self._connection_to_dict(row) if row else None

    async def create_connection(self, values: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        async with self._write_session() as session:
            count = await session.scalar(select(func.count()).select_from(AIConnection)) or 0
            make_default = bool(values.pop("make_default", False)) or count == 0
            if make_default:
                await session.execute(update(AIConnection).values(is_default=False))
            row = AIConnection(
                connection_id=str(uuid4()),
                position=count,
                is_default=make_default,
                created_at=now,
                updated_at=now,
                **values,
            )
            session.add(row)
            await session.commit()
            return self._connection_to_dict(row)

    async def update_connection(self, connection_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        async with self._write_session() as session:
            row = await session.get(AIConnection, connection_id)
            if row is None:
                return None
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utcnow_iso()
            await session.commit()
            return self._connection_to_dict(row)

    async def set_default_connection(self, connection_id: str) -> bool:
        async with self._write_session() as session:
            if await session.get(AIConnection, connection_id) is None:
                return False
            await session.execute(update(AIConnection).values(is_default=False))
            await session.execute(
                update(AIConnection)
                .where(AIConnection.connection_id == connection_id)
                .values(is_default=True, updated_at=utcnow_iso())
            )
            await session.commit()
            return True

    async def reorder_connections(self, ordered_ids: list[str]) -> None:
        async with self._write_session() as session:
            rows = (await session.execute(select(AIConnection))).scalars().all()
            rank = {cid: i for i, cid in enumerate(ordered_ids)}
            ordered = sorted(rows, key=lambda r: (rank.get(r.connection_id, len(rank)), r.position))
            for position, row in enumerate(ordered):
                row.position = position
            await session.commit()

    async def delete_connection(self, connection_id: str) -> bool:
        """Delete; if it was the default, the next connection becomes default."""
        async with self._write_session() as session:
            row = await session.get(AIConnection, connection_id)
            if row is None:
                return False
            was_default = row.is_default
            await session.delete(row)
            await session.flush()
            remaining = (
                await session.execute(select(AIConnection).order_by(AIConnection.position))
            ).scalars().all()
            for i, other in enumerate(remaining):
                other.position = i
            if was_default and remaining:
                remaining[0].is_default = True
            await session.execute(
                update(Task).where(Task.connection_id == connection_id).values(connection_id=None)
            )
            await session.commit()
            return True

    # -- model usage (model-tier fallback) ---------------------------------------

    async def record_model_call(
        self, day: str, model: str, *, succeeded: bool, exhausted: bool = False
    ) -> None:
        async with self._write_session() as session:
            row = await session.get(ModelUsage, (day, model))
            if row is None:
                row = ModelUsage(day=day, model=model, calls=0, exhausted=False)
                session.add(row)
            if succeeded:
                row.calls += 1
            if exhausted:
                row.exhausted = True
            row.updated_at = utcnow_iso()
            await session.commit()

    async def get_model_usage(self, day: str) -> dict[str, dict[str, Any]]:
        async with self._session() as session:
            result = await session.execute(select(ModelUsage).where(ModelUsage.day == day))
            return {
                row.model: {"calls": row.calls, "exhausted": row.exhausted}
                for row in result.scalars()
            }

    # -- maintenance -------------------------------------------------------------

    async def reset_database(self) -> None:
        """Delete all profiles, resumes and tasks. AI connections are kept."""
        async with self._write_session() as session:
            await session.execute(delete(Task))
            await session.execute(delete(ProfileResume))
            await session.execute(delete(Profile))
            await session.commit()


db = Database()
