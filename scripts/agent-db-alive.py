#!/usr/bin/env python3
"""agent-db-alive.py — a sessão produziu trabalho novo nos últimos N segundos?

POR QUE EXISTE (06/11/2026): o watcher usava
`SELECT MAX(time_updated), MAX(time_created) FROM part` — **sem filtrar por
sessão**. Como qualquer agente que escrevesse uma part (inclusive a própria IA
acordada) deixava o máximo global recente, **todas** as sessões pareciam
"vivas" → nunca havia idle → **nunca havia wake** → o watcher "não fazia
nada" (sintoma do dono).

Agora o filtro é por `session_id`: vivo = **esta** sessão produziu part nova
dentro da janela (AGENTS_DB_ALIVE, padrão 600 s).

uso: agent-db-alive.py <opencode.db> <janela_s> [session_id]
saída: 0 = viva (part nova na janela) · 1 = ociosa
"""

import sqlite3
import sys
import time


def main() -> int:
    if len(sys.argv) < 3:
        print("uso: agent-db-alive.py <db> <janela_s> [session_id]", file=sys.stderr)
        return 2
    db, janela = sys.argv[1], int(sys.argv[2])
    sessao = sys.argv[3] if len(sys.argv) > 3 else ""
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        if sessao:
            row = con.execute(
                "SELECT MAX(time_updated), MAX(time_created) FROM part WHERE session_id = ?",
                (sessao,),
            ).fetchone()
        else:
            row = con.execute(
                "SELECT MAX(time_updated), MAX(time_created) FROM part"
            ).fetchone()
    except Exception:
        return 1
    if not row:
        return 1
    agora = int(time.time() * 1000)
    for t in row:
        if t and agora - t <= janela * 1000:
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
