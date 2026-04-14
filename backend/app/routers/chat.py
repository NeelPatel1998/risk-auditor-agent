import asyncio
import json
import logging
import re  # used by _sanitize_thread_title
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.prompts import INJECTION_RESPONSE, SYSTEM_PROMPT, format_rag_user_message
from app.agents.risk_auditor import UNKNOWN_REPLY, agent, lc_messages_to_openai
from app.env import CHECKPOINT_DB
from app.models.schemas import ChatRequest, ChatResponse, ThreadTitleRequest, ThreadTitleResponse
from app.services import thread_store
from app.services.retrieval import search as retrieve_context
from app.utils.auth import require_user_id
from app.utils.guardrails import check_injection, check_jailbreak, guard_user_message
from app.utils.llm import llm_client

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)

@router.get("/chat/auth/check")
async def auth_check(user_id: str = Depends(require_user_id)) -> dict[str, str]:
    """Login verification for the UI (demo auth)."""
    return {"ok": "true", "user_id": user_id}


def _schedule_persist_streamed_turn(
    thread_id: str,
    doc_id: str,
    user_id: str,
    user_message: str,
    assistant_text: str,
    context: str,
    sources: list[dict[str, Any]],
) -> None:
    """Checkpoint write can be slow; do not block closing the SSE stream."""

    async def _persist() -> None:
        try:
            await agent.record_streamed_turn(
                thread_id, doc_id, user_message, assistant_text, context, sources
            )
            await thread_store.add_message(thread_id, "user", user_message, [])
            await thread_store.add_message(thread_id, "assistant", assistant_text, sources)
        except Exception:
            logger.exception("Failed to persist streamed chat turn (thread_id=%s)", thread_id)

    asyncio.create_task(_persist())


THREAD_TITLE_SYSTEM = (
    "You label a single chat thread for a sidebar list. Reply with ONLY a short title: "
    "4 to 6 words, Title Case, no quotation marks, no newlines, no trailing punctuation. "
    "Under 52 characters. Summarize the specific topic from the user question "
    "(use the assistant reply as extra context only if provided); "
    "do not repeat boilerplate like 'question about' or 'information on'."
)


def _sanitize_thread_title(raw: str) -> str:
    t = (raw or "").strip().replace("\n", " ").replace('"', "").replace("'", "")
    t = re.sub(r"\s+", " ", t).strip(" .—-")
    if len(t) > 52:
        t = t[:49].rsplit(" ", 1)[0].strip() or t[:52]
    return t or "New chat"



@router.get("/threads")
async def list_threads(doc_id: str, user_id: str = Depends(require_user_id)) -> list[dict[str, Any]]:
    """Return all threads for a document, newest first."""
    await thread_store.assert_document_owner(doc_id, user_id)
    return await thread_store.list_threads(user_id, doc_id)


@router.get("/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str, user_id: str = Depends(require_user_id)) -> list[dict[str, Any]]:
    """Return the full message history for a thread."""
    return await thread_store.get_messages(user_id, thread_id)


@router.post("/chat/thread-title", response_model=ThreadTitleResponse)
async def thread_title(request: ThreadTitleRequest, user_id: str = Depends(require_user_id)) -> ThreadTitleResponse:
    if guard_user_message(request.user_message):
        return ThreadTitleResponse(title="New chat")
    um = request.user_message.strip()[:2000]
    am = request.assistant_message.strip()[:8000]
    user_content = f"User question:\n{um}\n\nSidebar title:"
    if am:
        user_content = f"User question:\n{um}\n\nAssistant reply (excerpt):\n{am}\n\nSidebar title:"
    messages = [
        {"role": "system", "content": THREAD_TITLE_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    try:
        raw = await llm_client.chat(messages, temperature=0.25, max_tokens=48)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Title model error: {e!s}") from e
    title = _sanitize_thread_title(raw)
    # Persist title synchronously so the frontend re-fetch that fires right after
    # this response always sees the updated title (no create_task race).
    if request.thread_id:
        await thread_store.update_title(request.thread_id, user_id, title)
    return ThreadTitleResponse(title=title)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user_id: str = Depends(require_user_id)) -> ChatResponse:
    if check_injection(request.message) or check_jailbreak(request.message):
        tid = request.thread_id or str(uuid.uuid4())
        return ChatResponse(reply=INJECTION_RESPONSE, sources=[], thread_id=tid)
    if blocked := guard_user_message(request.message):
        tid = request.thread_id or str(uuid.uuid4())
        return ChatResponse(reply=blocked, sources=[], thread_id=tid)
    thread_id = request.thread_id or str(uuid.uuid4())
    await thread_store.assert_document_owner(request.doc_id, user_id)
    try:
        out = await agent.chat(request.message, thread_id, request.doc_id)
    except ValueError as e:
        # Often OpenRouter auth / billing / model access
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream model error: {e!s}") from e
    return ChatResponse(
        reply=out["reply"],
        sources=out.get("sources") or [],
        thread_id=out["thread_id"],
    )


async def _stream_openai_sse(
    thread_id: str,
    doc_id: str,
    user_message: str,
    user_id: str,
) -> AsyncIterator[bytes]:
    """SSE stream: data: {"token":"..."}\n\n then data: [DONE]."""
    tid = thread_id or str(uuid.uuid4())
    if check_injection(user_message) or check_jailbreak(user_message):
        payload = {"token": INJECTION_RESPONSE, "done": True, "thread_id": tid, "sources": []}
        yield f"data: {json.dumps(payload)}\n\n".encode()
        yield b"data: [DONE]\n\n"
        return
    if blocked := guard_user_message(user_message):
        payload = {"token": blocked, "done": True, "thread_id": tid, "sources": []}
        yield f"data: {json.dumps(payload)}\n\n".encode()
        yield b"data: [DONE]\n\n"
        return

    context, sources = await retrieve_context(user_message, doc_id, n_results=6)
    if not context.strip():
        reply = UNKNOWN_REPLY
        yield f"data: {json.dumps({'token': reply, 'done': True, 'thread_id': tid, 'sources': []})}\n\n".encode()
        yield b"data: [DONE]\n\n"
        _schedule_persist_streamed_turn(tid, doc_id, user_id, user_message, reply, "", [])
        return

    rag_user = format_rag_user_message(context=context, question=user_message)
    # History from checkpoint via compiled graph state
    compiled = agent.graph.compile(checkpointer=agent.checkpointer)
    config = {"configurable": {"thread_id": tid}}
    try:
        st = await compiled.aget_state(config)
        prior_msgs = list(st.values.get("messages", [])) if st and st.values else []
    except Exception:
        prior_msgs = []
    tail = prior_msgs[-5:] if len(prior_msgs) > 5 else prior_msgs
    lc_messages = [SystemMessage(content=SYSTEM_PROMPT)] + tail + [HumanMessage(content=rag_user)]
    openai_msgs = lc_messages_to_openai(lc_messages)

    full: list[str] = []
    try:
        async for piece in llm_client.chat_stream(openai_msgs):
            full.append(piece)
            yield f"data: {json.dumps({'token': piece, 'done': False, 'thread_id': tid, 'sources': sources})}\n\n".encode()
    except Exception as e:
        err = f"Model request failed: {e!s}"
        yield f"data: {json.dumps({'token': err, 'done': True, 'thread_id': tid, 'sources': sources, 'error': True})}\n\n".encode()
        yield b"data: [DONE]\n\n"
        return

    text = "".join(full)
    yield f"data: {json.dumps({'token': '', 'done': True, 'thread_id': tid, 'sources': sources})}\n\n".encode()
    yield b"data: [DONE]\n\n"
    _schedule_persist_streamed_turn(tid, doc_id, user_id, user_message, text, context, sources)


@router.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str, user_id: str = Depends(require_user_id)) -> dict[str, Any]:
    """Permanently delete a thread from all stores (checkpoints + threads table)."""
    try:
        await thread_store.assert_thread_owner(thread_id, user_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="Unknown thread_id") from None
    db_path = str(Path(CHECKPOINT_DB).resolve())
    deleted = 0
    try:
        async with aiosqlite.connect(db_path) as db:
            # LangGraph checkpointer tables — delete in dependency order
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                try:
                    cur = await db.execute(
                        f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,)  # noqa: S608
                    )
                    deleted += cur.rowcount
                except aiosqlite.OperationalError:
                    pass
            await db.commit()
        # Also remove from our threads/messages tables
        await thread_store.delete_thread(user_id, thread_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete thread: {e!s}") from e
    return {"thread_id": thread_id, "deleted_rows": deleted}


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, user_id: str = Depends(require_user_id)) -> StreamingResponse:
    tid = request.thread_id or str(uuid.uuid4())

    # Ensure document ownership and create the thread row *before* returning the
    # StreamingResponse.  The generator body only executes when the client starts
    # reading, so if we defer these calls into the generator, a concurrent
    # POST /chat/thread-title request may call update_title before the row exists
    # (a silent no-op that permanently loses the AI-generated title).
    await thread_store.assert_document_owner(request.doc_id, user_id)
    await thread_store.upsert_thread(tid, user_id, request.doc_id)

    async def gen() -> AsyncIterator[bytes]:
        async for chunk in _stream_openai_sse(tid, request.doc_id, request.message, user_id):
            yield chunk

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
