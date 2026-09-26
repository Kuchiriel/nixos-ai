"""Harbor custom agent — JARVIS Kernel (F10/ADR-005).

Calibração externa: o runtime atrás da interface `BaseAgent` do Harbor
(`--agent jarvis_harbor_agent:JarvisHarborAgent --agent-import-path ...`).
Imports do Harbor GUARDED (este módulo importa sem harbor instalado; os
testes usam stubs). Trajetória ATIF a partir da AgentSession.

NUNCA adaptar o runtime p/ passar numa task (otimizar o instrumento).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

try:  # Harbor instalado (job real)
    from harbor.agents.base import BaseAgent
    from harbor.environments.base import BaseEnvironment
    from harbor.models.agent.context import AgentContext
    _HARBOR = True
except Exception:  # sem harbor: stubs p/ teste local
    _HARBOR = False

    class BaseAgent:  # type: ignore[no-redef]
        def __init__(self, *a: Any, **k: Any) -> None:
            self.logs_dir = Path(k.get("logs_dir", "/tmp"))

    class BaseEnvironment:  # type: ignore[no-redef]
        pass

    class AgentContext:  # type: ignore[no-redef]
        def __init__(self) -> None:
            self.commands_executed = 0
            self.exit_code = 0
            self.n_input_tokens = 0
            self.n_output_tokens = 0
            self.cost_usd = 0.0
            self.error_message = None


class JarvisHarborAgent(BaseAgent):
    """AgentRuntime como custom agent do Harbor. Modelo via AgentRuntime."""

    SUPPORTS_ATIF = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._model_requirements: dict = kwargs.get("model_requirements") or {}

    @staticmethod
    def name() -> str:
        return "jarvis-kernel"

    def version(self) -> str | None:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        return None

    async def run(self, instruction: str, environment: BaseEnvironment,
                  context: AgentContext) -> None:
        from jarvis.runtime.agent_runtime import AgentRuntime

        started = time.time()
        rt = AgentRuntime()
        result = rt.run(instruction,
                        model_requirements=self._model_requirements or None)
        sess = result.session
        context.commands_executed = sess.turns
        context.exit_code = 0 if sess.verified else 1
        if sess.termination not in ("VERIFIED",):
            context.error_message = (
                f"{sess.termination}: {'; '.join(sess.missing[:3])}"[:500])
        # ATIF-ish: trajetória + sessão serializada no logs_dir
        try:
            logs = Path(getattr(self, "logs_dir", "/tmp"))
            logs.mkdir(parents=True, exist_ok=True)
            (logs / "trajectory.json").write_text(json.dumps({
                "agent": self.name(), "version": self.version(),
                "instruction": instruction,
                "verdict": sess.termination, "turns": sess.turns,
                "model": sess.model_id,
                "duration_s": round(time.time() - started, 1),
                "steps": sess.steps,
                "evidence": sess.evidence, "missing": sess.missing,
            }, ensure_ascii=False, default=str)[:200000], encoding="utf-8")
            (logs / "session.json").write_text(json.dumps(
                sess.to_dict(), ensure_ascii=False, default=str)[:200000],
                encoding="utf-8")
        except Exception:
            pass
