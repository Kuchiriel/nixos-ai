"""Testes unitários do RAG híbrido (porta V4.0.5) — sem serviços externos."""

import os

from jarvis.core.rag import (
    HybridHit,
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
