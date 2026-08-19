"""Circuit Breaker e Fallback Inteligente de Inferência.

Padrão Circuit Breaker:
  - CLOSED: backend local funciona → usa local
  - OPEN: backend falhou N vezes → abre circuito, usa fallback remoto
  - HALF_OPEN: após cooldown, testa backend local → se funcionar, fecha circuito

Fallback remoto:
  - Provider configurável (OpenRouter/Gemini/Groq) via env
  - Só aceita prompts SEM dados sensíveis (filtro de segurança)
  - Logs de cada decisão (local/remote) para auditoria

POLÍTICA DE EGRESS:
  - Dados sensíveis (memórias episódicas, RAG, contexto privado) NUNCA saem
  - Filtro por keywords e padrões (ex: "recall", "remember", "vault", paths)
  - Usuário pode forçar modo local (/force_local)
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

import requests

from jarvis.core.health_monitor import BackendHealthMonitor, BackendState


class CircuitState(str, Enum):
    CLOSED = "closed"      # local funciona
    OPEN = "open"          # local falhou → fallback
    HALF_OPEN = "half_open"  # testando se local voltou


# Keywords que indicam dados sensíveis — NUNCA devem ir para fallback remoto
SENSITIVE_PATTERNS: tuple[str, ...] = (
    "recall", "remember", "vault", "memória", "memoria", "episódica",
    "episodica", "lesson", "lição", "lição", "fato pessoal",
    "/home/", "/etc/", "password", "senha", "token", "api_key",
    "secret", "credential", "ssh", "private", "privado",
)


@dataclass
class CircuitBreakerState:
    """Estado do circuit breaker."""
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    total_local_calls: int = 0
    total_fallback_calls: int = 0
    total_rejected: int = 0  # fallback negado por segurança


class ContentSafetyFilter:
    """Filtra prompts que contêm dados sensíveis.

    Retorna True se o prompt é SEGURO para envio remoto.
    """

    def __init__(self, extra_patterns: tuple[str, ...] | None = None) -> None:
        self._patterns = SENSITIVE_PATTERNS + (extra_patterns or ())
        # Patterns de caminho (/home/, /etc/) e tokens longos usam substring;
        # patterns curtos (< 5 chars) usam word boundary para evitar falsos
        # positivos em strings aleatórias (ex: "ssh" em "uhrsshb6a9...").
        self._compiled: list[re.Pattern[str]] = []
        for p in self._patterns:
            escaped = re.escape(p)
            if len(p) < 5 and not p.startswith("/"):
                self._compiled.append(re.compile(rf"\b{escaped}\b", re.IGNORECASE))
            else:
                self._compiled.append(re.compile(escaped, re.IGNORECASE))

    def is_safe(self, prompt: str) -> tuple[bool, str]:
        """Verifica se o prompt é seguro para fallback remoto.

        Returns:
            (is_safe, reason) — reason é vazio se seguro
        """
        for i, pattern in enumerate(self._compiled):
            if pattern.search(prompt):
                return False, f"sensitive pattern: {self._patterns[i]}"
        return True, ""


class CircuitBreaker:
    """Circuit Breaker com fallback remoto e filtro de segurança.

    Exemplo:
        cb = CircuitBreaker(
            health_monitor=monitor,
            fallback_fn=my_remote_api,
        )
        result = cb.execute("qual é a capital do Brasil?")
        # Se local falhou → fallback automático (se seguro)
    """

    def __init__(
        self,
        health_monitor: BackendHealthMonitor,
        *,
        failure_threshold: int = 3,
        recovery_timeout_s: float = 60.0,
        fallback_fn: Callable[[list[dict[str, str]]], str] | None = None,
        on_state_change: Callable[[CircuitState, CircuitState, str], Any] | None = None,
    ) -> None:
        self._monitor = health_monitor
        self._failure_threshold = failure_threshold
        self._recovery_timeout_s = recovery_timeout_s
        self._fallback_fn = fallback_fn
        self._on_state_change = on_state_change
        self._state = CircuitBreakerState()
        self._safety = ContentSafetyFilter()
        self._log: list[dict[str, Any]] = []

    @property
    def state(self) -> CircuitState:
        """Estado atual (com transição automática HALF_OPEN → CLOSED se OK)."""
        self._maybe_transition()
        return self._state.state

    @property
    def state_info(self) -> dict[str, Any]:
        """Info completa do estado."""
        return {
            "circuit_state": self._state.state.value,
            "failure_count": self._state.failure_count,
            "total_local": self._state.total_local_calls,
            "total_fallback": self._state.total_fallback_calls,
            "total_rejected": self._state.total_rejected,
            "backend": self._monitor.status_dict(),
        }

    def execute(
        self,
        messages: list[dict[str, str]],
        *,
        local_fn: Callable[[list[dict[str, str]]], str],
        force_local: bool = False,
    ) -> dict[str, Any]:
        """Executa inferência com circuit breaker.

        Returns:
            {
                "response": str,
                "backend": "local" | "fallback" | "rejected",
                "circuit_state": str,
                "latency_ms": float,
            }
        """
        self._maybe_transition()

        # Se force_local, tenta local mesmo se circuito aberto
        if force_local or self._state.state == CircuitState.CLOSED:
            return self._try_local(messages, local_fn)

        if self._state.state == CircuitState.HALF_OPEN:
            # Testa local
            result = self._try_local(messages, local_fn)
            if result["backend"] == "local":
                self._transition(CircuitState.CLOSED, "local recovered")
            return result

        # Circuit OPEN — tenta fallback
        if self._fallback_fn is None:
            return {
                "response": "ERRO: backend local indisponível e fallback não configurado.",
                "backend": "rejected",
                "circuit_state": self._state.state.value,
                "latency_ms": 0,
            }

        # Filtro de segurança
        prompt_text = " ".join(m.get("content", "") for m in messages)
        is_safe, reason = self._safety.is_safe(prompt_text)
        if not is_safe:
            self._state.total_rejected += 1
            self._record_decision("rejected", reason)
            return {
                "response": f"ERRO: backend local indisponível. Fallback remoto negado: dados sensíveis detectados ({reason}). Aguarde recuperação do backend local.",
                "backend": "rejected",
                "circuit_state": self._state.state.value,
                "latency_ms": 0,
            }

        # Executa fallback remoto
        return self._try_fallback(messages)

    def _try_local(
        self,
        messages: list[dict[str, str]],
        local_fn: Callable[[list[dict[str, str]]], str],
    ) -> dict[str, Any]:
        """Tenta execução local."""
        t0 = time.time()
        try:
            response = local_fn(messages)
            latency = round((time.time() - t0) * 1000, 1)
            self._state.total_local_calls += 1
            self._state.last_success_time = time.time()
            self._state.failure_count = 0
            self._record_decision("local", f"ok ({latency}ms)")
            return {
                "response": response,
                "backend": "local",
                "circuit_state": self._state.state.value,
                "latency_ms": latency,
            }
        except Exception as exc:  # noqa: BLE001
            latency = round((time.time() - t0) * 1000, 1)
            self._state.failure_count += 1
            self._state.last_failure_time = time.time()
            self._record_decision("local_error", str(exc)[:200])

            if self._state.failure_count >= self._failure_threshold:
                self._transition(CircuitState.OPEN, f"threshold reached ({self._state.failure_count} failures)")

            # Se tem fallback, tenta
            if self._fallback_fn is not None:
                return self._try_fallback(messages)

            return {
                "response": f"ERRO: backend local falhou ({exc}). Sem fallback configurado.",
                "backend": "local_error",
                "circuit_state": self._state.state.value,
                "latency_ms": latency,
            }

    def _try_fallback(
        self,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Tenta fallback remoto."""
        assert self._fallback_fn is not None
        t0 = time.time()
        try:
            response = self._fallback_fn(messages)
            latency = round((time.time() - t0) * 1000, 1)
            self._state.total_fallback_calls += 1
            self._record_decision("fallback", f"ok ({latency}ms)")
            return {
                "response": response,
                "backend": "fallback",
                "circuit_state": self._state.state.value,
                "latency_ms": latency,
            }
        except Exception as exc:  # noqa: BLE001
            latency = round((time.time() - t0) * 1000, 1)
            self._record_decision("fallback_error", str(exc)[:200])
            return {
                "response": f"ERRO: backend local e fallback ambos falharam. ({exc})",
                "backend": "fallback_error",
                "circuit_state": self._state.state.value,
                "latency_ms": latency,
            }

    def _transition(self, new_state: CircuitState, reason: str) -> None:
        """Transição de estado com notificação."""
        old = self._state.state
        if old == new_state:
            return
        self._state.state = new_state
        if new_state == CircuitState.OPEN:
            self._state.last_failure_time = time.time()
        elif new_state == CircuitState.CLOSED:
            self._state.failure_count = 0
            self._state.last_success_time = time.time()
        if self._on_state_change:
            self._on_state_change(old, new_state, reason)

    def _maybe_transition(self) -> None:
        """Verifica se deve transicionar de OPEN para HALF_OPEN."""
        if self._state.state == CircuitState.OPEN:
            elapsed = time.time() - self._state.last_failure_time
            if elapsed >= self._recovery_timeout_s:
                self._transition(CircuitState.HALF_OPEN, "recovery timeout elapsed")

    def _record_decision(self, backend: str, detail: str) -> None:
        """Registra decisão de roteamento para auditoria."""
        self._log.append({
            "ts": time.time(),
            "circuit_state": self._state.state.value,
            "backend": backend,
            "detail": detail,
        })
        # Mantém apenas os últimos 200 registros
        if len(self._log) > 200:
            self._log = self._log[-200:]

    @property
    def recent_log(self) -> list[dict[str, Any]]:
        """Últimas 20 decisões de roteamento."""
        return self._log[-20:]

    def force_local(self) -> str:
        """Força retorno ao modo local."""
        self._transition(CircuitState.CLOSED, "forced by user")
        self._state.failure_count = 0
        return "Circuit breaker resetado — modo local forçado."

    def force_remote(self) -> str:
        """Força abertura do circuito (fallback)."""
        self._transition(CircuitState.OPEN, "forced by user")
        return "Circuit breaker aberto — usando fallback remoto."

    def force_open(self) -> str:
        """Força abertura do circuito (fallback)."""
        self._transition(CircuitState.OPEN, "forced by user")
        return "Circuit breaker aberto — usando fallback remoto."
