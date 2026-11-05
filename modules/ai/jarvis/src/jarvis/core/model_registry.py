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
    # (26/10) Default = Qwen3.5-4B-MTP + LoRA micro-turn (:8092, stock).
    # Espelha models.nix `routing.default`. Antes era "bonsai" (EN-only).
    "default": "jarvis-mtp-lora",
    "maxResident": 1,
    # (03/11) Estrutura nova (paridade com o JSON gerado pelo Nix):
    # endpoints por grupo do router, portas dos serviços auxiliares e a
    # unit systemd que serve cada model id.
    "endpoints": {"prism": 8080, "upstream": 8083, "ik": 8084},
    "servicePorts": {"embeddings": 8081, "rerank": 8082},
    "bootModel": {"host": "bonsai", "vm": "jarvis-fast"},
    "units": {},
    # (03/11) Espelho de models.nix `routing.directServers` (porta + unit).
    "directServers": {
        "uncensored-35b": {"endpoint": 8084, "unit": "llama-uncensored-35b"},
        "duplex-35b": {"endpoint": 8085, "unit": "llama-duplex-35b"},
        "uncensored-4b": {"endpoint": 8092, "unit": "llama-uncensored-4b"},
        # (05/11) 8094: 8085 era compartilhada com duplex-35b (models.nix) —
        # as units se conflitavam. Espelha o registry gerado pelo Nix.
        "deepseek-7b": {"endpoint": 8094, "unit": "llama-deepseek-7b"},
        "xlam-8b": {"endpoint": 8089, "unit": "llama-xlam-8b"},
        "phi-mini": {"endpoint": 8086, "unit": "llama-phi-mini"},
        "gemma-4b": {"endpoint": 8087, "unit": "llama-gemma-4b"},
        "qwen30b-moe": {"endpoint": 8091, "unit": "llama-qwen30b-moe"},
        "uncensored-35b-q4kp": {"endpoint": 8093, "unit": "llama-uncensored-35b-q4kp"},
    },
    "models": {
        "jarvis-mtp-lora": {
            "tier": "fast",
            "capabilities": ["general", "coding", "tools", "pt", "uncensored", "lora"],
            "params_b": 4,
            "vram_mb": 4474,
            "endpoint": 8092,
            "unit": "llama-uncensored-4b",
            "sampling": {"temperature": 0.7, "top_p": 0.8, "top_k": 20,
                         "min_p": 0.0, "presence_penalty": 1.5,
                         "repetition_penalty": 1.0},
            "guidance": "DEFAULT: PT-BR + classificador de turno (LoRA)",
        },
        "bonsai": {
            "tier": "speed",
            "capabilities": ["general", "coding", "tools", "en"],
            "params_b": 8,
            "vram_mb": 2400,
            "endpoint": 8080,
            "unit": "llama-cpp-server",
            "sampling": {"temperature": 0.5, "top_p": 0.9, "top_k": 20,
                         "min_p": 0.0, "presence_penalty": 0.0,
                         "repetition_penalty": 1.0},
            # Espelho do guidance em models.nix (SEM pt desde 07/10).
            "guidance": "speed/code/English first; NEVER answer in Brazilian Portuguese here; Brazilian Portuguese goes to the fast tier",
        },
        "jarvis-fast": {
            "tier": "fast",
            "capabilities": ["general", "coding", "tools", "pt"],
            "params_b": 4,
            "vram_mb": 2600,
            "endpoint": 8083,
            "unit": "llama-cpp-upstream",
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
            "unit": "llama-cpp-ik",
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
            "unit": "llama-cpp-upstream",
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
            "unit": "llama-cpp-ik",
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
    # (03/11) Estrutura vinda do mesmo JSON (models.nix): portas dos grupos
    # do router, dos serviços auxiliares e a unit systemd por model id.
    endpoints: dict[str, int] = field(default_factory=dict)
    service_ports: dict[str, int] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)
    # (03/11) Servidores DIRETOS (não são tiers): {nome: {endpoint, unit}}.
    # Derivado de models.nix `directServers` — o heal usa p/ descobrir a
    # unit que serve uma porta sem hardcode.
    direct_servers: dict[str, dict] = field(default_factory=dict)

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
        # (03/11) Portas dos grupos do router — o fallback de `endpoint` vem
        # daqui (NÃO de um literal 8080 no código).
        endpoints = {
            str(k): int(v)
            for k, v in (data.get("endpoints") or {}).items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        service_ports = {
            str(k): int(v)
            for k, v in (data.get("servicePorts") or {}).items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        units = {
            str(k): str(v)
            for k, v in (data.get("units") or {}).items()
            if isinstance(v, dict) and v.get("unit")
        }
        direct_servers = {
            str(k): {"endpoint": int(v.get("endpoint") or 0),
                     "unit": str(v.get("unit") or "")}
            for k, v in (data.get("directServers") or {}).items()
            if isinstance(v, dict)
        }
        # (03/11) Chaves NOVAS podem faltar num registry JSON ANTIGO (gerado
        # antes do rebuild) → completa com o fallback embutido (o Nix é a
        # fonte; o fallback só evita quebrar o heal/doctor nesse meio-tempo).
        if not service_ports:
            service_ports = {
                str(k): int(v)
                for k, v in (_FALLBACK.get("servicePorts") or {}).items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
        if not direct_servers:
            direct_servers = {
                str(k): {"endpoint": int(v.get("endpoint") or 0),
                         "unit": str(v.get("unit") or "")}
                for k, v in (_FALLBACK.get("directServers") or {}).items()
                if isinstance(v, dict)
            }
        # (03/11) Fallback do endpoint: 1) o próprio modelo; 2) a porta do
        # grupo prism declarada no registry; 3) o literal 8080 (default do
        # router — contrato do test_registry_endpoint_defaults_8080).
        fallback_endpoint = endpoints.get("prism", 8080)
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
                endpoint=int(m.get("endpoint") or fallback_endpoint or 0),
                sampling=dict(m.get("sampling", {}) or {}),
                raw=m,
            )
        default = str(data.get("default", ""))
        if default not in models:
            raise RegistryError(f"default {default!r} fora do registry ({source})")
        return cls(models=models, default=default,
                   max_resident=int(data.get("maxResident", 1) or 1),
                   source=source,
                   endpoints=endpoints,
                   service_ports=service_ports,
                   units=units,
                   direct_servers=direct_servers)

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

    # ── (03/11) PORTAS/UNITS: fonte única = registry JSON (models.nix) ──
    def port_for(self, model_id: str) -> int:
        """Porta do server que serve o modelo (0 = desconhecida)."""
        try:
            return int(self.get(model_id).endpoint or 0)
        except RegistryError:
            return 0

    def base_url_for(self, model_id: str) -> str:
        """Base URL OpenAI-compatible do server que serve o modelo."""
        return f"http://127.0.0.1:{self.port_for(model_id)}"

    def service_port(self, name: str) -> int | None:
        """Porta de um serviço auxiliar (embeddings|rerank). None se ausente."""
        value = self.service_ports.get(name)
        return int(value) if value else None

    def router_port(self, binary: str = "prism") -> int | None:
        """Porta do grupo do router para um binário (prism|upstream|ik)."""
        value = self.endpoints.get(binary)
        return int(value) if value else None

    def unit_for(self, model_id: str) -> str | None:
        """Unit systemd que serve o modelo (None se não declarada)."""
        entry = self.models.get(model_id)
        if entry is not None:
            unit = entry.raw.get("unit")
            if unit:
                return str(unit)
        unit = self.units.get(model_id)
        return str(unit) if unit else None

    def direct_units(self) -> dict[str, int]:
        """unit systemd -> porta dos servidores DIRETOS (registry)."""
        out: dict[str, int] = {}
        for info in self.direct_servers.values():
            unit = info.get("unit")
            port = info.get("endpoint")
            if unit and port:
                out[str(unit)] = int(port)
        return out

    def port_units(self) -> dict[str, str]:
        """porta -> unit systemd (direct servers têm precedência sobre o
        grupo do router na mesma porta)."""
        out: dict[str, str] = {}
        for mid, entry in self.models.items():
            unit = entry.raw.get("unit")
            if unit and entry.endpoint:
                out[str(entry.endpoint)] = str(unit)
        for unit, port in self.direct_units().items():
            out[str(port)] = unit
        return out


# ── (03/11) API de módulo: registry em cache + URLs derivadas ──
_REGISTRY_CACHE: "ModelRegistry | None" = None
_REGISTRY_LOADED = False


def load_registry(path: str | Path | None = None) -> ModelRegistry:
    """Registry vivo (cacheado por processo; env > /etc > fallback)."""
    global _REGISTRY_CACHE, _REGISTRY_LOADED
    if path is None and _REGISTRY_LOADED:
        return _REGISTRY_CACHE  # type: ignore[return-value]
    reg = ModelRegistry.load(path)
    if path is None:
        _REGISTRY_CACHE = reg
        _REGISTRY_LOADED = True
    return reg


def registry_or_none() -> ModelRegistry | None:
    """Registry ou None (nunca levanta)."""
    try:
        return load_registry()
    except Exception:
        return None


def default_base_url(suffix: str = "") -> str:
    """URL do server que serve o modelo DEFAULT (registry)."""
    reg = registry_or_none()
    if reg is not None:
        url = reg.base_url_for(reg.default)
        if url and not url.endswith(":0"):
            return f"{url}{suffix}"
    return f"http://127.0.0.1:8092{suffix}"


def router_port() -> int:
    """Porta do router (grupo prism)."""
    reg = registry_or_none()
    if reg is not None:
        port = reg.router_port("prism")
        if port:
            return int(port)
    return 8080


def router_base_url(suffix: str = "") -> str:
    """URL do router (grupo prism)."""
    return f"http://127.0.0.1:{router_port()}{suffix}"
