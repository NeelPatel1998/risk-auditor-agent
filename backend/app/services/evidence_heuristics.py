"""Heuristics to prefer narrative evidence over disclosure-table imperatives in RAG."""
from __future__ import annotations

import re
from typing import Any

_DISCLOSURE_LINE = re.compile(
    r"(?im)(^\s*[a-z]\)\s*Describe\b|"
    r"^Describe the\b|"
    r"Disclosure expectation|"
    r"Disclosure element)",
)


def classify_chunk_text(text: str) -> str:
    """
    Rough class for stored chunk metadata.
    ``disclosure_checklist`` = annex-style imperatives / table prompts.
    ``table_dense`` = many short lines (tabular extraction).
    ``narrative`` = default prose.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "narrative"
    n = len(lines)
    disc_hits = sum(1 for ln in lines if _DISCLOSURE_LINE.search(ln))
    short_lines = sum(1 for ln in lines if len(ln) < 90)
    if disc_hits >= 2 or (disc_hits >= 1 and short_lines / n >= 0.45):
        return "disclosure_checklist"
    if short_lines / n >= 0.55 and n >= 4:
        return "table_dense"
    return "narrative"


def query_requests_disclosure_context(query: str) -> bool:
    q = (query or "").lower()
    needles = (
        "disclos",
        "annex ",
        "annex-",
        "filing",
        "reporting obligation",
        "must we disclose",
        "disclosure requirement",
        "disclosure expectation",
        "tabular disclosure",
    )
    return any(x in q for x in needles)


def rrf_adjustment(doc_text: str, query: str, evidence_class: str | None) -> float:
    """
    Small additive tweak to RRF score so narrative chunks rank above checklist rows
    when the user is not explicitly asking about disclosure obligations.
    """
    ec = evidence_class or classify_chunk_text(doc_text)
    if query_requests_disclosure_context(query):
        return 0.0
    if ec == "disclosure_checklist":
        return -0.012
    if ec == "table_dense":
        return -0.006
    return 0.0


def evidence_class_from_meta(meta: dict[str, Any] | None) -> str | None:
    if not meta:
        return None
    raw = meta.get("evidence_class")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None
