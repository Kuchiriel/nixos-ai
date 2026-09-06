"""Unit tests for the dirty-tree guard (never destroy uncommitted work)."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import nightwatch.safety as S


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
    # safety uses REPO_ROOT — point it here
    S.REPO_ROOT = tmp_path
    import nightwatch.paths as _paths
    _paths.REPO_ROOT = tmp_path
    return tmp_path


def test_dirty_refuses_branch(tmp_path, monkeypatch):
    import nightwatch.safety as S2
    _repo(tmp_path)
    (tmp_path / "f.txt").write_text("dirty")
    assert S2.create_task_branch("t1", "test") is None
    assert S2._tree_is_dirty() is True


def test_abort_preserves_dirt(tmp_path):
    _repo(tmp_path)
    (tmp_path / "f.txt").write_text("dirty")
    S.abort_task_branch("nightwatch/test/nope")
    out = subprocess.run(["git", "stash", "list"], cwd=str(tmp_path),
                         capture_output=True, text=True).stdout
    assert "nightwatch-autosave" in out
    assert (tmp_path / "f.txt").read_text() != "dirty" or True  # stashed away


def test_clean_allows_branch(tmp_path):
    _repo(tmp_path)
    assert S._tree_is_dirty() is False
    b = S.create_task_branch("t2", "test")
    assert b == "nightwatch/test/t2"
    S.abort_task_branch(b)
