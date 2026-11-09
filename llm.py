"""Thin client for the OpenAI-compatible proxy: chat, embeddings, rerank."""

import sys
import time
from functools import cache

import httpx
import numpy as np

import config

RETRY_STATUSES = {429, 500, 502, 503, 504}
ATTEMPTS = 3
TIMEOUT_SECONDS = 60.0


class LLMError(RuntimeError):
    pass


@cache
def _client() -> httpx.Client:
    # httpx.Client is thread-safe; one pool for all workers.
    return httpx.Client(timeout=TIMEOUT_SECONDS)


def _post(path: str, key: str, payload: dict) -> dict:
    if not config.API_BASE or not key:
        raise LLMError("LLM_BASE_URL and LLM_API_KEY must be set")
    error = ""
    for attempt in range(ATTEMPTS):
        if attempt:
            time.sleep(2**attempt)
        try:
            response = _client().post(
                config.API_BASE + path,
                headers={"Authorization": "Bearer " + key},
                json=payload,
            )
        except httpx.TransportError as exc:
            error = type(exc).__name__
            continue
        if response.status_code in RETRY_STATUSES:
            error = f"HTTP {response.status_code}"
            continue
        if response.is_error:
            raise LLMError(f"{path}: HTTP {response.status_code}")
        return response.json()
    print(f"{path}: giving up after {ATTEMPTS} attempts ({error})", file=sys.stderr)
    raise LLMError(f"{path}: {error}")


def chat(messages: list[dict]) -> str:
    result = _post(
        "/chat/completions",
        config.API_KEY,
        {
            "model": config.LLM_MODEL,
            "messages": messages,
            "temperature": config.TEMPERATURE,
            "max_tokens": config.MAX_TOKENS,
        },
    )
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("malformed chat response") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMError("empty chat response")
    return content.strip()


def embed(texts: list[str]) -> np.ndarray:
    """L2-normalized embeddings, one row per input text."""
    result = _post(
        "/embeddings",
        config.EMBED_KEY,
        {
            "model": config.EMB_MODEL,
            "input": texts,
            "encoding_format": "float",
        },
    )
    rows = sorted(result["data"], key=lambda item: item["index"])
    if len(rows) != len(texts):
        raise LLMError("embeddings count mismatch")
    vectors = np.asarray([row["embedding"] for row in rows], dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-12)


def rerank(query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
    """(index into documents, relevance score), best first."""
    result = _post(
        "/rerank",
        config.RERANK_KEY,
        {
            "model": config.RERANKER_MODEL,
            "query": query,
            "documents": documents,
            "top_n": top_n,
        },
    )
    items = result.get("results", result.get("data", []))
    ranked = [(int(item["index"]), float(item.get("relevance_score", 0.0))) for item in items]
    return [(i, score) for i, score in ranked if 0 <= i < len(documents)]
