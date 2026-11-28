#!/usr/bin/env python3
"""Aggregate the fleet's real bus paths into one JSON feed for the hub.

Paths exposed (each item carries `path`):
  bus-gh#100  -> durable coord bus (GitHub issue comments, coord-json + plain)
  coord-mcp   -> live coord_read board/claims from the LAN MCP
  hub-wake    -> direct session deliveries made through the hub /api/wake

Read-only, bounded timeouts, no secrets. Called by agent-hub.mjs via pyJSON.
"""
from __future__ import annotations
import os

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
ISSUE = "Kuchiriel/mt5"
GH_ISSUE = "100"
# MEDIDO 28/11: o coord-mcp escuta no IP da tailnet (100.121.100.103:8765 e o
# IPv6), NAO em 127.0.0.1 — o default 127.0.0.1 dava Connection refused e o
# Bus/Chat do hub ficavam sem os 2520 itens do caminho coord-mcp.
MCP = os.environ.get("COORD_MCP_URL","http://100.121.100.103:8765/mcp")
HUB_LOG = HOME / ".local/state/jarvis/hub-messages.jsonl"
JOURNAL = HOME / ".local/state/jarvis/bus-journal"


def _gh_token() -> str:
    try:
        p = subprocess.run(["gh", "auth", "token"], capture_output=True,
                           text=True, timeout=20)
        return p.stdout.strip()
    except Exception:
        return ""


def _get(url: str, token: str = "") -> tuple[bytes, dict]:
    headers = {"User-Agent": "agent-hub", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read(), dict(r.headers)


def github_items(limit: int) -> list[dict]:
    tok = _gh_token()
    base = f"https://api.github.com/repos/{ISSUE}/issues/{GH_ISSUE}/comments"
    _, head = _get(base + "?per_page=1", tok)
    link = head.get("Link", "")
    total = int(re.search(r"[?&]page=(\d+)[^>]*>;\s*rel=\"last\"", link).group(1)) if "rel=\"last\"" in link else 1
    per = 60
    last = max(1, (total + per - 1) // per)
    pages = sorted({max(1, last - 1), last})
    items: list[dict] = []
    for pg in pages:
        raw, _ = _get(f"{base}?per_page={per}&page={pg}", tok)
        comments = json.loads(raw)
        for c in comments:
            body = c.get("body") or ""
            ts = str(c.get("created_at") or "")[:19].replace("T", " ")
            who = (c.get("user") or {}).get("login", "?")
            blocks = re.findall(r"```coord-json\s*(.*?)```", body, re.S)
            parsed = []
            for b in blocks:
                try:
                    j = json.loads(b)
                except Exception:
                    continue
                if isinstance(j, dict):
                    parsed.append({
                        "ts": str(j.get("ts") or ts)[:19].replace("T", " "),
                        "from": j.get("agent") or j.get("from") or who,
                        "to": j.get("to") or "-",
                        "kind": j.get("kind") or "msg",
                        "lane": j.get("lane") or "",
                        "text": re.sub(r"\s+", " ", str(j.get("message") or j.get("intent") or j.get("note") or ""))[:400],
                        "path": f"bus-gh#{GH_ISSUE}",
                    })
            if parsed:
                items.extend(parsed)
                continue
            items.append({
                "ts": ts, "from": who, "to": "-", "kind": "comment", "lane": "",
                "text": re.sub(r"\s+", " ", body)[:400],
                "path": f"bus-gh#{GH_ISSUE}",
            })
    return items[-limit:]


def _mcp_post(payload: dict, sid: str | None = None) -> tuple[dict, str]:
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if sid:
        headers["Mcp-Session-Id"] = sid
    req = urllib.request.Request(MCP, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read().decode(errors="ignore")
        session = r.headers.get("Mcp-Session-Id", "")
    data_line = ""
    for line in body.splitlines():
        if line.startswith("data: "):
            data_line = line[6:]
            break
    try:
        return json.loads(data_line) if data_line else {}, session
    except Exception:
        return {}, session


def coord_items(limit: int) -> list[dict]:
    init, sid = _mcp_post({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "agent-hub-bus", "version": "1"}},
    })
    if not sid:
        return []
    _mcp_post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    res, _ = _mcp_post({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "coord_read", "arguments": {}},
    }, sid)
    text = ""
    for c in (res.get("result") or {}).get("content", []):
        if c.get("type") == "text":
            text += c.get("text", "")
    ts = ""
    m = re.search(r"bus_updated_at:\s*(\S+)", text)
    if m:
        ts = m.group(1)[:19].replace("T", " ")
    out = []
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        parts = [p.strip() for p in line[2:].split("·")]
        name = parts[0] if parts else "?"
        kind = parts[1] if len(parts) > 1 else "msg"
        out.append({
            "ts": ts, "from": name, "to": "-", "kind": kind or "msg",
            "lane": parts[3] if len(parts) > 3 else "",
            "text": " · ".join(parts[4:])[:400] if len(parts) > 4 else line[2:400],
            "path": "coord-mcp",
        })
    return out[-limit:]


def hub_items(limit: int) -> list[dict]:
    if not HUB_LOG.exists():
        return []
    out = []
    for line in HUB_LOG.read_text(errors="ignore").splitlines()[-limit:]:
        try:
            j = json.loads(line)
        except Exception:
            continue
        out.append({
            "ts": str(j.get("ts") or "")[:19].replace("T", " "),
            "from": j.get("name", "?"), "to": j.get("to", "-"),
            "kind": "wake", "lane": "hub",
            "text": re.sub(r"\s+", " ", str(j.get("text", "")))[:400],
            "path": "hub-wake",
        })
    return out


def record(items: list[dict], limit: int) -> dict:
    """Append-only, idempotent dataset of fleet conversations.

    One JSONL per UTC day + a manifest with counts by path. Id is a hash of
    the stable fields, so re-running the capture never duplicates a message.
    """
    JOURNAL.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = JOURNAL / f"{day}.jsonl"
    seen = set()
    if out.exists():
        for line in out.read_text(errors="ignore").splitlines():
            try:
                seen.add(json.loads(line).get("id", ""))
            except Exception:
                continue
    added = 0
    with out.open("a", encoding="utf-8") as fh:
        for item in items[-limit:]:
            key = "|".join(str(item.get(k, "")) for k in ("path", "ts", "from", "kind", "text"))
            ident = hashlib.sha256(key.encode()).hexdigest()[:20]
            if ident in seen:
                continue
            seen.add(ident)
            row = dict(item)
            row["id"] = ident
            row["recorded_at"] = datetime.now(timezone.utc).isoformat()
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            added += 1
    by_path: dict[str, int] = {}
    total = 0
    for line in out.read_text(errors="ignore").splitlines():
        try:
            j = json.loads(line)
        except Exception:
            continue
        by_path[j.get("path", "?")] = by_path.get(j.get("path", "?"), 0) + 1
        total += 1
    manifest = {
        "day": day, "file": str(out), "total": total, "by_path": by_path,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (JOURNAL / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return {"added": added, **manifest}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("limit", nargs="?", type=int, default=40)
    ap.add_argument("--record", action="store_true",
                    help="append new messages to the durable bus journal")
    args = ap.parse_args()
    limit = args.limit
    items: list[dict] = []
    errs = []
    for name, fn in (("gh", github_items), ("mcp", coord_items), ("hub", hub_items)):
        try:
            items.extend(fn(limit))
        except Exception as exc:
            errs.append(f"{name}: {type(exc).__name__}: {exc}"[:160])
    #公平: coord-mcp estampa o mesmo `bus_updated_at` em todas as linhas e
    # dominaria o feed. Reserva uma cota por caminho antes de ordenar.
    groups: dict[str, list[dict]] = {}
    for i in items:
        groups.setdefault(i.get("path", "?"), []).append(i)
    quota = max(2, limit // max(1, len(groups)))
    fair: list[dict] = []
    for group in groups.values():
        fair.extend(group[-quota:])
    fair.sort(key=lambda x: x.get("ts", ""))
    items = fair[-limit:]
    result = {"items": items, "errs": errs,
              "paths": sorted({i.get("path", "?") for i in items}),
              "at": datetime.now(timezone.utc).isoformat()}
    if args.record:
        result["journal"] = record(items, limit)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
