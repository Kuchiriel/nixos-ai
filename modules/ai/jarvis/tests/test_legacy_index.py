"""Testes do índice legado (.ai-index) — loader, busca pura V4.0.5 e migração.

Os testes de integração (migração real + paridade contra Qdrant) são
marcados `integration` e pulam quando o Qdrant não está disponível.
"""

import json
import os

import numpy as np
import pytest

from jarvis.core.legacy_index import (
    LegacyIndex,
    LegacyIndexError,
    _overlap,
    legacy_search,
    legacy_search_symbols,
    load_legacy_index,
    migrate,
    parity_report,
)
from jarvis.providers.vector_store import QdrantStore, dense_key


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_index(tmp_path, n=4, dim=8) -> LegacyIndex:
    """Índice sintético determinístico: paths de projeto + símbolos."""
    meta = []
    for i in range(n):
        meta.append({
            "path": f"/home/dev/proj/file{i}.py",
            "facts": [f"fn: symbol{i}"],
            "content": f"def symbol{i}():\n    return {i}\n" * 3,
        })
    rng = np.random.default_rng(42)
    vectors = rng.normal(size=(n, dim))
    symbols = {f"symbol{i}": [f"/home/dev/proj/file{i}.py"] for i in range(n)}
    hashes = {f"/home/dev/proj/file{i}.py|0|0": "abc" for i in range(n)}

    for name, data in (
        ("global_meta.json", meta),
        ("symbols.json", symbols),
        ("file_hashes.json", hashes),
    ):
        (tmp_path / name).write_text(json.dumps(data))
    np.save(tmp_path / "global_vectors.npy", vectors)
    return load_legacy_index(tmp_path)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def test_load_legacy_index(tmp_path):
    index = _make_index(tmp_path)
    assert len(index) == 4
    assert index.vectors.shape == (4, 8)
    assert index.symbols["symbol0"] == ["/home/dev/proj/file0.py"]
    assert index.paths()[0].endswith("file0.py")


def test_load_missing_files_raises(tmp_path):
    with pytest.raises(LegacyIndexError):
        load_legacy_index(tmp_path)


def test_load_bad_shape_raises(tmp_path):
    (tmp_path / "global_meta.json").write_text(json.dumps([{"path": "/a.py"}]))
    (tmp_path / "symbols.json").write_text(json.dumps({}))
    np.save(tmp_path / "global_vectors.npy", np.zeros((2, 8)))  # 2 vetores, 1 meta
    with pytest.raises(LegacyIndexError):
        load_legacy_index(tmp_path)


# ---------------------------------------------------------------------------
# Busca legada pura (ground-truth V4.0.5)
# ---------------------------------------------------------------------------

def test_legacy_search_returns_top_k(tmp_path):
    index = _make_index(tmp_path)
    qvec = index.vectors[0]
    results = legacy_search(index, qvec, "file0", top_k=3)
    assert len(results) == 3
    assert results[0]["path"].endswith("file0.py")  # self-match no topo
    assert results[0]["score"] > 0.1


def test_legacy_search_extension_filter(tmp_path):
    # índice misto: .py e .cpp — query com ".cpp" deve retornar só .cpp
    meta = [
        {"path": "/home/dev/proj/a.py", "facts": [], "content": "def a(): pass"},
        {"path": "/home/dev/proj/bfile.cpp", "facts": [], "content": "int b() {}"},
    ]
    (tmp_path / "global_meta.json").write_text(json.dumps(meta))
    (tmp_path / "symbols.json").write_text(json.dumps({}))
    np.save(tmp_path / "global_vectors.npy", np.eye(2, dtype=float))
    index = load_legacy_index(tmp_path)
    # "bfile.cpp" na query → sovereignty do filename + filtro de extensão
    results = legacy_search(index, index.vectors[0], "bfile.cpp", top_k=5)
    assert results, "esperava ao menos um resultado"
    assert all(r["path"].endswith(".cpp") for r in results)
    assert results[0]["path"].endswith("bfile.cpp")


def test_legacy_search_symbols(tmp_path):
    index = _make_index(tmp_path)
    results = legacy_search_symbols(index, "symbol2 symbol9")
    symbols = {r["symbol"] for r in results}
    assert "symbol2" in symbols
    assert "symbol9" not in symbols


def test_overlap_metric():
    assert _overlap(["a", "b"], ["a", "b"], 2) == 1.0
    assert _overlap(["a", "b"], ["a", "c"], 2) == pytest.approx(0.5)  # 1 de 2
    assert _overlap([], ["a"], 2) == 0.0


# ---------------------------------------------------------------------------
# Migração (unit: shape/ids determinísticos — sem Qdrant)
# ---------------------------------------------------------------------------

def test_migrate_builds_deterministic_point_ids(tmp_path):
    index = _make_index(tmp_path)
    # sem Qdrant: simulamos os pontos que seriam enviados checando o id único
    ids = {abs(dense_key(p)) for p in index.paths()}
    assert len(ids) == len(index.paths())


def test_payload_schema_matches_new_index(tmp_path):
    index = _make_index(tmp_path)
    payload = index.payload_for(0)
    assert payload["path"].endswith("file0.py")
    assert payload["filename"] == "file0.py"
    assert payload["symbols"] == ["symbol0"]
    assert "def symbol0" in payload["content"]


# ---------------------------------------------------------------------------
# Integração (Qdrant real) — skip quando indisponível
# ---------------------------------------------------------------------------


def _qdrant_available() -> bool:
    from jarvis.core.config import Config

    return QdrantStore(Config()).is_available()


@pytest.mark.integration
def test_migrate_roundtrip_and_count(tmp_path):
    if not _qdrant_available():
        pytest.skip("Qdrant indisponível")
    from jarvis.core.config import Config

    cfg = Config()
    store = QdrantStore(cfg)
    collection = "jarvis_test_migrate"
    index = _make_index(tmp_path)
    try:
        store.delete_collection(collection)
        migrated = migrate(index, cfg, collection=collection)
        assert migrated == len(index)
        assert store.count(collection) == len(index)
    finally:
        store.delete_collection(collection)


@pytest.mark.integration
def test_parity_with_synthetic_index(tmp_path):
    if not _qdrant_available():
        pytest.skip("Qdrant indisponível")
    from jarvis.core.config import Config

    cfg = Config()
    store = QdrantStore(cfg)
    collection = cfg.qdrant_collection_code
    index = _make_index(tmp_path, n=8, dim=16)
    try:
        store.delete_collection(collection)
        migrate(index, cfg)
        report = parity_report(
            index,
            cfg,
            queries=[f"/home/dev/proj/file{i}.py" for i in range(4)],
            top_k=3,
        )
        assert report["total_queries"] >= 3
        # no mínimo 2 de 3 no top-3 (≥ 66%) para índice sintético coeso
        assert report["overlap_medio"] >= 0.6
    finally:
        store.delete_collection(collection)
