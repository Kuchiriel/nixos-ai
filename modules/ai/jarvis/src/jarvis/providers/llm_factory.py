"""Backend factory — creates the appropriate LLM backend from config.

Usage:
    from jarvis.providers.llm_factory import create_backend
    from jarvis.core.config import Config
    
    config = Config()
    backend = create_backend(config)
    response = backend.chat(messages=[...])
"""

from __future__ import annotations

import logging
from typing import Any

from .llm_backend import LLMBackend
from ..core.config import Config

logger = logging.getLogger(__name__)


def create_backend(
    config: Config | None = None,
    *,
    backend_type: str | None = None,
    base_url: str | None = None,
    embed_url: str | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> LLMBackend:
    """Create an LLM backend based on configuration.
    
    Args:
        config: Jarvis config (uses defaults if None)
        backend_type: Override backend type ("llama-cpp", "prismml", "bonsai")
        base_url: Override base URL
        embed_url: Override embedding URL
        model: Override model name
        **kwargs: Additional arguments passed to the backend constructor
    
    Returns:
        An LLMBackend implementation
    
    Raises:
        ValueError: If backend_type is not supported
    """
    config = config or Config()
    backend = backend_type or config.llm_backend
    
    if backend == "llama-cpp":
        from .llm_llama_cpp import LlamaCppBackend
        return LlamaCppBackend(
            base_url=base_url or config.llm_base_url.replace("/v1", ""),
            embed_url=embed_url or config.embed_base_url.replace("/v1", ""),
            model=model or config.llm_model,
            connect_timeout=kwargs.get("connect_timeout", 5.0),
            read_timeout=kwargs.get("read_timeout", float(config.llm_timeout)),
            session=kwargs.get("session"),
        )
    
    elif backend == "prismml":
        # Future: PrismML backend
        raise NotImplementedError(
            "PrismML backend not yet implemented. "
            "Set JARVIS_LLM_BACKEND=llama-cpp or contribute an adapter."
        )
    
    elif backend == "bonsai":
        # Future: Bonsai Ternary backend
        raise NotImplementedError(
            "Bonsai backend not yet implemented. "
            "Set JARVIS_LLM_BACKEND=llama-cpp or contribute an adapter."
        )
    
    else:
        raise ValueError(
            f"Unknown LLM backend: {backend!r}. "
            f"Supported: llama-cpp, prismml, bonsai. "
            f"Set JARVIS_LLM_BACKEND environment variable."
        )


def list_backends() -> list[str]:
    """List all available backend types."""
    backends = ["llama-cpp"]
    
    # Check for optional backends
    try:
        import prismml  # noqa: F401
        backends.append("prismml")
    except ImportError:
        pass
    
    try:
        import bonsai  # noqa: F401
        backends.append("bonsai")
    except ImportError:
        pass
    
    return backends
