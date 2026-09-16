"""
Model Policy — routes different models to different workflow stages.

Based on OpenDev's per-workflow LLM binding architecture:
- Cheap models for classification, routing, simple tasks
- Medium models for implementation, editing, testing
- Strong models for architecture, complex reasoning, planning
- Vision models for GUI interaction

The model is NOT hardcoded. It's selected based on:
1. The workflow stage
2. Available hardware (VRAM, RAM)
3. The task complexity
4. User preferences
"""

import json
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ModelTier:
    """A model tier with its characteristics."""
    name: str
    tier: str  # cheap, medium, strong, vision
    model_name: str
    context_size: int = 32000
    tokens_per_second: float = 0
    vram_required_gb: float = 0
    description: str = ""

    def to_dict(self):
        return {
            "name": self.name,
            "tier": self.tier,
            "model_name": self.model_name,
            "context_size": self.context_size,
            "tokens_per_second": self.tokens_per_second,
            "vram_required_gb": self.vram_required_gb,
            "description": self.description,
        }


# Default model tiers (contexto vem do registry/models.nix; fallback 32000)
def _registry_ctx(model_id: str, default: int = 32000) -> int:
    """Lê ctx do /etc/jarvis/model-registry.json (fonte: models.nix).

    Bug fix (dono 16/09): lia m.extra (campo INEXISTENTE em ModelEntry —
    sempre default 32000 mesmo com ctx=49152 no registry). ctx vive no
    raw dict (routing models.nix) → m.raw.get("ctx").
    """
    try:
        from jarvis.core.model_registry import ModelRegistry
        m = ModelRegistry.load().models.get(model_id)
        if m is None:
            return default
        c = (m.raw or {}).get("ctx")
        if c:
            return int(c)
    except Exception:
        pass
    return default


_CTX_BONSAI = _registry_ctx("bonsai")
_CTX_FAST = _registry_ctx("jarvis-fast")
DEFAULT_TIERS = {
    "cheap": ModelTier(
        name="cheap",
        tier="cheap",
        model_name="qwen3.6-4b",
        context_size=_CTX_FAST,
        tokens_per_second=45,
        vram_required_gb=2.5,
        description="Fast classification, routing, simple tasks",
    ),
    "medium": ModelTier(
        name="medium",
        tier="medium",
        model_name="qwen3.6-moe-14b",
        context_size=32000,
        tokens_per_second=24,
        vram_required_gb=5.5,
        description="Implementation, editing, testing",
    ),
    "strong": ModelTier(
        name="strong",
        tier="strong",
        model_name="qwen3.6-moe-35b",
        context_size=32000,
        tokens_per_second=15,
        vram_required_gb=20,
        description="Architecture, complex reasoning, planning",
    ),
}

# Stage → preferred tier mapping
STAGE_TIER_MAP = {
    # Planning / Architecture
    "research": "strong",
    "planning": "strong",
    "architecture": "strong",
    "decide": "strong",
    "review": "strong",

    # Implementation
    "implement": "medium",
    "patch": "medium",
    "fix": "medium",
    "backend_engineer": "medium",
    "nixos_engineer": "medium",

    # Testing
    "testing": "medium",
    "regression-test": "medium",
    "validate": "medium",

    # Simple tasks
    "classify": "cheap",
    "route": "cheap",
    "summarize": "cheap",
    "documentation": "cheap",
    "technical_writer": "cheap",

    # Discovery
    "discover": "cheap",
    "prioritize": "cheap",
    "monitor": "cheap",
}

# Workflow stage → tier mapping (used by orchestrator)
WORKFLOW_TIER_MAP = {
    # feature-development
    "research": "strong",
    "planning": "strong",
    "implementation": "medium",
    "testing": "medium",
    "review": "strong",
    "documentation": "cheap",

    # bugfix
    "reproduce": "medium",
    "diagnose": "strong",
    "patch": "medium",
    "regression-test": "medium",

    # architecture-review
    "audit": "strong",
    "analyze": "strong",
    "document": "cheap",

    # overnight-maintenance
    "prioritize": "cheap",
    "fix": "medium",
    "commit": "cheap",
}


class ModelPolicy:
    """Routes models to workflow stages."""

    def __init__(self, config_path: str = None):
        self._tiers = dict(DEFAULT_TIERS)
        self._stage_map = {**STAGE_TIER_MAP, **WORKFLOW_TIER_MAP}

        # Load user overrides
        if config_path:
            self._load_config(config_path)
        else:
            default_path = os.path.expanduser("~/.local/state/jarvis/model-policy.json")
            if os.path.exists(default_path):
                self._load_config(default_path)

    def _load_config(self, path: str):
        """Load model policy from config file."""
        try:
            with open(path) as f:
                data = json.load(f)

            # Override tiers
            for tier_name, tier_data in data.get("tiers", {}).items():
                if tier_name in self._tiers:
                    for k, v in tier_data.items():
                        setattr(self._tiers[tier_name], k, v)

            # Override stage mappings
            self._stage_map.update(data.get("stage_map", {}))
        except Exception:
            pass

    def select_tier(self, stage: str, available_vram_gb: float = 6.0) -> ModelTier:
        """Select the best model tier for a workflow stage.

        Considers:
        1. Stage requirements (from STAGE_TIER_MAP)
        2. Available VRAM (downgrades if necessary)
        3. Fallback to medium if unknown stage
        """
        preferred_tier = self._stage_map.get(stage, "medium")

        # Check if preferred tier fits in available VRAM
        tier = self._tiers.get(preferred_tier)
        if not tier:
            tier = self._tiers["medium"]

        if tier.vram_required_gb > available_vram_gb:
            # Downgrade to a tier that fits
            for candidate_name in ["medium", "cheap"]:
                candidate = self._tiers.get(candidate_name)
                if candidate and candidate.vram_required_gb <= available_vram_gb:
                    return candidate

            # Last resort: cheapest
            return self._tiers.get("cheap", tier)

        return tier

    def get_system_prompt_addition(self, tier: ModelTier) -> str:
        """Get system prompt additions based on model tier."""
        if tier.tier == "cheap":
            return (
                "You are running on a fast, lightweight model. "
                "Be concise. Focus on classification and simple tasks. "
                "Do not attempt complex reasoning or multi-step planning."
            )
        elif tier.tier == "strong":
            return (
                "You are running on a powerful model. "
                "Take time to reason carefully. Consider alternatives. "
                "Provide thorough analysis and well-structured plans."
            )
        else:  # medium
            return (
                "You are running on a balanced model. "
                "Focus on implementation and practical solutions."
            )

    def list_tiers(self) -> list[ModelTier]:
        """List all available tiers."""
        return list(self._tiers.values())

    def summary(self) -> str:
        """Human-readable summary."""
        lines = ["Model Policy:"]
        for name, tier in sorted(self._tiers.items()):
            lines.append(
                f"  {name}: {tier.model_name} "
                f"({tier.context_size} ctx, "
                f"~{tier.tokens_per_second} t/s, "
                f"{tier.vram_required_gb} GB VRAM)"
            )
        lines.append(f"\nStage mappings: {len(self._stage_map)}")
        return "\n".join(lines)

    def save(self, path: str = None):
        """Save policy to disk."""
        if path is None:
            path = os.path.expanduser("~/.local/state/jarvis/model-policy.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)

        data = {
            "tiers": {name: tier.to_dict() for name, tier in self._tiers.items()},
            "stage_map": self._stage_map,
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2)


# ── Router local (registry-driven) ─────────────────────────────────────
# Converge com modules/ai/models.nix `routing`: capabilities são HARD
# (modelo sem a capability nunca é selecionado), tier é preferência com
# fallback registrado em `reason`. Nenhum nome de modelo hardcoded aqui —
# tudo vem do ModelRegistry (JSON gerado pelo Nix).

class ModelRouteError(ValueError):
    """Nenhum modelo elegível para os requisitos."""


# Ordem de preferência quando o tier pedido não tem elegível (menor 1º).
_TIER_RANK = {"speed": 0, "fast": 1, "reasoning": 2}

# Stage legado (cheap/medium/strong) → tier do registry.
_STAGE_TO_TIER = {"cheap": "fast", "medium": "fast", "strong": "reasoning"}


def select_model(
    requirements: dict | None = None,
    registry=None,
) -> tuple[str, dict]:
    """Seleciona modelo do registry por requisitos.

    requirements: {
      "capabilities": set[str] (ex.: {"coding","tools"}),
      "tier": "fast"|"reasoning"|"speed"|None,
      "stage": "cheap"|"medium"|"strong"|None (legado, mapeado p/ tier),
      "local_only": bool (registry é local por construção; só documenta),
    }
    Retorna (model_id, reason). Capabilities insatisfeitas → ModelRouteError
    (nunca fallback silencioso p/ modelo incapaz). Tier é soft: se o tier
    pedido não tem elegível, usa o elegível mais barato e registra em reason.
    """
    from jarvis.core.model_registry import ModelRegistry

    req = requirements or {}
    reg = registry or ModelRegistry.load()
    caps = set(req.get("capabilities", ()))
    tier = req.get("tier")
    if tier is None and req.get("stage"):
        tier = _STAGE_TO_TIER.get(req["stage"])

    eligible = [
        m for m in reg.models.values()
        if caps <= set(m.capabilities)
    ]
    if not eligible:
        raise ModelRouteError(
            f"nenhum modelo com capabilities {sorted(caps)} "
            f"(registry: {reg.source})"
        )
    eligible.sort(key=lambda m: (_TIER_RANK.get(m.tier, 9), m.params_b))

    if tier is not None:
        for m in eligible:
            if m.tier == tier:
                return m.id, {
                    "requested": dict(req, capabilities=sorted(caps)),
                    "selected": m.id, "tier_match": True,
                    "local_only": True,
                }
        reason = {"tier_fallback": tier, "tier_match": False}
    else:
        reason = {"tier_match": None}
    chosen = eligible[0]
    return chosen.id, {
        "requested": dict(req, capabilities=sorted(caps)),
        "selected": chosen.id, "local_only": True, **reason,
    }
