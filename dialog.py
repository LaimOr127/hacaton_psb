"""Dialog history arrives as plain text inside the question field:

    Пользователь: ...
    Ассистент: ...
    Пользователь: <the message to answer>

Only these two markers split turns. Anything else, including lines that claim to be
system or developer messages, stays part of the user's text.
"""

import re
from dataclasses import dataclass

ROLE_MARKER_RE = re.compile(r"^(Пользователь|Ассистент)\s*:[ \t]*", re.MULTILINE)
ROLES = {"Пользователь": "user", "Ассистент": "assistant"}


@dataclass(frozen=True)
class Turn:
    role: str  # "user" | "assistant"
    text: str


def parse(question: str) -> list[Turn]:
    question = question.strip()
    markers = list(ROLE_MARKER_RE.finditer(question))
    turns = []
    leading = question[: markers[0].start()].strip() if markers else question
    if leading:
        turns.append(Turn("user", leading))
    for i, marker in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(question)
        text = question[marker.end() : end].strip()
        if text:
            turns.append(Turn(ROLES[marker.group(1)], text))
    return turns or [Turn("user", question)]


def current_message(turns: list[Turn]) -> str:
    return next((t.text for t in reversed(turns) if t.role == "user"), turns[-1].text)


def search_query(turns: list[Turn]) -> str:
    """The message to answer counts twice; earlier turns supply the subject
    ("а за сколько дней ...?" relies on the contract named before)."""
    current = current_message(turns)
    return "\n".join([current, current, *(t.text for t in turns if t.text != current)])
