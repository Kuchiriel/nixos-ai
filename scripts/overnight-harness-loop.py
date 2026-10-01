#!/usr/bin/env python3
"""Overnight harness-improvement loop (30/09).

Roda N ciclos do nightwatch, entre ciclos:
  - limpa a fila (tasks velhas nao se acumulam)
  - captura o RESULTADO de cada task (traceback recebido vs o que o
    modelo produziu) para diagnosticar o "último mile"
  - mede convergência (agora reportada pelo próprio harness)

NÃO é o nightwatch (esse é o agente que conserta o código). Este é o
motor que roda o nightwatch N vezes e me devolve dado. Depois eu leio e
consigo que solucoes venham de dentro do loop noturno.

Regras de segurança (a casa):
  - nunca commita/pusha sozinho
  - só toca na fila do nightwatch (nunca em código)
  - roda em main, nunca em branch de task (lição de hoje)
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

QUEUE = Path.home() / ".local/state/jarvis/nightwatch/task_queue-nixos-ai.json"
CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 8
COOLDOWN = int(sys.argv[2]) if len(sys.argv) > 2 else 60
LOGDIR = Path("/tmp/opencode/overnight")
LOGDIR.mkdir(parents=True, exist_ok=True)


def sh(cmd, timeout=120):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)


def clean_queue():
    """Mantém só READY/IN_PROGRESS; descarta o resto (velho/acabado)."""
    try:
        q = json.loads(QUEUE.read_text())
        ts = q if isinstance(q, list) else q.get("tasks", [])
        keep = [t for t in ts if t.get("status") in ("READY", "IN_PROGRESS")]
        out = q if isinstance(q, list) else q
        if not isinstance(q, list):
            out["tasks"] = keep
        QUEUE.write_text(json.dumps(out, indent=2))
        return len(keep)
    except Exception as e:
        print(f"  clean_queue err: {e}", flush=True)
        return -1


def run_cycle(n):
    print(f"\n{'='*60}\n=== CICLO {n} — {time.strftime('%H:%M:%S')}\n{'='*60}", flush=True)
    kept = clean_queue()
    print(f"fila: {kept} tasks", flush=True)

    sh("sudo systemctl reset-failed nightwatch.service")
    sh("sudo systemctl start --no-block nightwatch.service")

    # espera o serviço terminar (inactive/failed), com teto generoso
    deadline = time.time() + 3600
    while time.time() < deadline:
        st = sh("systemctl is-active nightwatch.service").stdout.strip()
        if st in ("inactive", "failed", "deactivating"):
            break
        time.sleep(20)
    else:
        print("  (teto de 1h atingido, parando o serviço)", flush=True)
        sh("sudo systemctl stop nightwatch.service")

    # captura o resultado
    j = sh("sudo journalctl -u nightwatch.service -b --no-pager --since '10min ago'").stdout
    (LOGDIR / f"cycle-{n}.log").write_text(j)
    conv = [l for l in j.splitlines() if "Retry convergence" in l]
    commits = [l for l in j.splitlines() if "- Commits:" in l]
    completed = [l for l in j.splitlines() if "- Completed:" in l]
    failed = [l for l in j.splitlines() if "- Failed:" in l]
    print("CONVERGENCE:", conv[-1].split(":", 1)[-1].strip() if conv else "?", flush=True)
    print("COMMITS:    ", commits[-1].split(":", 1)[-1].strip() if commits else "?", flush=True)
    print("COMPLETED:  ", completed[-1].split(":", 1)[-1].strip() if completed else "?", flush=True)
    print("FAILED:     ", failed[-1].split(":", 1)[-1].strip() if failed else "?", flush=True)

    # diagnóstico do último mile: quais testes falharam e com que erro
    fails = {}
    for line in j.splitlines():
        if "passed," in line and "failed" in line:
            fails[line.split(": ")[-1].strip()] = fails.get(line.split(": ")[-1].strip(), 0) + 1
    if fails:
        print("VALIDATION (n→):", dict(list(fails.items())[:5]), flush=True)

    sh("sudo systemctl reset-failed nightwatch.service")
    return conv


def main():
    print(f"Overnight: {CYCLES} ciclos, cooldown {COOLDOWN}s, iniciou {time.strftime('%H:%M:%S')}", flush=True)
    all_conv = []
    for n in range(1, CYCLES + 1):
        try:
            c = run_cycle(n)
            if c:
                all_conv.append(c[-1])
        except Exception as e:
            print(f"ciclo {n} erro: {e}", flush=True)
        if n < CYCLES:
            print(f"cooldown {COOLDOWN}s…", flush=True)
            time.sleep(COOLDOWN)
    print(f"\n{'='*60}\n=== OVERNIGHT DONE {time.strftime('%H:%M:%S')}\n{'='*60}", flush=True)
    for i, c in enumerate(all_conv, 1):
        print(f"ciclo {i}: {c.split(':',1)[-1].strip()}", flush=True)


if __name__ == "__main__":
    main()