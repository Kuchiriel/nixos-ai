"""Le pendências do BUS de coordenação via o MCP local (coord_pending).

POR QUE (05/11): o canal de bot-a-bot tem duas metades — o BUS (issue do
GitHub, `coord-json`, SSOT) e a entrega local. O watcher precisa do BUS
para ACORDAR o agente certo sem depender de prompt do dono: uma mensagem
no bus endereçada ao codinome de um agente (ou uma claim que se sobrepõe
aos arquivos dele) tem que virar um wake.

O bus é lido pelo MCP local (http://127.0.0.1:8765/mcp), que tem o
CACHE do GitHub dentro (o GitHub API tem rate limit de 60/h por token:
polling direto a cada ciclo estoura).

SAÍDA: JSON no stdout — lista de {"to": <codinome|lane>, "text": ...}.
Erro → imprime [] e sai 0 (o watcher nunca deve quebrar por causa do bus).

Uso:
  python3 scripts/agent-bus-pending.py [--url http://127.0.0.1:8765/mcp]
                                       [--agent <codinome>]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

def _default_url() -> str:
    """URL do MCP de coordenação local.

    A unit `coord-mcp.service` escuta na IP do TAILNET (e não em 0.0.0.0,
    para não expor na LAN). Logo, o loopback (127.0.0.1) NÃO responde: o
    watcher tem que falar com a tailnet — que é a mesma máquina, sem
    depender de rede externa. Detecta a IP do tailnet e cai para o loopback.
    """
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("100.100.100.100", 80))   # não trafega, só descobre a rota
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            return f"http://{ip}:8765/mcp"
    except OSError:
        pass
    return "http://127.0.0.1:8765/mcp"


DEFAULT_URL = _default_url()


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
    try:
        return json.loads(raw), sid
    except json.JSONDecodeError:
        return {}, sid


def main() -> int:
    ap = argparse.ArgumentParser(description="pendencias do bus de coordenacao")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--agent", default="", help="filtra: so o que e para este codinome")
    ap.add_argument("--codename", default="", help="codinome do agente que pergunta")
    ap.add_argument("--files", default="", help="globs do agente (detecta claim sobreposta)")
    ap.add_argument("--since", default="", help="cursor do bus (so o que e novo)")
    args = ap.parse_args()

    try:
        init, sid = _post(
            args.url,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "agent-bus-pending", "version": "1"},
                },
            },
        )
        if not sid:
            print("[]")
            return 0
        _post(args.url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
        resp, _ = _post(
            args.url,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "coord_pending",
                    "arguments": {
                        k: v
                        for k, v in (
                            ("agent", args.agent),
                            ("codename", args.codename),
                            ("files", args.files),
                            ("since", args.since),
                        )
                        if v
                    },
                },
            },
            sid,
        )
    except Exception as exc:  # o bus pode nao existir ainda → nao e erro
        print(f"agent-bus-pending: bus indisponivel ({exc})", file=sys.stderr)
        print("[]")
        return 0

    out: list[dict] = []
    for item in resp.get("result", {}).get("content", []):
        text = item.get("text") or ""
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            if text.strip():
                out.append({"to": "*", "text": text.strip()})
            continue
        if isinstance(parsed, list):
            out.extend(x for x in parsed if isinstance(x, dict))
        elif isinstance(parsed, dict):
            for key in ("pending", "items", "messages"):
                if isinstance(parsed.get(key), list):
                    out.extend(x for x in parsed[key] if isinstance(x, dict))
                    break
            else:
                out.append(parsed)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
