#!/usr/bin/env python3
"""agent-brief.py — o contexto COMPARTILHADO da frota (1 comando).

O problema que ele resolve: cada agente tem o proprio contexto e, sem isto,
cada um nasce cego para o que o outro ja mediu/descobriu (o AGENTS.md da
raiz diz: "dado que nao esta escrito, nao existe").

Le, de uma vez:
  - o topo da fila (AGENTS-QUEUE.md) — o que esta em aberto agora
  - a memoria episodica global (jarvis_recall) — o que os outros aprenderam
  - o roster — quem esta vivo e em que lane
  - as ultimas notas do vault — as conclusoes que sobrevivem a compactacao
  - o estado da infra (watcher/timer/saude) — quem pode trabalhar agora

Escreve BRIEF.md (curto, ~60 linhas, com o carimbo de quando foi gerado)
e imprime o caminho. Quem quiser o estado fresco: `agent-brief.sh` e le.

Uso:
    python3 scripts/agent-brief.py            # gera BRIEF.md
    python3 scripts/agent-brief.py --print    # so imprime
    python3 scripts/agent-brief.py --tail 25  # mais memoria
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

RAIZ = Path.home() / "projects"
OUT = RAIZ / "docs" / "agents" / "BRIEF.md"
CLI = RAIZ / "nixos-ai" / "scripts" / "jarvis-cli.sh"


def run(cmd: list[str], timeout: int = 45) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or p.stderr or "").strip()
    except Exception as e:
        return f"(erro: {type(e).__name__})"


def memoria(n: int) -> list[str]:
    """Memorias RECENTES (o que importa agora).

    O `recall` e por SIMILARIDADE: devolve o que 'parece' com a query, nao
    o que e novo. O brief precisa do opposite — o que foi medido nas ultimas
    horas. Por isso le o Qdrant direto, ordenado por `ts` (o timestamp
    real; `iso` e o carimbo legivel).
    """
    try:
        import urllib.request
        # o order_by do Qdrant nao funciona nesse payload (devolve vazio);
        # a ordenacao e feita aqui, por ts (epoch no payload).
        body = json.dumps({
            "limit": 400, "with_payload": True, "with_vector": False,
        }).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:6333/collections/memories/points/scroll",
            data=body, method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        pts = (data.get("result") or {}).get("points") or []
        pts.sort(key=lambda pt: float((pt.get("payload") or {}).get("ts") or 0),
                 reverse=True)
        out = []
        for pt in pts:
            pl = pt.get("payload") or {}
            iso = str(pl.get("iso") or "")[:16]
            out.append(f"- [{pl.get('kind', '?')}] {iso} — "
                       f"{str(pl.get('text', ''))[:420]}")
        return out[:n]
    except Exception as e:
        return [f"(qdrant indisponivel: {type(e).__name__})"]


def fila() -> list[str]:
    p = RAIZ / "AGENTS-QUEUE.md"
    if not p.exists():
        return ["(sem fila)"]
    linhas = []
    for l in p.read_text(errors="ignore").splitlines()[:40]:
        if l.startswith("## ") or l.startswith("**Resumo") or l.startswith("**Próxima"):
            linhas.append(l.strip()[:220])
    return linhas[:8]


def roster() -> list[str]:
    p = RAIZ / ".agents" / "roster.json"
    if not p.exists():
        return ["(sem roster)"]
    try:
        data = json.loads(p.read_text())
        out = []
        agents = data.get("agents") or data.get("roster") or {}
        if isinstance(agents, dict):
            agents = list(agents.values())
        for a in agents:
            if not isinstance(a, dict):
                continue
            out.append(f"- {a.get('codename') or a.get('name')} "
                       f"[{a.get('lane')}] ctx: "
                       f"{str(a.get('context') or a.get('note') or '')[:70]}")
        return out[:8]
    except Exception:
        return ["(roster ilegível)"]


def infra() -> list[str]:
    out = []
    for svc in ("agents-watcher.service", "opencode-serve.service",
                "nv-gate.service"):
        st = run(["systemctl", "--user", "is-active", svc], 10)
        out.append(f"- {svc}: {st}")
    timers = run(["systemctl", "--user", "list-timers", "--no-pager",
                  "--all"], 20)
    for l in timers.splitlines():
        if l.strip() and "TIMER" not in l and "LEFT" not in l:
            out.append("  timer: " + l.strip()[:120])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true")
    ap.add_argument("--tail", type=int, default=14)
    args = ap.parse_args()

    now = time.strftime("%Y-%m-%d %H:%M")
    partes = [
        f"# BRIEF DA FROTA — gerado {now}",
        "",
        "> Leia isto antes de começar: é o que os OUTROS agentes já "
        "descobriram. Fonte da verdade: memória global + fila + vault.",
        "",
        "## 1. Fila (o que está em aberto agora)",
        "",
    ]
    partes += fila() or ["(vazio)"]
    partes += ["", "## 2. Memória global (o que foi aprendido/medido)", ""]
    mem = memoria(args.tail)
    partes += [f"- {l[:400]}" for l in mem] or ["(vazio)"]
    partes += ["", "## 3. Frota (quem está vivo)", ""]
    partes += roster()
    partes += ["", "## 4. Infra (quem pode trabalhar agora)", ""]
    partes += infra()
    partes += [
        "",
        "## 5. Como isto se mantém vivo",
        "",
        "- Qualquer agente: ao achar algo que muda comportamento, "
        "`jarvis_remember` (memória global) + o topo do `AGENTS-QUEUE.md`.",
        "- O `--steer-only`/erro que se repete: `jarvis_lessons` ANTES de "
        "tentar de novo.",
        "- Ao compactar: este arquivo + `jarvis_rehydrate` devolvem o estado.",
        "",
    ]
    texto = "\n".join(partes)
    if not args.print:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(texto, encoding="utf-8")
        print(f"brief: {OUT} ({len(texto)} bytes)")
    print(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
