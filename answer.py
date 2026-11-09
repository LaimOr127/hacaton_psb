"""Question -> grounded answer. Shared by solution.py and the web app."""

import re
from dataclasses import dataclass, field

import dates
import dialog
import guard
import llm
import prompts
from search import Block, Index

MAX_ANSWER_CHARS = 10000
FALLBACK = "Не удалось сформировать ответ по базе знаний из-за технической ошибки. Повторите запрос позже."

_MARKDOWN_RE = re.compile(r"\*\*|^#+\s*", re.MULTILINE)


@dataclass
class Answer:
    text: str
    blocks: list[Block]
    retried: bool = False
    # Facts the model kept asserting after the retry; their sentences were removed.
    dropped: list[str] = field(default_factory=list)


def _plain(text: str) -> str:
    text = _MARKDOWN_RE.sub("", text).strip()
    return text[:MAX_ANSWER_CHARS]


def prepare(index: Index, question: str) -> tuple[list[Block], list[dict]]:
    """Context blocks and the messages for the model; everything except the LLM call."""
    turns = dialog.parse(question)
    blocks = index.context(dialog.search_query(turns))
    event = dates.event_period(dialog.current_message(turns)) or dates.event_period(question)
    return blocks, prompts.build_messages(blocks, turns, event)


def answer(index: Index, question: str) -> Answer:
    blocks, messages = prepare(index, question)
    sources = messages[-1]["content"]

    reply = _plain(llm.chat(messages))
    violations = guard.check(reply, sources)
    if not violations:
        return Answer(reply, blocks)

    retry = [
        *messages,
        {"role": "assistant", "content": reply},
        {"role": "user", "content": prompts.correction(violations)},
    ]
    reply = _plain(llm.chat(retry))
    violations = guard.check(reply, sources)
    if violations:
        reply = guard.strip(reply, violations) or prompts.INSUFFICIENT
    return Answer(reply, blocks, retried=True, dropped=violations)
