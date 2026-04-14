"""
In-memory BM25 keyword index, built per-document from Chroma chunks.

Complements the dense vector search:
  - Dense (Chroma HNSW) excels at semantic/paraphrase matching
  - BM25 excels at exact-term matching ("Principle 3.6", "E-23", "OSFI")

Results from both are merged via Reciprocal Rank Fusion (RRF) before
being passed to the cross-encoder re-ranker.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

# Simple whitespace + punctuation tokeniser
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+(?:\.[0-9]+)*")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class BM25Index:
    """Per-document BM25 index.  Built lazily on first search for a doc_id,
    then cached until invalidated (upload / delete)."""

    def __init__(self) -> None:
        # doc_id → (BM25Okapi instance, ordered doc list, ordered meta list)
        self._cache: dict[str, tuple[BM25Okapi, list[str], list[dict[str, Any]]]] = {}

    def invalidate(self, doc_id: str | None = None) -> None:
        """Drop cached index for one doc (or all docs if None)."""
        if doc_id is None:
            self._cache.clear()
        else:
            self._cache.pop(doc_id, None)

    def _build(self, doc_id: str, documents: list[str], metadatas: list[dict[str, Any]]) -> None:
        corpus = [_tokenize(d) for d in documents]
        if not corpus:
            return
        bm25 = BM25Okapi(corpus)
        self._cache[doc_id] = (bm25, documents, metadatas)
        logger.debug("BM25 index built for doc_id=%s  chunks=%d", doc_id, len(documents))

    def ensure_built(self, doc_id: str, documents: list[str], metadatas: list[dict[str, Any]]) -> None:
        if doc_id not in self._cache:
            self._build(doc_id, documents, metadatas)

    def search(self, doc_id: str, query: str, n: int = 18) -> list[tuple[str, dict[str, Any], float]]:
        """Return top-n (document, metadata, score) tuples by BM25 relevance.

        Returns an empty list if no index exists for this doc_id.
        """
        entry = self._cache.get(doc_id)
        if entry is None:
            return []
        bm25, documents, metadatas = entry
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores = bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n]
        return [(documents[i], metadatas[i], float(scores[i])) for i in ranked if scores[i] > 0]


bm25_index = BM25Index()
