"""Read and rewrite a DOCX resume in place without disturbing its formatting.

The JD Studio flow never regenerates a document from scratch. It lists the
paragraphs of the user's own ``.docx``, lets the LLM propose new text for a
subset of them, and writes that text back into the original runs so fonts,
spacing, bullets, tables and page layout are untouched.

A paragraph is only *editable* when it is made of plain text runs. Paragraphs
holding tabs (right-aligned dates), line breaks, hyperlinks, fields, images or
tracked changes are *locked*: rewriting them safely would require guessing at
layout intent, so they are shown to the LLM as context only.
"""

import copy
import io
import re
from dataclasses import asdict, dataclass
from typing import Any

from docx import Document
from docx.oxml.ns import qn
from lxml import etree

import zipfile

# Limits for uploaded .docx archives (zip bombs, oversized packages).
MAX_UPLOAD_BYTES = 6 * 1024 * 1024
_MAX_DOCX_MEMBERS = 2_000
_MAX_UNPACKED_BYTES = 16 * 1024 * 1024

_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"

# Run children that are pure text or invisible bookkeeping.
_SAFE_RUN_CHILDREN = frozenset(
    {qn("w:rPr"), qn("w:t"), qn("w:lastRenderedPageBreak"), qn("w:softHyphen")}
)
# Paragraph children that carry no visible content of their own.
_SAFE_PARAGRAPH_CHILDREN = frozenset(
    {
        qn("w:pPr"),
        qn("w:r"),
        qn("w:proofErr"),
        qn("w:bookmarkStart"),
        qn("w:bookmarkEnd"),
        qn("w:commentRangeStart"),
        qn("w:commentRangeEnd"),
        qn("w:permStart"),
        qn("w:permEnd"),
    }
)

# Manually typed bullet glyphs at the start of a paragraph.
_BULLET_PREFIX = re.compile(r"^\s*([•·▪●◦■□➢➤►▶✓✔\-–—*])\s+")

MAX_EDIT_TEXT_CHARS = 1_500


class DocxEditError(ValueError):
    """Raised when a DOCX cannot be read or an edit cannot be applied."""


@dataclass(frozen=True)
class DocxParagraph:
    """One paragraph of the document body, in reading order."""

    index: int
    text: str
    style: str
    is_list: bool
    editable: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load(content: bytes) -> Any:
    try:
        return Document(io.BytesIO(content))
    except Exception as exc:  # python-docx raises a variety of zip/xml errors
        raise DocxEditError("The file is not a readable .docx document.") from exc


def validate_docx_bytes(content: bytes) -> None:
    """Check archive limits (entries, unpacked size, encryption), then confirm it opens."""
    if len(content) > MAX_UPLOAD_BYTES:
        raise DocxEditError("File too large (6MB maximum).")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > _MAX_DOCX_MEMBERS:
                raise DocxEditError("The document archive has too many entries.")
            names = {m.filename for m in members}
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise DocxEditError("The file is not a valid .docx document.")
            if any(m.flag_bits & 0x1 for m in members):
                raise DocxEditError("Password-protected documents are not supported.")
            if sum(m.file_size for m in members) > _MAX_UNPACKED_BYTES:
                raise DocxEditError("The document is too large once unpacked (16MB maximum).")
    except zipfile.BadZipFile as exc:
        raise DocxEditError("The file is not a readable .docx document.") from exc
    _load(content)


def _paragraph_elements(document: Any) -> list[Any]:
    """All body paragraphs in reading order, including tables and text boxes.

    Paragraphs inside ``mc:Fallback`` are legacy VML duplicates of text-box
    content that Word ignores when the modern ``mc:Choice`` is present, so
    listing them would show the user every text-box line twice.
    """
    body = document.element.body
    elements = []
    for paragraph in body.iter(qn("w:p")):
        if any(ancestor.tag == _MC_FALLBACK for ancestor in paragraph.iterancestors()):
            continue
        elements.append(paragraph)
    return elements


def _run_text(run: Any) -> str:
    return "".join(node.text or "" for node in run if node.tag == qn("w:t"))


def _paragraph_text(paragraph: Any) -> str:
    """Visible text including tabs/breaks, used for display and matching."""
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == qn("w:t"):
            parts.append(node.text or "")
        elif node.tag == qn("w:tab"):
            parts.append("\t")
        elif node.tag in (qn("w:br"), qn("w:cr")):
            parts.append("\n")
    return "".join(parts)


def _is_editable(paragraph: Any) -> bool:
    for child in paragraph:
        if not isinstance(child.tag, str):
            continue  # XML comments / processing instructions
        if child.tag not in _SAFE_PARAGRAPH_CHILDREN:
            return False
        if child.tag == qn("w:r"):
            for node in child:
                if isinstance(node.tag, str) and node.tag not in _SAFE_RUN_CHILDREN:
                    return False
    return True


def _style_name(paragraph: Any, styles: dict[str, str]) -> str:
    style = paragraph.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")
    if style is None:
        return "Normal"
    style_id = style.get(qn("w:val")) or ""
    return styles.get(style_id, style_id)


def _is_list(paragraph: Any, style: str) -> bool:
    if paragraph.find(f"{qn('w:pPr')}/{qn('w:numPr')}") is not None:
        return True
    text = _paragraph_text(paragraph)
    return "list" in style.lower() or bool(_BULLET_PREFIX.match(text))


def _style_names(document: Any) -> dict[str, str]:
    names: dict[str, str] = {}
    for style in document.styles:
        try:
            names[style.style_id] = style.name
        except Exception:  # latent/numbering styles may lack an id
            continue
    return names


def read_paragraphs(content: bytes) -> list[DocxParagraph]:
    """List every non-empty body paragraph with its stable document index."""
    document = _load(content)
    styles = _style_names(document)
    paragraphs: list[DocxParagraph] = []
    for index, element in enumerate(_paragraph_elements(document)):
        text = _paragraph_text(element)
        if not text.strip():
            continue
        style = _style_name(element, styles)
        paragraphs.append(
            DocxParagraph(
                index=index,
                text=text,
                style=style,
                is_list=_is_list(element, style),
                editable=_is_editable(element),
            )
        )
    return paragraphs


def plain_text(paragraphs: list[DocxParagraph]) -> str:
    """Join paragraphs into the plain text used for matching and prompts."""
    return "\n".join(p.text for p in paragraphs)


def _set_run_text(run: Any, text: str) -> None:
    for node in [n for n in run if n.tag == qn("w:t")]:
        run.remove(node)
    t = etree.SubElement(run, qn("w:t"))
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _keep_bullet_prefix(original: str, new_text: str) -> str:
    """Restore a manually typed bullet glyph the model dropped."""
    match = _BULLET_PREFIX.match(original)
    if match and not _BULLET_PREFIX.match(new_text):
        return match.group(0).lstrip() + new_text.lstrip()
    return new_text


def set_paragraph_text(paragraph: Any, new_text: str) -> None:
    """Replace a paragraph's text while keeping its run formatting.

    Leading runs whose text is still a prefix of the new text are kept as-is,
    so a bold lead-in such as ``"Languages: "`` keeps its bold. The remainder
    goes into the next run (inheriting that run's formatting) and any later
    runs are removed.
    """
    runs = [child for child in paragraph if child.tag == qn("w:r")]
    if not runs:
        raise DocxEditError("Paragraph has no text runs to edit.")

    consumed = 0
    target = 0
    while target < len(runs) - 1:
        text = _run_text(runs[target])
        if not text or not new_text.startswith(text, consumed):
            break
        consumed += len(text)
        target += 1

    _set_run_text(runs[target], new_text[consumed:])
    for run in runs[target + 1 :]:
        paragraph.remove(run)


def _clean_text(index: int, text: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        raise DocxEditError(f"Paragraph {index} cannot be made empty.")
    if len(cleaned) > MAX_EDIT_TEXT_CHARS:
        raise DocxEditError(f"Paragraph {index} text is too long.")
    return cleaned


def _new_paragraph_like(anchor: Any, text: str) -> Any:
    """A copy of ``anchor`` (same bullet, numbering, spacing) holding ``text``.

    Paragraph properties are kept as they are, so the new line sits in the
    same list with the same indent. The text takes the formatting of the
    anchor's longest run (the bullet's body text rather than a bold lead-in),
    and every other child (runs, bookmarks) is dropped.
    """
    clone = copy.deepcopy(anchor)
    runs = [child for child in clone if child.tag == qn("w:r")]
    if not runs:
        raise DocxEditError("Paragraph has no text runs to copy formatting from.")
    template = max(runs, key=lambda r: len(_run_text(r)))
    for child in list(clone):
        if child.tag != qn("w:pPr") and child is not template:
            clone.remove(child)
    for node in [n for n in template if n.tag != qn("w:rPr")]:
        template.remove(node)
    _set_run_text(template, _keep_bullet_prefix(_paragraph_text(anchor), text))
    return clone


def apply_edits(
    content: bytes,
    edits: dict[int, str],
    insertions: list[tuple[int, str]] | None = None,
) -> bytes:
    """Write ``{paragraph_index: new_text}`` into the DOCX and return new bytes.

    ``insertions`` are ``(after_index, text)`` pairs: a new paragraph formatted
    like paragraph ``after_index`` is added right after it (several after the
    same paragraph keep their order). Indices always refer to the original
    document, before any insertion.

    Only editable paragraphs may change or anchor an insertion; a locked or
    unknown index is an error rather than a silent skip, so callers cannot
    believe a change landed when it did not.
    """
    document = _load(content)
    elements = _paragraph_elements(document)
    for after, text in insertions or []:
        if after < 0 or after >= len(elements):
            raise DocxEditError(f"Paragraph {after} does not exist.")
        if not _is_editable(elements[after]):
            raise DocxEditError(f"Paragraph {after} is locked and cannot anchor a new line.")
        _clean_text(after, text)
    # Clone anchors before any edit, so a new bullet copies the neighbour's
    # formatting, not text an edit is about to put there.
    originals = {after: copy.deepcopy(elements[after]) for after, _ in insertions or []}
    for index, new_text in edits.items():
        if index < 0 or index >= len(elements):
            raise DocxEditError(f"Paragraph {index} does not exist.")
        element = elements[index]
        if not _is_editable(element):
            raise DocxEditError(f"Paragraph {index} is locked and cannot be edited.")
        cleaned = _clean_text(index, new_text)
        set_paragraph_text(element, _keep_bullet_prefix(_paragraph_text(element), cleaned))

    last_inserted: dict[int, Any] = {}
    for after, text in insertions or []:
        paragraph = _new_paragraph_like(originals[after], _clean_text(after, text))
        last_inserted.get(after, elements[after]).addnext(paragraph)
        last_inserted[after] = paragraph

    output = io.BytesIO()
    document.save(output)
    return output.getvalue()
