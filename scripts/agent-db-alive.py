#!/usr/bin/env python3
"""agent-db-alive.py — a sessão produziu trabalho novo nos últimos N segundos?

(15/11, crouton-alpha) DELEGADO ao oc-db.py (fonte unica). O bug medido:
esta copia consultava a tabela `part`, que no opencode 2.2.6 e o schema
LEGADO do 1.x — congelada em 09/11 no host (max(part.time_updated) =
09/11 06:12). O 2.2.6 grava a atividade em `session_message`/`session_part`
(medido: session_message chega a 15/11 04:48). Efeito: o watcher via
`agents-watcher.sh:agente_vivo_db` concluia que as sessoes vivas estavam
ociosas -> wake nunca acontecia (o sintoma "o agent watcher que ate agora
nao fez nada"), e o prune apagava agentes vivos.

uso: agent-db-alive.py <opencode.db> <janela_s> [session_id]
saida: 0 = viva (atividade nova na janela) · 1 = ociosa
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
OC_DB = os.path.join(HERE, "oc-db.py")


def main() -> int:
    if len(sys.argv) < 3:
        print("uso: agent-db-alive.py <db> <janela_s> [session_id]", file=sys.stderr)
        return 2
    cmd = ["python3", OC_DB] + sys.argv[1:]
    try:
        rc = subprocess.run(cmd, capture_output=True, timeout=20).returncode
    except Exception:
        return 1
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
