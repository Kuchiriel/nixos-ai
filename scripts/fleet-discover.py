#!/usr/bin/env python3
"""Fleet discovery — dynamic, evidence-based host and agent inventory.

No hardcoded hostnames, IPs or roles. Candidates come from Tailscale peers,
mDNS and localhost; their capabilities come from active probes (ICMP, TCP,
HTTPS, SNMP UDP/161) and from local APIs (agent hub, coord-mcp). Every finding
carries method, timestamp and measured evidence. The method_stats block is the
A/B of discovery channels: coverage and latency per method in each run.

Read-only. No credentials are emitted. Safe to run on a timer.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
STATE = HOME / ".local/state/jarvis/fleet-discovery"
PORTS = {
    22: "ssh", 8022: "ssh-termux", 445: "smb", 443: "https",
    8765: "coord-mcp", 8091: "agent-hub", 4599: "opencode",
    6333: "qdrant", 8788: "openai-bridge", 8789: "webhook",
}


def run(cmd: list[str], timeout: int = 6) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or "").strip()
    except Exception:
        return ""


def tailscale_peers() -> list[dict]:
    raw = run(["tailscale", "status", "--json"], 8)
    if not raw:
        return []
    try:
        d = json.loads(raw)
    except Exception:
        return []
    out = []
    for key in ("Self", *[f"Peer:{k}" for k in (d.get("Peers") or {})]):
        node = d.get(key) if key == "Self" else (d.get("Peers") or {}).get(key[5:])
        if not node:
            continue
        ips = [str(x) for x in (node.get("TailscaleIPs") or [])]
        out.append({
            "hostname": node.get("HostName") or "",
            "dns": node.get("DNSName") or "",
            "ips": ips,
            "os": node.get("OS") or "",
            "online": bool(node.get("Online")),
            "source": "tailscale",
        })
    return out


def mdns_hosts() -> list[dict]:
    raw = run(["avahi-browse", "-at", "-r", "--terminate"], 8)
    hosts: dict[str, dict] = {}
    for line in raw.splitlines():
        parts = line.split(";")
        if len(parts) < 8 or parts[0] != "=":
            continue
        name, ip = parts[3], parts[-1]
        if not name or ":" in ip and "." in ip:
            continue
        hosts.setdefault(ip, {"hostname": name, "dns": "", "ips": [ip],
                              "os": "mdns", "online": True, "source": "mdns"})
    return list(hosts.values())


def ai_mesh_hints() -> list[dict]:
    """Existing manifests are HINTS to probe, never the truth about a host."""
    out: dict[str, dict] = {}
    for root in (HOME / "ai-mesh/manifests/mesh",
                 HOME / "projects/ai-mesh/manifests/mesh"):
        if not root.exists():
            continue
        for path in root.glob("*.json"):
            try:
                d = json.loads(path.read_text())
            except Exception:
                continue
            host = str(d.get("hostname") or d.get("host") or "")
            ip = str(d.get("ip") or "")
            if host:
                if not ip:
                    try:
                        ip = socket.gethostbyname(host)
                    except OSError:
                        ip = ""
                key = ip or host
                out.setdefault(key, {"hostname": host, "ips": [ip or host],
                                     "os": "hint", "source": "ai-mesh-manifest",
                                     "online": True})
            elif ip:
                out.setdefault(ip, {"hostname": "", "ips": [ip], "os": "hint",
                                    "source": "ai-mesh-manifest", "online": True})
    return list(out.values())


HOST_RE = re.compile(r"\b[A-Z][A-Z0-9]*-[A-Z0-9]{4,}\b")


def bus_feed() -> list[str]:
    """Last 400 bus comments; single bounded call used by hints + agents."""
    raw = run(["gh", "issue", "view", "100", "--repo", "Kuchiriel/mt5",
               "--json", "comments", "--jq", ".comments[-400:] | .[].body | @json"], 40)
    bodies = []
    for line in (raw.splitlines() if raw else []):
        try:
            bodies.append(json.loads(line))
        except Exception:
            bodies.append(line)
    return bodies


def bus_api_hints() -> list[dict]:
    """Hosts announced by the fleet itself on the bus, resolved by DNS.

    Prefers the structured `host` object in coord-json; falls back to generic
    hostname tokens. No hostname or IP is hardcoded.
    """
    found: dict[str, dict] = {}
    for body in bus_feed():
        metas = []
        for block in re.findall(r"```coord-json\s*(.*?)```", body, re.S):
            try:
                j = json.loads(block)
            except Exception:
                continue
            h = j.get("host") if isinstance(j, dict) else None
            if isinstance(h, dict) and h.get("hostname"):
                metas.append({"hostname": str(h["hostname"]),
                              "kind": str(h.get("kind", "")),
                              "os": str(h.get("os", "")),
                              "arch": str(h.get("arch", ""))})
        if not metas:
            for name in HOST_RE.findall(body):
                metas.append({"hostname": name, "kind": "", "os": "", "arch": ""})
        for m in metas:
            found.setdefault(m["hostname"], m)
    out = []
    for name, meta in found.items():
        try:
            ip = socket.gethostbyname(name)
        except OSError:
            continue
        out.append({"hostname": name, "ips": [ip], "os": meta["os"] or "bus-api",
                    "kind": meta["kind"], "arch": meta["arch"],
                    "source": "bus-api", "online": True})
    return out


def bus_agents() -> list[dict]:
    """Agents that announced themselves from a discovered host on the bus."""
    out: dict[tuple[str, str], dict] = {}
    for body in bus_feed():
        sender = re.search(r"\*\*msg\*\* de `([^`]+)`", body)
        for block in re.findall(r"```coord-json\s*(.*?)```", body, re.S):
            try:
                j = json.loads(block)
            except Exception:
                continue
            if not isinstance(j, dict):
                continue
            name = str(j.get("agent") or j.get("from") or
                       (sender.group(1) if sender else ""))
            if not name:
                continue
            host_obj = j.get("host") if isinstance(j.get("host"), dict) else {}
            hosts = [str(host_obj["hostname"])] if host_obj.get("hostname") else []
            text = " ".join(str(j.get(k, "")) for k in ("note", "intent", "lane", "context"))
            hosts.extend(HOST_RE.findall(text))
            for host in set(hosts):
                out[(name, host)] = {"name": name, "host": host,
                                     "lane": str(j.get("lane", "")),
                                     "kind": str(host_obj.get("kind", "")),
                                     "os": str(host_obj.get("os", "")),
                                     "arch": str(host_obj.get("arch", "")),
                                     "source": "bus-coord-json"}
    return list(out.values())


def bus_host_hints() -> list[dict]:
    """Discover hostnames mentioned by the fleet itself (append-only dataset).

    Generic pattern for uppercase host-style names (e.g. WORKSTATION-ABC123);
    no specific hostname is hardcoded here.
    """
    journal = HOME / ".local/state/jarvis/bus-journal"
    names: set[str] = set()
    if journal.exists():
        for path in journal.glob("*.jsonl"):
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            names.update(re.findall(r"\b[A-Z][A-Z0-9]*-[A-Z0-9]{4,}\b", text))
    out = []
    for name in names:
        try:
            # So hostnames the fleet can actually resolve count as hosts;
            # document titles such as POR-TOKEN must not become fake peers.
            ip = socket.gethostbyname(name)
        except OSError:
            continue
        out.append({"hostname": name, "ips": [ip], "os": "bus-hint",
                    "source": "bus-journal", "online": True})
    return out


def arp_neighbors() -> list[dict]:
    raw = run(["ip", "neigh", "show"], 5)
    out = {}
    for line in raw.splitlines():
        parts = line.split()
        if parts and re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[0]):
            out.setdefault(parts[0], {"hostname": "", "ips": [parts[0]],
                                      "os": "lan", "source": "arp", "online": True})
    return list(out.values())


def tcp_open(ip: str, port: int, timeout: float = 0.7) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def icmp(ip: str) -> bool:
    return bool(run(["ping", "-c", "1", "-W", "1", ip], 4))


def https_status(ip: str, port: int = 443) -> str:
    out = run(["curl", "-k", "-s", "-o", "/dev/null", "-w", "%{http_code}",
               "--max-time", "2", f"https://{ip}:{port}/"], 6)
    return out if out.isdigit() else ""


def ber_len(n: int) -> bytes:
    if n < 128:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def tlv(tag: int, payload: bytes) -> bytes:
    return bytes([tag]) + ber_len(len(payload)) + payload


def snmp_sysdescr(ip: str, community: str = "public", timeout: float = 1.5) -> str:
    """Minimal SNMPv1 GetRequest for 1.3.6.1.2.1.1.1.0 (sysDescr.0)."""
    oid = bytes.fromhex("2b06010201010100")
    varbind = tlv(0x30, tlv(0x06, oid) + tlv(0x05, b""))
    pdu = tlv(0xA0, tlv(0x02, b"\x01") + tlv(0x02, b"\x00") +
              tlv(0x02, b"\x00") + tlv(0x30, varbind))
    packet = tlv(0x30, tlv(0x02, b"\x00") +
                 tlv(0x04, community.encode()) + pdu)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        s.sendto(packet, (ip, 161))
        data, _ = s.recvfrom(4096)
        s.close()
    except OSError:
        return ""
    # GetResponse PDU = 0xA2; sysDescr OID present in the response.
    if b"\xa2" not in data[:8] or oid not in data:
        return ""
    return "snmp-ok"


def hub_agents() -> list[dict]:
    tok_file = HOME / ".config/opencode/agent-hub.token"
    if not tok_file.exists():
        return []
    tok = tok_file.read_text().strip()
    req = urllib.request.Request("http://127.0.0.1:8091/api/agents",
                                 headers={"x-agent-hub-token": tok})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            d = json.loads(r.read())
    except Exception:
        return []
    return [{"name": a.get("name"), "session": a.get("session"),
             "model": a.get("model"), "busy": bool(a.get("busy")),
             "source": "agent-hub"} for a in d.get("agents", [])]


def mcp_agents() -> list[dict]:
    url = os.environ.get("COORD_MCP_URL", "http://127.0.0.1:8765/mcp")
    def post(payload: dict, sid: str = "") -> tuple[dict, str]:
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if sid:
            headers["Mcp-Session-Id"] = sid
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                url, data=json.dumps(payload).encode(), headers=headers), timeout=6)
            body, new_sid = r.read().decode(errors="ignore"), r.headers.get("Mcp-Session-Id", "")
        except Exception:
            return {}, ""
        line = next((l[6:] for l in body.splitlines() if l.startswith("data: ")), "")
        try:
            return (json.loads(line) if line else {}), new_sid
        except Exception:
            return {}, new_sid
    init, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "fleet-discovery", "version": "1"}}})
    if not sid:
        return []
    post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    res, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                   "params": {"name": "coord_roster", "arguments": {}}}, sid)
    text = "".join(c.get("text", "") for c in (res.get("result") or {}).get("content", [])
                   if c.get("type") == "text")
    out = []
    for line in text.splitlines():
        if line.startswith("- "):
            parts = [p.strip() for p in line[2:].split("·")]
            if parts:
                out.append({"name": parts[0], "context": " · ".join(parts[1:])[:200],
                            "source": "coord-mcp"})
    return out


def discover() -> dict:
    t0 = time.time()
    stats: dict[str, dict] = {}
    def timed(name: str, fn) -> dict:
        a = time.time(); r = fn(); ms = round((time.time() - a) * 1000, 1)
        if isinstance(r, list):
            found = (sum(1 for x in r if x)
                     if r and all(isinstance(x, (bool, int, str)) for x in r)
                     else len(r))
        elif isinstance(r, dict):
            found = len(r)
        else:
            found = int(bool(r))
        stats[name] = {"ms": ms, "found": found}
        return {"value": r, "found": found}

    candidates: dict[str, dict] = {}
    for c in (timed("tailscale", tailscale_peers)["value"] +
              timed("mdns", mdns_hosts)["value"] +
              timed("ai-mesh", ai_mesh_hints)["value"] +
              timed("bus-journal", bus_host_hints)["value"] +
              timed("bus-api", bus_api_hints)["value"] +
              timed("arp", arp_neighbors)["value"]):
        for ip in c.get("ips", []):
            if ip in candidates:
                cur = candidates[ip]
                # evidência viva (bus/tailscale) prevalece sobre hint estático
                for key in ("hostname", "kind", "os", "arch", "dns"):
                    if not c.get(key):
                        continue
                    # fontes vivas (bus/tailscale) valem mais que hint genérico
                    if c.get("source") in ("bus-api", "bus-journal", "tailscale") \
                            or not cur.get(key) or cur.get(key) in ("hint", "lan"):
                        cur[key] = c[key]
                cur.setdefault("sources", [cur.get("source", "")])
                if c.get("source") not in cur["sources"]:
                    cur["sources"].append(c.get("source", ""))
                if c.get("online"):
                    cur["online"] = True
            else:
                candidates[ip] = {**c, "ips": [ip], "sources": [c.get("source", "")]}
    candidates.setdefault("127.0.0.1", {"hostname": "localhost", "ips": ["127.0.0.1"],
                                        "source": "loopback", "online": True})

    def probe_host(item):
        ip, meta = item
        local = {}
        icmp_ok = icmp(ip)
        local[f"icmp:{ip}"] = {"ms": 0, "found": int(icmp_ok)}
        ports = {}
        for port, label in PORTS.items():
            ok = tcp_open(ip, port)
            local[f"tcp:{ip}:{port}"] = {"ms": 0, "found": int(ok)}
            if ok:
                ports[str(port)] = label
        https = https_status(ip) if ports.get("443") else ""
        snmp = snmp_sysdescr(ip)
        local[f"https:{ip}"] = {"ms": 0, "found": int(bool(https))}
        local[f"snmp:{ip}"] = {"ms": 0, "found": int(bool(snmp))}
        return ({
            "ip": ip, "hostname": meta.get("hostname", ""), "dns": meta.get("dns", ""),
            "os": meta.get("os", ""), "kind": meta.get("kind", ""),
            "arch": meta.get("arch", ""), "source": meta.get("source", ""),
            "icmp": icmp_ok, "ports": ports, "https": bool(https), "snmp": bool(snmp),
            "methods": [m for m, ok in (("tcp", bool(ports)), ("https", bool(https)),
                                        ("snmp", bool(snmp)), ("icmp", icmp_ok)) if ok],
        }, local)

    hosts = []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        for host, local in pool.map(probe_host, candidates.items()):
            hosts.append(host)
            stats.update(local)
    agents = (timed("agent-hub", hub_agents)["value"] +
              timed("coord-mcp", mcp_agents)["value"] +
              timed("bus-agents", bus_agents)["value"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round((time.time() - t0) * 1000, 1),
        "hosts": hosts, "agents": agents, "method_stats": stats,
        "note": "descoberta viva; nada aqui é hardcoded — hostname/porta vêm de evidência",
    }


def write_manifests(data: dict, root: Path) -> list[str]:
    """Emit capability manifests derived ONLY from measured discovery."""
    out = root / "manifests/mesh/discovered"
    out.mkdir(parents=True, exist_ok=True)
    written = []
    services = {v: k for k, v in PORTS.items()}
    for h in data["hosts"]:
        host = (h.get("hostname") or h.get("ip") or "").strip()
        if not host:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")
        ports = h.get("ports") or {}
        doc = {
            "host": slug,
            "hostname": host,
            "discovered_ips": h.get("ips", [h.get("ip")]),
            "source": h.get("source"),
            "discovery_methods": h.get("methods", []),
            "services": [f"{ports[p]}:{p}" for p in sorted(ports, key=int)],
            "host_kind": h.get("kind", ""), "host_os": h.get("os", ""),
            "host_arch": h.get("arch", ""),
            "agentes_observados": sorted({
                a.get("name", "") for a in data["agents"]
                if a.get("name") and (a.get("host", "").lower() == host.lower()
                                      or host.lower() in a.get("name", "").lower())}),
            "capacidades": [services.get(int(p), p) for p in sorted(ports, key=int)],
            "medido_em": data["generated_at"],
            "contrato": "descoberto",
            "nota": "Gerado por scripts/fleet-discover.py a partir de sondas vivas. "
                    "Nao editar a mao; ausencia de porta nao prova incapacidade.",
        }
        path = out / f"{slug}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        written.append(str(path))
    return written


def report_methods() -> int:
    """A/B honesto: cobertura acumulada por método a partir do histórico."""
    hist = STATE / "history.jsonl"
    if not hist.exists():
        print("sem histórico: rode --write-state primeiro")
        return 1
    counts: dict[str, int] = {}
    runs = 0
    for line in hist.read_text(errors="ignore").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        runs += 1
        for m in d.get("methods", []):
            counts[m] = counts.get(m, 0) + 1
    print(json.dumps({"runs": runs, "coverage": counts}, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write-manifests", default="",
                    help="ai-mesh repo path to write discovered manifests")
    ap.add_argument("--report", action="store_true",
                    help="A/B coverage per discovery method from history")
    ap.add_argument("--write-state", action="store_true",
                    help="save latest.json and append history.jsonl")
    args = ap.parse_args()
    if args.report:
        return report_methods()
    data = discover()
    if args.write_state:
        STATE.mkdir(parents=True, exist_ok=True)
        (STATE / "latest.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
        with (STATE / "history.jsonl").open("a") as fh:
            fh.write(json.dumps({"ts": data["generated_at"],
                                 "hosts": len(data["hosts"]),
                                 "agents": len(data["agents"]),
                                 "methods": sorted({m for h in data["hosts"] for m in h["methods"]})},
                                ensure_ascii=False) + "\n")
    if args.write_manifests:
        data["manifests_written"] = write_manifests(data, Path(args.write_manifests))
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
