"""Shared security module — single source of truth for command validation.

Consolidates: command_allowed, has_chaining_operators, _validate_pipes,
run_shell, dangerous patterns, safe pipe targets.

Previously duplicated across: agent.py, devtools.py, mcp_server.py
"""

from __future__ import annotations

import shlex
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
        if not any(check_cmd.startswith(p) for p in prefixes):
            return False
    return True


def run_shell(cmd: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Execute a command safely via shlex (no shell=True)."""
    argv = shlex.split(cmd)
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


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
