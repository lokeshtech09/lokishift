"""Profiles (one per target job title) and the resume versions under each."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.database import db
from app.routers._files import docx_response, read_docx_upload
from app.schemas import ProfileFields, ProfileUpdate
from app.services.docx_editor import plain_text

router = APIRouter(prefix="/profiles", tags=["Profiles"])

MAX_RESUMES_PER_PROFILE = 20



async def _require_profile(profile_id: str) -> dict[str, Any]:
    profile = await db.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


async def _require_resume(profile_id: str, resume_id: str, include_docx: bool = False) -> dict[str, Any]:
    resume = await db.get_resume(resume_id, include_docx=include_docx)
    if resume is None or resume["profile_id"] != profile_id:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume


def _public_resume(resume: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in resume.items() if k not in ("docx", "text")}


@router.get("")
async def list_profiles() -> dict[str, Any]:
    return {"profiles": await db.list_profiles()}


@router.post("")
async def create_profile(request: ProfileFields) -> dict[str, Any]:
    return await db.create_profile(request.model_dump())


@router.get("/{profile_id}")
async def get_profile(profile_id: str) -> dict[str, Any]:
    profile = await _require_profile(profile_id)
    profile["resumes"] = [_public_resume(r) for r in await db.list_resumes(profile_id)]
    return profile


@router.patch("/{profile_id}")
async def update_profile(profile_id: str, request: ProfileUpdate) -> dict[str, Any]:
    values = request.model_dump(exclude_unset=True)
    updated = await db.update_profile(profile_id, values)
    if updated is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return updated


@router.delete("/{profile_id}")
async def delete_profile(profile_id: str) -> dict[str, bool]:
    if not await db.delete_profile(profile_id):
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"deleted": True}


# -- resumes ---------------------------------------------------------------------


@router.post("/{profile_id}/resumes")
async def upload_resume(
    profile_id: str, file: UploadFile = File(...), name: str | None = Form(default=None)
) -> dict[str, Any]:
    await _require_profile(profile_id)
    if len(await db.list_resumes(profile_id)) >= MAX_RESUMES_PER_PROFILE:
        raise HTTPException(
            status_code=400,
            detail=f"A profile can hold {MAX_RESUMES_PER_PROFILE} resumes. Delete one first.",
        )
    content, paragraphs = await read_docx_upload(file)
    filename = Path(file.filename or "resume.docx").name
    display = (name or "").strip()[:80] or Path(filename).stem[:80]
    resume = await db.create_resume(profile_id, display, filename, content, plain_text(paragraphs))
    return _public_resume(resume)


@router.patch("/{profile_id}/resumes/{resume_id}")
async def update_resume(profile_id: str, resume_id: str, request: dict[str, Any]) -> dict[str, Any]:
    """Rename a resume (``name``) or move it to another profile (``profile_id``)."""
    await _require_resume(profile_id, resume_id)
    values: dict[str, Any] = {}
    if isinstance(request.get("name"), str) and request["name"].strip():
        values["name"] = request["name"].strip()[:80]
    target = request.get("profile_id")
    if isinstance(target, str) and target and target != profile_id:
        await _require_profile(target)
        values["profile_id"] = target
    if not values:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    updated = await db.update_resume(resume_id, values)
    assert updated is not None
    return _public_resume(updated)


@router.put("/{profile_id}/resumes/{resume_id}/file")
async def replace_resume_file(
    profile_id: str, resume_id: str, file: UploadFile = File(...)
) -> dict[str, Any]:
    await _require_resume(profile_id, resume_id)
    content, paragraphs = await read_docx_upload(file)
    updated = await db.update_resume(
        resume_id,
        {
            "docx": content,
            "text": plain_text(paragraphs),
            "filename": Path(file.filename or "resume.docx").name,
        },
    )
    assert updated is not None
    return _public_resume(updated)


@router.get("/{profile_id}/resumes/{resume_id}/text")
async def resume_text(profile_id: str, resume_id: str) -> dict[str, str]:
    resume = await _require_resume(profile_id, resume_id)
    return {"text": resume["text"]}


@router.get("/{profile_id}/resumes/{resume_id}/download")
async def download_resume(profile_id: str, resume_id: str) -> Response:
    resume = await _require_resume(profile_id, resume_id, include_docx=True)
    return docx_response(resume["docx"], resume["filename"])


@router.delete("/{profile_id}/resumes/{resume_id}")
async def delete_resume(profile_id: str, resume_id: str) -> dict[str, bool]:
    await _require_resume(profile_id, resume_id)
    await db.delete_resume(resume_id)
    return {"deleted": True}
