"""Provider de LLM — cliente OpenAI-compatível para o llama.cpp (llama-server).

O core do JARVIS conversa com esta interface; trocar de backend
(ollama, outro servidor) não afeta o core.

Projetado para uso pesado de coding local: falhas do servidor (processo
morto, OOM, fila de slots cheia, context overflow) precisam ser
diferenciáveis e nunca travar o chamador silenciosamente.
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

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

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


def _build_session(*, total_retries: int, backoff_factor: float, backoff_jitter: float) -> requests.Session:
    """Session com retry/backoff automático em erros transitórios.

    Retry apenas em falhas de conexão e status transitórios (429/5xx).
    NUNCA em 4xx de request malformado (inclui context overflow, ver
    _classify_error_response) — retry aí só mascara e desperdiça o
    budget contra um erro que não é transitório.

    backoff_jitter é explícito (default do urllib3 é 0 — sem jitter),
    importante pra evitar que retries de várias chamadas concorrentes
    (ex. vários tool calls de um agente) caiam sincronizados no mesmo
    instante e sobrecarreguem o slot que acabou de liberar.
    """
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


def _classify_error_response(status_code: int, body_text: str) -> type[LLMError]:
    """Mapeia status + corpo do erro do llama-server pra exceção específica.

    O llama-server retorna context overflow como HTTP 400 com
    `"type": "exceed_context_size_error"` (ou mensagem equivalente) no
    corpo — precisa ser distinguido de um 400 genérico de payload malformado
    porque o tratamento correto é diferente (truncar prompt, não retry).
    """
    lowered = body_text.lower()
    if status_code == 400 and ("context" in lowered and ("exceed" in lowered or "size" in lowered)):
        return LLMContextOverflowError
    if status_code >= 500:
        return LLMServerError
    return LLMError


class LLMClient:
    """Cliente para a API /v1/chat/completions do llama-server.

    Suporta uso como context manager para garantir que a Session (e o
    connection pool subjacente) seja fechada corretamente:

        with LLMClient() as client:
            client.chat(messages)
    """

    _EMBED_CHARS_PER_TOKEN_ESTIMATE = 3.2
    _EMBED_MAX_TOKENS = 480  # margem de segurança abaixo do ctx=512
    _HEALTH_CACHE_TTL = 2.0  # segundos — evita martelar /models em loops de agente

    def __init__(self, config: Config | None = None) -> None:
        self._cfg = config or Config()
        self._base = self._cfg.llm_base_url.rstrip("/")

        total_retries = getattr(self._cfg, "llm_max_retries", 3)
        backoff_factor = getattr(self._cfg, "llm_backoff_factor", 0.5)
        backoff_jitter = getattr(self._cfg, "llm_backoff_jitter", 0.3)
        self._session = _build_session(
            total_retries=total_retries, backoff_factor=backoff_factor, backoff_jitter=backoff_jitter
        )

        # timeouts separados: connect precisa falhar rápido (processo morto
        # não vale a pena esperar), read precisa ser generoso (gerações de
        # código longas + possível espera na fila de slots do servidor).
        self._connect_timeout = getattr(self._cfg, "llm_connect_timeout", 5.0)
        self._read_timeout = getattr(self._cfg, "llm_read_timeout", self._cfg.llm_timeout)

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
        self._session.close()

    # --- health ---

    def is_available(self, timeout: float | None = None, *, use_cache: bool = True) -> bool:
        """Health check com cache curto (evita martelar /models em loops).

        use_cache=False força um check real — útil antes de uma operação
        crítica onde um resultado de 2s atrás não é confiável o bastante.
        """
        if use_cache and self._health_cache is not None:
            ts, result = self._health_cache
            if time.monotonic() - ts < self._HEALTH_CACHE_TTL:
                return result

        connect_t = timeout if timeout is not None else self._connect_timeout
        try:
            resp = self._session.get(f"{self._base}/models", timeout=(connect_t, connect_t))
            result = resp.status_code == 200
        except requests.RequestException as exc:
            logger.debug("health check falhou: %s", exc)
            result = False

        with self._health_lock:
            self._health_cache = (time.monotonic(), result)
        return result

    def models(self) -> list[dict[str, Any]]:
        resp = self._session.get(f"{self._base}/models", timeout=(self._connect_timeout, self._read_timeout))
        resp.raise_for_status()
        return resp.json().get("data", [])

    def _resolve_model_id(self, *, force_refresh: bool = False) -> str:
        """Detecta o model_id real do servidor (o default 'default' não existe
        no llama.cpp — o nome vem do arquivo GGUF, ex: Qwen3-4B-Q4_K_M).

        Cacheado (thread-safe) após a primeira resolução — o modelo carregado
        não muda em runtime a menos que o processo seja reiniciado, então
        refazer esse GET a cada chat() é round-trip desperdiçada.
        """
        with self._model_lock:
            if self._resolved_model_id is not None and not force_refresh:
                return self._resolved_model_id
        try:
            resp = self._session.get(f"{self._base}/models", timeout=(self._connect_timeout, 3))
            resp.raise_for_status()
            data = resp.json()
            if data.get("data"):
                resolved = data["data"][0].get("id", self._cfg.llm_model)
                with self._model_lock:
                    self._resolved_model_id = resolved
                return resolved
        except Exception as exc:
            logger.warning(
                "falha ao detectar model_id via /models, usando fallback '%s': %s",
                self._cfg.llm_model,
                exc,
            )
        return self._cfg.llm_model

    def _build_payload(
        self, messages: list[dict[str, str]], *, temperature: float, max_tokens: int | None, stream: bool
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._resolve_model_id(),
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if self._cfg.llm_disable_thinking:
            # Qwen3/Qwen3.6: desliga o modo de raciocínio (chat template suporta
            # enable_thinking) — tool calling direto e rápido em CPU. Aceito pelo
            # llama-server (validado ao vivo); ignorado por templates que não o
            # conhecem (jinja trata variável ausente como falsy).
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        return payload

    def _post(self, url: str, payload: dict[str, Any], *, request_id: str, stream: bool = False) -> requests.Response:
        """POST com circuit breaker + classificação de erro centralizada."""
        self._breaker.before_call()
        try:
            resp = self._session.post(
                url,
                json=payload,
                timeout=(self._connect_timeout, self._read_timeout),
                stream=stream,
                headers={"X-Request-Id": request_id},
            )
        except requests.exceptions.ConnectTimeout as exc:
            self._breaker.record_failure()
            raise LLMTimeoutError(f"[{request_id}] connect timeout ({self._connect_timeout}s) em {url}") from exc
        except requests.exceptions.ReadTimeout as exc:
            self._breaker.record_failure()
            raise LLMTimeoutError(f"[{request_id}] read timeout ({self._read_timeout}s) em {url}") from exc
        except requests.exceptions.ConnectionError as exc:
            self._breaker.record_failure()
            raise LLMConnectionError(f"[{request_id}] servidor inalcançável em {self._base}: {exc}") from exc
        except requests.RequestException as exc:
            self._breaker.record_failure()
            raise LLMError(f"[{request_id}] falha de request: {exc}") from exc

        if resp.status_code != 200:
            body_preview = resp.text[:300]
            error_cls = _classify_error_response(resp.status_code, resp.text)
            # context overflow (400) não é falha do servidor — não conta pro breaker
            if error_cls is not LLMContextOverflowError:
                self._breaker.record_failure()
            raise error_cls(f"[{request_id}] llama-server respondeu HTTP {resp.status_code}: {body_preview}")

        self._breaker.record_success()
        return resp

    # --- chat (síncrono) ---

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int | None = None) -> str:
        request_id = uuid.uuid4().hex[:12]
        payload = self._build_payload(messages, temperature=temperature, max_tokens=max_tokens, stream=False)
        resp = self._post(f"{self._base}/chat/completions", payload, request_id=request_id)
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"[{request_id}] resposta sem conteúdo esperado: {data}") from exc

    # --- chat (streaming) ---

    def chat_stream(
        self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int | None = None
    ) -> Iterator[str]:
        """Gera tokens conforme chegam via SSE (stream: true).

        Uso:
            for delta in client.chat_stream(messages):
                print(delta, end="", flush=True)

        Nota: uma vez que o stream começou a chegar, uma queda no meio NÃO
        é reexecutada automaticamente (evitaria duplicar tokens já emitidos
        ao chamador) — propaga LLMStreamError nesse caso.
        """
        request_id = uuid.uuid4().hex[:12]
        payload = self._build_payload(messages, temperature=temperature, max_tokens=max_tokens, stream=True)
        resp = self._post(f"{self._base}/chat/completions", payload, request_id=request_id, stream=True)

        try:
            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line or not raw_line.startswith("data:"):
                    continue
                chunk_str = raw_line[len("data:"):].strip()
                if chunk_str == "[DONE]":
                    return
                try:
                    chunk = json.loads(chunk_str)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                except (json.JSONDecodeError, KeyError, IndexError) as exc:
                    raise LLMStreamError(f"[{request_id}] chunk malformado: {chunk_str[:200]}") from exc
                if delta:
                    yield delta
        except requests.exceptions.ChunkedEncodingError as exc:
            raise LLMStreamError(f"[{request_id}] conexão caiu no meio do stream: {exc}") from exc

    # --- embeddings ---

    def _truncate_for_embedding(self, text: str) -> str:
        """Trunca por estimativa de tokens (não por char cru), em fronteira
        de palavra, logando quando corta — hoje isso é silencioso.
        """
        max_chars = int(self._EMBED_MAX_TOKENS * self._EMBED_CHARS_PER_TOKEN_ESTIMATE)
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars].rsplit(" ", 1)[0]
        logger.warning(
            "texto truncado para embedding: %d -> %d chars (~%d tokens estimados)",
            len(text),
            len(truncated),
            self._EMBED_MAX_TOKENS,
        )
        return truncated

    def embed(self, text: str, model: str | None = None) -> list[float]:
        """Embedding via /v1/embeddings — servidor dedicado (--embeddings).

        Usa `embed_base_url` (porta 8081 por padrão), separado do chat.
        """
        request_id = uuid.uuid4().hex[:12]
        base = self._cfg.embed_base_url.rstrip("/")
        text = self._truncate_for_embedding(text)
        payload: dict[str, Any] = {"model": model or self._cfg.embed_model, "input": text}
        resp = self._post(f"{base}/embeddings", payload, request_id=request_id)
        data = resp.json()
        try:
            return data["data"][0]["embedding"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"[{request_id}] embedding sem dado esperado: {data}") from exc
