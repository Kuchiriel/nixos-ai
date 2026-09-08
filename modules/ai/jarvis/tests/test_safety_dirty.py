"""Unit tests for the dirty-tree guard (never destroy uncommitted work)."""
import subprocess
import sys
from pathlib import Path

import pytest
pytestmark = pytest.mark.integration

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import contextlib

import nightwatch.safety as S
from nightwatch.project_isolation import use_project_root


@contextlib.contextmanager
def _repo(tmp_path):
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(tmp_path),
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(tmp_path),
                   capture_output=True)
    (tmp_path / "f.txt").write_text("v1")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path),
                   capture_output=True)
    # safety resolve o root via find_repo_root — injeta o repo de teste
    # no contexto (o setattr em atributo de módulo morreu na consolidação).
    with use_project_root(tmp_path):
        yield tmp_path


def test_dirty_refuses_branch(tmp_path, monkeypatch):
    import nightwatch.safety as S2
    with _repo(tmp_path):
        (tmp_path / "f.txt").write_text("dirty")
        assert S2.create_task_branch("t1", "test") is None
        assert S2._tree_is_dirty() is True


def test_abort_preserves_dirt(tmp_path):
    with _repo(tmp_path):
        (tmp_path / "f.txt").write_text("dirty")
        S.abort_task_branch("nightwatch/test/nope")
        out = subprocess.run(["git", "stash", "list"], cwd=str(tmp_path),
                             capture_output=True, text=True).stdout
        assert "nightwatch-autosave" in out
        assert (tmp_path / "f.txt").read_text() == "v1"


def test_clean_allows_branch(tmp_path):
    with _repo(tmp_path):
        assert S._tree_is_dirty() is False
        b = S.create_task_branch("t2", "test")
        assert b == "nightwatch/test/t2"
        S.abort_task_branch(b)
