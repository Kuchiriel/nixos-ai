"""Testes unitários do RAG híbrido (porta V4.0.5) — sem serviços externos."""
import pytest
pytestmark = pytest.mark.integration

import os

from jarvis.core.rag import (
    HybridHit,
    _target_extension,
    apply_legacy_boosts,
    build_rich_content,
    extract_facts,
    get_symbol_block,
    iter_indexable_files,
    sparse_terms,
    sparse_vector,
)


# ---------------------------------------------------------------------------
# extract_facts (porta V4.0.5)
# ---------------------------------------------------------------------------

def test_extract_facts_python() -> None:
    content = "def analyze_packet(data):\n    pass\n\nclass PacketParser:\n    pass\n"
    facts = extract_facts(content, ".py")
    assert "fn: analyze_packet" in facts
    assert "ent: PacketParser" in facts


def test_extract_facts_ignores_stop_symbols_and_short() -> None:
    content = "def if(data):\n    pass\ndef ab(x):\n    pass\n"
    facts = extract_facts(content, ".py")
    assert all(f not in facts for f in ("fn: if", "fn: ab"))


def test_extract_facts_composite_extension_pb_h() -> None:
    content = "void set_attack_power(int v) {}\nclass Character {}\n"
    facts = extract_facts(content, ".pb.h")
    assert "fn: set_attack_power" in facts
    assert "ent: Character" in facts


def test_extract_facts_lua_function_forms() -> None:
    content = "function Player.new(x)\n  return x\nend\nlocal helper = function(a)\n  return a\nend\n"
    facts = extract_facts(content, ".lua")
    assert any(f.startswith("fn: Player.new") for f in facts)
    assert any(f == "fn: helper" for f in facts)


def test_extract_facts_nix_attrs_and_options() -> None:
    content = (
        "services.qdrant = { enable = true; };\n"
        "networking.hostName = mkForce \"lab\";\n"
        "options.services.foo.enable = mkEnableOption \"foo\";\n"
    )
    facts = extract_facts(content, ".nix")
    assert any(f.startswith("fn: services.qdrant") for f in facts)
    assert any(f.startswith("fn: networking.hostName") for f in facts)
    assert any("mkEnableOption" in f for f in facts)


def test_extract_facts_unknown_extension() -> None:
    assert extract_facts("def foo(): pass", ".xyz") == []


# ---------------------------------------------------------------------------
# get_symbol_block (porta V4.0.5)
# ---------------------------------------------------------------------------

def test_get_symbol_block_returns_braced_block() -> None:
    content = "class Foo {\n  int x;\n  int bar() { return 1; }\n}\n"
    block = get_symbol_block(content, "Foo")
    assert block is not None
    assert block.startswith("class Foo {")
    assert "int bar" in block


# ---------------------------------------------------------------------------
# rich content + sparse
# ---------------------------------------------------------------------------

def test_build_rich_content_matches_legacy_format() -> None:
    rich = build_rich_content("/a/b.py", ["fn: main"], "print('hi')")
    assert rich.startswith("[PATH: /a/b.py]")
    assert "[FACTS: fn: main]" in rich
    assert "print('hi')" in rich


def test_build_rich_content_truncates_content_not_header() -> None:
    content = "x" * 10_000
    rich = build_rich_content("/a/b.py", [], content, max_chars=3000)
    assert rich.startswith("[PATH: /a/b.py]")
    assert len(rich) < 3200  # cabe no ctx do modelo de embedding


def test_sparse_terms_counts_and_stopwords() -> None:
    terms = sparse_terms("def foo foo bar the")
    assert terms.get("foo") == 2.0
    assert terms.get("bar") == 1.0
    assert "the" not in terms
    assert "def" not in terms


def test_sparse_vector_is_deterministic() -> None:
    a = sparse_vector(sparse_terms("alpha beta gamma"))
    b = sparse_vector(sparse_terms("alpha beta gamma"))
    assert a == b


# ---------------------------------------------------------------------------
# boosts V4.0.5 (re-rank)
# ---------------------------------------------------------------------------

def _hit(path: str, score: float) -> dict:
    return {"score": score, "payload": {"path": path}}


def test_extension_filter_excludes_other_exts() -> None:
    hits = [_hit("/a/main.py", 0.9), _hit("/b/main.cpp", 0.95)]
    result = apply_legacy_boosts("procure main .py", hits)
    assert len(result) == 1
    assert result[0]["payload"]["path"] == "/a/main.py"


def test_target_extension_detects_real_extensions() -> None:
    assert _target_extension("procure main .py") == ".py"
    assert _target_extension("leia o README.md") == ".md"
    assert _target_extension("config.json do projeto") == ".json"


def test_target_extension_ignores_dotted_acronyms() -> None:
    assert _target_extension("N.O.M.A.D offline survival") is None
    assert _target_extension("S.O.S. protocol") is None
    assert _target_extension("C.A.B. bandage") is None
    assert _target_extension("U.S. military") is None


def test_dotted_acronym_query_does_not_filter_hits() -> None:
    hits = [_hit("/a/main.py", 0.9), _hit("/b/main.cpp", 0.95)]
    result = apply_legacy_boosts("N.O.M.A.D offline survival", hits)
    assert len(result) == 2
    assert result[0]["payload"]["path"] == "/b/main.cpp"


def test_filename_sovereignty_dominates() -> None:
    hits = [_hit("/a/other.py", 0.99), _hit("/b/working_proto.py", 0.5)]
    result = apply_legacy_boosts("working_proto", hits)
    assert result[0]["payload"]["path"] == "/b/working_proto.py"
    assert result[0]["score"] > 100000.0


def test_word_in_filename_boost() -> None:
    hits = [_hit("/a/network_protocol.py", 0.5), _hit("/b/unrelated.py", 0.6)]
    result = apply_legacy_boosts("procure o arquivo network protocol", hits)
    assert result[0]["payload"]["path"] == "/a/network_protocol.py"


def test_scores_sorted_desc() -> None:
    hits = [_hit("/a/x.py", 0.2), _hit("/b/y.py", 0.8)]
    result = apply_legacy_boosts("x", hits)
    assert [h["score"] for h in result] == sorted((h["score"] for h in result), reverse=True)


# ---------------------------------------------------------------------------
# varredura de diretórios (regras V4.0.5)
# ---------------------------------------------------------------------------

def test_iter_indexable_files_excludes_and_allows(tmp_path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("x = 1")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print(1)")
    (tmp_path / "src" / "README.md").write_text("# doc")
    (tmp_path / "src" / "notes.txt").write_text("notas")

    files = sorted(iter_indexable_files(tmp_path))
    rel = [os.path.relpath(f, tmp_path) for f in files]
    assert "src/main.py" in rel
    assert "src/README.md" in rel
    assert "node_modules/dep.js" not in rel


def test_iter_indexable_files_accepts_single_file(tmp_path) -> None:
    f = tmp_path / "single.py"
    f.write_text("x = 1")
    files = list(iter_indexable_files(f))
    assert len(files) == 1
    assert files[0].endswith("single.py")


def test_hybrid_hit_dataclass() -> None:
    hit = HybridHit(path="/a.py", score=0.5, payload={"symbols": ["main"]})
    assert hit.path == "/a.py"
    assert hit.payload["symbols"] == ["main"]


# ---------------------------------------------------------------------------
# index_file: chunk que nao cabe no ctx do embedder (audit P1-3)
# ---------------------------------------------------------------------------

class _FakeStore:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, list[dict]]] = []

    def upsert(self, name, points):
        self.upserts.append((name, points))

    def delete_by_filter(self, *a, **kw):
        raise AssertionError("prune nao deve rodar por default")


class _FakeLLM:
    """embed() falha acima de `limit` chars; embed_batch sempre falha."""
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.seen: list[str] = []

    def embed_batch(self, texts):
        raise RuntimeError("batch off no teste")

    def embed(self, text):
        if len(text) > self.limit:
            raise RuntimeError("input too large")
        self.seen.append(text)
        return [0.1, 0.2, 0.3, 0.4]


def _indexer(tmp_path, limit: int):
    from jarvis.core.rag import HybridIndexer

    idx = HybridIndexer()
    idx._store = _FakeStore()
    idx._llm = _FakeLLM(limit)
    path = tmp_path / "big.py"
    path.write_text("x = 1\n" * 400, encoding="utf-8")  # 2400 chars, 2 chunks
    return idx, str(path)


def test_index_file_shrinks_chunk_and_keeps_payload_consistent(tmp_path) -> None:
    # rich = chunk (1200) + header de proveniencia; metade (600) cabe em 800
    idx, path = _indexer(tmp_path, limit=800)
    payload = idx.index_file(path, force=True)

    assert payload is not None  # entrou (metade do chunk cabe)
    _name, points = idx._store.upserts[-1]
    sent = idx._llm.seen[-1]
    # o vetor foi calculado sobre o MESMO texto que o payload guarda
    assert payload["content"] in sent
    assert 500 <= len(payload["content"]) <= 800
    assert points[0]["payload"]["content"] == payload["content"]


def test_index_file_writes_canonical_payload_fields(tmp_path) -> None:
    """O indexador preenche os campos que knowledge_schema INDEXA.

    Medido 19/11: `code_index` tinha payload indexes para source_type,
    authority, status, canonical_path e source_modified_at, mas todo ponto
    gravado por `rag.py` vinha sem esses campos (so path/domain/arxiv_id),
    entao um filtro por eles nao casava com nada.
    """
    idx, path = _indexer(tmp_path, limit=4000)
    payload = idx.index_file(path, force=True)

    assert payload is not None
    assert payload["canonical_path"] == path
    assert payload["source_type"] == "code"
    assert payload["knowledge_domain"] == "code_knowledge"
    assert payload["authority"] == "source"
    assert payload["status"] == "current"
    assert payload["filename"] == "big.py"
    assert payload["extractor"] == "py"
    assert payload["sanitizer_version"]
    assert payload["source_modified_at"] > 0
    # identidade preservada: o prune por source_sha256 depende dela
    assert len(payload["source_sha256"]) == 64
    assert payload["source_id"] == payload["document_id"]
    assert payload["content_hash"]


def test_index_file_records_dropped_chunk_reason(tmp_path) -> None:
    idx, path = _indexer(tmp_path, limit=10)  # nada cabe, nem a metade
    assert idx.index_file(path, force=True) is None
    assert idx.skipped == [(path, "chunk_dropped 2/2")]


def test_legacy_boost_ignores_hit_without_path() -> None:
    """Hit sem path nao pode ganhar soberania de filename (regressao 19/11).

    `filename` vazio e substring de qualquer query, entao o boost de 100000
    ia para todo payload sem `path` (books) e dominava o top-k.
    """
    hits = [
        {"score": 1.0, "payload": {"book": "x", "content": "book chunk"}},
        {"score": 1.0, "payload": {"path": "/repo/vault_cipher.py"}},
    ]
    out = apply_legacy_boosts("how does the vault cipher work", hits)
    assert out[0]["payload"]["path"].endswith("vault_cipher.py")
    assert out[0]["score"] < 100000


def test_rerank_orders_by_cross_encoder_and_clears_the_tail(monkeypatch) -> None:
    """O cross-encoder manda e o slice fica acima da cauda (regressao 19/11).

    A fusao antiga era quase simetrica e devolvia score ~1/61 ao slice,
    enquanto a cauda mantinha o score do boost: o diversify_by_source entao
    subia a cauda na frente e o rerank piorava o recall (0.93 -> 0.36).
    """
    import types

    import jarvis.providers.reranker as rr
    from jarvis.core import rag as ragmod

    class FakeReranker:
        def __init__(self, *a, **kw) -> None:
            pass

        def rerank(self, query, docs):
            return [0.1, 5.0, 0.2, 9.0, 0.3]

    monkeypatch.setattr(rr, "Reranker", FakeReranker)
    dummy = types.SimpleNamespace(_cfg=types.SimpleNamespace(rerank_base_url="http://x"))
    cands = [{"score": 1000.0 - i, "payload": {"path": f"/p{i}.py", "content": "x"}}
             for i in range(8)]

    out = ragmod.HybridSearch._rerank_candidates(dummy, "q", cands)

    order = [h["payload"]["path"] for h in out[:5]]
    assert order == ["/p3.py", "/p1.py", "/p4.py", "/p2.py", "/p0.py"]
    tail = out[5:]
    assert [h["payload"]["path"] for h in tail] == ["/p5.py", "/p6.py", "/p7.py"]
    assert min(h["score"] for h in out[:5]) > max(h["score"] for h in tail)
