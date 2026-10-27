"""SQLAlchemy ORM models for LokiShift.

LokiShift is organised around three things:

* ``Profile``       - one target job title for the candidate (e.g. "Python
                      Developer"), with the candidate's details and work history.
* ``ProfileResume`` - the N resume versions (original DOCX files) kept under a
                      profile.
* ``Task``          - one job application: a JD matched against every resume in
                      the profile, then tailored in the background.

The facade in ``app/database.py`` converts ORM rows to plain dicts so the rest
of the app never sees ORM objects.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow_iso() -> str:
    """Current UTC time as an ISO-8601 string (stored as text, compared lexically)."""
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    """Declarative base shared by every table."""


class Profile(Base):
    __tablename__ = "profiles"

    profile_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    full_name: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str] = mapped_column(String, default="")
    phone: Mapped[str] = mapped_column(String, default="")
    linkedin: Mapped[str] = mapped_column(String, default="")
    location: Mapped[str] = mapped_column(String, default="")
    total_experience: Mapped[str] = mapped_column(String, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    experience: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String, default=utcnow_iso)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow_iso)


class ProfileResume(Base):
    """One resume version, kept as its original DOCX."""

    __tablename__ = "profile_resumes"

    resume_id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String, ForeignKey("profiles.profile_id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    docx: Mapped[bytes] = mapped_column(LargeBinary)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, default=utcnow_iso)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow_iso)


# Task lifecycle:
#   matching -> matched -> tailoring -> finished
#   any running state -> failed (retry puts it back to matching / tailoring)
TASK_STATUSES = ("matching", "matched", "tailoring", "finished", "failed")
RUNNING_STATUSES = ("matching", "tailoring")


class Task(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    # Not a foreign key: deleting a profile keeps its task history.
    profile_id: Mapped[str] = mapped_column(String, index=True)
    profile_title: Mapped[str] = mapped_column(String, default="")

    job_title: Mapped[str] = mapped_column(String)
    job_location: Mapped[str] = mapped_column(String, default="")
    vendor_company: Mapped[str] = mapped_column(String, default="")
    domain: Mapped[str] = mapped_column(String, default="")
    job_description: Mapped[str] = mapped_column(Text)
    recruiter_name: Mapped[str] = mapped_column(String, default="")
    recruiter_email: Mapped[str] = mapped_column(String, default="")
    vendor_name: Mapped[str] = mapped_column(String, default="")
    vendor_email: Mapped[str] = mapped_column(String, default="")
    ai_instructions: Mapped[str] = mapped_column(Text, default="")
    auto_tailor: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[str] = mapped_column(String, default="matching", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Matching: every resume in the profile, scored; best first.
    ranking: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    best_resume_id: Mapped[str | None] = mapped_column(String, nullable=True)
    match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # AI connection chosen for this task (None = use the default).
    connection_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Name/model of the connection that actually ran the last job.
    llm_used: Mapped[str | None] = mapped_column(String, nullable=True)

    # Tailoring output.
    tailored_resume_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tailored_docx: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    tailored_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    tailoring: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    tailored_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # False once the task reaches matched/finished/failed until the user sees it.
    seen: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[str] = mapped_column(String, default=utcnow_iso, index=True)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow_iso)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)


class ModelUsage(Base):
    """Per-model LLM calls for one provider quota day (model-tier fallback)."""

    __tablename__ = "model_usage"

    day: Mapped[str] = mapped_column(String, primary_key=True)
    model: Mapped[str] = mapped_column(String, primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    exhausted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow_iso)


class AIConnection(Base):
    """A saved AI setup: provider + model + its own encrypted key.

    Exactly one connection is the default (used unless a task picks another).
    Connections with ``use_as_backup`` are tried in ``position`` order when the
    chosen one fails for provider reasons (credit, quota, outage, bad key).
    """

    __tablename__ = "ai_connections"

    connection_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    api_base: Mapped[str | None] = mapped_column(String, nullable=True)
    reasoning_effort: Mapped[str | None] = mapped_column(String, nullable=True)
    # Fernet ciphertext; plaintext exists in memory only at call time.
    key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    use_as_backup: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String, default=utcnow_iso)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow_iso)
