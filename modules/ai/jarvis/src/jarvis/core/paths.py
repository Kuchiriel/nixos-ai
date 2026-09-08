"""Project root canônico — ÚNICA fonte de verdade para "qual projeto?".

Precedência (documentada, testada):
    1. JARVIS_PROJECT_ROOT válido (diretório existente) — vence sempre.
       Projetos externos SEM marcadores (.git/flake.nix) resolvem aqui;
       sem isso, o isolamento A/B quebra (fallback p/ nixos-ai = contaminação).
    2. Walk-up do CWD procurando .git ou flake.nix (até 10 níveis).
    3. Fallback ~/projects/nixos-ai.

Mutação SOMENTE via set_project_root() (sessão) ou use_project_root()
(task, contextvar). Leitores NUNCA fazem os.environ.get("JARVIS_PROJECT_ROOT")
direto — usam find_repo_root(). (Auditoria 2026-09: 3 resolvers + 4
mutadores + defaults divergentes + monkeypatch de isolamento consolidados
aqui.)
"""

from __future__ import annotations

import contextlib
import contextvars
import os
from pathlib import Path
from typing import Iterator

_ENV_VAR = "JARVIS_PROJECT_ROOT"

# Task-scoped override (substitui o monkeypatch de REPO_ROOT por módulo —
# mesma semântica de isolamento, sem atributo global mutável; seguro para
# futura concorrência pois contextvar é por-contexto, não por-processo).
_current: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "jarvis_project_root", default=None
)


def find_repo_root() -> Path:
    """Resolve o project root ativo.

    Precedência:
        1. Override de task (use_project_root) — isolamento A/B.
        2. JARVIS_PROJECT_ROOT válido (diretório existente).
        3. Walk-up do CWD procurando .git ou flake.nix (até 10 níveis).
        4. Fallback ~/projects/nixos-ai.
    """
    task_root = _current.get()
    if task_root is not None:
        return task_root
    env_root = os.environ.get(_ENV_VAR, "")
    if env_root:
        candidate = Path(env_root).expanduser()
        if candidate.is_dir():
            return candidate.resolve()
        # Set-but-invalid: ignora e cai na descoberta (fail-open auditável
        # via debug; nunca resolve lixo silenciosamente como root).
    current = Path.cwd()
    for _ in range(10):
        if (current / ".git").exists() or (current / "flake.nix").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return Path.home() / "projects" / "nixos-ai"


def set_project_root(path: str | Path) -> Path:
    """ÚNICO mutador legítimo de JARVIS_PROJECT_ROOT.

    Valida que é diretório existente (fail fast) antes de exportar.
    Substitui atribuições espalhadas `os.environ[...] = ...` (4 pontos
    pré-auditoria: dev.py ×3, persona_executor ×1).
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"project root not a directory: {path}")
    os.environ[_ENV_VAR] = str(resolved)
    return resolved


@contextlib.contextmanager
def use_project_root(path: str | Path) -> Iterator[Path]:
    """Escopo de task: find_repo_root() retorna `path` dentro do bloco.

    Substitui o monkeypatch de REPO_ROOT por módulo (project_isolation):
    mesma garantia de restauração (inclusive em exceção), sem global mutável.
    Aninhável: o token restaura o valor anterior, não um default fixo.
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"project root not a directory: {path}")
    token = _current.set(resolved)
    try:
        yield resolved
    finally:
        _current.reset(token)
