"""Question -> grounded answer. Shared by solution.py and the web app."""

import re
from dataclasses import dataclass

import dialog
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


def _plain(text: str) -> str:
    text = _MARKDOWN_RE.sub("", text).strip()
    return text[:MAX_ANSWER_CHARS]


def answer(index: Index, question: str) -> Answer:
    turns = dialog.parse(question)
    blocks = index.context(dialog.search_query(turns))
    reply = llm.chat(prompts.build_messages(blocks, turns))
    return Answer(_plain(reply), blocks)
