"""FileGuard — Structural validation layer for the Nightwatch harness.

Prevents:
- Markdown fences in .py files
- Missing imports
- Truncated files
- Functions disappearing
- Invalid syntax
- Import integrity violations
"""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class ValidationResult:
    """Result of file validation."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    original_size: int = 0
    new_size: int = 0


def detect_language(path: Path) -> str:
    """(30/09) DELEGA para `jarvis.core.syntax.detect_language` — o dono único."""
    from jarvis.core.syntax import detect_language as _dl
    return _dl(path)


def strip_markdown_fences(content: str) -> str:
    """(30/09) DELEGA para `jarvis.core.syntax.strip_markdown_fences` — o dono único."""
    from jarvis.core.syntax import strip_markdown_fences as _smf
    return _smf(content)


def validate_python(content: str, path: Path | None = None) -> ValidationResult:
    """(30/09) DELEGA para `jarvis.core.syntax.check_python` — o dono único.

    A versão Rica (ast + heurísticas de import/truncamento) morava AQUI e
    só aqui; o `core/devtools._validate_python_syntax` tinha um `compile()`
    quase cego. Guarda mais permissivo no caminho mais usado (o REPL), e
    ninguém via porque os nomes eram diferentes. Agora os dois usam a
    mesma política, e este só mapeia o veredito para ValidationResult.
    """
    from jarvis.core.syntax import check_python
    r = check_python(content, path)
    return ValidationResult(
        valid=r.valid,
        original_size=r.original_size,
        new_size=r.new_size,
        errors=list(r.errors),
        warnings=list(r.warnings),
    )


def validate_nix(content: str) -> ValidationResult:
    """Validate Nix file structure."""
    result = ValidationResult(valid=True, original_size=len(content))
    content = strip_markdown_fences(content)
    result.new_size = len(content)
    
    # Use nix-instantiate --parse
    try:
        proc = subprocess.run(
            ["nix-instantiate", "--parse"],
            input=content, capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            result.valid = False
            result.errors.append(f"Nix parse error: {proc.stderr[:200]}")
    except FileNotFoundError:
        result.warnings.append("nix-instantiate not available, skipping validation")
    except subprocess.TimeoutExpired:
        result.warnings.append("Nix validation timed out")
    
    return result


def validate_json(content: str) -> ValidationResult:
    """Validate JSON structure."""
    import json
    result = ValidationResult(valid=True, original_size=len(content))
    content = strip_markdown_fences(content)
    result.new_size = len(content)
    
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        result.valid = False
        result.errors.append(f"JSON error: {e.msg} at position {e.pos}")
    
    return result


def validate_file(path: Path, new_content: str) -> ValidationResult:
    """Validate file based on language."""
    lang = detect_language(path)
    
    if lang == "python":
        return validate_python(new_content, path)
    elif lang == "nix":
        return validate_nix(new_content)
    elif lang == "json":
        return validate_json(new_content)
    else:
        # Basic validation for other types
        result = ValidationResult(valid=True, original_size=len(new_content))
        result.new_size = len(strip_markdown_fences(new_content))
        return result


def check_import_integrity(original: str, new: str, path: Path) -> ValidationResult:
    """Check that imports haven't been removed or broken."""
    result = ValidationResult(valid=True)
    
    try:
        orig_tree = ast.parse(original)
        new_tree = ast.parse(new)
    except SyntaxError:
        result.valid = False
        result.errors.append("Cannot parse one or both versions")
        return result
    
    # Extract imports from original
    orig_imports = set()
    for node in ast.walk(orig_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                orig_imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                orig_imports.add(node.module)
    
    # Extract imports from new
    new_imports = set()
    for node in ast.walk(new_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                new_imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                new_imports.add(node.module)
    
    # Check for removed imports
    removed = orig_imports - new_imports
    if removed:
        result.warnings.append(f"Imports removed: {', '.join(removed)}")
    
    return result


def apply_with_guard(
    path: Path,
    new_content: str,
    baseline_content: str | None = None,
) -> tuple[bool, ValidationResult]:
    """Apply file change with full validation.
    
    Returns (applied, validation_result).
    """
    # 1. Strip markdown fences
    new_content = strip_markdown_fences(new_content)
    
    # 2. Validate syntax/structure
    validation = validate_file(path, new_content)
    if not validation.valid:
        return False, validation
    
    # 3. Check import integrity if we have baseline
    if baseline_content and path.suffix == ".py":
        import_check = check_import_integrity(baseline_content, new_content, path)
        if not import_check.valid:
            return False, import_check
        validation.warnings.extend(import_check.warnings)
    
    # 4. Check file size (prevent truncation; tiny files exempt —
    # a 1-line fix on a 26-char file is not "truncation", but emptying
    # any file is always rejected).
    if baseline_content:
        if not new_content.strip():
            validation.errors.append("New content is empty")
            return False, validation
        if len(baseline_content) > 100:
            if len(new_content) < len(baseline_content) * 0.3:
                validation.errors.append(f"File shrunk too much: {len(baseline_content)} -> {len(new_content)}")
                return False, validation
            if len(new_content) > len(baseline_content) * 3:
                validation.warnings.append(f"File grew significantly: {len(baseline_content)} -> {len(new_content)}")
    
    # 5. Apply the change
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_content, encoding="utf-8")
        return True, validation
    except Exception as e:
        validation.errors.append(f"Write failed: {e}")
        return False, validation
