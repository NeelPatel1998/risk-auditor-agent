from __future__ import annotations

import logging
import re
from typing import Any

import chromadb

from app.env import CHROMA_DIR, EMBED_BATCH_SIZE, RETRIEVAL_MAX_DISTANCE
from app.services.bm25_index import bm25_index
from app.services.evidence_heuristics import evidence_class_from_meta, rrf_adjustment
from app.utils.llm import llm_client

logger = logging.getLogger(__name__)

# RRF constant — standard value from the Cormack et al. paper
_RRF_K = 60


def _format_hits(
    documents: list[list[str]],
    metadatas: list[list[dict[str, Any]]] | None,
    distances: list[list[float]] | None,
) -> tuple[str, list[dict[str, Any]]]:
    """Build RAG context string and structured sources for UI.

    Sources are always numbered 1, 2, 3 … sequentially so the numbers the LLM
    sees in the context string exactly match the ``index`` values in the returned
    sources list.  Previously, distance-filtered-out chunks caused gaps in the
    numbering (e.g. [Source 2], [Source 4]) which led the model to cite wrong
    source numbers.
    """
    if not documents or not documents[0]:
        return "", []
    docs = documents[0]
    metas = (metadatas or [[]])[0] if metadatas else []
    dists = (distances or [[]])[0] if distances else []

    lines: list[str] = []
    sources: list[dict[str, Any]] = []
    for use_distance_cutoff in (True, False):
        lines.clear()
        sources.clear()
        new_idx = 1  # always sequential — no gaps
        for i, doc in enumerate(docs):
            dist = dists[i] if i < len(dists) else None
            if use_distance_cutoff and dist is not None and float(dist) > RETRIEVAL_MAX_DISTANCE:
                continue
            lines.append(f"[Source {new_idx}]\n{doc}")
            meta = metas[i] if i < len(metas) else {}
            sources.append(
                {
                    "index": new_idx,
                    "content": doc[:2000],
                    "distance": float(dist) if dist is not None else None,
                    "metadata": meta,
                }
            )
            new_idx += 1
        if lines or not use_distance_cutoff:
            break
    if not lines:
        return "", []
    return "\n\n".join(lines), sources


def _chroma_metadata_for_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    """Chroma allows only str, int, float, bool — no None."""
    md = dict(chunk.get("metadata") or {})
    md["doc_id"] = str(chunk["doc_id"])
    md["chunk_id"] = str(chunk["chunk_id"])
    md["char_start"] = int(md.pop("start", 0) or 0)
    md["char_end"] = int(md.pop("end", 0) or 0)
    out: dict[str, Any] = {}
    for k, v in md.items():
        if v is None:
            continue
        key = str(k)
        if isinstance(v, (str, int, float, bool)):
            out[key] = v
        else:
            out[key] = str(v)[:512]
        if key == "filename" and isinstance(out.get(key), str) and len(out[key]) > 512:
            out[key] = out[key][:512]
    return out


class VectorStore:
    def __init__(self) -> None:
        self.client = chromadb.PersistentClient(path=CHROMA_DIR)
        self.collection = self.client.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "l2"},
        )

    async def add_chunks(self, chunks: list[dict[str, Any]]) -> None:
        if not chunks:
            return
        batch_size = EMBED_BATCH_SIZE
        doc_ids_seen: set[str] = set()
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            contents = [c["content"] for c in batch]
            embeddings = await llm_client.embed(contents)
            ids = [c["chunk_id"] for c in batch]
            metadatas = [_chroma_metadata_for_chunk(c) for c in batch]
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=contents,
                metadatas=metadatas,
            )
            for c in batch:
                doc_ids_seen.add(str(c["doc_id"]))
        for did in doc_ids_seen:
            bm25_index.invalidate(did)

    def _ensure_bm25(self, doc_id: str) -> None:
        """Lazily build the BM25 index for this document from Chroma chunks."""
        doc_id_s = str(doc_id)
        try:
            res = self.collection.get(
                where={"doc_id": doc_id_s},
                include=["documents", "metadatas"],
                limit=5000,
            )
        except Exception:
            return
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        if docs:
            bm25_index.ensure_built(doc_id_s, docs, metas)

    async def search(
        self,
        query: str,
        doc_id: str,
        n_results: int = 6,
    ) -> tuple[str, list[dict[str, Any]]]:
        from app.services.reranker import rerank

        q_emb = await llm_client.embed([query])
        doc_id_s = str(doc_id)

        # ── Dense retrieval (Chroma HNSW) ──
        fetch_n = min(n_results * 3, 30)

        res = self.collection.query(
            query_embeddings=q_emb,
            n_results=fetch_n,
            where={"doc_id": doc_id_s},
            include=["documents", "metadatas", "distances"],
        )
        documents = res.get("documents") or []
        metadatas = res.get("metadatas")
        distances = res.get("distances")

        if not documents or not documents[0]:
            wide = self.collection.query(
                query_embeddings=q_emb,
                n_results=min(fetch_n * 4, 80),
                include=["documents", "metadatas", "distances"],
            )
            d0 = wide.get("documents") or [[]]
            m0 = wide.get("metadatas") or [[]]
            di0 = wide.get("distances") or [[]]
            fd, fm, fdi = [], [], []
            for doc, meta, dist in zip(d0[0], m0[0], di0[0]):
                mid = meta.get("doc_id") if meta else None
                if str(mid) == doc_id_s:
                    fd.append(doc)
                    fm.append(meta or {})
                    fdi.append(dist)
                if len(fd) >= fetch_n:
                    break
            documents = [fd]
            metadatas = [fm]
            distances = [fdi]

        dense_docs:  list[str]  = documents[0] if documents else []
        dense_metas: list[dict] = (metadatas or [[]])[0] if metadatas else []
        dense_dists: list[float] = (distances or [[]])[0] if distances else []

        # ── BM25 keyword retrieval ──
        self._ensure_bm25(doc_id_s)
        bm25_hits = bm25_index.search(doc_id_s, query, n=fetch_n)

        # ── Reciprocal Rank Fusion (RRF) ──
        # Merge dense and BM25 ranked lists into one using:
        #   score(d) = Σ 1/(k + rank_i)  for each retrieval system i
        rrf: dict[str, float] = {}
        doc_lookup: dict[str, tuple[str, dict, float]] = {}

        for rank, (doc, meta, dist) in enumerate(zip(dense_docs, dense_metas, dense_dists)):
            key = doc[:200]
            rrf[key] = rrf.get(key, 0.0) + 1.0 / (_RRF_K + rank + 1)
            if key not in doc_lookup:
                doc_lookup[key] = (doc, meta, dist)

        for rank, (doc, meta, _score) in enumerate(bm25_hits):
            key = doc[:200]
            rrf[key] = rrf.get(key, 0.0) + 1.0 / (_RRF_K + rank + 1)
            if key not in doc_lookup:
                doc_lookup[key] = (doc, meta, 0.0)

        def _rrf_plus_evidence(k: str) -> float:
            doc, meta, _dist = doc_lookup[k]
            ec = evidence_class_from_meta(meta if isinstance(meta, dict) else None)
            return rrf[k] + rrf_adjustment(doc, query, ec)

        sorted_keys = sorted(rrf.keys(), key=_rrf_plus_evidence, reverse=True)
        candidate_n = min(len(sorted_keys), fetch_n)
        take = sorted_keys[:candidate_n]

        docs_flat = [doc_lookup[k][0] for k in take]
        metas_flat = [doc_lookup[k][1] for k in take]
        dists_flat = [doc_lookup[k][2] for k in take]

        logger.debug(
            "Hybrid search: dense=%d  bm25=%d  fused=%d  candidates=%d",
            len(dense_docs), len(bm25_hits), len(sorted_keys), candidate_n,
        )

        # ── Cross-encoder re-rank ──
        if len(docs_flat) > n_results:
            top_idxs = await rerank(query, docs_flat, n_results)
            docs_flat = [docs_flat[i] for i in top_idxs]
            metas_flat = [metas_flat[i] for i in top_idxs] if metas_flat else []
            dists_flat = [dists_flat[i] for i in top_idxs] if dists_flat else []

        return _format_hits([docs_flat], [metas_flat] if metas_flat else None, [dists_flat] if dists_flat else None)

    def list_documents(self, limit: int = 500) -> list[dict[str, Any]]:
        """Unique doc_ids with filename from chunk metadata (requires filename on ingest).

        Documents whose doc_id starts with ``eval__`` are ghost vectors
        used only by the evaluation harness — they are hidden from the UI.
        """
        raw = self.collection.get(include=["metadatas"], limit=limit)
        metas = raw.get("metadatas") or []
        by_doc: dict[str, dict[str, Any]] = {}
        for mid in metas:
            if not isinstance(mid, dict):
                continue
            did = str(mid.get("doc_id") or "").strip()
            if not did or did.startswith("eval__"):
                continue
            fn = mid.get("filename")
            fname = fn.strip() if isinstance(fn, str) and fn.strip() else None
            if did not in by_doc:
                by_doc[did] = {"doc_id": did, "filename": fname or "Document"}
            if fname:
                by_doc[did]["filename"] = fname
        return sorted(by_doc.values(), key=lambda x: str(x["filename"]).lower())

    def get_all_chunks(self, doc_id: str) -> list[dict[str, Any]]:
        """Return every stored chunk for a document, ordered by page then position."""
        doc_id_s = str(doc_id)
        try:
            res = self.collection.get(
                where={"doc_id": doc_id_s},
                include=["documents", "metadatas"],
                limit=2000,
            )
        except Exception:
            return []
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        chunks: list[dict[str, Any]] = []
        for i, content in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            chunks.append({"content": content, "metadata": meta})

        def sort_key(c: dict[str, Any]) -> tuple[int, int]:
            m = re.search(r"\[Page\s*(\d+)\]", c.get("content", ""))
            page = int(m.group(1)) if m else 0
            char_start = int(c.get("metadata", {}).get("char_start", 0) or 0)
            return (page, char_start)

        chunks.sort(key=sort_key)
        return chunks

    def delete_by_doc_id(self, doc_id: str) -> int:
        """Remove every chunk for this doc_id from Chroma. Returns how many rows were removed."""
        bm25_index.invalidate(str(doc_id))
        doc_id_s = str(doc_id)
        try:
            res = self.collection.delete(where={"doc_id": doc_id_s})
            return int(res.get("deleted", 0)) if isinstance(res, dict) else 0
        except Exception:
            # Fallback: paginated get + delete (legacy metadata types / filter quirks)
            total = 0
            while True:
                got = self.collection.get(where={"doc_id": doc_id_s}, include=[], limit=5000)
                ids = got.get("ids") or []
                if not ids:
                    break
                self.collection.delete(ids=ids)
                total += len(ids)
                if len(ids) < 5000:
                    break
            return total

    def delete_all_chunks(self) -> int:
        """Remove every vector row (full reset). Returns approximate rows removed."""
        bm25_index.invalidate()
        total = 0
        while True:
            got = self.collection.get(include=[], limit=5000)
            ids = got.get("ids") or []
            if not ids:
                break
            self.collection.delete(ids=ids)
            total += len(ids)
        return total


vector_store = VectorStore()
