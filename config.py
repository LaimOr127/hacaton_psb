"""Runtime settings. Names and fallbacks follow the platform regulation."""

import os
from pathlib import Path


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        # The platform may leave a placeholder equal to the variable name.
        if value and value != name:
            return value
    return default


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(_env(name))))
    except ValueError:
        return default


def _env_float(name: str, default: float, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(_env(name))))
    except ValueError:
        return default


DATA_DIR = Path(_env("DATA_DIR", default="data"))

API_BASE = _env("LLM_BASE_URL", "OPENAI_BASE_URL", "BASE_URL").rstrip("/")
API_KEY = _env("LLM_API_KEY", "OPENAI_API_KEY")
EMBED_KEY = _env("EMBEDDER_API_KEY") or API_KEY
RERANK_KEY = _env("RERANKER_API_KEY") or API_KEY

LLM_MODEL = _env("LLM_MODEL", "GEN_MODEL", "OPENAI_MODEL", default="deepseek/deepseek-v4.1-flash")
EMB_MODEL = _env("EMB_MODEL", default="baai/bge-m3")
RERANKER_MODEL = _env("RERANKER_MODEL", default="qwen/qwen3-reranker-8b")

TEMPERATURE = _env_float("TEMPERATURE", 0.0, 0.0, 1.0)
MAX_TOKENS = _env_int("MAX_TOKENS", 1024, 256, 4096)
MAX_WORKERS = _env_int("MAX_WORKERS", 4, 1, 16)

# The whole run is killed after 20 minutes; stop starting LLM calls well before that.
TIME_BUDGET_SECONDS = _env_int("TIME_BUDGET_SECONDS", 16 * 60, 60, 20 * 60)

# Web app only: the platform passes the knowledge base through DATA_DIR instead.
KB_PATH = Path(_env("KB_PATH", default="data/raw/knowledge-base.zip"))
# Host header allow-list: an unauthenticated internal app must not answer pages that
# rebind their own domain to its address (DNS rebinding).
ALLOWED_HOSTS = [
    host.strip() for host in _env("ALLOWED_HOSTS", default="127.0.0.1,localhost").split(",") if host.strip()
]
