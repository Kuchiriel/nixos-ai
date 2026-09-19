#!/usr/bin/env python3
"""Reindexa o code_index (coleção canônica) a partir do código vivo.

Reprodutibilidade: a ingestão anterior de code_index foi um heredoc one-off;
este runner versiona o processo. Idempotente — IDs derivam de conteúdo
(vector_store.stable_id), re-executar só sobrescreve os mesmos pontos.

Uso:
    nix develop -c python3 scripts/reindex_code.py            # indexa
    nix develop -c python3 scripts/reindex_code.py --dry-run  # só descobre

Schema da coleção: SEMPRE via knowledge_schema.ensure_collection (dense+sparse
+ payload indexes canônicos) — nunca via QdrantStore.ensure_collection bare.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules" / "ai" / "jarvis" / "src"))

from jarvis.core import knowledge_schema  # noqa: E402
from jarvis.core.config import Config  # noqa: E402
from jarvis.core.rag import HybridIndexer  # noqa: E402
from jarvis.providers.vector_store import QdrantStore  # noqa: E402

# Raízes de descoberta (relativas ao repo) e extensões de código elegíveis.
# .md de docs/ entram (curadoria faz parte do self-knowledge); caches e
# artefatos de build ficam fora.
ROOTS = ["modules/ai", "scripts", "docs"]
EXTENSIONS = {".py", ".md", ".toml", ".nix", ".sh", ".mmd", ".json"}
SKIP_DIRS = {
    "__pycache__", ".hypothesis", ".pytest_cache", "node_modules",
    ".git", "result", "frontend", ".venv", "logs",
}


def discover(repo: Path) -> list[Path]:
    files: list[Path] = []
    for root in ROOTS:
        base = repo / root
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in EXTENSIONS:
                continue
            if any(part in SKIP_DIRS for part in p.relative_to(repo).parts):
                continue
            files.append(p)
    return sorted(set(files))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = Config()
    store = QdrantStore(cfg)
    if not store.is_available():
        print("ERRO: Qdrant indisponível", file=sys.stderr)
        return 1

    # Schema canônico ANTES da ingestão (indexes p/ filtros, §14 da missão).
    info = knowledge_schema.ensure_collection(store, "code_index")
    print(f"schema ok: code_index ({info.get('points_count', 0)} pts pré-existentes)")

    files = discover(REPO)
    print(f"{len(files)} arquivos elegíveis")
    if args.dry_run:
        for p in files:
            print(f"  {p.relative_to(REPO)}")
        return 0

    indexer = HybridIndexer(cfg)
    indexed = skipped = errors = 0
    t0 = time.time()
    manifest = []
    for i, p in enumerate(files, 1):
        try:
            res = indexer.index_file(str(p))
        except Exception as exc:  # erro visível, não engolido
            print(f"  ERRO {p.relative_to(REPO)}: {exc}", file=sys.stderr)
            errors += 1
            continue
        if res:
            indexed += 1
            manifest.append({"path": str(p.relative_to(REPO)), "chunks": res.get("chunks", "?")})
        else:
            skipped += 1
        if i % 25 == 0 or i == len(files):
            print(f"{i}/{len(files)} | {indexed} idx | {skipped} skip | {errors} err | {time.time()-t0:.0f}s")

    out = REPO / "logs" / "code_index-reindex.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(
        {"total": len(files), "indexed": indexed, "skipped": skipped,
         "errors": errors, "files": manifest}, ensure_ascii=False, indent=1))
    print(f"feito: {indexed} indexados, {skipped} skip, {errors} erros → {out.name}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
