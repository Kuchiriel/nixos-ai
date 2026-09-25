"""Testes do chunk + mean-pool de embeddings longos.

Bug que motivou: remember() com texto longo recebia HTTP 500 do
llama-server de embeddings (n_ctx 2048) e a memória sumia em silêncio.
"""

from __future__ import annotations

from jarvis.providers.embedding import (
    CHUNK_CHARS,
    embed_long,
    mean_pool,
    split_for_embedding,
)


def test_short_text_single_chunk() -> None:
    assert split_for_embedding("olá mundo") == ["olá mundo"]


def test_empty_text() -> None:
    assert split_for_embedding("   ") == [""]


def test_long_text_is_split_with_overlap() -> None:
    text = "palavra " * 5000  # bem acima de CHUNK_CHARS
    chunks = split_for_embedding(text)
    assert len(chunks) > 1
    assert all(len(c) <= CHUNK_CHARS + 1 for c in chunks)
    # sem buraco: o último chunk encosta no fim do texto
    assert chunks[-1].strip().endswith("palavra")


def test_split_breaks_on_paragraph_boundary() -> None:
    para = "linha\n" * 900  # ~4500 chars
    chunks = split_for_embedding(para + para)
    assert len(chunks) >= 2


def test_mean_pool_normalizes() -> None:
    pooled = mean_pool([[3.0, 4.0], [0.0, 5.0]])
    norm = sum(v * v for v in pooled) ** 0.5
    assert abs(norm - 1.0) < 1e-6
    assert all(v > 0 for v in pooled)


def test_mean_pool_empty() -> None:
    assert mean_pool([]) == []


def test_embed_long_calls_backend_once_for_short() -> None:
    calls: list[str] = []

    def fake(text: str) -> list[float]:
        calls.append(text)
        return [1.0, 0.0]

    out = embed_long(fake, "curto")
    assert out == [1.0, 0.0]
    assert len(calls) == 1


def test_embed_long_pools_multiple_chunks() -> None:
    calls: list[str] = []

    def fake(text: str) -> list[float]:
        calls.append(text)
        return [1.0, 0.0]

    out = embed_long(fake, "palavra " * 5000)
    assert len(calls) > 1
    assert abs(sum(v * v for v in out) ** 0.5 - 1.0) < 1e-6


def test_embed_long_empty_text_still_calls_backend() -> None:
    seen: list[str] = []
    embed_long(lambda t: (seen.append(t) or [0.0, 1.0]), "")
    assert seen == [""]
