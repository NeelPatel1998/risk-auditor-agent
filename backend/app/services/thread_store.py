"""
Server-side thread and message persistence using the same SQLite DB as LangGraph.

Tables (demo auth)
------------------
documents           – one row per uploaded PDF (doc_id, user_id, filename, created_at)
threads             – one row per conversation (thread_id, user_id, doc_id, title, created_at)
thread_messages     – ordered message log per thread, including sources JSON
document_suggestions – suggested questions per PDF (doc_id, user_id)
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import aiosqlite

from app.env import CHECKPOINT_DB

logger = logging.getLogger(__name__)

_DB_PATH = str(Path(CHECKPOINT_DB).resolve())


_SQLITE_UTC_NAIVE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d+)?$",
)


def _created_at_iso_utc(sqlite_text: str) -> str:
    """
    SQLite datetime('now') is UTC but has no timezone suffix. Browsers parse
    'YYYY-MM-DD HH:MM:SS' as *local* time, shifting wall clocks by several hours.
    Normalize to ISO-8601 with Z for correct client-side display.
    """
    s = (sqlite_text or "").strip()
    if not s or s.endswith("Z"):
        return s
    if _SQLITE_UTC_NAIVE.match(s):
        return f"{s.replace(' ', 'T', 1)}Z"
    return s

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id     TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    filename   TEXT NOT NULL DEFAULT 'Document',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS threads (
    thread_id  TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    doc_id     TEXT NOT NULL,
    title      TEXT NOT NULL DEFAULT 'New chat',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS thread_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id  TEXT    NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    role       TEXT    NOT NULL,          -- 'user' | 'assistant'
    content    TEXT    NOT NULL,
    sources    TEXT    NOT NULL DEFAULT '[]', -- JSON array
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_docs_user ON documents(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_threads_doc ON threads(doc_id);
CREATE INDEX IF NOT EXISTS idx_msgs_thread ON thread_messages(thread_id, id);

CREATE TABLE IF NOT EXISTS document_suggestions (
    doc_id     TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL DEFAULT '',
    questions  TEXT    NOT NULL DEFAULT '[]',
    status     TEXT    NOT NULL DEFAULT 'pending',
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

async def init_db() -> None:
    """Create tables if they don't exist. Called once at app startup."""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.executescript(_DDL)
        await db.commit()
    logger.info("thread_store: DB initialised at %s", _DB_PATH)


# ---------------------------------------------------------------------------
# Document suggested questions (per PDF)
# ---------------------------------------------------------------------------


async def insert_pending_suggestions(doc_id: str, user_id: str) -> None:
    """Record that we will generate suggested questions (status=pending)."""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO document_suggestions (doc_id, user_id, questions, status, updated_at)
            VALUES (?, ?, '[]', 'pending', datetime('now'))
            ON CONFLICT(doc_id) DO UPDATE SET
                user_id = excluded.user_id,
                status = excluded.status,
                updated_at = datetime('now')
            """,
            (doc_id, user_id),
        )
        await db.commit()


async def upsert_suggestions(
    doc_id: str,
    questions: list[str],
    *,
    user_id: str,
    status: str = "ready",
) -> None:
    """Persist generated questions (JSON array) and status (ready | failed)."""
    payload = json.dumps(questions, ensure_ascii=False)
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO document_suggestions (doc_id, user_id, questions, status, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(doc_id) DO UPDATE SET
                user_id = excluded.user_id,
                questions = excluded.questions,
                status = excluded.status,
                updated_at = datetime('now')
            """,
            (doc_id, user_id, payload, status),
        )
        await db.commit()


async def get_suggestions_row(doc_id: str, user_id: str) -> dict[str, Any] | None:
    """Return { doc_id, questions, status, created_at, updated_at } for a user's doc_id, or None."""
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT doc_id, questions, status, created_at, updated_at "
            "FROM document_suggestions WHERE doc_id = ? AND user_id = ?",
            (doc_id, user_id),
        )
        row = await cur.fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["questions"] = json.loads(d.get("questions") or "[]")
    except Exception:
        d["questions"] = []
    if not isinstance(d["questions"], list):
        d["questions"] = []
    return d


async def delete_suggestions(doc_id: str) -> None:
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute("DELETE FROM document_suggestions WHERE doc_id = ?", (doc_id,))
        await db.commit()

async def delete_document_row(doc_id: str, user_id: str) -> None:
    """Remove the document row and cascade-delete its threads + messages."""
    async with aiosqlite.connect(_DB_PATH) as db:
        # Threads cascade to thread_messages via ON DELETE CASCADE
        await db.execute(
            "DELETE FROM threads WHERE doc_id = ? AND user_id = ?",
            (doc_id, user_id),
        )
        await db.execute(
            "DELETE FROM documents WHERE doc_id = ? AND user_id = ?",
            (doc_id, user_id),
        )
        await db.commit()


async def upsert_document(doc_id: str, user_id: str, filename: str) -> None:
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO documents (doc_id, user_id, filename)
            VALUES (?, ?, ?)
            ON CONFLICT(doc_id) DO UPDATE SET
                user_id = excluded.user_id,
                filename = excluded.filename
            """,
            (doc_id, user_id, filename or "Document"),
        )
        await db.commit()


async def list_documents(user_id: str) -> list[dict[str, str]]:
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT doc_id, filename, created_at FROM documents WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        rows = await cur.fetchall()
    out: list[dict[str, str]] = []
    for r in rows:
        d = dict(r)
        d["created_at"] = _created_at_iso_utc(str(d.get("created_at") or ""))
        out.append(d)
    return out


async def assert_document_owner(doc_id: str, user_id: str) -> None:
    async with aiosqlite.connect(_DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM documents WHERE doc_id = ? AND user_id = ?", (doc_id, user_id))
        row = await cur.fetchone()
    if not row:
        raise PermissionError("Unknown doc_id or not allowed")

async def assert_thread_owner(thread_id: str, user_id: str) -> None:
    async with aiosqlite.connect(_DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM threads WHERE thread_id = ? AND user_id = ?",
            (thread_id, user_id),
        )
        row = await cur.fetchone()
    if not row:
        raise PermissionError("Unknown thread_id or not allowed")


# ---------------------------------------------------------------------------
# Thread operations
# ---------------------------------------------------------------------------

async def upsert_thread(thread_id: str, user_id: str, doc_id: str, title: str = "New chat") -> None:
    """Insert a thread record; ignore if it already exists."""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO threads (thread_id, user_id, doc_id, title) VALUES (?, ?, ?, ?)",
            (thread_id, user_id, doc_id, title),
        )
        await db.commit()


async def update_title(thread_id: str, user_id: str, title: str) -> None:
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "UPDATE threads SET title = ? WHERE thread_id = ? AND user_id = ?",
            (title, thread_id, user_id),
        )
        await db.commit()


async def list_threads(user_id: str, doc_id: str) -> list[dict[str, str]]:
    """Return threads for a document ordered newest-first."""
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT thread_id, doc_id, title, created_at FROM threads "
            "WHERE user_id = ? AND doc_id = ? ORDER BY created_at DESC",
            (user_id, doc_id),
        )
        rows = await cur.fetchall()
    out: list[dict[str, str]] = []
    for r in rows:
        d = dict(r)
        d["created_at"] = _created_at_iso_utc(str(d.get("created_at") or ""))
        out.append(d)
    return out


async def delete_thread(user_id: str, thread_id: str) -> None:
    """Delete thread row (cascade deletes messages too)."""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute("DELETE FROM threads WHERE thread_id = ? AND user_id = ?", (thread_id, user_id))
        await db.commit()


# ---------------------------------------------------------------------------
# Message operations
# ---------------------------------------------------------------------------

async def add_message(
    thread_id: str,
    role: str,
    content: str,
    sources: list[dict[str, Any]] | None = None,
) -> None:
    sources_json = json.dumps(sources or [])
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "INSERT INTO thread_messages (thread_id, role, content, sources) VALUES (?, ?, ?, ?)",
            (thread_id, role, content, sources_json),
        )
        await db.commit()


async def get_messages(user_id: str, thread_id: str) -> list[dict[str, Any]]:
    """Return all messages for a thread in chronological order (scoped to user)."""
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Ensure the thread belongs to the user before returning messages.
        cur0 = await db.execute(
            "SELECT 1 FROM threads WHERE thread_id = ? AND user_id = ?",
            (thread_id, user_id),
        )
        ok = await cur0.fetchone()
        if not ok:
            return []
        cur = await db.execute(
            "SELECT role, content, sources, created_at FROM thread_messages "
            "WHERE thread_id = ? ORDER BY id ASC",
            (thread_id,),
        )
        rows = await cur.fetchall()
    result = []
    for r in rows:
        try:
            sources = json.loads(r["sources"] or "[]")
        except Exception:
            sources = []
        result.append({"role": r["role"], "content": r["content"], "sources": sources})
    return result
