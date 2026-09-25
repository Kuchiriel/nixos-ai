"""Regressão: manifest não pode dizer 'indexado' para o que não foi indexado.

Bug (25/09): `index_file` gravava `_indexed_hashes[path] = mtime` ANTES de
decidir. Um arquivo em quarentena (PATH_ERROR, PII) ou que falhasse no embed
ficava marcado como indexado — e como o manifest é o que faz `index_file`
pular arquivo inalterado, o arquivo nunca mais era retryado. Perda
silenciosa: as 33 notas do vault davam 0 indexadas e nenhuma busca as achava.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import dataclasses

from jarvis.core.config import Config
from jarvis.core.rag import HybridIndexer


class _Store:
    """Store em memória: guarda o que foi realmente upsertado."""

    def __init__(self) -> None:
        self.upserts: list[tuple[str, list[dict]]] = []

    def ensure_collection(self, *a, **k) -> None:
        return None

    def upsert(self, collection: str, points: list[dict]) -> None:
        self.upserts.append((collection, points))

    def count(self, *a, **k) -> int:
        return sum(len(p) for _, p in self.upserts)


class _LLM:
    """Embedder determinístico; `fail` força a exceção do embed."""

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.fail = False

    def embed(self, text: str, model: str | None = None) -> list[float]:
        if self.fail:
            raise RuntimeError("embeddings down")
        h = sum(ord(c) for c in text[:64]) or 1
        return [((h * (i + 1)) % 97) / 97.0 for i in range(self.dim)]


def _indexer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HybridIndexer:
    # Col derivada via replace (convenção do test_test_isolation.py): nunca
    # nome de coleção de produção em arquivo de teste.
    cfg = dataclasses.replace(Config(), qdrant_collection_code="jarvis_test_manifest")
    ix = HybridIndexer(cfg)
    ix._store = _Store()
    ix._llm = _LLM()
    ix._indexed_hashes = {}
    return ix


def test_quarantine_nao_marca_como_indexado(tmp_path, monkeypatch) -> None:
    """Arquivo em quarentena NÃO pode entrar no manifest."""
    ix = _indexer(tmp_path, monkeypatch)
    f = tmp_path / "fora.md"
    f.write_text("conteudo", encoding="utf-8")

    real_sanitize = None

    def _boom(path):
        class R:
            status = "quarantine"
            text = ""
        return R()

    monkeypatch.setattr(
        "jarvis.core.doc_sanitize.sanitize_document", _boom)
    assert ix.index_file(str(f)) is None
    assert str(f) not in ix._indexed_hashes, "quarentena não pode marcar o manifest"


def test_erro_de_embed_nao_marca_como_indexado(tmp_path) -> None:
    """Falha do embed também não pode marcar (senão o retry nunca acontece)."""
    ix = _indexer(tmp_path, None)  # type: ignore[arg-type]
    f = tmp_path / "nota.md"
    f.write_text("texto suficiente para chunk", encoding="utf-8")
    ix._llm.fail = True

    assert ix.index_file(str(f)) is None
    assert str(f) not in ix._indexed_hashes, "embed falhou: não pode marcar"


def test_sucesso_marca_no_manifest(tmp_path) -> None:
    """Caminho feliz: indexado de verdade => manifest registra (mtime)."""
    ix = _indexer(tmp_path, None)  # type: ignore[arg-type]
    f = tmp_path / "ok.md"
    f.write_text("texto suficiente para chunk", encoding="utf-8")

    out = ix.index_file(str(f))
    assert out is not None, "deveria ter indexado"
    assert str(f) in ix._indexed_hashes
    assert ix._indexed_hashes[str(f)] == f.stat().st_mtime


def test_arquivo_inalterado_e_pulado(tmp_path) -> None:
    """Skip por mtime continua funcionando (é o propósito do manifest)."""
    ix = _indexer(tmp_path, None)  # type: ignore[arg-type]
    f = tmp_path / "ok.md"
    f.write_text("texto suficiente para chunk", encoding="utf-8")
    ix.index_file(str(f))
    antes = len(ix._store.upserts)
    ix.index_file(str(f))  # segunda chamada: deve pular
    assert len(ix._store.upserts) == antes, "não deve reindexar sem mudança"


def test_manifest_preservado_entre_instancias(tmp_path) -> None:
    """O manifest vem do disco: um arquivo já indexado continua pulando."""
    ix = _indexer(tmp_path, None)  # type: ignore[arg-type]
    f = tmp_path / "ok.md"
    f.write_text("texto suficiente para chunk", encoding="utf-8")
    ix.index_file(str(f))
    mtime = f.stat().st_mtime
    ix2 = _indexer(tmp_path, None)  # type: ignore[arg-type]
    ix2._indexed_hashes = {str(f): mtime}
    assert ix2.index_file(str(f)) is None
    assert not ix2._store.upserts
