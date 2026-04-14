"""FastAPI application factories: monolith, Document service, Chat service."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.env import CHECKPOINT_DB, cors_allow_origins
from app.services.reranker import warm_up as reranker_warm_up
from app.services.thread_store import init_db


def _sqlite_conn_string() -> str:
    return str(Path(CHECKPOINT_DB).resolve())


def _add_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allow_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@asynccontextmanager
async def _lifespan_monolith(_app: FastAPI):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from app.agents.risk_auditor import agent

    conn = _sqlite_conn_string()
    async with AsyncSqliteSaver.from_conn_string(conn) as saver:
        agent.checkpointer = saver
        await init_db()
        await reranker_warm_up()
        yield
    agent.checkpointer = None


@asynccontextmanager
async def _lifespan_document(_app: FastAPI):
    await init_db()
    await reranker_warm_up()
    yield


@asynccontextmanager
async def _lifespan_chat(_app: FastAPI):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from app.agents.risk_auditor import agent

    conn = _sqlite_conn_string()
    async with AsyncSqliteSaver.from_conn_string(conn) as saver:
        agent.checkpointer = saver
        await init_db()
        yield
    agent.checkpointer = None


def create_monolith_app() -> FastAPI:
    """Single process: files + chat + local retrieval (default dev)."""
    from app.routers import chat, files

    app = FastAPI(title="Risk Auditor AI", lifespan=_lifespan_monolith)
    _add_cors(app)
    app.include_router(files.router)
    app.include_router(chat.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy", "mode": "monolith"}

    return app


def create_document_app() -> FastAPI:
    """Document / ingestion service: vectors, uploads, internal retrieve API."""
    from app.routers import files, internal_retrieve

    app = FastAPI(title="Risk Auditor — Document", lifespan=_lifespan_document)
    _add_cors(app)
    app.include_router(files.router)
    app.include_router(internal_retrieve.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy", "service": "document"}

    return app


def create_chat_app() -> FastAPI:
    """Conversation service: guardrails, LangGraph, streaming LLM (retrieval via remote or local env)."""
    from app.routers import chat

    app = FastAPI(title="Risk Auditor — Chat", lifespan=_lifespan_chat)
    _add_cors(app)
    app.include_router(chat.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy", "service": "chat"}

    return app
