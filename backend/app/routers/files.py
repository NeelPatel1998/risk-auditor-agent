import asyncio
import glob
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.env import CLEAR_CHROMA_ON_UPLOAD, MAX_UPLOAD_BYTES, UPLOAD_DIR
from app.models.schemas import DocumentDeleteResult, DocumentSummary, SuggestedQuestionsResponse, UploadResponse
from app.services.chunker import chunk_document
from app.services.pdf_parser import parse_pdf
from app.services.suggested_questions import run_generation_task
from app.services import thread_store
from app.services.vector_store import vector_store
from app.utils.auth import require_user_id

router = APIRouter(tags=["files"])


@router.get("/documents", response_model=list[DocumentSummary])
async def list_documents(user_id: str = Depends(require_user_id)) -> list[DocumentSummary]:
    """PDFs uploaded by the current user."""
    rows = await thread_store.list_documents(user_id)
    return [DocumentSummary(doc_id=str(r["doc_id"]), filename=str(r["filename"])) for r in rows]


@router.get("/documents/{doc_id}/suggested-questions", response_model=SuggestedQuestionsResponse)
async def get_suggested_questions(
    doc_id: str,
    user_id: str = Depends(require_user_id),
) -> SuggestedQuestionsResponse:
    """LLM-generated suggested questions stored in SQLite after upload (poll while status is pending)."""
    await thread_store.assert_document_owner(doc_id, user_id)
    row = await thread_store.get_suggestions_row(doc_id, user_id)
    if not row:
        return SuggestedQuestionsResponse(questions=[], status="none")
    return SuggestedQuestionsResponse(
        questions=[str(q) for q in row.get("questions") or [] if str(q).strip()],
        status=str(row.get("status") or "pending"),
    )


@router.get("/documents/{doc_id}/pages")
async def get_document_pages(doc_id: str, user_id: str = Depends(require_user_id)) -> list[dict]:
    """Return raw page-by-page text extracted from the stored PDF.

    Each item: { page: int, content: str }
    This is the unprocessed PyMuPDF output — preserves the original
    document structure exactly as uploaded.
    """
    await thread_store.assert_document_owner(doc_id, user_id)
    fp = os.path.join(UPLOAD_DIR, f"{doc_id}.pdf")
    if not os.path.isfile(fp):
        raise HTTPException(status_code=404, detail="PDF file not found")
    return parse_pdf(fp)


@router.delete("/documents/{doc_id}", response_model=DocumentDeleteResult)
async def delete_document(doc_id: str, user_id: str = Depends(require_user_id)) -> DocumentDeleteResult:
    """Remove a document and all associated data (vectors, PDF file, threads, suggestions)."""
    await thread_store.assert_document_owner(doc_id, user_id)
    # Remove vectors (may already be gone if a previous delete partially succeeded)
    n = vector_store.delete_by_doc_id(doc_id)
    # Remove suggestions and the document row + cascade threads/messages
    await thread_store.delete_suggestions(doc_id)
    await thread_store.delete_document_row(doc_id, user_id)
    # Remove the uploaded PDF file if present
    fp = os.path.join(UPLOAD_DIR, f"{doc_id}.pdf")
    if os.path.isfile(fp):
        os.remove(fp)
    return DocumentDeleteResult(doc_id=doc_id, deleted_chunks=n)


@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...), user_id: str = Depends(require_user_id)) -> UploadResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
        )
    if CLEAR_CHROMA_ON_UPLOAD:
        vector_store.delete_all_chunks()
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        for path in glob.glob(os.path.join(UPLOAD_DIR, "*.pdf")):
            try:
                os.remove(path)
            except OSError:
                pass

    doc_id = str(uuid.uuid4())
    fname = file.filename or "document.pdf"
    await thread_store.upsert_document(doc_id, user_id, fname)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(UPLOAD_DIR, f"{doc_id}.pdf")
    with open(file_path, "wb") as f:
        f.write(raw)
    pages = parse_pdf(file_path)
    chunks = chunk_document(pages, doc_id)
    for c in chunks:
        c.setdefault("metadata", {})["filename"] = fname
        c["metadata"]["user_id"] = user_id
    try:
        await vector_store.add_chunks(chunks)
    except ValueError as e:
        # Missing/invalid OpenRouter key or upstream model error during embedding
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        try:
            os.remove(file_path)
        except OSError:
            pass
        vector_store.delete_by_doc_id(doc_id)
        raise HTTPException(status_code=502, detail=f"Ingest failed: {e!s}") from e

    await thread_store.insert_pending_suggestions(doc_id, user_id)
    asyncio.create_task(run_generation_task(doc_id, fname, chunks))

    return UploadResponse(doc_id=doc_id, filename=fname)
