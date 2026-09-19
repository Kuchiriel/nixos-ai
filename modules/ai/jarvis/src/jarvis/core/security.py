"""Shared security module — single source of truth for command validation.

Consolidates: command_allowed, has_chaining_operators, _validate_pipes,
run_shell, dangerous patterns, safe pipe targets.

Previously duplicated across: agent.py, devtools.py, mcp_server.py
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
from typing import Any


# ═══ Dangerous Patterns ═══
# Operators that allow arbitrary command execution — always blocked
DANGEROUS_CHAINING = ("&&", "||", "`", "$(", "${", "\n")

# Commands blocked even as standalone (destructive)
DANGEROUS_COMMANDS = ("rm ", "chmod", "chown", "dd ", "mkfs")


# ═══ Safe Pipe Targets ═══
# Commands that are safe after a pipe (read-only, no side effects)
SAFE_PIPE_TARGETS = (
    "head", "tail", "grep", "rg", "wc", "sort", "uniq", "cut",
    "awk", "sed", "tr", "column", "jq", "ls", "cat", "echo",
)


# ═══ Command Allowlist ═══
# Read-only commands allowed without approval
DEFAULT_ALLOWED_PREFIXES = (
    "ls", "cat", "head", "tail", "grep", "rg", "find", "wc",
    "df", "free", "ps", "pgrep", "ss", "ip", "uname", "uptime",
    "date", "echo", "hostname", "id", "whoami", "file", "stat",
    "du", "which", "type", "realpath", "pwd",
    "systemctl is-active", "systemctl status", "systemctl list-units",
    "journalctl", "nix flake check", "nix eval", "nix build --dry-run",
    "nix search", "nix develop",
    "git log", "git status", "git diff", "git show", "git branch",
    "curl -sf", "curl -s", "nvidia-smi",
)


def has_dangerous_operators(cmd: str) -> bool:
    """True if command contains dangerous shell operators (&&, ||, backticks, etc.)."""
    for pat in DANGEROUS_CHAINING:
        if pat in cmd:
            return True
    return False


def has_chaining_operators(cmd: str) -> bool:
    """True if command contains ANY chaining operators (including ; and |).

    Used for backward compatibility with tests.
    For security validation, use command_allowed() instead.
    """
    _ALL_CHAINING = ("&&", "||", ";", "|", "`", "$(", "${", "\n")
    for pat in _ALL_CHAINING:
        if pat in cmd:
            return True
    return False


def validate_pipes(cmd: str) -> bool:
    """Validate that pipes point only to safe commands.

    Allows: find ... | head, ls ... | grep
    Blocks: find ... | rm, ls ... | xargs rm
    """
    if "|" not in cmd:
        return True
    parts = cmd.split("|")
    for part in parts[1:]:
        part = part.strip()
        if not part:
            continue
        # Extract first token (command)
        first_token = part.split()[0] if part.split() else ""
        # Remove redirects
        first_token = first_token.split(">")[0]
        if first_token and not any(first_token.startswith(p) for p in SAFE_PIPE_TARGETS):
            return False
    return True


def _python_file_allowed(part: str) -> bool:
    """Permite `python3 <arquivo>` SÓ se o arquivo está no jail.

    Elo M2 (16/09): o modelo escrevia o script certo e não podia RODÁ-LO
    (`python` fora do allowlist) — o passo "run" morria e a cadeia quebrava.
    Cap cirúrgico (não prefixo cego): primeiro token python/python3,
    NENHUMA flag `-x` (sem `-c` inline, sem `-m`), exatamente ≥1 path, e
    TODOS os paths dentro do jail (projeto, /tmp, /build — mesma regra
    do _safe_path de leitura). Fora do jail ou com flag → bloqueado.
    """
    import shlex as _shlex
    from pathlib import Path as _P
    try:
        argv = _shlex.split(part)
    except ValueError:
        return False
    if not argv or argv[0] not in ("python", "python3"):
        return False
    rest = argv[1:]
    if not rest or any(a.startswith("-") for a in rest):
        return False
    try:
        from jarvis.core.paths import find_repo_root
        root = str(find_repo_root())
    except Exception:
        root = ""
    allowed = tuple(p for p in ("/tmp", "/build", root) if p)
    for a in rest:
        p = _P(a)
        target = str(((_P(root) / p).resolve() if not p.is_absolute()
                      else p))
        if not any(target == pfx or target.startswith(pfx.rstrip("/") + "/")
                   for pfx in allowed):
            return False
    return True


def command_allowed(
    cmd: str,
    allowed_prefixes: tuple[str, ...] | None = None,
) -> bool:
    """True if command is safe to execute without approval.

    Checks:
    1. Starts with an allowed prefix
    2. No dangerous operators (&&, ||, backticks)
    3. Pipes point to safe commands
    4. Each semicolon-separated part starts with allowed prefix
    """
    prefixes = allowed_prefixes or DEFAULT_ALLOWED_PREFIXES
    stripped = cmd.strip()
    if not stripped:
        return False
    if has_dangerous_operators(stripped):
        return False
    if not validate_pipes(stripped):
        return False
    # For commands with ;, verify each part
    for part in stripped.split(";"):
        part = part.strip()
        if not part:
            continue
        check_cmd = part.split("|")[0].strip()
        first = check_cmd.split()[0] if check_cmd.split() else ""
        if first in ("python", "python3"):
            if not _python_file_allowed(check_cmd):
                return False
            continue
        if not any(check_cmd.startswith(p) for p in prefixes):
            return False
    return True


def run_shell(cmd: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Execute a command safely via shlex (no shell=True).

    Expande ~ e $VAR por token (forense 2026-09: `ls ~/Books` falhava com
    "No such file" porque sem shell não há expansão — o agente concluía
    "vazio"). Sem shell continua: sem risco de injection.

    Aspas desbalanceadas viram CompletedProcess 127 (nunca exceção: L2
    real matou o run inteiro com ValueError do shlex).
    """
    try:
        argv = [os.path.expandvars(os.path.expanduser(tok))
                for tok in shlex.split(cmd)]
    except ValueError as e:
        return subprocess.CompletedProcess(
            args=cmd, returncode=127, stdout="",
            stderr=f"ERROR: quoting inválido ({e}) — reescreva o comando "
                   f"com aspas balanceadas ou grave script .py e rode-o.")
    # Sessão própria p/ matar a ÁRVORE no timeout (L8r real: script com
    # auto-invocação `./response.sh $ip` recursa infinito — matar só o
    # filho direto órfã os netos que seguem se replicando. killpg fecha).
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True,
                                start_new_session=True)
    except OSError as e:
        return subprocess.CompletedProcess(
            args=cmd, returncode=127, stdout="",
            stderr=f"ERROR: Command failed to start: {e}")
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        out, err = proc.communicate()
        return subprocess.CompletedProcess(
            args=cmd, returncode=-1, stdout=out or "",
            stderr=((err or "")
                    + f"\nERROR: Command timed out after {timeout}s "
                    "(process tree killed)"))
    return subprocess.CompletedProcess(
        args=cmd, returncode=proc.returncode, stdout=out, stderr=err)


def run_shell_dict(cmd: str, timeout: int = 60) -> dict[str, Any]:
    """Execute a command and return structured result dict."""
    try:
        result = run_shell(cmd, timeout=timeout)
        output = result.stdout if result.returncode == 0 else (result.stdout + result.stderr)
        if not output.strip():
            output = f"(exit code {result.returncode})"
        return {
            "ok": result.returncode == 0,
            "output": output[:5000],
            "exit_code": result.returncode,
            "truncated": len(output) > 5000,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Command timed out", "exit_code": -1}
    except Exception as e:
        return {"ok": False, "error": str(e), "exit_code": -1}
