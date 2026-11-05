"""Poller do BUS para uma máquina que NÃO é esta (ex.: o opencode do Windows).

POR QUE (05/11/2026): o watcher do Linux acorda sessões LOCAIS. Uma IA em
outra máquina (Windows via Tailscale, ou o Termux do Crouton) precisa do
mesmo mecanismo do outro lado — e o canal já existe: o MCP de coordenação
(`coord_http` na tailnet) expõe `coord_pending`, que devolve **só** o que
pertence a quem pergunta (msg endereçada ao codinome + claim com escopo
sobreposto).

COMO USAR (no Windows, a cada ~60 s, num loop do seu scheduler):
    python agent-bus-poll.py --codename matheus-perf \
        --files "tools/coord_servidor.ps1,PROP_FUNDEDNEXT_MATHEUS/**" \
        --url http://100.121.100.103:8765/mcp
    → imprime JSON [{"to": ..., "text": ...}] com o que é seu.

Aí o teu agente (ou o teu watcher local) acorda a sessão com esse texto —
mesmo caminho do Linux, sem GitHub e sem credencial: a trava é a ACL do
Tailscale.

O `--since` (cursor) evita reprocessar: use `bus_updated_at` do `coord_read`.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

DEFAULT_URL = "http://100.121.100.103:8765/mcp"


def _post(url: str, payload: dict, session: str | None = None) -> tuple[dict, str | None]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST", headers=headers
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        sid = resp.headers.get("Mcp-Session-Id") or session
        raw = resp.read().decode("utf-8", "replace")
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip()), sid
            except json.JSONDecodeError:
                continue
    return {}, sid


def _call(url: str, tool: str, arguments: dict) -> dict:
    init, sid = _post(url, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "agent-bus-poll", "version": "1"}},
    })
    if not sid:
        return {}
    _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    result, _sid = _post(url, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }, sid)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-bus-poll")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--codename", default="")
    parser.add_argument("--agent", default="")
    parser.add_argument("--lane", default="")
    parser.add_argument("--files", default="")
    parser.add_argument("--since", default="")
    args = parser.parse_args(argv)

    try:
        result = _call(args.url, "coord_pending", {
            "codename": args.codename or None,
            "agent": args.agent or None,
            "lane": args.lane or None,
            "files": args.files or None,
            "since": args.since or None,
        })
    except Exception as exc:
        print(json.dumps([]))
        print(f"coord: bus indisponível ({exc})", file=sys.stderr)
        return 0
    text = ""
    for part in (result.get("content") or []):
        if part.get("type") == "text":
            text = part.get("text") or ""
    items = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            items.append({"text": line[2:], "to": args.codename})
    print(json.dumps(items, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
