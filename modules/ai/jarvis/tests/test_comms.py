"""Testes da camada de comunicação unificada (comms) e da persona ativa.

O QUE ESTES TESTES PROVAM (e por que existem):
  - o quadro junta bus x roster por ALIAS (medido 07/11: 13 nomes para 6
    agentes — "jarvis@nitro-v15", "Cervo", "Arara", "sweep-2026-11" são o
    mesmo agente; sem o join o quadro mostra "sem claim" para todo mundo);
  - a entrega vai pelo caminho canônico (bus + wake) e o fallback direto
    na API V2 monta o payload certo (NOTA = delivery=queue, PEDIDO = delivery=steer);
  - a persona ativa persiste e volta (o /mood do Telegram depende disso).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.core import comms, persona


# ── quadro ───────────────────────────────────────────────────────────────
def test_board_joins_claim_by_alias(monkeypatch):
    """A claim no bus (pelo alias) aparece no quadro do agente."""
    claim = {"kind": "claim", "agent": "Arara", "to": "", "intent": "mexer no X"}
    monkeypatch.setattr(
        "jarvis.core.coord.bus_state", lambda *a, **k: ({"Arara": claim}, 12)
    )
    monkeypatch.setattr("jarvis.core.coord.bus_updated_at", lambda: "2026-11-07T00:00:00Z")
    monkeypatch.setattr(
        comms,
        "live_agents",
        lambda *a, **k: [
            {
                "name": "jarvis@nitro-v15",
                "codename": "Arara",
                "aliases": ["Cervo", "sweep-2026-11"],
                "lane": "redteam/matrix",
                "session": "ses_x",
                "busy": False,
            }
        ],
    )
    b = comms.board()
    assert b["claims"], "o board não viu a claim"
    txt = comms.board_text()
    assert "mexer no X" in txt, txt
    assert "Arara" in txt, txt


def test_board_text_lista_agentes_sem_claim(monkeypatch):
    monkeypatch.setattr(
        "jarvis.core.coord.bus_state", lambda *a, **k: ({}, None)
    )
    monkeypatch.setattr("jarvis.core.coord.bus_updated_at", lambda: "")
    monkeypatch.setattr(
        comms,
        "live_agents",
        lambda *a, **k: [
            {"name": "X", "codename": "", "aliases": [], "lane": "l", "session": "s", "busy": False}
        ],
    )
    txt = comms.board_text()
    assert "QUADRO DOS AGENTES" in txt
    assert "sem claim" in txt


# ── entrega ──────────────────────────────────────────────────────────────
def test_deliver_fallback_nota_usa_queue(monkeypatch):
    """Sem o roster, a NOTA entra na fila V2 (delivery=queue)."""
    monkeypatch.setattr(
        "jarvis.core.coord_roster.send_message",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sem roster")),
    )
    monkeypatch.setattr(
        comms,
        "find_agent",
        lambda name: {"name": "X", "session": "ses_abc"},
    )
    seen: dict = {}

    def fake_post(path, body, timeout=25):
        seen["path"] = path
        seen["body"] = body
        return True, "200 ok"

    monkeypatch.setattr(comms, "_post", fake_post)
    ok, detail = comms.deliver("X", "oi")
    assert ok, detail
    assert seen["path"] == "/session/ses_abc/prompt"
    assert seen["body"]["delivery"] == "queue"
    assert seen["body"]["text"] == "oi"


def test_deliver_fallback_pedido_usa_steer(monkeypatch):
    monkeypatch.setattr(
        "jarvis.core.coord_roster.send_message",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sem roster")),
    )
    monkeypatch.setattr(
        comms,
        "find_agent",
        lambda name: {"name": "X", "session": "ses_abc"},
    )
    seen: dict = {}

    def fake_post(path, body, timeout=25):
        seen["path"] = path
        seen["body"] = body
        return True, "200 ok"

    monkeypatch.setattr(comms, "_post", fake_post)
    ok, _ = comms.deliver("X", "roda", request=True)
    assert ok
    assert seen["path"] == "/session/ses_abc/prompt"
    assert seen["body"]["delivery"] == "steer"


def test_deliver_usa_caminho_canonico(monkeypatch):
    """O caminho normal é o coord_roster.send_message (bus + wake)."""
    calls: list = []

    def fake_send(target, message, note=True):
        calls.append((target, message, note))
        return "publicado no bus"

    monkeypatch.setattr("jarvis.core.coord_roster.send_message", fake_send)
    ok, detail = comms.deliver("Arara", "oi", request=False)
    assert ok
    assert calls and calls[0][0] == "Arara"
    assert calls[0][2] is True  # nota
    assert "bus" in detail


def test_deliver_sem_roster_falha_explicito(monkeypatch):
    monkeypatch.setattr(
        "jarvis.core.coord_roster.send_message",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")),
    )
    monkeypatch.setattr(comms, "find_agent", lambda name: None)
    ok, detail = comms.deliver("ninguem", "oi")
    assert not ok
    assert "roster" in detail


# ── persona ativa (MBTI) ─────────────────────────────────────────────────
def test_persona_ativa_persiste(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    monkeypatch.delenv(persona.ACTIVE_PERSONA_ENV, raising=False)
    p = persona.set_active_persona("marketing")
    assert p is not None
    data = json.loads((tmp_path / "persona.json").read_text(encoding="utf-8"))
    assert data["id"] == "marketing"
    assert data["mbti"], "a persona ativa tem que expor o MBTI"
    assert "MBTI" in data["system_prompt_additions"]
    again = persona.active_persona()
    assert again is not None and again.id == "marketing"
    assert persona.clear_active_persona() is True
    assert persona.active_persona() is None


def test_mbti_index_tem_catalogo():
    idx = persona.mbti_index()
    assert len(idx) >= 5
    assert any(m for _pid, _name, m in idx), "nenhuma persona tem MBTI"
