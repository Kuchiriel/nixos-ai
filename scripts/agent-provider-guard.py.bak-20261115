#!/usr/bin/env python3
"""agent-provider-guard.py — detecta falhas do PROVIDER de LLM e avisa (ping).

Por que existe (03/11/2026): o turno do agente morreu com
`ProviderHeaderTimeoutError: Provider response headers timed out after
300000ms` (nvidia/minimax, contexto ~145k) e o dono só descobriu 15 min
depois, quando o opencode desistiu (3 retries x 5 min). Os mesmos requests
também levam `Too Many Requests` (429, NIM free tier saturado) e
`Bad Request` (400 = prompt+max_tokens > contexto do modelo). Nada disso
é erro de tool — o agent-pains.sh não vê; o watcher não avisa.

O que faz: lê o log do opencode, classifica os erros de provider das
últimas N minutos, deduplica e — para cada evento NOVO — manda um ping
(notify-send no desktop do dono) e uma nota (agent-msg.sh --note) para a
peer, para o problema não ser silencioso.

Uso:
    agent-provider-guard.py scan [--since-min 15] [--max 5]
                                 [--dry-run] [--no-notify] [--no-peer]
    agent-provider-guard.py classes

Contrato:
    AGENTS_OC_LOG     log do opencode (default ~/.local/share/opencode/log/opencode.log)
    AGENTS_GUARD_STATE arquivo de dedup (default ~/.local/state/jarvis/provider-guard.seen.json)
    AGENTS_GUARD_PEER nome no roster p/ a nota (default coord-naming; vazio = não nota)
    saída             1 linha por evento NOVO (stdout); exit 0 SEMPRE (não quebra o watcher)
    --dry-run         não notifica e não grava estado (só mostra)

Exemplo:
    python3 scripts/agent-provider-guard.py scan --since-min 20 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
LOG_DEFAULT = HOME / ".local/share/opencode/log/opencode.log"
STATE_DEFAULT = HOME / ".local/state/jarvis/provider-guard.seen.json"
AGENT_MSG = Path(__file__).resolve().parent / "agent-msg.sh"

# cooldown por (classe, provider, sessao): 1 ping a cada 15 min, mesmo com
# dezenas de linhas iguais no log (429 repete a cada retry -> spam no peer)
COOLDOWN_SEC = 900

# classificação: (padrão no texto do erro, classe, dica acionável)
CLASSES = (
    ("ProviderHeaderTimeoutError", "TIMEOUT",
     "provider nao mandou headers em 5 min (contexto grande/fornecedor lento); "
     "opencode tenta +2x antes de desistir — considere trocar de modelo"),
    ("Too Many Requests", "RATE",
     "429 do provider (free tier saturado; varios agentes na mesma chave); "
     "espere ~1 min ou troque de provider"),
    ("exceeds the available context size", "CTX",
     "request passou do contexto do server local; compacte a sessao"),
    ("Bad Request", "BADREQ",
     "400 do provider: prompt_tokens + max_tokens > contexto do modelo "
     "(ou request invalido); compacte a sessao"),
    ("AI_APICallError", "API",
     "erro de API do provider; veja o log"),
)

LINE_RE = re.compile(
    r'timestamp=(?P<ts>\S+)\s+level=ERROR.*?message="stream error".*?'
    r'providerID=(?P<provider>\S+).*?modelID=(?P<model>\S+).*?'
    r'session\.id=(?P<session>\S+).*?error\.error="(?P<error>[^"]+)"'
)


def classify(error: str) -> tuple[str, str]:
    for pattern, cls, hint in CLASSES:
        if pattern in error:
            return cls, hint
    return "OTHER", "erro de provider não classificado"


def parse_events(log_path: Path, since_min: int) -> list[dict]:
    """Eventos de provider das últimas `since_min` minutos (mais novo primeiro)."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_min)
    events: list[dict] = []
    # lê só o rabo do log (26MB+): 4MB cobre com folga N minutos de atividade
    try:
        with log_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 4_000_000))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return events
    for line in tail.splitlines():
        m = LINE_RE.search(line)
        if not m:
            continue
        try:
            ts = datetime.fromisoformat(m["ts"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts < cutoff:
            continue
        cls, hint = classify(m["error"])
        events.append({
            "ts": ts.isoformat(),
            "epoch": int(ts.timestamp()),
            "provider": m["provider"],
            "model": m["model"],
            "session": m["session"],
            "error": m["error"][:200],
            "class": cls,
            "hint": hint,
        })
    events.sort(key=lambda e: e["epoch"], reverse=True)
    return events


def load_state(path: Path) -> tuple[set[str], dict[str, int]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), {}
    seen = set(data.get("seen") or [])
    cooldown = {str(k): int(v) for k, v in (data.get("cooldown") or {}).items()}
    return seen, cooldown


def save_state(path: Path, seen: set[str], cooldown: dict[str, int]) -> None:
    # mantém os 300 mais recentes (a chave é o timestamp do evento)
    ordered = sorted(seen)[-300:]
    trimmed = {k: v for k, v in sorted(cooldown.items(), key=lambda kv: kv[1])[-200:]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"seen": ordered, "cooldown": trimmed}, indent=0),
                    encoding="utf-8")


def ping(title: str, body: str) -> None:
    notifier = shutil.which("notify-send") or "/run/current-system/sw/bin/notify-send"
    try:
        subprocess.run([notifier, "-u", "critical", "-a", "opencode", title, body],
                       timeout=5, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


def peer_note(text: str, peer: str) -> None:
    if not peer or not AGENT_MSG.exists():
        return
    try:
        subprocess.run(["bash", str(AGENT_MSG), "--note", text, peer],
                       timeout=15, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


def cmd_scan(args: argparse.Namespace) -> int:
    log_path = Path(os.environ.get("AGENTS_OC_LOG", str(LOG_DEFAULT)))
    state_path = Path(os.environ.get("AGENTS_GUARD_STATE", str(STATE_DEFAULT)))
    peer = "" if args.no_peer else os.environ.get("AGENTS_GUARD_PEER", "coord-naming")
    if not log_path.exists():
        print(f"provider-guard: log ausente ({log_path})")
        return 0
    seen, cooldown = load_state(state_path)
    events = parse_events(log_path, args.since_min)
    fresh = [e for e in events if str(e["epoch"]) not in seen][: args.max]
    if not fresh:
        print(f"provider-guard: sem evento novo em {args.since_min}min")
        return 0
    now = int(datetime.now().timestamp())
    for e in fresh:
        when = datetime.fromtimestamp(e["epoch"]).strftime("%H:%M")
        key = f"{e['class']}|{e['provider']}|{e['session']}"
        line = (f"{e['class']} {e['provider']}/{e['model']} "
                f"sessao={e['session']} as {when}: {e['hint']}")
        seen.add(str(e["epoch"]))
        if now - cooldown.get(key, 0) < COOLDOWN_SEC:
            continue
        print(line)
        if args.dry_run:
            cooldown[key] = max(e["epoch"], now)
            continue
        if not args.no_notify:
            ping(f"opencode: {e['class']} ({e['provider']})", line[:220])
        if peer:
            peer_note(f"PROVIDER {e['class']} em {e['provider']}/{e['model']} "
                      f"(sessao {e['session']}, {when}): {e['hint']}", peer)
        cooldown[key] = max(e["epoch"], now)
    if not args.dry_run:
        save_state(state_path, seen, cooldown)
    return 0


def cmd_classes(_: argparse.Namespace) -> int:
    for pattern, cls, hint in CLASSES:
        print(f"{cls:8s} {pattern} -> {hint}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    scan = sub.add_parser("scan", help="procura eventos novos e notifica")
    scan.add_argument("--since-min", type=int, default=15)
    scan.add_argument("--max", type=int, default=5)
    scan.add_argument("--dry-run", action="store_true")
    scan.add_argument("--no-notify", action="store_true")
    scan.add_argument("--no-peer", action="store_true")
    sub.add_parser("classes", help="lista as classes de erro")
    args = ap.parse_args()
    if args.cmd == "classes":
        return cmd_classes(args)
    if args.cmd in (None, "scan"):
        if args.cmd is None:
            args = ap.parse_args(["scan"])
        if getattr(args, "no_notify", False):
            args.no_peer = True
        return cmd_scan(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
