"""Deterministic check that an answer does not state facts absent from its sources.

The platform judge zeroes a question for any invented fact, so every number, point
reference, federal law number and "code + article" pair in the answer must occur in
the text the model was given (documents, dialog history, question).
"""

import re

# "450 000" is one number; "ст. 9 152-ФЗ" is two.
THOUSANDS_RE = re.compile(r"\b\d{1,3}(?:[   ]\d{3})+(?![\d-])")
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
# A number right after a reference word is checked even when it is a single digit.
REFERENCE_RE = re.compile(
    r"(?:\b(?:п|пп|ч|ст|абз)\.\s*|\b(?:пункт|подпункт|част|стать|абзац)\w*\s+)(\d+(?:\.\d+)*)", re.IGNORECASE
)
FEDERAL_LAW_RE = re.compile(r"\b(\d+)-ФЗ\b")
CODE_FIRST_RE = re.compile(r"\b([А-Я][А-Яа-я]{1,4}) РФ,?\s*(?:ст\.|стать\w+)\s*(\d+(?:\.\d+)*)")
ARTICLE_FIRST_RE = re.compile(r"(?:\bст\.|\bстать\w+)\s*(\d+(?:\.\d+)*)\s+([А-Я][А-Яа-я]{1,4}) РФ\b")
# Sentence ends, except after reference abbreviations: "ТК РФ, ст. 70" is one sentence.
SENTENCE_RE = re.compile(r"(?<!\bст\.)(?<!\bп\.)(?<!\bпп\.)(?<!\bч\.)(?<!\bабз\.)(?<=[.!?])\s+(?=[^\d\s])")


def _normalize(text: str) -> str:
    return THOUSANDS_RE.sub(lambda m: re.sub(r"\D", "", m.group()), text)


def _canonical(number: str) -> str:
    """'01.03.2025' and '1.03.2025' are the same date; '0,1' and '0.1' the same rate."""
    parts = number.replace(",", ".").split(".")
    # lstrip instead of int(): no conversion limit on absurdly long digit runs.
    return ".".join(part.lstrip("0") or "0" for part in parts if part)


def _numbers(text: str) -> set[str]:
    return {_canonical(n) for n in NUMBER_RE.findall(text)}


def _significant_numbers(text: str) -> set[str]:
    """Plain single digits are skipped: "1 рабочий день", "ДС № 1" are too common to judge."""
    found = {_canonical(n) for n in NUMBER_RE.findall(text) if len(n) > 1}
    return found | {_canonical(n) for n in REFERENCE_RE.findall(text)}


def _code_articles(text: str) -> set[str]:
    pairs = {(code, article) for code, article in CODE_FIRST_RE.findall(text)}
    pairs |= {(code, article) for article, code in ARTICLE_FIRST_RE.findall(text)}
    return {f"{code} РФ, ст. {_canonical(article)}" for code, article in pairs}


def check(answer: str, sources: str) -> list[str]:
    """Facts in the answer that the sources do not contain."""
    answer, sources = _normalize(answer), _normalize(sources)
    missing = set(_significant_numbers(answer) - _numbers(sources))
    missing |= {f"{n}-ФЗ" for n in FEDERAL_LAW_RE.findall(answer)} - {
        f"{n}-ФЗ" for n in FEDERAL_LAW_RE.findall(sources)
    }
    missing |= _code_articles(answer) - _code_articles(sources)
    return sorted(missing)


def strip(answer: str, violations: list[str]) -> str:
    """Drops sentences that carry a violation; what remains is backed by the sources."""
    kept = []
    for sentence in SENTENCE_RE.split(answer.strip()):
        normalized = _normalize(sentence)
        tokens = _significant_numbers(normalized) | _code_articles(normalized)
        tokens |= {f"{n}-ФЗ" for n in FEDERAL_LAW_RE.findall(normalized)}
        if not tokens & set(violations):
            kept.append(sentence)
    return " ".join(kept).strip()
