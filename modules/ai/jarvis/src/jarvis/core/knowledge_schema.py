"""Decisão de taxonomia + payload schema + bootstrap Qdrant (§9–16).

Matriz de decisão (internal, explícita):

| DOMÍNIO            | SCHEMA (named vectors)      | QUERY PATTERN                | RETENTION | UPDATE    | ISOLATION | COLEÇÃO     |
|--------------------|------------------------------|------------------------------|-----------|-----------|-----------|-------------|
| code_knowledge     | dense 768 + bm25 sparse(idf) | híbrido dense-dominante (5:1), boost filename | segue git | por mtime | payload `source_type` | code_index  |
| episodic_memory    | dense 768 + bm25 sparse(idf) | híbrido, filtro kind/ts      | 7d→vault  | append-only | payload `kind` | memories    |
| durable_knowledge  | dense 768 + bm25 sparse(idf) | híbrido, filtro source_type/domain | longo | por mtime+sha | payload `source_type`,`knowledge_domain` | books       |

Mesma embedding (nomic-embed-v2-moe, 768), mesma estrutura de vetores →
3 coleções porque os contratos de RETENÇÃO e FILTRO divergem
(episódica expira; código segue git; knowledge é durável). Payload
particiona dentro de cada uma (§9: nem 1-tudo, nem 1-tipo-cego).

Payload schema canônico (§13, só o que filtra/prova):
  knowledge_domain, source_type, source_id, canonical_path, filename,
  ext, chunk_index, title, repo, git_commit, source_sha256,
  content_hash, source_modified_at, ingested_at, sanitizer_version,
  extractor, ocr_used, authority, status + (episódica: kind, ts).

Payload indexes (§14, só campos filtrados):
  keyword: knowledge_domain, source_type, source_id, repo, status,
           authority, kind (memories)
  datetime: source_modified_at, ingested_at

Bootstrap idempotente e versionado (SCHEMA_VERSION). Recria coleções
com named vectors + sparse + indexes; NÃO apaga dados existentes
(wipe é operação explícita separada, só com backup verificado).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "2.0.0"


def _embed_dim() -> int:
    """Dimensão derivada do Config (fonte única JARVIS_EMBED_DIM), não cópia."""
    try:
        from jarvis.core.config import Config
        return Config().embed_dim
    except Exception:
        return 768


EMBED_DIM = _embed_dim()  # compat; real vem de Config.embed_dim

# (nome, sparse, indexes-keyword, indexes-datetime)
COLLECTIONS = {
    "code_index": {
        "sparse": True,
        "keyword": ["source_type", "source_id", "repo", "status", "authority"],
        "datetime": ["source_modified_at", "ingested_at"],
    },
    "memories": {
        "sparse": True,
        "keyword": ["kind", "status", "authority"],
        "datetime": ["ts", "ingested_at"],
    },
    "books": {
        "sparse": True,
        "keyword": ["knowledge_domain", "source_type", "source_id", "repo",
                    "status", "authority"],
        "datetime": ["source_modified_at", "ingested_at"],
    },
}

DEFAULT_AUTHORITY = "source"  # source > extracted > repo > derived > model
DEFAULT_STATUS = "current"    # current | historical | unknown


def vector_config(sparse: bool) -> dict[str, Any]:
    """Schema de NAMED vectors da coleção (mesma forma do vector_store).

    Formato Qdrant: `vectors` = {nome: spec} com SÓ o denso; sparse vai
    em `sparse_vectors` separado (misturar bm25 dentro de `vectors` dá
    400 VectorsConfig — verificado E2E).
    """
    v: dict[str, Any] = {
        "dense": {"size": EMBED_DIM, "distance": "Cosine"},
    }
    if sparse:
        return {
            "vectors": {"dense": {"size": EMBED_DIM, "distance": "Cosine"}},
            "sparse_vectors": {"bm25": {"modifier": "idf"}},
        }
    return {"vectors": v}


def ensure_collection(store: Any, name: str, *, recreate: bool = False) -> dict[str, Any]:
    """Cria/atualiza coleção com schema canônico + payload indexes.

    Idempotente: existe com o schema certo → retorna info sem tocar.
    recreate=True: DELETA e recria (só com backup verificado pelo caller).
    """
    spec = COLLECTIONS[name]
    existing = None
    try:
        info = store.info(name)
        # store real retorna {"result": {...}} com status; store ausente
        # levanta erro ou retorna dict sem "result"
        if isinstance(info, dict) and "result" in info:
            existing = info
        else:
            existing = None
    except Exception:
        existing = None
    has = existing is not None and isinstance(existing, dict) and \
        existing.get("result", {}).get("status") in ("green", "yellow", "red")
    if has and not recreate:
        return existing
    if has and recreate:
        store.delete_collection(name)
    store.ensure_collection(name, dim=EMBED_DIM)
    # payload indexes (keyword + datetime) — Qdrant recomenda criar
    # ANTES da ingestão para filter-aware HNSW
    for field in spec["keyword"]:
        _create_payload_index(store, name, field, "keyword")
    for field in spec["datetime"]:
        _create_payload_index(store, name, field, "datetime")
    # criação de index é ASSÍNCRONA no Qdrant (ack != construído):
    # espera limitada até payload_schema refletir todos os indexes.
    # Stores que não expõem payload_schema (fakes/compat) → sem verificação
    # estrita possível; com Qdrant real, timeout → erro explícito.
    expected = set(spec["keyword"]) | set(spec["datetime"])
    import time as _time
    deadline = _time.monotonic() + 15.0
    last_fields: set[str] | None = None
    while _time.monotonic() < deadline:
        try:
            info = store.info(name)
            schema = info.get("result", {}).get("payload_schema")
            if schema is None:
                return info  # store não reporta schema (fake/compat): nada a provar aqui
            fields = set(schema.keys())
            last_fields = fields
            if expected <= fields:
                return info
        except Exception:
            pass
        _time.sleep(0.3)
    if last_fields is None:
        # nunca conseguiu ler info nem expor schema → não bloquear stores compat
        return store.info(name)
    raise RuntimeError(
        f"bootstrap {name}: indexes não apareceram em 15s "
        f"(esperados {sorted(expected)}, vistos {sorted(last_fields)})")


def _create_payload_index(store: Any, name: str, field: str, schema_type: str) -> None:
    """Cria 1 payload index via API do store (sem client duplicado)."""
    try:
        store._request("PUT", f"/collections/{name}/index",
                       json={"field_name": field, "field_schema": schema_type})
    except Exception:
        pass  # index já existe → idempotente


def build_payload(base: dict[str, Any], *, knowledge_domain: str = "",
                  source_type: str = "", source_id: str = "",
                  canonical_path: str = "", filename: str = "",
                  title: str = "", repo: str = "", git_commit: str = "",
                  source_sha256: str = "", source_modified_at: float | None = None,
                  sanitizer_version: str = "", extractor: str = "",
                  ocr_used: bool = False, authority: str = DEFAULT_AUTHORITY,
                  status: str = DEFAULT_STATUS) -> dict[str, Any]:
    """Payload canônico (§13). Só campos filtráveis/provas — sem decorativo."""
    p = dict(base)  # content + chunk_index + ext etc. do caller
    now = datetime.now(timezone.utc).isoformat()
    p.update({
        "knowledge_domain": knowledge_domain,
        "source_type": source_type,
        "source_id": source_id,
        "canonical_path": canonical_path,
        "filename": filename,
        "title": title,
        "repo": repo,
        "git_commit": git_commit,
        "source_sha256": source_sha256,
        "content_hash": _content_hash(str(base.get("content", ""))),
        "source_modified_at": source_modified_at,
        "ingested_at": now,
        "sanitizer_version": sanitizer_version,
        "extractor": extractor,
        "ocr_used": ocr_used,
        "authority": authority,
        "status": status,
    })
    return p


def _content_hash(content: str) -> str:
    import hashlib
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def wipe_collections(store: Any, names: list[str], *,
                     backup_verified: bool = False) -> dict[str, Any]:
    """Wipe controlado (API-level, §17). Exige backup_verified=True.

    Retorna registros do antes/depois. Nunca rm -rf storage.
    """
    if not backup_verified:
        raise RuntimeError(
            "wipe exige backup_verified=True (Phase 0 provada); "
            "nunca destruir sem recovery point")
    before = {}
    for name in names:
        try:
            info = store.info(name)
            before[name] = info.get("result", {}).get("points_count", 0) \
                if isinstance(info, dict) else 0
        except Exception:
            before[name] = 0
        store.delete_collection(name)
    after = {}
    for name in names:
        try:
            info = store.info(name)
            after[name] = "EXISTS" if isinstance(info, dict) else "ABSENT"
        except Exception:
            after[name] = "ABSENT"
    return {"before": before, "after": after,
            "ts": datetime.now(timezone.utc).isoformat()}
