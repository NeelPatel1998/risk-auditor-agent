"""Unit tests for RAG evidence-type heuristics."""
from app.services.evidence_heuristics import (
    classify_chunk_text,
    query_requests_disclosure_context,
    rrf_adjustment,
)


def test_classify_narrative_prose():
    text = (
        "[Page 1]\nThe board of directors oversees climate-related risks and ensures "
        "that management implements appropriate strategies across the institution."
    )
    assert classify_chunk_text(text) == "narrative"


def test_classify_disclosure_checklist():
    text = (
        "[Page 18]\nDisclosure expectation\n"
        "a) Describe the climate-related risks the FRFI has identified.\n"
        "b) Describe management's role in monitoring climate-related risks.\n"
    )
    assert classify_chunk_text(text) == "disclosure_checklist"


def test_query_disclosure_boosts_neutral():
    q = "What are the key roles and responsibilities?"
    assert query_requests_disclosure_context(q) is False
    assert rrf_adjustment("a) Describe the risk.", q, "disclosure_checklist") < 0


def test_query_disclosure_no_penalty_when_user_asks_disclosure():
    q = "What must we disclose in Annex 2-2?"
    assert query_requests_disclosure_context(q) is True
    assert rrf_adjustment("a) Describe the risk.", q, "disclosure_checklist") == 0.0
