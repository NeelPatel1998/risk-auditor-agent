"""Internal retrieval API — Document service only; not exposed via public gateway."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.env import INTERNAL_API_TOKEN
from app.models.schemas import InternalRetrieveRequest, InternalRetrieveResponse
from app.services.vector_store import vector_store

router = APIRouter(tags=["internal"], include_in_schema=False)


def _check_token(x_internal_token: str | None) -> None:
    expected = (INTERNAL_API_TOKEN or "").strip()
    if not expected:
        return
    if (x_internal_token or "").strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing internal token")


@router.post("/internal/v1/retrieve", response_model=InternalRetrieveResponse)
async def internal_retrieve(
    body: InternalRetrieveRequest,
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> InternalRetrieveResponse:
    _check_token(x_internal_token)
    context, sources = await vector_store.search(
        body.query, body.doc_id, n_results=body.n_results
    )
    return InternalRetrieveResponse(context=context, sources=sources)
