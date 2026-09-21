"""Shared security module — single source of truth for command validation.

Consolidates: command_allowed, has_chaining_operators, _validate_pipes,
run_shell, dangerous patterns, safe pipe targets.

Previously duplicated across: agent.py, devtools.py, mcp_server.py
"""

from __future__ import annotations

import os
import re
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


def _strip_quoted(cmd: str) -> str:
    """Remove spans entre aspas (operadores lá dentro são literais, não
    shell). `"` e `'` com escape `\\` respeitado; backtick NÃO é stripped
    (command substitution — falha p/ o lado seguro)."""
    out: list[str] = []
    i, n = 0, len(cmd or "")
    q: str | None = None
    while i < n:
        c = cmd[i]
        if q is not None:
            if c == "\\":
                i += 2
                continue
            if c == q:
                q = None
        elif c in ("'", '"'):
            q = c
        else:
            out.append(c)
        i += 1
    return "".join(out)


def has_chaining_operators(cmd: str) -> bool:
    """True if command contains ANY chaining operators (including ; and |).

    Operadores DENTRO de aspas são literais (L8v40: sketch python3-c com
    `;` foi barrado — o modelo seguiu nossa instrução e a policy puniu!).
    run_shell usa shlex (sem shell): string quotada nunca vira comando.
    Backtick continua sempre bloqueado (fail-closed).

    Used for backward compatibility with tests.
    For security validation, use command_allowed() instead.
    """
    bare = _strip_quoted(cmd)
    _ALL_CHAINING = ("&&", "||", ";", "|", "`", "$(", "${", "\n")
    for pat in _ALL_CHAINING:
        if pat in bare:
            return True
    # Backtick mesmo quotado (conservador: _strip_quoted não o remove).
    if "`" in (cmd or ""):
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


_CHMOD_RUN_RE = re.compile(
    r"^\s*chmod\s+\+x\s+(\S+)\s*(?:&&|;)\s*\./(\S+)(.*)$"
)


def strip_redundant_chmod_run(cmd: str) -> str | None:
    """`chmod +x F && ./F [args]` fundido → só `./F [args]` (L8: idiom
    fused no treino; banido pela policy virava STUCK certo em 2 runs).
    write_file já dá +x: o chmod é redundante. Forma ESTRITA (mesma
    basename, sem outros operadores no resto — senão None e o ban vale):
    roda MENOS comandos, nunca mais (sem superfície nova). Retorna a
    parte run ou None.
    """
    m = _CHMOD_RUN_RE.match(cmd or "")
    if not m:
        return None
    if os.path.basename(m.group(1)) != os.path.basename(m.group(2)):
        return None
    tail = m.group(3) or ""
    if re.search(r"&&|\|\||[;|`]|\$\(", tail):
        return None
    run = ("./" + m.group(2) + tail).strip()
    return run or None


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
    if not argv:
        # Comando vazio (Ciclo 6: modelo chamou execute_shell c/ cmd=""
        # → Popen([]) → IndexError cru derrubando o run APÓS trabalho
        # útil). Falha legível, nunca crash.
        return subprocess.CompletedProcess(
            args=cmd, returncode=127, stdout="",
            stderr="ERROR: empty command — passe um comando não-vazio.")
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


# --- Máscaras GBNF p/ synthesize_command (H-grammar) ---
# Restrições descobertas no servidor (spike 20/09, fork prism):
# literais/classes/negação/repetição/alternação OK; `/regex/` NÃO;
# escape `\"` NÃO é confiável (funcionou 1x, depois 400 consistente) —
# NENHUMA gramática aqui usa `\"`: single-quotes p/ literais shell,
# formatos date SEM aspas (`date -u +%Y...` é válido sem elas).
# PATH genérico (nunca paths de task hardcoded — sem contaminação).
_SYNTH_PATH = 'PATH ::= [a-zA-Z0-9_.~-]+ ("/" [a-zA-Z0-9_.~-]+)*'

SYNTH_GRAMMARS: dict[str, str] = {
    "grep": (
        'root ::= "grep" (" -c" | " -h" | " -E" | " -oE" | " -F" | " -q")? '
        '" \'" [^\']+ "\' " PATH\n' + _SYNTH_PATH
    ),
    "jqread": (
        'root ::= "jq " ("-r ")? "\'" [^\']+ "\' " PATH\n' + _SYNTH_PATH
    ),
    "date": 'root ::= "date -u +" [A-Za-z0-9%.:_-]+',
    "chmod": 'root ::= "chmod +x " PATH\n' + _SYNTH_PATH,
}

_SYNTH_FAMILY = (
    ("grep", ("grep ",)),
    ("jqread", ("jq ",)),
    ("date", ("date ",)),
    ("chmod", ("chmod ",)),
)


def suggest_synth_grammar(text: str) -> str | None:
    """Família de comando → id de gramática (ou None). Match no primeiro
    token parecido-com-comando; conservador (desconhecido = None)."""
    low = (text or "").lower()
    for name, markers in _SYNTH_FAMILY:
        if any(m in low for m in markers):
            return name
    return None


_ECHO_JSON_HEAD = re.compile(r"^\s*(echo|printf)\s")


def echo_to_json(cmd: str) -> bool:
    """echo/printf com redirect direto p/ *.json no mesmo segmento de pipe.

    L8: echo-JSON é a representação que mais falha (v27 4x echo-surgery
    idêntica, b3 runtime inválido ×3, w2 doubled-quote) e conselho não muta
    representação — após escalada, vira BLOCKED vinculante (soft→binding).
    `echo x | jq ... > a.json` passa: o redirect está em segmento jq, não
    echo. Split ingênuo em `|` (limitação: echo com pipe quotado pode
    escapar — o ban é best-effort, a ordem TROQUE segue valendo).
    """
    for seg in (cmd or "").split("|"):
        seg = seg.strip()
        if not _ECHO_JSON_HEAD.match(seg):
            continue
        if re.search(r">>?\s*[\"']?[^\s\"']*\.json", seg):
            return True
    return False
