#!/usr/bin/env python3
"""fleet-milestone — notifica o dono no celular SÓ em marcos da frota.

Marcos (regex no corpo do bus, issue #12):
  - credencial rotacionada / key-rotate
  - veredito do A/B (5 passed / ck=v3 com motivo review)
  - entrega de artefato (docs/... commitado)
  - claim nova de outro agente
  - falha de entrega (inbox preso, wake failed)

Anti-flood: dedup por id de comentário em ~/.local/state/fleet-milestone.seen.json,
no máximo 6 notificações por hora, e --id estável no notify do celular.

Uso: fleet-milestone [--dry-run] [--limit 40]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

STATE = Path.home() / ".local/state/fleet-milestone.seen.json"
PHONE = os.environ.get("TERMUX_PHONE_SSH", os.environ.get("PHONE", "u0_a438@100.104.175.123"))  # fallback local; env tem precedência
PATTERNS = [
    (re.compile(r"credencial rotacionada|key-rotate", re.I), "KEY"),
    (re.compile(r"ck=v3.*(5 passed|motivo=review)|veredito", re.I), "AB"),
    (re.compile(r"entregou|entrega.*commit|docs/[a-z-]+-17-11", re.I), "ENTREGA"),
    (re.compile(r"inbox preso|fleet-watchdog|wake.*falh", re.I), "WAKE"),
    (re.compile(r"claim de .* na lane", re.I), "CLAIM"),
    (re.compile(r"\*\*done\*\*|ENTREGA OK|GUIA-FROTA", re.I), "DONE"),
]


def seen_load() -> set[str]:
    try:
        return set(json.loads(STATE.read_text()))
    except Exception:
        return set()


def seen_save(s: set[str]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(sorted(s)[-500:]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()

    # (17/11) BUG REAL: a issue tem 2432 comentarios e a API devolve os MAIS
    # ANTIGOS na pagina 1. Ler per_page=40 sem pagina = outubro/2025, nunca
    # as mensagens de hoje. Descobre o total e vai na ULTIMA pagina.
    tot = subprocess.run(
        ["gh", "api", "repos/Kuchiriel/mt5/issues/12", "--jq", ".comments"],
        capture_output=True, text=True, timeout=60)
    try:
        total = int((tot.stdout or "0").strip())
    except Exception:
        total = 0
    per = max(10, min(100, a.limit))
    pagina = max(1, (total + per - 1) // per)
    r = subprocess.run(
        ["gh", "api", f"repos/Kuchiriel/mt5/issues/12/comments?per_page={per}&page={pagina}",
         "--jq", '.[] | {id: .id, body: .body, created: .created_at}'],
        capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        print("fleet-milestone: bus indisponível")
        return 0
    print(f"bus: {total} comentarios, lendo pagina {pagina} ({per}/pagina)")
    try:
        items = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
    except Exception:
        items = []
    items = items[::-1]
    seen = seen_load()
    novos = []
    agora = time.time()
    for it in items:
        key = str(it.get("id"))
        # so marcos das ultimas 2 h (o bus tem meses de histórico)
        try:
            ts = time.mktime(time.strptime(str(it.get("created") or "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            ts = 0
        if ts and (agora - ts) > 7200:
            continue
        if key in seen:
            continue
        body = str(it.get("body") or "")
        tags = [tag for rx, tag in PATTERNS if rx.search(body)]
        if tags:
            novos.append((key, tags[0], body))
    # anti-flood: no máximo 6 por execução
    for key, tag, body in novos[:3]:
        line = " ".join(body.split())[:110]
        msg = f"FROTA {tag}: {line}"
        print(("dry-run " if a.dry_run else "") + msg)
        if not a.dry_run:
            subprocess.run(
                ["ssh", "-4", "-p", "8022", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
                 PHONE, "~/bin/notify", msg, "--title", "fleet-marco", "--id",
                 f"fleet-{key[-10:]}"], capture_output=True, timeout=40)
        seen.add(key)
    if not a.dry_run:
        seen_save(seen)
    print(f"marcos novos: {len(novos[:3])} de {len(items)} mensagens lidas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
