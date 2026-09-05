"""Unit tests for bounded workspace discovery (no rglob hang)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jarvis.core.workspace import _count_languages


def _big_tree(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    for i in range(50):
        (root / "src" / f"m{i}.py").write_text("x = 1\n")
    git = root / ".git" / "objects"
    git.mkdir(parents=True)
    for i in range(2000):
        (git / f"o{i}.bin").write_text("x" * 100)
    nm = root / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    for i in range(500):
        (nm / f"f{i}.js").write_text("y = 2\n")


def test_prunes_skip_dirs(tmp_path):
    _big_tree(tmp_path)
    t0 = time.time()
    counts = _count_languages(tmp_path)
    dt = time.time() - t0
    assert counts.get("python") == 50
    assert "javascript" not in counts
    assert dt < 5, f"too slow: {dt:.1f}s"


def test_depth_and_file_caps(tmp_path):
    deep = tmp_path
    for i in range(12):
        deep = deep / f"d{i}"
    deep.mkdir(parents=True)
    (deep / "deep.py").write_text("x = 1\n")
    counts = _count_languages(tmp_path, max_depth=6)
    assert counts.get("python") is None
