"""Skills on-demand (standard Agent Skills): discovery, frontmatter, load."""

from __future__ import annotations

import os

import pytest

from jarvis.core import skills as S


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    # skills/ relativo ao cwd (repo) não pode vazar nos testes.
    empty = tmp_path / "cwd"
    empty.mkdir(exist_ok=True)
    monkeypatch.chdir(empty)


def _mk(base, name, desc, body="corpo"):
    d = base / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n\n{body}\n",
        encoding="utf-8")
    return d


def test_discovers_dir_with_skill_md(tmp_path, monkeypatch):
    _mk(tmp_path, "alpha", "faz alpha")
    monkeypatch.setenv("JARVIS_SKILLS_DIR", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "nohome")
    found = {s.name: s for s in S.list_skills()}
    assert found["alpha"].description == "faz alpha"


def test_lenient_root_md_and_name_fallback(tmp_path, monkeypatch):
    (tmp_path / "loose.md").write_text("sem frontmatter\n", encoding="utf-8")
    d = tmp_path / "noname"
    d.mkdir()
    (d / "SKILL.md").write_text("sem frontmatter\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_SKILLS_DIR", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "nohome")
    found = {s.name: s for s in S.list_skills()}
    assert "loose" in found  # nome = arquivo
    assert "noname" in found  # nome = diretório


def test_dedupe_first_source_wins(tmp_path, monkeypatch):
    a = tmp_path / "a"
    b = tmp_path / "b"
    _mk(a, "dup", "primeira")
    _mk(b, "dup", "segunda")
    monkeypatch.setenv("JARVIS_SKILLS_DIR", str(a))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "nohome")
    # injeta segunda fonte via monkeypatch em skill_dirs
    orig = S.skill_dirs
    monkeypatch.setattr(S, "skill_dirs", lambda: [a, b])
    found = {s.name: s for s in S.list_skills()}
    assert found["dup"].description == "primeira"
    monkeypatch.setattr(S, "skill_dirs", orig)


def test_load_skill_ok_and_unknown(tmp_path, monkeypatch):
    _mk(tmp_path, "beta", "faz beta", body="PASSO 1")
    monkeypatch.setenv("JARVIS_SKILLS_DIR", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "nohome")
    ok = S.load_skill("beta")
    assert ok["ok"] is True and "PASSO 1" in ok["content"]
    bad = S.load_skill("fantasma")
    assert bad["ok"] is False and "known" in bad


def test_load_skill_truncates(tmp_path, monkeypatch):
    _mk(tmp_path, "big", "grande", body="x" * (S.MAX_SKILL_CHARS + 100))
    monkeypatch.setenv("JARVIS_SKILLS_DIR", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "nohome")
    ok = S.load_skill("big")
    assert ok["ok"] is True
    assert len(ok["content"]) <= S.MAX_SKILL_CHARS + 50


def test_descriptions_block_format(tmp_path, monkeypatch):
    _mk(tmp_path, "gama", "faz gama")
    monkeypatch.setenv("JARVIS_SKILLS_DIR", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "nohome")
    block = S.descriptions_block()
    assert "<skills>" in block
    assert 'name="gama"' in block
    assert "load_skill" in block


def test_empty_dirs_gives_empty_block(tmp_path, monkeypatch):
    (tmp_path / "vazio").mkdir()
    monkeypatch.setenv("JARVIS_SKILLS_DIR", str(tmp_path / "vazio"))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "nohome")
    assert S.descriptions_block() == ""


def test_handle_dev_tool_load_skill(tmp_path, monkeypatch):
    from jarvis.core.devtools import handle_dev_tool
    import json as J
    _mk(tmp_path, "delta", "faz delta", body="CONTEUDO")
    monkeypatch.setenv("JARVIS_SKILLS_DIR", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "nohome")
    # skills do repo (cwd) podem interferir — força só tmp via env já basta
    # se ./skills não existir no cwd do teste; verifica o essencial:
    out = J.loads(handle_dev_tool("load_skill", {"name": "delta"}))
    assert out["ok"] is True and "CONTEUDO" in out["content"]
    out2 = J.loads(handle_dev_tool("load_skill", {}))
    assert out2["ok"] is False and "args ausentes" in out2["error"]
