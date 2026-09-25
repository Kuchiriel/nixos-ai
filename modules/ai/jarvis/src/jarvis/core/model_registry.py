"""Model Registry — fonte de runtime derivada de modules/ai/models.nix.

ÚNICA FONTE: /etc/jarvis/model-registry.json (gerado pelo Nix via
`builtins.toJSON routing`; override: JARVIS_MODEL_REGISTRY).
NADA de dict Python espelhando metadata de modelos — este módulo só
carrega, valida e consulta.

Fallback embutido (_FALLBACK): usado apenas quando o JSON inexiste
(dev sem NixOS instalado, testes de policy). Ele espelha a ESTRUTURA,
não os dados — qualquer divergência de conteúdo aparece nos testes de
paridade quando o JSON existe.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

REGISTRY_ENV = "JARVIS_MODEL_REGISTRY"
REGISTRY_DEFAULT_PATH = "/etc/jarvis/model-registry.json"
REGISTRY_VERSION = 1

# Estrutura mínima p/ operar sem o JSON (dev/test). Conteúdo pode divergir;
# o que importa é o contrato (tiers/capabilities) usado pela policy.
_FALLBACK = {
    "version": 1,
    "default": "bonsai",
    "maxResident": 1,
    "models": {
        "bonsai": {
            "tier": "speed",
            "capabilities": ["general", "coding", "tools", "pt"],
            "params_b": 8,
            "vram_mb": 2400,
            "endpoint": 8080,
            "sampling": {"temperature": 0.5, "top_p": 0.9, "top_k": 20,
                         "min_p": 0.0, "presence_penalty": 0.0,
                         "repetition_penalty": 1.0},
        },
        "jarvis-fast": {
            "tier": "fast",
            "capabilities": ["general", "coding", "tools", "pt"],
            "params_b": 4,
            "vram_mb": 2600,
            "endpoint": 8083,
            "sampling": {"temperature": 0.7, "top_p": 0.8, "top_k": 20,
                         "min_p": 0.0, "presence_penalty": 1.5,
                         "repetition_penalty": 1.0},
        },
        "jarvis-strong": {
            "tier": "reasoning",
            "capabilities": ["general", "coding", "tools", "reasoning", "analysis", "vision", "pt"],
            "params_b": 35,
            "vram_mb": 4600,
            "endpoint": 8084,
            "sampling": {"temperature": 1.0, "top_p": 0.95, "top_k": 20,
                         "min_p": 0.0, "presence_penalty": 1.5,
                         "repetition_penalty": 1.0},
        },
        "jarvis-raw": {
            "tier": "fast",
            "capabilities": ["general", "coding", "tools", "pt", "uncensored"],
            "params_b": 4,
            "vram_mb": 2700,
            "endpoint": 8083,
            "sampling": {"temperature": 0.7, "top_p": 0.8, "top_k": 20,
                         "min_p": 0.0, "presence_penalty": 1.5,
                         "repetition_penalty": 1.0},
        },
        "jarvis-raw-strong": {
            "tier": "reasoning",
            "capabilities": ["general", "coding", "tools", "reasoning", "analysis", "pt", "uncensored"],
            "params_b": 35,
            "vram_mb": 4600,
            "endpoint": 8084,
            "sampling": {"temperature": 1.0, "top_p": 0.95, "top_k": 20,
                         "min_p": 0.0, "presence_penalty": 1.5,
                         "repetition_penalty": 1.0},
        },
    },
}


class RegistryError(ValueError):
    """Registry ausente ou inválido."""


@dataclass
class ModelEntry:
    id: str
    tier: str
    capabilities: frozenset = field(default_factory=frozenset)
    params_b: float = 0
    vram_mb: int = 0
    # Porta do serviço que roda o BINÁRIO CERTO p/ este modelo
    # (models.nix `routing.endpoints`; docs/models/BINARIES.md).
    endpoint: int = 8080
    # Defaults de geração — ÚNICA FONTE: models.nix `routing.models.<id>.sampling`.
    sampling: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


@dataclass
class ModelRegistry:
    """Registro de modelos servíveis pelo router llama-server (:8080)."""

    models: dict[str, ModelEntry]
    default: str
    max_resident: int = 1
    source: str = ""

    @classmethod
    def load(cls, path: str | Path | None = None) -> "ModelRegistry":
        """Carrega do JSON gerado (env > default path > fallback)."""
        src = str(path or os.environ.get(REGISTRY_ENV, REGISTRY_DEFAULT_PATH))
        data: dict | None = None
        try:
            data = json.loads(Path(src).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        from_fallback = data is None
        if from_fallback:
            import logging
            logging.getLogger(__name__).warning(
                "model registry ausente (%s) — usando fallback embutido; "
                "instale /etc/jarvis/model-registry.json via NixOS", src)
            data = _FALLBACK
        return cls._validate(data, source="fallback" if from_fallback else src)

    @classmethod
    def _validate(cls, data: dict, source: str = "") -> "ModelRegistry":
        if not isinstance(data, dict):
            raise RegistryError(f"registry inválido em {source}: raiz não é objeto")
        if data.get("version") != REGISTRY_VERSION:
            raise RegistryError(
                f"registry versão {data.get('version')} != {REGISTRY_VERSION} ({source})"
            )
        raw_models = data.get("models")
        if not isinstance(raw_models, dict) or not raw_models:
            raise RegistryError(f"registry sem models ({source})")
        models: dict[str, ModelEntry] = {}
        for mid, m in raw_models.items():
            if not isinstance(m, dict):
                raise RegistryError(f"modelo {mid!r} inválido ({source})")
            if mid in models:
                raise RegistryError(f"modelo duplicado: {mid!r} ({source})")
            caps = m.get("capabilities", [])
            if not isinstance(caps, list) or not caps:
                raise RegistryError(f"modelo {mid!r} sem capabilities ({source})")
            models[mid] = ModelEntry(
                id=mid,
                tier=str(m.get("tier", "")),
                capabilities=frozenset(caps),
                params_b=float(m.get("params_b", 0) or 0),
                vram_mb=int(m.get("vram_mb", 0) or 0),
                endpoint=int(m.get("endpoint", 8080) or 8080),
                sampling=dict(m.get("sampling", {}) or {}),
                raw=m,
            )
        default = str(data.get("default", ""))
        if default not in models:
            raise RegistryError(f"default {default!r} fora do registry ({source})")
        return cls(models=models, default=default,
                   max_resident=int(data.get("maxResident", 1) or 1),
                   source=source)

    def get(self, model_id: str) -> ModelEntry:
        try:
            return self.models[model_id]
        except KeyError:
            raise RegistryError(
                f"modelo {model_id!r} inexistente (registry: {self.source})"
            ) from None

    def ids(self) -> list[str]:
        return list(self.models)

    def sampling_for(self, model_id: str) -> dict:
        """Defaults de geração do modelo (models.nix `sampling`). Vazio se ausente."""
        try:
            return dict(self.get(model_id).sampling)
        except RegistryError:
            return {}
