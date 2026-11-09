"""Retrieval over knowledge base chunks and assembly of the LLM context."""

from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer

from kb import Chunk, Document

TOP_CHUNKS = 12
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


class Index:
    def __init__(self, documents: list[Document]):
        self.documents = {doc.doc_id: doc for doc in documents}
        self.chunks = [chunk for doc in documents for chunk in doc.chunks]
        # Character n-grams stand in for lemmatization, which is not available on the
        # platform: "договору" and "договора" share most n-grams, as do "П-17/2024" variants.
        self.vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, preprocessor=_normalize
        )
        self.matrix = self.vectorizer.fit_transform([self._index_text(c) for c in self.chunks])

    def _index_text(self, chunk: Chunk) -> str:
        doc = self.documents[chunk.doc_id]
        heading = doc.text.split("\n", 1)[0]
        return f"{doc.title}\n{heading}\n{chunk.address}\n{chunk.text}"

    def search(self, query: str, top_k: int = TOP_CHUNKS) -> list[tuple[Chunk, float]]:
        scores = (self.matrix @ self.vectorizer.transform([query]).T).toarray().ravel()
        best = scores.argsort()[::-1][:top_k]
        return [(self.chunks[i], float(scores[i])) for i in best if scores[i] > 0]

    def context(self, query: str) -> list[Block]:
        blocks: dict[str, Block] = {}
        used = 0
        for chunk, _ in self.search(query):
            doc = self.documents[chunk.doc_id]
            whole = len(doc.text) <= FULL_DOC_CHARS
            key = doc.doc_id if whole else chunk.chunk_id
            if key in blocks:
                blocks[key].hits.append(chunk.chunk_id)
                continue
            text = doc.text if whole else chunk.text
            if used + len(text) > MAX_CONTEXT_CHARS:
                continue
            used += len(text)
            blocks[key] = Block(doc, text, "" if whole else chunk.address, [chunk.chunk_id])
        return list(blocks.values())
