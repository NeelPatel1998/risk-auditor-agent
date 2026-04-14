"""Smoke tests — no API keys or network required."""

import pytest
from fastapi.testclient import TestClient

from app.app_factory import create_chat_app, create_document_app, create_monolith_app
from app.main import app


@pytest.mark.parametrize(
    "factory,needle",
    [
        (create_monolith_app, "Risk Auditor AI"),
        (create_document_app, "Document"),
        (create_chat_app, "Chat"),
    ],
)
def test_app_factory_titles(factory, needle):
    assert needle in factory().title


def test_monolith_health():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"
