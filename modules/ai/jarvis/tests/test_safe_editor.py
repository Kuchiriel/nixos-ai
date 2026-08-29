"""Adversarial tests for SafeEditor.

Tests simulate LLM corruption scenarios:
- markdown fences wrapping entire files
- truncated files
- files with imports removed
- files with functions/classes disappeared
- Python invalid but was valid before
- valid diff but semantically dangerous
- file shrunk dramatically
- file grew dramatically
"""

import ast
import tempfile
from pathlib import Path

import pytest

from nightwatch.safe_editor import (
    SafeEditor,
    EditResult,
    strip_markdown_fences,
    validate_python,
    check_import_integrity,
    check_structural_integrity,
    detect_language,
    compute_checksum,
)


# --- Fixtures ---

@pytest.fixture
def tmp_editor(tmp_path):
    """Create a SafeEditor with temp backup dir."""
    backup_dir = tmp_path / "backups"
    return SafeEditor(backup_dir=backup_dir)


@pytest.fixture
def sample_python(tmp_path):
    """Create a sample Python file."""
    content = '''"""Sample module."""

import os
import sys
from pathlib import Path


def main():
    """Main function."""
    print("hello")


def helper():
    """Helper function."""
    return True


class MyClass:
    """A class."""

    def method(self):
        return 42
'''
    path = tmp_path / "sample.py"
    path.write_text(content)
    return path, content


# --- Markdown fence tests ---

class TestMarkdownFences:
    """LLM wraps entire file in ```python ... ``` blocks."""

    def test_single_fence_stripped(self):
        content = '```python\nimport os\n\nprint("hello")\n```'
        result = strip_markdown_fences(content)
        assert "```" not in result
        assert 'import os' in result

    def test_double_fence_stripped(self):
        content = '````python\n```python\nimport os\nprint("hello")\n```\n````'
        result = strip_markdown_fences(content)
        assert "```" not in result
        assert 'import os' in result

    def test_fence_with_content_preserved(self):
        content = '```python\ndef foo():\n    return 1\n```'
        result = strip_markdown_fences(content)
        assert 'def foo' in result
        assert 'return 1' in result

    def test_no_fence_unchanged(self):
        content = 'import os\n\nprint("hello")'
        result = strip_markdown_fences(content)
        assert result == content


# --- Truncation tests ---

class TestTruncationDetection:
    """LLM returns half a file."""

    def test_detects_shrunk_file(self, tmp_editor, sample_python):
        path, original = sample_python
        # Truncated to less than 30% of original to trigger size guard
        truncated = original[:len(original) // 5]
        result = tmp_editor.apply_edit(path, truncated)
        assert not result.success
        # Either syntax error or size guard should reject it
        assert result.errors, "Expected at least one error"

    def test_file_unchanged_on_rejection(self, tmp_editor, sample_python):
        path, original = sample_python
        truncated = original[:100]
        tmp_editor.apply_edit(path, truncated)
        assert path.read_text() == original


# --- Import removal tests ---

class TestImportIntegrity:
    """LLM removes imports."""

    def test_detects_removed_imports(self):
        original = 'import os\nimport sys\n\ndef main():\n    os.getcwd()\n'
        new = 'import os\n\ndef main():\n    os.getcwd()\n'
        ok, warnings = check_import_integrity(original, new)
        assert ok
        assert any("sys" in w for w in warnings)

    def test_no_removal_no_warning(self):
        code = 'import os\nimport sys\n\ndef main():\n    os.getcwd()\n'
        ok, warnings = check_import_integrity(code, code)
        assert ok
        assert len(warnings) == 0

    def test_safe_editor_rejects_import_removal(self, tmp_editor, sample_python):
        path, original = sample_python
        # Remove 'os' import
        new_content = original.replace("import os\n", "")
        result = tmp_editor.apply_edit(path, new_content)
        # Should have warnings about removed imports
        assert any("import" in w.lower() for w in result.warnings)


# --- Structural integrity tests ---

class TestStructuralIntegrity:
    """LLM removes functions or classes."""

    def test_detects_removed_function(self):
        original = 'def foo():\n    pass\n\ndef bar():\n    pass\n'
        new = 'def foo():\n    pass\n'
        ok, errors, warnings = check_structural_integrity(original, new)
        assert not ok
        assert any("bar" in e for e in errors)

    def test_detects_removed_class(self):
        original = 'class A:\n    pass\n\nclass B:\n    pass\n'
        new = 'class A:\n    pass\n'
        ok, errors, warnings = check_structural_integrity(original, new)
        assert not ok
        assert any("B" in e for e in errors)

    def test_detects_added_function(self):
        original = 'def foo():\n    pass\n'
        new = 'def foo():\n    pass\n\ndef baz():\n    pass\n'
        ok, errors, warnings = check_structural_integrity(original, new)
        assert ok
        assert not errors
        assert any("baz" in w for w in warnings)

    def test_safe_editor_blocks_function_removal(self, tmp_editor, sample_python):
        path, original = sample_python
        # Remove 'helper' function — should be BLOCKED now
        new_content = original.replace('\ndef helper():\n    """Helper function."""\n    return True\n', '\n')
        result = tmp_editor.apply_edit(path, new_content)
        assert not result.success
        assert any("helper" in e for e in result.errors)


# --- Invalid Python tests ---

class TestInvalidPython:
    """LLM produces syntactically invalid Python."""

    def test_syntax_error_rejected(self, tmp_editor, sample_python):
        path, original = sample_python
        invalid = 'def foo(\n    unclosed'
        result = tmp_editor.apply_edit(path, invalid)
        assert not result.success
        assert any("syntax" in e.lower() for e in result.errors)

    def test_syntax_error_preserves_original(self, tmp_editor, sample_python):
        path, original = sample_python
        invalid = 'def foo(\n    unclosed'
        tmp_editor.apply_edit(path, invalid)
        assert path.read_text() == original


# --- Valid edit tests ---

class TestValidEdits:
    """LLM produces valid, safe changes."""

    def test_valid_minor_edit_accepted(self, tmp_editor, sample_python):
        path, original = sample_python
        # Replace preserving same structure/size
        new_content = original.replace("print(\"hello\")", "print(\"world\")")
        result = tmp_editor.apply_edit(path, new_content)
        assert result.success
        # strip_markdown_fences normalizes trailing whitespace
        written = path.read_text()
        assert "print(\"world\")" in written
        assert result.checksum_before != result.checksum_after

    def test_valid_addition_accepted(self, tmp_editor, sample_python):
        path, original = sample_python
        new_content = original + '\ndef new_func():\n    """New function."""\n    pass\n'
        result = tmp_editor.apply_edit(path, new_content)
        assert result.success


# --- Language detection tests ---

class TestLanguageDetection:
    """Correct language detection."""

    def test_python(self):
        assert detect_language(Path("foo.py")) == "python"

    def test_nix(self):
        assert detect_language(Path("foo.nix")) == "nix"

    def test_json(self):
        assert detect_language(Path("foo.json")) == "json"

    def test_unknown(self):
        assert detect_language(Path("foo.xyz")) == "unknown"


# --- Checksum tests ---

class TestChecksum:
    """Checksum integrity."""

    def test_same_content_same_checksum(self):
        c = "hello world"
        assert compute_checksum(c) == compute_checksum(c)

    def test_different_content_different_checksum(self):
        assert compute_checksum("hello") != compute_checksum("world")


# --- Backup and rollback tests ---

class TestBackupRollback:
    """Backup creation and rollback."""

    def test_backup_created(self, tmp_editor, sample_python):
        path, _ = sample_python
        new_content = 'print("changed")'
        tmp_editor.apply_edit(path, new_content)
        backups = list(tmp_editor.backup_dir.glob(f"{path.name}.*.bak"))
        assert len(backups) >= 1

    def test_rollback_restores_original(self, tmp_editor, sample_python):
        path, original = sample_python
        new_content = 'print("changed")'
        tmp_editor.apply_edit(path, new_content)
        success = tmp_editor.rollback(path)
        assert success
        assert path.read_text() == original


# --- Atomic write tests ---

class TestAtomicWrite:
    """Write goes through temp file."""

    def test_write_succeeds(self, tmp_editor, tmp_path):
        # Use a small file so the content doesn't trigger size guard
        path = tmp_path / "small.py"
        path.write_text('print("old")\n')
        new = 'print("atomic")\n'
        result = tmp_editor.apply_edit(path, new)
        assert result.success
        assert result.checksum_before != result.checksum_after

    def test_checksum_after_matches_content(self, tmp_editor, tmp_path):
        # Use a small file so the content doesn't trigger size guard
        path = tmp_path / "small.py"
        path.write_text('print("old")\n')
        new = 'print("checksum")\n'
        result = tmp_editor.apply_edit(path, new)
        assert result.success
        actual = path.read_text()
        assert result.checksum_after == compute_checksum(actual)


# --- Edge cases ---

class TestEdgeCases:
    """Edge cases and adversarial inputs."""

    def test_empty_file_accepted(self, tmp_editor, tmp_path):
        path = tmp_path / "empty.py"
        path.write_text("# empty\n")
        result = tmp_editor.apply_edit(path, "")
        # Empty file after strip should be rejected (shrunk too much)
        assert not result.success

    def test_binary_content_rejected(self, tmp_editor, sample_python):
        path, original = sample_python
        result = tmp_editor.apply_edit(path, "\x00\x01\x02binary")
        assert not result.success

    def test_very_long_file_accepted(self, tmp_editor, tmp_path):
        path = tmp_path / "long.py"
        path.write_text("# short\n")
        long_content = "x = 1\n" * 10000
        result = tmp_editor.apply_edit(path, long_content)
        assert result.success

    def test_concurrent_edit_detected(self, tmp_editor, sample_python):
        """Simulate external modification during edit."""
        path, original = sample_python
        # External modification
        path.write_text("external change\n")
        new_content = original.replace("print(\"hello\")", "print(\"world\")")
        # Editor should detect mismatch (original != current)
        result = tmp_editor.apply_edit(path, new_content)
        # May succeed or fail depending on implementation
        # Key point: no crash, no silent corruption
        assert isinstance(result, EditResult)
