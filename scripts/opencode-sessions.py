#!/usr/bin/env python3
"""opencode-sessions — registro e reabertura das sessões opencode.

POR QUÊ: quando o dono fecha o TUI (Ctrl+C), o foot fecha junto e a
mensagem que o opencode deixa ("pra abrir a sessão de novo") morre com a
janela. Depois é caça ao tesouro no SQLite.

Este utilitário é a fonte única do "como reabrir":
  * `list`     — sessões recentes (SQLite), com marca de as que estão vivas;
  * `last`     — a última sessão fechada (estado em ~/.local/state/jarvis);
  * `closed`   — registra que uma sessão foi encerrada (o wrapper chama);
  * `resume`   — imprime o comando para reabrir (ou executa).

SQLite: ~/.local/share/opencode/opencode.db (modo ro; o storage/ JSON só
tem sessões antigas). Tabela `session`: id, title, directory, time_updated.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
DB = HOME / ".local/share/opencode/opencode.db"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state")) / "jarvis"
CLOSED_FILE = STATE_DIR / "last-closed-session.json"
RUNNING_FILE = STATE_DIR / "opencode-sessions-running.json"


def _db() -> sqlite3.Connection | None:
    if not DB.is_file():
        return None
    try:
        return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _running_ids() -> set[str]:
    """Sessões abertas agora (mesmo mecanismo do snapshot: cmdline -s)."""
    ids: set[str] = set()
    try:
        out = subprocess.run(["pgrep", "-f", r"opencode -s "], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ids
    for pid_s in out.split():
        try:
            raw = Path(f"/proc/{pid_s}/cmdline").read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        parts = [p for p in raw.split("\0") if p]
        for i, part in enumerate(parts):
            if part == "-s" and i + 1 < len(parts):
                ids.add(parts[i + 1])
    return ids


def list_sessions(limit: int = 15, only_closed: bool = False) -> list[dict]:
    con = _db()
    if con is None:
        return []
    running = _running_ids()
    rows: list[dict] = []
    try:
        for sid, title, directory, updated in con.execute(
            "SELECT id, title, directory, time_updated FROM session "
            "ORDER BY time_updated DESC LIMIT ?", (limit * 3,)
        ):
            item = {
                "id": sid,
                "title": title or "(sem título)",
                "directory": directory or "",
                "updated": updated,
                "running": sid in running,
            }
            if only_closed and item["running"]:
                continue
            rows.append(item)
            if len(rows) >= limit:
                break
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return rows


def mark_closed(session_id: str, title: str = "", directory: str = "") -> dict:
    """Registra a última sessão encerrada (chamado pelo wrapper)."""
    entry = {
        "id": session_id,
        "title": title,
        "directory": directory or os.getcwd(),
        "closed_at": int(time.time()),
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CLOSED_FILE.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    return entry


def last_closed() -> dict | None:
    try:
        return json.loads(CLOSED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cmd_list(args: argparse.Namespace) -> int:
    rows = list_sessions(args.limit, only_closed=args.closed)
    if not rows:
        print("(nenhuma sessão no banco)")
        return 0
    print(f"{'STATUS':8s} {'SESSÃO':24s} {'QUANDO':12s} TÍTULO")
    for row in rows:
        when = time.strftime("%d/%m %H:%M", time.localtime(row["updated"] / 1000))
        status = "ABERTA" if row["running"] else "fechada"
        print(f"{status:8s} {row['id']:24s} {when:12s} {row['title'][:60]}")
    closed = last_closed()
    if closed:
        print(f"\núltima encerrada: {closed['id']}  ({closed['title'][:50]})")
    return 0


def cmd_last(args: argparse.Namespace) -> int:
    entry = last_closed()
    if not entry:
        print("nenhuma sessão encerrada registrada ainda", file=sys.stderr)
        return 1
    print(entry["id"])
    return 0


def cmd_closed(args: argparse.Namespace) -> int:
    session_id = args.session
    title = args.title
    directory = args.directory
    if not title:
        con = _db()
        if con is not None:
            row = con.execute("SELECT title, directory FROM session WHERE id = ?",
                              (session_id,)).fetchone()
            con.close()
            if row:
                title, directory = row[0] or "", row[1] or directory
    entry = mark_closed(session_id, title, directory)
    print(json.dumps(entry, ensure_ascii=False))
    return 0


def cmd_directory(args: argparse.Namespace) -> int:
    """Diretorio de uma sessao (para reabrir no lugar certo)."""
    con = _db()
    if con is None:
        return 1
    row = con.execute("SELECT directory FROM session WHERE id = ?", (args.session,)).fetchone()
    con.close()
    if row and row[0]:
        print(row[0])
        return 0
    return 1



def cmd_resolve(args: argparse.Namespace) -> int:
    """Descobre o id da sessao criada depois de --since-ms neste diretorio."""
    con = _db()
    if con is None:
        return 1
    row = con.execute(
        "SELECT id FROM session WHERE directory = ? AND time_created >= ? "
        "ORDER BY time_created DESC LIMIT 1", (args.directory, args.since_ms)).fetchone()
    con.close()
    if row:
        print(row[0])
        return 0
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="registro e reabertura de sessões opencode")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="sessões recentes")
    p_list.add_argument("--limit", type=int, default=15)
    p_list.add_argument("--closed", action="store_true", help="só as que não estão abertas")
    p_list.set_defaults(func=cmd_list)

    p_last = sub.add_parser("last", help="id da última sessão encerrada")
    p_last.set_defaults(func=cmd_last)

    p_closed = sub.add_parser("closed", help="registra sessão encerrada")
    p_closed.add_argument("session")
    p_closed.add_argument("--title", default="")
    p_closed.add_argument("--directory", default="")
    p_closed.set_defaults(func=cmd_closed)

    p_dir = sub.add_parser("directory", help="diretório de uma sessão")
    p_dir.add_argument("--session", required=True)
    p_dir.set_defaults(func=cmd_directory)

    p_resolve = sub.add_parser("resolve", help="id da sessão criada depois de --since-ms")
    p_resolve.add_argument("--since-ms", type=int, required=True)
    p_resolve.add_argument("--directory", default=os.getcwd())
    p_resolve.set_defaults(func=cmd_resolve)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
