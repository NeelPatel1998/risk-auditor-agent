# Risk Auditor Assistant

A production-grade AI agent that lets risk officers upload any regulatory PDF and hold a cited, memory-aware conversation with it — grounded strictly in the document, with zero hallucination tolerance.

---

## Quick Start

### Docker (recommended)

```bash
# 1. Add your OpenRouter key
echo "OPENROUTER_API_KEY=sk-or-..." > risk-auditor/.env

# 2. Build and run
cd risk-auditor
docker compose up -d --build

# 3. Open the UI
open http://localhost:8080
```

Login password: **admin**

### Local development

```powershell
# Backend
cd risk-auditor\backend
python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements-document.txt -r requirements-chat.txt
copy ..\.env.example .env            # add OPENROUTER_API_KEY
$env:PYTHONPATH = "."
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd risk-auditor\frontend
npm install
npm run dev                          # http://localhost:5173
```

---

## Key Features

| Feature | What it does |
|---|---|
| **Document-grounded answers** | Every reply is built exclusively from retrieved passages — the model cannot invent facts not in the PDF |
| **Numbered citations with page preview** | Responses cite `[Source 1]`, `[Source 2]` etc.; clicking a citation opens the exact page(s) and highlights the matching paragraph in a side panel |
| **Conversational memory** | Follow-up questions work naturally — the agent remembers the last 5 turns via LangGraph checkpointing persisted to SQLite |
| **Suggested questions** | After upload, an LLM reads the document body and generates 5 narrow, answerable questions specific to that PDF |
| **Auto-titled threads** | Sidebar conversation titles are AI-generated from the user's first message and stored in the backend |
| **Prompt injection & jailbreak guard** | A pattern-matching layer (`guardrails.py`) detects and blocks adversarial inputs before they reach the LLM |
| **Microservice architecture** | Split into a lightweight chat service (~320 MB) and a separate document service (~2 GB with ML stack) — each scales independently |
| **Streaming responses** | Token-by-token SSE streaming — users see the first word within ~1–2 s |
| **CI pipeline** | GitHub Actions runs Ruff linting and a pytest evaluation suite on every push |

---

## System Architecture

```
Browser
  │  REST + SSE
  ▼
Nginx gateway (:8080)   ← serves the React SPA + reverse-proxies /api
  │
  ├─► Chat service (:8000)      — conversation, memory, streaming
  │
  └─► Document service (:8001)  — ingest, embed, retrieve
          │
          ├─ ChromaDB   (vector store, file-based)
          ├─ SQLite     (LangGraph checkpoints + thread/message/suggestions store)
          └─ Uploads/   (raw PDFs, on-disk)
```

### Major Components

#### Document Service

| Component | Role |
|---|---|
| **PDF Parser** (`pdf_parser.py`) | PyMuPDF extracts text page-by-page, preserving page numbers |
| **Chunker** (`chunker.py`) | Section-aware splitter: detects regulatory headings (e.g. "Principle 3.6", "ANNEX A") and keeps each heading with its full body. Falls back to paragraph then sentence splits — never cuts mid-sentence |
| **Embedder** (`llm.py`) | Calls OpenRouter `qwen/qwen3-embedding-8b` in batches of 32 chunks |
| **Vector Store** (`vector_store.py`) | ChromaDB with L2 HNSW index; hybrid search = dense + BM25 fused via Reciprocal Rank Fusion, then cross-encoder re-ranked |
| **Evidence Heuristics** (`evidence_heuristics.py`) | Classifies chunks as *narrative* or *disclosure checklist* and adjusts RRF scores so explanatory text ranks above table rows |

#### Chat Service

| Component | Role |
|---|---|
| **LangGraph agent** (`risk_auditor.py`) | `StateGraph` with a single `generate` node; compiled with `AsyncSqliteSaver` checkpointer for per-thread memory |
| **System prompt** (`prompts.py`) | 12-rule strict prompt: grounding, citation format, "I cannot find" fallback, injection refusal, no financial advice, no PII |
| **SSE streaming** (`chat.py`) | Token-by-token streaming via FastAPI `StreamingResponse`; sources are attached to every frame so citations render as the response streams |
| **Thread store** (`thread_store.py`) | SQLite tables for documents, threads, messages, and suggested questions — all scoped per user |

---

## Design Decisions

### Why LangGraph for memory?

LangGraph's `StateGraph` + `AsyncSqliteSaver` gives persistent, per-thread conversation checkpoints with zero external infrastructure — no Redis, no separate session store. The graph compiles fresh on each request but rehydrates state from SQLite, so memory survives container restarts. The window is intentionally capped at **5 messages**: 10 messages ≈ 8k tokens which routinely hits rate limits on lower-tier inference plans, while 5 is enough for meaningful follow-up chains.


### Why hybrid retrieval (dense + BM25 + re-rank)?

Pure vector search misses exact regulatory terms ("AIRB", "FRTB", "E-23") that appear infrequently in training data and embed poorly. BM25 catches keyword matches that vector similarity misses. Reciprocal Rank Fusion merges both ranked lists without needing score calibration. The cross-encoder re-ranker (sentence-transformers) then reorders the top candidates by semantic relevance — running on CPU with no GPU dependency.

### Why section-aware chunking?

Naively splitting at fixed character counts severs headings from their bodies — a chunk starting mid-paragraph loses the section label that tells the LLM what the text is about. The chunker detects regulatory heading patterns first, keeps each heading + body as one logical unit, then splits oversized units at paragraph breaks. Retrieved chunks are always semantically self-contained, which directly improves answer quality and citation accuracy.

### Why microservices (document + chat)?

The document service needs PyMuPDF, ChromaDB, and a CPU-only PyTorch sentence-transformer (~2 GB image). The chat service needs only LangGraph and LangChain-core (~320 MB image). Splitting them keeps the chat container lean and allows independent scaling — more chat replicas without duplicating the large ML stack.

### Why ChromaDB over Pinecone / Weaviate?

ChromaDB is file-based (no server to manage), has zero cold-start latency, and is free. For a prototype handling a handful of documents this is the right tradeoff. A production deployment would swap it for a managed vector store once document volume justifies operational overhead.

---

## Security

The system was designed with a banking-sector threat model in mind:

| Control | Implementation |
|---|---|
| **Prompt injection blocking** | Every user message is checked by a pattern-matching layer before reaching the LLM; known jailbreak patterns return a canned refusal without consuming tokens |
| **Strict grounding** | The system prompt forbids the model from answering outside the retrieved context; it must respond with "I cannot find this information" rather than speculating |
| **Scope restriction** | The model is constrained to risk management, governance, and compliance topics only — off-topic requests are refused |
| **No financial advice** | An explicit rule prevents the model from giving investment, lending, or trading advice |
| **PII refusal** | The model refuses to process or echo back names, account numbers, employee IDs, or similar personal data |
| **Instruction confidentiality** | The model will not reveal, paraphrase, or hint at the system prompt — critical in a regulated environment |
| **No compiler in production image** | Multi-stage Docker build: the runtime image contains no `gcc`, `make`, or build tools — reducing the attack surface |
| **Distance cutoff on retrieval** | Chunks with L2 distance > 2.5 are rejected; the model never sees low-confidence, potentially misleading passages |

---

## Reliability

| Technique | Effect |
|---|---|
| **SSE streaming** | First token appears in ~1–2 s; the user sees progress immediately rather than waiting for a full reply |
| **Async throughout** | FastAPI + `asyncio` + `aiosqlite` — no thread blocking on any I/O path |
| **Lazy imports** | Heavy modules (PyMuPDF, ChromaDB, torch) are only imported by the service that needs them, preventing OOM crashes in the chat container |
| **BM25 cached in memory** | Built once per document on first query; subsequent keyword lookups are microsecond in-memory operations |
| **Embedding cache (SHA-256)** | Embeddings are cached in SQLite keyed by a SHA-256 hash of each chunk’s text; re-uploading the same PDF (or repeated passages) reuses cached vectors instead of re-embedding |
| **Named Docker volume** | `risk_data` persists SQLite + ChromaDB + uploads across container restarts; no data loss on redeploy |
| **CI on every push** | Ruff + pytest block a merge if any import is broken or retrieval accuracy regresses |

---

## What I Would Do Differently With 30 Days

The 3-day build proves the concept works. The 30-day version makes it trustworthy enough to put in front of risk officers at a regulated institution. Six changes would have the largest compounding impact:

### 1. LLM Observability & Compliance Audit Trail

Today the system writes application logs. That is not enough for a banking deployment. Every query should emit a **structured trace** — retrieved chunks with similarity scores, the full prompt, the raw model output, latency split by stage (retrieval / rerank / LLM / serialisation), and any user feedback signal. An open-source monitoring library built on OpenTelemetry would give compliance and ML-ops teams a searchable audit trail of every answer the system has ever produced, a live dashboard to catch retrieval failures before users notice them, and an automated faithfulness scorer (LLM-as-judge) that flags answers not supported by the cited chunks. Without this, running the system in production is flying blind.

### 2. Multi-hop Agentic Retrieval

The current RAG pipeline does one retrieval pass per question. Complex regulatory questions — *"How does E-23's model validation standard compare to what B-15 requires for climate models?"* — require the agent to decompose the question into sub-queries, retrieve against each, verify consistency across answers, and synthesise a single grounded response. With 30 days this would be built as a LangGraph tool-calling loop: the agent issues targeted sub-queries, checks whether the partial answers conflict, and iterates before producing a final response. This is the single biggest driver of answer quality for the hard questions a real risk officer would ask.

### 3. Enterprise Auth, Data Governance & PII Protection

The demo uses a hardcoded username and password. Production requires **OAuth 2.0 / OIDC** (e.g. Azure AD for a bank) with per-user JWTs, role-based access (read-only analyst vs. document admin), and group-level document sharing so teams can work from the same library while keeping conversations private. Alongside auth: automated PII and sensitive data detection (using a library like Microsoft Presidio) runs before any text is chunked and embedded, so customer names, account numbers, and internal classifications never enter the vector store unmasked. Uploaded PDFs and SQLite are encrypted at rest (AES-256). Together these three controls are the minimum bar for a regulated environment.

### 4. Smarter Document Intelligence

The current parser extracts plain text and splits on headings and paragraph boundaries. Real regulatory documents are harder: scanned pages with no selectable text, dense comparison tables that lose meaning when linearised, multi-column layouts where paragraphs interleave, and footnotes that carry material caveats. With 30 days the pipeline would use a layout-aware PDF library to extract bounding boxes and detect tables, preserve table structure as Markdown rather than flattening it to prose, apply OCR where the page is a raster image, and tag every chunk with its structural role (heading / body / table / footnote) so the retriever can weight them appropriately. This directly improves citation accuracy for quantitative questions.

### 5. Human Feedback Loop & Continuous Improvement

Every answer should carry a simple thumbs-up / thumbs-down. Those signals, stored against the exact query, retrieved chunks, and model output, form a labelled dataset that can drive three improvements over time: (a) re-ranking tuning — chunks that were retrieved but unhelpful get down-weighted; (b) prompt iteration — patterns of thumbs-down for a question type reveal a system prompt failure; (c) golden set expansion — high-confidence thumbs-up pairs are automatically promoted to the regression eval suite. Without a feedback loop the system can only improve through manual intervention. With one, it improves every day the product is used.

### 6. ML-Based Guardrails

The current prompt injection guard uses hand-crafted regex patterns — fast and free, but brittle against novel attack phrasing. With 30 days, this would be replaced with a **small classification model** (fine-tuned on adversarial prompt datasets) that scores every incoming message for injection intent before it reaches the LLM. Alongside that: output scanning to detect when the model's response drifts outside the grounded context (a secondary faithfulness check), and rate-limiting repeat offenders at the user level. For a banking deployment, robust guardrails are as important as answer quality — a single successful jailbreak that causes the system to reveal internal data or give financial advice is a compliance incident.

### 7. Production Infrastructure & Cost Control

Docker Compose on a single host is the right way to ship a prototype. A bank running this for hundreds of analysts needs **Kubernetes** with horizontal pod autoscaling on the chat service (the LLM calls are the bottleneck), a managed vector store with per-tenant namespaces and point-in-time backup, and a per-user token-per-minute quota enforced at the API gateway to prevent runaway LLM costs and denial-of-service. Equally important: **model routing by query complexity** — simple factual lookups use a fast, cheap model; multi-hop synthesis queries are routed to a more capable one. In practice this cuts cost by 40–60 % with no user-visible quality change.

---

### Summary

| Priority | What changes | Why it matters most |
|---|---|---|
| **1 — LLM observability** | Structured traces on every request | Compliance audit trail; catch retrieval failures before users do |
| **2 — Multi-hop retrieval** | Agent decomposes and iterates queries | Biggest quality jump for hard cross-document questions |
| **3 — Auth + governance + PII** | OAuth/OIDC, redaction, encryption | Minimum bar for a regulated institution |
| **4 — Document intelligence** | Layout-aware parsing, OCR, table extraction | Accurate answers on quantitative and table-heavy content |
| **5 — Feedback loop** | Thumbs up/down → reranker + eval improvement | System that gets better with use instead of staying static |
| **6 — ML-based guardrails** | Classification model replaces regex patterns | Resilient against novel attack phrasing; output scanning |
| **7 — Production infra + cost control** | Kubernetes, managed DB, model routing | Scales to real load; keeps LLM spend predictable |

