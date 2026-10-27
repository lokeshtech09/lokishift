"""In-process background worker for LokiShift tasks.

The ``tasks`` table is the queue: a task's ``status`` says what it is waiting
for (``matching`` or ``tailoring``). Jobs are also pushed onto an in-memory
``asyncio.Queue`` so they start immediately; on startup every task left in a
running status (the server stopped mid-job) is queued again.

A job never raises out of the worker: any failure is written to the task as
``status="failed"`` with a readable ``error``, and the task is marked unseen
so the dashboard notifies the user.
"""

import asyncio
import logging
from typing import Any, Literal

from app.ai_budget import operation_budget
from app.config import settings
from app.database import db
from app.connections import ActiveConnection, connection_chain, use_connection
from app.llm import NOT_CONFIGURED_MESSAGE
from app.models import utcnow_iso
from app.services.docx_editor import DocxEditError
from app.services.matching import (
    ProviderBillingError,
    ProviderOverloaded,
    ProviderRateLimited,
    rank_resumes,
)
from app.services.tailoring import tailor_docx, tailored_filename

logger = logging.getLogger(__name__)

JobKind = Literal["match", "tailor"]

_queue: asyncio.Queue[tuple[str, JobKind]] | None = None
_workers: list[asyncio.Task[None]] = []
_queued: set[str] = set()


class JobError(RuntimeError):
    """A failure with a message that is safe and useful to show the user."""


class ProviderFailure(RuntimeError):
    """The AI provider could not do the job; another connection might."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _provider_message(exc: BaseException) -> str | None:
    if isinstance(exc, ProviderRateLimited):
        if exc.daily:
            return (
                "Every AI model has used up today's quota. Retry the task after the "
                "quota resets (midnight Pacific for Gemini)."
            )
        return "The AI provider kept rate-limiting the request. Retry in a few minutes."
    if isinstance(exc, ProviderOverloaded):
        return "The AI models are overloaded right now. Retry in a few minutes."
    if isinstance(exc, ProviderBillingError):
        return "The AI provider account has no credit left. Add credit or use another connection in Settings."
    if isinstance(exc, TimeoutError):
        return "The AI took too long to answer. Retry the task."
    text = str(exc).lower()
    if "connection error" in text or "connecterror" in text or "name resolution" in text:
        return (
            "Could not reach the AI provider. Check your internet connection and the "
            "connection's base URL in Settings, then retry."
        )
    if "authentication" in text or "invalid api key" in text or "incorrect api key" in text:
        return "The AI provider rejected the API key. Update it in Settings, then retry."
    if "notfound" in text.replace(" ", "") or "does not exist" in text or "model_not_found" in text:
        return "The AI provider doesn't offer this model for your key. Check the model name in Settings."
    return None


# -- jobs ------------------------------------------------------------------------


async def _run_match(task: dict[str, Any], final: bool = True) -> dict[str, Any]:
    resumes = await db.list_resumes(task["profile_id"])
    if not resumes:
        raise JobError(
            f'The profile "{task["profile_title"]}" has no resumes. Upload one, then retry.'
        )
    ranking = await rank_resumes(task["job_description"], resumes)
    if ranking.get("model") is None and ranking.get("warning") and not final:
        # The AI failed and matching fell back to keyword scores; a backup
        # connection can still give real AI scores.
        raise ProviderFailure(ranking["warning"])
    best_id = ranking["recommended_resume_id"]
    best = next(r for r in ranking["rankings"] if r["resume_id"] == best_id)
    return {
        "ranking": ranking,
        "best_resume_id": best_id,
        "match_score": best["score"],
    }


async def _run_tailor(task: dict[str, Any]) -> dict[str, Any]:
    resume_id = task.get("tailored_resume_id") or task.get("best_resume_id")
    if not resume_id:
        raise JobError("No resume was selected for tailoring. Retry matching first.")
    resume = await db.get_resume(resume_id, include_docx=True)
    if resume is None:
        raise JobError("The selected resume was deleted. Pick another resume and tailor again.")
    profile = await db.get_profile(task["profile_id"]) or {}

    try:
        result = await tailor_docx(
            docx=resume["docx"],
            job_description=task["job_description"],
            job_title=task["job_title"],
            domain=task.get("domain") or "",
            instructions=task.get("ai_instructions") or "",
        )
    except (DocxEditError, ValueError) as exc:
        raise JobError(str(exc)) from exc

    # Score the tailored resume the same way the original was scored.
    rescored = await rank_resumes(
        task["job_description"],
        [{"resume_id": "tailored", "name": "Tailored", "text": result["text"]}],
    )
    score = rescored["rankings"][0]["score"]

    report = result["report"]
    report["resume_id"] = resume["resume_id"]
    report["resume_name"] = resume["name"]
    report["score_before"] = task.get("match_score")
    report["score_after"] = score
    report["score_warning"] = rescored.get("warning")
    return {
        "tailored_resume_id": resume["resume_id"],
        "tailored_docx": result["docx"],
        "tailored_filename": tailored_filename(
            resume["filename"],
            profile.get("full_name", ""),
            task["job_title"],
            task.get("vendor_company", ""),
        ),
        "tailoring": report,
        "tailored_score": score,
    }


async def _run_on_connection(task: dict[str, Any], kind: JobKind, final: bool) -> dict[str, Any]:
    """One connection: wait out short rate limits, map provider errors."""
    attempts = settings.job_rate_limit_retries + 1
    for attempt in range(attempts):
        try:
            async with operation_budget(settings.job_timeout_seconds):
                if kind == "match":
                    return await _run_match(task, final)
                return await _run_tailor(task)
        except (JobError, ProviderFailure):
            raise
        except ProviderRateLimited as exc:
            if exc.daily or attempt == attempts - 1:
                raise ProviderFailure(_provider_message(exc) or str(exc)) from exc
            wait = min(max(exc.retry_after, 10.0), 120.0)
            logger.info("Task %s rate limited; retrying in %.0fs", task["task_id"], wait)
            await asyncio.sleep(wait)
        except Exception as exc:
            message = _provider_message(exc)
            if message is None:
                raise
            raise ProviderFailure(message) from exc
    raise ProviderFailure("The AI provider kept rate-limiting the request.")


async def _process(task_id: str, kind: JobKind) -> None:
    task = await db.get_task(task_id)
    if task is None:
        return
    expected = "matching" if kind == "match" else "tailoring"
    if task["status"] != expected:
        return  # deleted, retried or superseded meanwhile

    chain: list[ActiveConnection] = [c for c in connection_chain(task.get("connection_id")) if c.usable]
    if not chain:
        await _fail(task_id, NOT_CONFIGURED_MESSAGE)
        return

    failures: list[str] = []
    values: dict[str, Any] | None = None
    used: ActiveConnection | None = None
    for index, connection in enumerate(chain):
        try:
            with use_connection(connection):
                values = await _run_on_connection(task, kind, final=index == len(chain) - 1)
            used = connection
            break
        except JobError as exc:
            await _fail(task_id, str(exc))
            return
        except ProviderFailure as exc:
            failures.append(f"{connection.name}: {exc.message}")
            if index < len(chain) - 1:
                logger.warning(
                    "Task %s: %s failed (%s); trying backup %s",
                    task_id, connection.name, exc.message, chain[index + 1].name,
                )
        except Exception:  # noqa: BLE001 - a bug, not a provider problem
            logger.exception("Task %s %s job failed", task_id, kind)
            await _fail(
                task_id,
                f"{'Matching' if kind == 'match' else 'Tailoring'} failed unexpectedly. Retry the task.",
            )
            return

    if values is None or used is None:
        if len(failures) == 1:
            await _fail(task_id, failures[0].split(": ", 1)[1])
        else:
            await _fail(task_id, "Every AI connection failed. " + " · ".join(failures))
        return

    values["llm_used"] = used.label
    note = {"connection": used.label, "backup_used": bool(failures), "failed_connections": failures}
    if kind == "match":
        values["ranking"] = {**values["ranking"], **note}
    else:
        values["tailoring"] = {**values["tailoring"], **note}

    # The user may have deleted the task while the job ran.
    current = await db.get_task(task_id)
    if current is None or current["status"] != expected:
        return

    if kind == "match":
        auto = bool(current.get("auto_tailor"))
        values.update(status="tailoring" if auto else "matched", error=None, seen=auto)
        await db.update_task(task_id, values)
        if auto:
            await enqueue(task_id, "tailor")
    else:
        values.update(status="finished", error=None, seen=False, finished_at=utcnow_iso())
        await db.update_task(task_id, values)
    logger.info("Task %s %s job done on %s", task_id, kind, used.label)


async def _fail(task_id: str, message: str) -> None:
    logger.warning("Task %s failed: %s", task_id, message)
    await db.update_task(
        task_id,
        {"status": "failed", "error": message, "seen": False, "finished_at": utcnow_iso()},
    )


# -- queue -----------------------------------------------------------------------


async def _worker_loop(number: int) -> None:
    assert _queue is not None
    while True:
        task_id, kind = await _queue.get()
        _queued.discard(f"{task_id}:{kind}")
        try:
            await _process(task_id, kind)
        except Exception:  # noqa: BLE001 - keep the worker alive
            logger.exception("Worker %s crashed on task %s", number, task_id)
        finally:
            _queue.task_done()


async def enqueue(task_id: str, kind: JobKind) -> None:
    """Queue a job (no-op if the same job is already waiting)."""
    if _queue is None:
        raise RuntimeError("Worker not started")
    key = f"{task_id}:{kind}"
    if key in _queued:
        return
    _queued.add(key)
    await _queue.put((task_id, kind))


async def start() -> None:
    """Start the worker pool and re-queue jobs a restart interrupted."""
    global _queue
    if _queue is not None:
        return
    _queue = asyncio.Queue()
    for number in range(settings.worker_concurrency):
        _workers.append(asyncio.create_task(_worker_loop(number), name=f"lokishift-worker-{number}"))
    for task_id, status in await db.running_tasks():
        await enqueue(task_id, "match" if status == "matching" else "tailor")
    logger.info("Worker started (%d concurrent jobs)", settings.worker_concurrency)


async def stop() -> None:
    global _queue
    for worker in _workers:
        worker.cancel()
    await asyncio.gather(*_workers, return_exceptions=True)
    _workers.clear()
    _queued.clear()
    _queue = None


def queue_size() -> int:
    return _queue.qsize() if _queue is not None else 0
