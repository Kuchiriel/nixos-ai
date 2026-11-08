#!/usr/bin/env python3
"""Corpus offline de sobrevivência (fase A) — extração e indexação.

Propósito: transformar as fontes já baixadas (catálogo N.O.M.A.D de remédios
CDC/NIH/FDA + ZIM Kiwix "Water Treatment") em markdown com proveniência e
indexar na coleção Qdrant `offline_survival`. As coleções de produção
(code_index, memories, books, vault) nunca são tocadas.

Uso:
    python3 data/offline/build_corpus.py extract \
        --nomad-dir /tmp/opencode/nomad-sample/nomad/collections \
        --zim /tmp/opencode/nomad-sample/zims/water_en.zim \
        --zimdump /nix/store/<...>-zim-tools-3.6.0/bin/zimdump \
        --out data/offline
    python3 data/offline/build_corpus.py index \
        --dir data/offline --collection offline_survival

Exemplo:
    python3 data/offline/build_corpus.py extract --out data/offline
    python3 data/offline/build_corpus.py index --dir data/offline

Requisitos: PyMuPDF (pymupdf) para o texto dos PDFs; `zimdump` (nixpkgs
#zim-tools) para extrair o ZIM. O texto do ZIM é público (Kiwix open-access,
autores diversos) — a licença de cada documento vai no front-matter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_NOMAD_DIR = "/tmp/opencode/nomad-sample/nomad/collections"
DEFAULT_ZIM = "/tmp/opencode/nomad-sample/zims/water_en.zim"

KIWIX_LIBRARY = "Water Treatment Library (Kiwix zimgit-water_en_2024-08)"
KIWIX_LIBRARY_URL = "https://browse.library.kiwix.org/content/zimgit-water_en_2024-08"

# Licenças por documento do ZIM: o que o próprio documento declara ou o que
# a autoria implica (obra do governo dos EUA = domínio público). Onde o
# documento não declara nada, o front-matter aponta o original.
WATER_LICENSES: dict[str, str] = {
    "Water (1).pdf": "Public domain (Michigan State University Extension)",
    "Water (2).pdf": "Public domain (Washington State Department of Health)",
    "Water (3).pdf": "Public domain (US Environmental Protection Agency)",
    "Water (4).pdf": "Public domain (US Geological Survey)",
    "Water (5).pdf": (
        "© SODIS, Antenna — reuse livre com citação da fonte "
        "(declaração de licença no próprio manual)"
    ),
    "Water (6).pdf": "Consultar o documento original (Kiwix open-access library)",
    "Water (7).pdf": "Consultar o documento original (Kiwix open-access library)",
}

_HEADING_RE = re.compile(r"^\d+(\.\d+)*\.?\s+\S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:80] or "doc"


def _front_matter(meta: dict[str, str]) -> str:
    """Front-matter YAML plano; valores em JSON (YAML válido e parseável)."""
    lines = ["---"]
    for key in ("id", "title", "source", "source_url", "license", "retrieved_at"):
        lines.append(f"{key}: {json.dumps(meta.get(key, ''), ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError("front-matter ausente")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise ValueError("front-matter não fechado")
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        key, sep, raw = line.partition(":")
        if not sep:
            continue
        meta[key.strip()] = json.loads(raw.strip())
    return meta, text[end + len("\n---\n"):]


# ---------------------------------------------------------------------------
# Extração — catálogo N.O.M.A.D
# ---------------------------------------------------------------------------

def _remedy_body(remedy: dict[str, Any]) -> str:
    parts = [f"# {remedy['name']}"]
    common = remedy.get("commonNames") or []
    if common:
        parts.append(f"**Também chamada:** {', '.join(common)}")
    conditions = remedy.get("conditions") or []
    if conditions:
        parts.append(f"**Condições:** {', '.join(conditions)}")
    for label, key in (("Uso", "uses"), ("Como usar", "how"),
                       ("Evidência", "evidence"), ("Cautelas", "cautions")):
        value = (remedy.get(key) or "").strip()
        if value:
            parts.append(f"## {label}\n\n{value}")
    return "\n\n".join(parts) + "\n"


def _extract_nomad(nomad_dir: Path, out_dir: Path, retrieved_at: str) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for fname, family in (("home_remedies.json", "home"), ("natural_remedies.json", "natural")):
        path = nomad_dir / fname
        if not path.is_file():
            print(f"[aviso] {path} ausente — pulando", file=sys.stderr)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        source = data.get("source", {})
        for remedy in data.get("remedies", []):
            doc_id = f"nomad:{family}:{remedy['slug']}"
            meta = {
                "id": doc_id,
                "title": remedy["name"],
                "source": source.get("name", "N.O.M.A.D collection"),
                "source_url": remedy.get("sourceUrl") or source.get("url", ""),
                "license": source.get("license", "Public domain (US government work)"),
                "retrieved_at": retrieved_at,
            }
            body = _remedy_body(remedy)
            fname_out = f"nomad-{family}-{_slug(remedy['slug'])}.md"
            (out_dir / fname_out).write_text(
                _front_matter(meta) + "\n" + body, encoding="utf-8")
            docs.append({**meta, "file": fname_out,
                         "bytes": len(body.encode("utf-8"))})
    return docs


# ---------------------------------------------------------------------------
# Extração — ZIM Kiwix (PDFs -> markdown)
# ---------------------------------------------------------------------------

def _is_heading(line: str) -> bool:
    if not line or len(line) > 90:
        return False
    if any(ch.isalpha() for ch in line) and line == line.upper():
        return True
    return bool(_HEADING_RE.match(line))


def _pdf_to_markdown(pdf_path: Path) -> tuple[str, int]:
    try:
        import pymupdf  # type: ignore
    except ImportError:  # pragma: no cover - alias antigo
        import fitz as pymupdf  # type: ignore
    doc = pymupdf.open(pdf_path)
    pages: list[str] = []
    for number, page in enumerate(doc, start=1):
        blocks = []
        for block in page.get_text("blocks"):
            lines = [ln.strip() for ln in str(block[4]).splitlines() if ln.strip()]
            if not lines:
                continue
            if _is_heading(lines[0]):
                blocks.append(f"### {lines[0]}")
                if len(lines) > 1:
                    blocks.append(" ".join(lines[1:]))
            else:
                blocks.append(" ".join(lines))
        if blocks:
            pages.append(f"## Page {number}\n\n" + "\n\n".join(blocks))
    return "\n\n".join(pages) + "\n", doc.page_count


def _field(raw: str, key: str) -> str:
    """Valor de um campo do database.js do ZIM ('ti', 'dsc', 'aut', ...)."""
    m = re.search(rf"'{key}': '(.*?)'(?=,\s*'|\]|\}}|$)", raw)
    return m.group(1) if m else ""


def _extract_zim(zim: Path, zimdump: str, out_dir: Path, retrieved_at: str) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="zimdump-") as tmp:
        work = Path(tmp)
        subprocess.run([zimdump, "dump", "--dir", str(work), str(zim)],
                       check=True, capture_output=True)
        database = (work / "database.js").read_text(encoding="utf-8")
        entries = re.findall(r"\{'_id'.*?\}", database)
        for raw in entries:
            title = _field(raw, "ti")
            author = _field(raw, "aut")
            description = _field(raw, "dsc")
            files = re.findall(r"'([^']+\.pdf)'", raw)
            if not files:
                continue
            pdf = work / "files" / files[0]
            if not pdf.is_file():
                print(f"[aviso] PDF ausente: {pdf}", file=sys.stderr)
                continue
            body, pages = _pdf_to_markdown(pdf)
            doc_id = f"kiwix:water_en:{_slug(title)}"
            meta = {
                "id": doc_id,
                "title": title,
                "source": f"{KIWIX_LIBRARY} — {author}",
                "source_url": KIWIX_LIBRARY_URL,
                "license": WATER_LICENSES.get(files[0],
                                              "Consultar o documento original"),
                "retrieved_at": retrieved_at,
            }
            head = f"# {title}\n\n**Autor:** {author}\n\n{description}\n\n**Páginas:** {pages}\n\n"
            fname_out = f"kiwix-water-{_slug(title)}.md"
            (out_dir / fname_out).write_text(
                _front_matter(meta) + "\n" + head + body, encoding="utf-8")
            docs.append({**meta, "file": fname_out, "pages": pages,
                         "bytes": len(body.encode("utf-8"))})
    return docs


# ---------------------------------------------------------------------------
# Indexação — coleção offline_survival
# ---------------------------------------------------------------------------

def index_corpus(corpus_dir: Path, collection: str, batch_size: int = 64) -> dict[str, Any]:
    from jarvis.core.config import Config
    from jarvis.core.doc_sanitize import SANITIZER_VERSION
    from jarvis.core.rag import sparse_terms, sparse_vector
    from jarvis.providers.embedding import CHUNK_CHARS, OVERLAP_CHARS, split_for_embedding
    from jarvis.providers.llm import LLMClient
    from jarvis.providers.vector_store import QdrantStore, stable_id

    cfg = Config()
    store = QdrantStore(cfg)
    llm = LLMClient(cfg)

    source_cfg = store.info(cfg.qdrant_collection_code)["result"]["config"]["params"]
    vectors = source_cfg.get("vectors", {})
    dense_cfg = vectors.get("dense") if isinstance(vectors, dict) else None
    if not dense_cfg:
        raise SystemExit(f"não achei o vetor dense em {cfg.qdrant_collection_code}")
    size = int(dense_cfg["size"])
    distance = str(dense_cfg.get("distance", "Cosine"))
    if distance != "Cosine":
        raise SystemExit(f"distância {distance} não suportada por ensure_collection")
    store.ensure_collection(collection, dim=size)

    ingested_at = _now_iso()
    files = sorted(p for p in corpus_dir.glob("*.md"))
    if not files:
        raise SystemExit(f"nenhum .md em {corpus_dir}")

    n_chunks = 0
    n_docs = 0
    pending: list[dict[str, Any]] = []
    t0 = time.monotonic()

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        store.upsert(collection, pending)
        pending = []

    for path in files:
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_front_matter(raw)
        doc_id = meta.get("id", path.stem)
        source_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        prefix = f"[SOURCE: {doc_id}] [TITLE: {meta.get('title', '')[:60]}]\n"
        body_limit = max(200, CHUNK_CHARS - len(prefix))
        chunks = split_for_embedding(body, body_limit, OVERLAP_CHARS)
        rich_list = [prefix + chunk for chunk in chunks]
        vectors_out: list[list[float]] = []
        for start in range(0, len(rich_list), batch_size):
            vectors_out.extend(llm.embed_batch(rich_list[start:start + batch_size]))
        rel_path = str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)
        for i, (rich, chunk) in enumerate(zip(rich_list, chunks)):
            dense = vectors_out[i] if i < len(vectors_out) else []
            if not dense:
                print(f"[aviso] sem embedding: {path.name} chunk {i}", file=sys.stderr)
                continue
            pending.append({
                "id": stable_id("offline", doc_id, str(i)),
                "vector": {
                    "dense": dense,
                    "bm25": sparse_vector(sparse_terms(rich)),
                },
                "payload": {
                    "path": rel_path,
                    "document_id": f"offline:{doc_id}:{i}",
                    "chunk_id": f"{source_sha[:16]}:{i}",
                    "chunk_index": i,
                    "filename": path.name,
                    "ext": ".md",
                    "content": chunk,
                    "source_id": doc_id,
                    "source_title": meta.get("title", ""),
                    "source": meta.get("source", ""),
                    "source_url": meta.get("source_url", ""),
                    "license": meta.get("license", ""),
                    "retrieved_at": meta.get("retrieved_at", ""),
                    "source_sha256": source_sha,
                    "content_hash": hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                    "sanitizer_version": SANITIZER_VERSION,
                    "ingested_at": ingested_at,
                    "embedding_model": cfg.embed_model,
                },
            })
            n_chunks += 1
        if len(pending) >= batch_size:
            flush()
        n_docs += 1
    flush()

    return {
        "collection": collection,
        "documents": n_docs,
        "chunks": n_chunks,
        "points": store.count(collection),
        "vector_size": size,
        "distance": distance,
        "seconds": round(time.monotonic() - t0, 2),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_extract = sub.add_parser("extract", help="extrai markdown + index.jsonl")
    p_extract.add_argument("--nomad-dir", default=DEFAULT_NOMAD_DIR)
    p_extract.add_argument("--zim", default=DEFAULT_ZIM)
    p_extract.add_argument("--zimdump", required=True,
                           help="binário zimdump (nixpkgs#zim-tools)")
    p_extract.add_argument("--out", default=str(REPO_ROOT / "data" / "offline"))

    p_index = sub.add_parser("index", help="indexa o corpus no Qdrant")
    p_index.add_argument("--dir", default=str(REPO_ROOT / "data" / "offline"))
    p_index.add_argument("--collection", default="offline_survival")
    p_index.add_argument("--batch-size", type=int, default=64)

    args = parser.parse_args(argv)

    if args.cmd == "extract":
        out_dir = Path(args.out).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        retrieved_at = _now_iso()
        docs = _extract_nomad(Path(args.nomad_dir), out_dir, retrieved_at)
        docs += _extract_zim(Path(args.zim), args.zimdump, out_dir, retrieved_at)
        index_path = out_dir / "index.jsonl"
        with index_path.open("w", encoding="utf-8") as fh:
            for doc in docs:
                fh.write(json.dumps(doc, ensure_ascii=False) + "\n")
        total = sum(d["bytes"] for d in docs)
        print(json.dumps({
            "documents": len(docs),
            "bytes": total,
            "mb": round(total / 1_048_576, 3),
            "index": str(index_path),
        }, ensure_ascii=False))
        return 0

    stats = index_corpus(Path(args.dir).expanduser(), args.collection, args.batch_size)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
