"""
Persistent embedding cache backed by SQLite.

Avoids redundant OpenRouter API calls when the same text chunk is
re-embedded (e.g. re-uploading the same PDF, or identical passages
across different documents).

Storage: a single SQLite table in the same data/ directory as Chroma.
Key is a SHA-256 hash of the text; value is the embedding vector
serialised as JSON.  Average row size ≈ 10 KB for a 1536-dim vector.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from app.env import CHROMA_DIR

logger = logging.getLogger(__name__)

_DB_PATH = str(Path(CHROMA_DIR).parent / "embed_cache.db")

_DDL = """
CREATE TABLE IF NOT EXISTS embeddings (
    text_hash  TEXT PRIMARY KEY,
    embedding  TEXT NOT NULL
);
"""


class EmbedCache:
    def __init__(self) -> None:
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_DDL)
            logger.info("Embedding cache opened at %s", _DB_PATH)
        return self._conn

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get_many(self, texts: list[str]) -> list[list[float] | None]:
        """Look up cached embeddings.  Returns None for misses."""
        conn = self._get_conn()
        results: list[list[float] | None] = [None] * len(texts)
        hashes = [self._hash(t) for t in texts]

        placeholders = ",".join("?" for _ in hashes)
        if not placeholders:
            return results
        rows = conn.execute(
            f"SELECT text_hash, embedding FROM embeddings WHERE text_hash IN ({placeholders})",
            hashes,
        ).fetchall()

        hit_map = {row[0]: json.loads(row[1]) for row in rows}
        for i, h in enumerate(hashes):
            if h in hit_map:
                results[i] = hit_map[h]
        return results

    def put_many(self, texts: list[str], embeddings: list[list[float]]) -> None:
        """Store embeddings in the cache."""
        conn = self._get_conn()
        rows = [
            (self._hash(t), json.dumps(e))
            for t, e in zip(texts, embeddings)
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO embeddings (text_hash, embedding) VALUES (?, ?)",
            rows,
        )
        conn.commit()

    def stats(self) -> dict[str, Any]:
        conn = self._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        return {"cached_embeddings": count, "db_path": _DB_PATH}


embed_cache = EmbedCache()
