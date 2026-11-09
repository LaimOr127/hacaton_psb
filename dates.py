"""Dates in questions and documents.

The model is bad at comparing dates across several documents, so the code computes
which edition applies to the event date and which law points changed after it, and
passes the result to the model as notes next to each document.
"""

import calendar
import re
from datetime import date

MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}  # fmt: skip
# "ма" alone would match "максимальный"; May needs its inflection letter.
MONTH = "(" + "|".join(("ма[йяе]" if stem == "ма" else stem) + r"\w*" for stem in MONTHS) + ")"

NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
WORD_DATE_RE = re.compile(rf"\b(\d{{1,2}})\s+{MONTH}\s+(\d{{4}})", re.IGNORECASE)
MONTH_YEAR_RE = re.compile(rf"\b{MONTH}\s+(\d{{4}})", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(?:в|за|на)\s+(\d{4})\s*(?:год|г\.)", re.IGNORECASE)
DATE = rf"(\d{{1,2}}\.\d{{1,2}}\.\d{{4}}|\d{{1,2}}\s+{MONTH}\s+\d{{4}})"
VALID_FROM_RE = re.compile(rf"(?:действует\s+с|редакция\s+от)\s+{DATE}", re.IGNORECASE)
VALID_TO_RE = re.compile(rf"утратил\w*\s+силу\s+с\s+{DATE}", re.IGNORECASE)
CHANGED_RE = re.compile(rf"(?:изменен|дополнен|изложен)\w*[^.\n]{{0,40}}?\s+с\s+{DATE}", re.IGNORECASE)

Period = tuple[date, date]  # inclusive


def _month(word: str) -> int:
    word = word.lower()
    return next(number for stem, number in MONTHS.items() if word.startswith(stem))


def parse_date(text: str) -> date | None:
    try:
        if match := NUMERIC_DATE_RE.search(text):
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        if match := WORD_DATE_RE.search(text):
            return date(int(match.group(3)), _month(match.group(2)), int(match.group(1)))
    except (ValueError, StopIteration):
        return None
    return None


def event_period(text: str) -> Period | None:
    """The first date the question mentions, widened to a month or a year when vague."""
    candidates: list[tuple[int, Period]] = []
    for match in NUMERIC_DATE_RE.finditer(text):
        if day := parse_date(match.group()):
            candidates.append((match.start(), (day, day)))
    for match in WORD_DATE_RE.finditer(text):
        if day := parse_date(match.group()):
            candidates.append((match.start(), (day, day)))
    for match in MONTH_YEAR_RE.finditer(text):
        year, month = int(match.group(2)), _month(match.group(1))
        last = calendar.monthrange(year, month)[1]
        candidates.append((match.start(), (date(year, month, 1), date(year, month, last))))
    for match in YEAR_RE.finditer(text):
        year = int(match.group(1))
        candidates.append((match.start(), (date(year, 1, 1), date(year, 12, 31))))
    # A day-precise date and its month/year overlap at the same position; prefer the narrowest.
    candidates.sort(key=lambda item: (item[0], item[1][1] - item[1][0]))
    return candidates[0][1] if candidates else None


def validity(text: str) -> tuple[date | None, date | None]:
    """Edition validity stated in the document header: (from, until exclusive)."""
    head = "\n".join(text.split("\n", 6)[:6])
    start = VALID_FROM_RE.search(head)
    end = VALID_TO_RE.search(head)
    return (parse_date(start.group(1)) if start else None, parse_date(end.group(1)) if end else None)


def changed_since(text: str) -> list[date]:
    return [day for match in CHANGED_RE.finditer(text) if (day := parse_date(match.group(1)))]


def _fmt(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def edition_note(doc_text: str, event: Period | None) -> str:
    start, end = validity(doc_text)
    if not start and not end:
        return ""
    span = f"с {_fmt(start)}" if start else ""
    span += f" до {_fmt(end)} (утратила силу)" if end else " (действующая)"
    note = f"Срок действия редакции: {span.strip()}."
    if event:
        applies = (not start or event[1] >= start) and (not end or event[0] < end)
        note += " К дате события применима." if applies else " К дате события не применима."
    return note


def law_change_note(chunk_text: str, event: Period | None) -> str:
    if not event:
        return ""
    later = sorted({day for day in changed_since(chunk_text) if day > event[0]})
    if not later:
        return ""
    return (
        f"Внимание: норма в этом тексте изменена с {_fmt(later[-1])}, позже даты события. "
        "В базе только действующая редакция; редакции на дату события в базе нет."
    )
