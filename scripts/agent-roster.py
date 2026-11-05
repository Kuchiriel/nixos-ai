#!/usr/bin/env python3
"""agent-roster.py — ROSTER + TASKS da coordenação multi-agente (02/11).

POR QUE (e o que a literatura diz):
- A2A (Google→LF/AAIF, v1.0 em 03/2026): o "Agent Card" é a peça de
  DESCOBERTA (quem existe, o que sabe) e o roteamento pode ser LÓGICA
  DETERMINÍSTICA, sem LLM no meio. Roster = agent card.
- Claude Code Agent Teams (2026): teammates COMPARTILHAM uma lista de
  tarefas, cada um CLAIMa trabalho, e o isolamento de ARQUIVOS evita
  colisão. Duas janelas no mesmo assunto só é seguro com fronteira
  explícita de arquivos.
- Anthropic (multi-agent research, 06/2025): sem OBJETIVO + FRONTEIRAS
  explícitos na delegação, os agentes DUPLICAM trabalho; e multi-agente
  custa ~15x os tokens de chat — então broadcast é caro e deve ser raro.
- CHI'26 (arXiv 2602.17864): agente proativo que interrompe sem filtro
  QUEBRA o fluxo e aumenta a carga. Wake é para quem é dono do assunto.

O QUE FAZ:
  claim/release/list/prune  — quem existe, em que lane, com que arquivos
  task add/close/list       — a lista de tarefas compartilhada (A2A Task)
  windows/resolve           — resolve nomes -> janela viva (usado pelo
                              agent-msg.sh e pelo watcher; fonte ÚNICA da
                              geometria de janelas)

ESTADO: ~/projects/.agents/roster.json (texto plano, diffável, git-friendly).
        Override: $AGENTS_ROSTER.  Lock: flock no arquivo ao lado.

USO:
  ./scripts/agent-roster.py claim --name mt5 --lane "mt5/optimizer" \
      --repo mt5 --files "backtest/**,mql/**" --note "rodando sweep v3.11"
  ./scripts/agent-roster.py list
  ./scripts/agent-roster.py task add --title "medir DD do v3.12" --owner mt5
  ./scripts/agent-roster.py release --name mt5
  ./scripts/agent-roster.py windows --json
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECTS_ROOT = Path(os.environ.get("AGENTS_ROOT", Path.home() / "projects"))
ROSTER_PATH = Path(
    os.environ.get("AGENTS_ROSTER", PROJECTS_ROOT / ".agents" / "roster.json"))
LOCK_PATH = ROSTER_PATH.with_suffix(".lock")
STALE_AFTER_S = int(os.environ.get("AGENTS_ROSTER_STALE_S", "900"))
VERSION = 1


# ── geometria de janelas (fonte única) ─────────────────────────────────
def _proc_map() -> tuple[dict[int, int], set[int]]:
    """ppid de cada pid + pids que são opencode."""
    ppid_de: dict[int, int] = {}
    agente: set[int] = set()
    for d in os.scandir("/proc"):
        if not d.name.isdigit():
            continue
        pid = int(d.name)
        try:
            stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            ppid_de[pid] = int(stat[1])
            if b"opencode" in Path(f"/proc/{pid}/cmdline").read_bytes():
                agente.add(pid)
        except Exception:
            continue
    return ppid_de, agente


def _descendants(root: int, ppid_de: dict[int, int]) -> list[int]:
    pids, frontier = [root], [root]
    while frontier:
        nxt = [p for p in ppid_de
               if ppid_de.get(p) in frontier and p not in pids]
        pids += nxt
        frontier = nxt
    return pids


def hypr_clients() -> list[dict]:
    try:
        out = subprocess.run(["hyprctl", "clients", "-j"],
                             capture_output=True, text=True, timeout=5).stdout
        return json.loads(out or "[]")
    except Exception:
        return []


def _cpu_ticks(pids: list[int]) -> int:
    """utime+stime de um conjunto de pids (ticks de clock)."""
    total = 0
    for pid in pids:
        try:
            parts = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            total += int(parts[11]) + int(parts[12])
        except Exception:
            continue
    return total


DB_PATH = Path(os.environ.get(
    "AGENTS_DB_PATH", Path.home() / ".local/share/opencode/opencode.db"))
BUSY_WINDOW_S = int(os.environ.get("AGENTS_BUSY_S", "60"))


def _session_do_pid(pid: int) -> str:
    """Session id do opencode (-s ses_...) de um pid, se houver."""
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
    except Exception:
        return ""
    parts = [p for p in argv.split("\0") if p]
    for i, p in enumerate(parts):
        if p == "-s" and i + 1 < len(parts):
            return parts[i + 1]
        if p.startswith("ses_"):
            return p
    return ""


def session_busy(session: str, janela_s: int = BUSY_WINDOW_S) -> bool:
    """O agente da session está EM TURNO agora (part nova nos últimos N s)?

    Read-only (mode=ro). Sem DB/session => False (o alvo é considerado ocioso).
    """
    if not session or not DB_PATH.exists():
        return False
    try:
        import sqlite3
        c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        r = c.execute("SELECT MAX(time_updated), MAX(time_created) FROM part "
                      "WHERE session_id=?", (session,)).fetchone()
        now = int(time.time() * 1000)
        return bool(r and any(t and now - t <= janela_s * 1000 for t in r))
    except Exception:
        return False


def agent_windows() -> list[dict]:
    """Janelas foot com um opencode VIVO dentro (process-tree, sem título)."""
    ppid_de, agente = _proc_map()
    out = []
    for c in hypr_clients():
        if c.get("class") != "foot":
            continue
        pid = c.get("pid", 0)
        desc = _descendants(pid, ppid_de)
        vivos = [p for p in desc if p in agente]
        if not vivos:
            continue
        session = ""
        for p in vivos:
            session = _session_do_pid(p)
            if session:
                break
        out.append({"address": c.get("address", ""), "pid": pid,
                    "title": c.get("title") or "", "cpu": _cpu_ticks(desc),
                    "session": session,
                    "busy": session_busy(session)})
    return out


def own_window(windows: list[dict] | None = None) -> dict | None:
    """A janela do chamador (sobe a árvore de ppid até achar um foot-agente)."""
    windows = agent_windows() if windows is None else windows
    pids = {w["pid"] for w in windows}
    ppid_de, _ = _proc_map()
    p = os.getppid()
    while p > 1:
        if p in pids:
            for w in windows:
                if w["pid"] == p:
                    return w
        p = ppid_de.get(p, 0)
    return None


def live_sessions() -> dict[str, int]:
    """session id -> pid dos TUIs opencode VIVOS.

    (03/11, dono: "quando eu reabro as janelas vcs acham que fechou")
    O ENDEREÇO da janela é efêmero: reabrir a janela = novo address → o
    roster via address dava o agente por morto. A SESSÃO é a identidade
    DURÁVEL (opencode -s ses_...) → é ela que decide a vida.
    """
    out: dict[str, int] = {}
    for d in os.scandir("/proc"):
        if not d.name.isdigit():
            continue
        pid = int(d.name)
        try:
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
        except Exception:
            continue
        if "bin/opencode" not in argv:
            continue
        sess = _session_do_pid(pid)
        if sess:
            out.setdefault(sess, pid)
    return out


def window_alive(entry: dict, windows: list[dict],
                 sessions: dict[str, int] | None = None) -> bool:
    """O agente ainda está vivo?

    address casa com uma janela viva (mesma janela) OU a SESSÃO do agente
    ainda tem um TUI opencode vivo (a janela foi reaberta/mudou de lugar).
    """
    if any(w["address"] == entry.get("window") for w in windows):
        return True
    sess = entry.get("session") or ""
    if not sess:
        return False
    sessions = live_sessions() if sessions is None else sessions
    return sess in sessions


def window_of_session(entry: dict, windows: list[dict]) -> dict | None:
    """A janela viva que carrega a sessão do agente (se houver)."""
    sess = entry.get("session") or ""
    if not sess:
        return None
    return next((w for w in windows
                 if (w.get("session") or "") == sess), None)


# ── roster: leitura/escrita atômica ───────────────────────────────────
def _blank() -> dict:
    return {"version": VERSION, "agents": [], "tasks": []}


def load() -> dict:
    try:
        data = json.loads(ROSTER_PATH.read_text())
    except Exception:
        return _blank()
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return _blank()
    data.setdefault("agents", [])
    data.setdefault("tasks", [])
    return data


def save(data: dict) -> None:
    ROSTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ROSTER_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, ROSTER_PATH)


class _Lock:
    """flock no arquivo ao lado (serializa claim/release/task)."""

    def __enter__(self):
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(LOCK_PATH, "w")
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()
        return False


def _overlaps(a: list[str], b: list[str]) -> list[str]:
    """Interseção entre globs de arquivos (mesmo repo OU path absoluto)."""
    def norm(g: str) -> str:
        return g.strip().rstrip("/")
    sa = {norm(x) for x in a if x.strip()}
    sb = {norm(x) for x in b if x.strip()}
    hits = set()
    for x in sa:
        for y in sb:
            if x == y or x.startswith(y + "/") or y.startswith(x + "/"):
                hits.add(x if x in sb else y)
            elif "**" in x and y.startswith(x.split("**")[0]):
                hits.add(y)
            elif "**" in y and x.startswith(y.split("**")[0]):
                hits.add(x)
    return sorted(hits)


def _files_of(entry: dict) -> list[str]:
    return list(entry.get("files") or [])


# ── comandos ───────────────────────────────────────────────────────────
def cmd_claim(args) -> int:
    windows = agent_windows()
    own = own_window(windows)
    if own is None:
        print("agent-roster: chamador não vive numa janela-agente "
              "(foot com opencode vivo) — rode de dentro do terminal do "
              "agente, ou use --window/--pid para claim manual",
              file=sys.stderr)
        return 2
    with _Lock():
        data = load()
        agents = data["agents"]
        for e in agents:
            if e["name"] == args.name and window_alive(e, windows):
                print(f"agent-roster: nome '{args.name}' já está vivo na "
                      f"janela {e.get('window')} — use outro nome ou "
                      f"release antes", file=sys.stderr)
                return 3
        for e in agents:
            if e["name"] == args.name:
                continue
            hit = _overlaps(_files_of(e), args.files or [])
            if hit and not args.force:
                print(f"agent-roster: COLISÃO de arquivos com '{e['name']}' "
                      f"({', '.join(hit)}) — duas janelas no mesmo arquivo "
                      f"duplicam trabalho (Anthropic: fronteiras explícitas). "
                      f"Use --force se a intenção é assumir.", file=sys.stderr)
                return 4
        entry = {
            "name": args.name,
            "lane": args.lane or "",
            "repo": args.repo or "",
            "files": args.files or [],
            "note": args.note or "",
            "window": own["address"],
            "pid": own["pid"],
            "session": own.get("session", ""),
            "claimed_at": int(time.time()),
        }
        agents[:] = [e for e in agents if e["name"] != args.name]
        agents.append(entry)
        save(data)
    print(f"roster: '{args.name}' na lane '{entry['lane'] or '(sem lane)'}' "
          f"(repo={entry['repo'] or '-'}, janela={entry['window']})")
    return 0


def cmd_release(args) -> int:
    with _Lock():
        data = load()
        before = len(data["agents"])
        data["agents"] = [e for e in data["agents"] if e["name"] != args.name]
        if len(data["agents"]) == before:
            print(f"agent-roster: '{args.name}' não está no roster")
            return 1
        save(data)
    print(f"roster: '{args.name}' liberado")
    return 0


def cmd_list(args) -> int:
    data = load()
    windows = agent_windows()
    sessions = live_sessions()
    sessao = {w["address"]: w.get("session", "") for w in windows}
    now = int(time.time())
    rows = []
    mudou = False
    for e in data["agents"]:
        alive = window_alive(e, windows, sessions)
        # auto-cura: a sessão bate com uma janela viva → o address mudou
        # (o dono reabriu a janela) → o registro passa a apontar pra ela
        wv = window_of_session(e, windows)
        if wv and wv.get("address") != e.get("window"):
            e["window"] = wv.get("address")
            e["pid"] = wv.get("pid")
            mudou = True
        age = now - int(e.get("claimed_at") or now)
        state = "live" if alive else ("stale" if age > STALE_AFTER_S else "dead")
        rows.append({**e, "state": state, "age_s": age,
                     "session": e.get("session") or sessao.get(e.get("window"), ""),
                     "busy": next((bool(w.get("busy")) for w in windows
                                   if w["address"] == e.get("window")), False)})
    if mudou:
        with _Lock():
            save(data)
    if args.json:
        print(json.dumps({"agents": rows, "tasks": data["tasks"]},
                         ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("roster vazio (nenhum agente fez claim)")
    for r in sorted(rows, key=lambda x: x["name"]):
        print(f"{r['state']:5} {r['name']:14} lane={r['lane'] or '-':22} "
              f"repo={r['repo'] or '-':10} janela={r['window'] or '-':16} "
              f"age={r['age_s']}s")
        if r.get("note"):
            print(f"      nota: {r['note']}")
    if data["tasks"]:
        print("\ntarefas:")
        for t in data["tasks"]:
            print(f"  {t['id']:6} [{t['status']:8}] owner={t.get('owner') or '-':14} "
                  f"{t['title']}")
    return 0


def cmd_prune(args) -> int:
    with _Lock():
        data = load()
        windows = agent_windows()
        now = int(time.time())
        keep = []
        for e in data["agents"]:
            if window_alive(e, windows):
                keep.append(e)
            elif now - int(e.get("claimed_at") or 0) > STALE_AFTER_S:
                continue
            else:
                keep.append(e)
        removed = len(data["agents"]) - len(keep)
        data["agents"] = keep
        save(data)
    print(f"roster: {removed} entradas mortas removidas")
    return 0


def cmd_task_add(args) -> int:
    with _Lock():
        data = load()
        n = 1 + max([int(t["id"].split("-")[1]) for t in data["tasks"]
                     if t["id"].startswith("t-") and t["id"].split("-")[1].isdigit()]
                    or [0])
        task = {
            "id": f"t-{n}",
            "title": args.title,
            "owner": args.owner or "",
            "lane": args.lane or "",
            "files": args.files or [],
            "status": "working" if args.owner else "pending",
            "note": args.note or "",
            "created": int(time.time()),
        }
        data["tasks"].append(task)
        save(data)
    print(f"task: {task['id']} criada (owner={task['owner'] or '-'}, "
          f"status={task['status']}) — {task['title']}")
    return 0


def cmd_task_close(args) -> int:
    with _Lock():
        data = load()
        for t in data["tasks"]:
            if t["id"] == args.id:
                t["status"] = "done"
                t["closed"] = int(time.time())
                save(data)
                print(f"task: {args.id} fechada")
                return 0
    print(f"agent-roster: task {args.id} não existe", file=sys.stderr)
    return 1


def cmd_task_list(args) -> int:
    data = load()
    if args.json:
        print(json.dumps(data["tasks"], ensure_ascii=False, indent=2))
        return 0
    for t in data["tasks"]:
        print(f"{t['id']:6} [{t['status']:8}] owner={t.get('owner') or '-':14} "
              f"{t['title']}")
    return 0


def cmd_windows(args) -> int:
    windows = agent_windows()
    own = own_window(windows)
    out = {
        "own": own,
        "others": [w for w in windows if not own or w["address"] != own["address"]],
        "all": windows,
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"minha janela: {own['address'] if own else '(não detectada)'}")
        for w in out["others"]:
            print(f"  {w['address']} pid={w['pid']} title={w['title']!r}")
    return 0


def cmd_resolve(args) -> int:
    """Resolve um NOME do roster -> janela viva (JSON). Sai 1 se não achar."""
    data = load()
    windows = agent_windows()
    sessions = live_sessions()
    for e in data["agents"]:
        if e["name"] != args.name:
            continue
        alive = window_alive(e, windows, sessions)
        wv = window_of_session(e, windows)
        out = {**e, "live": alive,
               "window": (wv or e).get("address") if alive else "",
               "pid": (wv or e).get("pid", e.get("pid")) if alive else 0}
        print(json.dumps(out, ensure_ascii=False))
        return 0 if alive else 1
    print(json.dumps({"error": "nome desconhecido", "name": args.name},
                     ensure_ascii=False))
    return 1


def cmd_events(args) -> int:
    """Filtra eventos do watcher pela LANE do dono da janela (stdin → stdout).

    Regras:
      - evento de commit do repo X → só o agente dono do repo X (ou lane
        "X/...") ou um generalista (repo vazio);
      - evento global (fila/hooks) → todo mundo;
      - sem roster (ou janela sem claim) → legado: passa tudo.
    """
    eventos = [linha for linha in sys.stdin.read().splitlines() if linha.strip()]
    data = load()
    agentes = data.get("agents", [])
    if not agentes:
        print("\n".join(eventos))
        return 0
    me = next((a for a in agentes if a.get("window") == args.window), None)
    if me is None:
        # (03/11) a janela foi reaberta → address novo: casa pela SESSÃO
        windows = agent_windows()
        sess = next((w.get("session", "") for w in windows
                     if w.get("address") == args.window), "")
        if sess:
            me = next((a for a in agentes if a.get("session") == sess), None)
    if me is None:
        print("\n".join(eventos))
        return 0
    meu_repo = (me.get("repo") or "").strip()
    meu_lane = (me.get("lane") or "").strip()

    def pertence(linha: str) -> bool:
        corpo = linha.split(": ", 1)[-1]
        if not corpo.startswith("commit:"):
            return True                      # fila/hooks = global
        partes = corpo.split()
        # "commit:<repo> <hash>" → repo é o primeiro campo depois do prefixo
        repo = partes[0].split(":", 1)[1] if partes and ":" in partes[0] else ""
        if not meu_repo:
            return True                      # generalista = global
        if repo.lower() == meu_repo.lower():
            return True
        return meu_lane.lower().startswith(repo.lower() + "/")

    print("\n".join(linha for linha in eventos if pertence(linha)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="roster+tasks da coordenação")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("claim", help="reivindica uma lane (a janela do chamador)")
    p.add_argument("--name", required=True)
    p.add_argument("--lane", default="")
    p.add_argument("--repo", default="")
    p.add_argument("--files", default="", help="globs separados por vírgula")
    p.add_argument("--note", default="")
    p.add_argument("--force", action="store_true",
                   help="assume mesmo com colisão de arquivos")
    p.set_defaults(func=cmd_claim)

    p = sub.add_parser("release", help="libera a claim")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_release)

    p = sub.add_parser("list", help="lista o roster + tarefas")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("prune", help="remove entradas mortas")
    p.set_defaults(func=cmd_prune)

    p = sub.add_parser("task", help="lista de tarefas compartilhada")
    tsub = p.add_subparsers(dest="tcmd", required=True)
    q = tsub.add_parser("add")
    q.add_argument("--title", required=True)
    q.add_argument("--owner", default="")
    q.add_argument("--lane", default="")
    q.add_argument("--files", default="")
    q.add_argument("--note", default="")
    q.set_defaults(func=cmd_task_add)
    q = tsub.add_parser("close")
    q.add_argument("--id", required=True)
    q.set_defaults(func=cmd_task_close)
    q = tsub.add_parser("list")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_task_list)

    p = sub.add_parser("windows", help="janelas de agente vivas (JSON)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_windows)

    p = sub.add_parser("resolve", help="nome do roster -> janela viva (JSON)")
    p.add_argument("name")
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("events", help="filtra eventos do watcher pela lane "
                                      "(stdin: linhas de evento)")
    p.add_argument("--window", required=True)
    p.set_defaults(func=cmd_events)

    args = ap.parse_args()
    if getattr(args, "files", ""):
        args.files = [f.strip() for f in args.files.split(",") if f.strip()]
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
