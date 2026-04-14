"""RAG retrieval: local vector_store or remote Document service (microservices mode)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.env import DOCUMENT_SERVICE_URL, INTERNAL_API_TOKEN, RETRIEVAL_MODE

logger = logging.getLogger(__name__)


async def search(query: str, doc_id: str, n_results: int = 6) -> tuple[str, list[dict[str, Any]]]:
    """Return (context_string, sources) — same contract as vector_store.search."""
    mode = (RETRIEVAL_MODE or "local").strip().lower()
    if mode == "remote":
        return await _search_remote(query, doc_id, n_results)
    from app.services.vector_store import vector_store

    return await vector_store.search(query, doc_id, n_results=n_results)


async def _search_remote(query: str, doc_id: str, n_results: int) -> tuple[str, list[dict[str, Any]]]:
    base = (DOCUMENT_SERVICE_URL or "").rstrip("/")
    if not base:
        raise RuntimeError("DOCUMENT_SERVICE_URL is required when RETRIEVAL_MODE=remote")

    url = f"{base}/internal/v1/retrieve"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    token = (INTERNAL_API_TOKEN or "").strip()
    if token:
        headers["X-Internal-Token"] = token

    payload = {"query": query, "doc_id": doc_id, "n_results": n_results}

    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    context = str(data.get("context") or "")
    sources = data.get("sources") or []
    if not isinstance(sources, list):
        sources = []
    return context, sources
