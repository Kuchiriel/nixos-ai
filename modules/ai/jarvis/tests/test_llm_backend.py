"""Tests for LLM backend abstraction.

Tests the adapter contract, backend factory, and configuration.
Uses mock backends to verify behavior without requiring a real server.
"""

import json
import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

from jarvis.providers.llm_backend import (
    LLMBackend, ChatResponse, EmbeddingResponse, BackendInfo, ChatMessage
)
from jarvis.providers.llm_factory import create_backend, list_backends
from jarvis.core.config import Config


# ---------------------------------------------------------------------------
# Mock backend for testing
# ---------------------------------------------------------------------------

class MockLLMBackend(LLMBackend):
    """Mock backend for testing the interface contract."""
    
    def __init__(self, base_url: str = "http://mock:8080", model: str = "mock-model"):
        self._base_url = base_url
        self._model = model
        self._chat_calls = []
        self._embed_calls = []
    
    def chat(self, messages, *, temperature=0.0, max_tokens=None,
             tools=None, tool_choice=None, stream=False, extra=None):
        self._chat_calls.append({
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": tools,
        })
        return ChatResponse(
            content="Mock response",
            tool_calls=[],
            finish_reason="stop",
            usage={"total_tokens": 100},
            latency_seconds=0.1,
            backend="mock",
            model_id=self._model,
        )
    
    def embed(self, text, model=None):
        self._embed_calls.append({"text": text, "model": model})
        return [0.1, 0.2, 0.3]
    
    def health(self, timeout=3.0):
        return True
    
    def info(self):
        return BackendInfo(
            backend_type="mock",
            model_name=self._model,
            n_ctx=32768,
            n_gpu_layers=45,
            is_available=True,
        )


# ---------------------------------------------------------------------------
# Tests: ChatResponse
# ---------------------------------------------------------------------------

class TestChatResponse:
    """Test ChatResponse dataclass."""
    
    def test_default_values(self):
        resp = ChatResponse()
        assert resp.content == ""
        assert resp.tool_calls == []
        assert resp.finish_reason == ""
        assert resp.usage == {}
        assert resp.latency_seconds == 0.0
        assert resp.backend == ""
    
    def test_with_content(self):
        resp = ChatResponse(content="Hello", backend="llama-cpp")
        assert resp.content == "Hello"
        assert resp.backend == "llama-cpp"
    
    def test_with_tool_calls(self):
        tool_calls = [{"function": {"name": "test", "arguments": "{}"}}]
        resp = ChatResponse(tool_calls=tool_calls)
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0]["function"]["name"] == "test"


# ---------------------------------------------------------------------------
# Tests: BackendInfo
# ---------------------------------------------------------------------------

class TestBackendInfo:
    """Test BackendInfo dataclass."""
    
    def test_default_values(self):
        info = BackendInfo(backend_type="test")
        assert info.backend_type == "test"
        assert info.model_name == ""
        assert info.n_ctx == 0
        assert info.is_available == False
    
    def test_with_values(self):
        info = BackendInfo(
            backend_type="llama-cpp",
            model_name="Qwen3-4B",
            n_ctx=32768,
            n_gpu_layers=45,
            is_available=True,
        )
        assert info.model_name == "Qwen3-4B"
        assert info.n_ctx == 32768
        assert info.n_gpu_layers == 45


# ---------------------------------------------------------------------------
# Tests: LLMBackend interface
# ---------------------------------------------------------------------------

class TestLLMBackendInterface:
    """Test that MockLLMBackend correctly implements the interface."""
    
    def test_chat(self):
        backend = MockLLMBackend()
        messages = [{"role": "user", "content": "Hello"}]
        resp = backend.chat(messages=messages, temperature=0.5)
        
        assert isinstance(resp, ChatResponse)
        assert resp.content == "Mock response"
        assert resp.backend == "mock"
        assert len(backend._chat_calls) == 1
        assert backend._chat_calls[0]["temperature"] == 0.5
    
    def test_chat_with_tools(self):
        backend = MockLLMBackend()
        messages = [{"role": "user", "content": "Hello"}]
        tools = [{"type": "function", "function": {"name": "test"}}]
        resp = backend.chat(messages=messages, tools=tools)
        
        assert isinstance(resp, ChatResponse)
        assert backend._chat_calls[0]["tools"] == tools
    
    def test_embed(self):
        backend = MockLLMBackend()
        embedding = backend.embed("Hello world")
        
        assert embedding == [0.1, 0.2, 0.3]
        assert len(backend._embed_calls) == 1
        assert backend._embed_calls[0]["text"] == "Hello world"
    
    def test_health(self):
        backend = MockLLMBackend()
        assert backend.health() == True
    
    def test_info(self):
        backend = MockLLMBackend()
        info = backend.info()
        
        assert info.backend_type == "mock"
        assert info.model_name == "mock-model"
        assert info.n_ctx == 32768
        assert info.is_available == True
    
    def test_supports_tool_calling(self):
        backend = MockLLMBackend()
        assert backend.supports_tool_calling() == True
    
    def test_supports_streaming(self):
        backend = MockLLMBackend()
        assert backend.supports_streaming() == True
    
    def test_supports_embeddings(self):
        backend = MockLLMBackend()
        assert backend.supports_embeddings() == True


# ---------------------------------------------------------------------------
# Tests: Backend Factory
# ---------------------------------------------------------------------------

class TestBackendFactory:
    """Test create_backend factory function."""
    
    def test_create_llama_cpp_backend(self):
        """Test creating llama-cpp backend."""
        with patch.dict(os.environ, {"JARVIS_LLM_BACKEND": "llama-cpp"}):
            config = Config()
            backend = create_backend(config)
            assert backend.__class__.__name__ == "LlamaCppBackend"
    
    def test_create_prismml_backend(self):
        """Test creating prismml backend."""
        with patch.dict(os.environ, {"JARVIS_LLM_BACKEND": "prismml"}):
            config = Config()
            backend = create_backend(config)
            assert backend.__class__.__name__ == "PrismMLBackend"
    
    def test_create_bonsai_backend(self):
        """Test creating bonsai backend (uses PrismML)."""
        with patch.dict(os.environ, {"JARVIS_LLM_BACKEND": "bonsai"}):
            config = Config()
            backend = create_backend(config)
            assert backend.__class__.__name__ == "PrismMLBackend"
    
    def test_create_unknown_backend_raises(self):
        """Test that unknown backend raises ValueError."""
        with patch.dict(os.environ, {"JARVIS_LLM_BACKEND": "unknown"}):
            config = Config()
            with pytest.raises(ValueError, match="Unknown LLM backend"):
                create_backend(config)
    
    def test_create_with_override(self):
        """Test creating with explicit backend_type override."""
        config = Config()
        backend = create_backend(config, backend_type="llama-cpp")
        assert backend.__class__.__name__ == "LlamaCppBackend"
    
    def test_list_backends(self):
        """Test list_backends returns available backends."""
        backends = list_backends()
        assert "llama-cpp" in backends


# ---------------------------------------------------------------------------
# Tests: Config backend selection
# ---------------------------------------------------------------------------

class TestConfigBackend:
    """Test Config backend configuration."""
    
    def test_default_backend(self):
        """Test default backend is llama-cpp."""
        config = Config()
        assert config.llm_backend == "llama-cpp"
    
    def test_backend_from_env(self):
        """Test backend can be set via environment variable."""
        with patch.dict(os.environ, {"JARVIS_LLM_BACKEND": "prismml"}):
            config = Config()
            assert config.llm_backend == "prismml"
    
    def test_tool_calling_from_env(self):
        """Test tool calling can be set via environment variable."""
        with patch.dict(os.environ, {"JARVIS_LLM_TOOL_CALLING": "0"}):
            config = Config()
            assert config.llm_tool_calling == False


# ---------------------------------------------------------------------------
# Tests: LLMClient integration
# ---------------------------------------------------------------------------

class TestLLMClientIntegration:
    """Test LLMClient with mock backend."""
    
    def test_chat_with_mock_backend(self):
        """Test LLMClient.chat works with mock backend."""
        from jarvis.providers.llm import LLMClient
        
        mock_backend = MockLLMBackend()
        client = LLMClient(backend=mock_backend)
        
        messages = [{"role": "user", "content": "Hello"}]
        result = client.chat(messages=messages)
        
        assert result == "Mock response"
    
    def test_chat_with_tools_mock_backend(self):
        """Test LLMClient.chat_with_tools works with mock backend."""
        from jarvis.providers.llm import LLMClient
        
        mock_backend = MockLLMBackend()
        client = LLMClient(backend=mock_backend)
        
        messages = [{"role": "user", "content": "Hello"}]
        tools = [{"type": "function", "function": {"name": "test"}}]
        result = client.chat_with_tools(messages=messages, tools=tools)
        
        assert isinstance(result, ChatResponse)
        assert result.content == "Mock response"
    
    def test_embed_with_mock_backend(self):
        """Test LLMClient.embed works with mock backend."""
        from jarvis.providers.llm import LLMClient
        
        mock_backend = MockLLMBackend()
        client = LLMClient(backend=mock_backend)
        
        embedding = client.embed("Hello world")
        
        assert embedding == [0.1, 0.2, 0.3]
    
    def test_health_with_mock_backend(self):
        """Test LLMClient.is_available works with mock backend."""
        from jarvis.providers.llm import LLMClient
        
        mock_backend = MockLLMBackend()
        client = LLMClient(backend=mock_backend)
        
        assert client.is_available() == True
    
    def test_get_backend_info(self):
        """Test LLMClient.get_backend_info works with mock backend."""
        from jarvis.providers.llm import LLMClient
        
        mock_backend = MockLLMBackend()
        client = LLMClient(backend=mock_backend)
        
        info = client.get_backend_info()
        assert info.backend_type == "mock"
        assert info.model_name == "mock-model"
    
    def test_base_url_compat(self):
        """Test backward compatibility: base_url property."""
        from jarvis.providers.llm import LLMClient
        
        mock_backend = MockLLMBackend(base_url="http://test:8080")
        client = LLMClient(backend=mock_backend)
        
        assert client.base_url == "http://test:8080"
    
    def test_n_ctx_compat(self):
        """Test backward compatibility: n_ctx property."""
        from jarvis.providers.llm import LLMClient
        
        mock_backend = MockLLMBackend()
        client = LLMClient(backend=mock_backend)
        
        assert client.n_ctx == 32768


# ---------------------------------------------------------------------------
# Tests: ChatMessage
# ---------------------------------------------------------------------------

class TestChatMessage:
    """Test ChatMessage dataclass."""
    
    def test_to_dict(self):
        msg = ChatMessage(role="user", content="Hello")
        d = msg.to_dict()
        assert d == {"role": "user", "content": "Hello"}
    
    def test_to_dict_with_tool_calls(self):
        msg = ChatMessage(
            role="assistant",
            content="",
            tool_calls=[{"function": {"name": "test"}}],
        )
        d = msg.to_dict()
        assert "tool_calls" in d
        assert d["tool_calls"][0]["function"]["name"] == "test"
    
    def test_to_dict_tool_result(self):
        msg = ChatMessage(
            role="tool",
            content="result",
            tool_call_id="call_123",
            name="test_tool",
        )
        d = msg.to_dict()
        assert d["role"] == "tool"
        assert d["tool_call_id"] == "call_123"
        assert d["name"] == "test_tool"


# ---------------------------------------------------------------------------
# MISSÃO 2 (ASYNC P0) — streaming SSE real token a token
# ---------------------------------------------------------------------------


class TestSSEParsing:
    def test_extract_delta_content(self):
        from jarvis.providers.llm_llama_cpp import LlamaCppBackend
        line = 'data: {"choices":[{"delta":{"content":" Olá"},"finish_reason":null}]}'
        assert LlamaCppBackend._extract_delta(line) == " Olá"

    def test_extract_delta_done(self):
        from jarvis.providers.llm_llama_cpp import LlamaCppBackend
        assert LlamaCppBackend._extract_delta("data: [DONE]") is None
        assert LlamaCppBackend._extract_delta("") is None
        assert LlamaCppBackend._extract_delta(": heartbeat") is None

    def test_extract_delta_empty_content(self):
        from jarvis.providers.llm_llama_cpp import LlamaCppBackend
        line = 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}'
        assert LlamaCppBackend._extract_delta(line) is None

    def test_extract_delta_malformed(self):
        from jarvis.providers.llm_llama_cpp import LlamaCppBackend
        assert LlamaCppBackend._extract_delta("data: {not json") is None


class TestSyncStream:
    def _sse_response(self, tokens):
        """Mock de requests.Response com iter_lines SSE."""
        mock_resp = MagicMock()
        lines = []
        for t in tokens:
            lines.append(f'data: {json.dumps({"choices": [{"delta": {"content": t}}]})}')
        lines.append("data: [DONE]")
        mock_resp.iter_lines.return_value = iter(lines)
        mock_resp.raise_for_status.return_value = None
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)
        return mock_resp

    def test_chat_stream_yields_incremental(self):
        from jarvis.providers.llm_llama_cpp import LlamaCppBackend
        backend = LlamaCppBackend()
        mock_session = MagicMock()
        mock_session.post.return_value = self._sse_response([" Olá", " mundo"])
        backend._session = mock_session
        chunks = list(backend.chat_stream([{"role": "user", "content": "oi"}], max_tokens=8))
        assert chunks == [" Olá", " mundo"]
        # stream=True chegou ao requests (não buffer completo)
        _, kwargs = mock_session.post.call_args
        assert kwargs.get("stream") is True
        assert kwargs["json"]["stream"] is True

    def test_chat_stream_skips_done(self):
        from jarvis.providers.llm_llama_cpp import LlamaCppBackend
        backend = LlamaCppBackend()
        mock_session = MagicMock()
        mock_session.post.return_value = self._sse_response(["a"])
        backend._session = mock_session
        chunks = list(backend.chat_stream([{"role": "user", "content": "oi"}]))
        assert chunks == ["a"]
        assert "[DONE]" not in "".join(chunks)


# ---------------------------------------------------------------------------
# MISSÃO 4 (P1) — telemetria real + reconciliação (fim da heurística cega)
# ---------------------------------------------------------------------------


class TestSessionTelemetry:
    def test_record_and_aggregates(self):
        from jarvis.core.context_budget import SessionTelemetry
        tel = SessionTelemetry()
        tel.record(model="m", backend="llama-cpp", prompt_tokens=21,
                   completion_tokens=2, ttft_s=0.08, latency_s=0.25,
                   tps=60.7, cached_tokens=3)
        tel.record(model="m", backend="llama-cpp", prompt_tokens=10,
                   completion_tokens=5, ttft_s=0.10, latency_s=0.30, tps=55.0)
        assert tel.n_calls == 2
        assert tel.total_prompt == 31
        assert tel.total_completion == 7
        assert tel.total_tokens == 38
        assert abs(tel.avg_tps - 57.85) < 0.01
        assert abs(tel.avg_ttft - 0.09) < 0.001
        assert tel.calls[0].cached_tokens == 3

    def test_window_bar_against_server_numbers(self):
        from jarvis.core.context_budget import SessionTelemetry
        tel = SessionTelemetry(window_tokens=32768, window_used=22)
        assert abs(tel.window_pct - 0.067) < 0.01
        bar = tel.window_bar()
        assert "22/32768 tok" in bar
        rendered = tel.render()
        assert "janela:" in rendered and "throughput médio" in rendered

    def test_empty_session_renders(self):
        from jarvis.core.context_budget import SessionTelemetry
        tel = SessionTelemetry()
        assert tel.n_calls == 0
        assert tel.avg_tps == 0.0
        assert "chamadas: 0" in tel.render()


class TestBudgetReconciliation:
    def test_record_actual_feeds_totals(self):
        from jarvis.core.context_budget import ContextBudget
        b = ContextBudget(max_tokens=32768)
        b.record_actual(21, 2)
        assert b.total_tokens_processed == 23
        assert b.total_llm_calls == 1

    def test_calibration_converges_from_pairs(self):
        from jarvis.core import tokens as _tokens
        from jarvis.core.context_budget import ContextBudget
        _tokens._reset()
        b = ContextBudget(max_tokens=32768)
        assert b._calibration_ratio() == 1.0  # sem amostras: heurística pura
        text = "x" * 400  # heurística diria 100 tok
        b.record_actual_for_text(text, 25)  # real: 25 tok
        assert b._calibration_ratio() == 3.0  # clamped (4.0 → 3.0)
        # estimativa futura converge para o real (fonte única global)
        assert b.estimate_tokens("y" * 400) == 33  # 100 // 3.0
        _tokens._reset()

    def test_sync_from_slots_aligns_budget(self):
        from jarvis.core.context_budget import ContextBudget
        b = ContextBudget(max_tokens=32000)
        b.sync_from_slots(22, 32768)
        assert b.max_tokens == 32768
        assert b.used_tokens == 22
        assert abs(b.usage_percent - 22 / (32768 - 2000) * 100) < 0.01


class TestClientTelemetryWiring:
    def test_chat_records_real_usage(self):
        from unittest.mock import MagicMock
        from jarvis.providers.llm import LLMClient
        from jarvis.providers.llm_backend import ChatResponse
        backend = MagicMock()
        backend.chat.return_value = ChatResponse(
            content="ok",
            usage={"prompt_tokens": 21, "completion_tokens": 2,
                   "prompt_tokens_details": {"cached_tokens": 3}},
            timings={"predicted_per_second": 60.7},
            backend="llama-cpp", model_id="bonsai",
        )
        client = LLMClient(backend=backend)
        assert client.chat([{"role": "user", "content": "oi"}]) == "ok"
        tel = client.session_telemetry
        assert tel.total_prompt == 21
        assert tel.total_completion == 2
        assert abs(tel.avg_tps - 60.7) < 0.01
        assert tel.last.cached_tokens == 3

    def test_stream_records_real_ttft(self):
        import time
        from unittest.mock import MagicMock
        from jarvis.providers.llm import LLMClient
        backend = MagicMock()
        backend.chat_stream.return_value = iter(["Olá", " mundo"])
        client = LLMClient(backend=backend)
        chunks = list(client.chat_stream([{"role": "user", "content": "oi"}]))
        assert chunks == ["Olá", " mundo"]
        assert client.last_ttft_s >= 0.0
        assert client.session_telemetry.n_calls == 1


# ---------------------------------------------------------------------------
# Interface única de tokens (jarvis/core/tokens.py) — p/ jarvis + outros CLIs
# ---------------------------------------------------------------------------


class TestTokensInterface:
    def setup_method(self):
        from jarvis.core import tokens as _tokens
        _tokens._reset()

    def teardown_method(self):
        from jarvis.core import tokens as _tokens
        _tokens._reset()

    def test_heuristic_without_samples(self):
        from jarvis.core import tokens as _tokens
        assert _tokens.calibration_ratio() == 1.0
        assert _tokens.estimate("x" * 400) == 100

    def test_calibrate_converges(self):
        from jarvis.core import tokens as _tokens
        _tokens.calibrate("x" * 400, 25)
        assert _tokens.calibration_ratio() == 3.0
        assert _tokens.estimate("y" * 400) == 33

    def test_estimate_messages_with_tools(self):
        from jarvis.core import tokens as _tokens
        msgs = [
            {"role": "user", "content": "x" * 40},
            {"role": "assistant", "content": None,
             "tool_calls": [{"function": {"name": "read_file", "arguments": '{"a":1}'}}]},
        ]
        assert _tokens.estimate_messages(msgs) == 10 + 2 + 1 + 1

    def test_cli_text(self, capsys):
        from jarvis.core import tokens as _tokens
        assert _tokens.main(["--text", "x" * 40]) == 0
        assert '"tokens": 10' in capsys.readouterr().out

    def test_cli_stats(self, capsys):
        import json
        from jarvis.core import tokens as _tokens
        assert _tokens.main(["--stats"]) == 0
        assert json.loads(capsys.readouterr().out)["ratio"] == 1.0
