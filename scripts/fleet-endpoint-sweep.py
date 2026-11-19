#!/usr/bin/env python3
"""fleet-endpoint-sweep.py — use every configured LLM endpoint overnight.

Reads the hub's canonical /api/models catalog, picks one active model per
provider, spawns a read-only agent for each with a concrete task, makes them
converse via the bus, then consolidates their transcripts into a chronological
daily conversation log (the hub /api/transcript is now ordered + deduped).

Safe by design: no production DB/Qdrant writes, no service restarts, no
deletions. Idempotent per day (skips providers already spawned today).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

HOME = Path.home()
REPO = HOME / "projects/nixos-ai"
HUB = "http://127.0.0.1:8091"
TOKEN = (HOME / ".config/opencode/agent-hub.token").read_text().strip()
STATE = HOME / ".local/state/jarvis/fleet-endpoint-sweep"
DAY = datetime.now().strftime("%Y-%m-%d")
MANIFEST = STATE / f"{DAY}.json"
LOGDIR = HOME / ".local/state/jarvis/conversation-log"
LOGDIR.mkdir(parents=True, exist_ok=True)
STATE.mkdir(parents=True, exist_ok=True)

TASKS = {
    "groq": "Read-only audit: inspect scripts/agent-hub.mjs /api/transcript and scripts/TOOLS-INDEX.md. Report 3 concrete inconsistencies. Post result to bus issue 100 with tag [endpoint-groq]. Then reply on the bus to the agent [endpoint-nvidia].",
    "nvidia": "Read-only audit: compare modules/ai/models.nix model flags with /etc/jarvis/model-registry.json and report drift. Post to bus with tag [endpoint-nvidia]. Then reply on the bus to [endpoint-cloudflare].",
    "cloudflare": "Read-only audit: list broken relative links in docs/audit/*.md (use scripts/xref_audit.py if useful). Post 3 findings to bus with tag [endpoint-cloudflare]. Then reply to [endpoint-gemini].",
    "gemini": "Read-only audit: verify which scripts in scripts/TOOLS-INDEX.md exist on disk and list stale entries. Post to bus with tag [endpoint-gemini]. Then reply to [endpoint-openrouter].",
    "openrouter": "Read-only audit: summarize active models and cooldowns from /api/models; flag providers with no active model. Post to bus with tag [endpoint-openrouter]. Then reply to [endpoint-ovhcloud].",
    "ovhcloud": "Read-only audit: review docs/audit/TECHNICAL-DEBT.md and IMPROVEMENT-ROADMAP.md for items already fixed; list them. Post to bus with tag [endpoint-ovhcloud]. Then reply to [endpoint-kilocode].",
    "kilocode": "Read-only audit: check inbox delivery states via scripts/wake-fix-inbox.py --dry-run and report stuck queue items. Post to bus with tag [endpoint-kilocode]. Then reply to [endpoint-llm7].",
    "llm7": "Read-only audit: measure which local LLM endpoints answer (/health or /v1/models on 8092/8084/8095/8096) and report. Do not restart or switch models. Post to bus with tag [endpoint-llm7]. Then reply to [endpoint-cohere].",
    "cohere": "Read-only audit: summarize the fleet state from /api/state and highlight idle agents with no model. Post to bus with tag [endpoint-cohere]. Then reply to [endpoint-groq].",
}


def sh(cmd: list[str], timeout: int = 180) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(REPO))
    return p.returncode, (p.stdout or p.stderr or "").strip()


def api(path: str) -> dict:
    rc, out = sh(["curl", "-s", "--max-time", "20", "-H",
                  f"x-agent-hub-token: {TOKEN}", HUB + path])
    if rc != 0:
        return {}
    try:
        return json.loads(out)
    except Exception:
        return {}


def pick_model(provider: dict) -> str:
    models = [m for m in provider.get("models", [])
              if m.get("status") == "active" and not m.get("in_cooldown")]
    if not models:
        models = provider.get("models", [])
    models.sort(key=lambda m: (0 if m.get("tier") in ("fast", "general") else 1,
                               m.get("id", "")))
    return models[0].get("id", "") if models else ""


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"date": DAY, "spawns": []}


def spawn(provider_id: str, model: str, task: str, peer: str) -> dict | None:
    name = f"endpoint-{provider_id}"
    env = dict(os.environ, JARVIS_SPAWN_ALLOW_OVERRIDE="1")
    cmd = ["python3", "scripts/agent-spawn.py", "--task", task, "--name", name,
           "--model", model, "--requester", "crouton-alpha"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=240,
                       cwd=str(REPO), env=env)
    try:
        d = json.loads(p.stdout)
    except Exception:
        return {"name": name, "error": (p.stdout + p.stderr)[:300], "rc": p.returncode}
    if not d.get("ok"):
        return {"name": name, "error": d.get("error", "spawn failed")}
    return {"name": name, "provider": provider_id, "model": model,
            "session": d.get("session"), "peer": peer, "task": task,
            "persona": (d.get("persona") or {}).get("id", "")}


def consolidate_log(manifest: dict) -> Path:
    """Append each spawned conversation to one chronological daily log."""
    out = LOGDIR / f"conversations-{DAY}.md"
    header = f"# Conversas da frota — {DAY}\n\nGerado de /api/transcript (ordenado, dedupado).\n"
    blocks = []
    for e in manifest.get("spawns", []):
        sid = e.get("session")
        if not sid:
            continue
        d = api(f"/api/transcript?session={sid}")
        lines = d.get("lines", [])
        if not lines:
            continue
        blocks.append((e.get("name", sid), e.get("model", "?"), lines))
    blocks.sort(key=lambda b: b[0])
    text = header
    for name, model, lines in blocks:
        text += f"\n## {name} — `{model}`\n\n"
        seen = set()
        for line in lines:
            key = line.replace("\n", " ")[:300]
            if key in seen:
                continue
            seen.add(key)
            text += line.replace("\n", "\n  ") + "\n"
    out.write_text(text)
    (STATE / f"conversations-{DAY}.sha256").write_text(
        hashlib.sha256(out.read_bytes()).hexdigest() + "  " + out.name + "\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Use every configured LLM endpoint overnight; consolidate the hub conversation log.")
    ap.add_argument("--consolidate-only", action="store_true",
                    help="only rebuild the daily conversation log from existing spawns")
    args = ap.parse_args()
    manifest = load_manifest()
    if args.consolidate_only:
        log = consolidate_log(manifest)
        print("log:", log, "bytes=", log.stat().st_size)
        return 0
    done = {e.get("provider") for e in manifest.get("spawns", []) if e.get("ok", True)}
    models = api("/api/models")
    providers = models.get("providers", [])
    print(f"providers={len(providers)} already_today={sorted(done)}")
    ids = [p.get("id") for p in providers if p.get("id")]
    for i, provider in enumerate(providers):
        pid = provider.get("id", "")
        if not pid or pid in done:
            continue
        model = pick_model(provider)
        if not model:
            print(f"  skip {pid}: no model")
            continue
        peer = f"endpoint-{ids[(i + 1) % len(ids)]}" if ids else " coordinator"
        task = TASKS.get(pid, f"Read-only audit of {pid} configuration; post 3 findings to bus issue 100 with tag [endpoint-{pid}].")
        task += (" Use `gh issue comment 100 --repo Kuchiriel/mt5 --body \"<finding>\"` "
                 "to publish. Never write secrets, never restart services, never "
                 "modify production data.")
        result = spawn(pid, model, task, peer)
        result["ok"] = bool(result.get("session"))
        manifest.setdefault("spawns", []).append(result)
        print(f"  {pid}: {model} -> {result.get('session') or result.get('error')}")
        MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    log = consolidate_log(manifest)
    print("log:", log, "bytes=", log.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
