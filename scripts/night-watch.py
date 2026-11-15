#!/usr/bin/env python3
"""night-watch — vigilancia noturna da frota (15/11, crouton-alpha).

O QUE FAZ (por ciclo):
  1. roda o provider-guard (rotaciona o modelo sozinho em 429);
  2. checa as sessoes dos agentes do roster: morta/ausente -> acorda via
     API (mesmo caminho do /to do Telegram, agora headless e comprovado);
  3. mede a atividade: quem worked, quem esta parado, e o que responderam;
  4. escreve um resumo em ~/.local/state/jarvis/night-watch.log (append).

COMO RODAR:
  nohup python3 scripts/night-watch.py --interval 300 >/dev/null 2>&1 &
  (ou via systemd --user; o dono liga com "night-watch start")

DISCRETO: nao notifica o dono a cada ciclo (evita spam); so registra. A
notificacao fica para eventos reais (429 rotacionado, agente acordado).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
REPO = HOME / "projects/nixos-ai"
STATE = Path(os.environ.get("JARVIS_STATE_DIR", str(HOME / ".local/state/jarvis")))
LOG = STATE / "night-watch.log"
SRC = str(REPO / "modules/ai/jarvis/src")
GUARD = str(REPO / "scripts/agent-provider-guard.py")
ROSTER = str(REPO / "scripts/agent-roster.py")
WAKE = str(REPO / "scripts/agent-api.py")


def log(msg: str) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%d/%m %H:%M")
    with LOG.open("a") as fh:
        fh.write(f"[{stamp}] {msg}\n")
    print(msg, flush=True)


def roster() -> list[dict]:
    try:
        out = subprocess.run(["python3", ROSTER, "list", "--json"],
                             capture_output=True, text=True, timeout=30)
        d = json.loads(out.stdout or "{}")
        return d.get("agents") or []
    except Exception as exc:  # noqa: BLE001
        log(f"roster falhou: {exc}")
        return []


def guard() -> str:
    try:
        out = subprocess.run(["python3", GUARD, "scan", "--since-min", "10"],
                             capture_output=True, text=True, timeout=420)
        return (out.stdout or out.stderr or "").strip()[-400:]
    except Exception as exc:  # noqa: BLE001
        return f"guard falhou: {exc}"


def wake(session: str, text: str) -> str:
    try:
        out = subprocess.run(["python3", WAKE, "--session", session, "--text", text],
                             capture_output=True, text=True, timeout=120)
        return (out.stdout or out.stderr or "").strip()[:200]
    except Exception as exc:  # noqa: BLE001
        return f"wake falhou: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

    while True:
        ciclo = datetime.now().strftime("%d/%m %H:%M")
        g = guard()
        if g and "sem evento novo" not in g and "log ausente" not in g:
            log(f"[{ciclo}] provider-guard: {g}")
            if "rotacao" in g:
                log(f"[{ciclo}] ROTACAO aplicada: {g.split('rotacao:')[-1][:160]}")

        agentes = roster()
        vivos = [a for a in agentes if a.get("session")]
        log(f"[{ciclo}] roster: {len(agentes)} agentes | com sessao: {len(vivos)}")
        for a in vivos:
            sess = a.get("session")
            nome = a.get("codename") or a.get("name")
            if not sess.startswith("ses_"):
                continue
            # se a sessao nao responde a API, acorda (mesmo caminho do /to)
            try:
                import urllib.request
                pw = ""
                env = HOME / ".config/opencode/server.env"
                for line in env.read_text().splitlines():
                    if line.startswith("OPENCODE_SERVER_PASSWORD="):
                        pw = line.split("=", 1)[1].strip().strip("\"'")
                        break
                import base64
                auth = "Basic " + base64.b64encode(f"opencode:{pw}".encode()).decode()
                req = urllib.request.Request(
                    f"http://100.121.100.103:4599/api/session/{sess}",
                    headers={"Authorization": auth})
                urllib.request.urlopen(req, timeout=15).read()
            except Exception as exc:  # noqa: BLE001
                # 404 = a sessao NAO EXISTE mais (virou registro no DB, o
                # opencode nao a ve). Acordar nao adianta: em vez de tocar
                # todo ciclo, o claim e liberado (prune oficial da casa).
                if "404" in str(exc):
                    try:
                        subprocess.run(["python3", ROSTER, "release", "--name",
                                        str(a.get("name") or "")],
                                       capture_output=True, text=True, timeout=30)
                        log(f"[{ciclo}] {nome}: sessao nao existe mais (404) — claim liberado")
                    except Exception as exc2:  # noqa: BLE001
                        log(f"[{ciclo}] {nome}: 404 e release falhou: {exc2}")
                    continue
                log(f"[{ciclo}] {nome}: sessao nao responde ({exc}) — acordando")
                r = wake(sess, "[night-watch] Sessao nao responde; retome a tarefa em andamento.")
                log(f"[{ciclo}] {nome}: wake -> {r[:160]}")

        if args.once:
            return 0
        time.sleep(max(60, args.interval))


if __name__ == "__main__":
    sys.exit(main())
