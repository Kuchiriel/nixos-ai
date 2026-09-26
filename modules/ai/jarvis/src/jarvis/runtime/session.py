"""AgentSession — estado explícito de execução (F7/ADR-005 §5).

Separa task/messages/tool-history/observations/artifacts/model/retry/
verification/memory-refs/telemetry/timestamps/termination em tipos claros —
nada espalhado em messages[] soltos, dicts, env vars ou CLI state.

Serializável (checkpoint/restore/inspect/test). Consumers truncam messages
antes de persistir (ver MAX_MESSAGES_PERSISTED).
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any


MAX_MESSAGES_PERSISTED = 50


@dataclass
class AgentSession:
    """Uma execução do runtime. JSON-nativo (to_dict/from_dict)."""

    task: str
    model_id: str = ""
    started_at: float = field(default_factory=time.time)
    ended_at: float = 0.0
    termination: str = "unknown"  # veredito do contrato (F5)
    verified: bool = False
    turns: int = 0
    response: str = ""
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    commands_denied: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    api_fallback: bool = False
    api_model: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    telemetry: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_agent_result(cls, task: str, model_id: str, result: Any,
                          started_at: float, ended_at: float,
                          telemetry: dict[str, Any] | None = None,
                          ) -> AgentSession:
        return cls(
            task=task, model_id=model_id,
            started_at=started_at, ended_at=ended_at,
            termination=getattr(result, "verdict", "unknown"),
            verified=bool(getattr(result, "verified", False)),
            turns=int(getattr(result, "turns", 0) or 0),
            response=str(getattr(result, "final_response", "") or ""),
            evidence=list(getattr(result, "evidence", []) or []),
            missing=list(getattr(result, "missing", []) or []),
            commands_run=list(getattr(result, "commands_run", []) or []),
            commands_denied=list(getattr(result, "commands_denied", []) or []),
            steps=list(getattr(result, "steps", []) or []),
            api_fallback=bool(getattr(result, "api_fallback", False)),
            api_model=str(getattr(result, "api_model", "") or ""),
            messages=list(getattr(result, "messages", []) or []),
            telemetry=dict(telemetry or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # trajetória capada p/ persistência (forense completa fica no JSONL)
        d["messages"] = d["messages"][-MAX_MESSAGES_PERSISTED:]
        d["messages_truncated"] = len(self.messages) > MAX_MESSAGES_PERSISTED
        return json.loads(json.dumps(d, default=str))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentSession:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
