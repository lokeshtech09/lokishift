"""Resume tasks: create (auto-match), tailor in the background, download."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.database import db
from app.connections import connection_chain
from app.llm import NOT_CONFIGURED_MESSAGE
from app.models import TASK_STATUSES
from app.routers._files import docx_response
from app.schemas import TailorRequest, TaskCreate
from app.services import worker
from app.services.reports import build_report

router = APIRouter(tags=["Tasks"])


def _ai_ready(connection_id: str | None) -> bool:
    """A usable connection exists for this task (its own, the default or a backup)."""
    return any(c.usable for c in connection_chain(connection_id))


async def _require_task(task_id: str) -> dict[str, Any]:
    task = await db.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/dashboard")
async def dashboard() -> dict[str, Any]:
    """Stat cards, weekly usage and unseen notifications in one call."""
    return {
        "stats": await db.task_stats(),
        "notifications": await db.unseen_tasks(),
        "queue_size": worker.queue_size(),
    }


@router.get("/reports")
async def reports(
    days: int = Query(default=90, ge=0, le=3650),
    tz_offset: int = Query(default=0, ge=-840, le=840, description="Viewer's UTC offset, minutes"),
) -> dict[str, Any]:
    """Trends and breakdowns for the last ``days`` days (0 = all time)."""
    tasks = await db.list_tasks(limit=100_000)
    return build_report(tasks, days, tz_offset_minutes=tz_offset)


@router.get("/tasks")
async def list_tasks(
    profile_id: str | None = None,
    status: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    created_from: datetime | None = Query(default=None, description="Inclusive, ISO 8601"),
    created_to: datetime | None = Query(default=None, description="Exclusive, ISO 8601"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    running = status == "running"
    if status and not running and status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"Unknown status: {status}")
    tasks = await db.list_tasks(
        profile_id=profile_id,
        status=None if running else status,
        search=q,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    if running:
        tasks = [t for t in tasks if t["status"] in ("matching", "tailoring")]
    return {"tasks": tasks}


@router.post("/tasks")
async def create_task(request: TaskCreate) -> dict[str, Any]:
    if not _ai_ready(request.connection_id):
        raise HTTPException(status_code=400, detail=NOT_CONFIGURED_MESSAGE)
    profile = await db.get_profile(request.profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    if not await db.list_resumes(request.profile_id):
        raise HTTPException(
            status_code=400,
            detail=f'Upload at least one resume to "{profile["title"]}" first.',
        )
    if request.connection_id and await db.get_connection(request.connection_id) is None:
        raise HTTPException(status_code=404, detail="AI connection not found")
    values = request.model_dump()
    values["job_description"] = values["job_description"].strip()
    values["profile_title"] = profile["title"]
    task = await db.create_task(values)
    await worker.enqueue(task["task_id"], "match")
    return task


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, Any]:
    return await _require_task(task_id)


@router.post("/tasks/{task_id}/tailor")
async def tailor_task(task_id: str, request: TailorRequest | None = None) -> dict[str, Any]:
    """Queue tailoring. Uses the best-matching resume unless ``resume_id`` is given."""
    task = await _require_task(task_id)
    if not _ai_ready(task.get("connection_id")):
        raise HTTPException(status_code=400, detail=NOT_CONFIGURED_MESSAGE)
    if task["status"] in ("matching", "tailoring"):
        raise HTTPException(status_code=409, detail="This task is already running.")
    if not task.get("best_resume_id"):
        raise HTTPException(status_code=409, detail="Matching has not finished for this task.")
    request = request or TailorRequest()
    resume_id = request.resume_id or task["best_resume_id"]
    resume = await db.get_resume(resume_id)
    if resume is None or resume["profile_id"] != task["profile_id"]:
        raise HTTPException(status_code=404, detail="Resume not found in this task's profile")
    values: dict[str, Any] = {
        "status": "tailoring",
        "error": None,
        "seen": True,
        "tailored_resume_id": resume_id,
    }
    if request.ai_instructions is not None:
        values["ai_instructions"] = request.ai_instructions
    updated = await db.update_task(task_id, values)
    await worker.enqueue(task_id, "tailor")
    return updated or task


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str) -> dict[str, Any]:
    """Re-run the step that failed (matching if never matched, else tailoring)."""
    task = await _require_task(task_id)
    if task["status"] in ("matching", "tailoring"):
        raise HTTPException(status_code=409, detail="This task is already running.")
    kind = "tailor" if task.get("best_resume_id") and task["status"] in ("failed", "finished") and task.get("tailored_resume_id") else "match"
    status = "tailoring" if kind == "tailor" else "matching"
    updated = await db.update_task(task_id, {"status": status, "error": None, "seen": True})
    await worker.enqueue(task_id, kind)
    return updated or task


@router.post("/tasks/{task_id}/rematch")
async def rematch_task(task_id: str) -> dict[str, Any]:
    """Score the profile's resumes again (e.g. after uploading a new one)."""
    task = await _require_task(task_id)
    if task["status"] in ("matching", "tailoring"):
        raise HTTPException(status_code=409, detail="This task is already running.")
    updated = await db.update_task(
        task_id, {"status": "matching", "error": None, "seen": True, "auto_tailor": False}
    )
    await worker.enqueue(task_id, "match")
    return updated or task


@router.get("/tasks/{task_id}/download")
async def download_task(task_id: str) -> Response:
    content, filename = await db.get_tailored_docx(task_id)
    if content is None:
        await _require_task(task_id)
        raise HTTPException(status_code=409, detail="This task has no tailored resume yet.")
    return docx_response(content, filename or "Tailored resume.docx")


@router.post("/tasks/seen")
async def mark_seen(task_ids: list[str] | None = None) -> dict[str, int]:
    """Mark notifications as seen (all of them when no ids are sent)."""
    return {"updated": await db.mark_seen(task_ids)}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str) -> dict[str, bool]:
    if not await db.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": True}
