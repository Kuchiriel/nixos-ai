"""Configuração central do JARVIS.

Toda configuração vem de variáveis de ambiente com defaults locais
(127.0.0.1) — nada de caminhos hardcoded do sistema. O estado de runtime
da aplicação fica fora da configuração declarativa do NixOS.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Config:
    # --- Backend Selection ---
    # Which LLM backend to use: "llama-cpp", "prismml", "bonsai", etc.
    llm_backend: str = field(default_factory=lambda: _env_str("JARVIS_LLM_BACKEND", "llama-cpp"))
    
    # --- LLM (llama.cpp / OpenAI-compatible) ---
    llm_base_url: str = field(default_factory=lambda: _env_str("JARVIS_LLM_BASE_URL", "http://127.0.0.1:8080/v1"))
    llm_model: str = field(default_factory=lambda: _env_str("JARVIS_LLM_MODEL", "default"))
    llm_timeout: int = field(default_factory=lambda: _env_int("JARVIS_LLM_TIMEOUT", 120))
    # Thinking / reasoning enabled by default on GPU hardware (Bonsai/Qwen3)
    llm_disable_thinking: bool = field(default_factory=lambda: _env_str("JARVIS_LLM_DISABLE_THINKING", "0") == "1")
    # Tool calling support (True for llama.cpp with jinja, False for simpler backends)
    llm_tool_calling: bool = field(default_factory=lambda: _env_bool("JARVIS_LLM_TOOL_CALLING", True))

    # --- Embeddings (servidor dedicado llama.cpp --embeddings, porta 8081) ---
    embed_base_url: str = field(default_factory=lambda: _env_str("JARVIS_EMBED_BASE_URL", "http://127.0.0.1:8081/v1"))

    # --- Reranker (servidor dedicado llama.cpp --rerank, porta 8082 — Fase 10) ---
    # Endpoint /rerank do llama-server (bge-reranker-v2-m3 GGUF do store).
    rerank_base_url: str = field(default_factory=lambda: _env_str("JARVIS_RERANK_BASE_URL", "http://127.0.0.1:8082"))

    # --- Qdrant ---
    qdrant_url: str = field(default_factory=lambda: _env_str("JARVIS_QDRANT_URL", "http://127.0.0.1:6333"))

    # --- Estado da aplicação (separado da config NixOS) ---
    state_dir: Path = field(default_factory=lambda: Path(_env_str("JARVIS_STATE_DIR", "~/.local/state/jarvis")).expanduser())
    # --- Vault de memória de longo prazo (markdown git-syncado, estilo m3ta-brain) ---
    vault_dir: Path = field(default_factory=lambda: Path(_env_str("JARVIS_VAULT_DIR", "~/.local/state/jarvis/vault")).expanduser())

    # --- Canal Telegram (Fase 9 — aprovação assíncrona) ---
    # Token e chat_ids vêm do EnvironmentFile do serviço (/etc/jarvis-telegram.env)
    # — nunca no repo/store. chat_id pode ser uma lista separada por vírgula.
    telegram_token: str = field(default_factory=lambda: _env_str("JARVIS_TELEGRAM_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: _env_str("JARVIS_TELEGRAM_CHAT_ID", ""))

    # --- Embeddings ---
    embed_model: str = field(default_factory=lambda: _env_str("JARVIS_EMBED_MODEL", "nomic-embed-text-v2"))
    embed_dim: int = field(default_factory=lambda: _env_int("JARVIS_EMBED_DIM", 768))

    # --- Coleções Qdrant ---
    qdrant_collection_code: str = field(default_factory=lambda: _env_str("JARVIS_QDRANT_COLLECTION_CODE", "code_index"))
    qdrant_collection_memories: str = field(default_factory=lambda: _env_str("JARVIS_QDRANT_COLLECTION_MEMORIES", "memories"))
    qdrant_collection_books: str = field(default_factory=lambda: _env_str("JARVIS_QDRANT_COLLECTION_BOOKS", "books"))

    # --- MCP (mcp-nixos: consulta real de packages/options do nixpkgs) ---
    # Binário do servidor MCP. Vem do propagatedBuildInputs (package.nix),
    # então no ambiente Nix `mcp-nixos` está no PATH.
    mcp_nixos_bin: str = field(default_factory=lambda: _env_str("JARVIS_MCP_NIXOS_BIN", "mcp-nixos"))

    # --- Indexação RAG ---
    # Tamanho do texto embebido por arquivo (rich_content). O legado usava 5000
    # chars; o nomic-embed-text-v2-moe GGUF tem ctx 2048, então o default é
    # reduzido para caber (~1450 tokens) — ajustável por env.
    rich_content_chars: int = field(default_factory=lambda: _env_int("JARVIS_RICH_CONTENT_CHARS", 3000))

    # --- Indexação (excludes de diretórios) ---
    # Corrigido vs legado: o default do V4.0.5 excluía "modules" (builds
    # CMake/otclient do jogo) — quebrava o index de repos NixOS, onde
    # "modules" é código. Removidos também os resquícios do jogo
    # (monster/world/items/npc/clientdata). Ajustável via JARVIS_INDEX_EXCLUDE_DIRS.
    index_exclude_dirs: tuple[str, ...] = field(default_factory=lambda: tuple(
        d for d in _env_str(
            "JARVIS_INDEX_EXCLUDE_DIRS",
            "git,node_modules,pycache,backup,temp,venv,site-packages,dist,target,vendor,.idea,.vscode,build,result,.direnv",
        ).split(",") if d
    ))

    def ensure_state_dir(self) -> Path:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        return self.state_dir


def get_config() -> Config:
    """Retorna a config única (env-driven)."""
    return Config()
