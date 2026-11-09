"""Links between company documents that the model must see together.

- A supplementary agreement and the contract it amends: the contract alone gives an
  outdated clause, the agreement alone has no context.
- Editions of one internal document: the right edition depends on the event date,
  so the model gets all of them.
"""

import re
from collections import defaultdict

from kb import Document

NUMBER = r"([A-ZА-ЯЁ]{1,4}-\d+(?:/\d{2,4})?)"
OWN_NUMBER_RE = re.compile(r"№\s*" + NUMBER)
AMENDS_RE = re.compile(r"к\s+договору[^№\n]{0,60}№\s*" + NUMBER, re.IGNORECASE)
EDITION_RE = re.compile(r"\bред(?:акция|\.)\s+от\b", re.IGNORECASE)
HEAD_LINES = 5


def _head(doc: Document) -> list[str]:
    return doc.text.split("\n", HEAD_LINES)[:HEAD_LINES]


def own_number(doc: Document) -> str | None:
    match = OWN_NUMBER_RE.search(_head(doc)[0])
    return match.group(1) if match else None


def _amended_number(doc: Document) -> str | None:
    match = AMENDS_RE.search("\n".join(_head(doc)))
    return match.group(1) if match else None


def _edition_family(doc: Document) -> str | None:
    """Title line shared by editions; banners like "РЕДАКЦИЯ УТРАТИЛА СИЛУ" are skipped."""
    head = _head(doc)
    if not EDITION_RE.search("\n".join(head)):
        return None
    for line in head:
        letters = [c for c in line if c.isalpha()]
        if len(letters) > 10 and all(c.isupper() for c in letters) and "УТРАТИЛ" not in line:
            return line.strip()
    return None


def link(documents: list[Document]) -> dict[str, list[str]]:
    """doc_id -> related doc_ids, symmetric."""
    company = [d for d in documents if d.kind == "company"]
    by_number = {number: d.doc_id for d in company if (number := own_number(d))}
    families: dict[str, list[str]] = defaultdict(list)
    for doc in company:
        if family := _edition_family(doc):
            families[family].append(doc.doc_id)

    links: dict[str, set[str]] = defaultdict(set)
    for doc in company:
        target = by_number.get(_amended_number(doc) or "")
        if target and target != doc.doc_id:
            links[doc.doc_id].add(target)
            links[target].add(doc.doc_id)
    for members in families.values():
        for doc_id in members:
            links[doc_id].update(m for m in members if m != doc_id)
    return {doc_id: sorted(related) for doc_id, related in links.items()}
