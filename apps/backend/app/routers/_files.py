"""Shared helpers for DOCX uploads and downloads."""

from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, UploadFile
from fastapi.responses import Response

from app.services.docx_editor import (
    MAX_UPLOAD_BYTES,
    DocxEditError,
    DocxParagraph,
    read_paragraphs,
    validate_docx_bytes,
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# Browsers sometimes send a generic type for .docx; the bytes are validated anyway.
_ACCEPTED_TYPES = {DOCX_MIME, "application/octet-stream", "", None}
_CHUNK = 256 * 1024


async def read_docx_upload(file: UploadFile) -> tuple[bytes, list[DocxParagraph]]:
    if Path(file.filename or "").suffix.lower() != ".docx":
        raise HTTPException(status_code=400, detail="Only .docx files are supported.")
    if file.content_type not in _ACCEPTED_TYPES:
        raise HTTPException(status_code=400, detail="Only .docx files are supported.")
    content = bytearray()
    while chunk := await file.read(_CHUNK):
        content.extend(chunk)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large (6MB maximum).")
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")
    try:
        validate_docx_bytes(bytes(content))
        paragraphs = read_paragraphs(bytes(content))
    except DocxEditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not paragraphs:
        raise HTTPException(status_code=422, detail="The document contains no text.")
    return bytes(content), paragraphs


def docx_response(content: bytes, filename: str) -> Response:
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "") or "resume.docx"
    return Response(
        content=content,
        media_type=DOCX_MIME,
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
            )
        },
    )
