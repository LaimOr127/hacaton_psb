"""Which documents and clauses an answer cites, for highlighting in the web UI.

The answer cites like the golden answers: "договор № П-17/2024 ... (п. 4.2)",
"Источник: ТК РФ, ст. 70". A clause is highlighted when its number is referenced and
its document is the one the answer names; a bare "п. 3.1" would otherwise light up
clause 3.1 of every contract in the context.
"""

import re
from dataclasses import dataclass

import dates
import relations
from kb import Chunk, Document
from search import Block

ARTICLE_REF_RE = re.compile(r"(?:\bст\.|\bстать\w*)\s*(\d+(?:\.\d+)*)", re.IGNORECASE)
POINT_REF_RE = re.compile(r"(?:\b(?:п|пп|ч)\.\s*|\b(?:пункт|подпункт|част)\w*\s+)(\d+(?:\.\d+)*)", re.IGNORECASE)
ADDRESS_POINT_RE = re.compile(r"(?:^|,\s*)п\.\s*(\d+(?:\.\d+)*)")
TITLE_ARTICLE_RE = re.compile(r"ст\.\s*(\d+(?:\.\d+)*)")


@dataclass(frozen=True)
class Source:
    doc_id: str
    title: str
    kind: str
    chunk_ids: tuple[str, ...]
    cited: bool  # False: retrieved for the answer but not referenced in it


def _point(chunk: Chunk) -> str | None:
    match = ADDRESS_POINT_RE.search(chunk.address)
    return match.group(1) if match else None


def _edition_date(doc: Document) -> str | None:
    start, _ = dates.validity(doc.text)
    return start.strftime("%d.%m.%Y") if start else None


def _is_named(doc: Document, answer: str, articles: set[str], cited_editions: set[str]) -> bool:
    if doc.kind == "law":
        match = TITLE_ARTICLE_RE.search(doc.title)
        return bool(match) and match.group(1) in articles
    if number := relations.own_number(doc):
        return number in answer
    # No number: the answer has to name the document by its first two title words
    # ("Регламенту согласования", "служебной записке") and, if it names an edition date, that edition.
    stems = [word.lower()[:5] for word in doc.title.split()[:2]]
    if len(stems) < 2 or not all(len(stem) == 5 and stem in answer.lower() for stem in stems):
        return False
    edition = _edition_date(doc)
    return edition is None or not cited_editions or edition in cited_editions


def sources(answer: str, blocks: list[Block]) -> list[Source]:
    articles = set(ARTICLE_REF_RE.findall(answer))
    points = set(POINT_REF_RE.findall(answer))
    docs: dict[str, Document] = {}
    hits: dict[str, list[str]] = {}
    for block in blocks:
        docs.setdefault(block.doc.doc_id, block.doc)
        hits.setdefault(block.doc.doc_id, []).extend(block.hits)

    editions = {date for doc in docs.values() if (date := _edition_date(doc))}
    cited_editions = {date for date in editions if date in answer}
    cited, rest = [], []
    for doc_id, doc in docs.items():
        named = _is_named(doc, answer, articles, cited_editions)
        clauses = [c.chunk_id for c in doc.chunks if named and _point(c) in points]
        # "Источник: ТК РФ, ст. 70" names a document without a point: highlight the best match.
        if not clauses and named and hits[doc_id]:
            clauses = hits[doc_id][:1]
        if clauses:
            cited.append(Source(doc_id, doc.title, doc.kind, tuple(dict.fromkeys(clauses)), True))
        else:
            rest.append(Source(doc_id, doc.title, doc.kind, tuple(dict.fromkeys(hits[doc_id])), False))
    return cited + rest
