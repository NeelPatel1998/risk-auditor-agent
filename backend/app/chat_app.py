"""Uvicorn entry: Chat service — `uvicorn app.chat_app:app`."""
from app.app_factory import create_chat_app

app = create_chat_app()
