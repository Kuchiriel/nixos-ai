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
