"""Testes do knowledge_schema (§32): bootstrap, payload, wipe, taxonomia."""
from __future__ import annotations

import json

import pytest


class _FakeStore:
    def __init__(self, existing: dict | None = None):
        self.existing = existing or {}
        self.deleted = []
        self.indexes = []
        self.created = []

    def info(self, name):
        if name in self.existing:
            return self.existing[name]
        raise RuntimeError(f"coleção {name} ausente")

    def ensure_collection(self, name, dim=None):
        self.created.append((name, dim))
        self.existing[name] = {"result": {"status": "green"}}

    def delete_collection(self, name):
        self.deleted.append(name)
        self.existing.pop(name, None)

    def _request(self, method, path, **kwargs):
        self.indexes.append((method, path, kwargs.get("json") or kwargs.get("body")))
        return {"result": {"status": "ok"}}


# ---------------------------------------------------------------------------
# taxonomia / vector config
# ---------------------------------------------------------------------------

def test_vector_config_dense_plus_sparse():
    from jarvis.core.knowledge_schema import vector_config
    v = vector_config(True)
    assert v["vectors"]["dense"]["size"] == 768
    assert v["vectors"]["dense"]["distance"] == "Cosine"
    assert v["sparse_vectors"]["bm25"]["modifier"] == "idf"
    v2 = vector_config(False)
    assert "sparse_vectors" not in v2


def test_collections_spec_has_three_domains():
    from jarvis.core.knowledge_schema import COLLECTIONS
    assert set(COLLECTIONS) == {"code_index", "memories", "books"}
    # episódica expira (retention), código segue git, knowledge durável —
    # contratos divergem → 3 coleções (não 1-tudo)
    assert "kind" in COLLECTIONS["memories"]["keyword"]
    assert "knowledge_domain" in COLLECTIONS["books"]["keyword"]
    assert "source_type" in COLLECTIONS["code_index"]["keyword"]


# ---------------------------------------------------------------------------
# ensure_collection
# ---------------------------------------------------------------------------

def test_ensure_collection_creates_with_indexes():
    from jarvis.core.knowledge_schema import ensure_collection
    store = _FakeStore()
    info = ensure_collection(store, "books")
    assert store.created == [("books", 768)]
    # indexes keyword + datetime criados (Qdrant: antes da ingestão)
    paths = [p for _, p, _ in store.indexes]
    assert "/collections/books/index" in paths
    fields = [b["field_name"] for _, _, b in store.indexes]
    assert "knowledge_domain" in fields and "ingested_at" in fields
    types = {b["field_name"]: b["field_schema"] for _, _, b in store.indexes}
    assert types["knowledge_domain"] == "keyword"
    assert types["ingested_at"] == "datetime"


def test_ensure_collection_idempotent_when_schema_ok():
    from jarvis.core.knowledge_schema import ensure_collection
    store = _FakeStore(existing={"books": {"result": {"status": "green"}}})
    info = ensure_collection(store, "books")
    assert store.created == []  # não toca
    assert store.indexes == []


def test_ensure_collection_recreate_deletes_first():
    from jarvis.core.knowledge_schema import ensure_collection
    store = _FakeStore(existing={"books": {"result": {"status": "green"}}})
    ensure_collection(store, "books", recreate=True)
    assert store.deleted == ["books"]
    assert store.created == [("books", 768)]


# ---------------------------------------------------------------------------
# build_payload
# ---------------------------------------------------------------------------

def test_build_payload_canonical_fields():
    from jarvis.core.knowledge_schema import build_payload, SCHEMA_VERSION
    p = build_payload(
        {"content": "texto", "chunk_index": 0, "ext": ".md"},
        knowledge_domain="durable_knowledge", source_type="books_notes",
        source_id="sha256:abc", canonical_path="/x/doc.md", filename="doc.md",
        title="Doc", repo="/home/nixos/Books", git_commit="69a6e7f",
        source_sha256="def" * 21 + "f", source_modified_at=1789736000.0,
        sanitizer_version=SCHEMA_VERSION, extractor="direct-read")
    assert p["knowledge_domain"] == "durable_knowledge"
    assert p["authority"] == "source"  # default source > model
    assert p["status"] == "current"
    assert len(p["content_hash"]) == 64
    assert p["ingested_at"]  # ISO
    assert p["ocr_used"] is False


def test_build_payload_content_hash_deterministic():
    from jarvis.core.knowledge_schema import build_payload
    a = build_payload({"content": "mesmo texto"}, )
    b = build_payload({"content": "mesmo texto"}, )
    assert a["content_hash"] == b["content_hash"]
    c = build_payload({"content": "outro"})
    assert c["content_hash"] != a["content_hash"]


# ---------------------------------------------------------------------------
# wipe
# ---------------------------------------------------------------------------

def test_wipe_requires_backup_verified():
    from jarvis.core.knowledge_schema import wipe_collections
    store = _FakeStore(existing={"books": {"result": {"points_count": 40}}})
    with pytest.raises(RuntimeError, match="backup_verified"):
        wipe_collections(store, ["books"], backup_verified=False)
    assert store.deleted == []  # nunca apaga sem prova


def test_wipe_controlled_api_level():
    from jarvis.core.knowledge_schema import wipe_collections
    store = _FakeStore(existing={
        "books": {"result": {"points_count": 40}},
        "memories": {"result": {"points_count": 509}},
    })
    out = wipe_collections(store, ["books", "memories"], backup_verified=True)
    assert out["before"] == {"books": 40, "memories": 509}
    assert out["after"] == {"books": "ABSENT", "memories": "ABSENT"}
    assert store.deleted == ["books", "memories"]
