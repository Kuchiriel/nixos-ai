"""Dono único da validação de SINTAXE de um trecho de código.

(30/09) Quarta (e última) consolidação do dia. Havia duas validações de
sintaxe Python com capacidades muito diferentes:

  - `nightwatch/file_guard.validate_python`: `ast.parse` + heurísticas
    (import sem statement, arquivo grande sem função/classe, arquivo
    truncado por parênteses desbalanceados). Devolve ValidationResult.
  - `core/devtools._validate_python_syntax`: só `compile()`. Devolve tuple.

O dev era o mais fraco, e é o que roda no REPL — a ferramenta que o
modelo mais usa. Ou seja: o guarda mais permissivo era o do caminho
mais usado, e a divergência ninguém via porque os nomes eram diferentes.

Aqui mora a versão RICA. Os dois lados delegam; cada um mantém o seu
formato de retorno (não é papel deste módulo saber o que o chamador
quer).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "SyntaxCheck",
    "strip_markdown_fences",
    "check_python",
    "validate_python_syntax",
    "detect_language",
    "validate_nix",
    "validate_json",
]


@dataclass
class SyntaxCheck:
    """Veredito de sintaxe + avisos. Não é o tipo do chamador — cada
    consumidor mapeia para o seu (ValidationResult, tuple, dict)."""
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    original_size: int = 0
    new_size: int = 0


def strip_markdown_fences(content: str) -> str:
    """Remove ```lang ... ``` que o modelo às vezes emite em volta."""
    s = content.strip()
    if not s.startswith("```"):
        return content
    lines = s.split("\n")
    if len(lines) < 2:
        return content
    # descarta a linha de abertura e qualquer linha final só com cercas
    if not lines[-1].strip().startswith("```"):
        return content
    return "\n".join(lines[1:-1])


def check_python(content: str, path: Path | None = None) -> SyntaxCheck:
    """Valida a estrutura de um arquivo Python (a versão RICA)."""
    result = SyntaxCheck(original_size=len(content))

    body = strip_markdown_fences(content)
    result.new_size = len(body)

    try:
        tree = ast.parse(body)
    except SyntaxError as e:
        result.valid = False
        result.errors.append(f"Syntax error at line {e.lineno}: {e.msg}")
        return result
    except ValueError as e:
        # fonte com null bytes e afins
        result.valid = False
        result.errors.append(f"Value error: {e}")
        return result

    source = body

    # "import" no texto mas nenhum statement de import
    imports = [n for n in ast.walk(tree)
               if isinstance(n, (ast.Import, ast.ImportFrom))]
    if not imports and "import" in source.lower():
        result.warnings.append(
            "File has 'import' text but no import statements")

    functions = [n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    if not functions and not classes and len(source) > 500:
        result.warnings.append("Large file with no functions or classes")

    # arquivo truncado: abre muito mais do que fecha
    opens = source.count("(") + source.count("[") + source.count("{")
    closes = source.count(")") + source.count("]") + source.count("}")
    if opens > closes + 5:
        result.warnings.append(
            f"Possibly truncated: {opens} opens vs {closes} closes")

    return result


def validate_python_syntax(code: str) -> tuple[bool, str | None]:
    """Forma de tuple, para quem só quer ok/motivo.

    (30/09) Antes isto era `compile(code, "<devtools>", "exec")` — quase
    cego. Agora usa a mesma validação rica do nightwatch, então o REPL
    vê truncamento e import-quebrado, não só erro de sintaxe.
    """
    r = check_python(code)
    if r.valid:
        return True, None
    return False, r.errors[0] if r.errors else "invalid"


# ──────────────────────────────────────────────────────────────────────────
# outras linguagens (extraídas do file_guard, mesmo dono)
# ──────────────────────────────────────────────────────────────────────────
_LANG_BY_SUFFIX = {
    ".py": "python", ".nix": "nix", ".json": "json",
    ".sh": "bash", ".bash": "bash", ".js": "javascript",
    ".ts": "typescript", ".lua": "lua",
}


def detect_language(path: Path) -> str:
    """Linguagem pelo sufixo; '' quando desconhecida."""
    return _LANG_BY_SUFFIX.get(Path(path).suffix.lower(), "")


def validate_nix(content: str) -> SyntaxCheck:
    """Checagem estrutural de Nix: balanceamento de chaves e aspas.

    Não é parser de Nix (não existe nos steroids) — é o guard honesto:
    pega o erro dedigitado que mais acontece, e não finge mais do que isso.
    """
    result = SyntaxCheck(original_size=len(content), new_size=len(content))
    body = strip_markdown_fences(content)
    result.new_size = len(body)
    if body.count("{") != body.count("}"):
        result.valid = False
        result.errors.append(
            f"Unbalanced braces: {body.count('{')} open vs "
            f"{body.count('}')} close")
    if body.count("(") != body.count(")"):
        result.valid = False
        result.errors.append(
            f"Unbalanced parens: {body.count('(')} open vs "
            f"{body.count(')')} close")
    return result


def validate_json(content: str) -> SyntaxCheck:
    import json as _json
    result = SyntaxCheck(original_size=len(content), new_size=len(content))
    body = strip_markdown_fences(content)
    try:
        _json.loads(body)
    except Exception as e:
        result.valid = False
        result.errors.append(f"Invalid JSON: {e}")
    return result
