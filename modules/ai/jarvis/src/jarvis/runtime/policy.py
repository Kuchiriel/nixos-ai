"""Choke point único de seleção de modelo — F6 (ADR-005).

Task → Policy → Provider/Model → LLMClient. Toda seleção de modelo p/
execução de agente passa por `select_model_for_task` (que delega p/
`model_policy.select_model`, registry-driven, capabilities HARD).
Regras por capability; nunca `if bonsai:` espalhado (exceções vivem no
ModelRegistry/ModelPolicy).

`provider_registry.route()` é política MORTA (0 callers — nuvem/free tiers,
nunca ligada): DEPRECATED, ver docstring lá. Se um dia o fallback cloud
for ligado, passa por ESTE funil (o linter exige).
"""
from __future__ import annotations

from typing import Any, Callable


def select_model_for_task(
    requirements: dict | None,
    *,
    caller: str = "unknown",
    emit: Callable[..., None] | None = None,
) -> tuple[str, dict]:
    """Seleciona modelo + registra provenance (quem pediu, o que voltou).

    Retorno idêntico a `model_policy.select_model` (model_id, reason) —
    o funil só ADICIONA observabilidade, nunca muda a decisão.
    """
    from jarvis.core.model_policy import select_model

    model_id, reason = select_model(requirements)
    if emit is not None:
        try:
            emit("model_selected", detail={
                "caller": caller, "model": model_id, "reason": reason})
        except Exception:
            pass
    return model_id, reason
