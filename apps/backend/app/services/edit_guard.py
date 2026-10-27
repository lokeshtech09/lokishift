"""Local checks on LLM paragraph rewrites: style polish and a truth guard.

Both run after the LLM, cost nothing, and only look at what an edit *added*:
words the candidate wrote themselves are never changed or flagged.

* ``polish_edit`` swaps stock AI phrasing ("spearheaded", "leveraged",
  "in order to") for plain words and drops empty hype adjectives.
* ``find_unsupported_claims`` flags numbers, skills and tool names that appear
  in the rewrite but nowhere in the candidate's resume, which is how
  overstatement usually shows up.
"""

import re

from app.services.jd_analysis import CONCEPT_SKILLS, find_skills

# Only replacements that keep the meaning intact.
_REPLACEMENTS: dict[str, str] = {
    "spearheaded": "led",
    "spearheading": "leading",
    "orchestrated": "coordinated",
    "orchestrating": "coordinating",
    "championed": "promoted",
    "leveraged": "used",
    "leveraging": "using",
    "leverage": "use",
    "utilized": "used",
    "utilizing": "using",
    "utilize": "use",
    "harnessed": "used",
    "harnessing": "using",
    "synergized": "collaborated",
    "revolutionized": "transformed",
    "catalyzed": "started",
    "operationalized": "implemented",
    "effectuated": "completed",
    "endeavored": "worked",
    "showcasing": "showing",
    "in order to": "to",
    "for the purpose of": "to",
    "with a view to": "to",
    "on a daily basis": "daily",
    "on a regular basis": "regularly",
    "in a timely manner": "promptly",
    "due to the fact that": "because",
    "in the event that": "if",
}
# Hype adjectives that add no information; removed outright.
_DROP: tuple[str, ...] = (
    "cutting-edge",
    "bleeding-edge",
    "state-of-the-art",
    "world-class",
    "best-in-class",
    "robust",
    "seamless",
    "seamlessly",
    "impactful",
    "holistic",
    "dynamic",
    "innovative",
    "highly",
    "successfully",
)
AVOID_WORDS: tuple[str, ...] = tuple(
    w for w in (*_REPLACEMENTS, *_DROP) if " " not in w
)

_NUMBER = re.compile(r"[$€£₹]?\d[\d,]*(?:\.\d+)?\s?(?:%|\+|x\b|k\b|m\b|b\b|tb\b|gb\b|pb\b|ms\b)?", re.I)
# Tool-like tokens: acronyms (AWS, EC2) or mixed case (PySpark, GraphQL).
_TECH_TOKEN = re.compile(r"\b(?:[A-Z]{2,}[A-Za-z0-9+#]*|[A-Za-z]+[A-Z][A-Za-z0-9+#]*|[A-Za-z]+\d[A-Za-z0-9]*)\b")


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", re.IGNORECASE)


def _match_case(source: str, replacement: str) -> str:
    return replacement[:1].upper() + replacement[1:] if source[:1].isupper() else replacement


def polish_edit(original: str, new_text: str, job_description: str) -> tuple[str, list[str]]:
    """Replace AI-sounding words the edit introduced; return text and changes.

    A phrase is left alone when the candidate already used it in this
    paragraph or when the JD itself uses it (the employer's own vocabulary).
    """
    keep = f"{original}\n{job_description}".lower()
    text = new_text
    changed: list[str] = []

    for phrase, replacement in _REPLACEMENTS.items():
        pattern = _phrase_pattern(phrase)
        if pattern.search(keep) or not pattern.search(text):
            continue
        text = pattern.sub(lambda m, r=replacement: _match_case(m.group(0), r), text)
        changed.append(f"{phrase} → {replacement}")

    for word in _DROP:
        pattern = re.compile(rf"(?<![\w-]){re.escape(word)}(?![\w-])\s*", re.IGNORECASE)
        if pattern.search(keep) or not pattern.search(text):
            continue
        text = pattern.sub(lambda m: "", text)
        changed.append(f"removed “{word}”")

    if changed:
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r"\s+([,.;:])", r"\1", text).strip()
        text = text[:1].upper() + text[1:]
    return text, changed


def _numbers(text: str) -> set[str]:
    return {re.sub(r"[\s,]", "", m.group(0)).lower() for m in _NUMBER.finditer(text)}


def find_new_numbers(new_text: str, source_text: str) -> list[str]:
    """Numbers in ``new_text`` that do not appear anywhere in ``source_text``."""
    source = _numbers(source_text)
    bare_source = {re.sub(r"[^\d.]", "", n) for n in source}
    return [
        n
        for n in sorted(_numbers(new_text))
        if n not in source and re.sub(r"[^\d.]", "", n) not in bare_source
    ]


def find_unsupported_claims(new_text: str, resume_text: str) -> list[str]:
    """Numbers, skills and tool names in ``new_text`` absent from the resume."""
    flags: list[str] = []
    resume_lower = resume_text.lower()

    for number in find_new_numbers(new_text, resume_text):
        flags.append(f"New number “{number}” is not in your resume")

    new_skills = sorted(find_skills(new_text) - find_skills(resume_text) - CONCEPT_SKILLS)
    for skill in new_skills:
        flags.append(f"“{skill}” is not mentioned anywhere in your resume")

    seen = {s.lower() for s in new_skills}
    for token in _TECH_TOKEN.findall(new_text):
        key = token.lower()
        if key in seen or key in resume_lower:
            continue
        seen.add(key)
        flags.append(f"“{token}” is not mentioned anywhere in your resume")
    return flags
