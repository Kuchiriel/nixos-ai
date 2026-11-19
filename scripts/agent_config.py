#!/usr/bin/env python3
"""
agent_config.py — configuração centralizada da frota JARVIS.

Todos os scripts devem importar deste módulo em vez de hardcodear
portas, URLs e caminhos. Exemplo:

    from agent_config import PORTA_OPencode, URL_HUB, CAMINHO_ROSTER
    # ou
    cfg = AgentConfig()
    print(cfg.servicos["agent_hub"].url)

O arquivo fonte é scripts/agent-config.json (editável sem tocar código).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(
    os.environ.get(
        "AGENT_CONFIG_PATH",
        "/home/nixos/projects/nixos-ai/scripts/agent-config.json",
    )
)


@dataclass
class Servico:
    porta: int
    host: str
    descricao: str

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.porta}"

    @property
    def url_v1(self) -> str:
        return f"{self.url}/v1"


@dataclass
class AgentConfig:
    versao: int
    host: dict[str, str]
    servicos: dict[str, Servico] = field(default_factory=dict)
    caminhos: dict[str, str] = field(default_factory=dict)
    bus: dict[str, Any] = field(default_factory=dict)
    ambiente: dict[str, str] = field(default_factory=dict)

    @classmethod
    def carregar(cls, caminho: Path | str | None = None) -> "AgentConfig":
        p = Path(caminho) if caminho else DEFAULT_CONFIG_PATH
        if not p.exists():
            raise FileNotFoundError(f"agent-config.json não encontrado: {p}")
        raw = json.loads(p.read_text(encoding="utf-8"))
        servicos = {
            nome: Servico(
                porta=s["porta"],
                host=s.get("host", "127.0.0.1"),
                descricao=s.get("descricao", ""),
            )
            for nome, s in raw.get("servicos", {}).items()
        }
        return cls(
            versao=raw.get("versao", 1),
            host=raw.get("host", {}),
            servicos=servicos,
            caminhos=raw.get("caminhos", {}),
            bus=raw.get("bus", {}),
            ambiente=raw.get("ambiente", {}),
        )

    # ── atalhos úteis ──────────────────────────────────────────────

    def url(self, servico: str) -> str:
        return self.servicos[servico].url

    def porta(self, servico: str) -> int:
        return self.servicos[servico].porta

    def caminho(self, chave: str) -> str:
        return self.caminhos[chave]

    def env(self, chave: str) -> str:
        return self.ambiente[chave]

    # compatibilidade com nomes de variáveis antigas (hardcoded)
    @property
    def OC_URL(self) -> str:
        return self.ambiente.get("AGENTS_OC_URL", "http://127.0.0.1:4599")

    @property
    def HUB_URL(self) -> str:
        return self.ambiente.get("AGENT_HUB_URL", "http://127.0.0.1:8091")

    @property
    def COORD_URL(self) -> str:
        return self.ambiente.get("COORD_MCP_URL", "http://127.0.0.1:8765/mcp")

    @property
    def ROSTER_PATH(self) -> str:
        return self.caminhos.get("roster_json", "/home/nixos/projects/.agents/roster.json")

    @property
    def STATE_DIR(self) -> str:
        return self.caminhos.get("state_dir", "/home/nixos/.local/state/jarvis")

    @property
    def LOGS_DIR(self) -> str:
        return self.caminhos.get("logs_dir", "/home/nixos/logs")

    @property
    def HUB_TOKEN_PATH(self) -> str:
        return self.caminhos.get("agent_hub_token", "/home/nixos/.config/opencode/agent-hub.token")


# Instância singleton (carregada na primeira importação)
_cfg: AgentConfig | None = None


def carregar(caminho: Path | str | None = None) -> AgentConfig:
    global _cfg
    _cfg = AgentConfig.carregar(caminho)
    return _cfg


def cfg() -> AgentConfig:
    global _cfg
    if _cfg is None:
        _cfg = AgentConfig.carregar()
    return _cfg


# Atalhos de módulo (para import direto: from agent_config import PORTA_HUB)
def _atalhos() -> dict[str, Any]:
    c = cfg()
    return {
        "PORTA_OPCODE_SERVE": c.porta("opencode_serve"),
        "PORTA_AGENT_HUB": c.porta("agent_hub"),
        "PORTA_JARVIS_WEBUI": c.porta("jarvis_webui"),
        "PORTA_COORD_MCP": c.porta("coord_mcp"),
        "PORTA_LLAMA_ROUTER": c.porta("llama_router"),
        "PORTA_EMBEDDINGS": c.porta("embeddings"),
        "PORTA_RERANK": c.porta("rerank"),
        "PORTA_QDRANT": c.porta("qdrant"),
        "PORTA_VOZ_DUPLEX": c.porta("voz_duplex"),
        "URL_OPCODE_SERVE": c.url("opencode_serve"),
        "URL_AGENT_HUB": c.url("agent_hub"),
        "URL_JARVIS_WEBUI": c.url("jarvis_webui"),
        "URL_COORD_MCP": c.url("coord_mcp"),
        "URL_LLAMA_ROUTER": c.url("llama_router"),
        "CAMINHO_ROSTER": c.caminho("roster_json"),
        "CAMINHO_STATE": c.caminho("state_dir"),
        "CAMINHO_LOGS": c.caminho("logs_dir"),
        "CAMINHO_HUB_TOKEN": c.caminho("agent_hub_token"),
        "BUS_REPO": c.bus.get("repo", "Kuchiriel/mt5"),
        "BUS_ISSUE": c.bus.get("issue", 12),
    }


# Carrega automaticamente na importação e expõe atalhos como variáveis de módulo
try:
    _c = carregar()
    for _nome, _valor in _atalhos().items():
        globals()[_nome] = _valor
except Exception:
    # Se não conseguir carregar, os atalhos não funcionarão até carregar()
    pass
