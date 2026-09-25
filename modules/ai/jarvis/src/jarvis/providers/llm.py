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
from collections.abc import AsyncIterator, Iterator
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

    def release(self) -> None:
        """Libera um slot de sondagem sem contar sucesso nem falha.

        Usado quando o consumidor abandona um stream (GeneratorExit): sem
        isso, _half_open_calls_in_flight ficava preso em 1 e o circuito
        nunca mais saía de HALF_OPEN (liveness bug — recovery impossível
        sem restart do processo).
        """
        with self._lock:
            self._half_open_calls_in_flight = max(0, self._half_open_calls_in_flight - 1)

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


def _review_prompt(focus: str | None) -> str:
    """Framing polimórfico do loop de revisão (dono 19/09: thinking como
    revisão externalizada; caderno > cadeia volátil).
    - factual (default): fatos com citação verbatim + números recalculados.
    - syntax: quoting/sintaxe shell+JSON — reexamina cada aspa/echo e, se
      quebrado, reemite a tool call corrigida (mesmo path); a forma robusta
      é python3 -c com json.dumps, nunca echo-JSON aninhado.
    """
    if focus == "syntax":
        return (
            "REVISE sua resposta acima focando em SINTAXE shell+JSON. "
            "Releia cada linha com echo/aspas da sua chamada: toda aspa "
            "aberta precisa fechar na mesma construção; JSON exige aspas "
            "DUPLAS nas chaves; `grep ... | jq` nunca (jq lê arquivos JSON, "
            "não texto). Se quebrado, responda com a tool call CORRIGIDA "
            "(MESMO path, lógica preservada) — forma robusta: python3 -c "
            "com json.dumps p/ qualquer saída JSON. Se está correto, "
            "responda MANTER.")
    return (
        "REVISE sua resposta acima. Responda: MANTER, ou NOVA "
        "RESPOSTA corrigida. Exija de si: (1) toda afirmação "
        "factual precisa de CITAÇÃO EXATA copiada do contexto "
        "(proibido paráfrase/reticências); (2) todo NÚMERO "
        "calculado precisa ser RECALCULADO passo a passo a "
        "partir dos dados observados — se divergir, corrija o "
        "número. Sem citação válida: MANTER.")


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

        # "default" é alias resolvido pelo registry (model.nix `routing`):
        # com o router ativo, o campo `model` do payload precisa ser um
        # preset real (o servidor single-model antigo ignorava o valor).
        # Best-effort: sem registry, mantém "default" (compat single-model).
        if self._cfg.llm_model in ("", "default"):
            try:
                from dataclasses import replace as _replace

                from jarvis.core.model_registry import ModelRegistry
                _resolved = ModelRegistry.load().default
                logger.info("llm_model 'default' → registry default %r", _resolved)
                self._cfg = _replace(self._cfg, llm_model=_resolved)
            except Exception:
                pass
        
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
        # Breaker separado para embeddings: o servidor de embed (8081) é
        # processo independente do chat (8080) — um chat morto não pode
        # vetar RAG, e vice-versa (domínios de falha distintos).
        self._embed_breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=getattr(self._cfg, "llm_circuit_failure_threshold", 4),
                recovery_timeout=getattr(self._cfg, "llm_circuit_recovery_timeout", 15.0),
            )
        )

        self._model_lock = threading.Lock()
        self._resolved_model_id: str | None = None

        self._health_lock = threading.Lock()
        self._health_cache: tuple[float, bool] | None = None  # (timestamp, resultado)

        # MISSÃO 4: telemetria real da última chamada + sessão acumulada
        self._telemetry_lock = threading.Lock()
        self._last_usage: dict[str, Any] = {}
        self._last_timings: dict[str, Any] = {}
        self._last_ttft_s: float = 0.0
        self._last_model: str = ""
        self._last_backend: str = ""
        from jarvis.core.context_budget import SessionTelemetry
        self._telemetry = SessionTelemetry()

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

    def _record_telemetry(
        self,
        response: Any,
        *,
        ttft_s: float = 0.0,
        latency_s: float = 0.0,
    ) -> None:
        """Alimenta telemetria com números REAIS (usage/timings) — MISSÃO 4."""
        usage = getattr(response, "usage", {}) or {}
        timings = getattr(response, "timings", {}) or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        cached = 0
        details = usage.get("prompt_tokens_details") or {}
        if isinstance(details, dict):
            cached = int(details.get("cached_tokens", 0) or 0)
        tps = float(timings.get("predicted_per_second", 0) or 0)
        backend = getattr(response, "backend", "") or ""
        model = getattr(response, "model_id", "") or ""
        with self._telemetry_lock:
            self._last_usage = dict(usage)
            self._last_timings = dict(timings)
            self._last_ttft_s = ttft_s
            self._last_model = model
            self._last_backend = backend
            self._telemetry.record(
                model=model, backend=backend,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                ttft_s=ttft_s, latency_s=latency_s, tps=tps,
                cached_tokens=cached,
            )

    @property
    def session_telemetry(self):  # SessionTelemetry
        """Telemetria acumulada da sessão (números reais)."""
        return self._telemetry

    @property
    def last_ttft_s(self) -> float:
        """TTFT real da última chamada (t_primeiro_token - t0_envio)."""
        with self._telemetry_lock:
            return self._last_ttft_s

    # --- temperatura: política por modelo (24/09) ---
    # O bonsai é ternário Q2_0 e o harness o mede PERFEITO a temp 0
    # (12/12 world_ok). Modelos denso-comuns (Qwen 4B etc.) repetem/loop
    # a temp 0. Então: default 0.0 SÓ para ternário/bonsai; 0.7 para o
    # resto. Override explícito (arg ou JARVIS_LLM_TEMPERATURE) manda.
    _TERMINAL_ID: dict[str, str] = {}
    _MODEL_ID_TTL = 120.0

    def _served_model_id(self) -> str:
        import time as _t

        base = self._cfg.llm_base_url.rstrip("/")
        cached = self._TERMINAL_ID.get(base)
        if cached and (_t.time() - cached[1] if isinstance(cached, tuple) else 0) < self._MODEL_ID_TTL:
            return cached[0] if isinstance(cached, tuple) else cached
        model_id = ""
        try:
            import httpx

            with httpx.Client(timeout=2.0) as c:
                r = c.get(f"{base}/props")
                if r.status_code == 200:
                    d = r.json()
                    model_id = (d.get("model_path") or d.get("default_generation_settings", {})
                               .get("model") or d.get("model") or "")
        except Exception:  # noqa: BLE001 — política nunca derruba a chamada
            model_id = ""
        if not model_id:
            try:
                import httpx

                with httpx.Client(timeout=2.0) as c:
                    r = c.get(f"{base}/models")
                    if r.status_code == 200:
                        data = r.json().get("data") or []
                        if data:
                            model_id = str(data[0].get("id", ""))
            except Exception:  # noqa: BLE001
                model_id = ""
        self._TERMINAL_ID[base] = (model_id, _t.time())
        return model_id

    def _resolve_temperature(self, explicit: float | None) -> float:
        if explicit is not None:
            return float(explicit)
        cfg_t = getattr(self._cfg, "llm_temperature", -1.0)
        if cfg_t is not None and float(cfg_t) >= 0:
            return float(cfg_t)
        # SSOT: models.nix `routing.models.<id>.sampling` via registry.
        mid = (self._served_model_id() or "").strip()
        name = (getattr(self._cfg, "llm_model", "") or "").strip()
        for cand in (mid, name):
            if not cand:
                continue
            try:
                from jarvis.core.model_registry import ModelRegistry
                s = ModelRegistry.load().sampling_for(cand)
                if "temperature" in s:
                    return float(s["temperature"])
            except Exception:  # noqa: BLE001 — política nunca derruba a chamada
                break
        # Legado (servidor sem registry): heurística antiga preservada, mas
        # bonsai NUNCA 0.0 — greedy colapsa (2/2 idênticas, medido 25/09);
        # vendor/GGUF default é 0.5.
        blob = f"{mid} {name}".lower()
        if "bonsai" in blob or "ternary" in blob or "q2_0" in blob or "pq2" in blob:
            return 0.5
        if mid or name:
            return 0.7
        return 0.0

    def chat_full(
        self, messages: list[dict[str, Any]], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> ChatResponse:
        """Chat completion — retorna ChatResponse crua (breaker + telemetria).

        Caminho canônico para callers que precisam de campos além de
        `content` (ex.: vision precisa de `reasoning`).
        """
        request_id = uuid.uuid4().hex[:12]
        temperature = self._resolve_temperature(temperature)

        self._breaker.before_call()
        t0 = time.monotonic()
        try:
            response = self._backend.chat(
                messages=messages,
                temperature=self._resolve_temperature(temperature),
                max_tokens=max_tokens,
            )
            self._breaker.record_success()
            self._record_telemetry(response, latency_s=time.monotonic() - t0)
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

    def chat(self, messages: list[dict[str, str]], *, temperature: float | None = None, max_tokens: int | None = None) -> str:
        """Chat completion — retorna conteúdo como string."""
        return self.chat_full(messages, temperature=temperature, max_tokens=max_tokens).content

    # --- chat com tool calling (retorna ChatResponse) ---
    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
        review_focus: str | None = None,
        role: str = "orchestrator",
    ) -> ChatResponse:
        """Chat completion com tool calling — retorna ChatResponse completo.

        reasoning_effort (OpenAI-style, imitado por loops — bonsai não tem
        thinking nativo): None/low = direto; medium = +1 revisão grounded;
        high = +2 revisões. Cada revisão exige CITAÇÃO VERBATIM da resposta
        anterior; sem ela, mantém anterior e para (anti-alucinação).
        review_focus seleciona o framing ("factual" default; "syntax" p/
        quoting/shell — aceita revisão que refina o mesmo path).

        GATE (H3): reasoning_effort é custo puro em tasks curtas/classificação
        (evidência local: 3× turns sem ganho). Ativa-se automaticamente quando
        a task exige raciocínio profundo (factual-grounded, multi-step,
        tool-use complexo). Detectado via heuristica simples no conteúdo.

        ROLE (reasoning placement): "orchestrator" (default) mantém o effort
        pedido; "worker" força effort low (zero revisões), independente do
        pedido — loops de revisão em subagente têm benefício limitado ou
        negativo e custo integral em modelo pequeno. Role inválido = erro
        (fail-closed, nunca default silencioso).
        """
        if role not in ("orchestrator", "worker"):
            raise ValueError(f"role inválido: {role!r} (use 'orchestrator' ou 'worker')")
        if role == "worker":
            reasoning_effort = "low"
        # Gate automático H3: tasks longas/factual precisam de review;
        # curtas/classificação não (evita desperdício de contexto).
        _joined = " ".join(
            m.get("content", "") for m in messages
            if isinstance(m.get("content"), str)).lower()
        if reasoning_effort and reasoning_effort != "low":
            _short = len(_joined) < 80 or any(
                k in _joined for k in ("uma palavra", "quem fala",
                                        "classifique", "resuma"))
            if _short:
                reasoning_effort = "low"
        response = self._chat_once(
            messages, tools=tools, temperature=self._resolve_temperature(temperature),
            max_tokens=max_tokens, extra=extra)
        passes = {"low": 0, None: 0, "medium": 1, "high": 2}.get(
            reasoning_effort, 0)
        # Contexto da revisão inclui as tool calls anteriores serializadas:
        # turns tool-only têm content vazio e sem isso a revisão não vê nada.
        def _tc_paths(tcs: list) -> set:
            import re as _re0
            out: set = set()
            for _tc in tcs or []:
                try:
                    _fn = _tc.get("function", {}) or {}
                    _a = _fn.get("arguments", {})
                    _a = json.loads(_a) if isinstance(_a, str) else _a
                    if isinstance(_a, dict) and _a.get("path"):
                        out.add(str(_a["path"]))
                except Exception:
                    pass
            return out

        def _fn_of(tc):
            # function pode vir string (modelo malformado) — nunca .get nu.
            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
            return fn if isinstance(fn, dict) else {}

        _prior_calls = json.dumps(
            [{"name": _fn_of(tc).get("name"),
              "arguments": _fn_of(tc).get("arguments")}
             for tc in (response.tool_calls or [])], ensure_ascii=False,
            default=str)[:4000]
        # Revisão de SINTAXE precisa EMITIR calls (o loop despacha
        # tool_calls, não texto!): passa as tools; factual passa None
        # (força resposta textual avaliável por quote-grounding).
        _review_tools = tools if review_focus == "syntax" else None
        for _ in range(passes):
            review = self._chat_once(
                messages + [
                    {"role": "assistant", "content": (
                        (response.content or "")
                        + ("\n[tool_calls] " + _prior_calls
                           if _prior_calls != "[]" else ""))},
                    {"role": "user",
                     "content": _review_prompt(review_focus)},
                ], tools=_review_tools, temperature=self._resolve_temperature(temperature),
                max_tokens=max_tokens, extra=extra)
            txt = (review.content or "").strip()
            if txt.startswith("MANTER"):
                break
            if review_focus == "syntax":
                # Aceitação p/ código (novo por natureza — quote-grounding
                # fático o rejeitaria sempre): refinou os MESMOS paths, sem
                # deriva de tópico; adota AS CALLS (é o que o loop despacha).
                # Backstop continua sendo o harness (bash -n etc. barram o
                # inválido de qualquer forma).
                _p0 = _tc_paths(response.tool_calls)
                _p1 = _tc_paths(review.tool_calls)
                if _p0 and _p1 and _p1 <= _p0:
                    response.tool_calls = review.tool_calls
                    response.content = txt
                break
            import re as _re
            quotes = _re.findall(r"[\"“]([^\"”]{8,})[\"”]", txt)
            ctx = " ".join(
                m.get("content", "") for m in messages
                if isinstance(m.get("content"), str))
            ctx += " " + (response.content or "")
            if quotes and all(q in ctx for q in quotes):
                response.content = txt
            else:
                break  # sem evidência grounded: para (não degrada)
        return response

    def _chat_once(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Chat completion com tool calling — retorna ChatResponse completo."""
        request_id = uuid.uuid4().hex[:12]

        self._breaker.before_call()
        t0 = time.monotonic()
        try:
            response = self._backend.chat(
                messages=messages,
                temperature=self._resolve_temperature(temperature),
                max_tokens=max_tokens,
                tools=tools,
                extra=extra,
            )
            self._breaker.record_success()
            self._record_telemetry(response, latency_s=time.monotonic() - t0)
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
        self, messages: list[dict[str, str]], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> Iterator[str]:
        """Gera tokens incrementais via SSE real do backend (MISSÃO 2).

        Delega para backend.chat_stream() quando disponível; caso contrário
        usa fallback não-streaming de yield único.
        """
        backend_stream = getattr(self._backend, "chat_stream", None)
        if backend_stream is None:
            yield self.chat(messages, temperature=temperature, max_tokens=max_tokens)
            return
        self._breaker.before_call()
        t0 = time.monotonic()
        ttft_s = 0.0
        chunks: list[str] = []
        try:
            for token in backend_stream(messages, temperature=temperature, max_tokens=max_tokens):
                if ttft_s == 0.0:
                    ttft_s = time.monotonic() - t0  # TTFT real (MISSÃO 4)
                chunks.append(token)
                yield token
            self._breaker.record_success()
        except GeneratorExit:
            # Consumidor abandonou o stream: libera o slot sem contar
            # sucesso nem falha (abandono não é evidência de saúde).
            self._breaker.release()
            raise
        except Exception as exc:
            self._breaker.record_failure()
            raise LLMError(f"stream failed: {exc}") from exc
        finally:
            # Telemetria do stream: TTFT real; tokens via usage quando o
            # backend expõe (fallback: contagem de chunks como aproximação).
            with self._telemetry_lock:
                self._last_ttft_s = ttft_s
                self._telemetry.record(
                    model=self._resolved_model_id or "",
                    backend=getattr(self._backend, "__class__", type(self._backend)).__name__,
                    ttft_s=ttft_s, latency_s=time.monotonic() - t0,
                )

    async def achat_stream(
        self, messages: list[dict[str, str]], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        """Versão async sem bloquear o event loop (httpx no backend)."""
        backend_astream = getattr(self._backend, "achat_stream", None)
        if backend_astream is None:
            yield self.chat(messages, temperature=temperature, max_tokens=max_tokens)
            return
        self._breaker.before_call()
        t0 = time.monotonic()
        ttft_s = 0.0
        try:
            async for token in backend_astream(messages, temperature=temperature, max_tokens=max_tokens):
                if ttft_s == 0.0:
                    ttft_s = time.monotonic() - t0
                yield token
            self._breaker.record_success()
        except GeneratorExit:
            self._breaker.release()
            raise
        except Exception as exc:
            self._breaker.record_failure()
            raise LLMError(f"async stream failed: {exc}") from exc
        finally:
            with self._telemetry_lock:
                self._last_ttft_s = ttft_s
                self._telemetry.record(
                    model=self._resolved_model_id or "",
                    backend=getattr(self._backend, "__class__", type(self._backend)).__name__,
                    ttft_s=ttft_s, latency_s=time.monotonic() - t0,
                )

    # --- embeddings ---

    def embed(self, text: str, model: str | None = None) -> list[float]:
        """Embedding via backend (sob o breaker de embed: falha conta como as demais).

        (25/09) NÃO trunca mais aqui. O truncamento client-side (~480 tokens)
        derrotava o chunk+mean-pool do backend: texto de 10k chars era cortado
        para ~1.4k ANTES de chegar no providers/embedding.py, perdendo ~85%
        em silêncio — a mesma classe de bug que o remember já tinha. Quem
        respeita o limite de 512 tokens do servidor é o chunker do backend,
        que não perde dado: parte, embeda e combina por mean-pooling L2.
        """
        self._embed_breaker.before_call()
        try:
            result = self._backend.embed(text, model=model)
        except Exception as exc:
            self._embed_breaker.record_failure()
            raise LLMError(f"embedding failed: {exc}") from exc
        self._embed_breaker.record_success()
        return result

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
        # Derivado do registry — mudar a fonte propaga (test_context_drift).
        from jarvis.core.provider_registry import CANONICAL_CONTEXT
        return info.n_ctx if info else CANONICAL_CONTEXT
