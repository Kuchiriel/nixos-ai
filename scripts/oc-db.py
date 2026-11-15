#!/usr/bin/env python3
"""oc-db.py — leitura do DB do opencode 2.2.6 (fonte unica da casa).

POR QUE ESTE MODULO (15/11, crouton-alpha): o opencode 2.2.6 grava a
atividade em `session_message`/`session_part`/`session_v2`; as tabelas
`message`/`part`/`session` sao o schema LEGADO do 1.x e ficaram CONGELADAS
em 09/11 no host (medido: max(part.time_updated) = 09/11 06:12, enquanto
session_message chega a 15/11 04:48). Varios scripts da casa liam a
tabela ERRADA e concluem "o agente esta morto" (ou, pior, que o DB
inteiro morreu) — foi o que fez o `prune` apagar os 4 agentes vivos.

ESTE modulo escolhe a tabela certa sozinho:
  1) se `session_message` tem linhas recentes -> usa ela (2.2.6);
  2) senao, se `part` tem linhas recentes -> usa ela (1.x);
  3) senao -> sem atividade.

API:
  oc_db.py <db> <janela_s> [session_id]     # 0 = viva, 1 = ociosa
  oc_db.py --sessions <db> <janela_s>       # lista session_id vivos (1 por linha)
  oc_db.py --last <db> <session_id>         # epoch(s) da ultima atividade
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

LEGACY = ("message", "part")          # 1.x
MODERN = ("session_message", "session_part")  # 2.2.x


def _tables(con) -> set[str]:
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except Exception:
        return set()


def _recent(con, table: str, janela_ms: int, sessao: str | None) -> list[tuple[str, int]]:
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    if "time_updated" not in cols:
        return []
    tcol = "time_updated"
    if sessao:
        q = f"SELECT session_id, MAX({tcol}) FROM {table} WHERE session_id = ? AND {tcol} >= ? GROUP BY session_id"
        rows = con.execute(q, (sessao, janela_ms)).fetchall()
    else:
        q = f"SELECT session_id, MAX({tcol}) FROM {table} WHERE {tcol} >= ? GROUP BY session_id"
        rows = con.execute(q, (janela_ms,)).fetchall()
    return [(str(r[0]), int(r[1] or 0)) for r in rows]


def tabelas_ativas(con, janela_ms: int, sessao: str | None) -> tuple[str, list[tuple[str, int]]]:
    """(tabela usada, [(session_id, ultimo_ms)]) — escolhe a tabela VIVA."""
    tabs = _tables(con)
    # 2.2.x primeiro (o schema que o 2.2.6 usa)
    for tab in ("session_message", "session_part"):
        if tab not in tabs:
            continue
        rows = _recent(con, tab, janela_ms, sessao)
        if rows:
            return tab, rows
    # 1.x legado (fallback)
    for tab in ("part", "message"):
        if tab not in tabs:
            continue
        rows = _recent(con, tab, janela_ms, sessao)
        if rows:
            return tab, rows
    # nenhuma tabela com atividade na janela: devolve a preferencia (modern)
    pref = "session_message" if "session_message" in tabs else ("part" if "part" in tabs else "")
    return pref, []


def main() -> int:
    argv = sys.argv[1:]
    modo = ""
    if argv and argv[0].startswith("--"):
        modo = argv[0]
        argv = argv[1:]
    if len(argv) < 2:
        print("uso: oc-db.py <db> <janela_s> [session_id] | --sessions <db> <janela_s> | --last <db> <session_id>", file=sys.stderr)
        return 2
    db = argv[0]
    if modo == "--last":
        sessao = argv[1]
        janela_s = 10 * 365 * 24 * 3600
    else:
        janela_s = int(argv[1])
        sessao = argv[2] if len(argv) > 2 else None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
    except Exception:
        return 1
    agora_ms = int(time.time() * 1000)
    janela_ms = agora_ms - janela_s * 1000
    try:
        if modo == "--sessions":
            _tab, rows = tabelas_ativas(con, janela_ms, None)
            for sid, _ts in rows:
                print(sid)
            return 0
        if modo == "--last":
            _tab, rows = tabelas_ativas(con, janela_ms, sessao)
            for sid, ts in rows:
                if sid == sessao:
                    print(ts // 1000)
                    return 0
            return 1
        _tab, rows = tabelas_ativas(con, janela_ms, sessao)
        return 0 if rows else 1
    except Exception:
        return 1
    finally:
        try:
            con.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
