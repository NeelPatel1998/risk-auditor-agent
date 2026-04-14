from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app

AUTH_HEADERS = {"X-User-Id": "Neel", "X-Admin-Password": "admin"}


def test_thread_title_returns_sanitized_title(monkeypatch):
    monkeypatch.setattr(
        "app.routers.chat.llm_client.chat",
        AsyncMock(return_value='  "Model Risk Overview"  '),
    )
    with TestClient(app) as client:
        r = client.post(
            "/chat/thread-title",
            json={"user_message": "What is model risk?", "assistant_message": "Model risk refers to errors in models."},
            headers=AUTH_HEADERS,
        )
    assert r.status_code == 200
    data = r.json()
    assert "title" in data
    assert len(data["title"]) <= 80
    assert "model" in data["title"].lower()


def test_thread_title_rejects_missing_auth():
    with TestClient(app) as client:
        r = client.post(
            "/chat/thread-title",
            json={"user_message": "What is model risk?", "assistant_message": "Model risk refers to errors in models."},
        )
    assert r.status_code == 401
