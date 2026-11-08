#!/usr/bin/env python3
"""night-comms.py — a PASSADA DE MADRUGADA da comunicação entre agentes.

POR QUE ESTE SCRIPT EXISTE (dono, 07/11)
-----------------------------------------
De madrugada havia um serviço que trabalhava num **projeto de teste de
jogo** (o "dungeon", via `team-suite.timer` às 03:30): os bots do `team/`
faziam features e o bot de suite validava. Não ajuda em nada — é o
exercício de um time de bots, não o trabalho dos agentes de verdade.

O dono pediu: achar o serviço de madrugada e **adaptá-lo para o nosso
propósito** — que é a **comunicação**: os agentes opencode (que moram no
bus de coord) devem saber o que tem pendente, mesmo com o dono dormindo.

O QUE ESTA PASSADA FAZ (tudo sem gastar token do modelo):
  1. Lê o BUS (coord) e monta o QUADRO (claims ativas + agentes vivos +
     colisões) — o mesmo quadro que o Telegram mostra em `/board`.
  2. Entrega a cada agente que tem pendência uma **NOTA** (noReply=true:
     a mensagem entra na sessão dele, o agente NÃO roda, zero token).
  3. Reporta um resumo ao dono no **Telegram**.
  4. Deixa o registro em `~/.local/state/jarvis/night-comms.jsonl` (o que
     foi entregue, para o dia seguinte e para o watcher).

O AGENTE DORME E ACORDA SOZINHO: quem roda é o `agents-watcher.sh` (o
watcher do bus já existe e acorda o agente quando há trabalho de verdade).
Esta passada é o "estado da noite": ninguém perde o que chegou na madrugada.

Uso:
    python3 scripts/night-comms.py                # roda a passada
    python3 scripts/night-comms.py --dry-run      # só mostra o quadro
    python3 scripts/night-comms.py --agent <nome> # só um agente
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JARVIS_SRC = HERE.parent / "modules" / "ai" / "jarvis" / "src"
if str(JARVIS_SRC) not in sys.path:
    sys.path.insert(0, str(JARVIS_SRC))

LOG = Path(
    os.environ.get(
        "JARVIS_STATE_DIR", str(Path.home() / ".local/state/jarvis")
    )
) / "night-comms.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="só mostra o quadro")
    ap.add_argument("--agent", default="", help="só este agente")
    ap.add_argument("--no-notify", action="store_true", help="não manda pro Telegram")
    args = ap.parse_args()

    from jarvis.core import comms

    board = comms.board_text()
    print(board)

    if args.dry_run:
        return 0

    report = comms.night_pass(
        agent=args.agent,
        deliver_notes=not args.no_notify,
    )
    print()
    print("passada da madrugada:")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:2000])

    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(report, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"(log não gravado: {exc})", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
