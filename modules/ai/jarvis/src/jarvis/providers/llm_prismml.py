"""PrismML/Bonsai backend adapter.

Implements the LLMBackend interface for PrismML's fork of llama-server.
PrismML adds support for ternary (1.58-bit) Bonsai models via Q2_0 format.

The server API is the same OpenAI-compatible API as llama.cpp.
The main difference is:
- Model format: Q2_0 (ternary) instead of standard GGUF quantizations
- Custom CUDA kernels for ternary inference
- Same endpoints: /v1/chat/completions, /v1/embeddings, /health, /props

Usage:
    JARVIS_LLM_BACKEND=prismml
    JARVIS_PRISMML_BIN=/path/to/prism-llama-server
    JARVIS_PRISMML_MODEL=/path/to/Bonsai-8B-Q2_0.gguf
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from .llm_backend import LLMBackend, ChatResponse, BackendInfo

logger = logging.getLogger(__name__)


def _build_session(
    total_retries: int = 3,
    backoff_factor: float = 0.5,
    backoff_jitter: float = 0.3,
) -> requests.Session:
    """Build an HTTP session with retry/backoff."""
    retry = Retry(
        total=total_retries,
        connect=total_retries,
        read=total_retries,
        status=total_retries,
        backoff_factor=backoff_factor,
        backoff_jitter=backoff_jitter,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class PrismMLBackend(LLMBackend):
    """PrismML/Bonsai backend adapter.
    
    Connects to a running PrismML llama-server instance via its OpenAI-compatible API.
    Supports Bonsai ternary models (Q2_0 format).
    
    The API is identical to llama.cpp since PrismML is a fork.
    The difference is in model format and inference kernels.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        embed_url: str | None = None,
        model: str = "default",
        connect_timeout: float = 5.0,
        read_timeout: float = 120.0,
        session: requests.Session | None = None,
    ):
        """
        Args:
            base_url: Base URL for PrismML llama-server
            embed_url: Separate URL for embedding server (if different port)
            model: Model name to send in requests
            connect_timeout: Connection timeout in seconds
            read_timeout: Read timeout in seconds
            session: Optional pre-built requests session (for testing)
        """
        self._base_url = base_url.rstrip("/")
        self._embed_url = (embed_url or base_url).rstrip("/")
        self._model = model
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._session = session or _build_session()
        self._info_cache: BackendInfo | None = None

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
        """Send a chat completion request to PrismML llama-server."""
        t0 = time.monotonic()
        
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice
        if extra:
            payload.update(extra)

        resp = self._session.post(
            f"{self._base_url}/v1/chat/completions",
            json=payload,
            timeout=(self._connect_timeout, self._read_timeout),
            stream=stream,
        )
        elapsed = time.monotonic() - t0
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        message = choice["message"]

        return ChatResponse(
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls", []),
            finish_reason=choice.get("finish_reason", ""),
            usage=data.get("usage", {}),
            latency_seconds=elapsed,
            backend="prismml",
            model_id=data.get("model", self._model),
        )

    def embed(self, text: str, model: str | None = None) -> list[float]:
        """Generate embedding via PrismML llama-server /v1/embeddings."""
        payload: dict[str, Any] = {
            "model": model or self._model,
            "input": text,
        }
        resp = self._session.post(
            f"{self._embed_url}/v1/embeddings",
            json=payload,
            timeout=(self._connect_timeout, self._read_timeout),
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]

    def health(self, timeout: float = 3.0) -> bool:
        """Check if PrismML llama-server is responding."""
        try:
            resp = self._session.get(
                f"{self._base_url}/health",
                timeout=(timeout, timeout),
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def info(self) -> BackendInfo:
        """Get server info from /props endpoint."""
        if self._info_cache is not None:
            return self._info_cache
        
        try:
            resp = self._session.get(
                f"{self._base_url}/props",
                timeout=(self._connect_timeout, 5),
            )
            resp.raise_for_status()
            data = resp.json()
            settings = data.get("default_generation_settings", {})
            
            self._info_cache = BackendInfo(
                backend_type="prismml",
                model_name=settings.get("model", self._model),
                n_ctx=settings.get("n_ctx", 0),
                n_gpu_layers=settings.get("n_gpu_layers", 0),
                is_available=True,
                extra=settings,
            )
            return self._info_cache
        except Exception as e:
            logger.warning("Failed to get PrismML backend info: %s", e)
            return BackendInfo(
                backend_type="prismml",
                model_name=self._model,
                is_available=False,
            )

    def get_slots_status(self) -> dict[str, Any]:
        """Get slot status from /slots endpoint."""
        try:
            resp = self._session.get(
                f"{self._base_url}/slots",
                timeout=(self._connect_timeout, 3),
            )
            if resp.status_code != 200:
                return {}
            slots = resp.json()
            if not isinstance(slots, list):
                return {}
            idle = sum(1 for s in slots if not s.get("is_processing"))
            busy = sum(1 for s in slots if s.get("is_processing"))
            total_ctx = sum(s.get("n_ctx", 0) for s in slots)
            used_ctx = sum(s.get("n_prompt_tokens", 0) for s in slots)
            return {
                "slots_total": len(slots),
                "slots_idle": idle,
                "slots_busy": busy,
                "ctx_total": total_ctx,
                "ctx_used": used_ctx,
                "ctx_pct": round(used_ctx / total_ctx * 100, 1) if total_ctx > 0 else 0,
            }
        except (requests.RequestException, ValueError):
            return {}

    def is_busy(self, ctx_threshold: float = 80.0) -> bool:
        """Check if server is under heavy load."""
        status = self.get_slots_status()
        if not status:
            return True
        if status["slots_busy"] >= status["slots_total"]:
            return True
        if status["ctx_pct"] > ctx_threshold:
            return True
        return False

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()

    @staticmethod
    def find_prism_binary() -> str | None:
        """Find PrismML llama-server binary.
        
        Checks:
        1. JARVIS_PRISMML_BIN env var
        2. Common paths in ~/projects/prism-bin/
        3. PATH
        """
        # Check env var
        env_bin = os.environ.get("JARVIS_PRISMML_BIN")
        if env_bin and os.path.exists(env_bin):
            return env_bin
        
        # Check common paths
        home = os.path.expanduser("~")
        prism_dirs = [
            os.path.join(home, "projects/prism-bin/llama-prism-b10660-e311ed3"),
            os.path.join(home, "projects/prism-llama.cpp/build/bin"),
        ]
        for d in prism_dirs:
            server = os.path.join(d, "llama-server")
            if os.path.exists(server):
                return server
        
        return None
