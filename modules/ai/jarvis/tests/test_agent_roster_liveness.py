"""Roster: liveness por SESSÃO (03/11, dono: "vcs acham que fechou").

O endereço da janela do Hyprland é efêmero: reabrir a janela = novo
address → o roster dava o agente por morto (e o `agent-msg.sh` recusava
a entrega: "não está vivo"). A SESSÃO (opencode -s ses_...) é a identidade
durável → é ela que decide a vida do agente.

Teste OFFLINE: sem hyprctl, sem /proc real (monkeypatch).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

def _find_upwards(*candidates: str) -> Path | None:
    """Procura um arquivo subindo a arvore (o pacote nix so leva ./jarvis)."""
    for parent in Path(__file__).resolve().parents:
        for candidate in candidates:
            path = parent / candidate
            if path.is_file():
                return path
    return None


def _load():
    path = _find_upwards("scripts/agent-roster.py")
    if path is None:
        # No sandbox do nix o pacote so leva ./jarvis -> o script nao existe:
        # o modulo inteiro e pulado (allow_module_level obrigatorio no pytest 8).
        pytest.skip("scripts/agent-roster.py nao encontrado neste checkout",
                    allow_module_level=True)
    spec = importlib.util.spec_from_file_location("agent_roster_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def roster():
    return _load()


def _win(address, session):
    return {"address": address, "pid": 42, "title": "", "session": session,
            "busy": False}


def test_alive_by_address(roster):
    entry = {"window": "0xaaa", "session": "ses_1"}
    windows = [_win("0xaaa", "ses_1")]
    assert roster.window_alive(entry, windows, {}) is True


def test_alive_by_session_after_window_reopened(roster):
    """A janela mudou de address, mas a sessão continua viva → VIVO."""
    entry = {"window": "0xantigo", "session": "ses_1"}
    windows = [_win("0xnovo", "ses_1")]
    sessions = {"ses_1": 999}
    assert roster.window_alive(entry, windows, sessions) is True


def test_dead_when_neither_matches(roster):
    entry = {"window": "0xantigo", "session": "ses_morta"}
    windows = [_win("0xnovo", "ses_outra")]
    assert roster.window_alive(entry, windows, {"ses_outra": 1}) is False


def test_dead_without_session_and_without_address(roster):
    entry = {"window": "0xantigo", "session": ""}
    assert roster.window_alive(entry, [], {}) is False


def test_window_of_session(roster):
    entry = {"session": "ses_1"}
    windows = [_win("0xaaa", "ses_1"), _win("0xbbb", "ses_2")]
    assert roster.window_of_session(entry, windows)["address"] == "0xaaa"
    assert roster.window_of_session({"session": "nope"}, windows) is None
    assert roster.window_of_session({}, windows) is None


def test_window_of_session_ignores_empty_session(roster):
    windows = [_win("0xaaa", "")]
    assert roster.window_of_session({"session": ""}, windows) is None


# ── identidade do chamador (08/11): a sessão vem do env, não do ppid ──
# Medido: o bash tool recebe OPENCODE_SESSION_ID; o MCP server recebe
# OPENCODE_PID (o app pai, com -s ses_... no argv). Sem isso, claim do MCP
# caía na primeira janela viva e 3 agentes ficaram na mesma sessão.

def test_own_window_by_session_env(roster, monkeypatch):
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_1")
    windows = [_win("0xaaa", "ses_1"), _win("0xbbb", "ses_2")]
    assert roster.own_window(windows)["address"] == "0xaaa"


def test_own_window_session_beats_ppid_walk(roster, monkeypatch):
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_2")
    windows = [_win("0xaaa", "ses_1"), _win("0xbbb", "ses_2")]
    # o ppid do pytest não casa com nenhuma janela: só a sessão importa
    assert roster.own_window(windows)["address"] == "0xbbb"


def test_own_window_from_opencode_pid(roster, monkeypatch):
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    monkeypatch.setenv("OPENCODE_PID", "4242")
    monkeypatch.setattr(roster, "_session_do_pid", lambda pid: "ses_mcp")
    windows = [_win("0xccc", "ses_mcp")]
    assert roster.own_window(windows)["address"] == "0xccc"


def test_own_window_server_side_synthesizes(roster, monkeypatch):
    """Bash filho do `opencode serve`: não há janela foot, mas há sessão."""
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_serve")
    monkeypatch.setattr(roster, "session_busy", lambda s, **k: False)
    own = roster.own_window([])
    assert own is not None
    assert own["session"] == "ses_serve"
    assert own["address"] == ""


def test_own_window_falls_back_to_ppid_without_env(roster, monkeypatch):
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    monkeypatch.delenv("OPENCODE_PID", raising=False)
    import os
    windows = [_win("0xppid", "")]
    windows[0]["pid"] = os.getppid()
    monkeypatch.setattr(roster, "_proc_map", lambda: ({}, set()))
    assert roster.own_window(windows)["address"] == "0xppid"



def test_live_sessions_includes_serve_hosted_session(roster, monkeypatch, tmp_path):
    """Sessão de `opencode serve` não tem -s no argv: quem decide é o DB.

    Medido 08/11: o claim por sessão gravava o id certo, mas o roster marcava
    `dead` porque `live_sessions()` só olhava /proc. Mesmo critério do
    watcher: part nova na janela AGENTS_DB_ALIVE (600s) = viva.
    """
    import sqlite3
    import time as _time

    db = tmp_path / "opencode.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE part (session_id TEXT, time_updated INTEGER, time_created INTEGER)")
    agora = int(_time.time() * 1000)
    con.execute("INSERT INTO part VALUES (?,?,?)", ("ses_serve", agora, agora))
    con.execute("INSERT INTO part VALUES (?,?,?)", ("ses_velha", agora - 3_600_000, agora - 3_600_000))
    con.commit()
    con.close()

    monkeypatch.setenv("AGENTS_DB_PATH", str(db))
    monkeypatch.setenv("AGENTS_DB_ALIVE", "600")
    monkeypatch.setattr(roster.os, "scandir", lambda path: [])

    sessoes = roster.live_sessions()
    assert "ses_serve" in sessoes
    assert "ses_velha" not in sessoes
