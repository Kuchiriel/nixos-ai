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


# ── (03/11) Defaults derivados do REGISTRY (models.nix) ──────────────────
# O registry JSON (/etc/jarvis/model-registry.json) é a fonte única de
# default/portas. Sem ele (dev/test), caem nos literais de fallback — os
# mesmos valores do registry, escritos uma vez aqui.
_REGISTRY_CACHE: dict = {}


def _registry():
    """Registry carregado uma vez (None se indisponível)."""
    if "reg" not in _REGISTRY_CACHE:
        try:
            from jarvis.core.model_registry import ModelRegistry
            _REGISTRY_CACHE["reg"] = ModelRegistry.load()
        except Exception:
            _REGISTRY_CACHE["reg"] = None
    return _REGISTRY_CACHE["reg"]


def _registry_default_model() -> str:
    reg = _registry()
    return reg.default if reg else "jarvis-mtp-lora"


def _registry_default_base_url() -> str:
    reg = _registry()
    if reg:
        url = reg.base_url_for(reg.default)
        if url and not url.endswith(":0"):
            return f"{url}/v1"
    return "http://127.0.0.1:8092/v1"


def _registry_service_url(name: str, fallback: str) -> str:
    reg = _registry()
    if reg:
        port = reg.service_port(name)
        if port:
            return f"http://127.0.0.1:{port}"
    return fallback


@dataclass(frozen=True)
class Config:
    # --- Personas custom (painel de bots, 07/10): JSONs aqui viram personas
    # sem editar código (PersonaRegistry._load_from_dir). Painel = escrever
    # arquivo; formato = Persona.to_dict().
    personas_dir: str = field(default_factory=lambda: _env_str(
        "JARVIS_PERSONAS_DIR",
        os.path.join(os.path.expanduser("~"), ".config", "jarvis", "personas")))
    # --- Backend Selection ---
    # Which LLM backend to use: "llama-cpp", "prismml", "bonsai", etc.
    llm_backend: str = field(default_factory=lambda: _env_str("JARVIS_LLM_BACKEND", "llama-cpp"))
    
    # --- LLM (llama.cpp / OpenAI-compatible) ---
    # (26/10, dono) DEFAULT = Qwen3.5-4B-MTP **com o LoRA** (:8092, stock).
    # Antes: :8080/v1 + model "default" → router prism → bonsai (8B ternário,
    # EN-only, sem PT). Motivo: (a) o classificador de turno do duplex
    # (RESPOND/WAIT/SILENCE/BARGE) É o LoRA — medido: LoRA ON 4/4, LoRA OFF
    # o base nem classifica ("Thinking Pro"); (b) PT-BR de verdade.
    # O id = alias do server (medido: com --alias o /v1/models anuncia o
    # alias; sem ele anuncia o path do gguf → ensure_model não prova
    # identidade). Fallback antigo via env: JARVIS_LLM_BASE_URL=...:8080/v1.
    llm_base_url: str = field(default_factory=lambda: _env_str("JARVIS_LLM_BASE_URL", _registry_default_base_url()))
    llm_model: str = field(default_factory=lambda: _env_str("JARVIS_LLM_MODEL", _registry_default_model()))
    llm_timeout: int = field(default_factory=lambda: _env_int("JARVIS_LLM_TIMEOUT", 120))
    # Thinking / reasoning enabled by default on GPU hardware (Bonsai/Qwen3)
    llm_disable_thinking: bool = field(default_factory=lambda: _env_str("JARVIS_LLM_DISABLE_THINKING", "0") == "1")
    # Tool calling support (True for llama.cpp with jinja, False for simpler backends)
    llm_tool_calling: bool = field(default_factory=lambda: _env_bool("JARVIS_LLM_TOOL_CALLING", True))
    # Temperatura: -1 = AUTO por modelo (24/09). Medido: o bonsai (ternário
    # Q2_0) é determinístico e MELHOR a temp 0 (12/12 no harness); já
    # modelos denso-comuns (ex.: Qwen 4B) caem em repetição/loop a temp 0 —
    # para eles o auto usa 0.7. Override explícito sempre manda.
    llm_temperature: float = field(default_factory=lambda: float(_env_str("JARVIS_LLM_TEMPERATURE", "-1")))

    # --- Embeddings (servidor dedicado llama.cpp --embeddings, porta 8081) ---
    embed_base_url: str = field(default_factory=lambda: _env_str("JARVIS_EMBED_BASE_URL", _registry_service_url("embeddings", "http://127.0.0.1:8081/v1")))

    # --- Reranker (servidor dedicado llama.cpp --rerank, porta 8082 — Fase 10) ---
    # Endpoint /rerank do llama-server (bge-reranker-v2-m3 GGUF do store).
    rerank_base_url: str = field(default_factory=lambda: _env_str("JARVIS_RERANK_BASE_URL", _registry_service_url("rerank", "http://127.0.0.1:8082")))

    # --- Qdrant ---
    qdrant_url: str = field(default_factory=lambda: _env_str("JARVIS_QDRANT_URL", "http://127.0.0.1:6333"))
    # Chave do Qdrant em arquivo (24/09): self-hosted sem api_key deixa
    # qualquer processo local ler/escrever qualquer coleção. O arquivo é
    # root/nixos 600 fora do repo — a chave nunca vai pro git nem pro env.
    qdrant_api_key_file: str = field(default_factory=lambda: _env_str("JARVIS_QDRANT_API_KEY_FILE", ""))

    # --- Estado da aplicação (separado da config NixOS) ---
    state_dir: Path = field(default_factory=lambda: Path(_env_str("JARVIS_STATE_DIR", "~/.local/state/jarvis")).expanduser())
    # --- Vault de memória de longo prazo (markdown git-syncado, estilo m3ta-brain) ---
    vault_dir: Path = field(default_factory=lambda: Path(_env_str("JARVIS_VAULT_DIR", "~/.local/state/jarvis/vault")).expanduser())

    # --- Canal Telegram (Fase 9 — aprovação assíncrona) ---
    # Token e chat_ids vêm do EnvironmentFile do serviço (/etc/jarvis-telegram.env)
    # — nunca no repo/store. chat_id pode ser uma lista separada por vírgula.
    telegram_token: str = field(default_factory=lambda: _env_str("JARVIS_TELEGRAM_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: _env_str("JARVIS_TELEGRAM_CHAT_ID", ""))
    # Sender allowlist (comma-separated). Empty = chat_id alone decides, which
    # is UNSAFE in a group chat: anyone in that group would be authorized.
    # Set it whenever the bot is added to a group.
    telegram_user_id: str = field(default_factory=lambda: _env_str("JARVIS_TELEGRAM_USER_ID", ""))

    # --- Embeddings ---
    embed_model: str = field(default_factory=lambda: _env_str("JARVIS_EMBED_MODEL", "nomic-embed-text-v2"))
    embed_dim: int = field(default_factory=lambda: _env_int("JARVIS_EMBED_DIM", 768))

    # --- Coleções Qdrant ---
    qdrant_collection_code: str = field(default_factory=lambda: _env_str("JARVIS_QDRANT_COLLECTION_CODE", "code_index"))
    qdrant_collection_memories: str = field(default_factory=lambda: _env_str("JARVIS_QDRANT_COLLECTION_MEMORIES", "memories"))
    qdrant_collection_books: str = field(default_factory=lambda: _env_str("JARVIS_QDRANT_COLLECTION_BOOKS", "books"))
    # Vault = memória escrita-pelo-agente (filesystem). Indexada em coleção
    # PRÓPRIA, nunca misturada com books/code: um índice para "corpus que
    # você não escreveu" (RAG) e outro para "o que o agente escreveu"
    # (memória) — são trabalhos diferentes (padrão de mercado 2026).
    qdrant_collection_vault: str = field(default_factory=lambda: _env_str("JARVIS_QDRANT_COLLECTION_VAULT", "vault"))

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
    # 23/09: expandido com artefatos ÓBVIOS de build/cache/deps (mesma lista
    # dos templates .gitignore de mercado). Match é por SUBSTRING no nome do
    # dir — por isso NÃO entram tokens largos tipo "log" (pegaria "catalogs"),
    # "bin", "obj", "env", "data". Dirs ocultos (.* ) já são podados no walk.
    # Por-PROJETO: use .ragignore (sintaxe gitignore; ver rag.py).
    index_exclude_dirs: tuple[str, ...] = field(default_factory=lambda: tuple(
        d for d in _env_str(
            "JARVIS_INDEX_EXCLUDE_DIRS",
            "git,node_modules,pycache,backup,temp,venv,site-packages,dist,target,vendor,.idea,.vscode,build,result,.direnv,"
            "cache,tmp,coverage,htmlcov,egg-info,gradle,cmake,bower_components,jspm_packages,elm-stuff,_build,deps,DerivedData",
        ).split(",") if d
    ))

    def ensure_state_dir(self) -> Path:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        return self.state_dir


def get_config() -> Config:
    """Retorna a config única (env-driven)."""
    return Config()
