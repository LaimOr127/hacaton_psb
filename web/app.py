"""HTTP API and static chat UI over the same pipeline the platform runs.

uvicorn web.app:app --host 127.0.0.1 --port 8000
"""

import re
import sys
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

import config
import kb
import llm
from answer import MAX_ANSWER_CHARS, answer
from citations import sources
from search import Index

STATIC_DIR = Path(__file__).parent / "static"
MAX_QUESTION_CHARS = 4000
MAX_MESSAGES = 20
RATE_LIMIT = 20
RATE_WINDOW_SECONDS = 60
DOC_ID_RE = re.compile(r"^[0-9a-f]{10}$")
ROLE_LABELS = {"user": "Пользователь", "assistant": "Ассистент"}
# A message must not open a new turn from inside its own text.
TURN_MARKER_RE = re.compile(r"^(\s*)(Пользователь|Ассистент)\s*:", re.MULTILINE)
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class Message(BaseModel):
    role: Literal["user", "assistant"]
    # Assistant turns echo earlier answers, which may be longer than a question.
    text: str = Field(min_length=1, max_length=MAX_ANSWER_CHARS)

    @model_validator(mode="after")
    def question_size(self) -> "Message":
        if self.role == "user" and len(self.text) > MAX_QUESTION_CHARS:
            raise ValueError(f"a question is limited to {MAX_QUESTION_CHARS} characters")
        return self


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=MAX_MESSAGES)

    @model_validator(mode="after")
    def ends_with_user(self) -> "ChatRequest":
        if self.messages[-1].role != "user":
            raise ValueError("the last message must come from the user")
        return self


class RateLimiter:
    """Sliding window per client address.

    ponytail: in-process memory; behind several workers or a proxy use a shared store
    and a trusted forwarded-for header.
    """

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self.calls: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            calls = self.calls[key]
            while calls and now - calls[0] > self.window:
                calls.popleft()
            if len(calls) >= self.limit:
                return False
            calls.append(now)
            return True


def to_question(messages: list[Message]) -> str:
    """Same text format the platform uses for dialogs, so both paths share dialog.parse."""
    texts = [TURN_MARKER_RE.sub(r"\1\2 —", m.text.strip()) for m in messages]
    if len(messages) == 1:
        return texts[0]
    return "\n".join(f"{ROLE_LABELS[m.role]}: {text}" for m, text in zip(messages, texts, strict=True))


def build_index() -> Index:
    use_api = bool(config.API_BASE and config.API_KEY)
    return Index(
        kb.load_zip(config.KB_PATH),
        embed=llm.embed if use_api else None,
        rerank=llm.rerank if use_api else None,
    )


def create_app(index: Index | None = None, allowed_hosts: list[str] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.index = index or build_index()
        yield

    app = FastAPI(title="Юридический ассистент", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.limiter = RateLimiter(RATE_LIMIT, RATE_WINDOW_SECONDS)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or config.ALLOWED_HOSTS)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health(request: Request) -> dict:
        index: Index = request.app.state.index
        return {"status": "ok", "documents": len(index.documents), "dense": index.vectors is not None}

    @app.get("/api/documents")
    def documents(request: Request) -> list[dict]:
        docs = sorted(request.app.state.index.documents.values(), key=lambda d: (d.kind != "company", d.title))
        return [{"doc_id": d.doc_id, "title": d.title, "kind": d.kind} for d in docs]

    @app.get("/api/documents/{doc_id}")
    def document(doc_id: str, request: Request) -> dict:
        doc = request.app.state.index.documents.get(doc_id) if DOC_ID_RE.match(doc_id) else None
        if doc is None:
            raise HTTPException(404, "Документ не найден")
        chunks = [{"chunk_id": c.chunk_id, "address": c.address, "start": c.start, "end": c.end} for c in doc.chunks]
        return {"doc_id": doc.doc_id, "title": doc.title, "kind": doc.kind, "text": doc.text, "chunks": chunks}

    @app.post("/api/chat")
    def chat(body: ChatRequest, request: Request) -> dict:
        client = request.client.host if request.client else "unknown"
        if not request.app.state.limiter.allow(client):
            raise HTTPException(429, "Слишком много запросов. Повторите через минуту.")
        try:
            result = answer(request.app.state.index, to_question(body.messages))
        except llm.LLMError as exc:
            print(f"chat: {type(exc).__name__}", file=sys.stderr)
            raise HTTPException(503, "Языковая модель недоступна. Повторите запрос позже.") from None
        return {
            "answer": result.text,
            "sources": [asdict(source) for source in sources(result.text, result.blocks)],
            "trimmed": bool(result.dropped),
        }

    return app


app = create_app()
