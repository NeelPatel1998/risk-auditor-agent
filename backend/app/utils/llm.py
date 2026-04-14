import json
from typing import Any, AsyncIterator

import httpx
from httpx import ResponseNotRead

from app.env import EMBEDDING_MODEL, LLM_MAX_TOKENS, LLM_MODEL, OPENROUTER_API_KEY


def _detail_from_openrouter_json_body(raw: bytes) -> str:
    """Parse OpenRouter-style JSON error from raw bytes (never touch httpx Response on a stream)."""
    if not raw.strip():
        return ""
    try:
        j = json.loads(raw.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeError):
        return (raw.decode("utf-8", errors="replace") or "")[:300]
    err = j.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err)[:800]
    if isinstance(err, str):
        return err[:800]
    return ""


def _openrouter_error_message_for_status(status_code: int, detail: str) -> str:
    code = status_code
    if code in (401, 403):
        return (
            "OpenRouter rejected the request (authentication). "
            "Set OPENROUTER_API_KEY in risk-auditor/backend/.env (or risk-auditor/.env for Docker) "
            "from https://openrouter.ai/keys — then restart uvicorn or `docker compose up -d --force-recreate`."
        )
    if code == 429:
        return "OpenRouter rate limit (429). Wait a moment and try again."
    return f"OpenRouter HTTP {code}. {detail}".strip()


def _openrouter_error_message(resp: httpx.Response) -> str:
    """Build a user-facing message from a failed OpenRouter response (body must already be readable)."""
    detail = ""
    try:
        j = resp.json()
        err = j.get("error")
        if isinstance(err, dict):
            detail = str(err.get("message") or err)
        elif isinstance(err, str):
            detail = err
    except Exception:
        try:
            detail = (resp.text or "")[:300]
        except Exception:
            detail = ""
    return _openrouter_error_message_for_status(resp.status_code, detail)


def _raise_openrouter_response(resp: httpx.Response) -> None:
    """Normalize OpenRouter failures for non-streaming responses (body already loaded)."""
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise ValueError(_openrouter_error_message(resp)) from e


async def _raise_openrouter_stream_response(resp: httpx.Response) -> None:
    """
    Same as _raise_openrouter_response but for client.stream() responses.
    Never call resp.json() / resp.text here — use aread() bytes only (avoids ResponseNotRead).
    """
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        body = b""
        try:
            body = await resp.aread()
        except Exception:
            pass
        detail = _detail_from_openrouter_json_body(body)
        msg = _openrouter_error_message_for_status(resp.status_code, detail)
        raise ValueError(msg) from e


class LLMClient:
    def __init__(self) -> None:
        self.base_url = "https://openrouter.ai/api/v1"
        self.headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "Risk Auditor AI",
        }

    def _require_key(self) -> None:
        if not OPENROUTER_API_KEY:
            raise ValueError(
                "OPENROUTER_API_KEY is not set. Add a line OPENROUTER_API_KEY=sk-or-v1-... to "
                "risk-auditor/backend/.env (same as local uvicorn), or risk-auditor/.env next to "
                "docker-compose.yml, then restart the server or recreate containers."
            )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        self._require_key()
        cap = LLM_MAX_TOKENS if max_tokens is None else max_tokens
        payload: dict[str, Any] = {
            "model": LLM_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": cap,
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=120.0,
            )
            _raise_openrouter_response(r)
            data = r.json()
            return data["choices"][0]["message"]["content"] or ""

    async def chat_stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        self._require_key()
        payload = {
            "model": LLM_MODEL,
            "messages": messages,
            "temperature": 0.2,
            "stream": True,
            "max_tokens": LLM_MAX_TOKENS,
        }
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=120.0,
            ) as response:
                await _raise_openrouter_stream_response(response)
                saw_done = False
                try:
                    async for line in response.aiter_lines():
                        if saw_done:
                            continue
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line.removeprefix("data: ").strip()
                        if data_str == "[DONE]":
                            saw_done = True
                            continue
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield content
                except ResponseNotRead as e:
                    raise ValueError(
                        "OpenRouter closed the stream before the full body was available. "
                        "Try again; if it keeps happening, verify OPENROUTER_API_KEY and LLM_MODEL."
                    ) from e

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self._require_key()
        from app.services.embed_cache import embed_cache

        # Check cache first
        cached = embed_cache.get_many(texts)
        results: list[list[float] | None] = list(cached)
        miss_indices = [i for i, v in enumerate(results) if v is None]

        if miss_indices:
            miss_texts = [texts[i] for i in miss_indices]
            payload = {"model": EMBEDDING_MODEL, "input": miss_texts}
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{self.base_url}/embeddings",
                    headers=self.headers,
                    json=payload,
                    timeout=120.0,
                )
                _raise_openrouter_response(r)
                data = r.json()
                fresh = [e["embedding"] for e in data["data"]]

            # Fill results and persist to cache
            for idx, emb in zip(miss_indices, fresh):
                results[idx] = emb
            embed_cache.put_many(miss_texts, fresh)

        return results  # type: ignore[return-value]


llm_client = LLMClient()
