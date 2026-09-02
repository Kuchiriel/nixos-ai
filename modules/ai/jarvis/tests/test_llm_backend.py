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
