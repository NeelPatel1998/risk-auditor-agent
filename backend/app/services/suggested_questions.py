"""LLM generation of suggested chat questions from a sample of the document body."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.services import thread_store
from app.utils.llm import llm_client

logger = logging.getLogger(__name__)

_MAX_EXCERPT_CHARS = 4000
_SKIP_FRONT_CHUNKS = 8   # skip cover page, ToC, preamble (~3-5 pages)


def _build_excerpt(chunks: list[dict[str, Any]]) -> str:
    """Sample ~4000 chars spread across the document body so the LLM sees
    topics from the beginning, middle, and end — not just one section.

    Skips the first _SKIP_FRONT_CHUNKS to avoid cover/ToC content.
    Falls back gracefully for short documents.
    """
    body = chunks[_SKIP_FRONT_CHUNKS:] if len(chunks) > _SKIP_FRONT_CHUNKS else chunks
    if not body:
        body = chunks

    total = len(body)
    if total == 0:
        return ""

    # Pick three evenly-spaced windows: early body, middle, late
    third = max(1, total // 3)
    windows = [
        body[:third],          # early body
        body[third:2*third],   # middle
        body[2*third:],        # late
    ]

    chars_per_window = _MAX_EXCERPT_CHARS // 3
    parts: list[str] = []
    for window in windows:
        accumulated = 0
        for c in window:
            text = (c.get("content") or "").strip()
            if not text:
                continue
            parts.append(text)
            accumulated += len(text)
            if accumulated >= chars_per_window:
                break

    raw = "\n\n---\n\n".join(parts)
    if len(raw) > _MAX_EXCERPT_CHARS:
        raw = raw[:_MAX_EXCERPT_CHARS] + "\n…"
    return raw


def _build_messages(filename: str, excerpt: str) -> list[dict[str, str]]:
    system = (
        "You suggest 5 opening questions for a risk officer who just uploaded a regulatory PDF "
        "and wants to understand it quickly. "
        "Output ONLY a raw JSON array of exactly 5 strings — no markdown, no explanation. "
        "Each question must: "
        "(1) be something a real person would naturally ask, not an exam question; "
        "(2) have a clear, substantive answer inside the document; "
        "(3) cover a different topic so all 5 together give a broad view of the document; "
        "(4) be concise — under 100 characters. "
        "Do NOT use phrases like 'exactly as stated', 'quote the', 'list verbatim', or 'as numbered'. "
        "Do NOT mention page numbers. "
        "Do NOT ask the user to summarize the whole document."
    )

    ex1_user = (
        'Filename: "OSFI_E-23_Model_Risk_Management.pdf"\n'
        "Excerpt:\n"
        "[Page 6]\nPrinciple 1: Governance. The board is responsible for overseeing model risk.\n"
        "Senior management must establish a model risk management framework.\n"
        "[Page 10]\nModel Validation. Independent validation must assess conceptual soundness, "
        "data quality, and ongoing performance.\n"
        "[Page 18]\nModel Inventory. Institutions must maintain a complete and current inventory of all models."
    )
    ex1_asst = json.dumps([
        "What are the board's responsibilities for model risk governance?",
        "What does independent model validation involve?",
        "What information must be kept in the model inventory?",
        "How should institutions categorize their models by risk?",
        "What triggers a model to be reviewed or retired?",
    ], ensure_ascii=False)

    ex2_user = (
        'Filename: "AML_Compliance_Framework_2025.pdf"\n'
        "Excerpt:\n"
        "[Page 4]\nScope. This framework applies to all federally regulated financial institutions.\n"
        "[Page 9]\nCustomer Due Diligence. Institutions must verify customer identity and assess risk at onboarding.\n"
        "[Page 15]\nSuspicious Transaction Reporting. Transactions above $10,000 must be reported within 30 days."
    )
    ex2_asst = json.dumps([
        "Which institutions does this framework apply to?",
        "What is required during customer onboarding under this framework?",
        "When must a suspicious transaction be reported?",
        "How should institutions assess customer risk levels?",
        "What are the consequences of non-compliance with reporting requirements?",
    ], ensure_ascii=False)

    final_user = (
        f'Filename: "{filename}"\nExcerpt:\n{excerpt}\n\n'
        "Generate exactly 5 questions as a JSON array."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": ex1_user},
        {"role": "assistant", "content": ex1_asst},
        {"role": "user", "content": ex2_user},
        {"role": "assistant", "content": ex2_asst},
        {"role": "user", "content": final_user},
    ]


_JSON_ARRAY = re.compile(r"\[[\s\S]*\]")
_PAGE_REF = re.compile(r"(?i)\bpage\s*\d+\b|\[page\s*\d+\]")


def _parse_questions(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    if "```" in text:
        for part in text.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("["):
                text = part
                break
    m = _JSON_ARRAY.search(text)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for x in data:
        if not isinstance(x, str) or not x.strip():
            continue
        q = x.strip()
        # Strip any page references that slipped through
        q = re.sub(r"(?i)\s*\(?\s*page\s*\d+\s*\)?", "", q).strip()
        q = re.sub(r"\s+\?", "?", q).strip()
        if len(q) < 10:
            continue
        if len(q) > 200:
            q = q[:197] + "…"
        out.append(q)
    # Deduplicate
    seen: set[str] = set()
    deduped: list[str] = []
    for q in out:
        key = q.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(q)
    return deduped[:5]


async def generate_and_store(doc_id: str, filename: str, chunks: list[dict[str, Any]]) -> None:
    """Generate suggested questions and persist to SQLite."""
    user_id = ""
    try:
        user_id = str((chunks[0].get("metadata") or {}).get("user_id") or "").strip()
    except Exception:
        pass

    excerpt = _build_excerpt(chunks)
    if not excerpt.strip():
        await thread_store.upsert_suggestions(doc_id, [], user_id=user_id, status="failed")
        return

    messages = _build_messages(filename, excerpt)
    try:
        raw = await llm_client.chat(messages, temperature=0.3, max_tokens=400)
        questions = _parse_questions(raw)
        if not questions:
            logger.warning("suggested_questions: empty result for doc_id=%s raw=%r", doc_id, raw[:200])
            await thread_store.upsert_suggestions(doc_id, [], user_id=user_id, status="failed")
            return
        await thread_store.upsert_suggestions(doc_id, questions, user_id=user_id, status="ready")
        logger.info("suggested_questions: stored %d questions for doc_id=%s", len(questions), doc_id)
    except Exception as e:
        logger.exception("suggested_questions: failed for doc_id=%s: %s", doc_id, e)
        await thread_store.upsert_suggestions(doc_id, [], user_id=user_id, status="failed")


async def run_generation_task(doc_id: str, filename: str, chunks: list[dict[str, Any]]) -> None:
    """Entry point called as background task after upload."""
    await generate_and_store(doc_id, filename, chunks)
