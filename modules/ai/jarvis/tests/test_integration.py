"""Testes de integração contra os serviços locais da VM.

Skipped automaticamente quando llama.cpp (8080) ou Qdrant (6333) estão
fora do ar — permite rodar a suíte sem infraestrutura.
"""

import pytest

from jarvis.core.config import Config
from jarvis.providers.llm import LLMClient, LLMError
from jarvis.providers.vector_store import QdrantStore

cfg = Config()
llm = LLMClient(cfg)
store = QdrantStore(cfg)

pytestmark = pytest.mark.integration


def test_llama_cpp_is_up() -> None:
    if not llm.is_available():
        pytest.skip("llama.cpp não está respondendo em 8080")
    models = llm.models()
    assert isinstance(models, list)


def test_llama_cpp_chat() -> None:
    if not llm.is_available():
        pytest.skip("llama.cpp não está respondendo em 8080")
    response = llm.chat(
        [{"role": "user", "content": "Responda apenas com a palavra: ok"}],
        max_tokens=16,
    )
    assert isinstance(response, str)
    assert len(response) > 0


def test_llama_cpp_embeddings_or_explicit_failure() -> None:
    """Embeddings exigem llama-server com --embeddings; falha deve ser explícita."""
    if not llm.is_available():
        pytest.skip("llama.cpp não está respondendo em 8080")
    try:
        vec = llm.embed("teste de embedding")
    except LLMError as exc:
        pytest.skip(f"embedding não habilitado no servidor atual: {exc}")
    assert len(vec) > 0


def test_qdrant_roundtrip() -> None:
    if not store.is_available():
        pytest.skip("Qdrant não está respondendo em 6333")
    collection = "jarvis_test"
    try:
        store.ensure_collection(collection, dim=4)
        store.delete_points(collection, [1, 2])
        store.upsert(collection, [
            {"id": 1, "vector": [1.0, 0.0, 0.0, 0.0], "payload": {"path": "/a.py", "facts": ["fn: main"]}},
            {"id": 2, "vector": [0.0, 1.0, 0.0, 0.0], "payload": {"path": "/b.py"}},
        ])
        hits = store.search(collection, [1.0, 0.0, 0.0, 0.0], top_k=2)
        assert hits, "busca não retornou resultados"
        assert hits[0]["payload"]["path"] == "/a.py"
        assert store.count(collection) == 2
    finally:
        store.delete_collection(collection)
