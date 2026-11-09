"""Hybrid retrieval over knowledge base chunks and assembly of the LLM context.

Lexical (TF-IDF) and dense (bge-m3) rankings are fused with reciprocal rank fusion,
then optionally reordered by the reranker. Dense search and reranking depend on the
API: when it fails, retrieval continues with what is left instead of failing the run.
"""

import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

import relations
from kb import Chunk, Document

Embedder = Callable[[list[str]], np.ndarray]
Reranker = Callable[[str, list[str], int], list[tuple[int, float]]]

TOP_CHUNKS = 12
CHANNEL_CANDIDATES = 40
RERANK_CANDIDATES = 24
RRF_K = 60
EMBED_BATCH = 32
EMBED_WORKERS = 4
# Documents up to this size go to the model whole: a contract answer often needs
# neighbouring clauses (delivery date defined in 3.3, acceptance term in 6.1).
FULL_DOC_CHARS = 6000
MAX_CONTEXT_CHARS = 24000


@dataclass
class Block:
    """One numbered entry of the context: a whole document or a single chunk."""

    doc: Document
    text: str
    address: str
    hits: list[str] = field(default_factory=list)  # chunk ids that matched the query


def _normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def _warn(stage: str, exc: Exception) -> None:
    print(f"{stage} failed, disabled for this run: {type(exc).__name__}", file=sys.stderr)


def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)


class Index:
    def __init__(self, documents: list[Document], embed: Embedder | None = None, rerank: Reranker | None = None):
        self.documents = {doc.doc_id: doc for doc in documents}
        self.chunks = [chunk for doc in documents for chunk in doc.chunks]
        self.links = relations.link(documents)
        self.texts = [self._index_text(c) for c in self.chunks]
        # Character n-grams stand in for lemmatization, which is not available on the
        # platform: "договору" and "договора" share most n-grams, as do "П-17/2024" variants.
        self.vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, preprocessor=_normalize
        )
        self.matrix = self.vectorizer.fit_transform(self.texts)
        self.embed = embed
        self.rerank = rerank
        self.vectors = self._embed_chunks() if embed else None

    def _index_text(self, chunk: Chunk) -> str:
        doc = self.documents[chunk.doc_id]
        heading = doc.text.split("\n", 1)[0]
        return f"{doc.title}\n{heading}\n{chunk.address}\n{chunk.text}"

    def _embed_chunks(self) -> np.ndarray | None:
        batches = [self.texts[i : i + EMBED_BATCH] for i in range(0, len(self.texts), EMBED_BATCH)]
        try:
            with ThreadPoolExecutor(EMBED_WORKERS) as pool:
                return np.vstack(list(pool.map(self.embed, batches)))
        except Exception as exc:  # any API or payload failure disables the dense channel
            _warn("dense index", exc)
            return None

    def _lexical(self, query: str) -> list[int]:
        scores = (self.matrix @ self.vectorizer.transform([query]).T).toarray().ravel()
        best = scores.argsort()[::-1][:CHANNEL_CANDIDATES]
        return [int(i) for i in best if scores[i] > 0]

    def _dense(self, query: str) -> list[int]:
        if self.vectors is None:
            return []
        try:
            query_vector = self.embed([query])[0]
        except Exception as exc:
            # A failing channel is switched off after the first error: retrying it on every
            # question would spend the whole 20-minute budget on timeouts.
            # ponytail: off for the process lifetime; add a cooldown if the web app needs recovery
            _warn("query embedding", exc)
            self.vectors = None
            return []
        scores = self.vectors @ query_vector
        return [int(i) for i in scores.argsort()[::-1][:CHANNEL_CANDIDATES]]

    def _reranked(self, query: str, fused: list[tuple[int, float]]) -> list[tuple[int, float]]:
        if not self.rerank or len(fused) < 2:
            return fused
        candidates = fused[:RERANK_CANDIDATES]
        try:
            order = self.rerank(query, [self.texts[i] for i, _ in candidates], len(candidates))
        except Exception as exc:
            _warn("reranker", exc)
            self.rerank = None
            return fused
        if not order:
            return fused
        ranked = [(candidates[position][0], score) for position, score in order]
        seen = {i for i, _ in ranked}
        return ranked + [pair for pair in fused if pair[0] not in seen]

    def search(self, query: str, top_k: int = TOP_CHUNKS) -> list[tuple[Chunk, float]]:
        rankings = [ranking for ranking in (self._lexical(query), self._dense(query)) if ranking]
        ordered = self._reranked(query, rrf(rankings))
        return [(self.chunks[i], score) for i, score in ordered[:top_k]]

    def context(self, query: str) -> list[Block]:
        blocks: dict[str, Block] = {}
        remaining = MAX_CONTEXT_CHARS

        def add(doc: Document, chunk: Chunk | None = None) -> None:
            nonlocal remaining
            whole = len(doc.text) <= FULL_DOC_CHARS
            if chunk is None and not whole:
                return  # related documents are only added whole
            key = doc.doc_id if whole else chunk.chunk_id
            if key in blocks:
                if chunk:
                    blocks[key].hits.append(chunk.chunk_id)
                return
            text = doc.text if whole else chunk.text
            if len(text) > remaining:
                return
            remaining -= len(text)
            hits = [chunk.chunk_id] if chunk else []
            blocks[key] = Block(doc, text, "" if whole else chunk.address, hits)
            if whole:
                for related in self.links.get(doc.doc_id, []):
                    add(self.documents[related])

        for chunk, _ in self.search(query):
            add(self.documents[chunk.doc_id], chunk)
        return list(blocks.values())
