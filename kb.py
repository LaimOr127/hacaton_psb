"""Knowledge base loading and structural chunking.

A chunk is a structural unit (contract clause, law point) with character offsets
into the document text, so citations map to an exact span.
"""

import hashlib
import io
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from xml.etree import ElementTree

SUPPORTED_SUFFIXES = {".txt", ".md", ".docx"}
MAX_CHUNK_CHARS = 1500
SUBPOINT_SPLIT_CHARS = 800
OUTLINE_LINE_CHARS = 220
MAX_OUTLINE_CHARS = 2500

# "3.2. Товар ..." in contracts; "1. Налоговая ставка ..." or "2.1) услуг ..." in laws.
CLAUSE_RE = re.compile(r"^(\d+(?:\.\d+)+)\.?\s+\S")
SECTION_RE = re.compile(r"^(\d+)\.\s+\S")
SUBPOINT_RE = re.compile(r"^(\d+(?:\.\d+)*(?:-\d+)?)\)\s+\S")
ARTICLE_RE = re.compile(r"Статья\s+(\d+(?:\.\d+)*)")
CODE_RE = re.compile(r"\b([А-Я][А-Яа-я]{1,4} РФ)\b")
FEDERAL_LAW_RE = re.compile(r"N\s*(\d+-ФЗ)\s*(\"[^\"]+\")?")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    address: str
    text: str
    start: int
    end: int


@dataclass
class Document:
    doc_id: str
    title: str
    kind: str  # "law" | "company"
    text: str
    chunks: list[Chunk] = field(default_factory=list)
    outline: str = ""  # laws only: first sentence of every top-level point


def load_zip(path) -> list[Document]:
    documents = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            suffix = PurePosixPath(name).suffix.lower()
            if name.endswith("/") or name.startswith("__MACOSX/") or suffix not in SUPPORTED_SUFFIXES:
                continue
            try:
                text = _decode(archive.read(name), suffix)
            except (UnicodeDecodeError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
                print(f"skipped unreadable document: {name}", file=sys.stderr)
                continue
            if text.strip():
                documents.append(parse_document(name, text))
    if not documents:
        raise ValueError("knowledge base archive has no readable documents")
    return documents


def _decode(raw: bytes, suffix: str) -> str:
    if suffix != ".docx":
        return raw.decode("utf-8-sig")
    with zipfile.ZipFile(io.BytesIO(raw)) as docx:
        root = ElementTree.fromstring(docx.read("word/document.xml"))
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    return "\n".join("".join(t.text or "" for t in p.iter(ns + "t")) for p in root.iter(ns + "p"))


def parse_document(name: str, text: str) -> Document:
    text = text.replace("\r\n", "\n").strip()
    doc_id = hashlib.sha1(name.encode()).hexdigest()[:10]
    is_law = text.startswith("Источник:") and ARTICLE_RE.search(text.split("\n", 1)[0])
    if is_law:
        doc = Document(doc_id, _law_title(text, name), "law", text)
        doc.chunks = _chunk(doc, _law_units(text, _article(text)))
        doc.outline = _outline(text)
    else:
        doc = Document(doc_id, _file_title(name), "company", text)
        doc.chunks = _chunk(doc, _company_units(text))
    return doc


def _file_title(name: str) -> str:
    stem = PurePosixPath(name).stem
    return stem.split("__", 1)[-1].strip()


def _article(text: str) -> str:
    match = ARTICLE_RE.search(text)
    return match.group(1) if match else ""


def _law_title(text: str, name: str) -> str:
    source = text.split("\n", 1)[0]
    article = _article(source)
    code = CODE_RE.search(source)
    if code:
        law = code.group(1)
    else:
        federal = FEDERAL_LAW_RE.search(source)
        if not federal:
            return _file_title(name)
        law = "Федеральный закон № " + federal.group(1)
        if federal.group(2):
            law += " " + federal.group(2).replace('"', "«", 1).replace('"', "»", 1)
    heading = re.search(rf"^Статья {re.escape(article)}\.\s*(.+)$", text, re.MULTILINE)
    title = f"{law}, ст. {article}"
    return f"{title}. {heading.group(1).strip()}" if heading else title


def _outline(text: str) -> str:
    """A retrieved fragment of a long article loses the article's general rules: the 22% VAT
    rate lives in a one-line point 3 that matches almost no question wording."""
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if SECTION_RE.match(line):
            lines.append(
                line if len(line) <= OUTLINE_LINE_CHARS else line[:OUTLINE_LINE_CHARS].rsplit(" ", 1)[0] + " …"
            )
    outline = "\n".join(lines)
    return outline if len(outline) <= MAX_OUTLINE_CHARS else outline[:MAX_OUTLINE_CHARS].rsplit("\n", 1)[0]


def _paragraphs(text: str) -> list[tuple[int, int]]:
    """(start, end) spans of non-empty lines."""
    spans = []
    for match in re.finditer(r"[^\n]+", text):
        if match.group().strip():
            spans.append((match.start(), match.end()))
    return spans


NOTE_RE = re.compile(
    r"^(?:(?:Пункт|Подпункт|Часть|Статья|Абзац|Наименование)\w*\b.*\b(?:изменен|дополнен|утратил|признан|введен|изложен)"
    r"|Федеральным законом|О .+ см\.|См\.|Информация об изменениях"
    # Transitional notes: "Положения пункта 3 (в редакции Федерального закона от ...) применяются ..."
    r"|Положения [^(\n]{0,80}\(в редакции)"
)

# Unit kinds: "unit" starts a structural unit; "prefix" (heading, service note) is glued
# to the unit that follows it; "sub" (numbered subpoint) and "body" continue the current unit.
Unit = tuple[str, int, int, str]


def _law_units(text: str, article: str) -> list[Unit]:
    """Unnumbered paragraphs (parts of ТК articles) are addressed by article only:
    guessing part numbers would produce wrong citations."""
    base = f"ст. {article}" if article else ""
    point, units = "", []
    for start, end in _paragraphs(text):
        line = text[start:end].strip()
        clause = SECTION_RE.match(line) or CLAUSE_RE.match(line)
        sub = SUBPOINT_RE.match(line)
        if NOTE_RE.match(line) or line.startswith("Статья "):
            units.append(("", start, end, "prefix"))
        elif clause:
            point = clause.group(1)
            units.append((f"{base}, п. {point}", start, end, "unit"))
        elif sub:
            prefix = f"{base}, п. {point}" if point else base
            units.append((f"{prefix}, пп. {sub.group(1)}", start, end, "sub"))
        else:
            units.append((f"{base}, п. {point}" if point else base, start, end, "body"))
    return units


def _company_units(text: str) -> list[Unit]:
    units = []
    for start, end in _paragraphs(text):
        line = text[start:end].strip()
        clause = CLAUSE_RE.match(line)
        if clause:
            units.append((f"п. {clause.group(1)}", start, end, "unit"))
        elif SECTION_RE.match(line):
            units.append(("", start, end, "prefix"))
        else:
            units.append(("", start, end, "body"))
    return units


def _chunk(doc: Document, units: list[Unit]) -> list[Chunk]:
    chunks: list[Chunk] = []
    current: list[Unit] = []

    def flush() -> None:
        if not current:
            return
        start, end = current[0][1], current[-1][2]
        numbered = [a for a, _, _, kind in current if kind in ("unit", "sub")]
        addressed = [a for a, _, _, kind in current if a and kind != "prefix"]
        address = (numbered or addressed or [""])[0]
        chunks.append(Chunk(f"{doc.doc_id}#{len(chunks)}", doc.doc_id, address, doc.text[start:end], start, end))
        current.clear()

    for unit in units:
        _, start, end, kind = unit
        if current:
            only_prefix = all(k == "prefix" for *_, k in current)
            size = current[-1][2] - current[0][1]
            oversized = size + (end - start) > MAX_CHUNK_CHARS
            long_law_subpoint = (
                doc.kind == "law" and size > SUBPOINT_SPLIT_CHARS and SUBPOINT_RE.match(doc.text[start:end])
            )
            if (kind in ("unit", "prefix") and not only_prefix) or oversized or long_law_subpoint:
                flush()
        current.append(unit)
    flush()
    return chunks
