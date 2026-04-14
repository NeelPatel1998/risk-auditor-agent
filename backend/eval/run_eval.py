"""
Evaluation harness for the Risk Auditor RAG pipeline.

Runs every question in golden.json through the full pipeline
(retrieval → re-rank → generation) and produces a scored report.

Self-contained: on first run the harness automatically parses, chunks,
and embeds the test PDFs as "ghost" vectors (doc_id prefix ``eval__``)
that are invisible to the UI.  Subsequent runs reuse the existing vectors.

Usage:
    cd backend
    python -m eval.run_eval                  # full 30-question run
    python -m eval.run_eval --limit 5        # quick smoke test

Outputs:
    eval/results_<timestamp>.json   — full per-question results
    eval/summary_<timestamp>.txt    — aggregate scores printed to console
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.prompts import SYSTEM_PROMPT, format_rag_user_message
from app.services.chunker import chunk_document
from app.services.pdf_parser import parse_pdf
from app.services.vector_store import vector_store
from app.utils.llm import llm_client

EVAL_DIR = Path(__file__).resolve().parent
GOLDEN_PATH = EVAL_DIR / "golden.json"


def get_input_dir() -> Path:
    """
    Directory containing evaluation PDFs (see GHOST_PDFS filenames).

    Resolution order:
    1. RBC_INPUT_DATA_DIR env (CI, Docker, or custom layout)
    2. ``<repo>/risk-auditor/sample_input_data`` if that folder exists
    3. ``<monorepo parent>/sample_input_data`` (legacy layout next to ``risk-auditor/``)
    """
    override = (os.getenv("RBC_INPUT_DATA_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    backend_root = Path(__file__).resolve().parent.parent
    risk_auditor_root = backend_root.parent
    colocated = risk_auditor_root / "sample_input_data"
    monorepo_parent = risk_auditor_root.parent / "sample_input_data"
    if colocated.is_dir():
        return colocated
    return monorepo_parent

# Ghost PDFs: (eval doc_id, filename in "sample_input_data")
GHOST_PDFS: list[tuple[str, str]] = [
    ("eval__e23_2027",       "Guideline E23  Model Risk Management 2027.pdf"),
    ("eval__b15_climate",    "OSFI_B-15_Climate_Risk_2023_Original.pdf"),
    ("eval__worldbank_basel","World_Bank_Basel_Core_Principles_2024.pdf"),
]

# Default ghost doc_id used by golden.json (E-23)
DEFAULT_EVAL_DOC = "eval__e23_2027"


# ── Ghost vector ingestion ───────────────────────────────────────────────────

def _ghost_exists(doc_id: str) -> bool:
    """Check if ghost vectors already exist in Chroma."""
    try:
        res = vector_store.collection.get(
            where={"doc_id": doc_id},
            include=[],
            limit=1,
        )
        return bool(res.get("ids"))
    except Exception:
        return False


async def ensure_ghost_vectors(force: bool = False) -> None:
    """Parse, chunk, and embed all ghost PDFs that are not yet in the vector DB."""
    for doc_id, filename in GHOST_PDFS:
        if not force and _ghost_exists(doc_id):
            print(f"  [OK] Ghost vectors exist: {doc_id} ({filename})")
            continue

        pdf_path = get_input_dir() / filename
        if not pdf_path.is_file():
            print(f"  [MISS] PDF not found, skipping: {pdf_path}")
            continue

        print(f"  [INGEST] Ghost vectors: {doc_id} ({filename})...", flush=True)

        if force:
            vector_store.delete_by_doc_id(doc_id)

        pages = parse_pdf(str(pdf_path))
        chunks = chunk_document(pages, doc_id)
        for c in chunks:
            c.setdefault("metadata", {})["filename"] = filename

        t0 = time.perf_counter()
        await vector_store.add_chunks(chunks)
        elapsed = time.perf_counter() - t0

        print(f"    -> {len(chunks)} chunks embedded in {elapsed:.1f}s")


# ── Scoring helpers ──────────────────────────────────────────────────────────

def keyword_coverage(answer: str, keywords: list[str]) -> float:
    if not keywords:
        return 1.0
    lower = answer.lower()
    hits = sum(1 for kw in keywords if kw.lower() in lower)
    return hits / len(keywords)


def page_from_chunk(content: str) -> int | None:
    m = re.search(r"\[Page\s*(\d+)\]", content)
    return int(m.group(1)) if m else None


def retrieval_page_hit(sources: list[dict[str, Any]], expected_page: int) -> bool:
    for src in sources:
        pg = page_from_chunk(src.get("content", ""))
        if pg == expected_page:
            return True
    return False


def retrieval_page_rank(sources: list[dict[str, Any]], expected_page: int) -> int | None:
    for i, src in enumerate(sources):
        pg = page_from_chunk(src.get("content", ""))
        if pg == expected_page:
            return i + 1
    return None


def answer_includes_citation(answer: str) -> bool:
    return bool(re.search(r"\[Source\s*\d+\]", answer))


def faithfulness_heuristic(answer: str) -> float:
    score = 1.0
    lower = answer.lower()
    hedge_phrases = ["i think", "probably", "i believe", "it seems", "might be", "i'm not sure"]
    for phrase in hedge_phrases:
        if phrase in lower:
            score -= 0.15
    if not answer_includes_citation(answer):
        score -= 0.3
    if "i cannot find" in lower:
        score -= 0.5
    return max(0.0, score)


# ── Main evaluation loop ─────────────────────────────────────────────────────

async def run_one(item: dict[str, Any], fallback_doc_id: str) -> dict[str, Any]:
    q = item["question"]
    doc_id = item.get("doc_id", fallback_doc_id)
    t0 = time.perf_counter()

    context_str, sources = await vector_store.search(q, doc_id, n_results=6)
    retrieval_ms = (time.perf_counter() - t0) * 1000

    page_hit = retrieval_page_hit(sources, item["expected_page"])
    page_rank = retrieval_page_rank(sources, item["expected_page"])
    pages_returned = [page_from_chunk(s.get("content", "")) for s in sources]

    user_msg = format_rag_user_message(context_str, q)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    t1 = time.perf_counter()
    answer = await llm_client.chat(messages, temperature=0.1)
    generation_ms = (time.perf_counter() - t1) * 1000

    kw_cov = keyword_coverage(answer, item.get("expected_keywords", []))
    faith = faithfulness_heuristic(answer)
    has_cite = answer_includes_citation(answer)

    return {
        "id": item["id"],
        "doc_id": doc_id,
        "question": q,
        "difficulty": item.get("difficulty", "?"),
        "expected_page": item["expected_page"],
        "retrieval": {
            "page_hit": page_hit,
            "page_rank": page_rank,
            "pages_returned": pages_returned,
            "latency_ms": round(retrieval_ms, 1),
        },
        "generation": {
            "answer": answer[:2000],
            "has_citation": has_cite,
            "keyword_coverage": round(kw_cov, 3),
            "faithfulness_heuristic": round(faith, 3),
            "latency_ms": round(generation_ms, 1),
        },
    }


async def run_all(fallback_doc_id: str, golden: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for i, item in enumerate(golden, 1):
        tag = item.get("doc_id", fallback_doc_id).replace("eval__", "")
        print(f"  [{i:2d}/{len(golden)}] [{tag}] {item['question'][:55]}...", flush=True)
        try:
            result = await run_one(item, fallback_doc_id)
        except Exception as exc:
            result = {"id": item["id"], "question": item["question"], "error": str(exc)}
            print(f"         [!] ERROR: {exc}")
        results.append(result)
    return results


def print_summary(results: list[dict[str, Any]]) -> str:
    valid = [r for r in results if "error" not in r]
    n = len(valid)
    if n == 0:
        return "No valid results."

    page_hits = sum(1 for r in valid if r["retrieval"]["page_hit"])
    avg_kw    = sum(r["generation"]["keyword_coverage"] for r in valid) / n
    avg_faith = sum(r["generation"]["faithfulness_heuristic"] for r in valid) / n
    cite_rate = sum(1 for r in valid if r["generation"]["has_citation"]) / n
    avg_ret_ms = sum(r["retrieval"]["latency_ms"] for r in valid) / n
    avg_gen_ms = sum(r["generation"]["latency_ms"] for r in valid) / n

    mrr_scores = []
    for r in valid:
        rank = r["retrieval"]["page_rank"]
        mrr_scores.append(1.0 / rank if rank else 0.0)
    avg_mrr = sum(mrr_scores) / n

    # Per-doc breakdown
    docs_seen: dict[str, list] = {}
    for r in valid:
        did = r.get("doc_id", "unknown")
        docs_seen.setdefault(did, []).append(r)

    doc_lines = []
    for did, items in docs_seen.items():
        dn = len(items)
        dh = sum(1 for r in items if r["retrieval"]["page_hit"])
        doc_lines.append(f"    {did:30s} {dh}/{dn} ({dh/dn:.0%})")

    lines = [
        "=" * 60,
        f"  EVALUATION SUMMARY  ({n} questions, {len(results) - n} errors)",
        "=" * 60,
        "",
        "  RETRIEVAL",
        f"    Page Hit Rate:          {page_hits}/{n} ({page_hits/n:.0%})",
        f"    Mean Reciprocal Rank:   {avg_mrr:.3f}",
        f"    Avg Retrieval Latency:  {avg_ret_ms:.0f} ms",
        "",
        "    Per-document hit rate:",
        *doc_lines,
        "",
        "  GENERATION",
        f"    Citation Rate:          {cite_rate:.0%}",
        f"    Keyword Coverage:       {avg_kw:.1%}",
        f"    Faithfulness (heur.):   {avg_faith:.3f}",
        f"    Avg Generation Latency: {avg_gen_ms:.0f} ms",
        "",
        "  PER-QUESTION BREAKDOWN",
        f"    {'ID':<12} {'Diff':<7} {'PgHit':<6} {'Rank':<6} {'KW%':<6} {'Faith':<6} {'Cite':>5}",
        "    " + "-" * 55,
    ]
    for r in valid:
        ret = r["retrieval"]
        gen = r["generation"]
        lines.append(
            f"    {r['id']:<12} {r['difficulty']:<7} "
            f"{'Y' if ret['page_hit'] else 'N':<6} "
            f"{str(ret['page_rank'] or '-'):<6} "
            f"{gen['keyword_coverage']:.0%}  "
            f"{gen['faithfulness_heuristic']:.2f}  "
            f"{'Y' if gen['has_citation'] else 'N':>4}"
        )
    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description="RAG evaluation harness")
    parser.add_argument("--doc-id", default=DEFAULT_EVAL_DOC,
                        help=f"Fallback doc_id when question has no doc_id field (default: {DEFAULT_EVAL_DOC})")
    parser.add_argument("--golden", default=str(GOLDEN_PATH), help="Path to golden.json")
    parser.add_argument("--limit", type=int, default=None, help="Only run first N questions")
    args = parser.parse_args()

    print("\n--- Ensuring ghost vectors ---\n")
    await ensure_ghost_vectors(force=False)

    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    if args.limit:
        golden = golden[: args.limit]

    doc_ids_used = set(q.get("doc_id", args.doc_id) for q in golden)
    print(f"\n--- Running evaluation: {len(golden)} questions across {len(doc_ids_used)} document(s) ---\n")

    results = await run_all(args.doc_id, golden)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_path = EVAL_DIR / f"results_{ts}.json"
    results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = print_summary(results)
    print(summary)
    summary_path = EVAL_DIR / f"summary_{ts}.txt"
    summary_path.write_text(summary, encoding="utf-8")

    print(f"\n  Results:  {results_path}")
    print(f"  Summary:  {summary_path}\n")


if __name__ == "__main__":
    asyncio.run(main())
