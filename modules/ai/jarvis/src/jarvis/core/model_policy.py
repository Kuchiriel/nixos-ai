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

    # Framings por modelo API (catálogo 17/09, docs/models/api-catalog).
    # Regras operacionais curtas (RRP) por comportamento conhecido —
    # persona NÃO entra aqui (H2: persona perturba; rules funcionam).
    MODEL_FRAMINGS: dict[str, str] = {
        "nemotron": "Reason with thinking enabled before answering; keep the final answer structured.",
        "ling": "Output strict structured data (JSON) when the task asks for extraction; stay literal.",
        "mimo": "Be concise and direct; short answers first, details only if asked.",
        "spark": "Long-horizon task: keep a running plan, avoid repeating tool calls already made.",
        "union": "Privacy-critical repo: never include secrets or full file dumps in reasoning.",
        "deepseek": "Batch coding task: surgical diffs, one concern per edit, verify with tests.",
        "glm": "Classification only: output the label, no explanation.",
        "nex": "Follow instructions literally; stable Markdown formatting.",
    }

    @classmethod
    def framing_for(cls, model_id: str) -> str:
        """Framing RRP por id do modelo (match por substring, case-insensitive)."""
        mid = (model_id or "").lower()
        for key, framing in cls.MODEL_FRAMINGS.items():
            if key in mid:
                return framing
        return ""

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


# ── CASCADE_MAP: fonte única = free-providers.json ──────────────────
# (28/10, dono: "fonte única onde ambos sistemas bebem"). O JSON
# modules/ai/free-providers.json é a ÚNICA fonte de verdade — consumido
# por ESTE módulo (CASCADE_MAP) e pelo home.nix (opencode providers).
# NÃO editar CASCADE_MAP hardcoded: editar o JSON e re-testar.
#
# Formato do JSON: providers.<name>.{base_url,env_key,requires_headers,models[]}
#                 cascade_layers.<layer> = [{provider, model}, ...]
#
# Testado ao vivo 28/10/2026: groq ✅, nvidia ✅, cloudflare ✅,
# gemini ✅, openrouter ✅ (com headers), ovhcloud ✅ (anon),
# kilocode ✅ (anon), llm7 ✅ (anon). Desativados: cerebras (payment),
# together (bad key), hf (no credits), sambanova (high demand).

import json as _json
from pathlib import Path as _Path

_FREE_PROVIDERS_PATH = _Path(__file__).parent.parent.parent.parent.parent / "free-providers.json"


def _load_free_providers() -> dict:
    """Carrega free-providers.json (fonte única). Fallback = dict vazio."""
    try:
        return _json.loads(_FREE_PROVIDERS_PATH.read_text())
    except (OSError, _json.JSONDecodeError):
        return {"providers": {}, "cascade_layers": {}}


def _build_cascade_map() -> dict[str, list[tuple[str, str, str, str]]]:
    """Constrói CASCADE_MAP do free-providers.json.

    Retorna: {layer: [(provider, model, base_url, env_key), ...]}
    base_url e env_key vêm do provider definition no JSON.
    """
    data = _load_free_providers()
    providers = data.get("providers", {})
    layers = data.get("cascade_layers", {})

    result: dict[str, list[tuple[str, str, str, str]]] = {}
    for layer_name, entries in layers.items():
        if layer_name.startswith("_"):
            continue  # pula chaves de comentário
        layer_list: list[tuple[str, str, str, str]] = []
        for entry in entries:
            prov_name = entry.get("provider", "")
            model_id = entry.get("model", "")
            prov = providers.get(prov_name, {})
            base_url = prov.get("base_url", "")
            env_key = prov.get("env_key") or ""
            # Substitui placeholder de account_id se presente
            if "{CLOUDFLARE_ACCOUNT_ID}" in base_url:
                import os
                acct = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
                base_url = base_url.replace("{CLOUDFLARE_ACCOUNT_ID}", acct)
            layer_list.append((prov_name, model_id, base_url, env_key))
        result[layer_name] = layer_list
    return result


# CASCADE_MAP construído do JSON (fonte única). Mantém compat com o
# formato antigo: {layer: [(provider, model, base_url, env_key), ...]}
CASCADE_MAP: dict[str, list[tuple[str, str, str, str]]] = _build_cascade_map()


def cascade_for(layer: str) -> list[tuple[str, str, str, str]]:
    """Ordem de fallback API p/ camada (vazia se camada desconhecida)."""
    return list(CASCADE_MAP.get(layer, []))


def cascade_key_present(entry: tuple[str, str, str, str]) -> bool:
    """True se a env key da entrada existe e não está vazia."""
    import os
    return bool(os.environ.get(entry[3], ""))


# ── Hybrid Router (local vs cloud) ───────────────────────────────────
# JARVIS analisa dificuldade da tarefa e decide: local (simples/moderado)
# vs cloud (hard/expert). Princípio: local primeiro para economia/privacidade;
# cloud só quando a tarefa EXIGE raciocínio pesado que o 4B/8B não entrega.
# Integrado via select_model_for_task → o churno único continua valendo.

import re

# Heurísticas de dificuldade (simples, sem chamadas API — rápido).
# Sinais de HARD: raciocínio multi-etapa, debugging complexo, arquitetura,
# análise matemática, código longo/multi-arquivo, comparação de paradigmas.
# Patterns usam prefixos (\w*) p/ capturar variações PT/EN (refatorar, debugar).
_HARD_PATTERNS = [
    r"\b(refactor|refator\w*|redesen\w*|redesign|arquitetura|architecture)\b",
    r"\b(debug\w*|diagnóstic\w*|diagnostic\w*|root.?cause)\b",
    r"\b(prov\w*|demonstr\w*|formal\w*|teorema|theorem|lemma|corolário)\b",
    r"\b(algoritmo|algorithm|complexidade|complexity|big.?o)\b",
    r"\b(multi.?step|multi.?file|multi.?arquivo|cross.?cutting|end.?to.?end)\b",
    r"\b(otimiz\w*|optimiz\w*|performance|benchmark|profil\w*)\b",
    r"\b(security|segurança|vulnerabilidade|cve|exploit|pentest|injection)\b",
    r"\b(concurrent|concorrência|concorrent\w*|deadlock|race.?condition|thread.?safe)\b",
    r"\b(machine.?learning|deep.?learning|neural|gradient|backprop|rede neural)\b",
    r"\b(compile\w*|compiler|linker|assembly|bytecode|jit|interpreter)\b",
    r"\b(distributed|distributed.?system|consensus|raft|paxos|quorum|distribuíd\w*)\b",
    r"\b(phylogen|evolution|selection.?pressure|fitness.?landscape|algoritmo genético)\b",
    r"\b(improve|melhore|enhance|optimize|refine).{0,40}(strategy|estratégia|algorithm|algoritmo)\b",
    r"\b(analis\w*|analys\w*|avali\w*|evaluat\w*).{0,30}(complexidade|complexity|performance|eficiência)\b",
    r"\b(implement\w*|constru\w*|desenv\w*|develop).{0,40}(algoritmo|algorithm|sistema|system|arquitetura|architecture)\b",
    r"\b(refator\w*|migr\w*|transform\w*|conver\w*).{0,40}(módulo|module|sistema|system|base de dados|database)\b",
]

# Sinais de SIMPLES: perguntas diretas, código curto, explicação, formatação.
_SIMPLE_PATTERNS = [
    r"^(o que|what is|qual|which|quem|who|quando|when|onde|where|como|how)\b",
    r"\b(explique|explain|defina|define|liste|list|resuma|summarize|descreva|describe)\b",
    r"\b(conserte|fix|corrija|correct|mude|change|adicione|add|remova|remove|delete)\b.{0,30}\b(tipo|type|typo|spelling|indent|format|comment|comentário)\b",
    r"\b(renomeie|rename|mova|move|copie|copy|delete|remova|remove)\b.{0,40}\b(file|arquivo|line|linha|function|função)\b",
    r"\b(teste|test|unit.?test|integration.?test)\b.{0,30}\b(para|for|de|of)\b",
    r"\b(mostrue|show|exiba|display|print|imprima|imprimir)\b",
    r"\b(qual|which|onde|where|quando|when)\b.{0,30}\b(está|is|fica|located|vive)\b",
]


def classify_difficulty(prompt: str, context_len: int = 0) -> str:
    """Classifica dificuldade da tarefa: 'simple'|'moderate'|'hard'.

    Heurística rápida (regex + heurísticas de tamanho). Não substitui
    julgamento humano, mas separa bem: simples = pergunta direta/explicação;
    hard = raciocínio multi-etapa/debugging/arquitetura. moderate = default.
    """
    if not prompt or not prompt.strip():
        return "simple"

    text = prompt.lower()

    # Contagem de sinais
    hard_hits = sum(1 for p in _HARD_PATTERNS if re.search(p, text))
    simple_hits = sum(1 for p in _SIMPLE_PATTERNS if re.search(p, text))

    # Ajuste por tamanho: prompts muito longos tendem a ser mais complexos
    if context_len > 10000 or len(text) > 2000:
        hard_hits += 1
    elif len(text) < 100:
        simple_hits += 1

    # Múltiplos hard signals → hard
    if hard_hits >= 2:
        return "hard"
    # 1 hard + 0 simple → moderate (cuidado: pode ser hard disfarçado)
    if hard_hits == 1 and simple_hits == 0:
        return "moderate"
    # Só sinais de simples → simple
    if simple_hits > hard_hits:
        return "simple"
    # Default: moderate (local resolve bem)
    return "moderate"


# Cloud providers que FUNCIONAM hoje (fonte única: free-providers.json).
# Ordem vem do cascade_layers.dev no JSON — testado ao vivo 28/10.
# Mantido como fallback se o JSON não carregar.
_HYBRID_CLOUD_FALLBACK = [
    ("groq", "openai/gpt-oss-120b", "https://api.groq.com/openai", "GROQ_API_KEY"),
    ("groq", "qwen/qwen3.8-27b", "https://api.groq.com/openai", "GROQ_API_KEY"),
    ("cloudflare", "@cf/openai/gpt-oss-120b", "https://api.cloudflare.com/client/v4/accounts", "CLOUDFLARE_API_TOKEN"),
    ("openrouter", "nvidia/nemotron-3.5-lightning:free", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
]

# Construído do JSON (fonte única). Usa cascade_layers.dev como fila.
_HYBRID_CLOUD = CASCADE_MAP.get("dev", _HYBRID_CLOUD_FALLBACK)


def hybrid_route(
    prompt: str,
    *,
    local_requirements: dict | None = None,
    context_len: int = 0,
    force_local: bool = False,
    force_cloud: bool = False,
) -> dict:
    """Roteamento híbrido: decide local vs cloud por dificuldade.

    Retorna dict com:
      - target: "local" | "cloud"
      - local_model: id do modelo local (se target=local)
      - cloud_entry: (provider, model, base_url, env_key) (se target=cloud)
      - difficulty: "simple"|"moderate"|"hard"
      - reason: explicação da decisão

    Regras:
      1. force_local/force_cloud têm precedência máxima.
      2. difficulty=hard → cloud (se key disponível); senão fallback local.
      3. difficulty=simple|moderate → local (economia/privacidade).
    """
    from jarvis.core.model_policy import select_model

    req = local_requirements or {}
    difficulty = classify_difficulty(prompt, context_len)

    # Forced overrides
    if force_cloud:
        for entry in _HYBRID_CLOUD:
            if cascade_key_present(entry):
                return {
                    "target": "cloud",
                    "cloud_entry": entry,
                    "difficulty": difficulty,
                    "reason": "force_cloud=True",
                }
        # Sem key → cai pra local
        difficulty = difficulty  # mantém

    if force_local or difficulty in ("simple", "moderate"):
        try:
            model_id, reason = select_model(req)
        except ModelRouteError:
            # Sem modelo local elegível → tenta cloud se hard
            if difficulty == "hard":
                for entry in _HYBRID_CLOUD:
                    if cascade_key_present(entry):
                        return {
                            "target": "cloud",
                            "cloud_entry": entry,
                            "difficulty": difficulty,
                            "reason": "no_local_model_hard",
                        }
            raise
        return {
            "target": "local",
            "local_model": model_id,
            "difficulty": difficulty,
            "reason": f"local (difficulty={difficulty})",
        }

    # difficulty == "hard" → cloud primeiro
    for entry in _HYBRID_CLOUD:
        if cascade_key_present(entry):
            return {
                "target": "cloud",
                "cloud_entry": entry,
                "difficulty": difficulty,
                "reason": f"cloud (difficulty={difficulty})",
            }

    # Hard mas sem key cloud → fallback local (melhor que nada)
    try:
        model_id, reason = select_model(req)
        return {
            "target": "local",
            "local_model": model_id,
            "difficulty": difficulty,
            "reason": "local (hard but no cloud key)",
        }
    except ModelRouteError:
        raise ModelRouteError(
            f"hybrid: difficulty={difficulty}, no local model, no cloud key"
        )
