"""Abstract interface for LLM backends.

This module defines the contract that any LLM backend must implement
to be usable by Jarvis. Currently supported:
- llama.cpp (via OpenAI-compatible API)
- PrismML (future)
- Bonsai Ternary (future)

The interface is minimal: chat, embed, health, info.
Tool calling is handled by the LLMClient that wraps this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    """A single message in a conversation."""
    role: str  # "system", "user", "assistant", "tool"
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role}
        if self.content:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class ChatResponse:
    """Response from a chat completion."""
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    latency_seconds: float = 0.0
    # Backend-specific metadata
    backend: str = ""
    model_id: str = ""


@dataclass
class EmbeddingResponse:
    """Response from an embedding request."""
    embedding: list[float] = field(default_factory=list)
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class BackendInfo:
    """Information about the running backend."""
    backend_type: str  # "llama-cpp", "prismml", "bonsai", etc.
    model_name: str = ""
    n_ctx: int = 0
    n_gpu_layers: int = 0
    is_available: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class LLMBackend(ABC):
    """Abstract interface for an LLM backend.
    
    Implementations must be stateless — all connection management
    happens inside the implementation. The LLMClient wraps this
    interface with circuit breaker, retries, and error classification.
    """

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Send a chat completion request.
        
        Args:
            messages: List of message dicts (role, content, etc.)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            tools: Tool definitions for function calling
            tool_choice: "auto", "none", or specific tool
            stream: Whether to stream the response
            extra: Backend-specific parameters
        
        Returns:
            ChatResponse with content and/or tool_calls
        """
        ...

    @abstractmethod
    def embed(self, text: str, model: str | None = None) -> list[float]:
        """Generate an embedding for the given text.
        
        Args:
            text: Text to embed
            model: Optional model override
        
        Returns:
            List of floats (embedding vector)
        """
        ...

    @abstractmethod
    def health(self, timeout: float = 3.0) -> bool:
        """Check if the backend is available and responding.
        
        Args:
            timeout: Connection timeout in seconds
        
        Returns:
            True if healthy
        """
        ...

    @abstractmethod
    def info(self) -> BackendInfo:
        """Get information about the running backend.
        
        Returns:
            BackendInfo with model name, context size, etc.
        """
        ...

    def supports_tool_calling(self) -> bool:
        """Whether this backend supports tool/function calling.
        
        Default: True. Override to False for backends that don't support it.
        """
        return True

    def supports_streaming(self) -> bool:
        """Whether this backend supports streaming responses.
        
        Default: True. Override to False for backends that don't support it.
        """
        return True

    def supports_embeddings(self) -> bool:
        """Whether this backend supports embeddings.
        
        Default: True. Override to False for backends without embedding support.
        """
        return True
