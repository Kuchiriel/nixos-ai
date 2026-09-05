"""SafeEditor — Safe file editing for LLM agents.

Core principles:
1. Never overwrite silently
2. Write to temp file first
3. Validate before commit
4. Atomic rename on success
5. Keep backup on failure
6. Detect truncation, corruption, structural damage

Inspired by:
- Atomic write pattern (temp + rename)
- AST validation for Python
- Import integrity checking
- Size sanity checks
"""

from __future__ import annotations

import ast
import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


from nightwatch.paths import REPO_ROOT
BACKUP_DIR = Path.home() / ".local/state/jarvis/nightwatch/backups"


@dataclass
class EditResult:
    """Result of a safe edit operation."""
    success: bool
    path: str
    original_size: int = 0
    new_size: int = 0
    backup_path: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checksum_before: str = ""
    checksum_after: str = ""


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
    """Strip markdown code fences that LLMs sometimes add.
    
    Handles single and nested fences:
    - ```python ... ```
    - ```` ... ````
    - nested: ```` ```python ... ``` ````

    Only fence lines are removed — surrounding whitespace (incl. trailing
    newline) is preserved byte-for-byte for editor exactness.
    """
    lines = content.split("\n")
    # Drop the single trailing "" produced by a final newline (not content),
    # re-added at the end.
    trailing_nl = bool(lines) and lines[-1] == ""
    if trailing_nl:
        lines = lines[:-1]
    if not lines:
        return content
    
    # Strip opening fence(s)
    while lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    
    # Strip closing fence(s)
    while lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]

    result = "\n".join(lines)
    return result + ("\n" if trailing_nl else "")


def validate_python(content: str) -> tuple[bool, list[str], list[str]]:
    """Validate Python content. Returns (valid, errors, warnings)."""
    errors = []
    warnings = []
    
    # Syntax check
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return False, [f"Syntax error at line {e.lineno}: {e.msg}"], []
    
    # Structural checks
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    
    if not imports and "import" in content.lower():
        warnings.append("File has 'import' text but no import statements")
    
    if not functions and not classes and len(content) > 500:
        warnings.append("Large file with no functions or classes")
    
    # Check for truncated files
    opens = content.count("(") + content.count("[") + content.count("{")
    closes = content.count(")") + content.count("]") + content.count("}")
    if opens > closes + 5:
        warnings.append(f"Possibly truncated: {opens} opens vs {closes} closes")
    
    # Check for markdown outside strings/comments
    for i, line in enumerate(content.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("```") and not stripped.startswith('"""') and not stripped.startswith("'''"):
            # Check if it's inside a string
            try:
                # Simple heuristic: if line starts with ``` and we're not in a string
                if '"""' not in content and "'''" not in content:
                    warnings.append(f"Line {i}: markdown fence outside string")
            except Exception:
                pass
    
    return True, errors, warnings


def validate_nix(content: str) -> tuple[bool, list[str], list[str]]:
    """Validate Nix content."""
    errors = []
    warnings = []
    
    try:
        proc = subprocess.run(
            ["nix-instantiate", "--parse"],
            input=content, capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return False, [f"Nix parse error: {proc.stderr[:200]}"], []
    except FileNotFoundError:
        warnings.append("nix-instantiate not available")
    except subprocess.TimeoutExpired:
        warnings.append("Nix validation timed out")
    
    return True, errors, warnings


def validate_json(content: str) -> tuple[bool, list[str], list[str]]:
    """Validate JSON content."""
    import json
    errors = []
    
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        return False, [f"JSON error: {e.msg} at position {e.pos}"], []
    
    return True, errors, []


def check_import_integrity(original: str, new: str) -> tuple[bool, list[str]]:
    """Check that imports haven't been removed. Returns (ok, warnings)."""
    warnings = []
    
    try:
        orig_tree = ast.parse(original)
        new_tree = ast.parse(new)
    except SyntaxError:
        return False, ["Cannot parse one or both versions"]
    
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
        warnings.append(f"Imports removed: {', '.join(removed)}")
    
    # NOTE: import removal is a WARNING, not an error.
    # The caller (SafeEditor.validate_content) can upgrade to error
    # based on context. Structural integrity (functions/classes removed)
    # IS an error that blocks the edit.
    return True, warnings


def check_structural_integrity(original: str, new: str) -> tuple[bool, list[str], list[str]]:
    """Check that functions/classes haven't disappeared.
    
    Returns (ok, errors, warnings).
    Critical damage (removed functions/classes) → errors (blocks edit).
    Minor structural notes → warnings.
    """
    errors = []
    warnings = []
    
    try:
        orig_tree = ast.parse(original)
        new_tree = ast.parse(new)
    except SyntaxError:
        return False, ["Cannot parse one or both versions"], []
    
    # Check function count
    orig_funcs = {n.name for n in ast.walk(orig_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    new_funcs = {n.name for n in ast.walk(new_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    
    removed_funcs = orig_funcs - new_funcs
    if removed_funcs:
        errors.append(f"Functions removed: {', '.join(removed_funcs)}")
    
    # Check class count
    orig_classes = {n.name for n in ast.walk(orig_tree) if isinstance(n, ast.ClassDef)}
    new_classes = {n.name for n in ast.walk(new_tree) if isinstance(n, ast.ClassDef)}
    
    removed_classes = orig_classes - new_classes
    if removed_classes:
        errors.append(f"Classes removed: {', '.join(removed_classes)}")
    
    # Check for new functions/classes (informational)
    added_funcs = new_funcs - orig_funcs
    if added_funcs:
        warnings.append(f"Functions added: {', '.join(added_funcs)}")
    
    added_classes = new_classes - orig_classes
    if added_classes:
        warnings.append(f"Classes added: {', '.join(added_classes)}")
    
    return len(errors) == 0, errors, warnings


class SafeEditor:
    """Safe file editor with atomic writes and validation."""
    
    def __init__(self, backup_dir: Path | None = None):
        if backup_dir is not None:
            self.backup_dir = backup_dir
        else:
            self.backup_dir = BACKUP_DIR
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            fallback = Path(tempfile.gettempdir()) / "jarvis-backups"
            fallback.mkdir(parents=True, exist_ok=True)
            self.backup_dir = fallback
    
    def create_backup(self, path: Path) -> Path:
        """Create a timestamped backup of a file."""
        timestamp = path.stat().st_mtime if path.exists() else 0
        backup_name = f"{path.name}.{int(timestamp)}.bak"
        backup_path = self.backup_dir / backup_name
        
        if path.exists():
            shutil.copy2(path, backup_path)
        
        return backup_path
    
    def validate_content(
        self,
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
            valid, errors, warnings = validate_python(content)
            if not valid:
                # Repair flow: original already broken → syntax gate can't
                # apply (else broken files could never be fixed).
                try:
                    import ast as _ast
                    _ast.parse(original or "")
                    return False, all_errors + errors, all_warnings + warnings
                except Exception:
                    all_warnings.append("original already had syntax errors; syntax gate skipped")
            else:
                all_errors.extend(errors)
                all_warnings.extend(warnings)
        
        elif lang == "nix":
            valid, errors, warnings = validate_nix(content)
            all_errors.extend(errors)
            all_warnings.extend(warnings)
            if not valid:
                return False, all_errors, all_warnings
        
        elif lang == "json":
            valid, errors, warnings = validate_json(content)
            all_errors.extend(errors)
            all_warnings.extend(warnings)
            if not valid:
                return False, all_errors, all_warnings
        
        # Size checks against original. Emptying a file is always
        # rejected; tiny files are exempt from the ratio (a 1-line fix
        # on a 26-char file is not "truncation").
        if original:
            if not content.strip():
                all_errors.append(f"New content is empty (original had {len(original)} chars)")
                return False, all_errors, all_warnings
            if len(original) > 100:
                orig_size = len(original)
                new_size = len(content)

                if new_size < orig_size * 0.3:
                    all_errors.append(f"File shrunk too much: {orig_size} -> {new_size} ({new_size/orig_size:.0%})")
                    return False, all_errors, all_warnings

                if new_size > orig_size * 3:
                    all_warnings.append(f"File grew significantly: {orig_size} -> {new_size} ({new_size/orig_size:.0%})")
            
            # Import integrity for Python
            if lang == "python":
                ok, import_warnings = check_import_integrity(original, content)
                all_warnings.extend(import_warnings)
            
            # Structural integrity for Python — critical damage blocks the edit.
            # Repair flow: unparseable original → nothing to compare against.
            try:
                import ast as _ast2
                _ast2.parse(original or "")
                ok, struct_errors, struct_warnings = check_structural_integrity(original, content)
                all_errors.extend(struct_errors)
                all_warnings.extend(struct_warnings)
                if not ok:
                    return False, all_errors, all_warnings
            except Exception:
                all_warnings.append("original unparseable; structural check skipped")
        
        return len(all_errors) == 0, all_errors, all_warnings
    
    def apply_edit(
        self,
        path: Path,
        new_content: str,
        validate: bool = True,
    ) -> EditResult:
        """Apply an edit safely with atomic write.
        
        Steps:
        1. Read original (for comparison)
        2. Create backup
        3. Validate new content
        4. Write to temp file
        5. Validate temp file
        6. Atomic rename
        """
        result = EditResult(success=False, path=str(path))
        
        # Resolve path
        if not path.is_absolute():
            for prefix in ["modules/ai/jarvis/src/", "src/jarvis/", "jarvis/", "src/"]:
                alt = REPO_ROOT / prefix / path
                if alt.exists():
                    path = alt
                    break
            else:
                path = REPO_ROOT / path
        
        # Read original
        original = None
        if path.exists():
            try:
                original = path.read_text(encoding="utf-8")
                result.original_size = len(original)
                result.checksum_before = compute_checksum(original)
            except Exception as e:
                result.errors.append(f"Could not read original: {e}")
                return result
        
        # Create backup
        try:
            result.backup_path = str(self.create_backup(path))
        except Exception as e:
            result.warnings.append(f"Backup failed: {e}")
        
        # Strip markdown fences
        new_content = strip_markdown_fences(new_content)
        result.new_size = len(new_content)
        
        # Validate
        if validate:
            valid, errors, warnings = self.validate_content(path, new_content, original)
            result.errors.extend(errors)
            result.warnings.extend(warnings)
            
            if not valid:
                return result
        
        # Write to temp file
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=path.suffix,
                dir=path.parent,
                delete=False,
            ) as tmp:
                tmp.write(new_content)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = Path(tmp.name)
            
            # Validate temp file
            if validate:
                try:
                    content = tmp_path.read_text(encoding="utf-8")
                    valid, errors, warnings = self.validate_content(path, content, original)
                    if not valid:
                        tmp_path.unlink()
                        result.errors.extend(errors)
                        return result
                except Exception as e:
                    tmp_path.unlink()
                    result.errors.append(f"Temp validation failed: {e}")
                    return result
            
            # Atomic rename
            os.replace(tmp_path, path)
            
            # Verify
            final_content = path.read_text(encoding="utf-8")
            result.checksum_after = compute_checksum(final_content)
            
            if result.checksum_after != compute_checksum(new_content):
                result.errors.append("Content mismatch after write")
                return result
            
            result.success = True
            
        except Exception as e:
            result.errors.append(f"Write failed: {e}")
            # Cleanup temp file
            if "tmp_path" in locals() and tmp_path.exists():
                tmp_path.unlink()
        
        return result
    
    def rollback(self, path: Path) -> bool:
        """Rollback to backup."""
        if not path.is_absolute():
            for prefix in ["modules/ai/jarvis/src/", "src/jarvis/", "jarvis/", "src/"]:
                alt = REPO_ROOT / prefix / path
                if alt.exists():
                    path = alt
                    break
            else:
                path = REPO_ROOT / path
        
        # Find most recent backup
        backups = sorted(
            self.backup_dir.glob(f"{path.name}.*.bak"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        
        if not backups:
            return False
        
        try:
            shutil.copy2(backups[0], path)
            return True
        except Exception:
            return False


def safe_edit(
    path: str | Path,
    new_content: str,
    validate: bool = True,
) -> EditResult:
    """Convenience function for safe editing."""
    editor = SafeEditor()
    return editor.apply_edit(Path(path), new_content, validate)
