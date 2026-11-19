"""Reconciliação do índice RAG — versões antigas e arquivos removidos.

Por que existe (medido 19/11): o point id do RAG é
`stable_id("doc", source_sha256, chunk_index)`, derivado do CONTEÚDO.
Reindexar um arquivo alterado grava ids novos e deixa os antigos lá:
`rag.py` tinha 7 versões (231 pontos) para 39 chunks atuais, e `memory.py`
81 pontos para 16. O retrieval não sabe qual versão é a vigente, então
código velho pode vencer o top-k.

Contrato:
    scan(store, collection, *, exists=..., sha_of=...) -> report
        Varre o índice em páginas (payload mínimo) e classifica cada ponto:
          - "missing": o path não existe mais no disco;
          - "stale":   existe, mas o sha do arquivo difere do ponto;
          - "no_identity": ponto sem `path`/`source_sha256` (schema antigo).
            NÃO é removível: a coleção `books` legítimamente não guarda
            `path` (payload book_id/chapter/text do indexador de áudio) —
            3.064 pontos em 19/11 seriam apagados por engano se contassem
            como lixo;
          - "current": sha do ponto == sha do arquivo.
        NÃO apaga nada. `report["by_reason"]` tem contagem e `ids` por classe.
    apply(store, report, *, manifest_dir) -> summary
        Grava um manifesto JSON ANTES de apagar (procedência/reversão) e
        apaga por id em lotes. Exige `report` de uma varredura dry-run.

Regra de dados (AGENTS.md §10): a varredura é somente leitura; a remoção
só roda com `--apply` explícito e o manifesto fica no state dir. Nenhum
filtro por substring: a classificação é por sha do arquivo real.

Uso:
    jarvis rag-prune --collection code            # dry-run
    jarvis rag-prune --collection code --apply    # grava manifesto e apaga
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

REASON_CURRENT = "current"
REASON_STALE = "stale"
REASON_MISSING = "missing"
REASON_NO_IDENTITY = "no_identity"


def _file_sha(path: str) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def scan(
    store: Any,
    collection: str,
    *,
    sha_of: Callable[[str], str | None] = _file_sha,
    page: int = 1024,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Classifica os pontos da coleção contra o disco. Não apaga nada."""
    points = store.scroll_all(
        collection,
        payload_keys=["path", "source_sha256", "chunk_index"],
        page=page,
        max_pages=max_pages,
    )
    current_sha: dict[str, str | None] = {}
    by_reason: dict[str, int] = {
        REASON_CURRENT: 0, REASON_STALE: 0,
        REASON_MISSING: 0, REASON_NO_IDENTITY: 0,
    }
    ids: dict[str, list[int]] = {REASON_STALE: [], REASON_MISSING: []}
    per_path: dict[str, dict[str, int]] = {}
    for p in points:
        pl = p.get("payload", {}) or {}
        path = str(pl.get("path") or "")
        sha = str(pl.get("source_sha256") or "")
        pid = p.get("id")
        if not path or not sha:
            by_reason[REASON_NO_IDENTITY] += 1
            continue
        if path not in current_sha:
            current_sha[path] = sha_of(path)
        disk = current_sha[path]
        if disk is None:
            reason = REASON_MISSING
        elif disk != sha:
            reason = REASON_STALE
        else:
            reason = REASON_CURRENT
        by_reason[reason] += 1
        entry = per_path.setdefault(path, {})
        entry[reason] = entry.get(reason, 0) + 1
        if reason != REASON_CURRENT and pid is not None:
            ids[reason].append(pid)
    stale_paths = sorted(
        ({"path": path, **counts} for path, counts in per_path.items()
         if counts.get(REASON_STALE) or counts.get(REASON_MISSING)),
        key=lambda e: -(e.get(REASON_STALE, 0) + e.get(REASON_MISSING, 0)),
    )
    return {
        "collection": collection,
        "total_points": len(points),
        "unique_paths": len(per_path),
        "by_reason": by_reason,
        "removable": sum(len(v) for v in ids.values()),
        "ids": ids,
        "paths": stale_paths,
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def apply(
    store: Any,
    report: dict[str, Any],
    *,
    manifest_dir: str | Path | None = None,
    batch: int = 256,
) -> dict[str, Any]:
    """Grava o manifesto e apaga os ids classificados como removíveis."""
    collection = report["collection"]
    flat: list[int] = []
    for reason in (REASON_STALE, REASON_MISSING):
        flat.extend(report["ids"].get(reason, []))
    if not flat:
        return {"deleted": 0, "manifest": "", "collection": collection}
    manifest = ""
    if manifest_dir:
        out_dir = Path(manifest_dir).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%S")
        note = out_dir / f"rag-prune-{collection}-{stamp}.json"
        note.write_text(json.dumps({
            "collection": collection,
            "by_reason": report["by_reason"],
            "paths": report["paths"][:500],
            "ids": flat,
            "created_at": report.get("scanned_at", ""),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest = str(note)
    deleted = 0
    for i in range(0, len(flat), batch):
        store.delete_points(collection, flat[i:i + batch])
        deleted += len(flat[i:i + batch])
    return {"deleted": deleted, "manifest": manifest, "collection": collection}
