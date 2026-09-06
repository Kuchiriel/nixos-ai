"""llama.cpp backend adapter.

Implements the LLMBackend interface for llama-server's OpenAI-compatible API.
This is the current default backend.

Endpoints used:
- POST /v1/chat/completions — chat (+ SSE streaming via stream=true)
- POST /v1/embeddings — embeddings
- GET /health — health check
- GET /props — server properties (n_ctx, etc.)
- GET /models — model list
- GET /slots — slot status (optional)

MISSÃO 2 (ASYNC P0): streaming SSE real token a token.
- chat_stream(): gerador síncrono sobre requests stream=True (compat CLI).
- achat_stream(): gerador assíncrono sobre httpx.AsyncClient (event loop livre).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from .llm_backend import LLMBackend, ChatResponse, EmbeddingResponse, BackendInfo

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


class LlamaCppBackend(LLMBackend):
    """llama.cpp backend adapter.
    
    Connects to a running llama-server instance via its OpenAI-compatible API.
    Supports chat completions, embeddings, tool calling, and streaming.
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
            base_url: Base URL for llama-server (e.g., http://127.0.0.1:8080)
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
        """Send a chat completion request to llama-server."""
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
            timings=data.get("timings", {}),
            latency_seconds=elapsed,
            backend="llama-cpp",
            model_id=data.get("model", self._model),
        )

    def _stream_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Payload compartilhado entre chat_stream() e achat_stream()."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        return payload

    @staticmethod
    def _extract_delta(line: str) -> str | None:
        """Extrai o token incremental de uma linha SSE. None = ignorar."""
        if not line.startswith("data:"):
            return None
        data = line[5:].strip()
        if not data or data == "[DONE]":
            return None
        try:
            chunk = json.loads(data)
        except ValueError:
            return None
        choices = chunk.get("choices") or []
        if not choices:
            return None
        delta = choices[0].get("delta") or {}
        return delta.get("content") or None

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[str]:
        """Yields incrementais token a token via SSE real (requests stream=True).

        Compatível com consumidores síncronos (CLI). Não aguarda o buffer
        completo: o primeiro yield sai no TTFT do servidor.
        """
        payload = self._stream_payload(
            messages, temperature=temperature, max_tokens=max_tokens, tools=tools,
        )
        with self._session.post(
            f"{self._base_url}/v1/chat/completions",
            json=payload,
            timeout=(self._connect_timeout, self._read_timeout),
            stream=True,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                token = self._extract_delta(line)
                if token:
                    yield token

    async def achat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        """Yields incrementais sem bloquear o event loop (httpx.AsyncClient).

        Para o painel SvelteKit via SSE/WebSocket e futuros callers async.
        """
        payload = self._stream_payload(
            messages, temperature=temperature, max_tokens=max_tokens, tools=tools,
        )
        timeout = httpx.Timeout(self._read_timeout, connect=self._connect_timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/v1/chat/completions",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    token = self._extract_delta(line)
                    if token:
                        yield token

    def embed(self, text: str, model: str | None = None) -> list[float]:
        """Generate embedding via llama-server /v1/embeddings."""
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
        """Check if llama-server is responding."""
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
                backend_type="llama-cpp",
                model_name=settings.get("model", self._model),
                n_ctx=settings.get("n_ctx", 0),
                n_gpu_layers=settings.get("n_gpu_layers", 0),
                is_available=True,
                extra=settings,
            )
            return self._info_cache
        except Exception as e:
            logger.warning("Failed to get backend info: %s", e)
            return BackendInfo(
                backend_type="llama-cpp",
                model_name=self._model,
                is_available=False,
            )

    def get_slots_status(self) -> dict[str, Any]:
        """Get slot status from /slots endpoint (llama.cpp specific)."""
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
