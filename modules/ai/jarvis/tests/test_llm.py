"""Testes do cliente LLM — payload de chat e controle de thinking (Qwen3)."""

from __future__ import annotations

import pytest
import requests

from jarvis.core.config import Config
from jarvis.providers.llm import LLMClient, LLMError


class _FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


def _resp_with(data):
    return _FakeResp(data)


@pytest.mark.integration
def test_chat_sends_disable_thinking_by_default(monkeypatch):
    """Default (lab/CPU): thinking desligado — chat_template_kwargs no payload."""
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return _resp_with({
            "choices": [{"message": {"content": "ok"}}],
        })

    monkeypatch.setattr("jarvis.providers.llm.requests.post", fake_post)
    out = LLMClient(Config()).chat([{"role": "user", "content": "oi"}])
    assert out == "ok"
    assert captured["payload"]["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.integration
def test_chat_omits_disable_thinking_when_enabled(monkeypatch):
    """JARVIS_LLM_DISABLE_THINKING=0 → thinking reabilitado (payload limpo)."""
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return _resp_with({
            "choices": [{"message": {"content": "ok"}}],
        })

    monkeypatch.setattr("jarvis.providers.llm.requests.post", fake_post)
    cfg = Config(llm_disable_thinking=False)
    LLMClient(cfg).chat([{"role": "user", "content": "oi"}])
    assert "chat_template_kwargs" not in captured["payload"]


@pytest.mark.integration
def test_embed_truncates_long_text(monkeypatch):
    # ctx do modelo de embedding é 512 tokens — texto longo deve ser truncado
    # antes do POST (o llama-server rejeita com HTTP 400 caso contrário)
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["input"] = json["input"]
        return _FakeResp({"data": [{"embedding": [0.1, 0.2]}]})

    monkeypatch.setattr("jarvis.providers.llm.requests.post", fake_post)
    llm = LLMClient(Config(embed_base_url="http://x"))
    long_text = "palavra " * 500  # ~4000 chars
    vec = llm.embed(long_text)
    assert vec == [0.1, 0.2]
    assert len(captured["input"]) <= LLMClient._EMBED_MAX_CHARS


def test_embed_raises_on_http_400(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResp({"error": "ctx exceeded"}, status=400)

    monkeypatch.setattr("jarvis.providers.llm.requests.post", fake_post)
    llm = LLMClient(Config(embed_base_url="http://x"))
    with pytest.raises(LLMError):
        llm.embed("texto")


def test_chat_raises_llm_error_on_http_failure(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResp({}, status=500)

    monkeypatch.setattr("jarvis.providers.llm.requests.post", fake_post)
    with pytest.raises(LLMError):
        LLMClient(Config()).chat([{"role": "user", "content": "oi"}])
