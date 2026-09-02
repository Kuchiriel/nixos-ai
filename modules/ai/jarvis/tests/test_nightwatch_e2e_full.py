"""E2E test of the full Nightwatch pipeline.
import pytest
pytestmark = pytest.mark.integration

Tests: task -> structured patch -> Patcher -> SafeEditor -> Validator
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch as mock_patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nightwatch.patcher import PatchHunk, apply_hunk, parse_llm_patch
from nightwatch.safe_editor import SafeEditor, check_structural_integrity


SAMPLE = """\
\"\"\"Sample module.\"\"\"

import os
import json


def hello():
    \"\"\"Say hello.\"\"\"
    return "hello"


def world():
    \"\"\"Say world.\"\"\"
    return "world"


class Calculator:
    \"\"\"Simple calculator.\"\"\"

    def add(self, a, b):
        return a + b

    def subtract(self, a, b):
        return a - b
"""


@pytest.fixture
def project(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    subprocess.run(["git", "init"], cwd=str(d), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(d), capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(d), capture_output=True)
    (d / "module.py").write_text(SAMPLE)
    subprocess.run(["git", "add", "-A"], cwd=str(d), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(d), capture_output=True)
    return d


class TestParse:
    def test_single_hunk(self):
        r = (
            "=== FILE: module.py ===\n"
            "REASON: add multiply\n"
            "--- old text ---\n"
            "def world():\n"
            "    \"\"\"Say world.\"\"\"\n"
            "    return \"world\"\n"
            "--- new text ---\n"
            "def world():\n"
            "    \"\"\"Say world.\"\"\"\n"
            "    return \"world\"\n"
            "\n"
            "def multiply(a, b):\n"
            "    return a * b\n"
            "--- end ---"
        )
        patches = parse_llm_patch(r)
        assert len(patches) == 1
        assert patches[0].hunks[0].old_text.strip().startswith("def world")

    def test_no_changes(self):
        assert parse_llm_patch("NO_CHANGES") == []


class TestApply:
    def test_exact(self):
        ok, out = apply_hunk(
            "def f():\n    return 1",
            PatchHunk(old_text="def f():\n    return 1", new_text="def f():\n    return 2")
        )
        assert ok and "return 2" in out

    def test_missing(self):
        ok, _ = apply_hunk(
            "def f():\n    return 1",
            PatchHunk(old_text="def g():", new_text="def x():")
        )
        assert not ok


class TestPipeline:
    def test_edit_and_validate(self, project):
        """Full pipeline: parse patch -> apply hunk -> validate -> write -> verify."""
        r = (
            "=== FILE: module.py ===\n"
            "REASON: add multiply\n"
            "--- old text ---\n"
            "def world():\n"
            "    \"\"\"Say world.\"\"\"\n"
            "    return \"world\"\n"
            "--- new text ---\n"
            "def world():\n"
            "    \"\"\"Say world.\"\"\"\n"
            "    return \"world\"\n"
            "\n"
            "def multiply(a, b):\n"
            "    \"\"\"Multiply.\"\"\"\n"
            "    return a * b\n"
            "--- end ---"
        )

        # 1. Parse LLM response into structured patches
        patches = parse_llm_patch(r)
        assert len(patches) == 1

        # 2. Apply patch hunks to file content (real file, not mock)
        file_path = project / "module.py"
        original = file_path.read_text()
        hunk = patches[0].hunks[0]

        ok, patched = apply_hunk(original, hunk)
        assert ok, "Patch application failed"
        assert "def multiply(a, b):" in patched

        # 3. Validate Python syntax
        import ast
        ast.parse(patched)  # Must not raise

        # 4. Write via SafeEditor (atomic, validated)
        ed = SafeEditor(backup_dir=project / ".bak")
        res = ed.apply_edit(file_path, patched, validate=True)
        assert res.success, f"SafeEditor rejected: {res.errors}"

        # 5. Verify file was changed correctly
        final = file_path.read_text()
        assert "def multiply(a, b):" in final
        assert "return a * b" in final
        assert "def hello():" in final  # Original preserved

    def test_invalid_patch_preserves_original(self, project):
        """Invalid patch must not corrupt the file."""
        file_path = project / "module.py"
        original = file_path.read_text()

        # Patch targets nonexistent text
        ok, _ = apply_hunk(original, PatchHunk(
            old_text="def nonexistent():",
            new_text="def x():"
        ))
        assert not ok

        # File unchanged
        assert file_path.read_text() == original

    def test_structural_integrity_blocks_removal(self, project):
        """Removing functions must be blocked by structural integrity check."""
        orig = (project / "module.py").read_text()
        new = orig.replace(
            "def hello():\n    \"\"\"Say hello.\"\"\"\n    return \"hello\"\n\n",
            ""
        )
        ok, errs, _ = check_structural_integrity(orig, new)
        assert not ok
        assert any("hello" in e for e in errs)

    def test_markdown_fences_stripped(self, project):
        """LLM markdown fences must be stripped before validation."""
        from nightwatch.safe_editor import strip_markdown_fences

        content_with_fences = '```python\ndef f():\n    return 1\n```'
        cleaned = strip_markdown_fences(content_with_fences)
        assert "```" not in cleaned
        assert "def f():" in cleaned
