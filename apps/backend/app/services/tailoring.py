"""Tailoring: rewrite a DOCX resume toward a JD without making it longer.

The rules, all enforced in code (the prompt only explains them to the LLM):

* **Same length.** Each rewritten paragraph stays within a small allowance
  over its original length, and the whole document may not grow past
  ``_MAX_TOTAL_GROWTH``. Over-budget rewrites are dropped.
* **No net new bullets.** A new bullet is only allowed as a *swap* inside one
  of the three most recent roles: the role's weakest bullet is removed and the
  new one, no longer than it, takes its place.
* **Key skills in the recent roles.** Every JD must-have skill should appear in
  the bullets of ROLE 1 to ROLE 3 (the first three clients in the document).
* **ATS score >= 95.** The deterministic, importance-weighted keyword coverage
  (``weighted_match``) is checked after the first pass; if it is below
  ``ATS_TARGET`` or a key skill is missing from the recent roles, up to
  ``MAX_REPAIR_PASSES`` focused repair passes run, then a last deterministic
  step adds missing skills to a skills line within its allowance. The report
  says whether the target was met and what is still missing.

``edit_guard`` still polishes stock AI phrasing and flags every line that
introduces skills or tools the original resume did not mention.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.prompts.tailoring import REPAIR_PROMPT, REQUESTS_PROMPT, TAILOR_PROMPT
from app.services.docx_editor import (
    MAX_EDIT_TEXT_CHARS,
    DocxParagraph,
    apply_edits,
    plain_text,
    read_paragraphs,
)
from app.services.edit_guard import AVOID_WORDS, find_unsupported_claims, polish_edit
from app.services.jd_analysis import JDAnalysis, analyze_jd, find_skills, term_in_text, weighted_match
from app.services.matching import (
    _clip,
    _complete_json_tiered,
    _priorities_block,
    _str_list,
)

logger = logging.getLogger(__name__)

_JD_PROMPT_CHARS = 12_000

ATS_TARGET = 95
TOP_ROLES = 3
MAX_REPAIR_PASSES = 2

# Length allowances. A bullet may gain a few words for a JD term; a summary or
# skills line a little more. The document as a whole may grow at most 2%.
_BULLET_GROWTH_RATIO, _BULLET_GROWTH_CHARS = 1.10, 15
_OTHER_GROWTH_RATIO, _OTHER_GROWTH_CHARS = 1.15, 40
_SWAP_GROWTH_RATIO, _SWAP_GROWTH_CHARS = 1.05, 10
_MAX_TOTAL_GROWTH, _MAX_TOTAL_GROWTH_CHARS = 1.02, 40  # whichever is bigger: under half a line

# Kept for the report shape: "additions" now only ever holds swap-ins.
MAX_ADDITIONS = TOP_ROLES


_CONTACT = re.compile(
    r"@|https?://|www\.|linkedin|github\.com|\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}", re.IGNORECASE
)
# "Client: ...", "Role: ...", "Duration: ..." lines carry employers, titles and dates.
_FACT_LABEL = re.compile(
    r"^\s*(name|e-?mail|phone|mobile|contact|address|linkedin|client|company|employer|"
    r"role|title|designation|position|duration|period|dates?|location|education|degree|"
    r"university|college|certifications?)\s*[:\-–|]",
    re.IGNORECASE,
)
_YEAR = r"(19|20)\d{2}"
_DATE_RANGE = re.compile(
    rf"({_YEAR}|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?)\s*"
    rf"[-–—to]+\s*({_YEAR}|present|current|till date|now)",
    re.IGNORECASE,
)
# Locked lines that open a new role (client/company/title/date lines).
_ROLE_LABEL = re.compile(
    r"^\s*(client|company|employer|organi[sz]ation|role|title|designation|position|"
    r"duration|period|dates?)\s*[:\-–|]",
    re.IGNORECASE,
)
# Headings that close the experience section (anything after is not a role).
_SECTION_END = re.compile(
    r"education|academic|certific|award|achievement|publication|reference|declaration|"
    r"personal|languages known|hobbies|interests|training|skills|summary|profile",
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


# -- document structure --------------------------------------------------------


@dataclass
class Layout:
    """Which editable paragraph belongs to which role (1 = most recent)."""

    role_of: dict[int, int] = field(default_factory=dict)
    role_names: dict[int, str] = field(default_factory=dict)

    def bullets(self, role: int) -> list[int]:
        return [i for i, r in self.role_of.items() if r == role]

    @property
    def top_roles(self) -> list[int]:
        return [r for r in sorted(set(self.role_of.values())) if r <= TOP_ROLES]

    def in_top(self, index: int) -> bool:
        return 0 < self.role_of.get(index, 0) <= TOP_ROLES


_EDUCATION = re.compile(
    r"\b(degree|university|college|school|institute|bachelor|master|b\.?\s?tech|m\.?\s?tech|"
    r"b\.?\s?e\b|m\.?\s?s\b|mba|ph\.?d|gpa|cgpa)\b",
    re.IGNORECASE,
)


def _is_role_header(p: DocxParagraph) -> bool:
    text = p.text.strip()
    if _EDUCATION.search(text):
        return False
    return bool(_ROLE_LABEL.match(text) or (len(text) <= 160 and _DATE_RANGE.search(text)))


def _is_section_heading(p: DocxParagraph) -> bool:
    text = p.text.strip()
    words = len(text.split())
    return words <= 6 and (text.endswith(":") or text.isupper() or "heading" in p.style.lower())


def detect_roles(paragraphs: list[DocxParagraph]) -> Layout:
    """Group editable paragraphs under the role (client) they belong to.

    A role starts at a locked client/title/date line; consecutive such lines
    ("Client:", "Role:", "Duration:") belong to the same role. A heading such as
    "Education" ends the experience section. Resumes list the most recent role
    first, so role 1 is the most recent client.
    """
    layout = Layout()
    role = 0
    has_bullets = False
    in_experience = False
    for p in paragraphs:
        if is_protected(p):
            if _is_role_header(p):
                line = " ".join(p.text.split())
                if role == 0 or has_bullets or not in_experience:
                    role += 1
                    has_bullets = False
                    layout.role_names[role] = line[:120]
                elif len(layout.role_names[role]) < 200:
                    layout.role_names[role] = f"{layout.role_names[role]} · {line}"[:240]
                in_experience = True
            elif _is_section_heading(p) and _SECTION_END.search(p.text):
                in_experience = False
            continue
        if in_experience and role:
            layout.role_of[p.index] = role
            has_bullets = True
    return layout


# -- length rules ----------------------------------------------------------------


def _limit(original: str, ratio: float, extra: int) -> int:
    n = len(" ".join(original.split()))
    return int(max(n * ratio, n + extra))


def max_chars(p: DocxParagraph, layout: Layout) -> int:
    if p.index in layout.role_of:
        return _limit(p.text, _BULLET_GROWTH_RATIO, _BULLET_GROWTH_CHARS)
    return _limit(p.text, _OTHER_GROWTH_RATIO, _OTHER_GROWTH_CHARS)


def _edit_fits(p: DocxParagraph, new_text: str, layout: Layout) -> bool:
    if not new_text or new_text == " ".join(p.text.split()):
        return False
    return len(new_text) <= min(max_chars(p, layout), MAX_EDIT_TEXT_CHARS)


def total_budget(original_length: int) -> int:
    return int(max(original_length * _MAX_TOTAL_GROWTH, original_length + _MAX_TOTAL_GROWTH_CHARS))


def _body_length(texts: list[str]) -> int:
    return sum(len(" ".join(t.split())) for t in texts)


# -- tailoring state -------------------------------------------------------------


@dataclass
class Draft:
    """The tailored resume in memory: rewrites plus swaps over the original."""

    paragraphs: list[DocxParagraph]
    layout: Layout
    edits: dict[int, dict[str, Any]] = field(default_factory=dict)
    swaps: list[dict[str, Any]] = field(default_factory=list)
    deletions: dict[int, dict[str, Any]] = field(default_factory=dict)  # removed, nothing in their place

    @property
    def removed(self) -> set[int]:
        return {s["remove"] for s in self.swaps} | set(self.deletions)

    @property
    def paragraphs_by_index(self) -> dict[int, DocxParagraph]:
        return {p.index: p for p in self.paragraphs}

    def current(self, index: int, original: str) -> str:
        return self.edits[index]["new_text"] if index in self.edits else original

    def texts(self) -> list[str]:
        """Paragraph texts in document order, as the tailored resume reads."""
        added: dict[int, list[str]] = {}
        for s in self.swaps:
            added.setdefault(s["after"], []).append(s["text"])
        out: list[str] = []
        for p in self.paragraphs:
            if p.index not in self.removed:
                out.append(self.edits[p.index]["new_text"] if p.index in self.edits else p.text)
            out.extend(added.get(p.index, []))
        return out

    def text(self) -> str:
        return "\n".join(self.texts())

    def top_roles_text(self) -> str:
        parts = []
        for p in self.paragraphs:
            if not self.layout.in_top(p.index):
                continue
            if p.index not in self.removed:
                parts.append(self.edits[p.index]["new_text"] if p.index in self.edits else p.text)
        parts += [s["text"] for s in self.swaps if 0 < s["role"] <= TOP_ROLES]
        return "\n".join(parts)


# -- the candidate's explicit requests ---------------------------------------------
# "add 10 points on Kafka in Delta Bank", "rewrite all points in client 2 to
# mention Azure", "remove the Excel points from Old Mutual". There is no cap on
# the number: the only limit is how many bullets the role has, because every
# added point replaces one of them.

ACTIONS = ("add", "rewrite", "remove")


def _validate_requests(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result.get("requests"), list):
        raise ValueError("requests must be a list")
    return result


def clean_requests(raw: Any, layout: Layout) -> list[dict[str, Any]]:
    """Keep well-formed requests that name roles this resume actually has."""
    requests: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "add").strip().lower()
        if action not in ACTIONS:
            continue
        skill = " ".join(str(item.get("skill") or "").split())[:60]
        raw_count = item.get("count")
        if isinstance(raw_count, str) and raw_count.strip().lower() in ("all", "every", "*"):
            count: int | str = "all"
        elif raw_count in (None, ""):
            count = "all" if action == "remove" and skill else 2
        else:
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                continue
            if count <= 0:
                continue
        roles = []
        for r in item.get("roles") or [1]:
            try:
                r = int(r)
            except (TypeError, ValueError):
                continue
            if layout.bullets(r) and r not in roles:
                roles.append(r)
        if roles and (skill or action == "remove"):
            requests.append({"action": action, "skill": skill, "count": count, "roles": roles})
    return requests


async def parse_requests(instructions: str, layout: Layout, system_prompt: str) -> list[dict[str, Any]]:
    """Turn free-text instructions into ``[{action, skill, count, roles}]`` requests."""
    if not instructions.strip() or not layout.role_names:
        return []
    roles = "\n".join(f"ROLE {r}: {name}" for r, name in sorted(layout.role_names.items()))
    try:
        result, _ = await _complete_json_tiered(
            "tailor",
            prompt=REQUESTS_PROMPT.format(roles=roles, instructions=instructions.strip()[:2000]),
            system_prompt=system_prompt,
            max_tokens=2_000,
            schema_type="diff",
            response_validator=_validate_requests,
        )
    except Exception as exc:  # instructions still reach the tailoring prompt as text
        logger.warning("Could not read bullet requests from the instructions: %s", exc)
        return []
    return clean_requests(result.get("requests"), layout)


def _mentions(skill: str, text: str) -> bool:
    if not skill:
        return True
    return term_in_text(skill.lower(), text) or skill.lower() in text.lower()


def _target(req: dict[str, Any], role: int, draft: Draft) -> int:
    """How many bullets a request asks for in ``role``, capped by what the role has."""
    bullets = draft.layout.bullets(role)
    if req["action"] == "remove" and req["skill"]:
        available = sum(1 for i in bullets if _mentions(req["skill"], draft.paragraphs_by_index[i].text))
    else:
        available = len(bullets)
    return available if req["count"] == "all" else min(int(req["count"]), available)


def _done(req: dict[str, Any], n: int, role: int, draft: Draft) -> int:
    if req["action"] == "add":
        return sum(1 for s in draft.swaps if s.get("request") == n and s["role"] == role)
    if req["action"] == "remove":
        return sum(1 for d in draft.deletions.values() if d["request"] == n and d["role"] == role)
    # rewrite: original bullets of the role that now mention the skill
    return sum(
        1
        for i in draft.layout.bullets(role)
        if i not in draft.removed and _mentions(req["skill"], draft.current(i, draft.paragraphs_by_index[i].text))
    )


def request_status(draft: Draft, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For every (request, role): how many of the asked-for bullets are done."""
    status = []
    for n, req in enumerate(requests, start=1):
        for role in req["roles"]:
            status.append({
                "request": n,
                "action": req["action"],
                "skill": req["skill"],
                "role": role,
                "role_name": draft.layout.role_names.get(role, f"Role {role}"),
                "requested": _target(req, role, draft),
                "asked": req["count"],
                "done": min(_done(req, n, role, draft), _target(req, role, draft)),
            })
    return status


def _describe(action: str, count: Any, skill: str) -> str:
    n = "all" if count == "all" else str(count)
    if action == "add":
        return f"add {n} new bullet(s) about {skill}"
    if action == "rewrite":
        return f"rewrite {n} existing bullet(s) so each mentions {skill}"
    return f"remove {n} bullet(s)" + (f" about {skill}" if skill else "")


def _requests_block(requests: list[dict[str, Any]], layout: Layout) -> str:
    if not requests:
        return ""
    lines = ["CANDIDATE'S REQUESTS (must be done; see step 6):"]
    for n, req in enumerate(requests, start=1):
        where = "; ".join(f"ROLE {r} ({layout.role_names.get(r, '')[:60]})" for r in req["roles"])
        lines.append(f"Request {n} ({req['action']}): {_describe(req['action'], req['count'], req['skill'])} in EACH of: {where}")
    return "\n".join(lines) + "\n"


def _open_requests_block(status: list[dict[str, Any]]) -> str:
    lines = []
    for s in status:
        left = s["requested"] - s["done"]
        if left <= 0:
            continue
        if s["action"] == "add":
            what = f"add {left} more bullet(s) about {s['skill']}"
        elif s["action"] == "rewrite":
            what = f"rewrite {left} more existing bullet(s) so each mentions {s['skill']}"
        else:
            what = f"remove {left} more bullet(s)" + (f" about {s['skill']}" if s["skill"] else "")
        lines.append(f"Request {s['request']} ({s['action']}): {what} in ROLE {s['role']} ({s['role_name'][:60]})")
    return "\n".join(lines) or "none"


def key_skills(analysis: JDAnalysis) -> list[str]:
    return analysis.must_have or analysis.nice_to_have[:8]


def _missing_terms_block(analysis: JDAnalysis, missing: list[str]) -> str:
    if not missing:
        return "none"
    total = sum(analysis.weights.values()) or 1
    return ", ".join(f"{t} ({100 * analysis.weights[t] / total:.0f}%)" for t in missing)


def _format_paragraphs(draft: Draft) -> str:
    lines = []
    for p in draft.paragraphs:
        if p.index in draft.removed:
            continue
        text = draft.edits[p.index]["new_text"] if p.index in draft.edits else p.text
        text = text.replace("\n", " / ").replace("\t", "  |  ")
        if is_protected(p):
            lines.append(f"[{p.index}] ({p.style} | LOCKED) {text}")
            continue
        role = draft.layout.role_of.get(p.index)
        where = f"ROLE {role}" if role else "not in a role"
        lines.append(
            f"[{p.index}] ({p.style} | {where} | {len(' '.join(text.split()))} chars, "
            f"max {max_chars(p, draft.layout)}) {text}"
        )
        for s in draft.swaps:
            if s["after"] == p.index:
                lines.append(f"[new] (new bullet in ROLE {s['role']} | LOCKED) {s['text']}")
    return "\n".join(lines)


def _check(draft: Draft, analysis: JDAnalysis) -> dict[str, Any]:
    score = weighted_match(analysis, draft.text())
    top_text = draft.top_roles_text()
    missing_key = [s for s in key_skills(analysis) if not term_in_text(s, top_text)] if draft.layout.top_roles else []
    return {"score": score["score"], "matched": score["matched"], "missing": score["missing"], "missing_key": missing_key}


def _accept_edits(
    draft: Draft,
    raw_edits: Any,
    editable: dict[int, DocxParagraph],
    job_description: str,
    resume_text: str,
    requests: list[dict[str, Any]] | None = None,
) -> int:
    """Validate the model's rewrites and fold them into ``draft``; return how many."""
    accepted = 0
    seen: set[int] = set()
    for raw in raw_edits if isinstance(raw_edits, list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            index = int(raw.get("index"))
        except (TypeError, ValueError):
            continue
        paragraph = editable.get(index)
        if paragraph is None or index in seen or index in draft.removed:
            continue
        new_text = " ".join(str(raw.get("new_text") or "").split())
        new_text, _ = polish_edit(paragraph.text, new_text, job_description)
        request = _request_number(raw, requests or [], "rewrite")
        role = draft.layout.role_of.get(index)
        if request:
            req = (requests or [])[request - 1]
            if role not in req["roles"] or not _mentions(req["skill"], new_text):
                request = 0
        instruction = bool(raw.get("instruction"))  # carries out the candidate's free-text instructions
        if request and role is not None:
            fits = bool(new_text) and len(new_text) <= min(_requested_limit(draft, paragraph, role, editable), MAX_EDIT_TEXT_CHARS)
        elif instruction:
            fits = bool(new_text) and new_text != " ".join(paragraph.text.split()) and len(new_text) <= MAX_EDIT_TEXT_CHARS
        else:
            fits = _edit_fits(paragraph, new_text, draft.layout)
        if not fits:
            logger.info("Dropped over-length edit for paragraph %s", index)
            continue
        seen.add(index)
        previous = draft.edits.get(index, {})
        draft.edits[index] = {
            "index": index,
            "original_text": paragraph.text,
            "new_text": new_text,
            "keywords": sorted(set(previous.get("keywords", [])) | set(_str_list(raw.get("keywords"), 8))),
            "added_from_jd": find_unsupported_claims(new_text, resume_text),
            "request": request or previous.get("request"),
            "instruction": instruction or bool(previous.get("instruction")),
        }
        accepted += 1
    return accepted


def _request_number(raw: dict[str, Any], requests: list[dict[str, Any]], action: str) -> int:
    try:
        n = int(raw.get("request") or 0)
    except (TypeError, ValueError):
        return 0
    return n if 0 < n <= len(requests) and requests[n - 1]["action"] == action else 0


def _accept_removals(
    draft: Draft,
    raw_removals: Any,
    editable: dict[int, DocxParagraph],
    requests: list[dict[str, Any]],
) -> None:
    """Bullets the candidate asked to delete ("remove the Excel points")."""
    for raw in raw_removals if isinstance(raw_removals, list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            index = int(raw.get("index"))
        except (TypeError, ValueError):
            continue
        request = _request_number(raw, requests, "remove")
        role = draft.layout.role_of.get(index)
        if not request or index not in editable or index in draft.removed or role is None:
            continue
        req = requests[request - 1]
        if role not in req["roles"] or not _mentions(req["skill"], editable[index].text):
            continue
        if _done(req, request, role, draft) >= _target(req, role, draft):
            continue
        draft.edits.pop(index, None)
        draft.deletions[index] = {"index": index, "text": editable[index].text, "role": role, "request": request}


def _requested_limit(draft: Draft, removed: DocxParagraph, role: int, editable: dict[int, DocxParagraph]) -> int:
    """A requested bullet may be as long as the bullet it replaces, or the role's
    average bullet, whichever is longer; the document-wide budget still applies."""
    lengths = [len(" ".join(editable[i].text.split())) for i in draft.layout.bullets(role) if i in editable]
    average = sum(lengths) / len(lengths) if lengths else 0
    return int(max(_limit(removed.text, _SWAP_GROWTH_RATIO, _SWAP_GROWTH_CHARS), average * 1.1))


def _accept_swaps(
    draft: Draft,
    raw_swaps: Any,
    editable: dict[int, DocxParagraph],
    job_description: str,
    requests: list[dict[str, Any]] | None = None,
) -> None:
    requests = requests or []
    used_roles = {s["role"] for s in draft.swaps if not s.get("request")}
    for raw in raw_swaps if isinstance(raw_swaps, list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            remove, after = int(raw.get("remove")), int(raw.get("after"))
        except (TypeError, ValueError):
            continue
        request = _request_number(raw, requests, "add")
        role = draft.layout.role_of.get(remove)
        # "after" == "remove" puts the new bullet exactly where the removed one was.
        if (
            remove not in editable
            or after not in editable
            or role is None
            or draft.layout.role_of.get(after) != role
            or remove in draft.removed
        ):
            continue
        text = " ".join(str(raw.get("text") or "").split())
        text, _ = polish_edit("", text, job_description)
        if not text:
            continue
        if request:
            req = requests[request - 1]
            if (
                role not in req["roles"]
                or _done(req, request, role, draft) >= _target(req, role, draft)
                or not _mentions(req["skill"], text)
            ):
                logger.info("Dropped requested swap for paragraph %s: wrong role, too many, or skill not named", remove)
                continue
            if len(text) > _requested_limit(draft, editable[remove], role, editable):
                logger.info("Dropped requested swap for paragraph %s: too long", remove)
                continue
        else:
            request = 0
            if (
                not draft.layout.in_top(remove)
                or role in used_roles
                or len(text) > _limit(editable[remove].text, _SWAP_GROWTH_RATIO, _SWAP_GROWTH_CHARS)
            ):
                logger.info("Dropped swap for paragraph %s: outside roles 1-3, second swap, or too long", remove)
                continue
            used_roles.add(role)
        draft.edits.pop(remove, None)  # the removed bullet's rewrite no longer applies
        draft.swaps.append(
            {
                "after": after,
                "anchor_text": editable[after].text,
                "text": text,
                "keywords": _str_list(raw.get("keywords"), 8),
                "removed_index": remove,
                "removed_text": editable[remove].text,
                "remove": remove,
                "role": role,
                "request": request or None,
            }
        )


def _enforce_total_length(draft: Draft, original_length: int, analysis: JDAnalysis) -> None:
    """Drop the rewrites that grow the most until the document fits its budget,
    preferring to keep those that bring in a JD term found nowhere else. Edits
    the candidate asked for (requests and instructions) are never undone."""
    budget = total_budget(original_length)

    def automatic() -> list[int]:
        return [i for i, e in draft.edits.items() if not e.get("request") and not e.get("instruction")]

    while _body_length(draft.texts()) > budget and automatic():
        def growth(index: int) -> int:
            e = draft.edits[index]
            return len(e["new_text"]) - len(" ".join(e["original_text"].split()))

        def essential(index: int) -> bool:
            without = Draft(
                draft.paragraphs, draft.layout, {k: v for k, v in draft.edits.items() if k != index}, draft.swaps, draft.deletions
            )
            return weighted_match(analysis, without.text())["score"] < weighted_match(analysis, draft.text())["score"]

        candidates = sorted(automatic(), key=lambda i: (essential(i), -growth(i)))
        if growth(candidates[0]) <= 0:
            break
        logger.info("Reverted edit %s to keep the resume the same length", candidates[0])
        draft.edits.pop(candidates[0])


def _skills_line(draft: Draft, editable: dict[int, DocxParagraph]) -> DocxParagraph | None:
    """The editable, non-role paragraph that reads most like a skills list."""
    best, best_count = None, 1
    for index, p in editable.items():
        if index in draft.layout.role_of:
            continue
        text = draft.edits[index]["new_text"] if index in draft.edits else p.text
        count = text.count(",") + text.count("|")
        if count > best_count:
            best, best_count = p, count
    return best


def _add_missing_skills(draft: Draft, editable: dict[int, DocxParagraph], analysis: JDAnalysis, resume_text: str) -> None:
    """Last resort for the ATS target: append missing JD skills to the skills line,
    as far as its length allowance allows."""
    line = _skills_line(draft, editable)
    if line is None:
        return
    current = draft.edits[line.index]["new_text"] if line.index in draft.edits else " ".join(line.text.split())
    limit = min(max_chars(line, draft.layout), MAX_EDIT_TEXT_CHARS)
    missing = weighted_match(analysis, draft.text())["missing"]
    skills = [t for t in missing if t in find_skills(t) or t in analysis.must_have or t in analysis.nice_to_have]
    added = []
    for skill in skills:
        candidate = current.rstrip(" .,") + ", " + skill
        if len(candidate) > limit:
            continue
        current = candidate
        added.append(skill)
    if added:
        draft.edits[line.index] = {
            "index": line.index,
            "original_text": line.text,
            "new_text": current,
            "keywords": sorted(set(draft.edits.get(line.index, {}).get("keywords", [])) | set(added)),
            "added_from_jd": find_unsupported_claims(current, resume_text),
        }


def _validate_repair(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result.get("edits", []), list) or not isinstance(result.get("swaps", []), list):
        raise ValueError("edits and swaps must be lists")
    return result


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
    layout = detect_roles(paragraphs)
    draft = Draft(paragraphs, layout)
    original_length = _body_length([p.text for p in paragraphs])
    before = weighted_match(analysis, resume_text)

    instructions_block = ""
    if instructions and instructions.strip():
        instructions_block = (
            "\nTHE CANDIDATE'S OWN INSTRUCTIONS (they take priority over every rule below "
            "except NEVER CHANGE; give every edit that carries them out \"instruction\": true):\n"
            f"{instructions.strip()[:2000]}\n"
        )

    def validate(result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result.get("edits"), list):
            raise ValueError("edits must be a list")
        if not isinstance(result.get("swaps", []), list) or not isinstance(result.get("removals", []), list):
            raise ValueError("swaps and removals must be lists")
        return result

    system_prompt = (
        "You are an expert resume writer who tailors resumes to job descriptions "
        "without making them longer. You only return JSON."
    )
    requests = await parse_requests(instructions or "", layout, system_prompt)
    result, model = await _complete_json_tiered(
        "tailor",
        prompt=TAILOR_PROMPT.format(
            job_title=job_title or "(see JD)",
            domain=domain or "(see JD)",
            job_description=_clip(analysis.cleaned_text, _JD_PROMPT_CHARS),
            priorities=_priorities_block(analysis),
            key_skills=", ".join(key_skills(analysis)) or "(none detected; use the JD's main tools)",
            missing_terms=_missing_terms_block(analysis, before["missing"]),
            requests_block=_requests_block(requests, layout),
            paragraphs=_format_paragraphs(draft),
            instructions_block=instructions_block,
            avoid_words=", ".join(AVOID_WORDS),
        ),
        system_prompt=system_prompt,
        max_tokens=12_000,
        schema_type="diff",
        response_validator=validate,
    )
    _accept_removals(draft, result.get("removals"), editable, requests)
    _accept_swaps(draft, result.get("swaps"), editable, job_description, requests)
    _accept_edits(draft, result.get("edits"), editable, job_description, resume_text, requests)
    _enforce_total_length(draft, original_length, analysis)

    # -- repair passes until requests, the ATS target and key skills are met ---
    check = _check(draft, analysis)
    status = request_status(draft, requests)
    passes = 0

    def unmet() -> bool:
        return (
            check["score"] < ATS_TARGET
            or bool(check["missing_key"])
            or any(s["done"] < s["requested"] for s in status)
        )

    while unmet() and passes < MAX_REPAIR_PASSES:
        passes += 1
        problems = []
        if any(s["done"] < s["requested"] for s in status):
            problems.append("some of the candidate's requested bullets are still missing.")
        if check["score"] < ATS_TARGET:
            problems.append(f"its ATS keyword score is {check['score']}%, and it must reach {ATS_TARGET}%.")
        if check["missing_key"]:
            problems.append("some key skills are not in the bullets of the three most recent roles.")
        try:
            repair, model = await _complete_json_tiered(
                "tailor",
                prompt=REPAIR_PROMPT.format(
                    problems=" Also, ".join(problems),
                    job_title=job_title or "(see JD)",
                    missing_terms=_missing_terms_block(analysis, check["missing"]),
                    missing_key_skills=", ".join(check["missing_key"]) or "none",
                    open_requests=_open_requests_block(status),
                    paragraphs=_format_paragraphs(draft),
                    avoid_words=", ".join(AVOID_WORDS),
                ),
                system_prompt=system_prompt,
                max_tokens=8_000,
                schema_type="diff",
                response_validator=_validate_repair,
            )
        except Exception as exc:  # the first pass is still usable without a repair
            logger.warning("Tailoring repair pass %s failed: %s", passes, exc)
            break
        _accept_removals(draft, repair.get("removals"), editable, requests)
        _accept_swaps(draft, repair.get("swaps"), editable, job_description, requests)
        _accept_edits(draft, repair.get("edits"), editable, job_description, resume_text, requests)
        _enforce_total_length(draft, original_length, analysis)
        check = _check(draft, analysis)
        status = request_status(draft, requests)

    if check["score"] < ATS_TARGET:
        _add_missing_skills(draft, editable, analysis, resume_text)
        _enforce_total_length(draft, original_length, analysis)
        check = _check(draft, analysis)

    if not draft.edits and not draft.swaps and not draft.deletions:
        raise ValueError("The AI returned no usable changes for this resume.")

    edits = [
        {k: v for k, v in e.items() if k not in ("request", "instruction")}
        for e in sorted(draft.edits.values(), key=lambda e: e["index"])
    ]
    new_docx = apply_edits(
        docx,
        {e["index"]: e["new_text"] for e in edits},
        [(s["after"], s["text"]) for s in draft.swaps],
        [s["remove"] for s in draft.swaps] + sorted(draft.deletions),
    )
    new_paragraphs = read_paragraphs(new_docx)
    new_text = plain_text(new_paragraphs)
    after = weighted_match(analysis, new_text)
    missing_key = [s for s in key_skills(analysis) if not term_in_text(s, draft.top_roles_text())] if layout.top_roles else []

    additions = [{k: v for k, v in s.items() if k not in ("remove", "role")} for s in draft.swaps]
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
            "ats_score": after["score"],
            "ats_target": ATS_TARGET,
            "ats_target_met": after["score"] >= ATS_TARGET,
            "key_skills": key_skills(analysis),
            "key_skills_missing_in_recent_roles": missing_key,
            "recent_roles": [layout.role_names[r] for r in layout.top_roles if r in layout.role_names],
            "length_before": original_length,
            "length_after": _body_length([p.text for p in new_paragraphs]),
            "paragraphs_before": len(paragraphs),
            "paragraphs_after": len(new_paragraphs),
            "repair_passes": passes,
            "requests": request_status(draft, requests),
            "removed": [
                {k: v for k, v in d.items()} | {"role_name": layout.role_names.get(d["role"], "")}
                for d in sorted(draft.deletions.values(), key=lambda d: d["index"])
            ],
            "model": model,
        },
    }
