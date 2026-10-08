"""MissionStore — durable mission state.

Why a dedicated store instead of reusing `nightwatch.task_queue`: the
TaskQueue is nightwatch's mechanism (an autonomous per-project improvement
queue, with pruning and loop detection). A mission is a different shape — a
human objective, a Telegram binding, an approval, verification evidence,
and a pending decision question. Forcing missions into TaskQueue would mean
payload leaking outward (`Task.from_dict` silently drops unknown fields, so
the Telegram binding would simply vanish).

What this store guarantees:
- atomic writes (tmp + rename) — never corrupt on process death;
- written BEFORE prolonged work starts (the resume requirement);
- idempotent by `id` — reprocessing the same update does not duplicate a
  mission;
- recovery: a mission left RUNNING with no live process becomes runnable
  again, and tasks stuck in RUNNING go back to READY (never duplicated);
- a record of already-processed Telegram updates (offset survives restart).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterator

from jarvis.mission.models import Mission, MissionState, TaskState


def _safe(name: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)[:64] or "unknown"


class MissionStore:
    """Durable mission storage (one JSON file per mission)."""

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        # Resolve the directory lazily inside `root` (see below) rather than
        # at construction: the env var is read when the store is used, so a
        # caller can set JARVIS_MISSION_DIR after import. Evaluating
        # Path.home() eagerly also raised PermissionError in the Nix build
        # sandbox, where /homeless-shelter is not readable.
        self._explicit_root = Path(root) if root is not None else None
        self.root = self._resolve_root()
        # Creating the directory must never be fatal: in the Nix build
        # sandbox Path.home() resolves to /homeless-shelter, which cannot be
        # created. The store then works read-only against a temp dir instead
        # of exploding at construction.
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.root = Path(tempfile.gettempdir()) / "jarvis-missions"
            self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._index_file = self.root / "index.json"

    # -- paths ------------------------------------------------------------

    def _resolve_root(self) -> Path:
        if self._explicit_root is not None:
            return self._explicit_root
        env = os.environ.get("JARVIS_MISSION_DIR", "").strip()
        if env:
            return Path(env).expanduser()
        try:
            return Path.home() / ".local/state/jarvis/missions"
        except (OSError, RuntimeError):
            return Path(tempfile.gettempdir()) / "jarvis-missions"

    def path_for(self, mission_id: str) -> Path:
        return self.root / f"{_safe(mission_id)}.json"

    def _atomic_write(self, path: Path, payload: dict) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False,
                                  default=str), encoding="utf-8")
        os.replace(tmp, path)

    # -- writing ----------------------------------------------------------

    def save(self, mission: Mission) -> Path:
        """Persist the whole mission. Callers must do this BEFORE executing."""
        with self._lock:
            mission.updated_at = time.time()
            path = self.path_for(mission.id)
            self._atomic_write(path, mission.to_dict())
            self._reindex()
            return path

    def _reindex(self) -> None:
        """Light index (id -> state/objective) so listing need not open every file."""
        index: dict[str, dict] = {}
        for f in sorted(self.root.glob("msn-*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            index[d.get("id", f.stem)] = {
                "state": d.get("state", ""),
                "objective": str(d.get("objective", ""))[:120],
                "project": d.get("project", ""),
                "updated_at": d.get("updated_at", 0),
                "tasks": len(d.get("tasks", [])),
            }
        tmp = self._index_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, self._index_file)

    # -- reading ----------------------------------------------------------

    def load(self, mission_id: str) -> Mission | None:
        path = self.path_for(mission_id)
        if not path.exists():
            return None
        try:
            return Mission.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    def list(self, *, state: str | None = None,
             project: str | None = None) -> list[Mission]:
        out: list[Mission] = []
        for f in sorted(self.root.glob("msn-*.json")):
            try:
                m = Mission.from_dict(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
            if state and m.state != state:
                continue
            if project and m.project != project:
                continue
            out.append(m)
        out.sort(key=lambda m: -m.updated_at)
        return out

    def active(self) -> list[Mission]:
        """Non-terminal missions — what the supervisor resumes after restart."""
        terminal = {MissionState.DONE.value, MissionState.FAILED.value,
                    MissionState.CANCELLED.value}
        return [m for m in self.list() if m.state not in terminal]

    def iter_all(self) -> Iterator[Mission]:
        yield from self.list()

    # -- idempotency ------------------------------------------------------

    def exists(self, mission_id: str) -> bool:
        return self.path_for(mission_id).exists()

    # -- recovery ---------------------------------------------------------

    def recover_interrupted(self) -> list[Mission]:
        """Resume missions abandoned by a process crash.

        Rule: a task in RUNNING/VERIFYING/AWAITING_APPROVAL is not
        "executing" — if the process died, nobody is executing. It goes
        back to READY (re-executed idempotently by task id) instead of
        sticking around forever.

        A mission in RUNNING returns to RUNNING (the supervisor resumes the
        loop); not to PLANNING, or decomposition would run again.
        """
        recovered: list[Mission] = []
        for m in self.list():
            touched = False
            if m.state in (MissionState.RUNNING.value, MissionState.VERIFYING.value):
                m.state = MissionState.RUNNING.value
                touched = True
            for t in m.tasks:
                if t.status in (TaskState.RUNNING.value, TaskState.VERIFYING.value,
                                TaskState.AWAITING_APPROVAL.value):
                    t.status = TaskState.READY.value
                    t.updated_at = time.time()
                    touched = True
                # DONE without finished_at is inconsistent state (crash
                # mid-save). It stays DONE — verification had already
                # passed — but gets stamped.
                if t.status == TaskState.DONE.value and t.finished_at is None:
                    t.finished_at = time.time()
                    touched = True
            if touched:
                m.summary = (m.summary + " (resumed after restart)").strip()
                self.save(m)
                recovered.append(m)
        return recovered

    # -- already-processed update markers ---------------------------------

    def seen_marker(self, name: str) -> Path:
        return self.root / f".seen-{_safe(name)}"

    def mark_seen(self, name: str, ttl_seconds: float = 86400.0) -> bool:
        """True if NEW (and marks it); False if already seen.

        Used for update/callback idempotency: reprocessing the same
        update_id after a restart does not run the mission twice. The TTL
        keeps the directory from growing without bound.
        """
        path = self.seen_marker(name)
        now = time.time()
        try:
            if path.exists() and (now - path.stat().st_mtime) < ttl_seconds:
                return False
            path.write_text(str(now), encoding="utf-8")
            return True
        except OSError:
            # Disk failure: assume new (fail-open for the marker only —
            # never for the authorization gate, which is a different path).
            return True

    def sweep_seen(self, max_age_seconds: float = 172800.0) -> int:
        cutoff = time.time() - max_age_seconds
        n = 0
        for f in self.root.glob(".seen-*"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    n += 1
            except OSError:
                continue
        return n

    def prune(self, keep: int = 40) -> int:
        """Keep the `keep` most recent terminal missions."""
        terminal_states = {MissionState.DONE.value, MissionState.CANCELLED.value}
        done = [m for m in self.list() if m.state in terminal_states]
        done.sort(key=lambda m: -(m.finished_at or m.updated_at))
        removed = 0
        for m in done[keep:]:
            try:
                self.path_for(m.id).unlink()
                removed += 1
            except OSError:
                continue
        if removed:
            self._reindex()
        return removed