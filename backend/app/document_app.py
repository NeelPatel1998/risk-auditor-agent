"""Uvicorn entry: Document service — `uvicorn app.document_app:app`."""
from app.app_factory import create_document_app

app = create_document_app()
