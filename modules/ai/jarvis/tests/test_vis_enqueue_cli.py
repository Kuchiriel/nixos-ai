"""Contract for the scripts/vis-enqueue command-line interface."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def _find_script() -> Path | None:
    """Find the script in a source checkout; the Nix sandbox may omit it."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "scripts/vis-enqueue"
        if candidate.is_file():
            return candidate
    return None


SCRIPT = _find_script()
pytestmark = pytest.mark.skipif(
    SCRIPT is None,
    reason="scripts/vis-enqueue not found in this checkout",
)


def _run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HOME"] = str(home)
    return subprocess.run(
        [str(SCRIPT), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def test_direct_task_is_enqueued_and_returned_by_next(tmp_path: Path) -> None:
    task = "verify the visible queue contract"

    queued = _run(tmp_path, task)
    queue = tmp_path / ".local/state/jarvis/vis-queue.txt"

    assert queued.stdout.startswith("vis-enqueue: enfileirado")
    assert queue.read_text().splitlines() == [task]

    popped = _run(tmp_path, "next")
    assert popped.stdout.strip() == task
    assert queue.read_text() == ""


def test_status_does_not_enqueue_a_task(tmp_path: Path) -> None:
    result = _run(tmp_path, "status")
    queue = tmp_path / ".local/state/jarvis/vis-queue.txt"

    assert result.stdout.startswith("vis-enqueue: fila=")
    assert not queue.exists() or queue.read_text() == ""
