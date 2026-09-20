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
    """Default (lab/CPU): chat sends messages and returns content."""
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
    # chat_template_kwargs is now added by harness via extra=, not by LLMClient.chat() by default
    assert captured["payload"]["messages"][0]["content"] == "oi"


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


class _FakeStreamBackend:
    """Backend mínimo com chat_stream gerador (para testar abandono)."""

    def __init__(self, tokens=("a", "b", "c")):
        self._tokens = tokens

    def chat_stream(self, messages, **kw):
        yield from self._tokens

    def close(self):
        pass


def _half_open_client(monkeypatch):
    """LLMClient cujo breaker está em HALF_OPEN (OPEN expirado)."""
    from jarvis.providers.llm import _CircuitState

    client = LLMClient(Config(), backend=_FakeStreamBackend())
    monkeypatch.setattr(client._breaker, "_state", _CircuitState.OPEN)
    monkeypatch.setattr(client._breaker, "_opened_at", 0.0)
    monkeypatch.setattr(client._breaker._cfg, "recovery_timeout", 0.0)
    assert client._breaker.state == "half_open"
    return client


def test_stream_abandon_releases_half_open_slot(monkeypatch):
    """Abandonar stream em HALF_OPEN não trava o circuito (liveness).

    Regressão: before_call() incrementava _half_open_calls_in_flight e o
    GeneratorExit pulava record_success/failure — toda chamada seguinte
    falhava com CircuitOpenError para sempre.
    """
    client = _half_open_client(monkeypatch)
    gen = client.chat_stream([{"role": "user", "content": "oi"}])
    next(gen)  # consome 1 token e abandona
    gen.close()  # GeneratorExit no yield
    # Slot liberado: nova chamada de sondagem é aceita.
    gen2 = client.chat_stream([{"role": "user", "content": "oi"}])
    assert list(gen2) == ["a", "b", "c"]


def test_stream_success_closes_half_open(monkeypatch):
    """Stream consumido até o fim registra sucesso (HALF_OPEN -> CLOSED)."""
    client = _half_open_client(monkeypatch)
    assert list(client.chat_stream([{"role": "user", "content": "oi"}])) == ["a", "b", "c"]
    assert client._breaker.state == "closed"


def test_embed_failure_counts_for_breaker():
    """embed() participa de breaker próprio (antes: ponto cego)."""
    from jarvis.providers.llm import CircuitOpenError

    class _Boom:
        def embed(self, text, model=None):
            raise RuntimeError("down")

        def close(self):
            pass

    client = LLMClient(Config(), backend=_Boom())
    for _ in range(4):
        try:
            client.embed("x")
        except Exception:
            pass
    assert client._embed_breaker.state == "open"
    try:
        client.embed("x")
    except CircuitOpenError:
        pass
    else:
        raise AssertionError("breaker de embed deveria estar aberto")


def test_embed_breaker_independent_from_chat():
    """Domínios de falha distintos: chat morto não veta embed (8081)."""
    from jarvis.providers.llm import CircuitOpenError

    class _ChatDownEmbedUp:
        def chat(self, **kw):
            raise RuntimeError("chat down")

        def embed(self, text, model=None):
            return [0.1, 0.2]

        def close(self):
            pass

    client = LLMClient(Config(), backend=_ChatDownEmbedUp())
    for _ in range(4):
        try:
            client.chat([{"role": "user", "content": "oi"}])
        except Exception:
            pass
    assert client._breaker.state == "open"
    assert client.embed("x") == [0.1, 0.2]


def test_chat_full_returns_reasoning():
    """chat_full() expõe reasoning_content (vision precisa)."""
    from jarvis.providers.llm_backend import ChatResponse

    class _Think:
        def chat(self, **kw):
            return ChatResponse(content="", reasoning="hmm")

        def close(self):
            pass

    resp = LLMClient(Config(), backend=_Think()).chat_full(
        [{"role": "user", "content": "oi"}])
    assert resp.reasoning == "hmm"


@pytest.mark.integration
def test_chat_sends_thinking_off_when_disabled():
    """JARVIS_LLM_DISABLE_THINKING=1 → chat_template_kwargs no payload."""
    captured = {}

    def capture_post(*args, **kwargs):
        captured["payload"] = kwargs.get("json")
        return _resp_with({
            "choices": [{"message": {"content": "391"}}],
        })

    session = Mock(spec=requests.Session)
    session.post.side_effect = capture_post
    cfg = Config(llm_disable_thinking=True)
    out = LLMClient(cfg, session=session).chat([{"role": "user", "content": "oi"}])
    assert out == "391"
    assert captured["payload"]["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.integration
def test_stream_respects_thinking_off():
    """chat_stream envia o kwarg (antes: streams de thinking rendiam zero)."""
    captured = {}

    class _SSE:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_lines(self, decode_unicode=False):
            yield 'data: {"choices": [{"delta": {"content": "oi"}}]}'
            yield "data: [DONE]"

    def capture_post(*args, **kwargs):
        captured["payload"] = kwargs.get("json")
        return _SSE(kwargs.get("json"))

    session = Mock(spec=requests.Session)
    session.post.side_effect = capture_post
    cfg = Config(llm_disable_thinking=True)
    toks = list(LLMClient(cfg, session=session).chat_stream(
        [{"role": "user", "content": "oi"}]))
    assert toks == ["oi"]
    assert captured["payload"]["chat_template_kwargs"] == {"enable_thinking": False}


class _CountingBackend:
    """Backend que conta chamadas chat (mede passes de revisão)."""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, **kw):
        from jarvis.providers.llm_backend import ChatResponse
        self.calls += 1
        # Sem aspas/citações: review nunca encontra evidência grounded.
        return ChatResponse(content="resposta direta sem citacoes", tool_calls=[])

    def close(self):
        pass


def _msgs():
    # Task longa/factual: passa pelo gate H3 sem downgrade (isola o teste
    # no comportamento de role).
    return [{"role": "user", "content": (
        "Analise factual multi-step em profundidade: compare as evidências "
        "documentadas sobre o mecanismo e conclua com raciocínio detalhado.")}]


class TestReasoningPlacement:
    """Placement de reasoning: orquestrador raciocina, worker executa.

    (orchestrator-only reasoning concentra o ganho; revisão em subagente
    tem benefício limitado/negativo e custo integral em modelo pequeno.)
    """

    def test_orchestrator_medium_faz_review(self):
        b = _CountingBackend()
        LLMClient(Config(), backend=b).chat_with_tools(
            _msgs(), reasoning_effort="medium", role="orchestrator")
        assert b.calls == 2  # 1 inicial + 1 revisão

    def test_worker_medium_forcado_low(self):
        b = _CountingBackend()
        LLMClient(Config(), backend=b).chat_with_tools(
            _msgs(), reasoning_effort="medium", role="worker")
        assert b.calls == 1  # zero revisões, pedido ignorado

    def test_worker_high_forcado_low(self):
        b = _CountingBackend()
        LLMClient(Config(), backend=b).chat_with_tools(
            _msgs(), reasoning_effort="high", role="worker")
        assert b.calls == 1

    def test_role_default_e_orchestrator(self):
        b = _CountingBackend()
        LLMClient(Config(), backend=b).chat_with_tools(
            _msgs(), reasoning_effort="medium")
        assert b.calls == 2

    def test_role_invalido_falha_fechado(self):
        b = _CountingBackend()
        with pytest.raises(ValueError):
            LLMClient(Config(), backend=b).chat_with_tools(
                _msgs(), role="planner")
        assert b.calls == 0


def test_review_prompt_polymorphic():
    """Framing da revisão muda por foco (dono 19/09: thinking como revisão
    externalizada; sintaxe ≠ factual)."""
    from jarvis.providers.llm import _review_prompt
    assert "SINTAXE" in _review_prompt("syntax")
    assert "json.dumps" in _review_prompt("syntax")
    assert "SINTAXE" not in _review_prompt(None)
    assert "CITAÇÃO EXATA" in _review_prompt("factual")


class _ScriptedBackend:
    """Backend com roteiro: call quebrada, depois revisão (adota/recusa)."""

    def __init__(self, review_calls):
        self.calls = 0
        self.review_calls = review_calls
        self.tools_seen = []

    def chat(self, messages, **kw):
        from jarvis.providers.llm_backend import ChatResponse
        import json as _j
        self.calls += 1
        self.tools_seen.append(kw.get("tools"))
        if self.calls == 1:
            return ChatResponse(content="", tool_calls=[{
                "id": "c1", "type": "function",
                "function": {"name": "write_file", "arguments": _j.dumps(
                    {"path": "d.sh", "content": "#!/bin/bash\necho hi\n"})}}])
        return ChatResponse(content="revisado", tool_calls=self.review_calls)

    def close(self):
        pass


def _fixed_call():
    import json as _j
    return [{"id": "c2", "type": "function",
             "function": {"name": "write_file", "arguments": _j.dumps(
                 {"path": "d.sh", "content": "#!/bin/bash\necho fixed\n"})}}]


_TOOLS = [{"type": "function",
           "function": {"name": "write_file",
                        "description": "write",
                        "parameters": {"type": "object",
                                       "properties": {}}}}]


def test_syntax_review_adopts_same_path():
    """Revisão syntax com MESMO path é adotada (é o que o loop despacha)."""
    b = _ScriptedBackend(_fixed_call())
    r = LLMClient(Config(), backend=b).chat_with_tools(
        _msgs(), tools=_TOOLS, reasoning_effort="medium",
        review_focus="syntax", role="orchestrator")
    assert b.calls == 2
    assert b.tools_seen[1] is not None  # review recebe tools p/ emitir calls
    assert r.tool_calls == _fixed_call()


def test_syntax_review_rejects_drift():
    """Revisão que muda de path é descartada (mantém original)."""
    import json as _j
    other = [{"id": "c9", "type": "function",
              "function": {"name": "write_file", "arguments": _j.dumps(
                  {"path": "other.sh", "content": "x"})}}]
    b = _ScriptedBackend(other)
    r = LLMClient(Config(), backend=b).chat_with_tools(
        _msgs(), reasoning_effort="medium", review_focus="syntax",
        role="orchestrator")
    assert b.calls == 2
    import json as _j2
    assert "d.sh" in _j2.dumps(r.tool_calls)
    assert "other.sh" not in _j2.dumps(r.tool_calls)
