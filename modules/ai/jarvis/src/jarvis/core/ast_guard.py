"""AST Guard — proteção contra corrupção de código pelo SLM.

Inspirado no compiler_expert.py do legado (JARVIS V21).
Valida sintaxe Python com ast.parse() ANTES de aplicar str_replace.
Se a edição quebrar a sintaxe, rejeita e informa o erro ao SLM.

Padrão do legado:
  generate → validate → if fail → feed error back → retry (max 3x)

Nossa adaptação:
  str_replace → ast_validate(target_file) → if fail → revert + report error

Poneglyph Protocol (AST Hash Cache):
  Antes de ast.parse(), verifica o cache de hashes SHA-256.
  Se o hash bater: arquivo não mudou → bypass (ganho de performance).
  Se divergir: roda ast.parse() → grava novo hash se válido.
"""
from __future__ import annotations

import ast
import os
import shutil


def validate_python_syntax(code: str) -> tuple[bool, str]:
    """Valida sintaxe Python com ast.parse().

    Poneglyph: usa cache de hashes para bypass quando possível.

    Returns:
        (is_valid, error_message)
    """
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        msg = f"Linha {e.lineno}, Col {e.offset}: {e.msg}"
        return False, msg


def validate_python_syntax_cached(code: str, filepath: str = "") -> tuple[bool, str]:
    """Valida com cache de hashes — bypass se o hash bater.

    Se filepath não for fornecido, valida sem cache (fallback).

    Returns:
        (is_valid, error_message)
    """
    if not filepath:
        return validate_python_syntax(code)

    try:
        from jarvis.core.ast_cache import get_ast_cache
        cache = get_ast_cache()

        # Se o hash bater, arquivo não mudou → bypass
        if cache.is_valid(filepath, code):
            return True, ""

        # Hash divergiu → roda validação completa
        is_valid, error = validate_python_syntax(code)

        # Só grava no cache se for válido
        if is_valid:
            cache.mark_valid(filepath, code)

        return is_valid, error
    except ImportError:
        # ast_cache não disponível → fallback sem cache
        return validate_python_syntax(code)


def validate_file_syntax(filepath: str) -> tuple[bool, str]:
    """Valida sintaxe de um arquivo Python.
    
    Returns:
        (is_valid, error_message)
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            code = f.read()
        return validate_python_syntax(code)
    except FileNotFoundError:
        return False, f"Arquivo não encontrado: {filepath}"
    except Exception as e:
        return False, f"Erro ao ler arquivo: {e}"


def safe_str_replace(
    filepath: str,
    old: str,
    new: str,
    create_backup: bool = True,
) -> dict:
    """str_replace com guard AST — só aplica se a sintaxe continuar válida.
    
    Fluxo (inspirado no ForensicVerificationLoop do legado):
    1. Lê o arquivo atual
    2. Aplica a substituição em memória
    3. Valida a sintaxe do resultado com ast.parse()
    4. Se válido: aplica no arquivo real (+ backup)
    5. Se inválido: rejeita e retorna o erro
    
    Returns:
        {"ok": True, "replacements": N} ou
        {"ok": False, "error": "...", "ast_error": "..."}
    """
    filepath = os.path.realpath(filepath)
    
    # Lê o arquivo original
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            original = f.read()
    except FileNotFoundError:
        return {"ok": False, "error": f"Arquivo não encontrado: {filepath}"}
    
    # Verifica se old existe no arquivo
    if old not in original:
        return {"ok": False, "error": "Texto 'old' não encontrado no arquivo"}
    
    # Aplica a substituição em memória
    result = original.replace(old, new, 1)
    
    # Valida sintaxe do resultado
    is_valid, ast_error = validate_python_syntax(result)
    
    if not is_valid:
        return {
            "ok": False,
            "error": f"Edição rejeitada — quebra sintaxe Python",
            "ast_error": ast_error,
        }
    
    # Cria backup se solicitado
    if create_backup:
        backup_path = filepath + ".bak"
        try:
            shutil.copy2(filepath, backup_path)
        except Exception:
            pass  # Backup é best-effort
    
    # Aplica no arquivo real
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(result)
    except Exception as e:
        return {"ok": False, "error": f"Erro ao escrever arquivo: {e}"}
    
    count = original.count(old)
    return {"ok": True, "replacements": 1, "ast_validated": True}


def safe_write_file(
    filepath: str,
    content: str,
    create_backup: bool = True,
) -> dict:
    """write_file com guard AST — só cria se a sintaxe for válida."""
    filepath = os.path.realpath(filepath)
    
    is_valid, ast_error = validate_python_syntax(content)
    if not is_valid:
        return {
            "ok": False,
            "error": f"Arquivo rejeitado — sintaxe Python inválida",
            "ast_error": ast_error,
        }
    
    # Backup do arquivo existente
    if create_backup and os.path.exists(filepath):
        try:
            shutil.copy2(filepath, filepath + ".bak")
        except Exception:
            pass
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "bytes": len(content.encode("utf-8")), "ast_validated": True}
    except Exception as e:
        return {"ok": False, "error": f"Erro ao escrever: {e}"}


def format_ast_error_for_llm(error: str, original_code: str = "", new_code: str = "") -> str:
    """Formata erro AST para o SLM entender e corrigir.
    
    Inspirado no _build_refinement_prompt do compiler_expert.py do legado.
    """
    lines = [
        "ERRO DE SINTAXE PYTHON DETECTADO:",
        f"  {error}",
        "",
        "CORRIJA O CÓDIGO E TENTE NOVAMENTE.",
        "DICA: verifique indentação, dois-pontos, parênteses e aspas.",
    ]
    
    if original_code and new_code:
        lines.extend([
            "",
            "CÓDIGO ORIGINAL (válido):",
            f"```python",
            original_code[:500],
            f"```",
            "",
            "CÓDIGO PROPOSTO (inválido):",
            f"```python",
            new_code[:500],
            f"```",
        ])
    
    return "\n".join(lines)
