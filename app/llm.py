"""OpenRouter client: sync completion and streaming with retries and model fallbacks."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Iterator, Optional

import httpx
from dotenv import load_dotenv

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "z-ai/glm-5.3-flash"
DEFAULT_FALLBACKS = "particle-ai/particle-1:free,inclusionai/ling-3.2-flash:free"
TIMEOUT = httpx.Timeout(60.0, connect=15.0)
MAX_ATTEMPTS = 3


class LLMNotConfigured(Exception):
    """Raised when no OpenRouter API key is available."""


class LLMError(Exception):
    """Raised with a user friendly message when the LLM call fails."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class _Retryable(Exception):
    def __init__(self, message: str, same_model: bool = True):
        super().__init__(message)
        self.message = message
        self.same_model = same_model


class _Fatal(LLMError):
    pass


# Hooks so tests can inject a mock transport and skip real sleeping.
_transport: Optional[httpx.BaseTransport] = None
_sleep = time.sleep


def _env() -> None:
    load_dotenv(override=True)


def _key() -> str:
    _env()
    return (os.getenv("OPENROUTER_API_KEY") or "").strip().strip('"').strip("'")


def is_configured() -> bool:
    key = _key()
    return bool(key) and not key.lower().startswith("your")


def current_model() -> str:
    _env()
    return (os.getenv("OPENROUTER_MODEL") or "").strip() or DEFAULT_MODEL


def _models() -> list[str]:
    _env()
    primary = current_model()
    raw = os.getenv("OPENROUTER_FALLBACK_MODELS")
    if raw is None or not raw.strip():
        raw = DEFAULT_FALLBACKS
    out = [primary]
    for m in raw.split(","):
        m = m.strip()
        if m and m not in out:
            out.append(m)
    return out


def _headers(key: str) -> dict:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "RagBot",
    }


_pool: Optional[httpx.Client] = None
_pool_transport = None
_pool_lock = threading.Lock()


def _client() -> httpx.Client:
    """One pooled keep-alive client, shared by all calls (rebuilt only if the test transport changes)."""
    global _pool, _pool_transport
    with _pool_lock:
        if _pool is None or _pool_transport is not _transport:
            _pool = httpx.Client(
                timeout=TIMEOUT,
                transport=_transport,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=60.0),
            )
            _pool_transport = _transport
        return _pool


def models() -> list[str]:
    return _models()


def _error_text(resp: httpx.Response) -> str:
    try:
        data = json.loads(resp.read().decode("utf-8", "replace"))
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or "")
        if isinstance(err, str):
            return err
    except Exception:
        pass
    return ""


def _check_status(resp: httpx.Response) -> None:
    code = resp.status_code
    if code < 400:
        return
    detail = _error_text(resp)
    if code in (401, 403):
        raise _Fatal("The OpenRouter API key was rejected. Check OPENROUTER_API_KEY in .env.")
    if code == 402:
        raise _Fatal("OpenRouter reports insufficient credits for this model. Add credits or choose a free model.")
    if code == 429:
        raise _Retryable("The model is rate limited right now.")
    if code in (404, 400):
        raise _Retryable(
            "The selected model is unavailable." + (f" ({detail})" if detail else ""),
            same_model=False,
        )
    if code == 408 or code >= 500:
        raise _Retryable(f"The model provider had a temporary problem (HTTP {code}).")
    raise _Fatal(f"OpenRouter returned an error (HTTP {code}). {detail}".strip())


def _payload(model: str, messages: list[dict], max_tokens: int, temperature: float, stream: bool) -> dict:
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream,
    }
    # Free models reason before answering; keep that short so answers start quickly.
    body["reasoning"] = {"effort": "low"}
    if stream:
        body["stream_options"] = {"include_usage": True}
    return body


def _final_message(failures: list[str]) -> str:
    if failures and all("rate limited" in f for f in failures):
        return "All configured models are rate limited right now. Wait a moment and try again, or add a fallback model."
    if failures and all("unavailable" in f for f in failures):
        return "None of the configured models are available. Check OPENROUTER_MODEL in .env."
    return "The language model could not be reached or returned nothing. Please try again shortly."


def _one_shot(model: str, key: str, messages, max_tokens, temperature) -> str:
    try:
        c = _client()
        resp = c.post(API_URL, headers=_headers(key), json=_payload(model, messages, max_tokens, temperature, False))
        _check_status(resp)
        try:
            data = resp.json()
        except ValueError:
            raise _Retryable("The model returned an unreadable response.")
    except (httpx.TimeoutException, httpx.TransportError):
        raise _Retryable("The connection to the model timed out.")
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise _Retryable(f"The model returned an error. {msg or ''}".strip(), same_model=False)
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        text = ""
    if not text.strip():
        raise _Retryable("The model returned an empty response.")
    return text


def complete(messages: list[dict], max_tokens: int = 800, temperature: float = 0.2) -> str:
    if not is_configured():
        raise LLMNotConfigured("OPENROUTER_API_KEY is not set")
    key = _key()
    failures: list[str] = []
    for model in _models():
        for attempt in range(MAX_ATTEMPTS):
            try:
                return _one_shot(model, key, messages, max_tokens, temperature)
            except _Fatal as e:
                raise LLMError(e.message)
            except _Retryable as e:
                failures.append(e.message)
                if not e.same_model or attempt == MAX_ATTEMPTS - 1:
                    break
                _sleep(2 ** attempt)
    raise LLMError(_final_message(failures))


def _words(text: str) -> int:
    return len(text.split())


def _stream_once(model: str, key: str, messages, max_tokens, temperature) -> Iterator[dict]:
    """Yield event dicts. Raises _Retryable only if nothing has been yielded yet."""
    yielded = False
    answer = ""
    usage = None
    try:
        c = _client()
        with c.stream(
            "POST", API_URL, headers=_headers(key),
            json=_payload(model, messages, max_tokens, temperature, True),
        ) as resp:
            _check_status(resp)
            for line in resp.iter_lines():
                line = line.strip()
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if obj.get("error"):
                    err = obj["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    if yielded:
                        raise LLMError("The model stopped responding part way through. Please try again.")
                    raise _Retryable(f"The model returned an error. {msg or ''}".strip(), same_model=False)
                if isinstance(obj.get("usage"), dict):
                    usage = obj["usage"]
                try:
                    delta = obj["choices"][0].get("delta") or {}
                except (KeyError, IndexError, TypeError, AttributeError):
                    delta = {}
                think = delta.get("reasoning") or delta.get("reasoning_content")
                if isinstance(think, str) and think:
                    yielded = True
                    yield {"type": "thinking", "text": think}
                text = delta.get("content")
                if isinstance(text, str) and text:
                    yielded = True
                    answer += text
                    yield {"type": "token", "text": text}
    except (httpx.TimeoutException, httpx.TransportError):
        if yielded:
            raise LLMError("The connection to the model dropped part way through. Please try again.")
        raise _Retryable("The connection to the model timed out.")
    if not answer.strip():
        raise _Retryable("The model returned an empty response.")
    ev = {"type": "usage", "model": model, "estimated": False,
          "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
    if usage and (usage.get("prompt_tokens") is not None or usage.get("completion_tokens") is not None):
        details = usage.get("prompt_tokens_details") or {}
        ev["prompt_tokens"] = int(usage.get("prompt_tokens") or 0)
        ev["completion_tokens"] = int(usage.get("completion_tokens") or 0)
        ev["cached_tokens"] = int((details.get("cached_tokens") if isinstance(details, dict) else 0) or 0)
    else:
        ev["prompt_tokens"] = int(sum(_words(str(m.get("content", ""))) for m in messages) * 1.3)
        ev["completion_tokens"] = int(_words(answer) * 1.3)
        ev["estimated"] = True
    yield ev


def _ordered(preferred: Optional[str]) -> list[str]:
    """Configured models with the user's pick first (only if it is a configured model)."""
    chain = _models()
    if preferred and preferred in chain:
        return [preferred] + [m for m in chain if m != preferred]
    return chain


def stream_events(messages: list[dict], max_tokens: int = 900, temperature: float = 0.1,
                  model: Optional[str] = None) -> Iterator[dict]:
    if not is_configured():
        raise LLMNotConfigured("OPENROUTER_API_KEY is not set")
    key = _key()
    failures: list[str] = []
    for model in _ordered(model):
        for attempt in range(MAX_ATTEMPTS):
            try:
                for ev in _stream_once(model, key, messages, max_tokens, temperature):
                    yield ev
                return
            except _Fatal as e:
                raise LLMError(e.message)
            except _Retryable as e:
                failures.append(e.message)
                if not e.same_model or attempt == MAX_ATTEMPTS - 1:
                    break
                _sleep(2 ** attempt)
    raise LLMError(_final_message(failures))


def stream(messages: list[dict], max_tokens: int = 900, temperature: float = 0.1) -> Iterator[str]:
    for ev in stream_events(messages, max_tokens, temperature):
        if ev["type"] == "token":
            yield ev["text"]
