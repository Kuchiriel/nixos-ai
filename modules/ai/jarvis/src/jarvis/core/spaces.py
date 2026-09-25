"""Spaces — fronteiras de isolamento para o JARVIS (24/09).

Um *space* é um ambiente de contexto com identidade própria: state_dir
separado, vault cifrado com chave própria, coleções de RAG próprias,
raízes de leitura permitidas e uma política de provider (spaces
protegidos aceitam SÓ modelo local — nunca nuvem, que levaria o conteúdo
pra fora da máquina).

 inspired by: Global Agent Memory (Standard/Protected/Sealed, fail-closed,
 owner-granted access) e ProjectMemento (blob cifrado + redaction).

Modelo mental:
  space "default"  → o JARVIS de sempre: código, books, memórias abertas.
  space "pessoal"  → documentos, INSS, diário: vault cifrado, coleções
                     próprias, cifrado-at-rest no payload, só local.

Arquivo declarativo: ~/.config/jarvis/spaces.json (fora do repo, fora do
state_dir). Sem segredos ali: só caminhos e nomes de coleção. As chaves
vivem em /etc/jarvis-secrets/.

CLI: `jarvis space list|create|show|env|exec|doctor|purge`.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_PATH = Path(
    os.environ.get("JARVIS_SPACES_FILE", "~/.config/jarvis/spaces.json")
).expanduser()
SECRETS_DIR = Path("/etc/jarvis-secrets")


@dataclass
class Space:
    name: str
    state_dir: str
    key_file: str | None = None
    vault_enc: bool = False
    read_roots: list[str] = field(default_factory=list)
    collections: dict[str, str] = field(default_factory=dict)
    encrypt_collections: list[str] = field(default_factory=list)
    qdrant_token_file: str | None = None
    local_only: bool = True
    description: str = ""

    # --- derivado ---
    @property
    def vault_dir(self) -> Path:
        return Path(self.state_dir) / "vault"

    def collection(self, role: str) -> str:
        return self.collections.get(role) or f"{self.name}_{role}"

    def key_path(self) -> Path | None:
        return Path(self.key_file).expanduser() if self.key_file else None


def default_space() -> Space:
    return Space(
        name="default",
        state_dir="~/.local/state/jarvis",
        collections={"code": "code_index", "memories": "memories",
                     "books": "books"},
        local_only=False,
        description="ambiente de trabalho: código, books, memórias abertas",
    )


def load() -> dict[str, Space]:
    spaces: dict[str, Space] = {}
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"spaces.json inválido: {exc}")
        for name, data in raw.get("spaces", {}).items():
            data = dict(data)
            data["name"] = name
            spaces[name] = Space(**data)
    if "default" not in spaces:
        spaces["default"] = default_space()
    return spaces


def save(spaces: dict[str, Space]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "spaces": {
        n: {k: v for k, v in asdict(s).items() if k != "name"}
        for n, s in spaces.items()
    }}
    CONFIG_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    CONFIG_PATH.chmod(0o600)


def get(name: str) -> Space:
    spaces = load()
    if name not in spaces:
        raise SystemExit(
            f"space '{name}' não existe. Known: {', '.join(sorted(spaces))}")
    return spaces[name]


def create(name: str, *, description: str = "", read_roots: list[str] | None = None,
           encrypted: bool = True) -> Space:
    spaces = load()
    if name in spaces:
        raise SystemExit(f"space '{name}' já existe")
    key_file = None
    if encrypted:
        key_file = str(SECRETS_DIR / f"{name}-vault.fernet.key")
    sp = Space(
        name=name,
        state_dir=f"~/.local/state/jarvis-{name}",
        key_file=key_file,
        vault_enc=encrypted,
        read_roots=read_roots or [],
        collections={"code": f"{name}_code", "memories": f"{name}_memories",
                     "books": f"{name}_books"},
        encrypt_collections=[f"{name}_code"] if encrypted else [],
        local_only=encrypted,
        description=description or f"space isolada '{name}'",
    )
    spaces[name] = sp
    save(spaces)
    return sp


def keygen(space: Space) -> str:
    """Gera a chave Fernet do space (idempotente: não sobrescreve)."""
    if not space.key_file:
        raise SystemExit(f"space '{space.name}' não tem chave (não cifrado)")
    from jarvis.core.vault_cipher import generate_key

    path = space.key_path()
    assert path is not None
    if path.exists() and path.stat().st_size > 0:
        return str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return generate_key(path)


def env_for(space: Space) -> dict[str, str]:
    """Ambiente completo do space — a fonte única (CLI e MCP leem daqui)."""
    state = str(Path(space.state_dir).expanduser())
    env = {
        "JARVIS_SPACE": space.name,
        "JARVIS_STATE_DIR": state,
        "JARVIS_VAULT_DIR": str(Path(state) / "vault"),
        "JARVIS_QDRANT_COLLECTION_CODE": space.collection("code"),
        "JARVIS_QDRANT_COLLECTION_MEMORIES": space.collection("memories"),
        "JARVIS_QDRANT_COLLECTION_BOOKS": space.collection("books"),
    }
    if space.vault_enc and space.key_file:
        env["JARVIS_VAULT_ENC"] = "1"
        env["JARVIS_VAULT_KEY_FILE"] = str(Path(space.key_file).expanduser())
    if space.read_roots:
        env["JARVIS_EXTRA_READ_ROOTS"] = ":".join(
            str(Path(r).expanduser()) for r in space.read_roots)
    if space.encrypt_collections:
        env["JARVIS_RAG_ENCRYPT_COLLECTIONS"] = ",".join(space.encrypt_collections)
    if space.qdrant_token_file:
        env["JARVIS_QDRANT_API_KEY_FILE"] = str(
            Path(space.qdrant_token_file).expanduser())
    if space.local_only:
        # fail-closed: nuvem não pode tocar space protegido
        env["JARVIS_SPACE_LOCAL_ONLY"] = "1"
    return env


def ensure_dirs(space: Space) -> None:
    state = Path(space.state_dir).expanduser()
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o700)
    (state / "vault").mkdir(exist_ok=True)


def doctor(space: Space) -> dict[str, object]:
    state = Path(space.state_dir).expanduser()
    key = space.key_path()
    checks: dict[str, object] = {
        "state_dir": {"path": str(state), "ok": state.is_dir()},
        "vault_dir": {"path": str(state / "vault"),
                      "ok": (state / "vault").is_dir()},
        "key": {"path": str(key) if key else None,
                "ok": bool(key and key.exists()) if space.vault_enc else True},
        "collections": {r: space.collection(r) for r in ("code", "memories", "books")},
        "local_only": space.local_only,
    }
    try:
        import requests

        base = os.environ.get("JARVIS_QDRANT_URL", "http://127.0.0.1:6333")
        r = requests.get(f"{base}/collections", timeout=3)
        names = {c["name"] for c in r.json().get("result", {}).get("collections", [])}
        checks["qdrant"] = {
            "ok": True,
            "present": {r_: space.collection(r_) in names
                        for r_ in ("code", "memories", "books")},
        }
    except Exception as exc:  # noqa: BLE001
        checks["qdrant"] = {"ok": False, "error": str(exc)[:120]}
    return checks


def exec_in(space: Space, argv: list[str], *,
            env_extra: dict[str, str] | None = None) -> int:
    """Roda um comando com o ambiente do space (sem shell intermediário)."""
    env = os.environ.copy()
    env.update(env_for(space))
    if env_extra:
        env.update(env_extra)
    if space.local_only and not env.get("JARVIS_ALLOW_REMOTE_PROVIDER"):
        # fail-closed: provider de nuvem exige opt-in explícito
        for k in list(env):
            if k.startswith(("GROQ_", "OPENAI_", "ANTHROPIC_", "OPENROUTER_",
                             "NVIDIA_", "CEREBRAS_")):
                env.pop(k, None)
    proc = subprocess.run(argv, env=env)
    return proc.returncode


def show(space: Space) -> str:
    return json.dumps({"space": asdict(space), "env": env_for(space)},
                      indent=2, ensure_ascii=False)


def shell_hint(space: Space) -> str:
    env = env_for(space)
    return " ".join(f"{k}={shlex.quote(v)}" for k, v in sorted(env.items()))
