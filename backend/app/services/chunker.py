"""
Section-aware chunker for regulatory PDFs.

How it works (easy to explain to a team)
─────────────────────────────────────────
1.  PyMuPDF extracts text page-by-page.  Each page is prefixed with [Page N].

2.  A regex scans the full text for regulatory headings:
      • "Principle 3.6"  / "Section 4"  / "Annex A"
      • "4.1 Governance" / "2.3.1 Model Inventory"
      • ALL-CAPS lines  like "MODEL VALIDATION"

3.  The text is split at every heading boundary.
    Each resulting piece is called a *section*: heading + body together.
    This is the key improvement — headings and their content are NEVER
    separated into different chunks.

4.  If a section is still larger than CHUNK_SIZE it is further split at
    paragraph breaks (\n\n), then at sentence ends — never mid-word.

5.  Every chunk is prefixed with [Page N] so the citation panel can show
    the exact page.  Each chunk starts cleanly at a section or paragraph
    boundary — no mid-sentence overlap text is injected into stored content.

This is fast (pure Python, no ML), predictable, and produces semantically
complete chunks that align with how auditors actually read the document.
"""

import re
import uuid
from typing import Any

from app.env import CHUNK_SIZE
from app.services.evidence_heuristics import classify_chunk_text

# ---------------------------------------------------------------------------
# Heading detection
# ---------------------------------------------------------------------------

# Matches lines that look like regulatory section headings:
#   "Principle 3.6"  "Section 4"  "Annex A"  "Appendix B"
#   "4.1 Governance"  "2.3.1 Something"
#   "MODEL VALIDATION"  (all-caps, ≥4 chars, standalone line)
_HEADING = re.compile(
    r"(?m)^(?:"
    r"(?:Principle|Section|Annex|Appendix|Chapter|Article)\s+[\d.A-Za-z]+[^\n]*|"
    r"\d+\.\d+(?:\.\d+)*\s+[A-Z][^\n]*|"
    r"[A-Z][A-Z ,\-]{3,60}"
    r")$"
)

# Minimum chars a chunk must have to be worth storing.
_MIN_CHARS = 80


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_at_paragraphs(text: str, max_size: int) -> list[str]:
    """
    Break *text* into pieces no larger than *max_size*, splitting first at
    blank lines then at sentence ends.  Never cuts mid-word.
    """
    if len(text) <= max_size:
        return [text]

    pieces: list[str] = []
    # Try paragraph breaks first
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    current = ""
    for para in paras:
        candidate = (current + "\n\n" + para).strip() if current else para
        if len(candidate) <= max_size:
            current = candidate
        else:
            if current:
                pieces.append(current)
            # If even a single paragraph is too large, split at sentences
            if len(para) > max_size:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                buf = ""
                for sent in sentences:
                    trial = (buf + " " + sent).strip() if buf else sent
                    if len(trial) <= max_size:
                        buf = trial
                    else:
                        if buf:
                            pieces.append(buf)
                        buf = sent
                current = buf
            else:
                current = para
    if current:
        pieces.append(current)
    return pieces or [text[:max_size]]


def _normalize(text: str) -> str:
    """Collapse PDF hard-wrap artifacts (single \\n mid-sentence → space)."""
    # Protect real paragraph breaks
    text = text.replace("\n\n", "\x00")
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if (
            out
            and out[-1]
            and not out[-1].endswith((".", "!", "?", ":", ";", ",", "-"))
            and (line[0].islower() or line[0] == "(")
        ):
            out[-1] += " " + line
        else:
            out.append(line)
    result = "\n\n".join(
        seg for seg in "\x00".join(out).replace("\x00", "\n\n").split("\n\n")
        if seg.strip()
    )
    return re.sub(r"\n{3,}", "\n\n", result).strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_document(pages: list[dict[str, Any]], doc_id: str) -> list[dict[str, Any]]:
    """Split a document into section-aware, embedding-ready chunks."""

    # ── Step 1: build annotated full text ──────────────────────────────────
    parts: list[str] = []
    for p in pages:
        content = (p.get("content") or "").strip()
        if content:
            parts.append(f"[Page {p['page']}]\n{content}")
    full_text = "\n\n".join(parts)

    # ── Step 2: find all heading positions ─────────────────────────────────
    boundaries: list[int] = [m.start() for m in _HEADING.finditer(full_text)]

    # Build section spans: (start, end) in full_text
    if not boundaries:
        # No headings found — fall back to plain paragraph chunking
        sections = [full_text]
    else:
        spans = list(zip(boundaries, boundaries[1:] + [len(full_text)]))
        sections = [full_text[s:e].strip() for s, e in spans]
        # Prepend any text before the first heading as its own section
        preamble = full_text[: boundaries[0]].strip()
        if preamble:
            sections = [preamble] + sections

    # ── Step 3: split oversized sections; build final chunks ───────────────
    chunks: list[dict[str, Any]] = []

    for section in sections:
        section = _normalize(section)
        if not section:
            continue

        # Extract the [Page N] marker that's already in the section text
        page_match = re.search(r"\[Page (\d+)\]", section)
        page_num = int(page_match.group(1)) if page_match else 1

        pieces = _split_at_paragraphs(section, CHUNK_SIZE)

        for piece in pieces:
            piece = piece.strip()
            if len(piece) < _MIN_CHARS:
                continue

            # Ensure every chunk starts with a [Page N] marker
            if not piece.startswith("[Page"):
                piece = f"[Page {page_num}]\n{piece}"

            chunks.append({
                "chunk_id": str(uuid.uuid4()),
                "doc_id": doc_id,
                "content": piece,
                "metadata": {"evidence_class": classify_chunk_text(piece)},
            })

    # Very short PDFs (or single-line pages) can yield no pieces ≥ _MIN_CHARS;
    # still persist one chunk so ingest, eval, and tests remain deterministic.
    if not chunks and full_text.strip():
        page_match = re.search(r"\[Page (\d+)\]", full_text)
        page_num = int(page_match.group(1)) if page_match else 1
        norm = _normalize(full_text)
        if norm:
            piece = norm if norm.startswith("[Page") else f"[Page {page_num}]\n{norm}"
            chunks.append({
                "chunk_id": str(uuid.uuid4()),
                "doc_id": doc_id,
                "content": piece,
                "metadata": {"evidence_class": classify_chunk_text(piece)},
            })

    return chunks
