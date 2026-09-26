"""AgentRuntime — o único loop cognitivo (F7/ADR-005 §4).

Ciclo fixo: TASK → CONTEXT → MODEL → TOOL/TEXT → OBSERVATION → STATE →
VERIFICATION → RECOVERY/CONTINUE/COMPLETE/STUCK.

F7: compõe o Agent canônico (sem duplicar o loop) atrás da API do runtime,
com AgentSession explícita. Adapters (CLI/MCP/voz) e o supervisor
(Nightwatch) consomem `run()` — nenhum reimplementa o ciclo.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from jarvis.runtime.session import AgentSession


@dataclass
class RuntimeResult:
    """Resultado de AgentRuntime.run()."""

    session: AgentSession
    verdict: str = "unknown"
    response: str = ""
    turns: int = 0
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    # Espelhos p/ migração mecânica dos compositores (F8) — fonte: session.
    verified: bool = False
    commands_run: list[str] = field(default_factory=list)
    commands_denied: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)


class AgentRuntime:
    """Runtime canônico. Wiring injetável (testes usam FakeSession)."""

    def __init__(self, config: Any | None = None,
                 http_session: Any | None = None,
                 memory: Any | None = None,
                 agent_kwargs: dict[str, Any] | None = None) -> None:
        from jarvis.core.config import get_config
        self.config = config or get_config()
        self.http_session = http_session
        self.memory = memory
        self.agent_kwargs = dict(agent_kwargs or {})

    def run(self, task: str,
            model_requirements: dict | None = None,
            persona_id: str | None = None,
            **agent_kw: Any) -> RuntimeResult:
        from jarvis.core.agent import Agent

        started = time.time()
        agent = Agent(
            self.config, session=self.http_session, memory=self.memory,
            model_requirements=model_requirements, persona_id=persona_id,
            **{**self.agent_kwargs, **agent_kw})
        result = agent.run(task)
        ended = time.time()
        model_id = getattr(getattr(agent, "config", self.config),
                           "llm_model", "")
        session = AgentSession.from_agent_result(
            task, model_id, result, started, ended,
            telemetry={"runtime": "AgentRuntime", "caller": "run"})
        return RuntimeResult(
            session=session, verdict=session.termination,
            response=session.response, turns=session.turns,
            evidence=session.evidence, missing=session.missing,
            verified=session.verified, commands_run=session.commands_run,
            commands_denied=session.commands_denied, steps=session.steps)
