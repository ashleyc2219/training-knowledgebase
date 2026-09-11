"""app/agent/llm.py：Ollama provider 與 provider 鏈順序。

不碰網路：只 stub `httpx.post`，其餘走真程式。
"""

from __future__ import annotations

import httpx
import pytest

from app.agent import llm
from app.config import Settings


class _Resp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _capture_post(monkeypatch, status: int = 200, content: str = '{"a": 1}') -> list[dict]:
    calls: list[dict] = []

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return _Resp(status, {"message": {"role": "assistant", "content": content}, "done": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


# --- _ollama ---


def test_ollama_unavailable_when_base_url_unset(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "")
    with pytest.raises(llm.LLMUnavailable):
        llm._ollama("p", "{}")


def test_ollama_posts_chat_with_model_and_bearer(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com/")
    monkeypatch.setenv("OLLAMA_API_KEY", "k-test")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:31b")
    calls = _capture_post(monkeypatch, content='{"title": "x"}')

    out = llm._ollama("寫教學", '{"title": string}')

    assert out == {"title": "x"}
    call = calls[0]
    assert call["url"] == "https://ollama.com/api/chat"
    assert call["headers"]["Authorization"] == "Bearer k-test"
    body = call["json"]
    assert body["model"] == "gemma4:31b"
    assert body["stream"] is False
    assert body["format"] == {"type": "object"}
    assert body["messages"][0]["role"] == "system"
    assert '{"title": string}' in body["messages"][0]["content"]
    assert body["messages"][-1] == {"role": "user", "content": "寫教學"}


def test_ollama_default_model_and_no_auth_header_without_key(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_API_KEY", "")
    monkeypatch.setenv("OLLAMA_MODEL", "")
    calls = _capture_post(monkeypatch)

    llm._ollama("p", "{}")

    assert calls[0]["json"]["model"] == "gemma4:31b"
    assert "Authorization" not in calls[0]["headers"]


def test_ollama_non_200_raises_unavailable(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com")
    _capture_post(monkeypatch, status=401)
    with pytest.raises(llm.LLMUnavailable, match="401"):
        llm._ollama("p", "{}")


def test_ollama_connection_error_raises_unavailable(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:1")

    def boom(url, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(llm.LLMUnavailable):
        llm._ollama("p", "{}")


def test_ollama_extracts_json_from_fenced_text(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    _capture_post(monkeypatch, content='```json\n{"a": 1}\n```')
    assert llm._ollama("p", "{}") == {"a": 1}


# --- complete_json 鏈順序：RocketRide → Ollama → Anthropic ---


def test_complete_json_prefers_ollama_over_anthropic(monkeypatch):
    monkeypatch.setattr(llm, "_ollama", lambda p, s: {"from": "ollama"})
    monkeypatch.setattr(llm, "_anthropic", lambda p, s: {"from": "anthropic"})
    assert llm.complete_json("p", "{}") == {"from": "ollama"}


def test_complete_json_falls_back_to_anthropic_when_ollama_unavailable(monkeypatch):
    def down(p, s):
        raise llm.LLMUnavailable("ollama down")

    monkeypatch.setattr(llm, "_ollama", down)
    monkeypatch.setattr(llm, "_anthropic", lambda p, s: {"from": "anthropic"})
    assert llm.complete_json("p", "{}") == {"from": "anthropic"}


def test_complete_json_error_lists_all_providers(monkeypatch):
    def no_ollama(p, s):
        raise llm.LLMUnavailable("no ollama")

    def no_key(p, s):
        raise llm.LLMUnavailable("no key")

    monkeypatch.setattr(llm, "_ollama", no_ollama)
    monkeypatch.setattr(llm, "_anthropic", no_key)
    with pytest.raises(llm.LLMUnavailable, match="ollama: no ollama.*anthropic: no key"):
        llm.complete_json("p", "{}")


# --- Settings ---


def test_settings_reads_ollama_fields(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com")
    monkeypatch.setenv("OLLAMA_API_KEY", "k")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:31b")
    s = Settings.from_env()
    assert (s.OLLAMA_BASE_URL, s.OLLAMA_API_KEY, s.OLLAMA_MODEL) == ("https://ollama.com", "k", "gemma4:31b")


def test_settings_ollama_empty_means_unset_and_default_model(monkeypatch):
    for key in ("OLLAMA_BASE_URL", "OLLAMA_API_KEY", "OLLAMA_MODEL"):
        monkeypatch.setenv(key, "")
    s = Settings.from_env()
    assert s.OLLAMA_BASE_URL is None
    assert s.OLLAMA_API_KEY is None
    assert s.OLLAMA_MODEL == "gemma4:31b"
