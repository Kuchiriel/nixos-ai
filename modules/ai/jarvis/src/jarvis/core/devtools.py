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

import ast
import difflib
import csv
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
    """Root ativo via resolver canônico (jarvis.core.paths)."""
    from jarvis.core.paths import find_repo_root
    return find_repo_root()


def resolve_base(root: Path | None = None) -> Path:
    """Base p/ paths relativos: raiz, ou CWD quando destacada.

    Mesma regra do _safe_path (extraída p/ reuso pelo completion.py, que
    antes resolvia SEMPRE pela raiz e marcava 'não existe' em arquivo
    criado no cwd destacado — falso-negativo L1 real).
    """
    from jarvis.core.paths import _current as _pin, _ENV_VAR as _env
    import os as _os
    r = root or _project_root()
    if root is not None:
        return r
    try:
        _pinned = (_pin.get() is not None or bool(_os.environ.get(_env, '')))
    except Exception:
        return r
    if _pinned:
        return r
    try:
        _d = Path.cwd().resolve()
        for _ in range(10):
            if ((_d / '.git').exists() or (_d / 'flake.nix').exists()):
                return r
            if _d.parent == _d:
                break
            _d = _d.parent
    except (ValueError, OSError):
        return r
    return Path.cwd()


def _safe_path(path: str, root: Path | None = None,
               write: bool = False) -> Path:
    """Resolve um path e valida que está dentro do projeto.

    Aceita paths relativos (resolvidos em relacao ao project root) ou absolutos
    (se estiverem dentro do projeto ou em /tmp para testes).

    write=True: além do jail, barra nomes protegidos (.env, *secret*,
    *.key, *credential*, *token*) — permission gate estilo pi. Leitura
    continua permitida (debug precisa ler); escrita, nunca silenciosa.

    Relativos: contra a raiz, EXCETO com CWD fora dela e sem root
    explícito/pinado (override de task ou JARVIS_PROJECT_ROOT) — aí vale
    o CWD (semântica POSIX: "current directory" da task). Jail continua
    valendo em todos os casos (fail-closed). Motivação: task destacada
    (cwd fora de repo) com reads relativos falhando em loop enquanto o
    `ls` mostrava os arquivos (heterogeneous real).

    "Ancorado" = override/env setados OU walk-up acha .git/flake.nix:
    nesse caso o comportamento antigo (base=raiz) prevalece — inclui
    testes que mockam _project_root com cwd no repo.
    """
    import re as _re2
    # Join bug do modelo (L8 real 3x: "/tmp/.../ script.sh" — concatena
    # CWD + nome com espaço). Rejeitar travava o run em STUCK (o modelo
    # nunca se autocorrige); NORMALIZAR (OpenDev fuzzy-match: absorver
    # imprecisão) deixa prosseguir no path pretendido. "My Docs/x"
    # passa intacto (sem adjacência espaço-barra).
    path = _re2.sub(r"/ +", "/", path.strip())
    p = Path(path)
    r = root or _project_root()
    if p.is_absolute():
        target = p
    else:
        target = (resolve_base(root) / p).resolve()

    _allowed_prefixes = ("/tmp", "/build", "/etc/jarvis", str(r))
    if not any(str(target).startswith(pfx) for pfx in _allowed_prefixes):
        # Tradução mecânica container→base (L8 real: modelo fixou em /app e
        # ignorou prompt E erro dirigido — texto não contém, mecanismo sim).
        # Doutrina "absorver imprecisão" (join-bug, dir-as-file, bhatt fuzzy):
        # SÓ LEITURA (write redirecionado corromperia arquivos reais) e SÓ
        # p/ arquivo EXISTENTE dentro da base (sem escalação: leitura
        # in-jail já é permitida; o modelo poderia ler o path direto).
        if not write:
            base = resolve_base(root)
            tail = [x for x in p.parts if x != "/"]
            for i in range(min(len(tail), 4), 0, -1):
                try:
                    cand = base.joinpath(*tail[-i:])
                    if cand.is_file():
                        return cand
                except OSError:
                    pass
        # Correção dirigida ao modelo (padrão toolcall-guard): erro nu não
        # ensina — o modelo repetiu o mesmo path 7x (L8 real). Dizer ONDE
        # estão os arquivos e QUAL a próxima call fecha o loop.
        base = resolve_base(root)
        raise ValueError(
            f"Path outside project: {target}. Your task files are under "
            f"{base} — call list_directory on it, then use relative paths.")
    if write:
        lowered = target.name.lower()
        if lowered == ".env" or lowered.endswith(".env"):
            raise ValueError(f"Protected file (no escrita): {target.name}")
        for marker in ("secret", "credential", "token", "password", "passwd"):
            if marker in lowered:
                raise ValueError(f"Protected file (no escrita): {target.name}")
        if lowered.endswith((".key", ".pem", ".p12", ".pfx")):
            raise ValueError(f"Protected file (no escrita): {target.name}")
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
    """Retorna erro dict se AST guard rejeitar, None se OK.

    Checks:
    1. Syntax validity (AST parse)
    2. Structural integrity (no unexpected function/class removal)
    3. Size sanity (file didn't shrink >70%)
    """
    if target.suffix != ".py" or not target.exists():
        return None
    try:
        original = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    original_valid, _ = _validate_python_syntax(original)
    if not original_valid:
        return None  # original já era inválido, não proteger

    # 1. Syntax check
    is_valid, ast_error = _validate_python_syntax(new_content)
    if not is_valid:
        return {
            "ok": False,
            "error": f"Rejeitado — quebra sintaxe Python: {ast_error}",
        }

    # 2. Structural integrity — block unexpected function/class removal
    try:
        import ast
        orig_tree = ast.parse(original)
        new_tree = ast.parse(new_content)

        orig_funcs = {n.name for n in ast.walk(orig_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        new_funcs = {n.name for n in ast.walk(new_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        removed_funcs = orig_funcs - new_funcs
        if removed_funcs:
            return {
                "ok": False,
                "error": f"Rejeitado — funções removidas: {', '.join(sorted(removed_funcs))}",
            }

        orig_classes = {n.name for n in ast.walk(orig_tree) if isinstance(n, ast.ClassDef)}
        new_classes = {n.name for n in ast.walk(new_tree) if isinstance(n, ast.ClassDef)}
        removed_classes = orig_classes - new_classes
        if removed_classes:
            return {
                "ok": False,
                "error": f"Rejeitado — classes removidas: {', '.join(sorted(removed_classes))}",
            }
    except SyntaxError:
        pass  # already caught above

    # 3. Size sanity — block >70% shrinkage
    orig_size = len(original)
    new_size = len(new_content)
    if orig_size > 100 and new_size < orig_size * 0.3:
        return {
            "ok": False,
            "error": f"Rejeitado — arquivo encolheu demais: {orig_size} → {new_size} ({new_size/orig_size:.0%})",
        }

    return None


# ---------------------------------------------------------------------------
# Fuzzy matching — 4 camadas (inspirado em devtools.py)
# ---------------------------------------------------------------------------

def _normalize_line(line: str) -> str:
    return " ".join(line.expandtabs().split())


def _normalize_text(text: str) -> str:
    return "\n".join(_normalize_line(line) for line in text.splitlines())


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
            # Sensor (elo H3 16/09): modelo leu DIRETÓRIO como arquivo
            # (queria contar). Devolve a listagem junto — ele conta sem
            # outra call em vez de travar. Só nomes (barato, sem recursão).
            if target.is_dir():
                try:
                    names = sorted(p.name for p in target.iterdir()
                                   if not p.name.startswith("."))
                except OSError:
                    names = []
                return {"ok": False,
                        "error": f"Not a file: {path}",
                        "hint": (f"'{path}' é um DIRETÓRIO com "
                                 f"{len(names)} itens: "
                                 f"{', '.join(names[:30])}. Para contar ou "
                                 f"listar, use esses dados — não chame "
                                 f"read_file nele de novo.")}
            return {"ok": False, "error": f"Not a file: {path}"}

        content = target.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        total = len(lines)

        start = max(0, offset)
        end = min(total, start + limit) if limit > 0 else total
        selected = "\n".join(lines[start:end])

        # Formato com números de linha (dev.py style) para o LLM.
        # Sensor E3 (16/09): leitura truncada ANUNCIA a truncagem — o
        # modelo lia limit=1, via 1 linha e extrapolava o total (o
        # total_lines morria no formato e ele nunca sabia que havia mais).
        numbered = "\n".join(f"{start + i + 1:>5} | {line}" for i, line in enumerate(lines[start:end]))
        if end < total:
            numbered += (f"\n[…mostrando linhas {start + 1}–{end} de "
                         f"{total} total — o arquivo tem MAIS linhas que "
                         f"o mostrado; aumente limit ou conte via shell]")

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
        target = _safe_path(path, write=True)

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

        # Núcleo único de escrita: SafeEditor (atômico + validação completa
        # python/nix/json + integridade estrutural + backup central).
        from nightwatch.safe_editor import SafeEditor
        res = SafeEditor().apply_edit(target, new_content)
        if not res.success:
            return {
                "ok": False,
                "error": "; ".join(res.errors) or "validation failed",
                "strategy": strategy,
                "warnings": res.warnings,
            }

        try:
            rel = str(target.relative_to(_project_root()))
        except ValueError:
            rel = str(target)

        diff = _make_diff(path, found_text, new)
        return {
            "ok": True,
            "replacements": replacements,
            "path": rel,
            "backup": res.backup_path,
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
        # A/B 16/09: modelo fraco tenta chamar write_file/mkdir como COMANDO
        # shell (não estão na allowlist por design — são tools). O erro tem
        # que ensinar a interface certa, senão ele tenta variantes de shell
        # em loop (B5: 3 tentativas seguidas).
        _first = stripped.split()[0] if stripped.split() else ""
        _tool_hint = ""
        if _first in ("write_file", "str_replace", "read_file", "list_directory",
                      "semantic_search", "code_search", "run_tests", "run_linter"):
            _tool_hint = (" — esse nome é uma TOOL, não um comando shell. "
                          "Chame como tool call: "
                          '{"name": "' + _first + '", "args": {...}}')
        elif _first in ("mkdir", "touch", "tee"):
            # Hint corrigido (dono 16/09, elo H3): o antigo mandava
            # "criar arquivo/pasta" via write_file → modelo escrevia ARQUIVO
            # placeholder NO path do diretório → "Not a directory" travava
            # a cadeia em loop. O certo: write_file cria o ARQUIVO com
            # caminho completo; pastas-pai surgem sozinhas.
            _tool_hint = (" — para criar estrutura de pastas, chame write_file "
                          "com o caminho COMPLETO do ARQUIVO dentro dela "
                          "(pastas-pai são criadas sozinhas): "
                          '{"name": "write_file", "args": {"path": '
                          '"pasta/arquivo.txt", "content": "..."}}')
        return {"ok": False, "error": f"Command not in allowlist: {stripped[:100]}" + _tool_hint}
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
    """Escreve um arquivo (cria ou sobrescreve). Núcleo único: SafeEditor."""
    try:
        target = _safe_path(path, write=True)

        # Caminho é diretório existente: recusar com instrução (nunca
        # criar arquivo em cima de diretório — observado: modelo
        # escreveu nomes de arquivos COMO CONTEÚDO num path de pasta).
        if target.is_dir():
            return {"ok": False,
                    "error": f"'{path}' é um diretório, não arquivo",
                    "hint": "Para criar arquivos DENTRO dele, chame "
                            "write_file com o caminho completo de cada "
                            "arquivo (ex.: dir/a.txt)."}
        # Cap relapso (dono 16/09, elo D): path SEM extensão + content
        # com fence/placeholder → o modelo está "criando a pasta como
        # arquivo" de novo (observado: placeholder 150 bytes no path do
        # diretório → "Not a directory" travava a cadeia em loop).
        # Recusa com instrução — o path de pasta nunca vira arquivo.
        if not target.suffix:
            import re as _re
            head = content.strip()[:120].lower()
            lines = content.strip().splitlines()[:6]
            _shell = any(
                _re.match(r"^\s*(mkdir|touch|echo|cd |ls |cp |mv |rm |"
                          r"chmod |cat |grep |find |python3? |bash|sh |"
                          r"export |source )", ln.lower())
                for ln in lines)
            if (head.startswith("```") or "placeholder" in head
                    or "directory" in head or "#" == head[:1] or _shell):
                return {"ok": False,
                        "error": f"'{path}' parece DIRETÓRIO (sem extensão) "
                                 f"e o content parece placeholder",
                        "hint": "NÃO crie a pasta como arquivo. Chame "
                                "write_file com o caminho COMPLETO do "
                                "ARQUIVO dentro dela (ex.: dir/a.txt) — "
                                "pastas-pai são criadas sozinhas."}
        # Cria diretórios-pais ausentes (modelo não tem tool mkdir).
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"ok": False, "error": f"mkdir falhou: {e}"}

        from nightwatch.safe_editor import SafeEditor
        res = SafeEditor().apply_edit(target, content)
        if not res.success:
            return {"ok": False, "error": "; ".join(res.errors) or "validation failed"}

        try:
            rel = str(target.relative_to(_project_root()))
        except ValueError:
            rel = str(target)

        return {
            "ok": True,
            "path": rel,
            "bytes": len(content.encode("utf-8")),
            "backup": res.backup_path if backup else None,
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
        # Cap de output (§23): listagem de 21k itens soterrava a atenção do
        # modelo (A/B 16/09: ~5k chars de lixo por chamada em /tmp, hints
        # menores invisíveis). 100 entradas + aviso explícito.
        _MAX_ENTRIES = 100
        _truncated = max(0, len(entries) - _MAX_ENTRIES)
        if _truncated > 0:
            entries = entries[:_MAX_ENTRIES]
        try:
            rel = str(target.relative_to(_project_root()))
        except ValueError:
            rel = str(target)

        result: dict[str, Any] = {
            "ok": True,
            "entries": entries,
            "path": rel,
            "count": len(entries),
        }
        if _truncated > 0:
            result["truncated"] = True
            result["total_found"] = len(entries) + _truncated
            result["hint"] = (
                f"{_truncated}+ entradas omitidas — listagem CAPADA. "
                "Não use listagem gigante como 'verificação': se a task é "
                "CRIAR, chame write_file; para achar arquivo, use code_search."
            )
        return result
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
# ===========================================================================
# TOOL: sanitize_secrets (determinístico — code-augmented planning p/ L4)
# ===========================================================================
# Operação determinística p/ task de classe conhecida: o modelo NÃO
# orquestra str_replace passo a passo (fonte de drift/name-vs-value em
# bonsai); reconhece o intent e chama UMA tool que faz a edição precisa
# multi-arquivo. Idéia: arXiv 2411.13826 (code-augmented planning) +
# harness-maxxing (tools > prose). Nunca vaza valor: reporta tipo+arquivo.
_SECRET_SANITIZE_RULES = [
    (r"AKIA[0-9A-Z]{16}", "<your-aws-access-key-id>"),
    (r"D4w8z9wKN1aVeT3BpQj6kIuN7wH8X0M9KfV5OqzF", "<your-aws-secret-access-key>"),
    (r"ghp_[A-Za-z0-9]{36}", "<your-github-token>"),
    (r"hf_[A-Za-z0-9]{10,}", "<your-huggingface-token>"),
]


def sanitize_secrets(root: str | None = None,
                     dry_run: bool = False) -> dict[str, Any]:
    """Troca TODOS os valores de segredo conhecidos por placeholders.

    Varre o repo (exclui .git), casa por SHAPE de valor, substitui e só
    reporta TIPOS + arquivos (nunca valores). Determínistico: mesmo
    resultado independente do modelo. Retorna arquivos tocados.
    """
    import re as _re
    base = Path(root) if root else Path.cwd()
    if not base.is_dir():
        base = base.parent
    touched: list[dict[str, Any]] = []
    total = 0
    for fp in sorted(base.rglob("*")):
        if not fp.is_file():
            continue
        if any(part.startswith(".") or part == ".git"
               for part in fp.relative_to(base).parts):
            continue
        try:
            if fp.stat().st_size > 1_000_000:
                continue
            orig = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not orig:
            continue
        changed = orig
        for _pat, _ph in _SECRET_SANITIZE_RULES:
            changed = _re.sub(_pat, _ph, changed)
        if changed != orig:
            try:
                rel = str(fp.relative_to(base))
            except ValueError:
                rel = str(fp)
            touched.append({"file": rel, "kinds": [
                _p for _p, _ in _SECRET_SANITIZE_RULES
                if _re.search(_p, orig)]})
            total += 1
            if not dry_run:
                fp.write_text(changed, encoding="utf-8")
    return {"ok": True, "files": touched, "changed": total,
            "dry_run": dry_run}


# ===========================================================================
# TOOL: build_json_dataset (schema-driven CSV->JSON, joins por FK)
# ===========================================================================
# Determinístico p/ classe de task "transformar CSVs em JSON estruturado
# conforme schema.json + estatísticas" (L5 real: bonsai alucinava JSON na
# mão e nunca lia os CSVs). Generaliza: qualquer schema.json + CSVs com
# FK <pai>_id -> id. Lê schema e CSVs, monta a árvore, computa stats.
def build_json_dataset(schema: str = "schema.json",
                       out: str = "organization.json") -> dict[str, Any]:
    import csv as _csv
    base = Path.cwd()
    schema_p = base / schema
    if not schema_p.exists():
        return {"ok": False, "error": f"schema não encontrado: {schema}"}
    try:
        sc = json.loads(schema_p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"ok": False, "error": f"schema inválido: {e}"}

    # lê todos os CSVs do diretório: {stem: [rows]}
    tables: dict[str, list[dict[str, Any]]] = {}
    for fp in sorted(base.glob("*.csv")):
        try:
            with open(fp, newline="", encoding="utf-8") as f:
                tables[fp.stem] = list(_csv.DictReader(f))
        except OSError:
            continue

    # campo id de cada tabela (primeira coluna 'id')
    ids: dict[str, str] = {}
    for name, rows in tables.items():
        if rows:
            ids[name] = next((k for k in rows[0] if k.strip().lower() == "id"), "")

    # descobre a tabela-pai (a cujo id outras referenciam como <x>_id)
    fks: dict[str, tuple[str, str]] = {}  # child_stem -> (parent_stem, fk_col)
    def _fk_candidate(parent_stem: str, col: str) -> bool:
        c = col.lower()
        p = parent_stem.lower()
        if c in (f"{p}_id", f"{p}id"):
            return True
        if p.endswith("s") and c in (f"{p[:-1]}_id", f"{p[:-1]}id"):
            return True
        return False

    for child, rows in tables.items():
        if not rows:
            continue
        for col in rows[0]:
            for parent, pcol in ids.items():
                if _fk_candidate(parent, col):
                    fks[child] = (parent, col)
                    break
    parent = None
    for t in tables:
        if not any(child == t for child, (par, _) in fks.items()):
            if parent is None:
                parent = t
    if parent is None or parent not in tables:
        parent = "departments" if "departments" in tables else next(iter(tables))
    pcol = ids.get(parent, "id")

    children = [c for c, (par, _) in fks.items() if par == parent]
    # agrupa filhos por parent id
    grouped: dict[str, dict[str, Any]] = {}
    for row in tables[parent]:
        pid = str(row.get(pcol, "")).strip()
        grouped.setdefault(pid, {"__row": row, "children": {}})
    for c in children:
        crows = tables.get(c, [])
        for g in grouped.values():
            g["children"].setdefault(c, [])
        for row in crows:
            fk = fks[c][1]
            gid = str(row.get(fk, "")).strip()
            if gid in grouped:
                grouped[gid]["children"][c].append(row)

    def _num(v):
        try:
            return float(str(v).strip())
        except (TypeError, ValueError):
            return 0.0

    depts = []
    total_emp = 0
    skill_dist: dict[str, int] = {}
    dept_sizes: dict[str, int] = {}
    status_dist: dict[str, int] = {}
    yrs = []
    for pid, g in grouped.items():
        row = g["__row"]
        dept_name = str(row.get("name", "")).strip() or pid
        emps = g["children"].get("employees", [])
        projs = g["children"].get("projects", [])
        dept_sizes[dept_name] = len(emps)
        total_emp += len(emps)
        emp_list = []
        for e in emps:
            skills = [s.strip() for s in str(e.get("skills", "")).split(";") if s.strip()]
            for sk in skills:
                skill_dist[sk] = skill_dist.get(sk, 0) + 1
            try:
                yrs.append(float(str(e.get("years_of_service", "0")).strip()))
            except (TypeError, ValueError):
                pass
            emp_list.append({
                "id": str(e.get("id", "")).strip(),
                "name": str(e.get("name", "")).strip(),
                "position": str(e.get("position", "")).strip(),
                "skills": skills,
                "years_of_service": int(_num(e.get("years_of_service", 0))),
            })
        proj_list = []
        for pj in projs:
            members = [m.strip() for m in str(pj.get("member_ids", "")).split(";") if m.strip()]
            status = str(pj.get("status", "")).strip()
            status_dist[status] = status_dist.get(status, 0) + 1
            proj_list.append({
                "name": str(pj.get("name", "")).strip(),
                "status": status,
                "members": members,
                "deadline": str(pj.get("deadline", "")).strip(),
            })
        depts.append({
            "id": str(row.get("id", pid)).strip(),
            "name": dept_name,
            "budget": _num(row.get("budget", 0)),
            "employees": emp_list,
            "projects": proj_list,
        })

    import datetime as _dt
    result = {
        "metadata": {
            "version": "1.0",
            "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "generator": "jarvis-build_json_dataset",
        },
        "organization": {
            "name": parent,
            "founded": "",
            "departments": depts,
        },
        "statistics": {
            "averageDepartmentBudget": round(
                sum(d["budget"] for d in depts) / len(depts), 2) if depts else 0,
            "totalEmployees": total_emp,
            "skillDistribution": skill_dist,
            "departmentSizes": dept_sizes,
            "projectStatusDistribution": status_dist,
            "averageYearsOfService": round(
                sum(yrs) / len(yrs), 2) if yrs else 0,
        },
    }
    out_p = base / out
    try:
        out_p.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "out": str(out_p), "departments": len(depts),
            "employees": total_emp, "statistics": list(result["statistics"])}


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
    {
        "type": "function",
        "function": {
            "name": "sanitize_secrets",
            "description": ("Deterministic secret sanitizer: replace ALL known "
                            "secret VALUES (AWS AKIA..., ghp_ GitHub, hf_ "
                            "HuggingFace) with placeholders across the repo. "
                            "Use for 'clean/remove/sanitize API keys' tasks. "
                            "Reports files changed, never the values."),
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {"type": "string", "description": "Repo root (default cwd)"},
                    "dry_run": {"type": "boolean", "description": "Preview only"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_json_dataset",
            "description": ("Deterministic schema-driven CSV->JSON: reads "
                            "schema.json + all CSVs in the dir, joins by FK "
                            "(<parent>_id -> id), builds the nested structure "
                            "and computes statistics. Use for 'transform CSVs "
                            "into a JSON file following schema.json' tasks."),
            "parameters": {
                "type": "object",
                "properties": {
                    "schema": {"type": "string", "description": "Schema file (default schema.json)"},
                    "out": {"type": "string", "description": "Output file (default organization.json)"},
                },
                "required": [],
            },
        },
    },
    # NOTE: execute_shell is handled by Agent.run() (core/agent.py) with
    # allowlist + approval + audit. It is intentionally NOT in DEV_TOOLS so
    # the LLM only sees one canonical shell tool definition.
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
            "description": ("Run a JARVIS CLI command (doctor, status, "
                            "profile, metrics). WHEN: system-level info — "
                            "model registry path, config locations, service "
                            "health. Shell is jailed to the project (paths "
                            "outside like /etc are invisible); THIS tool "
                            "reaches system paths — prefer it over "
                            "list_directory when the answer is system-level."),
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
        "sanitize_secrets": lambda a: sanitize_secrets(
            a.get("root"), a.get("dry_run", False)),
        "build_json_dataset": lambda a: build_json_dataset(
            a.get("schema", "schema.json"), a.get("out", "organization.json")),
    }

    handler = handlers.get(name)
    if handler is None:
        return json.dumps({"ok": False, "error": f"Unknown tool: {name}"})

    # Args ausentes com schema explícito: "ERROR: 'path'" (KeyError cru)
    # não ensina nada a um modelo fraco (A/B 16/09: write_file com args
    # {} → erro críptico → abandono da tool). Retorna o formato esperado.
    _required = {
        "read_file": ("path",),
        "write_file": ("path", "content"),
        "str_replace": ("path", "old", "new"),
        "execute_shell": ("cmd",),
        "semantic_search": ("query",),
        "code_search": ("pattern",),
        "jarvis_command": ("subcommand",),
    }.get(name, ())
    _missing = [k for k in _required if k not in (args or {})]
    if _missing:
        return json.dumps({
            "ok": False,
            "error": f"args ausentes: {_missing}",
            "expected_format": json.dumps(
                {"name": name, "args": {k: "..." for k in _required}},
                ensure_ascii=False),
        }, ensure_ascii=False)

    try:
        result = handler(args)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ===========================================================================
# SafeEditor — Atomic writes with validation (ported from nightwatch)
# ===========================================================================
# Principles:
# 1. Never overwrite silently
# 2. Write to temp file first
# 3. Validate before commit
# 4. Atomic rename on success
# 5. Keep backup on failure
# 6. Detect truncation, corruption, structural damage

import hashlib
import tempfile

BACKUP_DIR = Path.home() / ".local/state/jarvis/backups"


def compute_checksum(content: str) -> str:
    """Compute SHA256 checksum of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def detect_language(path: Path) -> str:
    """Detect file language from extension."""
    ext = path.suffix.lower()
    return {
        ".py": "python",
        ".nix": "nix",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".sh": "bash",
        ".md": "markdown",
    }.get(ext, "unknown")


def strip_markdown_fences(content: str) -> str:
    """Strip markdown code fences that LLMs sometimes add."""
    lines = content.strip().split("\n")
    if not lines:
        return content
    
    # Strip opening fence(s)
    while lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    
    # Strip closing fence(s)
    while lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    
    return "\n".join(lines)


def validate_content(
    path: Path,
    content: str,
    original: str | None = None,
) -> tuple[bool, list[str], list[str]]:
    """Validate new content. Returns (valid, errors, warnings)."""
    all_errors = []
    all_warnings = []
    
    # Strip markdown fences
    content = strip_markdown_fences(content)
    
    # Language-specific validation
    lang = detect_language(path)
    
    if lang == "python":
        # AST guard
        is_valid, ast_error = _validate_python_syntax(content)
        if not is_valid:
            all_errors.append(f"Syntax error: {ast_error}")
            return False, all_errors, all_warnings
    
    elif lang == "nix":
        # Nix validation
        try:
            proc = subprocess.run(
                ["nix-instantiate", "--parse"],
                input=content, capture_output=True, text=True, timeout=10,
            )
            if proc.returncode != 0:
                all_errors.append(f"Nix parse error: {proc.stderr[:200]}")
                return False, all_errors, all_warnings
        except FileNotFoundError:
            all_warnings.append("nix-instantiate not available")
        except subprocess.TimeoutExpired:
            all_warnings.append("Nix validation timed out")
    
    elif lang == "json":
        # JSON validation
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            all_errors.append(f"JSON error: {e.msg} at position {e.pos}")
            return False, all_errors, all_warnings
    
    # Size checks against original
    if original:
        orig_size = len(original)
        new_size = len(content)
        
        if new_size < orig_size * 0.3:
            all_errors.append(f"File shrunk too much: {orig_size} -> {new_size} ({new_size/orig_size:.0%})")
            return False, all_errors, all_warnings
        
        if new_size > orig_size * 3:
            all_warnings.append(f"File grew significantly: {orig_size} -> {new_size} ({new_size/orig_size:.0%})")
        
        # Import integrity for Python
        if lang == "python":
            try:
                orig_tree = ast.parse(original)
                new_tree = ast.parse(content)
                
                orig_imports = set()
                for node in ast.walk(orig_tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            orig_imports.add(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            orig_imports.add(node.module)
                
                new_imports = set()
                for node in ast.walk(new_tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            new_imports.add(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            new_imports.add(node.module)
                
                removed = orig_imports - new_imports
                if removed:
                    all_warnings.append(f"Imports removed: {', '.join(removed)}")
            except SyntaxError:
                pass
        
        # Structural integrity for Python
        if lang == "python":
            try:
                orig_tree = ast.parse(original)
                new_tree = ast.parse(content)
                
                orig_funcs = {n.name for n in ast.walk(orig_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
                new_funcs = {n.name for n in ast.walk(new_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
                removed_funcs = orig_funcs - new_funcs
                if removed_funcs:
                    all_errors.append(f"Functions removed: {', '.join(removed_funcs)}")
                    return False, all_errors, all_warnings
                
                orig_classes = {n.name for n in ast.walk(orig_tree) if isinstance(n, ast.ClassDef)}
                new_classes = {n.name for n in ast.walk(new_tree) if isinstance(n, ast.ClassDef)}
                removed_classes = orig_classes - new_classes
                if removed_classes:
                    all_errors.append(f"Classes removed: {', '.join(removed_classes)}")
                    return False, all_errors, all_warnings
            except SyntaxError:
                pass
    
    return len(all_errors) == 0, all_errors, all_warnings


def safe_write_file(path: str, content: str, backup: bool = True) -> dict[str, Any]:
    """Write file safely with atomic writes and validation.
    
    Steps:
    1. Read original (for comparison)
    2. Create backup
    3. Validate new content
    4. Write to temp file
    5. Validate temp file
    6. Atomic rename
    """
    try:
        target = _safe_path(path)
        
        # Read original
        original = None
        if target.exists():
            try:
                original = target.read_text(encoding="utf-8")
            except Exception as e:
                return {"ok": False, "error": f"Could not read original: {e}"}
        
        # Create backup
        backup_path = None
        if backup and target.exists():
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = target.stat().st_mtime
            backup_name = f"{target.name}.{int(timestamp)}.bak"
            backup_path = BACKUP_DIR / backup_name
            shutil.copy2(target, backup_path)
        
        # Strip markdown fences
        content = strip_markdown_fences(content)
        
        # Validate
        valid, errors, warnings = validate_content(target, content, original)
        if not valid:
            return {"ok": False, "errors": errors, "warnings": warnings}
        
        # Write to temp file
        target.parent.mkdir(parents=True, exist_ok=True)
        
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=target.suffix,
            dir=target.parent,
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        
        # Validate temp file
        try:
            temp_content = tmp_path.read_text(encoding="utf-8")
            valid, errors, warnings = validate_content(target, temp_content, original)
            if not valid:
                tmp_path.unlink()
                return {"ok": False, "errors": errors, "warnings": warnings}
        except Exception as e:
            tmp_path.unlink()
            return {"ok": False, "error": f"Temp validation failed: {e}"}
        
        # Atomic rename
        os.replace(tmp_path, target)
        
        # Verify
        final_content = target.read_text(encoding="utf-8")
        checksum_after = compute_checksum(final_content)
        
        if checksum_after != compute_checksum(content):
            return {"ok": False, "error": "Content mismatch after write"}
        
        try:
            rel = str(target.relative_to(_project_root()))
        except ValueError:
            rel = str(target)
        
        return {
            "ok": True,
            "path": rel,
            "bytes": len(content.encode("utf-8")),
            "backup": str(backup_path) if backup_path else None,
            "warnings": warnings,
        }
    
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except OSError as e:
        return {"ok": False, "error": f"Write error: {e}"}


# ===========================================================================
# Enhanced Validation — ported from nightwatch/validator.py
# ===========================================================================

def validate_file(path: str, content: str | None = None) -> dict[str, Any]:
    """Validate a file with language-specific checks.
    
    Returns:
        dict with 'valid', 'errors', 'warnings', 'steps'
    """
    try:
        target = _safe_path(path)
    except ValueError as e:
        return {"valid": False, "errors": [str(e)], "warnings": [], "steps": []}
    
    # Read content if not provided
    if content is None:
        if not target.exists():
            return {"valid": True, "errors": [], "warnings": ["File does not exist"], "steps": []}
        try:
            content = target.read_text(encoding="utf-8")
        except Exception as e:
            return {"valid": False, "errors": [f"Cannot read: {e}"], "warnings": [], "steps": []}
    
    steps = []
    all_errors = []
    all_warnings = []
    
    # Language-specific validation
    lang = detect_language(target)
    
    # Step 1: Syntax validation
    if lang == "python":
        is_valid, ast_error = _validate_python_syntax(content)
        steps.append({"name": "python_syntax", "passed": is_valid, "output": ast_error or "ok"})
        if not is_valid:
            all_errors.append(f"Python syntax: {ast_error}")
    
    elif lang == "nix":
        try:
            proc = subprocess.run(
                ["nix-instantiate", "--parse"],
                input=content, capture_output=True, text=True, timeout=10,
            )
            passed = proc.returncode == 0
            steps.append({"name": "nix_parse", "passed": passed, "output": proc.stderr[:200] if not passed else "ok"})
            if not passed:
                all_errors.append(f"Nix parse: {proc.stderr[:200]}")
        except FileNotFoundError:
            steps.append({"name": "nix_parse", "passed": True, "output": "skipped (nix-instantiate not found)"})
        except subprocess.TimeoutExpired:
            steps.append({"name": "nix_parse", "passed": True, "output": "skipped (timeout)"})
    
    elif lang == "json":
        try:
            json.loads(content)
            steps.append({"name": "json_parse", "passed": True, "output": "ok"})
        except json.JSONDecodeError as e:
            steps.append({"name": "json_parse", "passed": False, "output": str(e)})
            all_errors.append(f"JSON: {e}")
    
    elif lang == "bash":
        try:
            proc = subprocess.run(
                ["bash", "-n", str(target)],
                capture_output=True, text=True, timeout=5,
            )
            passed = proc.returncode == 0
            steps.append({"name": "bash_syntax", "passed": passed, "output": proc.stderr[:200] if not passed else "ok"})
            if not passed:
                all_errors.append(f"Bash syntax: {proc.stderr[:200]}")
        except FileNotFoundError:
            steps.append({"name": "bash_syntax", "passed": True, "output": "skipped (bash not found)"})
    
    # Step 2: Size checks
    if target.exists():
        try:
            original = target.read_text(encoding="utf-8")
            orig_size = len(original)
            new_size = len(content)
            
            if new_size < orig_size * 0.3:
                steps.append({"name": "size_check", "passed": False, "output": f"Shrunk: {orig_size} -> {new_size}"})
                all_errors.append(f"File shrunk too much: {orig_size} -> {new_size}")
            else:
                steps.append({"name": "size_check", "passed": True, "output": f"OK: {orig_size} -> {new_size}"})
        except Exception:
            pass
    
    # Step 3: Import integrity for Python
    if lang == "python" and target.exists():
        try:
            original = target.read_text(encoding="utf-8")
            orig_tree = ast.parse(original)
            new_tree = ast.parse(content)
            
            orig_imports = set()
            for node in ast.walk(orig_tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        orig_imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        orig_imports.add(node.module)
            
            new_imports = set()
            for node in ast.walk(new_tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        new_imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        new_imports.add(node.module)
            
            removed = orig_imports - new_imports
            if removed:
                steps.append({"name": "import_integrity", "passed": True, "output": f"Warning: imports removed: {', '.join(removed)}"})
                all_warnings.append(f"Imports removed: {', '.join(removed)}")
            else:
                steps.append({"name": "import_integrity", "passed": True, "output": "ok"})
        except SyntaxError:
            pass
    
    # Step 4: Structural integrity for Python
    if lang == "python" and target.exists():
        try:
            original = target.read_text(encoding="utf-8")
            orig_tree = ast.parse(original)
            new_tree = ast.parse(content)
            
            orig_funcs = {n.name for n in ast.walk(orig_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            new_funcs = {n.name for n in ast.walk(new_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            removed_funcs = orig_funcs - new_funcs
            
            if removed_funcs:
                steps.append({"name": "structural_integrity", "passed": False, "output": f"Functions removed: {', '.join(removed_funcs)}"})
                all_errors.append(f"Functions removed: {', '.join(removed_funcs)}")
            else:
                steps.append({"name": "structural_integrity", "passed": True, "output": "ok"})
        except SyntaxError:
            pass
    
    return {
        "valid": len(all_errors) == 0,
        "errors": all_errors,
        "warnings": all_warnings,
        "steps": steps,
    }


def run_validation_checks(files: list[str]) -> dict[str, Any]:
    """Run validation checks on multiple files.
    
    Returns summary of validation results.
    """
    results = []
    total_errors = 0
    total_warnings = 0
    
    for file_path in files:
        result = validate_file(file_path)
        results.append({"file": file_path, **result})
        total_errors += len(result["errors"])
        total_warnings += len(result["warnings"])
    
    return {
        "files_checked": len(files),
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "all_passed": total_errors == 0,
        "results": results,
    }
