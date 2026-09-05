"""Pause signal — global stop/pause flag for autonomous work.

Contract (usable by any IDE, CLI, or AI):
- PAUSE_FILE exists → harness defers new tasks (no attempts consumed).
- Content: "<origin>:<reason>". Origin "watchdog" = auto-managed
  (cleared on recovery); anything else = manual (never auto-cleared).
- Watchdog sets it on critical memory pressure (PSI), clears on recovery.

Pressure source: /proc/pressure (PSI, the standard Linux mechanism)
plus MemAvailable. Thresholds tuned for 32GB RAM + 6GB VRAM host.
"""
from __future__ import annotations

from pathlib import Path

PAUSE_FILE = Path.home() / ".local/state/jarvis/PAUSED"

FULL_CRIT = 25.0
FULL_WARN = 10.0
AVAIL_CRIT_KB = 1_500_000
AVAIL_WARN_KB = 4_000_000


def is_paused() -> tuple[bool, str]:
    """Return (paused, reason)."""
    try:
        if PAUSE_FILE.exists():
            return True, PAUSE_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return False, ""


def pause(reason: str, origin: str = "manual") -> None:
    """Set the global pause flag."""
    PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAUSE_FILE.write_text(f"{origin}:{reason}", encoding="utf-8")


def resume() -> bool:
    """Clear the flag. Returns True if something was cleared."""
    try:
        if PAUSE_FILE.exists():
            PAUSE_FILE.unlink()
            return True
    except Exception:
        pass
    return False


def check_pressure() -> dict:
    """Read PSI + meminfo. Returns level ok|warning|critical + details."""
    full60 = 0.0
    try:
        for line in Path("/proc/pressure/memory").read_text().splitlines():
            if line.startswith("full"):
                for tok in line.split():
                    if tok.startswith("avg60="):
                        full60 = float(tok.split("=")[1])
    except Exception:
        pass
    avail_kb = 0
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                avail_kb = int(line.split()[1])
                break
    except Exception:
        pass
    if full60 >= FULL_CRIT or (avail_kb and avail_kb < AVAIL_CRIT_KB):
        level, reason = "critical", (
            f"memory pressure full={full60:.1f}% avail={avail_kb // 1024}MB"
        )
    elif full60 >= FULL_WARN or (avail_kb and avail_kb < AVAIL_WARN_KB):
        level, reason = "warning", (
            f"memory pressure full={full60:.1f}% avail={avail_kb // 1024}MB"
        )
    else:
        level, reason = "ok", f"full={full60:.1f}% avail={avail_kb // 1024}MB"
    return {"level": level, "reason": reason, "full_avg60": full60,
            "avail_kb": avail_kb}
