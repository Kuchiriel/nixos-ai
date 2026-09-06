"""Provider registry + roteamento policy-based (local → free → paid).

Nunca ficar sem modelo: cada consulta retorna uma LISTA ORDENADA de
candidatos (não um único provider), do mais barato/local ao mais caro.
O chamador tenta em ordem; cotas esgotadas só andam a lista adiante.

Fontes (inventário 2026-09-06, `opencode models` = 591 modelos):
  local 2 · cerebras 3 · groq 16 · google 38 · nvidia 101 · opencode 69 ·
  openrouter 362 (agregador c/ fallback próprio).

Agregadores de última linha (só PUBLIC — reviews apontam guardrails
fail-open e maintainer único; jamais dados sensíveis):
  - openrouter (SaaS, fallback próprio, :free 50 req/dia, 20 RPM)
  - omniroute (self-hosted localhost:20128, 352 providers, 150+ free)
  - 9router (original, 60+ providers, 3-tier; MESMA porta 20128 — conflito!)

Matemática (audit §1.5): minimizar C(p) = wt·T + wq·(1-Q) + wr·R + wc·Cost
com restrição dura R=∞ quando data_class > provider.max_data_class.
Na prática: filtro por classe (hard) + ordenação por tier/custo/latência.

Personas: model_preference cheap/medium/strong × task_kind
(code/research/reasoning/chat) → pool ordenado. Uma persona pode render
melhor com roteamento próprio em vez do default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from jarvis.core.circuit_breaker import DataClass


class ProviderTier(str, Enum):
    LOCAL = "local"  # $0, dados nunca saem — sempre primeiro
    FREE = "free"    # $0, cotas variáveis — meio
    PAID = "paid"    # $>0 — última linha antes de erro controlado


class ProviderKind(str, Enum):
    DIRECT = "direct"        # endpoint do próprio provider
    AGGREGATOR = "aggregator"  # fallback próprio interno (openrouter/omni/9router)


@dataclass(frozen=True)
class ModelCaps:
    """Capacidades de um modelo p/ capability matching."""
    context: int = 32768
    tools: bool = True
    reasoning: bool = False
    vision: bool = False
    latency: str = "normal"  # "fast" (LPU/Cerebras) | "normal" | "slow"


@dataclass(frozen=True)
class Provider:
    name: str
    kind: ProviderKind
    tier: ProviderTier
    base_url: str
    max_data_class: DataClass  # teto de sensibilidade (R=∞ acima)
    models: dict[str, ModelCaps] = field(default_factory=dict)
    notes: str = ""


# --- pools curados (do inventário real; não os 591 — os úteis) ---

LOCAL_BONSAI = Provider(
    name="local", kind=ProviderKind.DIRECT, tier=ProviderTier.LOCAL,
    base_url="http://127.0.0.1:8080/v1",
    max_data_class=DataClass.SECRET,  # tudo pode ficar local
    models={
        "bonsai-8b": ModelCaps(context=32768, tools=True, reasoning=True),
        "qwen3-35b-a3b": ModelCaps(context=131072, tools=True, reasoning=True),
    },
    notes="Ternary-Bonsai-8B Q2_0, TG 71.6 t/s medido",
)

CEREBRAS = Provider(
    name="cerebras", kind=ProviderKind.DIRECT, tier=ProviderTier.FREE,
    base_url="https://api.cerebras.ai/v1",
    max_data_class=DataClass.PUBLIC,
    models={"llama3.1-70b": ModelCaps(context=131072, tools=True, latency="fast")},
    notes="inferência rápida; free ~1M tok/dia",
)

GROQ = Provider(
    name="groq", kind=ProviderKind.DIRECT, tier=ProviderTier.FREE,
    base_url="https://api.groq.com/openai/v1",
    max_data_class=DataClass.PUBLIC,
    models={
        "llama-3.3-70b-versatile": ModelCaps(context=128000, tools=True, latency="fast"),
        "llama-3.1-8b-instant": ModelCaps(context=128000, tools=True, latency="fast"),
    },
    notes="LPU ultra-rápido; headers de rate-limit alimentam o router",
)

GEMINI = Provider(
    name="gemini", kind=ProviderKind.DIRECT, tier=ProviderTier.FREE,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    max_data_class=DataClass.PUBLIC,
    models={
        "gemini-2.5-flash": ModelCaps(context=1000000, tools=True, latency="fast"),
        "gemini-3-flash": ModelCaps(context=1000000, tools=True, reasoning=True),
    },
    notes="janela 1M p/ logs imensos; free tier treina com dados (caveat)",
)

NVIDIA = Provider(
    name="nvidia", kind=ProviderKind.DIRECT, tier=ProviderTier.FREE,
    base_url="https://integrate.api.nvidia.com/v1",
    max_data_class=DataClass.PUBLIC,
    models={
        "nemotron-3-ultra-free": ModelCaps(context=131072, tools=True, reasoning=True),
        "nemotron-3.5-lightning-free": ModelCaps(context=131072, tools=True, latency="fast"),
        "ling-3.0-flash-fin:free": ModelCaps(context=262000, tools=True, reasoning=True),
    },
    notes="NIM ~40 RPM free; thinking mode nativo (temp 1.0/top_p 0.95)",
)

OPENROUTER = Provider(
    name="openrouter", kind=ProviderKind.AGGREGATOR, tier=ProviderTier.FREE,
    base_url="https://openrouter.ai/api/v1",
    max_data_class=DataClass.PUBLIC,
    models={
        "free": ModelCaps(context=64000, tools=True),
        "qwen/qwen3-coder:free": ModelCaps(context=262000, tools=True),
    },
    notes="fallback próprio; :free 50 req/dia +$10 → maior RPM",
)

OMNIROUTE = Provider(
    name="omniroute", kind=ProviderKind.AGGREGATOR, tier=ProviderTier.FREE,
    base_url="http://localhost:20128/v1",
    max_data_class=DataClass.PUBLIC,  # NUNCA acima: guardrails fail-open
    models={"auto": ModelCaps(context=128000, tools=True)},
    notes="self-hosted, 352 providers; exige daemon local; conflita porta c/ 9router",
)

NINEROUTER = Provider(
    name="9router", kind=ProviderKind.AGGREGATOR, tier=ProviderTier.FREE,
    base_url="http://localhost:20128/v1",
    max_data_class=DataClass.PUBLIC,  # idem: só PUBLIC
    models={"auto": ModelCaps(context=128000, tools=True)},
    notes="original 3-tier (subscription→cheap→free); MESMA porta do omniroute",
)


REGISTRY: dict[str, Provider] = {
    p.name: p for p in (
        LOCAL_BONSAI, CEREBRAS, GROQ, GEMINI, NVIDIA,
        OPENROUTER, OMNIROUTE, NINEROUTER,
    )
}

# Ordem de custo: local → free (rápidos primeiro) → agregadores por último.
_TIER_ORDER = {ProviderTier.LOCAL: 0, ProviderTier.FREE: 1, ProviderTier.PAID: 2}


# --- roteamento por persona × tarefa ---

# model_preference (cheap/medium/strong) × task_kind → ajuste de pool.
PERSONA_ROUTING: dict[str, dict[str, Any]] = {
    "cheap": {"prefer_latency": True, "skip_reasoning": True},
    "medium": {"prefer_latency": True, "skip_reasoning": False},
    "strong": {"prefer_latency": False, "skip_reasoning": False},
}

TASK_ROUTING: dict[str, dict[str, Any]] = {
    "code": {"prefer_latency": True, "min_context": 0},
    "research": {"prefer_latency": False, "min_context": 200000},
    "reasoning": {"require_reasoning": True},
    "chat": {"prefer_latency": True, "min_context": 0},
}


def _class_allows(provider: Provider, data_class: DataClass) -> bool:
    """Restrição dura: R=∞ quando data_class > provider.max_data_class."""
    order = {DataClass.PUBLIC: 0, DataClass.INTERNAL: 1,
             DataClass.CONFIDENTIAL: 2, DataClass.SECRET: 3}
    return order[data_class] <= order[provider.max_data_class]


def route(
    data_class: DataClass = DataClass.PUBLIC,
    tier: str = "medium",
    task_kind: str = "chat",
    *,
    min_context: int = 0,
    require_tools: bool = False,
    local_only: bool = False,
) -> list[str]:
    """Lista ordenada de providers candidatos (nunca um único ponto de falha).

    SECRET/CONFIDENTIAL/INTERNAL → só local (ou vazio = erro controlado).
    PUBLIC → local → free rápidos → agregadores por último.
    """
    if local_only or data_class is not DataClass.PUBLIC:
        return ["local"]  # R=∞ p/ cloud: só o local pode atender

    t = PERSONA_ROUTING.get(tier, PERSONA_ROUTING["medium"])
    task = TASK_ROUTING.get(task_kind, TASK_ROUTING["chat"])
    need_ctx = max(min_context, task.get("min_context", 0))
    need_reason = task.get("require_reasoning", False)

    cands: list[tuple[int, int, str]] = []  # (tier, latency_penalty, name)
    for name, p in REGISTRY.items():
        if not _class_allows(p, data_class):
            continue
        if p.kind is ProviderKind.AGGREGATOR and name in ("omniroute", "9router"):
            continue  # agregadores locais exigem daemon; opt-in explícito
        if require_tools and not any(m.tools for m in p.models.values()):
            continue
        if need_reason and not any(m.reasoning for m in p.models.values()):
            continue
        if need_ctx and not any(m.context >= need_ctx for m in p.models.values()):
            continue
        latency_pen = 0
        if t.get("prefer_latency") or task.get("prefer_latency"):
            latency_pen = 0 if any(m.latency == "fast" for m in p.models.values()) else 1
        if (
            t.get("skip_reasoning")
            and p.tier is not ProviderTier.LOCAL
            and all(m.reasoning for m in p.models.values())
        ):
            continue
        cands.append((_TIER_ORDER[p.tier], latency_pen, name))

    cands.sort()
    return [name for _, _, name in cands]


def route_for_persona(persona_tier: str, task_kind: str = "chat", **kw: Any) -> list[str]:
    """Atalho: roteamento pelo model_preference da persona."""
    return route(tier=persona_tier or "medium", task_kind=task_kind, **kw)


def describe() -> dict[str, Any]:
    """Inventário legível p/ /stats, docs e debug."""
    return {
        name: {
            "tier": p.tier.value, "kind": p.kind.value,
            "url": p.base_url, "max_class": p.max_data_class.value,
            "models": sorted(p.models), "notes": p.notes,
        }
        for name, p in REGISTRY.items()
    }
