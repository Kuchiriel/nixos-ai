#!/usr/bin/env python3
"""
Consolidate opencode session summaries into durable JARVIS episodic memory.

Reads structured session summaries from Qdrant collection `sessions` (indexed
from ~/.local/share/opencode/opencode.db by index_opencode_sessions.py) and
stores one compact, deterministic FACT memory per session in the `memories`
collection. This makes past session outcomes/contexts retrievable via
`jarvis_recall`/`jarvis_rehydrate` (memories) in addition to
`jarvis_session_resume`/`jarvis_rag_search(collection="sessions")`.

Design (safe, local-first, idempotent-by-state):
  - Source of truth stays the opencode DB + `sessions` summaries (no raw transcript).
  - Deterministic, heuristic distillation only (no LLM), so behavior is testable
    and does not invent facts. Each memory cites `session_id`/`directory`.
  - Incremental state file tracks last consolidated `time_updated` per session_id;
    reruns only process new/updated sessions. `--force` reprocesses all.
  - Secret-safe posture: only summary payload text/metadata from `sessions` is used
    (already a structured summary, not raw transcript). No env/credential values
    are read or emitted beyond what summaries contain.

Usage:
  nix develop -c python3 scripts/consolidate_sessions_memory.py --dry-run
  nix develop -c python3 scripts/consolidate_sessions_memory.py --limit 50
  nix develop -c python3 scripts/consolidate_sessions_memory.py --incremental
  nix develop -c python3 scripts/consolidate_sessions_memory.py --force
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules/ai/jarvis/src"))

from jarvis.core.config import Config  # noqa: E402
from jarvis.core.memory import EpisodicMemory  # noqa: E402
from jarvis.providers.vector_store import QdrantStore  # noqa: E402

_cfg = Config()
SESS_COLLECTION = (
    os.environ.get("JARVIS_QDRANT_COLLECTION_SESSIONS", "") or _cfg.qdrant_collection_sessions
)


def _short(text: str, limit: int) -> str:
    t = " ".join((text or "").split())
    if len(t) <= limit:
        return t
    return t[: max(0, limit - 1)].rstrip() + "…"


def scroll_sessions(store: QdrantStore, collection: str, batch: int = 128) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = None
    while True:
        body: dict[str, Any] = {"limit": batch, "with_payload": True, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        try:
            res = store._request("POST", f"/collections/{collection}/points/scroll", json=body)
        except Exception:
            break
        result = res.get("result", {}) or {}
        points = result.get("points", []) or []
        if not points:
            break
        out.extend(points)
        offset = result.get("next_page_offset")
        if offset is None:
            break
    return out


def extract_section(text: str, header: str, max_chars: int = 320) -> str:
    # Grab lines after a header like "## Objetivo" until next "## " header.
    if not text:
        return ""
    marker = f"## {header}"
    i = text.find(marker)
    if i < 0:
        return ""
    j = text.find("\n", i)
    if j < 0:
        return ""
    rest = text[j + 1 :]
    k = rest.find("\n## ")
    block = rest if k < 0 else rest[:k]
    # take first meaningful bullet/line
    lines = [ln.strip("- ").strip() for ln in block.splitlines() if ln.strip()]
    if not lines:
        return ""
    # prefer the first non-generic line
    for ln in lines:
        if ln and ln not in {"(sem texto)", "-"}:
            return _short(ln, max_chars)
    return _short(lines[0], max_chars)


def build_fact(point: dict[str, Any]) -> tuple[str, dict[str, Any], str, int] | None:
    pl = point.get("payload") or {}
    sid = str(pl.get("session_id") or "")
    if not sid:
        return None
    title = str(pl.get("title") or "(sem título)")
    directory = str(pl.get("directory") or "")
    project_id = str(pl.get("project_id") or "")
    tu = int(pl.get("time_updated") or 0)
    tc = int(pl.get("time_created") or 0)
    nmsg = pl.get("message_count")
    text = str(pl.get("text") or "")

    objetivo = extract_section(text, "Objetivo / pedidos iniciais", 220)
    recente = extract_section(text, "Estado recente / pedidos recentes", 260)
    arquivos = extract_section(text, "Arquivos / caminhos citados", 220)

    parts = [f"PAST SESSION [{sid}] \"{_short(title, 80)}\""]
    if directory:
        parts.append(f"dir={directory}")
    if project_id:
        parts.append(f"project={project_id}")
    if tc or tu:
        parts.append(f"time={tc}->{tu}")
    if nmsg is not None:
        parts.append(f"messages={nmsg}")
    head = " | ".join(parts)

    body_bits = []
    if objetivo:
        body_bits.append(f"Goal: {objetivo}")
    if recente:
        body_bits.append(f"Recent: {recente}")
    if arquivos:
        body_bits.append(f"Paths: {arquivos}")
    if not body_bits:
        # fallback: compact slice of the summary text
        body_bits.append(_short(text, 360))

    fact = _short(head + "\n" + " ".join(body_bits), 900)
    meta = {
        "source": "session_consolidation",
        "session_id": sid,
        "directory": directory,
        "project_id": project_id,
        "time_updated": tu,
        "time_created": tc,
        "kind_origin": "session_summary",
    }
    return fact, meta, sid, tu


def load_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"sessions": {}}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="max sessions to process (0 = all)")
    ap.add_argument("--force", action="store_true", help="reprocess sessions even if unchanged")
    ap.add_argument("--incremental", action="store_true", help="process only sessions newer than state (default behavior)")
    ap.add_argument("--state-file", default="", help="state file (default: <state_dir>/sessions-consolidation-state.json)")
    ap.add_argument("--collection", default=SESS_COLLECTION)
    args = ap.parse_args()

    cfg = _cfg
    store = QdrantStore(cfg)
    if not store.is_available():
        print("Qdrant indisponível (verifique :6333)", file=sys.stderr)
        return 2
    try:
        info = store.info(args.collection)
        if not (isinstance(info, dict) and info.get("result")):
            raise RuntimeError("missing")
    except Exception:
        print(f"Coleção '{args.collection}' não encontrada. Rode index_opencode_sessions.py primeiro.", file=sys.stderr)
        return 2

    state_path = Path(args.state_file) if args.state_file else (cfg.ensure_state_dir() / "sessions-consolidation-state.json")
    state = load_state(state_path)
    seen: dict[str, int] = dict(state.get("sessions") or {})

    points = scroll_sessions(store, args.collection)
    # newest first for reporting; processing order doesn't matter
    points.sort(key=lambda p: int(((p.get("payload") or {}).get("time_updated") or 0)), reverse=True)

    em = EpisodicMemory(cfg)
    if not args.dry_run:
        em.ensure()

    candidates = 0
    stored = 0
    skipped = 0
    errors = 0
    processed = 0

    for p in points:
        if args.limit and processed >= args.limit:
            break
        built = build_fact(p)
        if not built:
            continue
        fact, meta, sid, tu = built
        prev_tu = int(seen.get(sid) or 0)
        if not args.force and tu and prev_tu and tu <= prev_tu:
            skipped += 1
            continue
        candidates += 1
        processed += 1
        if args.dry_run:
            # show a compact preview for first few
            if candidates <= 3:
                print(f"DRY {sid} tu={tu} :: {_short(fact, 180)}")
            continue
        try:
            mid = em.remember_fact(fact, **meta)
            if mid is None:
                errors += 1
                print(f"WARN: embed/store falhou para {sid}", file=sys.stderr)
                continue
            stored += 1
            if tu:
                seen[sid] = tu
            elif sid not in seen:
                seen[sid] = int(time.time() * 1000)
        except Exception as e:
            errors += 1
            print(f"ERR {sid}: {e}", file=sys.stderr)

    if not args.dry_run and (stored > 0 or args.force):
        state["sessions"] = seen
        state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_state(state_path, state)

    mode = "dry-run" if args.dry_run else "apply"
    print(
        f"[sessions->memories:{mode}] scanned={len(points)} candidates={candidates} "
        f"stored={stored} skipped={skipped} errors={errors} state={state_path}"
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
