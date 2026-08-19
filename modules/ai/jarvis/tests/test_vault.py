"""Testes do vault de memória de longo prazo (core/vault.py — Fase 7)."""

from __future__ import annotations

import time

from jarvis.core.config import Config
from jarvis.core.vault import MemoryVault


class FakeLLM:
    def chat(self, messages, *, temperature=0.0, max_tokens=None):
        return "## Lições\n- erro X foi corrigido com Y.\n## Decisões\n- nada."


class FakeMemory:
    def __init__(self, events):
        self._events = events
        self.facts = []

    def recent(self, *, limit=20):
        return list(self._events)

    def remember_fact(self, text, **meta):
        self.facts.append({"text": text, "meta": meta})
        return 42


def _events(n: int, *, age_days: float = 1.0) -> list[dict]:
    ts = time.time() - age_days * 86400
    return [
        {
            "kind": "lesson", "ts": ts,
            "text": f"Task: t{i}. Error: e{i}. Fix: f{i}",
            "task": f"t{i}", "error_pattern": f"e{i}", "fix": f"f{i}",
        }
        for i in range(n)
    ]


def _vault(tmp_path, events, *, llm=None, memory=None):
    cfg = Config(vault_dir=tmp_path / "vault")
    mem = memory or FakeMemory(events)
    return MemoryVault(cfg, memory=mem, llm=llm or FakeLLM()), mem


def test_summarize_writes_markdown_and_remembers(tmp_path) -> None:
    vault, mem = _vault(tmp_path, _events(3))
    result = vault.summarize(since_days=7, commit=False)

    assert result["written"] is True
    assert result["count"] == 3
    assert result["fact_id"] == 42

    # arquivo mensal criado com o resumo
    files = list((tmp_path / "vault").glob("*.md"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "## Resumo" in content
    assert "## Lições" in content
    assert "erro X foi corrigido" in content

    # resumo gravado de volta na memória episódica (recall semântico)
    assert len(mem.facts) == 1
    assert mem.facts[0]["meta"]["summary"] is True
    assert "Resumo de memória" in mem.facts[0]["text"]


def test_summarize_skips_when_no_recent_events(tmp_path) -> None:
    vault, _ = _vault(tmp_path, _events(2, age_days=30.0))
    result = vault.summarize(since_days=7, commit=False)
    assert result == {"written": False, "reason": "no_events", "count": 0}
    assert list((tmp_path / "vault").glob("*.md")) == []


def test_summarize_reports_llm_error(tmp_path) -> None:
    class BadLLM:
        def chat(self, messages, **kw):
            raise RuntimeError("servidor fora do ar")

    vault, _ = _vault(tmp_path, _events(1), llm=BadLLM())
    result = vault.summarize(since_days=7, commit=False)
    assert result["written"] is False
    assert result["reason"].startswith("llm_error")


def test_summarize_appends_to_same_month(tmp_path) -> None:
    vault, _ = _vault(tmp_path, _events(2))
    vault.summarize(since_days=7, commit=False)
    vault.summarize(since_days=7, commit=False)
    files = list((tmp_path / "vault").glob("*.md"))
    assert len(files) == 1  # mesmo mês → mesmo arquivo, seções acumuladas
    assert files[0].read_text(encoding="utf-8").count("## Resumo") == 2


def test_summarize_commits_git_when_requested(tmp_path, monkeypatch) -> None:
    calls = []

    class FakeGitMemory(FakeMemory):
        pass

    vault, mem = _vault(tmp_path, _events(1), memory=FakeGitMemory(_events(1)))
    monkeypatch.setattr(vault, "_git", lambda *a: (calls.append(a), True)[1])
    vault.summarize(since_days=7, commit=True)
    assert any(c[0] == "add" for c in calls)
    assert any(c[0] == "commit" for c in calls)


def test_list_notes_empty_and_after_summary(tmp_path) -> None:
    vault, _ = _vault(tmp_path, [])
    assert vault.list_notes() == []
    vault, _ = _vault(tmp_path, _events(1))
    vault.summarize(since_days=7, commit=False)
    assert len(vault.list_notes()) == 1
    assert vault.list_notes()[0].endswith(".md")
