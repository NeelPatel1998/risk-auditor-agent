"""
Cross-encoder re-ranker using sentence-transformers.

The model is loaded eagerly via ``warm_up()`` at server startup so the
first user query does not pay the ~3 s cold-start penalty.  If startup
warm-up is skipped, the model still loads lazily on the first call.

Falls back to the original dense-retrieval order if the model
cannot be loaded (e.g. sentence-transformers not installed).
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_reranker = None          # cached CrossEncoder instance (None = unavailable)
_load_attempted = False   # only try once to avoid repeated failures
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reranker")


def _load_once() -> None:
    global _reranker, _load_attempted
    if _load_attempted:
        return
    _load_attempted = True
    try:
        from sentence_transformers.cross_encoder import CrossEncoder  # type: ignore[import]

        _reranker = CrossEncoder(_RERANKER_MODEL, max_length=512)
        logger.info("Re-ranker loaded: %s", _RERANKER_MODEL)
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Re-ranker unavailable (%s). "
            "Run `pip install sentence-transformers` to enable it. "
            "Falling back to dense-retrieval order.",
            exc,
        )


async def warm_up() -> None:
    """Eagerly load the model and run a dummy prediction to pre-warm caches.

    Call this during FastAPI lifespan so the first real query is fast.
    Runs in the thread-pool executor to keep the event loop free.
    """
    loop = asyncio.get_event_loop()

    def _warm() -> None:
        _load_once()
        if _reranker is not None:
            _reranker.predict([["warm-up query", "warm-up passage"]])
            logger.info("Re-ranker warm-up complete")

    await loop.run_in_executor(_executor, _warm)


def _rerank_sync(query: str, candidates: list[str], top_n: int) -> list[int]:
    """Synchronous CPU-bound scoring — run inside the thread-pool executor."""
    _load_once()
    if _reranker is None or not candidates:
        return list(range(min(top_n, len(candidates))))
    pairs = [[query, c] for c in candidates]
    scores: list[float] = _reranker.predict(pairs).tolist()
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return ranked[:top_n]


async def rerank(query: str, candidates: list[str], top_n: int) -> list[int]:
    """Return the indices of the top-*top_n* candidates in relevance order.

    Runs the cross-encoder in a thread-pool to keep the event loop free.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _rerank_sync, query, candidates, top_n)
