"""Dev Tools — ferramentas de desenvolvimento unificadas para JARVIS.

Fusão de dev.py (4 tools lean) + devtools.py (robustez: AST guard, backup,
safety, fuzzy match 4 camadas). Mantém interface para agent.py.

Design (v2.0 unificado):
  - 4 tools core: read_file, str_replace, execute_shell, semantic_search
  - 2 tools opt: write_file, list_directory
  - AST guard: valida Python antes de escrever
  - Backup: .bak antes de sobrescrever
  - Project safety: _safe_path valida que está dentro do projeto
  - Fuzzy match: 4 camadas (exact → normalized → fuzzy → line)
  - Structured output: dicts para o agente, strings para o LLM

Interface (compatível com agent.py):
  - DEV_TOOLS: lista de tool schemas
  - handle_dev_tool(name, args) → str (JSON)
  - jarvis_command(subcommand, args) → dict
"""

from __future__ import annotations

import difflib
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Project safety — valida que paths estão dentro do projeto
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    root = os.environ.get("JARVIS_PROJECT_ROOT", "")
    if root:
        return Path(root).expanduser().resolve()
    return Path.cwd().resolve()


def _safe_path(path: str, root: Path | None = None) -> Path:
    """Resolve um path e valida que está dentro do projeto.

    Aceita paths relativos (resolvidos em relacao ao project root) ou absolutos
    (se estiverem dentro do projeto ou em /tmp para testes).
    """
    p = Path(path)
    r = root or _project_root()
    if p.is_absolute():
        target = p
    else:
        target = (r / p).resolve()

    _allowed_prefixes = ("/tmp", "/build", str(r))
    if not any(str(target).startswith(pfx) for pfx in _allowed_prefixes):
        raise ValueError(f"Path outside project: {target}")
    return target


# ---------------------------------------------------------------------------
# AST guard — valida sintaxe Python antes de escrever
# ---------------------------------------------------------------------------

def _validate_python_syntax(code: str) -> tuple[bool, str | None]:
    """Valida sintaxe Python. Retorna (is_valid, error_message)."""
    try:
        compile(code, "<devtools>", "exec")
        return True, None
    except SyntaxError as e:
        return False, f"Line {e.lineno}: {e.msg}"


def _ast_guard(target: Path, new_content: str) -> dict[str, Any] | None:
    """Retorna erro dict se AST guard rejeitar, None se OK."""
    if target.suffix != ".py" or not target.exists():
        return None
    try:
        original = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    original_valid, _ = _validate_python_syntax(original)
    if not original_valid:
        return None  # original já era inválido, não proteger

    is_valid, ast_error = _validate_python_syntax(new_content)
    if not is_valid:
        return {
            "ok": False,
            "error": f"Rejeitado — quebra sintaxe Python: {ast_error}",
        }
    return None


# ---------------------------------------------------------------------------
# Fuzzy matching — 4 camadas (inspirado em devtools.py)
# ---------------------------------------------------------------------------

def _normalize_line(line: str) -> str:
    return " ".join(line.expandtabs().split())


def _normalize_text(text: str) -> str:
    return "\n".join(_normalize_line(l) for l in text.splitlines())


def _fuzzy_find(content: str, old: str) -> tuple[str | None, str]:
    """Encontra `old` em `content` com estratégias crescentes.

    Retorna (found_text, strategy) ou (None, "none").
    """
    # 1. Match exato (rápido)
    if old in content:
        return old, "exact"

    # 2. Match normalizado (whitespace collapsing)
    norm_old = _normalize_text(old)
    content_lines = content.splitlines()
    old_lines = old.splitlines()

    if old_lines:
        for i in range(len(content_lines) - len(old_lines) + 1):
            window = content_lines[i:i + len(old_lines)]
            if _normalize_text("\n".join(window)) == norm_old:
                return "\n".join(window), "normalized"

    # 3. Match por similaridade (difflib, threshold 75%)
    if len(old_lines) >= 2:
        best_ratio = 0.0
        best_start = -1
        window_size = len(old_lines)

        for i in range(len(content_lines) - window_size + 1):
            window = content_lines[i:i + window_size]
            ratio = difflib.SequenceMatcher(
                None, "\n".join(old_lines), "\n".join(window),
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_start = i

        if best_ratio >= 0.75 and best_start >= 0:
            found = "\n".join(content_lines[best_start:best_start + window_size])
            return found, f"fuzzy ({best_ratio:.0%})"

    # 4. Match por linha única (último recurso)
    if old_lines:
        first_norm = _normalize_line(old_lines[0])
        for i, line in enumerate(content_lines):
            if _normalize_line(line) == first_norm:
                end = min(i + len(old_lines), len(content_lines))
                found = "\n".join(content_lines[i:end])
                if len(found.strip()) > 0:
                    return found, "line-match"

    return None, "none"


def _find_context(content: str, old: str, context_lines: int = 3) -> str:
    """Retorna contexto ao redor de onde `old` seria encontrado (para debug)."""
    content_lines = content.splitlines()
    old_lines = old.splitlines()
    if not old_lines:
        return ""

    best_ratio = 0.0
    best_start = 0
    for i in range(max(1, len(content_lines) - len(old_lines) + 1)):
        end = min(i + len(old_lines), len(content_lines))
        window = content_lines[i:end]
        ratio = difflib.SequenceMatcher(
            None, "\n".join(old_lines), "\n".join(window),
        ).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = i

    start = max(0, best_start - context_lines)
    end = min(len(content_lines), best_start + len(old_lines) + context_lines)
    lines = []
    for i in range(start, end):
        marker = ">>>" if best_start <= i < best_start + len(old_lines) else "   "
        lines.append(f"{i+1:4d} {marker} {content_lines[i]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Diff helper
# ---------------------------------------------------------------------------

def _make_diff(path: str, old: str, new: str) -> str:
    return "\n".join(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=path, tofile=path, lineterm="", n=1,
    ))


# ===========================================================================
# TOOL: read_file
# ===========================================================================

def read_file(path: str, offset: int = 0, limit: int = 2000) -> dict[str, Any]:
    """Lê um arquivo com offset/limit opcionais.

    Compatível com:
      - dev.py: read_file(path, start_line?, end_line?)
      - devtools.py: read_file(path, offset?, limit?)

    Returns: {"ok": True, "content": "...", "lines": N, "total_lines": M}
    """
    try:
        target = _safe_path(path)
        if not target.exists():
            return {"ok": False, "error": f"File not found: {path}"}
        if not target.is_file():
            return {"ok": False, "error": f"Not a file: {path}"}

        content = target.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        total = len(lines)

        start = max(0, offset)
        end = min(total, start + limit) if limit > 0 else total
        selected = "\n".join(lines[start:end])

        # Formato com números de linha (dev.py style) para o LLM
        numbered = "\n".join(f"{start + i + 1:>5} | {line}" for i, line in enumerate(lines[start:end]))

        try:
            rel = str(target.relative_to(_project_root()))
        except ValueError:
            rel = str(target)

        return {
            "ok": True,
            "content": numbered,
            "raw": selected,
            "lines": end - start,
            "total_lines": total,
            "offset": start,
            "path": rel,
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except OSError as e:
        return {"ok": False, "error": f"Read error: {e}"}


# ===========================================================================
# TOOL: str_replace
# ===========================================================================

def str_replace(path: str, old: str, new: str, allow_multiple: bool = False) -> dict[str, Any]:
    """Substitui uma string em um arquivo.

    Compatível com:
      - dev.py: str_replace(path, old_str, new_str)
      - devtools.py: str_replace(path, old, new, allow_multiple?)

    Suporta:
      - old="" para criar arquivo novo
      - Fuzzy match 4 camadas quando match exato falha
      - AST guard para Python
      - Backup automático

    Returns: {"ok": True, "replacements": N, "path": "...", "strategy": "..."}
    """
    try:
        target = _safe_path(path)

        # Criar arquivo novo (old vazio)
        if old == "":
            if target.exists():
                return {"ok": False, "error": f"File already exists: {path}"}
            # AST guard
            ast_err = _ast_guard(target, new)
            if ast_err:
                return ast_err
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new, encoding="utf-8")
            try:
                rel = str(target.relative_to(_project_root()))
            except ValueError:
                rel = str(target)
            return {
                "ok": True,
                "replacements": 1,
                "path": rel,
                "strategy": "create",
                "bytes": len(new.encode("utf-8")),
            }

        if not target.exists():
            return {"ok": False, "error": f"File not found: {path}"}

        content = target.read_text(encoding="utf-8", errors="replace")

        # Fuzzy match 4 camadas
        found_text, strategy = _fuzzy_find(content, old)

        if found_text is None:
            ctx = _find_context(content, old)
            return {
                "ok": False,
                "error": f"String not found in {path}",
                "hint": f"Searched with: exact, normalized, fuzzy (75%+). Closest match:\n{ctx}",
                "old_preview": old[:200],
            }

        count = content.count(found_text)
        if count > 1 and not allow_multiple:
            return {
                "ok": False,
                "error": f"String found {count} times (use allow_multiple=True)",
                "strategy": strategy,
            }

        # Substitui
        if allow_multiple:
            new_content = content.replace(found_text, new)
            replacements = count
        else:
            new_content = content.replace(found_text, new, 1)
            replacements = 1

        # AST guard
        ast_err = _ast_guard(target, new_content)
        if ast_err:
            ast_err["strategy"] = strategy
            return ast_err

        # Backup
        backup_path = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, backup_path)

        target.write_text(new_content, encoding="utf-8")

        try:
            rel = str(target.relative_to(_project_root()))
        except ValueError:
            rel = str(target)
        try:
            backup_rel = str(backup_path.relative_to(_project_root()))
        except ValueError:
            backup_rel = str(backup_path)

        diff = _make_diff(path, found_text, new)
        return {
            "ok": True,
            "replacements": replacements,
            "path": rel,
            "backup": backup_rel,
            "strategy": strategy,
            "diff": diff,
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except OSError as e:
        return {"ok": False, "error": f"Replace error: {e}"}


# ===========================================================================
# TOOL: execute_shell
# ===========================================================================

def execute_shell(cmd: str, approve: bool = False) -> dict[str, Any]:
    """Execute shell command — delegates to security.run_shell_dict().

    Single implementation. No duplicated validation logic.
    """
    from jarvis.core.security import run_shell_dict, command_allowed
    if not cmd:
        return {"ok": False, "error": "Empty command"}
    # Quick validation before execution
    stripped = cmd.strip()
    if not command_allowed(stripped):
        return {"ok": False, "error": f"Command not in allowlist: {stripped[:100]}"}
    return run_shell_dict(cmd)


# ===========================================================================
# TOOL: semantic_search
# ===========================================================================

def semantic_search(query: str, top_k: int = 5) -> dict[str, Any]:
    """Busca semântica no code_index do Qdrant."""
    if not query or not query.strip():
        return {"ok": False, "error": "Empty query"}

    try:
        from jarvis.core.config import get_config
        from jarvis.providers.llm import LLMClient
        from jarvis.providers.vector_store import QdrantStore

        cfg = get_config()
        llm = LLMClient(cfg)
        vec = llm.embed(query)
        if not vec:
            return {"ok": False, "error": "Embedding generation failed"}

        vs = QdrantStore(cfg)
        raw = vs.search(cfg.qdrant_collection_code, vec, top_k=top_k)

        formatted = []
        for r in raw:
            formatted.append({
                "text": r.get("payload", {}).get("text", "")[:300],
                "score": round(r.get("score", 0), 3),
                "source": r.get("payload", {}).get("path", "unknown"),
            })

        return {
            "ok": True,
            "results": formatted,
            "total": len(formatted),
            "query": query,
        }
    except Exception as e:
        err_type = type(e).__name__
        if "Connect" in err_type or "Connection" in err_type:
            msg = f"Qdrant unavailable: {e}"
        elif "NotFound" in str(e) or "not found" in str(e).lower():
            msg = "Collection missing — run 'jarvis rag index' first"
        else:
            msg = f"Search failed ({err_type}): {e}"
        return {"ok": False, "error": msg}


# ===========================================================================
# TOOL: write_file (opcional — para escrita completa)
# ===========================================================================

def write_file(path: str, content: str, backup: bool = True) -> dict[str, Any]:
    """Escreve um arquivo (cria ou sobrescreve). Com backup + AST guard."""
    try:
        target = _safe_path(path)

        # AST guard
        ast_err = _ast_guard(target, content)
        if ast_err:
            return ast_err

        # Backup
        backup_path = None
        if backup and target.exists():
            backup_path = target.with_suffix(target.suffix + ".bak")
            shutil.copy2(target, backup_path)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        try:
            rel = str(target.relative_to(_project_root()))
        except ValueError:
            rel = str(target)

        return {
            "ok": True,
            "path": rel,
            "bytes": len(content.encode("utf-8")),
            "backup": str(backup_path) if backup_path else None,
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except OSError as e:
        return {"ok": False, "error": f"Write error: {e}"}


# ===========================================================================
# TOOL: list_directory (opcional — baixo overhead)
# ===========================================================================

def list_directory(path: str = ".", max_depth: int = 2) -> dict[str, Any]:
    """Lista conteúdo de um diretório (recursivo limitado)."""
    try:
        target = _safe_path(path)
        if not target.exists():
            return {"ok": False, "error": f"Directory not found: {path}"}
        if not target.is_dir():
            return {"ok": False, "error": f"Not a directory: {path}"}

        ignore = {".git", "__pycache__", "node_modules", ".direnv", "result",
                  "build", ".hypothesis", ".venv", "venv", "dist"}
        entries: list[dict[str, Any]] = []

        def _scan(d: Path, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                for item in sorted(d.iterdir()):
                    if item.name in ignore or item.name.startswith("."):
                        continue
                    rel = item.relative_to(target)
                    entry: dict[str, Any] = {
                        "name": str(rel),
                        "type": "dir" if item.is_dir() else "file",
                    }
                    if item.is_file():
                        try:
                            entry["size"] = item.stat().st_size
                        except OSError:
                            pass
                    entries.append(entry)
                    if item.is_dir():
                        _scan(item, depth + 1)
            except PermissionError:
                pass

        _scan(target, 0)
        try:
            rel = str(target.relative_to(_project_root()))
        except ValueError:
            rel = str(target)

        return {
            "ok": True,
            "entries": entries,
            "path": rel,
            "count": len(entries),
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except OSError as e:
        return {"ok": False, "error": f"List error: {e}"}


# ===========================================================================
# TOOL: code_search (via grep — rápido)
# ===========================================================================

def code_search(pattern: str, path: str = ".", max_results: int = 50) -> dict[str, Any]:
    """Busca padrões no código (grep -rn)."""
    try:
        target = _safe_path(path)
        if not target.exists():
            return {"ok": False, "error": f"Path not found: {path}"}

        cmd = [
            "grep", "-rn",
            "--include=*.py", "--include=*.nix", "--include=*.md",
            "--include=*.toml", "--include=*.json", "--include=*.yaml",
            "--exclude-dir=.git", "--exclude-dir=__pycache__",
            "--exclude-dir=node_modules", "--exclude-dir=result",
            "-m", str(max_results), pattern, str(target),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        results: list[dict[str, Any]] = []
        for line in result.stdout.strip().splitlines():
            if ":" in line:
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    try:
                        results.append({
                            "file": parts[0],
                            "line": int(parts[1]),
                            "text": parts[2][:200],
                        })
                    except ValueError:
                        pass

        return {
            "ok": True,
            "results": results,
            "total": len(results),
            "pattern": pattern,
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Search timed out (30s)"}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": f"Search error: {e}"}


# ===========================================================================
# TOOL: run_tests
# ===========================================================================

def run_tests(test_path: str = "tests/", pattern: str = "", timeout: int = 120) -> dict[str, Any]:
    """Executa testes pytest e retorna resultado parseado."""
    try:
        cmd = ["python", "-m", "pytest", test_path, "-x", "-q", "--tb=short"]
        if pattern:
            cmd.extend(["-k", pattern])

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(_project_root() / "modules" / "ai" / "jarvis"),
        )

        output = result.stdout + result.stderr
        passed = failed = 0
        errors: list[str] = []

        for line in output.splitlines():
            if "passed" in line:
                try:
                    passed = int(line.split("passed")[0].strip().split()[-1])
                except (ValueError, IndexError):
                    pass
            if "failed" in line:
                try:
                    failed = int(line.split("failed")[0].strip().split()[-1])
                except (ValueError, IndexError):
                    pass
                errors.append(line.strip()[:200])

        return {
            "ok": result.returncode == 0,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "output": output[-2000:],
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Tests timed out ({timeout}s)", "passed": 0, "failed": -1}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": f"Test error: {e}", "passed": 0, "failed": -1}


# ===========================================================================
# TOOL: run_linter
# ===========================================================================

def run_linter(path: str = ".") -> dict[str, Any]:
    """Executa ruff linter e retorna issues."""
    try:
        target = _safe_path(path)
        cmd = ["ruff", "check", "--output-format=json", str(target)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        issues: list[dict[str, Any]] = []
        if result.stdout.strip():
            try:
                issues = json.loads(result.stdout)
            except json.JSONDecodeError:
                for line in result.stdout.strip().splitlines():
                    if ":" in line:
                        issues.append({"text": line[:200]})

        return {
            "ok": True,
            "issues": issues[:50],
            "total": len(issues),
            "clean": len(issues) == 0,
            "path": str(target),
        }
    except FileNotFoundError:
        return {"ok": False, "error": "ruff not installed"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Linter timed out (30s)"}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": f"Linter error: {e}"}


# ===========================================================================
# TOOL: jarvis_command
# ===========================================================================

def jarvis_command(subcommand: str, args: str = "") -> dict[str, Any]:
    """Executa um comando jarvis CLI."""
    cmd_parts = ["jarvis", subcommand] + (args.split() if args else [])
    try:
        result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=30)
        output = result.stdout if result.returncode == 0 else result.stderr
        return {"ok": result.returncode == 0, "output": output[:3000]}
    except FileNotFoundError:
        try:
            result = subprocess.run(
                ["python", "-m", "jarvis.cli.main", subcommand] + (args.split() if args else []),
                capture_output=True, text=True, timeout=30,
            )
            return {"ok": result.returncode == 0, "output": result.stdout[:3000]}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ===========================================================================
# Tool definitions — DEV_TOOLS (compatível com agent.py)
# ===========================================================================

DEV_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file's content with line numbers. Use offset/limit for large files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to project root"},
                    "offset": {"type": "integer", "description": "Line number to start (0-indexed)"},
                    "limit": {"type": "integer", "description": "Max lines to read (default 2000)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file (creates or overwrites). Creates backup. Validates Python AST.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to project root"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "str_replace",
            "description": "Replace a string in a file. Preferred for editing. Validates old string exists. old='' creates new file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to project root"},
                    "old": {"type": "string", "description": "Exact string to find and replace (empty = create file)"},
                    "new": {"type": "string", "description": "Replacement string"},
                    "allow_multiple": {"type": "boolean", "description": "Allow replacing multiple occurrences"},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
    # NOTE: execute_shell is defined in agent.py TOOLS (with safe shlex-based execution).
    # It is NOT duplicated here to avoid confusion for the LLM model.
    # agent.py intercepts execute_shell calls and routes to _execute_tool().
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": "Search codebase semantically via embeddings (slower but smarter than grep).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language query"},
                    "top_k": {"type": "integer", "description": "Number of results (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List directory contents recursively (limited depth).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default: project root)"},
                    "max_depth": {"type": "integer", "description": "Max recursion depth (default 2)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_search",
            "description": "Search for patterns in the codebase (grep -rn).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex or literal pattern to search"},
                    "path": {"type": "string", "description": "Directory to search in (default: project root)"},
                    "max_results": {"type": "integer", "description": "Max results (default 50)"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run pytest tests and return results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_path": {"type": "string", "description": "Test file or directory (default: tests/)"},
                    "pattern": {"type": "string", "description": "pytest -k pattern to filter"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_linter",
            "description": "Run ruff linter and return issues.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or directory to lint"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "jarvis_command",
            "description": "Run a JARVIS CLI command (doctor, status, profile, metrics).",
            "parameters": {
                "type": "object",
                "properties": {
                    "subcommand": {"type": "string", "description": "Subcommand: doctor, status, profile, metrics"},
                    "args": {"type": "string", "description": "Additional arguments"},
                },
                "required": ["subcommand"],
            },
        },
    },
]


# ===========================================================================
# Tool dispatcher — handle_dev_tool (compatível com agent.py)
# ===========================================================================

def handle_dev_tool(name: str, args: dict[str, Any]) -> str:
    """Despacha uma tool call do agente. Retorna JSON string."""
    handlers = {
        "read_file": lambda a: read_file(a["path"], a.get("offset", 0), a.get("limit", 2000)),
        "write_file": lambda a: write_file(a["path"], a["content"]),
        "str_replace": lambda a: str_replace(a["path"], a["old"], a["new"], a.get("allow_multiple", False)),
        "execute_shell": lambda a: execute_shell(a["cmd"]),
        "semantic_search": lambda a: semantic_search(a["query"], a.get("top_k", 5)),
        "list_directory": lambda a: list_directory(a.get("path", "."), a.get("max_depth", 2)),
        "code_search": lambda a: code_search(a["pattern"], a.get("path", "."), max_results=a.get("max_results", 50)),
        "run_tests": lambda a: run_tests(a.get("test_path", "tests/"), a.get("pattern", ""), a.get("timeout", 120)),
        "run_linter": lambda a: run_linter(a.get("path", ".")),
        "jarvis_command": lambda a: jarvis_command(a["subcommand"], a.get("args", "")),
    }

    handler = handlers.get(name)
    if handler is None:
        return json.dumps({"ok": False, "error": f"Unknown tool: {name}"})

    try:
        result = handler(args)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})
