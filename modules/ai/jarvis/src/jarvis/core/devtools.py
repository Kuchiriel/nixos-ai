"""Dev Tools — ferramentas de desenvolvimento para o agente JARVIS.

Inspirado em Aider, Claude Code e pi: o agente pode explorar, editar e
validar código de forma segura e iterativa.

Ferramentas:
  - read_file: lê um arquivo (com offset/limit opcional)
  - write_file: cria/escreve um arquivo (com validação de path)
  - str_replace: substitui strings em arquivos (método preferido para edição)
  - list_directory: lista conteúdo de diretórios
  - code_search: busca padrões no código (regex/substring)
  - run_tests: executa testes pytest e retorna resultado

Segurança:
  - Paths restritos ao diretório do projeto (CWD ou --project-root)
  - Operações de escrita são logged no audit trail
  - str_replace valida que a string antiga existe antes de escrever
  - write_file cria backups antes de sobrescrever
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from jarvis.core.config import get_config


def _project_root() -> Path:
    """Retorna o diretório raiz do projeto."""
    root = os.environ.get("JARVIS_PROJECT_ROOT", "")
    if root:
        return Path(root).expanduser().resolve()
    return Path.cwd().resolve()


def _safe_path(path: str, root: Path | None = None) -> Path:
    """Resolve um path e valida que está dentro do projeto.

    Aceita paths relativos (resolvidos相对于 project root) ou absolutos
    (se estiverem dentro do projeto ou em /tmp para testes).
    """
    p = Path(path)
    r = root or _project_root()
    if p.is_absolute():
        target = p
        # Permite /tmp e /build (sandbox Nix) para testes
        _allowed_prefixes = ("/tmp", "/build", str(r))
        if not any(str(target).startswith(pfx) for pfx in _allowed_prefixes):
            raise ValueError(f"Path outside project: {target}")
    else:
        target = (r / p)
        _allowed_prefixes = ("/tmp", "/build", str(r))
        if not any(str(target).startswith(pfx) for pfx in _allowed_prefixes):
            raise ValueError(f"Path outside project: {target}")
    return target


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------

def read_file(path: str, offset: int = 0, limit: int = 2000) -> dict[str, Any]:
    """Lê um arquivo com offset/limit opcionais.

    Returns:
        {"ok": True, "content": "...", "lines": 100, "total_lines": 150}
        ou {"ok": False, "error": "..."}
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

        try:
            rel = str(target.relative_to(_project_root()))
        except ValueError:
            rel = str(target)
        return {
            "ok": True,
            "content": selected,
            "lines": end - start,
            "total_lines": total,
            "offset": start,
            "path": rel,
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except OSError as e:
        return {"ok": False, "error": f"Read error: {e}"}


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------

def write_file(path: str, content: str, backup: bool = True) -> dict[str, Any]:
    """Escreve um arquivo (cria ou sobrescreve).

    Se backup=True e o arquivo existe, cria .bak antes de sobrescrever.
    Cria diretórios intermediários automaticamente.
    Valida AST para arquivos .py (proteção contra SLM).

    Returns:
        {"ok": True, "path": "...", "bytes": 1234, "backup": "..."}
    """
    try:
        target = _safe_path(path)

        # AST guard: valida sintaxe Python antes de escrever
        # Só aplica se o arquivo original era Python válido
        if target.suffix == ".py" and target.exists():
            try:
                from jarvis.core.ast_guard import validate_python_syntax_cached
                original_code = target.read_text(encoding="utf-8", errors="replace")
                original_valid, _ = validate_python_syntax_cached(original_code, str(target))
                if original_valid:
                    is_valid, ast_error = validate_python_syntax_cached(content, str(target))
                    if not is_valid:
                        return {
                            "ok": False,
                            "error": f"write_file rejeitado — sintaxe Python inválida",
                            "ast_error": ast_error,
                        }
            except ImportError:
                pass  # ast_guard não disponível, segue sem validação

        backup_path = None

        # Backup se arquivo existe
        if backup and target.exists():
            backup_path = target.with_suffix(target.suffix + ".bak")
            shutil.copy2(target, backup_path)

        # Cria diretórios
        target.parent.mkdir(parents=True, exist_ok=True)

        # Escreve
        target.write_text(content, encoding="utf-8")
        bytes_written = target.stat().st_size

        try:
            rel = str(target.relative_to(_project_root()))
        except ValueError:
            rel = str(target)
        backup_rel = None
        if backup_path:
            try:
                backup_rel = str(backup_path.relative_to(_project_root()))
            except ValueError:
                backup_rel = str(backup_path)
        return {
            "ok": True,
            "path": rel,
            "bytes": bytes_written,
            "backup": backup_rel,
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except OSError as e:
        return {"ok": False, "error": f"Write error: {e}"}# ---------------------------------------------------------------------------
# Fuzzy matching helpers (para SLMs que erram whitespace/indentação)
# ---------------------------------------------------------------------------

def _normalize_line(line: str) -> str:
    """Normaliza uma linha: strip, tabs→spaces, múltiplos espaços→1."""
    return " ".join(line.expandtabs().split())


def _normalize_text(text: str) -> str:
    """Normaliza bloco de texto para comparação fuzzy.

    Cada linha é normalizada individualmente (whitespace colapsado),
    preservando a estrutura de linhas para matching multi-linha.
    """
    return "\n".join(_normalize_line(l) for l in text.splitlines())


def _fuzzy_find(content: str, old: str) -> tuple[str | None, str]:
    """Tenta encontrar `old` em `content` com estratégias crescentes.

    Retorna (found_text, strategy) ou (None, "none").
    found_text é o texto EXATO do arquivo que corresponde (para substitution).
    """
    # 1. Match exato (rápido)
    if old in content:
        return old, "exact"

    # 2. Match normalizado (whitespace collapsing, preserva novas linhas)
    norm_old = _normalize_text(old)
    norm_content = _normalize_text(content.rstrip("\n"))
    if norm_old in norm_content:
        content_lines = content.splitlines()
        old_lines = old.splitlines()
        if old_lines:
            for i in range(len(content_lines) - len(old_lines) + 1):
                window = content_lines[i:i + len(old_lines)]
                if _normalize_text("\n".join(window)) == norm_old:
                    found = "\n".join(window)
                    return found, "normalized"

    # 2b. Match por colapso de whitespace em bloco (tolera \s+ → \s)
    #      Compara o bloco inteiro com regex de whitespace
    old_compact = re.sub(r"\s+", " ", old.strip())
    content_compact = re.sub(r"\s+", " ", content.strip())
    if old_compact in content_compact:
        # Encontra o bloco exato no conteúdo original
        content_lines = content.splitlines()
        old_lines = old.splitlines()
        if old_lines:
            for i in range(len(content_lines) - len(old_lines) + 1):
                window = content_lines[i:i + len(old_lines)]
                window_compact = re.sub(r"\s+", " ", " ".join(l.strip() for l in window).strip())
                if window_compact == old_compact:
                    found = "\n".join(window)
                    return found, "normalized"

    # 3. Match por similaridade de linhas (difflib)
    content_lines = content.splitlines()
    old_lines = old.splitlines()
    if len(old_lines) >= 2:
        # Janela deslizante com threshold de similaridade
        best_ratio = 0.0
        best_start = -1
        best_len = len(old_lines)
        window_size = len(old_lines)

        for i in range(len(content_lines) - window_size + 1):
            window = content_lines[i:i + window_size]
            ratio = difflib.SequenceMatcher(
                None,
                "\n".join(old_lines),
                "\n".join(window),
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_start = i

        if best_ratio >= 0.75 and best_start >= 0:
            found = "\n".join(content_lines[best_start:best_start + best_len])
            return found, f"fuzzy ({best_ratio:.0%})"

    # 4. Match por linha única (último recurso)
    if old_lines:
        first_norm = _normalize_line(old_lines[0])
        for i, line in enumerate(content_lines):
            if _normalize_line(line) == first_norm:
                # Tenta pegar as linhas seguintes
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

    # Tenta encontrar a melhor posição
    best_ratio = 0.0
    best_start = 0
    for i in range(max(1, len(content_lines) - len(old_lines) + 1)):
        end = min(i + len(old_lines), len(content_lines))
        window = content_lines[i:end]
        ratio = difflib.SequenceMatcher(
            None, "\n".join(old_lines), "\n".join(window)
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
# str_replace (método preferido para edição)
# ---------------------------------------------------------------------------
def str_replace(path: str, old: str, new: str, allow_multiple: bool = False) -> dict[str, Any]:
    """Substitui uma string em um arquivo (método preferido para edição).

    Valida que a string antiga existe antes de escrever.
    Se allow_multiple=False (default), exige que old apareça exatamente 1 vez.

    Suporta matching fuzzy (whitespace-insensitive) quando o match exato falha.

    Returns:
        {"ok": True, "replacements": 1, "path": "...", "strategy": "exact"}
    """
    try:
        target = _safe_path(path)
        if not target.exists():
            return {"ok": False, "error": f"File not found: {path}"}

        content = target.read_text(encoding="utf-8", errors="replace")

        # Tenta matching com estratégias crescentes
        found_text, strategy = _fuzzy_find(content, old)

        if found_text is None:
            # Nenhuma estratégia funcionou — retorna contexto útil
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

        # Substitui usando o texto EXATO encontrado no arquivo
        if allow_multiple:
            new_content = content.replace(found_text, new)
            replacements = count
        else:
            new_content = content.replace(found_text, new, 1)
            replacements = 1

        # AST guard: valida sintaxe Python antes de escrever
        # Só aplica se o arquivo original era Python válido
        if target.suffix == ".py":
            try:
                from jarvis.core.ast_guard import validate_python_syntax_cached, format_ast_error_for_llm
                original_valid, _ = validate_python_syntax_cached(content, str(target))
                if original_valid:
                    is_valid, ast_error = validate_python_syntax_cached(new_content, str(target))
                    if not is_valid:
                        return {
                            "ok": False,
                            "error": f"str_replace rejeitado — quebra sintaxe Python",
                            "ast_error": ast_error,
                            "hint": format_ast_error_for_llm(ast_error, found_text[:300], new[:300]),
                            "strategy": strategy,
                        }
            except ImportError:
                pass  # ast_guard não disponível, segue sem validação

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
        return {
            "ok": True,
            "replacements": replacements,
            "path": rel,
            "backup": backup_rel,
            "strategy": strategy,
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except OSError as e:
        return {"ok": False, "error": f"Replace error: {e}"}


# ---------------------------------------------------------------------------
# list_directory
# ---------------------------------------------------------------------------

def list_directory(path: str = ".", max_depth: int = 2, ignore: tuple[str, ...] = ()) -> dict[str, Any]:
    """Lista conteúdo de um diretório (recursivo limitado).

    Returns:
        {"ok": True, "entries": [{"name": "foo.py", "type": "file", "size": 1234}, ...]}
    """
    try:
        target = _safe_path(path)
        if not target.exists():
            return {"ok": False, "error": f"Directory not found: {path}"}
        if not target.is_dir():
            return {"ok": False, "error": f"Not a directory: {path}"}

        ignore_set = set(ignore) | {".git", "__pycache__", "node_modules", ".direnv", "result", "build", ".hypothesis"}
        entries: list[dict[str, Any]] = []

        def _scan(d: Path, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                for item in sorted(d.iterdir()):
                    if item.name in ignore_set or item.name.startswith("."):
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


# ---------------------------------------------------------------------------
# code_search
# ---------------------------------------------------------------------------

def code_search(
    pattern: str,
    path: str = ".",
    file_types: tuple[str, ...] = (),
    max_results: int = 50,
) -> dict[str, Any]:
    """Busca padrões no código (grep -rn via subprocess para velocidade).

    Returns:
        {"ok": True, "results": [{"file": "...", "line": 42, "text": "..."}], "total": 10}
    """
    try:
        target = _safe_path(path)
        if not target.exists():
            return {"ok": False, "error": f"Path not found: {path}"}

        cmd = ["grep", "-rn", "--include=*.py", "--include=*.nix", "--include=*.md",
               "--include=*.toml", "--include=*.json", "--include=*.yaml", "--include=*.yml",
               "--exclude-dir=.git", "--exclude-dir=__pycache__", "--exclude-dir=node_modules",
               "--exclude-dir=result", "--exclude-dir=build", "--exclude-dir=.direnv",
               "-m", str(max_results), pattern, str(target)]

        if file_types:
            # Reconstrói com tipos específicos
            cmd = ["grep", "-rn"]
            for ft in file_types:
                cmd.extend(["--include", f"*.{ft}"])
            cmd.extend(["--exclude-dir=.git", "--exclude-dir=__pycache__",
                        "-m", str(max_results), pattern, str(target)])

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


# ---------------------------------------------------------------------------
# run_tests
# ---------------------------------------------------------------------------

def run_tests(
    test_path: str = "tests/",
    pattern: str = "",
    timeout: int = 120,
) -> dict[str, Any]:
    """Executa testes pytest e retorna resultado parseado.

    Returns:
        {"ok": True, "passed": 100, "failed": 2, "errors": [...], "output": "..."}
    """
    try:
        cmd = ["python", "-m", "pytest", test_path, "-x", "-q", "--tb=short"]
        if pattern:
            cmd.extend(["-k", pattern])

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(_project_root() / "modules" / "ai" / "jarvis"),
        )

        output = result.stdout + result.stderr
        passed = 0
        failed = 0
        errors: list[str] = []

        # Parse "X passed" / "Y failed"
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
                # Extrai erro
                errors.append(line.strip()[:200])

        return {
            "ok": result.returncode == 0,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "output": output[-2000:],  # últimos 2000 chars
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Tests timed out ({timeout}s)", "passed": 0, "failed": -1, "errors": ["timeout"], "output": ""}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": f"Test error: {e}", "passed": 0, "failed": -1, "errors": [str(e)], "output": ""}


# ---------------------------------------------------------------------------
# run_linter
# ---------------------------------------------------------------------------
def run_linter(path: str = ".") -> dict[str, Any]:
    """Executa ruff linter e retorna issues encontradas.

    Returns:
        {"ok": True, "issues": [...], "total": 5, "clean": False}
    """
    try:
        target = _safe_path(path)
        cmd = ["ruff", "check", "--output-format=json", str(target)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        issues: list[dict[str, Any]] = []
        if result.stdout.strip():
            try:
                issues = json.loads(result.stdout)
            except json.JSONDecodeError:
                # Fallback: parse texto
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

# ---------------------------------------------------------------------------
# semantic_search (via Qdrant)
# ---------------------------------------------------------------------------
def semantic_search(query: str, top_k: int = 5) -> dict[str, Any]:
    """Busca semântica no code_index do Qdrant.

    Returns:
        {"ok": True, "results": [{"text": "...", "score": 0.9, "source": "file.py"}], "total": 3}
    """
    try:
        from jarvis.providers.vector_store import QdrantStore
        from jarvis.providers.llm import LLMClient

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
        if "Connect" in err_type or "Connection" in err_type or "Timeout" in err_type:
            msg = f"Qdrant daemon/connection unavailable ({err_type}): {e}"
        elif "NotFound" in str(e) or "not found" in str(e).lower():
            msg = f"Collection 'code_index' missing — run 'jarvis rag index' first"
        elif "Embedding" in err_type or "Model" in err_type:
            msg = f"Embedding generation failure ({err_type}): {e}"
        else:
            msg = f"Semantic search failure ({err_type}): {e}"
        return {"ok": False, "error": msg}


# ---------------------------------------------------------------------------
# Tool definitions para o agente
# ---------------------------------------------------------------------------

DEV_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file's content. Use offset/limit for large files.",
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
            "description": "Write content to a file (creates or overwrites). Creates backup.",
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
            "description": "Replace a string in a file. Preferred method for editing. Validates old string exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to project root"},
                    "old": {"type": "string", "description": "Exact string to find and replace"},
                    "new": {"type": "string", "description": "Replacement string"},
                    "allow_multiple": {"type": "boolean", "description": "Allow replacing multiple occurrences"},
                },
                "required": ["path", "old", "new"],
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
            "description": "Search for patterns in the codebase (grep).",
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
                    "pattern": {"type": "string", "description": "pytest -k pattern to filter tests"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)"},
                },
                "required": [],
            },
        },    },
    {
        "type": "function",
        "function": {
            "name": "run_linter",
            "description": "Run ruff linter on a file or directory and return issues.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or directory to lint (default: project root)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": "Search codebase semantically via Qdrant embeddings (slower but smarter than grep).",
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
            "name": "jarvis_command",
            "description": "Run a JARVIS CLI command (doctor, status, profile, metrics, etc).",
            "parameters": {
                "type": "object",
                "properties": {
                    "subcommand": {
                        "type": "string",
                        "description": "Subcommand: doctor, status, profile show, metrics, hwdetect, hwprofile",
                    },
                    "args": {
                        "type": "string",
                        "description": "Additional arguments (e.g. '--json', 'set verbosity verbose')",
                    },
                },
                "required": ["subcommand"],
            },
        },
    },
]


def jarvis_command(subcommand: str, args: str = "") -> dict[str, Any]:
    """Executa um comando jarvis CLI e retorna o resultado."""
    import subprocess
    cmd_parts = ["jarvis", subcommand] + (args.split() if args else [])
    try:
        result = subprocess.run(
            cmd_parts, capture_output=True, text=True, timeout=30,
        )
        output = result.stdout if result.returncode == 0 else result.stderr
        return {"ok": result.returncode == 0, "output": output[:3000]}
    except FileNotFoundError:
        # Fallback: python module
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


# ---------------------------------------------------------------------------
# Tool dispatcher (chamado pelo agente)
# ---------------------------------------------------------------------------
def handle_dev_tool(name: str, args: dict[str, Any]) -> str:
    """Despacha uma tool call do agente para a função correspondente."""
    import json

    handlers = {
        "read_file": lambda a: read_file(a["path"], a.get("offset", 0), a.get("limit", 2000)),
        "write_file": lambda a: write_file(a["path"], a["content"]),
        "str_replace": lambda a: str_replace(a["path"], a["old"], a["new"], a.get("allow_multiple", False)),
        "list_directory": lambda a: list_directory(a.get("path", "."), a.get("max_depth", 2)),
        "code_search": lambda a: code_search(a["pattern"], a.get("path", "."), max_results=a.get("max_results", 50)),
        "run_tests": lambda a: run_tests(a.get("test_path", "tests/"), a.get("pattern", ""), a.get("timeout", 120)),
        "run_linter": lambda a: run_linter(a.get("path", ".")),
        "semantic_search": lambda a: semantic_search(a["query"], a.get("top_k", 5)),
    }

    handler = handlers.get(name)
    if handler is None:
        return f"ERROR: unknown dev tool '{name}'"

    try:
        result = handler(args)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc}"
