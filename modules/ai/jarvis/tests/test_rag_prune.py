"""Reconciliação do índice RAG (rag_prune) — sem serviços externos.

Bug de origem (medido 19/11): `stable_id("doc", source_sha256, i)` muda a
cada edição, então reindexar deixa as versões antigas recuperáveis no
Qdrant. Estes testes fixam o contrato de classificação e o manifesto antes
da remoção.
"""
from __future__ import annotations

import json

from jarvis.core.rag_prune import (
    REASON_CURRENT,
    REASON_MISSING,
    REASON_NO_IDENTITY,
    REASON_STALE,
    apply,
    scan,
)


class FakeStore:
    def __init__(self, points: list[dict]) -> None:
        self.points = points
        self.deleted: list[tuple[str, list[int]]] = []

    def scroll_all(self, name, *, payload_keys=None, page=512, max_pages=None):
        return list(self.points)

    def delete_points(self, name, ids):
        self.deleted.append((name, list(ids)))


DISK = {"/repo/a.py": "sha-new", "/repo/b.py": "sha-b"}


def _sha(path: str):
    return DISK.get(path)


def _points() -> list[dict]:
    return [
        {"id": 1, "payload": {"path": "/repo/a.py", "source_sha256": "sha-new"}},
        {"id": 2, "payload": {"path": "/repo/a.py", "source_sha256": "sha-old"}},
        {"id": 3, "payload": {"path": "/repo/gone.py", "source_sha256": "sha-x"}},
        {"id": 4, "payload": {"path": "/repo/b.py"}},  # sem sha: schema antigo
        {"id": 5, "payload": {}},  # sem path: órfão
    ]


def test_scan_classifies_without_deleting() -> None:
    store = FakeStore(_points())
    report = scan(store, "code_index", sha_of=_sha)
    assert store.deleted == []  # varredura não apaga
    assert report["total_points"] == 5
    assert report["by_reason"] == {
        REASON_CURRENT: 1, REASON_STALE: 1,
        REASON_MISSING: 1, REASON_NO_IDENTITY: 2,
    }
    assert report["ids"][REASON_STALE] == [2]
    assert report["ids"][REASON_MISSING] == [3]
    # sem identidade NÃO é removível (books legítimo não tem path)
    assert report["removable"] == 2
    # paths só lista stale/missing
    assert {p["path"] for p in report["paths"]} == {"/repo/a.py", "/repo/gone.py"}


def test_apply_requires_report_and_deletes_only_removable(tmp_path) -> None:
    store = FakeStore(_points())
    report = scan(store, "code_index", sha_of=_sha)
    res = apply(store, report, manifest_dir=tmp_path)
    assert res["deleted"] == 2
    flat = [i for _, ids in store.deleted for i in ids]
    assert 1 not in flat  # versão atual fica
    assert sorted(flat) == [2, 3]
    manifest = json.loads(open(res["manifest"], encoding="utf-8").read())
    assert manifest["collection"] == "code_index"
    assert sorted(manifest["ids"]) == [2, 3]


def test_apply_with_nothing_removable_does_not_write_manifest(tmp_path) -> None:
    store = FakeStore([{"id": 1, "payload": {"path": "/repo/a.py",
                                             "source_sha256": "sha-new"}}])
    report = scan(store, "code_index", sha_of=_sha)
    res = apply(store, report, manifest_dir=tmp_path)
    assert res["deleted"] == 0
    assert store.deleted == []
    assert list(tmp_path.iterdir()) == []


def test_sha_lookup_happens_once_per_path() -> None:
    calls: list[str] = []

    def sha(path: str):
        calls.append(path)
        return DISK.get(path)

    scan(FakeStore(_points()), "code_index", sha_of=sha)
    assert calls.count("/repo/a.py") == 1
