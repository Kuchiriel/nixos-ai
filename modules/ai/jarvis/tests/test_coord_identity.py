"""Identidade do chamador no coord (08/11) — a raiz do "whoami = Arara".

Medido: o opencode injeta OPENCODE_SESSION_ID no bash tool, mas NÃO no MCP
server; o MCP recebe OPENCODE_PID (o processo opencode pai, com `-s ses_...`
no argv). O `agent_id()` antigo só olhava COORD_AGENT/default → todo MCP caía
em `jarvis@<host>` e o whoami/pending/set_context iam para o primeiro agente
com esse nome (Arara). O roster chegou a ter 3 agentes na mesma sessão.

Teste offline: sem roster real, sem /proc real.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def cr():
    from jarvis.core import coord_roster as module
    return module


def test_current_session_from_bash_env(cr, monkeypatch):
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_bash")
    assert cr.current_session() == "ses_bash"


def test_current_session_from_mcp_pid(cr, monkeypatch):
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    monkeypatch.setenv("OPENCODE_PID", "4242")
    monkeypatch.setattr(cr, "_session_from_cmdline", lambda pid: "ses_mcp")
    assert cr.current_session() == "ses_mcp"


def test_current_session_empty_without_signals(cr, monkeypatch):
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    monkeypatch.delenv("OPENCODE_PID", raising=False)
    assert cr.current_session() == ""


def test_agent_id_resolves_by_session(cr, monkeypatch):
    monkeypatch.delenv("COORD_AGENT", raising=False)
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_cervo")
    monkeypatch.setattr(cr, "roster_agents", lambda: [
        {"name": "arara", "session": "ses_arara", "claimed_at": 99},
        {"name": "cervo", "session": "ses_cervo", "claimed_at": 1},
    ])
    assert cr.agent_id() == "cervo"


def test_agent_id_prefers_most_recent_claim_in_shared_window(cr, monkeypatch):
    """Uma janela pode ter histórico de vários agentes: vale o claim novo."""
    monkeypatch.delenv("COORD_AGENT", raising=False)
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_shared")
    monkeypatch.setattr(cr, "roster_agents", lambda: [
        {"name": "antigo", "session": "ses_shared", "claimed_at": 10},
        {"name": "atual", "session": "ses_shared", "claimed_at": 20},
    ])
    assert cr.agent_id() == "atual"


def test_agent_id_falls_back_to_host(cr, monkeypatch):
    monkeypatch.delenv("COORD_AGENT", raising=False)
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    monkeypatch.delenv("OPENCODE_PID", raising=False)
    monkeypatch.setattr(cr, "roster_agents", lambda: [])
    assert cr.agent_id().startswith("jarvis@")


def test_coord_agent_override_wins(cr, monkeypatch):
    monkeypatch.setenv("COORD_AGENT", "explicito")
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_x")
    assert cr.agent_id() == "explicito"
