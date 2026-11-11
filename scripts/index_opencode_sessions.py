#!/usr/bin/env python3
"""
Indexa sessões do opencode.db no Qdrant (coleção dedicada `sessions`).

Objetivo: tornar "o que aconteceu em cada sessão" recuperável por RAG/MCP
(qualquer agente/harness) sem indexar transcript bruto completo.

- Fonte: ~/.local/share/opencode/opencode.db (somente leitura)
- Coleção: sessions (híbrida densa+sparse, schema canônico)
- Unidade: 1 documento-resumo por sessão (idempotente por session_id)
- Conteúdo: metadados + objetivo inicial + marcos recentes (user/assistant)
  + caminhos/arquivos citados (heurístico). Sem segredos por design aqui
  (não há filtro de segredo perfeito; evitar indexar valores sensíveis).

Uso:
  nix develop -c python3 scripts/index_opencode_sessions.py --dry-run
  nix develop -c python3 scripts/index_opencode_sessions.py
  nix develop -c python3 scripts/index_opencode_sessions.py --limit 50
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules/ai/jarvis/src"))

from jarvis.core import knowledge_schema  # noqa: E402
from jarvis.core.config import Config  # noqa: E402
from jarvis.providers.llm import LLMClient  # noqa: E402
from jarvis.providers.vector_store import QdrantStore, stable_id  # noqa: E402
from jarvis.core.rag import sparse_terms, sparse_vector  # noqa: E402

_cfg = Config()
COLLECTION = os.environ.get("JARVIS_QDRANT_COLLECTION_SESSIONS", "") or _cfg.qdrant_collection_sessions
DB_DEFAULT = Path.home() / ".local/share/opencode/opencode.db"

PATH_RE = re.compile(r"(?:(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+\.(?:py|nix|md|sh|ts|tsx|js|json|toml|yaml|yml|rs|go|lua|sql|mjs))")


def _ts(v: Any) -> str:
    try:
        if v is None:
            return ""
        # opencode stores ms epoch ints in some schemas
        iv = int(v)
        if iv > 10_000_000_000:  # ms
            iv = iv // 1000
        return datetime.fromtimestamp(iv, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    except Exception:
        return str(v) if v is not None else ""


def _short(text: str, limit: int) -> str:
    t = " ".join((text or "").split())
    if len(t) <= limit:
        return t
    return t[: max(0, limit - 1)].rstrip() + "…"


def open_db(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def list_sessions(con: sqlite3.Connection) -> list[dict[str, Any]]:
    # Prefer session_v2 titles/times when present; fall back to session.
    # Many installs have same ids in both; union by id.
    cur = con.cursor()
    sessions: dict[str, dict[str, Any]] = {}

    def ingest(table: str) -> None:
        try:
            cols = {r[1] for r in cur.execute(f"PRAGMA table_info({table})")}
        except Exception:
            return
        sel = ["id"]
        for c in ("title", "directory", "project_id", "time_created", "time_updated", "time_archived"):
            sel.append(c if c in cols else f"NULL AS {c}")
        for r in cur.execute(f"SELECT {', '.join(sel)} FROM {table}"):
            sid = r[0]
            row = {
                "id": sid,
                "title": r[1] or "",
                "directory": r[2] or "",
                "project_id": r[3] or "",
                "time_created": r[4],
                "time_updated": r[5],
                "time_archived": r[6],
            }
            prev = sessions.get(sid)
            # keep the one with newer updated time / non-empty title
            if not prev:
                sessions[sid] = row
            else:
                tu_new = int(row.get("time_updated") or 0)
                tu_old = int(prev.get("time_updated") or 0)
                if tu_new >= tu_old:
                    # merge, preferring non-empty
                    merged = dict(prev)
                    merged.update({k: v for k, v in row.items() if v not in (None, "")})
                    if not merged.get("title") and prev.get("title"):
                        merged["title"] = prev["title"]
                    sessions[sid] = merged

    ingest("session")
    ingest("session_v2")
    return list(sessions.values())


def count_messages(con: sqlite3.Connection, sid: str) -> int:
    cur = con.cursor()
    try:
        cur.execute("SELECT count(*) FROM message WHERE session_id=?", (sid,))
        return int(cur.fetchone()[0] or 0)
    except Exception:
        return 0


def extract_texts(con: sqlite3.Connection, sid: str, max_msgs: int = 60) -> list[dict[str, str]]:
    """Return ordered (role, text) from message/part, preferring text parts."""
    cur = con.cursor()
    try:
        mcols = {r[1] for r in cur.execute("PRAGMA table_info(message)")}
    except Exception:
        return []
    order = "rowid"
    q = "SELECT id, data FROM message WHERE session_id=? ORDER BY rowid"
    if max_msgs:
        # take from start and end by fetching all ids lightly is expensive; fetch ordered and sample
        pass
    rows = cur.execute(q, (sid,)).fetchall()
    if not rows:
        return []
    # sample: first 20, last 20, middle 20 spread (by index) to cap cost
    idxs = list(range(len(rows)))
    if len(rows) > max_msgs:
        head = idxs[:20]
        tail = idxs[-20:]
        mid_n = max(0, max_msgs - len(head) - len(tail))
        if mid_n > 0:
            step = max(1, (len(idxs) - 40) // mid_n)
            mid = idxs[20:len(idxs)-20:step][:mid_n]
        else:
            mid = []
        pick = sorted(set(head + mid + tail))
        rows = [rows[i] for i in pick]
    out = []
    for mid, data in rows:
        role = "?"
        if data:
            try:
                md = json.loads(data) if isinstance(data, str) else data
                if isinstance(md, dict):
                    role = md.get("role") or md.get("type") or "?"
            except Exception:
                pass
        texts = []
        try:
            for (pdata,) in cur.execute("SELECT data FROM part WHERE message_id=? ORDER BY rowid", (mid,)):
                try:
                    pd = json.loads(pdata) if isinstance(pdata, str) else pdata
                except Exception:
                    continue
                if not isinstance(pd, dict):
                    continue
                ptype = pd.get("type")
                if ptype == "text" and (pd.get("text") or "").strip():
                    texts.append(pd["text"].strip())
                elif ptype in ("tool", "tool-invocation", "tool-result"):
                    # keep a tiny marker/name, not full payload
                    name = pd.get("toolName") or pd.get("name") or pd.get("tool") or ""
                    if name:
                        texts.append(f"[tool:{name}]")
        except Exception:
            pass
        if texts:
            out.append({"role": str(role), "text": "\n".join(texts)})
    return out


def mentioned_paths(texts: list[dict[str, str]], limit: int = 20) -> list[str]:
    c: Counter[str] = Counter()
    for t in texts:
        for m in PATH_RE.findall(t.get("text") or ""):
            # filter obvious noise
            if m.startswith("http") or len(m) < 4:
                continue
            c[m] += 1
    return [p for p, _ in c.most_common(limit)]


def build_doc(meta: dict[str, Any], n_msgs: int, texts: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
    title = meta.get("title") or "(sem título)"
    directory = meta.get("directory") or ""
    created = _ts(meta.get("time_created"))
    updated = _ts(meta.get("time_updated"))
    archived = bool(meta.get("time_archived"))

    user_texts = [t["text"] for t in texts if t.get("role") == "user" and (t.get("text") or "").strip()]
    asst_texts = [t["text"] for t in texts if t.get("role") == "assistant" and (t.get("text") or "").strip()]

    first_user = _short("\n---\n".join(user_texts[:2]), 800) if user_texts else ""
    last_user = _short("\n---\n".join(user_texts[-2:]), 600) if len(user_texts) > 2 else ""
    last_asst = _short("\n---\n".join(asst_texts[-2:]), 700) if asst_texts else ""
    paths = mentioned_paths(texts)

    lines = [
        f"[SESSION] {title}",
        f"session_id: {meta.get('id')}",
        f"directory: {directory}",
        f"created: {created} | updated: {updated} | archived: {archived}",
        f"messages: {n_msgs}",
    ]
    if first_user:
        lines += ["", "Objetivo/pedidos iniciais (user):", first_user]
    if last_user:
        lines += ["", "Pedidos recentes (user):", last_user]
    if last_asst:
        lines += ["", "Estado/resposta recente (assistant):", last_asst]
    if paths:
        lines += ["", "Arquivos/caminhos citados:", ", ".join(paths)]
    doc = "\n".join(lines).strip()

    payload = {
        "source": "opencode_session",
        "session_id": meta.get("id"),
        "title": title,
        "directory": directory,
        "project_id": meta.get("project_id") or "",
        "time_created": meta.get("time_created"),
        "time_updated": meta.get("time_updated"),
        "created_iso": created,
        "updated_iso": updated,
        "archived": archived,
        "msg_count": n_msgs,
        "kind": "session_summary",
        "paths": paths[:20],
    }
    return doc, payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_DEFAULT))
    ap.add_argument("--collection", default=COLLECTION)
    ap.add_argument("--limit", type=int, default=0, help="indexa no máximo N sessões (0=todas)")
    ap.add_argument("--min-msgs", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--incremental", action="store_true",
                    help="indexa só sessões novas/atualizadas desde o último run (estado em JARVIS_STATE_DIR)")
    ap.add_argument("--state-file", default="", help="arquivo de estado incremental (default: <state_dir>/sessions-index-state.json)")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"ERRO: db não encontrado: {db}", file=sys.stderr)
        return 1

    cfg = Config()
    state_path = Path(args.state_file) if args.state_file else (cfg.ensure_state_dir() / "sessions-index-state.json")
    last_indexed_updated = 0
    state: dict[str, Any] = {}
    if args.incremental and state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            last_indexed_updated = int(state.get("last_time_updated") or 0)
        except Exception:
            last_indexed_updated = 0
            state = {}

    con = open_db(db)
    sessions = list_sessions(con)
    # enrich with msg count and filter
    enriched = []
    for s in sessions:
        n = count_messages(con, s["id"])
        if n < args.min_msgs:
            continue
        s["n_msgs"] = n
        if args.incremental and int(s.get("time_updated") or 0) <= last_indexed_updated:
            continue
        enriched.append(s)
    # newest updated first for deterministic --limit usefulness
    enriched.sort(key=lambda x: int(x.get("time_updated") or 0), reverse=True)
    if args.limit and args.limit > 0:
        enriched = enriched[: args.limit]

    mode = "incremental" if args.incremental else "full"
    extra = f", last_time_updated={last_indexed_updated}" if args.incremental else ""
    print(f"sessões candidatas ({mode}{extra}): {len(enriched)} (db={db}, collection={args.collection})")
    if args.dry_run:
        for s in enriched[:10]:
            print(f"  - {s['id']} msgs={s.get('n_msgs')} updated={_ts(s.get('time_updated'))} :: {_short(s.get('title',''),80)}")
        if len(enriched) > 10:
            print(f"  ... (+{len(enriched)-10})")
        con.close()
        return 0

    cfg = Config()
    store = QdrantStore(cfg)
    if not store.is_available():
        print("ERRO: Qdrant indisponível", file=sys.stderr)
        return 1

    def ensure_sessions_collection(name: str) -> dict[str, Any]:
        # schema híbrido compatível com o restante do RAG (dense + bm25 sparse)
        dim = getattr(cfg, "embed_dim", 768)
        try:
            info = store.info(name)
            if isinstance(info, dict) and info.get("result", {}).get("status") in ("green", "yellow", "red"):
                # garante índices (idempotente)
                for field, stype in (
                    ("session_id", "keyword"),
                    ("directory", "keyword"),
                    ("project_id", "keyword"),
                    ("source", "keyword"),
                    ("kind", "keyword"),
                    ("archived", "bool"),
                    ("msg_count", "integer"),
                    ("time_updated", "integer"),
                ):
                    try:
                        store._request("PUT", f"/collections/{name}/index",
                                       json={"field_name": field, "field_schema": stype})
                    except Exception:
                        pass
                return info
        except Exception:
            pass
        # cria coleção híbrida
        try:
            store._request("PUT", f"/collections/{name}", json={
                "vectors": {"dense": {"size": dim, "distance": "Cosine"}},
                "sparse_vectors": {"bm25": {"modifier": "idf"}},
            })
        except Exception:
            # fallback: ensure_collection padrão (pode não criar sparse igual, mas tenta)
            store.ensure_collection(name, dim=dim)
        for field, stype in (
            ("session_id", "keyword"),
            ("directory", "keyword"),
            ("project_id", "keyword"),
            ("source", "keyword"),
            ("kind", "keyword"),
            ("archived", "bool"),
            ("msg_count", "integer"),
            ("time_updated", "integer"),
        ):
            try:
                store._request("PUT", f"/collections/{name}/index",
                               json={"field_name": field, "field_schema": stype})
            except Exception:
                pass
        return store.info(name)

    if args.collection == COLLECTION or args.collection == "sessions":
        info = ensure_sessions_collection(args.collection)
    else:
        info = knowledge_schema.ensure_collection(store, args.collection)
    pts = 0
    try:
        pts = info.get("result", {}).get("points_count", 0) if isinstance(info, dict) else 0
    except Exception:
        pts = 0
    print(f"schema ok: {args.collection} (points pré-existentes: {pts})")

    llm = LLMClient(cfg)

    total = 0
    errors = 0
    max_ok_updated = int(last_indexed_updated or 0)
    batch_points: list[dict[str, Any]] = []
    t0 = time.time()

    def flush() -> None:
        nonlocal batch_points
        if not batch_points:
            return
        store.upsert(args.collection, batch_points)
        batch_points = []

    for i, meta in enumerate(enriched, 1):
        sid = meta["id"]
        try:
            n_msgs = int(meta.get("n_msgs") or 0)
            texts = extract_texts(con, sid)
            doc, payload = build_doc(meta, n_msgs, texts)
            vec = llm.embed(doc)
            if vec is None:
                print(f"  ERRO embed {sid}", file=sys.stderr)
                errors += 1
                continue
            pid = stable_id(f"session:{sid}")
            batch_points.append({
                "id": pid,
                "vector": {"dense": vec, "bm25": sparse_vector(sparse_terms(doc))},
                "payload": {**payload, "text": doc, "path": f"opencode-session://{sid}"},
            })
            total += 1
            try:
                tu = int(meta.get("time_updated") or 0)
                if tu > max_ok_updated:
                    max_ok_updated = tu
            except Exception:
                pass
            if len(batch_points) >= args.batch:
                flush()
        except Exception as exc:
            print(f"  ERRO {sid}: {exc}", file=sys.stderr)
            errors += 1
        if i % 25 == 0 or i == len(enriched):
            print(f"{i}/{len(enriched)} | {total} ok | {errors} err | {time.time()-t0:.0f}s")

    flush()
    con.close()
    if args.incremental or not state_path.exists():
        try:
            out_state = dict(state)
            out_state["last_time_updated"] = max_ok_updated
            out_state["collection"] = args.collection
            out_state["db"] = str(db)
            out_state["updated_at"] = datetime.now(timezone.utc).isoformat()
            out_state["last_run_indexed"] = total
            out_state["last_run_errors"] = errors
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(out_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"estado incremental salvo: {state_path} (last_time_updated={max_ok_updated})")
        except Exception as exc:
            print(f"AVISO: não foi possível salvar estado incremental: {exc}", file=sys.stderr)
    print(f"feito: {total} sessões indexadas em '{args.collection}', {errors} erros ({time.time()-t0:.0f}s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
