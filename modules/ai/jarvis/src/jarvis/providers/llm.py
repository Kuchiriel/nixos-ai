"""Provider de LLM — cliente OpenAI-compatível para o llama.cpp (llama-server).

O core do JARVIS conversa com esta interface; trocar de backend
(ollama, outro servidor) não afeta o core.

Projetado para uso pesado de coding local: falhas do servidor (processo
morto, OOM, fila de slots cheia, context overflow) precisam ser
diferenciáveis e nunca travar o chamador silenciosamente.

Architecture:
    LLMClient (this module)
        ↓
    LLMBackend (abstract interface)
        ├── LlamaCppBackend (default)
        ├── PrismMLBackend (future)
        └── BonsaiBackend (future)
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .llm_backend import LLMBackend, ChatResponse, BackendInfo
from .llm_factory import create_backend
from jarvis.core.config import Config

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Taxonomia de erros — o chamador decide o que fazer por TIPO, não por
# parsing de string de mensagem.
# --------------------------------------------------------------------------

class LLMError(RuntimeError):
    """Erro genérico — fallback para casos não classificados."""

class LLMConnectionError(LLMError):
    """Servidor inalcançável (processo morto, porta fechada, DNS)."""

class LLMTimeoutError(LLMError):
    """Requisição excedeu o timeout (connect ou read)."""

class LLMServerError(LLMError):
    """Servidor respondeu, mas com erro (5xx após esgotar retries)."""

class LLMContextOverflowError(LLMError):
    """Prompt excede o ctx configurado no servidor.

    NUNCA deve ser retentado — é um erro estrutural do request, não
    transitório. O chamador deve truncar/resumir e tentar de novo por
    conta própria, se fizer sentido.
    """

class LLMStreamError(LLMError):
    """Falha no meio de um stream SSE (chunk malformado ou conexão caiu)."""

class CircuitOpenError(LLMError):
    """Circuit breaker aberto — desistiu de tentar sem nem bater na rede.

    Sinal de que o servidor está consistentemente fora do ar; falha
    instantânea em vez de esperar o timeout completo de novo.
    """


# --------------------------------------------------------------------------
# Circuit breaker — thread-safe, sem dependência externa.
# --------------------------------------------------------------------------

class _CircuitState(Enum):
    CLOSED = "closed"  # operação normal
    OPEN = "open"  # desistiu, falha instantânea
    HALF_OPEN = "half_open"  # testando se o serviço voltou

@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 4  # falhas seguidas até abrir
    recovery_timeout: float = 15.0  # segundos em OPEN antes de testar de novo
    half_open_max_calls: int = 1  # chamadas de teste permitidas em HALF_OPEN

class CircuitBreaker:
    """Circuit breaker simples (Nygard/Release It), thread-safe.

    before_call() levanta CircuitOpenError se o circuito estiver aberto,
    sem tocar a rede.
    """

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._cfg = config or CircuitBreakerConfig()
        self._lock = threading.Lock()
        self._state = _CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float = 0.0
        self._half_open_calls_in_flight = 0

    def _maybe_transition_to_half_open(self) -> None:
        if self._state is _CircuitState.OPEN and (time.monotonic() - self._opened_at) >= self._cfg.recovery_timeout:
            self._state = _CircuitState.HALF_OPEN
            self._half_open_calls_in_flight = 0
            logger.info("circuit breaker: OPEN -> HALF_OPEN (testando recuperação)")

    def before_call(self) -> None:
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state is _CircuitState.OPEN:
                raise CircuitOpenError(
                    f"circuito aberto há {time.monotonic() - self._opened_at:.1f}s "
                    f"— servidor considerado indisponível, aguardando recovery_timeout"
                )
            if self._state is _CircuitState.HALF_OPEN:
                if self._half_open_calls_in_flight >= self._cfg.half_open_max_calls:
                    raise CircuitOpenError("circuito em teste (HALF_OPEN) — aguardando resultado da sondagem")
                self._half_open_calls_in_flight += 1

    def record_success(self) -> None:
        with self._lock:
            if self._state is not _CircuitState.CLOSED:
                logger.info("circuit breaker: %s -> CLOSED (recuperado)", self._state.value)
            self._state = _CircuitState.CLOSED
            self._consecutive_failures = 0
            self._half_open_calls_in_flight = 0

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._state is _CircuitState.HALF_OPEN:
                # sondagem falhou — volta a esperar o recovery_timeout inteiro
                self._state = _CircuitState.OPEN
                self._opened_at = time.monotonic()
                logger.warning("circuit breaker: HALF_OPEN -> OPEN (sondagem falhou)")
            elif self._consecutive_failures >= self._cfg.failure_threshold:
                self._state = _CircuitState.OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "circuit breaker: CLOSED -> OPEN (%d falhas consecutivas)", self._consecutive_failures
                )

    @property
    def state(self) -> str:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state.value


def _classify_error_response(status_code: int, body_text: str) -> type[LLMError]:
    """Mapeia status + corpo do erro do llama-server pra exceção específica."""
    lowered = body_text.lower()
    if status_code == 400 and ("context" in lowered and ("exceed" in lowered or "size" in lowered)):
        return LLMContextOverflowError
    if status_code >= 500:
        return LLMServerError
    return LLMError


class LLMClient:
    """Cliente para LLM com suporte a múltiplos backends.

    Suporta uso como context manager para garantir que a Session (e o
    connection pool subjacente) seja fechada corretamente:

        with LLMClient() as client:
            client.chat(messages)
    """

    _EMBED_CHARS_PER_TOKEN_ESTIMATE = 3.2
    _EMBED_MAX_TOKENS = 480  # margem de segurança abaixo do ctx=512
    _HEALTH_CACHE_TTL = 2.0  # segundos — evita martelar /models em loops de agente

    def __init__(self, config: Config | None = None, *, session=None, backend: LLMBackend | None = None) -> None:
        """
        Args:
            config: Jarvis config (uses defaults if None)
            session: Injection for testing (requests.Session mock)
            backend: Pre-configured backend instance (overrides config-based creation)
        """
        self._cfg = config or Config()
        
        # Create or use provided backend
        if backend is not None:
            self._backend = backend
        else:
            self._backend = create_backend(
                self._cfg,
                session=session,
            )

        self._breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=getattr(self._cfg, "llm_circuit_failure_threshold", 4),
                recovery_timeout=getattr(self._cfg, "llm_circuit_recovery_timeout", 15.0),
            )
        )

        self._model_lock = threading.Lock()
        self._resolved_model_id: str | None = None

        self._health_lock = threading.Lock()
        self._health_cache: tuple[float, bool] | None = None  # (timestamp, resultado)

    # --- context manager ---

    def __enter__(self) -> "LLMClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if hasattr(self._backend, "close"):
            self._backend.close()

    # --- health ---

    def is_available(self, timeout: float | None = None, *, use_cache: bool = True) -> bool:
        """Health check com cache curto (evita martelar /models em loops)."""
        if use_cache and self._health_cache is not None:
            ts, result = self._health_cache
            if time.monotonic() - ts < self._HEALTH_CACHE_TTL:
                return result

        try:
            result = self._backend.health(timeout=timeout or 3.0)
        except Exception as exc:
            logger.debug("health check falhou: %s", exc)
            result = False

        with self._health_lock:
            self._health_cache = (time.monotonic(), result)
        return result

    # --- slots / load detection (llama.cpp specific) ---

    def get_slots_status(self) -> dict[str, Any]:
        """Consulta status dos slots (se o backend suportar)."""
        if hasattr(self._backend, "get_slots_status"):
            return self._backend.get_slots_status()
        return {}

    def is_busy(self, *, ctx_threshold: float = 80.0) -> bool:
        """True se o servidor está sob carga alta."""
        if self._breaker.state == "open":
            return True
        if hasattr(self._backend, "is_busy"):
            return self._backend.is_busy(ctx_threshold=ctx_threshold)
        return False

    # --- backend info ---

    def get_backend_info(self) -> BackendInfo:
        """Get information about the running backend."""
        try:
            return self._backend.info()
        except Exception as e:
            logger.warning("Failed to get backend info: %s", e)
            return BackendInfo(backend_type="unknown", is_available=False)

    # --- model resolution ---

    def _resolve_model_id(self, *, force_refresh: bool = False) -> str:
        """Detecta o model_id real do servidor."""
        with self._model_lock:
            if self._resolved_model_id is not None and not force_refresh:
                return self._resolved_model_id
        try:
            info = self._backend.info()
            if info.model_name:
                with self._model_lock:
                    self._resolved_model_id = info.model_name
                return info.model_name
        except Exception as exc:
            logger.warning("falha ao detectar model_id, usando fallback '%s': %s", self._cfg.llm_model, exc)
        return self._cfg.llm_model

    # --- chat (síncrono) ---

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int | None = None) -> str:
        """Chat completion — retorna conteúdo como string."""
        request_id = uuid.uuid4().hex[:12]
        
        self._breaker.before_call()
        try:
            response = self._backend.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            self._breaker.record_success()
            return response.content
        except Exception as exc:
            self._breaker.record_failure()
            if "context" in str(exc).lower() and ("exceed" in str(exc).lower() or "overflow" in str(exc).lower()):
                raise LLMContextOverflowError(f"[{request_id}] context overflow: {exc}") from exc
            if "timeout" in str(exc).lower():
                raise LLMTimeoutError(f"[{request_id}] timeout: {exc}") from exc
            if "connection" in str(exc).lower():
                raise LLMConnectionError(f"[{request_id}] connection failed: {exc}") from exc
            raise LLMError(f"[{request_id}] {exc}") from exc

    # --- chat com tool calling (retorna ChatResponse) ---

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Chat completion com tool calling — retorna ChatResponse completo."""
        request_id = uuid.uuid4().hex[:12]
        
        self._breaker.before_call()
        try:
            response = self._backend.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                extra=extra,
            )
            self._breaker.record_success()
            return response
        except Exception as exc:
            self._breaker.record_failure()
            if "context" in str(exc).lower() and ("exceed" in str(exc).lower() or "overflow" in str(exc).lower()):
                raise LLMContextOverflowError(f"[{request_id}] context overflow: {exc}") from exc
            if "timeout" in str(exc).lower():
                raise LLMTimeoutError(f"[{request_id}] timeout: {exc}") from exc
            if "connection" in str(exc).lower():
                raise LLMConnectionError(f"[{request_id}] connection failed: {exc}") from exc
            raise LLMError(f"[{request_id}] {exc}") from exc

    # --- chat (streaming) ---

    def chat_stream(
        self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int | None = None
    ) -> Iterator[str]:
        """Gera tokens conforme chegam via SSE (stream: true)."""
        # For now, use non-streaming fallback
        # TODO: implement streaming in LlamaCppBackend
        content = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        yield content

    # --- embeddings ---

    def _truncate_for_embedding(self, text: str) -> str:
        """Trunca por estimativa de tokens (não por char cru)."""
        max_chars = int(self._EMBED_MAX_TOKENS * self._EMBED_CHARS_PER_TOKEN_ESTIMATE)
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars].rsplit(" ", 1)[0]
        logger.warning(
            "texto truncado para embedding: %d -> %d chars (~%d tokens estimados)",
            len(text), len(truncated), self._EMBED_MAX_TOKENS,
        )
        return truncated

    def embed(self, text: str, model: str | None = None) -> list[float]:
        """Embedding via backend."""
        text = self._truncate_for_embedding(text)
        try:
            return self._backend.embed(text, model=model)
        except Exception as exc:
            raise LLMError(f"embedding failed: {exc}") from exc

    @property
    def base_url(self) -> str:
        """Backward compat: expose base_url."""
        if hasattr(self._backend, "_base_url"):
            return self._backend._base_url
        return ""

    @property
    def n_ctx(self) -> int:
        """Backward compat: expose context size."""
        info = self.get_backend_info()
        return info.n_ctx if info else 32768
