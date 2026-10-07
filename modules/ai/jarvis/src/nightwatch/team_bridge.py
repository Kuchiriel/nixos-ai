"""team_bridge — multi_agent <-> team/queue.md convergence.

The Orchestrator (nightwatch.multi_agent) coordinates personas in-process;
the bash drivers (suite-bot.sh, drift-bot.sh, coord.sh) coordinate via file
in ~/projects/team. This bridge makes both speak THE SAME protocol:
claim/done/handoff + reports/.

No LLM, no VRAM: parsing and atomic append only.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

TEAM_DIR = Path(os.environ.get("TEAM_DIR", str(Path.home() / "projects/team")))
QUEUE = TEAM_DIR / "queue.md"
REPORTS = TEAM_DIR / "reports"

TASK_RE = re.compile(
    r"^- \[( |x)\] (\S+) · (open|done|blocked(?::.*)?|claimed(?::.*)?)"
    r"(?: · @(\S+))?(?: · (.*))?$"
)


def _read_lines() -> list[str]:
    return QUEUE.read_text(encoding="utf-8").splitlines() if QUEUE.exists() else []


def _write_lines(lines: list[str]) -> None:
    tmp = QUEUE.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(QUEUE)


def parse_task(line: str) -> dict[str, Any] | None:
    m = TASK_RE.match(line.strip())
    if not m:
        return None
    return {
        "checked": m.group(1) == "x",
        "id": m.group(2),
        "state": m.group(3).split(":")[0],
        "detail": m.group(3),
        "owner": m.group(4) or "any",
        "text": (m.group(5) or "").strip(),
    }


def list_open(owner: str | None = None) -> list[dict[str, Any]]:
    out = []
    for ln in _read_lines():
        t = parse_task(ln)
        if t and t["state"] == "open" and (owner in (None, "any", t["owner"]) or t["owner"] == "any"):
            out.append(t)
    return out


def enqueue(task_id: str, text: str, owner: str = "any") -> bool:
    """Enqueue an addressed task. Returns False if the id already exists."""
    lines = _read_lines()
    for ln in lines:
        t = parse_task(ln)
        if t and t["id"] == task_id:
            return False
    lines.append(f"- [ ] {task_id} · open · @{owner} · {text}")
    _write_lines(lines)
    return True


def handoff(from_bot: str, to_bot: str, text: str, task_id: str | None = None) -> str:
    """Bot-to-bot handoff: enqueues already addressed. Equivalent to the
    multi_agent HandoffContext, persisted on the blackboard."""
    tid = task_id or f"ho-{int(time.time())}-{from_bot}-{to_bot}"
    enqueue(tid, f"(from @{from_bot}) {text}", owner=to_bot)
    return tid


def claim(task_id: str, bot: str) -> bool:
    """Mark claimed IMMEDIATELY (prevents double work)."""
    lines = _read_lines()
    changed = False
    for i, ln in enumerate(lines):
        t = parse_task(ln)
        if t and t["id"] == task_id and t["state"] == "open":
            owner = f"@{t['owner']}" if t.get("owner") not in (None, "any") else ""
            rest = f" · {t['text']}" if t["text"] else ""
            lines[i] = (f"- [ ] {task_id} · claimed: {bot} "
                        f"{datetime.now().strftime('%d/%m %H:%M')}"
                        f"{(' · ' + owner) if owner else ''}{rest}")
            changed = True
            break
    if changed:
        _write_lines(lines)
    return changed


def done(task_id: str) -> bool:
    return _set_state(task_id, "done")


def block(task_id: str, reason: str) -> bool:
    return _set_state(task_id, f"blocked: {reason}")


def _set_state(task_id: str, state: str) -> bool:
    lines = _read_lines()
    changed = False
    for i, ln in enumerate(lines):
        t = parse_task(ln)
        if t and t["id"] == task_id and t["state"] in ("open", "claimed"):
            lines[i] = re.sub(
                r"· (open|claimed(?::.*)?)",
                f"· {state}",
                ln,
                count=1,
            )
            if state == "done":
                lines[i] = "- [x]" + lines[i][5:]
            changed = True
            break
    if changed:
        _write_lines(lines)
    return changed


def write_report(task_id: str, bot: str, body: str) -> Path:
    """Write reports/<date-time>-<task>.md, same pattern as the drivers."""
    REPORTS.mkdir(parents=True, exist_ok=True)
    name = f"{datetime.now().strftime('%Y-%m-%d-%H%M')}-{task_id}.md"
    p = REPORTS / name
    p.write_text(f"# {task_id} — @{bot}\n\n{body}\n", encoding="utf-8")
    return p


def create_team_executor(bot: str):
    """_execute_fn for AgentPersona: runs 'id: text' tasks with automatic
    claim + report. This is the real convergence: an Orchestrator persona
    working the same queue as the Telegram bots."""
    def _exec(task: str, context: dict[str, Any]) -> dict[str, Any]:
        tid = task.split(":", 1)[0].strip() if ":" in task else task[:40]
        text = task.split(":", 1)[1].strip() if ":" in task else task
        if not claim(tid, bot):
            return {"output": f"[{bot}] {tid} already claimed", "success": False,
                    "artifacts": {}}
        out = f"[{bot}] executed: {text[:200]}"
        write_report(tid, bot, out + f"\n\ncontext: {str(context)[:500]}")
        done(tid)
        # automatic handoff when the context carries the next owner
        nxt = (context or {}).get("next_owner")
        if nxt:
            handoff(bot, str(nxt), f"follow-up of {tid}: {text[:120]}")
        return {"output": out, "success": True, "artifacts": {"task": tid}}
    return _exec
