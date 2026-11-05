"""Choke point único de seleção de modelo — F6 (ADR-005).

Task → Policy → Provider/Model → LLMClient. Toda seleção de modelo p/
execução de agente passa por `select_model_for_task` (que delega p/
`model_policy.select_model`, registry-driven, capabilities HARD).
Regras por capability; nunca `if bonsai:` espalhado (exceções vivem no
ModelRegistry/ModelPolicy).

HÍBRIDO (28/10): dificuldade da tarefa decide local vs cloud.
- simple/moderate → local (economia/privacidade)
- hard → cloud (groq/openrouter) se key disponível; senão local
- force_local/force_cloud têm precedência máxima
Fluxo: hybrid_route → se local, select_model_for_task (registry).
Se cloud, caller (Agent) usa cloud_entry p/ RemoteBackend.chat().

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
    prompt: str = "",
    force_local: bool = False,
    force_cloud: bool = False,
) -> tuple[str, dict]:
    """Seleciona modelo + registra provenance (quem pediu, o que voltou).

    Retorno idêntico a `model_policy.select_model` (model_id, reason) —
    o funil só ADICIONA observabilidade, nunca muda a decisão.

    HÍBRIDO: se prompt não vazio, classifica dificuldade e roteia:
    - hard → cloud (retorna model_id como "cloud/provider/model")
    - simple/moderate → local (retorna model_id do registry)
    force_local/force_cloud sobrepõem classificação.
    """
    from jarvis.core.model_policy import select_model, hybrid_route, ModelRouteError

    # Híbrido: se prompt fornecido, decide local vs cloud
    if prompt and not force_local:
        try:
            route = hybrid_route(
                prompt,
                local_requirements=requirements,
                force_local=force_local,
                force_cloud=force_cloud,
            )
            if route["target"] == "cloud":
                provider, model, _base_url, _env_key = route["cloud_entry"]
                model_id = f"cloud/{provider}/{model}"
                reason = {
                    "hybrid": True,
                    "target": "cloud",
                    "difficulty": route["difficulty"],
                    "provider": provider,
                    "model": model,
                    "reason": route["reason"],
                }
                if emit is not None:
                    try:
                        emit("model_selected", detail={
                            "caller": caller, "model": model_id, "reason": reason})
                    except Exception:
                        pass
                return model_id, reason
            # Local: extrai model_id do hybrid_route
            model_id = route["local_model"]
            reason = {
                "hybrid": True,
                "target": "local",
                "difficulty": route["difficulty"],
                "model": model_id,
                "reason": route["reason"],
            }
            if emit is not None:
                try:
                    emit("model_selected", detail={
                        "caller": caller, "model": model_id, "reason": reason})
                except Exception:
                    pass
            return model_id, reason
        except ModelRouteError:
            # Hybrid falhou (sem local, sem cloud) → cai pro fluxo antigo
            pass

    # Fluxo original (sem prompt ou force_local): registry-driven
    model_id, reason = select_model(requirements)
    if emit is not None:
        try:
            emit("model_selected", detail={
                "caller": caller, "model": model_id, "reason": reason})
        except Exception:
            pass
    return model_id, reason
