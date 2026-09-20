#!/usr/bin/env python3
"""Ingestão do corpus de livros/papers/digests na coleção books (§10–§11).

Fila por categorias derivadas do manifest (Books/PROVENANCE.md v2):
  1. livros com text-layer confirmado (fitz, audit 3ª passagem)
  2. digests harness (notas curadas .md em Books/harness/)
  3. papers arXiv + python-3.14-docs
LotM (romance, ~17M chars) FORA da fila — decisão do dono (P3).

Idempotente: index_book usa stable_id(source_sha, ch, i) — re-executar
sobrescreve em vez de duplicar. Progresso em logs/books-batch.jsonl.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/nixos/projects/nixos-ai/modules/ai")

BOOKS = "/home/nixos/Books"
HARNESS = "/home/nixos/Books/harness"

QUEUE: list[tuple[str, str, str]] = [
    # (nome, dir, categoria)
    ("630O-Caibalion", BOOKS, "book"),
    ("14.DavidWerner-WhereThereIsNoDoctor", BOOKS, "book"),
    ("The Ultimate Survival Medicine Guide - Emergency Preparedness for Any Disaster 2015", BOOKS, "book"),
    ("Village Technology Handbook", BOOKS, "book"),
    ("_OceanofPDF.com_Pocket_Ref_-_Thomas_J_Glover", BOOKS, "book"),
    ("_OceanofPDF.com_The_Knowledge__How_to_Rebuild_our_World_fr_-_Lewis_Dartnell", BOOKS, "book"),
    ("_OceanofPDF.com_Origins_-_Lewis_Dartnell", BOOKS, "book"),
    ("_OceanofPDF.com_Life_in_the_Universe_-_Lewis_Dartnell", BOOKS, "book"),
    ("_OceanofPDF.com_The_Backyard_Homestead_Guide_to_Raising_Farm_AnimalS_-_Gail_Damerow", BOOKS, "book"),
    ("Schumacher (1973) Small is Beautiful", BOOKS, "book"),
    ("en_dent_2024_fm", BOOKS, "book"),
    ("dokumen.pub_the-encyclopedia-of-country-living-50th-anniversary-edition-the-original-manual-for-living-off-the-land-amp-doing-it-yourself-original-retailnbsped-1632172895-978-1632172891", BOOKS, "book_epub"),
    ("python-3.14-docs", BOOKS, "docs_python"),
    # digests harness (curadoria própria — alto valor por chunk)
    ("00-INDEX", HARNESS, "harness_digest"),
    ("agentconn-claude-code-prompt-cut", HARNESS, "harness_digest"),
    ("arxiv-2601.11327-small-agents-collaborate", HARNESS, "harness_digest"),
    ("arxiv-2603.05399-judge-reliability", HARNESS, "harness_digest"),
    ("arxiv-2607.11197-two-planning-abilities", HARNESS, "harness_digest"),
    ("awesome-harness-foundations", HARNESS, "harness_digest"),
    ("bhatt-agentic-engineering-6-principles", HARNESS, "harness_digest"),
    ("bits-bytes-prompts-to-harnesses", HARNESS, "harness_digest"),
    ("caveman-proxy-skill", HARNESS, "harness_digest"),
    ("arxiv-2605.18747-code-as-agent-harness", HARNESS, "harness_digest"),
    ("arxiv-2607.02599-agentltl", HARNESS, "harness_digest"),
    ("arxiv-2605.12129-not-the-size", HARNESS, "harness_digest"),
    ("arxiv-2405.00218-constrained-secure-code", HARNESS, "harness_digest"),
    ("arxiv-2505.14172-strawberry", HARNESS, "harness_digest"),
    ("arxiv-2510.14365-char-perturb", HARNESS, "harness_digest"),
    ("arxiv-2606.08610-harbor-robot", HARNESS, "harness_digest"),
    ("nvidia-gcd-bash-small-models", HARNESS, "harness_digest"),
    ("codeagents-pseudocode-2507.03254", HARNESS, "harness_digest"),
    ("faros-harness-engineering-mit-2026", HARNESS, "harness_digest"),
    ("nickyeo-model-vs-harness-4-sdks", HARNESS, "harness_digest"),
    ("voice-faster-whisper-kokoro", HARNESS, "harness_digest"),
    # papers arXiv (PDFs com text-layer)
    ("arxiv-2507.03254-codeagents", BOOKS, "paper"),
    ("arxiv-2601.11327-small-agents-collaborate", BOOKS, "paper"),
    ("arxiv-2603.05399-judge-reliability", BOOKS, "paper"),
    ("arxiv-2605.23296-parallel-context-compaction", BOOKS, "paper"),
    ("arxiv-2606.11213-beyond-compaction-cwl", BOOKS, "paper"),
    ("arxiv-2606.24083-cavewoman", BOOKS, "paper"),
    ("arxiv-2607.11197-two-planning-abilities", BOOKS, "paper"),
    ("arxiv-2607.25066-arc-addressable-recall", BOOKS, "paper"),
    ("arxiv-gaia2-benchmark", BOOKS, "paper"),
    ("arxiv-nature-collab-ceiling", BOOKS, "paper"),
    ("arxiv-2605.18747-code-as-agent-harness", BOOKS, "paper"),
    ("arxiv-2607.02599-agentltl", BOOKS, "paper"),
    ("arxiv-2605.12129-not-the-size", BOOKS, "paper"),
    ("arxiv-2405.00218-constrained-secure-code", BOOKS, "paper"),
    ("arxiv-2505.14172-strawberry", BOOKS, "paper"),
    ("arxiv-2510.14365-char-perturb", BOOKS, "paper"),
    ("arxiv-2606.08610-harbor-robot", BOOKS, "paper"),
    ("arxiv-2511.22277-treecoder", BOOKS, "paper"),
]

LOG = Path("/home/nixos/Books/session-2026-09-18/logs/books-batch.jsonl")


def main() -> int:
    from jarvis.core.audiobook import index_book

    LOG.parent.mkdir(parents=True, exist_ok=True)
    done_names = set()
    if LOG.exists():
        for line in LOG.read_text().splitlines():
            try:
                r = json.loads(line)
                if r.get("ok"):
                    done_names.add(r["name"])
            except Exception:
                pass

    for name, root, cat in QUEUE:
        if name in done_names:
            print(f"SKIP (já ok): {name}", flush=True)
            continue
        t0 = time.time()
        try:
            r = index_book(name, root)
        except Exception as e:
            r = {"ok": False, "error": str(e)[:200]}
        rec = {"name": name, "cat": cat, "seconds": round(time.time() - t0, 1), **r}
        with LOG.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{cat}] {name[:50]}: {rec.get('chunks', rec.get('error', '?'))} "
              f"({rec['seconds']}s)", flush=True)
    print("QUEUE DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
