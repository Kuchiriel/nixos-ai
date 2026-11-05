"""Testes do `jarvis_rehydrate` (R1 — resgate de sessão em 1 chamada).

Regras da pesquisa que estes testes TRAVAM (docs/REHYDRATACAO-E-COORDENACAO.md):
- reversível: devolve o ORIGINAL + o caminho (nunca um resumo do original);
- query-conditioned: memórias/lições/RAG filtradas pelo pedido;
- triage por tipo: guardas pinadas exatas no topo; HANDOFF atômico;
- 1 chamada: as guardas saem sempre, os blocos pedem `include`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def M(monkeypatch, tmp_path):
    from jarvis import mcp_server as m

    # fila fake (2 checkpoints: o topo tem que ser o mais recente)
    queue = tmp_path / "AGENTS-QUEUE.md"
    queue.write_text(
        "## ⭐ CHECKPOINT 2026-11-02 17:06 — nova-era\n"
        "**Resumo:** estado novo\n"
        "## ⭐ CHECKPOINT 2026-11-01 10:00 — velha-era\n"
        "**Resumo:** estado velho\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTS_QUEUE", str(queue))

    # vault fake: 2 HANDOFFs, o mais recente por nome
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "HANDOFF-2026-11-01-antigo.md").write_text("antigo\n", encoding="utf-8")
    (vault / "HANDOFF-2026-11-02-novo.md").write_text(
        "era nova\npasso 1: reidratar\n", encoding="utf-8")

    class FakeVault:
        def list_notes(self):
            return ["HANDOFF-2026-11-01-antigo.md", "HANDOFF-2026-11-02-novo.md"]

        def read_note(self, name):
            return (vault / name).read_text(encoding="utf-8")

    import jarvis.core.vault as vault_mod

    monkeypatch.setattr(vault_mod, "MemoryVault", FakeVault)

    # memória fake
    class FakeMem:
        def recall(self, query, top_k=5):
            return [{"kind": "fact", "text": f"memória de {query}"}]

        def lessons(self, query, top_k=3):
            return f"lição de {query}"

    import jarvis.core.memory as mem_mod

    monkeypatch.setattr(mem_mod, "EpisodicMemory", FakeMem)

    # RAG fake (sem rede/Qdrant no teste)
    monkeypatch.setattr(m, "_handle_rag_search",
                        lambda a: f"[rag] {a['query']} @ {a['collection']}")

    # roster fake
    monkeypatch.setattr(m, "_rehydrate_roster",
                        lambda: "- nixos-ai: lane=nixos-ai/coordenacao repo=nixos-ai")

    # loop-breaker desligado por default nos testes (cada teste = 1 resgate)
    monkeypatch.setenv("JARVIS_REHYDRATE_COOLDOWN_S", "0")
    m._REHYDRATE_CALLS.clear()
    m._REHYDRATE_SEEN.clear()
    return m


def test_rehydrate_requires_task(M):
    assert "ERROR" in M._handle_rehydrate({})
    assert "ERROR" in M._handle_rehydrate({"task": "  "})


def test_rehydrate_returns_guards_first(M):
    out = M._handle_rehydrate({"task": "coordenação", "include": "queue"})
    assert out.startswith("## GUARDS")
    # guardas pinadas: o contrato de coordenação tem que estar LITERAL
    assert "agent-roster.py claim" in out
    assert "--note" in out and "--to" in out and "--cancel" in out
    assert "rehydrate" in out


def test_rehydrate_queue_is_the_newest_note(M):
    out = M._handle_rehydrate({"task": "x", "include": "queue"})
    assert "nova-era" in out
    assert "velha-era" not in out


def test_rehydrate_handoff_is_newest_and_atomic(M):
    out = M._handle_rehydrate({"task": "x", "include": "handoff"})
    assert "HANDOFF-2026-11-02-novo.md" in out
    assert "era nova" in out
    assert "antigo" not in out


def test_rehydrate_memories_and_lessons_are_query_conditioned(M):
    out = M._handle_rehydrate({"task": "compaction", "include": "memories,lessons"})
    assert "memória de compaction" in out
    assert "lição de compaction" in out
    assert "memória de outra" not in out


def test_rehydrate_include_filters_blocks(M):
    out = M._handle_rehydrate({"task": "x", "include": "queue"})
    assert "## QUEUE" in out
    assert "## HANDOFF" not in out
    assert "## MEMORIES" not in out
    assert "## ROSTER" not in out


def test_rehydrate_default_includes_everything(M):
    out = M._handle_rehydrate({"task": "x"})
    for bloco in ("## QUEUE", "## HANDOFF", "## MEMORIES", "## LESSONS", "## RAG", "## ROSTER"):
        assert bloco in out


def test_rehydrate_roster_shows_lanes(M):
    out = M._handle_rehydrate({"task": "x", "include": "roster"})
    assert "nixos-ai" in out and "lane=" in out


def test_tool_is_registered(M):
    nomes = [t["name"] for t in M.JARVIS_TOOLS]
    assert "rehydrate" in nomes
    schema = next(t for t in M.JARVIS_TOOLS if t["name"] == "rehydrate")
    assert schema["inputSchema"]["required"] == ["task"]
    desc = schema["description"].lower()
    assert "rehydrate" in desc and "call it first" in desc
    # Everything the model reads is English (owner rule): a pt-BR tool
    # description is a rule the local small models cannot read.
    assert "primeiro" not in desc and "chamada" not in desc


def test_rehydrate_loop_breaker_blocks_after_the_budget(M, monkeypatch):
    """Orçamento de resgates completos por janela (medido: 293k tokens no loop)."""
    monkeypatch.setenv("JARVIS_REHYDRATE_COOLDOWN_S", "120")
    monkeypatch.setenv("JARVIS_REHYDRATE_MAX_CALLS", "2")
    M._REHYDRATE_CALLS.clear()
    M._REHYDRATE_SEEN.clear()
    # tasks distintas: o memo por pedido não dispara, o ORÇAMENTO dispara
    for i in range(2):
        assert "GUARDS" in M._handle_rehydrate({"task": f"algo {i}"})
    terceira = M._handle_rehydrate({"task": "algo 2"})
    assert "RESCUE ALREADY DONE" in terceira
    assert "window budget" in terceira
    assert len(terceira) < 400, "o ponteiro tem que ser curto (não repetir o bloco)"


def test_rehydrate_budget_allows_distinct_tasks(M, monkeypatch):
    """Resgates LEGÍTIMOS distintos (tasks diferentes) não são bloqueados."""
    monkeypatch.setenv("JARVIS_REHYDRATE_COOLDOWN_S", "120")
    monkeypatch.setenv("JARVIS_REHYDRATE_MAX_CALLS", "3")
    M._REHYDRATE_CALLS.clear()
    M._REHYDRATE_SEEN.clear()
    for i in range(3):
        assert "GUARDS" in M._handle_rehydrate({"task": f"tarefa {i}"})
    assert "RESCUE ALREADY DONE" in M._handle_rehydrate({"task": "tarefa 3"})


def test_rehydrate_same_task_is_cheap_on_repeat(M, monkeypatch):
    """Mesmo pedido de novo = ponteiro curto (não devolve o bloco inteiro)."""
    monkeypatch.setenv("JARVIS_REHYDRATE_COOLDOWN_S", "120")
    monkeypatch.setenv("JARVIS_REHYDRATE_MAX_CALLS", "3")
    M._REHYDRATE_CALLS.clear()
    M._REHYDRATE_SEEN.clear()
    assert "GUARDS" in M._handle_rehydrate({"task": "mesma coisa"})
    segunda = M._handle_rehydrate({"task": "mesma coisa"})
    assert "ALREADY DONE FOR THIS REQUEST" in segunda
    assert len(segunda) < 400


def test_rehydrate_cooldown_env_is_honored(M, monkeypatch):
    monkeypatch.setenv("JARVIS_REHYDRATE_COOLDOWN_S", "0")
    M._REHYDRATE_CALLS.clear()
    M._REHYDRATE_SEEN.clear()
    a = M._handle_rehydrate({"task": "x"})
    b = M._handle_rehydrate({"task": "x"})
    assert "GUARDS" in a and "GUARDS" in b
