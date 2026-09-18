#!/usr/bin/env python3
"""Inventário do corpus de conhecimento (§3/§22 da missão knowledge-substrate).

Gera $JARVIS_STATE_DIR/sanitize/inventory/corpus.jsonl — manifesto rastreável
do que existe fisicamente: path, hashes, timestamps, repositório git e
proveniência. É a ponte determinística filesystem → sanitização → ingestão →
Qdrant. Idempotente e ordenado (mesma árvore ⇒ mesmo arquivo).

Uso:
  nix develop -c python3 scripts/corpus_inventory.py            # gera/atualiza
  nix develop -c python3 scripts/corpus_inventory.py --check    # só valida (exit 1 se divergiu)

Fontes inventariadas (raízes fixas, com orçamento anti-DoS):
  ~/Books            corpus de conhecimento (binários + notas; inclui versions/)
  ~/Books-md         camada DERIVADA (conversões .md; binários fora)
  ~/vaults/projects  vault Obsidian versionado (até 3 níveis)
  ~/projects/nixos-ai docs/ + docs de módulos (repo vivo)
  ~/projects/plans   planos ativos
  ~/archives         snapshots arquivados (nível 2)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
STATE_DIR = Path(os.environ.get("JARVIS_STATE_DIR", HOME / ".local/state/jarvis"))
OUT = STATE_DIR / "sanitize/inventory/corpus.jsonl"

MAX_FILES = 5000
MAX_BYTES_PER_FILE = 2 * 1024 * 1024 * 1024  # §19: bounded; não hashamos além disso

# (raiz, profundidade, sufixos permitidos ou None=tudo, source_type)
# ORDEM IMPORTA: raízes mais específicas ANTES de Books (que as contém).
ROOTS: list[tuple[Path, int, tuple[str, ...] | None, str]] = [
    (HOME / "Books/harness", 1, (".md",), "harness_digests"),
    (HOME / "Books/memory", 1, (".md",), "memory_backup"),
    (HOME / "Books/session-2026-09-18", 1, (".md",), "session_backup"),
    (HOME / "Books/versions", 2, None, "books_versions"),
    (HOME / "Books-md", 1, (".md",), "books_derived_md"),
    (HOME / "vaults/projects", 3, (".md", ".json", ".canvas"), "obsidian_vault"),
    (HOME / "projects/nixos-ai/docs", 6, (".md",), "project_docs"),
    (HOME / "projects/nixos-ai/modules/ai/jarvis/docs", 3, (".md",), "module_docs"),
    (HOME / "projects/plans", 2, (".md",), "plans"),
    (HOME / "archives", 2, (".md",), "archives_snapshot"),
    (HOME / "Books", 6, None, "books_corpus"),
]


def _git(repo_dir: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=repo_dir,
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _git_info(path: Path) -> dict:
    """Provenância git do arquivo: repo, HEAD, tracked, último commit."""
    for parent in [path.parent, *path.parents]:
        if (parent / ".git").exists():
            rel = path.relative_to(parent).as_posix()
            tracked = _git(parent, "ls-files", "--", rel)
            return {
                "git_repository": str(parent),
                "git_head": _git(parent, "rev-parse", "--short", "HEAD"),
                "git_tracked": bool(tracked),
                "last_modified_commit": _git(parent, "log", "-1", "--format=%h", "--", rel),
            }
    return {"git_repository": "", "git_head": "", "git_tracked": False,
            "last_modified_commit": ""}


def classify_source_type(path: Path) -> str:
    """Classificação determinística por conteúdo/estrutura, não por extensão."""
    for root, _, _, source_type in ROOTS:
        try:
            path.relative_to(root)
            return source_type
        except ValueError:
            continue
    return "unknown"


def inventory_entry(path: Path) -> dict | None:
    try:
        st = path.stat()
    except OSError:
        return None
    if st.st_size > MAX_BYTES_PER_FILE:
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    entry = {
        "path": str(path),
        "filename": path.name,
        "ext": path.suffix,
        "size": st.st_size,
        "mtime": st.st_mtime,
        "sha256": h.hexdigest(),
        "source_type": classify_source_type(path),
        "git_tracked": False,
    }
    entry.update(_git_info(path))
    return entry


def collect() -> list[dict]:
    seen: set[Path] = set()
    entries: list[dict] = []
    for root, depth, suffixes, _ in ROOTS:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root)
            if len(rel.parts) > depth:
                continue
            if not p.is_file() or p in seen or ".git" in p.parts:
                continue
            if suffixes is not None and p.suffix not in suffixes:
                continue
            seen.add(p)
            e = inventory_entry(p)
            if e:
                entries.append(e)
            if len(entries) >= MAX_FILES:
                print(f"AVISO: teto MAX_FILES={MAX_FILES} atingido", file=sys.stderr)
                return sorted(entries, key=lambda x: x["path"])
    return sorted(entries, key=lambda x: x["path"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="não escreve; exit 1 se o inventário divergiu do disco")
    args = ap.parse_args()

    t0 = time.time()
    entries = collect()
    blob = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)

    if args.check:
        if not OUT.exists():
            print(f"FALHA: {OUT} ausente")
            return 1
        same = OUT.read_text() == blob
        print(f"{'OK' if same else 'DIVERGIU'}: {len(entries)} entradas")
        return 0 if same else 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".jsonl.tmp")
    tmp.write_text(blob)
    tmp.replace(OUT)
    print(f"corpus.jsonl: {len(entries)} entradas ({time.time()-t0:.1f}s) → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
