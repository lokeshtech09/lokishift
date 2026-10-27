"""Tailoring: rewrite a DOCX resume toward a JD in one pass, no questions.

The LLM rewrites the summary, skills and bullets toward the JD and adds new
bullets for JD responsibilities the resume does not cover. Deterministic code
around it:

* ``jd_analysis`` extracts the JD's weighted priorities and what the resume
  already covers, which the prompt uses;
* edits to locked paragraphs, out-of-range indexes and runaway lengths are
  dropped;
* ``edit_guard`` polishes stock AI phrasing and records every line that
  introduces skills or tools the original resume did not mention, so the
  candidate can see (and prepare for) what was added from the JD.
"""

import logging
import re
from pathlib import Path
from typing import Any

from app.prompts.tailoring import TAILOR_PROMPT
from app.services.docx_editor import (
    MAX_EDIT_TEXT_CHARS,
    DocxParagraph,
    apply_edits,
    plain_text,
    read_paragraphs,
)
from app.services.edit_guard import AVOID_WORDS, find_unsupported_claims, polish_edit
from app.services.jd_analysis import JDAnalysis, analyze_jd, term_in_text
from app.services.matching import (
    _clip,
    _complete_json_tiered,
    _priorities_block,
    _str_list,
    score_text,
)

logger = logging.getLogger(__name__)

_JD_PROMPT_CHARS = 12_000
MAX_ADDITIONS = 12
# A rewritten paragraph may grow (skills lines gain tools), within limits.
_MAX_GROWTH_RATIO = 2.5
_MAX_GROWTH_CHARS = 400
_MAX_ADDITION_CHARS = 400


_CONTACT = re.compile(
    r"@|https?://|www\.|linkedin|github\.com|\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}", re.IGNORECASE
)
# "Client: ...", "Role: ...", "Duration: ..." lines carry employers, titles and dates.
_FACT_LABEL = re.compile(
    r"^\s*(name|e-?mail|phone|mobile|contact|address|linkedin|client|company|employer|"
    r"role|title|designation|position|duration|period|dates?|location|education|degree|"
    r"university|college|certifications?)\s*[:\-\u2013|]",
    re.IGNORECASE,
)
_YEAR = r"(19|20)\d{2}"
_DATE_RANGE = re.compile(
    rf"({_YEAR}|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?)\s*"
    rf"[-\u2013\u2014to]+\s*({_YEAR}|present|current|till date|now)",
    re.IGNORECASE,
)


def is_protected(p: DocxParagraph) -> bool:
    """Paragraphs the tailor must never change: contact info, employer/title/date
    lines and section headings, whatever the model returns."""
    text = p.text.strip()
    if not p.editable or not text:
        return True
    if _CONTACT.search(text) or _FACT_LABEL.match(text):
        return True
    if len(text) <= 160 and _DATE_RANGE.search(text):
        return True
    words = len(text.split())
    if words <= 6 and (text.endswith(":") or text.isupper() or "heading" in p.style.lower()):
        return True
    if p.index == 0 and words <= 6:  # the candidate's name at the top
        return True
    return False


def _format_paragraphs(paragraphs: list[DocxParagraph]) -> str:
    lines = []
    for p in paragraphs:
        flag = " LOCKED" if is_protected(p) else ""
        text = p.text.replace("\n", " / ").replace("\t", "  |  ")
        lines.append(f"[{p.index}] ({p.style}{flag}) {text}")
    return "\n".join(lines)


def _coverage_block(analysis: JDAnalysis, resume_text: str) -> str:
    terms = analysis.must_have + analysis.nice_to_have
    covered = [t for t in terms if term_in_text(t, resume_text)]
    missing = [t for t in terms if t not in covered]
    return (
        "JD skills the resume already shows (surface them prominently): "
        + (", ".join(covered) or "none detected")
        + "\nJD skills the resume is MISSING (work them into skills lines and new or "
        "rewritten bullets): "
        + (", ".join(missing) or "none")
    )


def _edit_fits(original: str, new_text: str) -> bool:
    if not new_text or new_text == " ".join(original.split()):
        return False
    if len(new_text) > MAX_EDIT_TEXT_CHARS:
        return False
    limit = max(len(original) * _MAX_GROWTH_RATIO, len(original) + _MAX_GROWTH_CHARS)
    return len(new_text) <= limit


def _safe_filename_part(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", value or "")
    return " ".join(cleaned.split())[:80]


def tailored_filename(
    original_filename: str, candidate: str, job_title: str, vendor: str
) -> str:
    stem = _safe_filename_part(candidate) or _safe_filename_part(Path(original_filename).stem)
    parts = [p for p in (stem or "Resume", _safe_filename_part(job_title), _safe_filename_part(vendor)) if p]
    return " - ".join(parts) + ".docx"


async def tailor_docx(
    *,
    docx: bytes,
    job_description: str,
    job_title: str,
    domain: str = "",
    instructions: str = "",
) -> dict[str, Any]:
    """Tailor ``docx`` to the JD and return the new bytes plus a change report."""
    paragraphs = read_paragraphs(docx)
    editable = {p.index: p for p in paragraphs if not is_protected(p)}
    if not editable:
        raise ValueError("This resume has no editable text paragraphs.")

    analysis = analyze_jd(job_description)
    resume_text = plain_text(paragraphs)

    instructions_block = ""
    if instructions and instructions.strip():
        instructions_block = (
            "\nEXTRA INSTRUCTIONS FROM THE CANDIDATE (follow them unless they conflict "
            f"with NEVER CHANGE):\n{instructions.strip()[:2000]}\n"
        )

    def validate(result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result.get("edits"), list):
            raise ValueError("edits must be a list")
        if not isinstance(result.get("additions", []), list):
            raise ValueError("additions must be a list")
        return result

    result, model = await _complete_json_tiered(
        "tailor",
        prompt=TAILOR_PROMPT.format(
            job_title=job_title or "(see JD)",
            domain=domain or "(see JD)",
            job_description=_clip(analysis.cleaned_text, _JD_PROMPT_CHARS),
            priorities=_priorities_block(analysis),
            coverage=_coverage_block(analysis, resume_text),
            paragraphs=_format_paragraphs(paragraphs),
            instructions_block=instructions_block,
            avoid_words=", ".join(AVOID_WORDS),
            max_additions=MAX_ADDITIONS,
        ),
        system_prompt=(
            "You are an expert resume writer who tailors resumes to job descriptions. "
            "You only return JSON."
        ),
        max_tokens=12_000,
        schema_type="diff",
        response_validator=validate,
    )

    # -- rewrites -------------------------------------------------------------
    edits: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in result.get("edits", []):
        if not isinstance(raw, dict):
            continue
        try:
            index = int(raw.get("index"))
        except (TypeError, ValueError):
            continue
        paragraph = editable.get(index)
        if paragraph is None or index in seen:
            continue
        new_text = " ".join(str(raw.get("new_text") or "").split())
        new_text, _ = polish_edit(paragraph.text, new_text, job_description)
        if not _edit_fits(paragraph.text, new_text):
            logger.info("Dropped out-of-bounds edit for paragraph %s", index)
            continue
        seen.add(index)
        edits.append(
            {
                "index": index,
                "original_text": paragraph.text,
                "new_text": new_text,
                "keywords": _str_list(raw.get("keywords"), 8),
                "added_from_jd": find_unsupported_claims(new_text, resume_text),
            }
        )
    edits.sort(key=lambda e: e["index"])

    # -- new bullets ----------------------------------------------------------
    additions: list[dict[str, Any]] = []
    for raw in result.get("additions", []) or []:
        if len(additions) >= MAX_ADDITIONS or not isinstance(raw, dict):
            continue
        try:
            after = int(raw.get("after"))
        except (TypeError, ValueError):
            continue
        anchor = editable.get(after)
        if anchor is None:
            continue
        text = " ".join(str(raw.get("text") or "").split())
        text, _ = polish_edit("", text, job_description)
        if not text or len(text) > _MAX_ADDITION_CHARS:
            continue
        additions.append(
            {
                "after": after,
                "anchor_text": anchor.text,
                "text": text,
                "keywords": _str_list(raw.get("keywords"), 8),
            }
        )

    if not edits and not additions:
        raise ValueError("The AI returned no usable changes for this resume.")

    new_docx = apply_edits(
        docx,
        {e["index"]: e["new_text"] for e in edits},
        [(a["after"], a["text"]) for a in additions],
    )
    new_text = plain_text(read_paragraphs(new_docx))
    before = score_text(job_description, resume_text)
    after = score_text(job_description, new_text)

    return {
        "docx": new_docx,
        "text": new_text,
        "report": {
            "summary": str(result.get("summary") or "").strip()[:600],
            "edits": edits,
            "additions": additions,
            "keyword_score_before": before["score"],
            "keyword_score_after": after["score"],
            "matched_after": after["matched"],
            "missing_after": after["missing"],
            "model": model,
        },
    }
