#!/usr/bin/env python3
"""extract_sessions.py — extrai as sessões do opencode 1.18.34 (DB v1) para MARKDOWN.

POR QUE (07/11/2026, dono): "da pra importar as coisas da db antiga na nova pra
nao perder? pesquisa". RESPOSTA DA PESQUISA (medida, 3 caminhos testados):
  - o opencode 2.2.6 TEM `session export` e `session import` (o import aceita
    JSON ou URL) => o caminho existe, MAS so entre DBs v2;
  - o export do 2.2.6 nao le o DB v1 (ele busca na tabela `session_v2`; o DB
    antigo so tem `session`/`message`/`part`) => testei: DB atual, XDG_DATA_HOME
    apontando pro antigo e swap do arquivo => todos dao "Session not found";
  - o binario 1.18.34 nao tem export (so `session list`).
=> nao ha IMPORT oficial das sessoes v1. O que resta (e o que preserva o
   CONHECIMENTO, que e' o que importa) e' EXTRAIR o conteudo: as mensagens viram
   markdown versionado e pesquisavel (git grep + RAG), e o .db antigo segue como
   arquivo-fonte (o sqlite ainda le).

O QUE ESTE SCRIPT FAZ:
  1. indice  - lista todas as sessoes do DB antigo (id, titulo, msgs, data,
               tamanho) e escolhe as "valiosas" (titulo nao-generico OU muitas
               mensagens) -> um indice.md;
  2. extrai  - escreve o markdown das sessoes escolhidas em
               docs/sessions/<id>__<slug>.md (cabecalho com metadados + as
               mensagens em ordem, com o papel de cada uma);
  3. resume  - um resumo por sessao (primeiras mensagens do usuario) para o
               indice, sem precisar abrir cada arquivo.

USO:
  python3 scripts/extract_sessions.py --db ~/.local/share/opencode/opencode-stable.db \
      --out docs/sessions --indice docs/sessions/INDICE.md
  python3 scripts/extract_sessions.py --db ... --out ... --todas    # extrai todas
  python3 scripts/extract_sessions.py --db ... --out ... --min-msgs 20 --indice ...
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

GENERICO = re.compile(r"^(New session|untitled|test|session)", re.I)


def slug(text: str, limite: int = 60) -> str:
    s = re.sub(r"[^\w\s.-]", "", text or "").strip()
    s = re.sub(r"[\s_]+", "-", s)
    return (s[:limite] or "sessao").strip("-")


def abrir(db: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def sessoes(c: sqlite3.Connection) -> list[dict]:
    """Sessoes do schema v1 (session/message/part)."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(session)")}
    tem_id = "id" in cols
    tem_titulo = "title" in cols
    tem_dir = "directory" in cols
    tem_time = "time_created" in cols
    campos = ["s.id"]
    if tem_titulo:
        campos.append("s.title")
    if tem_dir:
        campos.append("s.directory")
    if tem_time:
        campos.append("s.time_created")
    sql = f"SELECT {', '.join(campos)}, (SELECT COUNT(*) FROM message m WHERE m.session_id = s.id) AS n_msgs FROM session s"
    out = []
    for r in c.execute(sql):
        d = {"id": r[0], "title": (r[1] if tem_titulo else "") or "",
             "directory": (r[2] if tem_dir else "") or "",
             "time_created": r[3] if tem_time else None,
             "n_msgs": r[-1]}
        out.append(d)
    out.sort(key=lambda x: -(x["n_msgs"] or 0))
    return out


def mensagens(c: sqlite3.Connection, sid: str) -> list[dict]:
    """Mensagens + partes (o texto esta na tabela part, tipo=text)."""
    mcols = {r[1] for r in c.execute("PRAGMA table_info(message)")}
    role = "role" if "role" in mcols else None
    mdata = "data" if "data" in mcols else None
    sql = "SELECT id" + (", role" if role else "") + (", data" if mdata else "") + " FROM message WHERE session_id=? ORDER BY rowid"
    out = []
    for r in c.execute(sql, (sid,)):
        mid = r[0]
        rl = r[1] if role else "?"
        texto = []
        try:
            for (pdata,) in c.execute("SELECT data FROM part WHERE message_id=? ORDER BY rowid", (mid,)):
                try:
                    pd = json.loads(pdata) if isinstance(pdata, str) else pdata
                except Exception:
                    continue
                if isinstance(pd, dict) and pd.get("type") == "text":
                    t = pd.get("text") or ""
                    if t.strip():
                        texto.append(t.strip())
        except Exception:
            pass
        if texto:
            out.append({"role": rl, "text": "\n\n".join(texto)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="extrai sessoes do opencode v1 para markdown")
    ap.add_argument("--db", default=str(Path.home() / ".local/share/opencode/opencode-stable.db"))
    ap.add_argument("--out", default="docs/sessions")
    ap.add_argument("--indice", default="docs/sessions/INDICE.md")
    ap.add_argument("--min-msgs", type=int, default=8, help="minimo de mensagens para ser considerada valiosa")
    ap.add_argument("--todas", action="store_true", help="extrai todas (mesmo as de titulo generico)")
    ap.add_argument("--max-mensagens", type=int, default=400, help="corta mensagens por sessao (o muito grande e' o diario)")
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"extract_sessions: DB ausente: {args.db}", file=__import__("sys").stderr)
        return 2
    c = abrir(args.db)
    ss = sessoes(c)
    if not ss:
        print("extract_sessions: nenhuma sessao no schema v1", file=__import__("sys").stderr)
        return 2

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    idx_rows = []
    extraidas = 0
    for s in ss:
        titulo = s["title"] or "(sem titulo)"
        valiosa = args.todas or (not GENERICO.match(titulo)) or (s["n_msgs"] or 0) >= args.min_msgs
        dt = ""
        if s.get("time_created"):
            try:
                dt = datetime.fromtimestamp(s["time_created"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            except Exception:
                dt = str(s["time_created"])
        idx_rows.append((s["id"], titulo, s["n_msgs"], dt, s["directory"]))
        if not valiosa:
            continue
        msgs = mensagens(c, s["id"])
        if not msgs:
            continue
        if len(msgs) > args.max_mensagens:
            msgs = msgs[:args.max_mensagens]
        nome = f"{s['id']}__{slug(titulo)}.md"
        caminho = outdir / nome
        with caminho.open("w", encoding="utf-8") as fh:
            fh.write(f"# {titulo}\n\n")
            fh.write(f"- **sessão:** `{s['id']}`\n")
            if dt:
                fh.write(f"- **quando:** {dt} (UTC)\n")
            fh.write(f"- **diretório:** `{s['directory']}`\n")
            fh.write(f"- **mensagens:** {s['n_msgs']} (exportadas: {len(msgs)})\n")
            fh.write(f"- **origem:** `{Path(args.db).name}` (opencode 1.18.34, schema v1)\n\n")
            fh.write("---\n\n")
            for m in msgs:
                quem = {"user": "👤 dono/agente", "assistant": "🤖 assistente"}.get(m["role"], f"· {m['role']}")
                fh.write(f"## {quem}\n\n{m['text']}\n\n---\n\n")
        extraidas += 1

    # o indice
    with Path(args.indice).open("w", encoding="utf-8") as fh:
        fh.write("# Índice das sessões do opencode 1.18.34 (DB antigo)\n\n")
        fh.write(f"- **origem:** `{Path(args.db).name}` ({Path(args.db).stat().st_size / 2**30:.1f} GB)\n")
        fh.write(f"- **sessões no total:** {len(ss)}\n")
        fh.write(f"- **exportadas em markdown:** {extraidas}\n")
        fh.write("- **como isso foi feito:** o opencode 2.2.6 tem `session export`/`import`, mas o\n")
        fh.write("  export não lê o schema v1 (ele lê `session_v2`); o 1.18.34 não tem export.\n")
        fh.write("  ⇒ o conteúdo foi extraído direto do sqlite (preserva o conhecimento e\n")
        fh.write("  fica pesquisável por git grep/RAG); o .db segue como arquivo-fonte.\n\n")
        fh.write("| sessão | título | msgs | quando | diretório |\n|---|---|---:|---|---|\n")
        for sid, titulo, n, dt, dr in idx_rows:
            t = (titulo or "").replace("|", "\\|")[:70]
            fh.write(f"| `{sid[:22]}` | {t} | {n} | {dt} | `{dr[:40]}` |\n")
    print(f"extract_sessions: {len(ss)} sessoes no DB | {extraidas} exportadas em {outdir} | indice: {args.indice}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
