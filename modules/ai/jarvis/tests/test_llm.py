"""Testes do cliente LLM — payload de chat e controle de thinking (Qwen3)."""

from __future__ import annotations

from unittest.mock import Mock

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


def _mock_session(fake_resp):
    """Retorna um Mock(spec=requests.Session) que devolve *fake_resp* em .post()."""
    session = Mock(spec=requests.Session)
    session.post.return_value = fake_resp
    return session


@pytest.mark.integration
def test_chat_sends_disable_thinking_by_default():
    """Default (lab/CPU): thinking desligado — chat_template_kwargs no payload."""
    captured = {}

    def capture_post(*args, **kwargs):
        captured["payload"] = kwargs.get("json")
        return _resp_with({
            "choices": [{"message": {"content": "ok"}}],
        })

    session = Mock(spec=requests.Session)
    session.post.side_effect = capture_post
    out = LLMClient(Config(), session=session).chat([{"role": "user", "content": "oi"}])
    assert out == "ok"
    assert captured["payload"]["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.integration
def test_chat_omits_disable_thinking_when_enabled():
    """JARVIS_LLM_DISABLE_THINKING=0 → thinking reabilitado (payload limpo)."""
    captured = {}

    def capture_post(*args, **kwargs):
        captured["payload"] = kwargs.get("json")
        return _resp_with({
            "choices": [{"message": {"content": "ok"}}],
        })

    session = Mock(spec=requests.Session)
    session.post.side_effect = capture_post
    cfg = Config(llm_disable_thinking=False)
    LLMClient(cfg, session=session).chat([{"role": "user", "content": "oi"}])
    assert "chat_template_kwargs" not in captured["payload"]


@pytest.mark.integration
def test_embed_truncates_long_text():
    # ctx do modelo de embedding é 512 tokens — texto longo deve ser truncado
    # antes do POST (o llama-server rejeita com HTTP 400 caso contrário)
    captured = {}

    def capture_post(*args, **kwargs):
        captured["input"] = kwargs["json"]["input"]
        return _FakeResp({"data": [{"embedding": [0.1, 0.2]}]})

    session = Mock(spec=requests.Session)
    session.post.side_effect = capture_post
    llm = LLMClient(Config(embed_base_url="http://x"), session=session)
    long_text = "palavra " * 500  # ~4000 chars
    vec = llm.embed(long_text)
    assert vec == [0.1, 0.2]
    max_chars = int(LLMClient._EMBED_MAX_TOKENS * LLMClient._EMBED_CHARS_PER_TOKEN_ESTIMATE)
    assert len(captured["input"]) <= max_chars


def test_embed_raises_on_http_400():
    session = _mock_session(_FakeResp({"error": "ctx exceeded"}, status=400))
    llm = LLMClient(Config(embed_base_url="http://x"), session=session)
    with pytest.raises(LLMError):
        llm.embed("texto")


def test_chat_raises_llm_error_on_http_failure():
    session = _mock_session(_FakeResp({}, status=500))
    with pytest.raises(LLMError):
        LLMClient(Config(), session=session).chat([{"role": "user", "content": "oi"}])
