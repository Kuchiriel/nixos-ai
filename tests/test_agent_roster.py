"""Testes do roster de agentes (scripts/agent-roster.py).

Cobre o contrato que a pesquisa de mercado impôs:
- claim é exclusivo por nome enquanto a janela está viva;
- dois agentes com ARQUIVOS sobrepostos são recusados (Anthropic:
  fronteiras explícitas → sem duplicação de trabalho);
- lane igual com arquivos disjuntos é permitido (2 janelas, 1 assunto);
- entrada sem janela viva = stale/dead (Claude Agent Teams: teammate que
  não existe mais não pode receber task);
- tasks têm ciclo de vida (pending → working → done).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "agent-roster.py"


@pytest.fixture()
def roster(tmp_path, monkeypatch):
    """Importa o script com AGENTS_ROSTER apontando p/ arquivo temporário."""
    path = tmp_path / "roster.json"
    monkeypatch.setenv("AGENTS_ROSTER", str(path))
    spec = importlib.util.spec_from_file_location("agent_roster", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # janelas fake: address -> vivo?
    fake = [
        {"address": "0xaaa", "pid": 111, "title": "OpenCode"},
        {"address": "0xbbb", "pid": 222, "title": "OpenCode"},
    ]
    monkeypatch.setattr(mod, "agent_windows", lambda: [dict(w) for w in fake])
    monkeypatch.setattr(mod, "own_window",
                        lambda windows=None: {"address": "0xaaa", "pid": 111,
                                              "title": "OpenCode"})
    mod._FAKE_WINDOWS = fake
    return mod


def _claim(mod, **kw):
    args = mod.argparse.Namespace(
        name=kw.get("name", "a"), lane=kw.get("lane", "lane/a"),
        repo=kw.get("repo", "repo-a"), files=kw.get("files", []),
        note=kw.get("note", ""), force=kw.get("force", False))
    return mod.cmd_claim(args)


def test_claim_registers_agent(roster):
    assert _claim(roster, name="mt5", lane="mt5/opt", repo="mt5",
                  files=["mql/**"]) == 0
    data = roster.load()
    assert [a["name"] for a in data["agents"]] == ["mt5"]
    assert data["agents"][0]["window"] == "0xaaa"
    assert data["agents"][0]["files"] == ["mql/**"]


def test_claim_same_name_twice_refused_while_live(roster):
    assert _claim(roster, name="mt5", files=["mql/**"]) == 0
    assert _claim(roster, name="mt5", files=["other/**"]) == 3


def test_claim_overlapping_files_refused(roster):
    assert _claim(roster, name="mt5", files=["mql/**"]) == 0
    # outro agente, MESMOS arquivos → colisão (trabalho duplicado)
    assert _claim(roster, name="outro", files=["mql/**"]) == 4


def test_claim_overlap_can_be_forced(roster):
    assert _claim(roster, name="mt5", files=["mql/**"]) == 0
    assert _claim(roster, name="outro", files=["mql/**"], force=True) == 0


def test_claim_same_lane_disjoint_files_allowed(roster):
    """2 janelas no MESMO assunto: permitido se não dividem arquivos."""
    assert _claim(roster, name="a", lane="topico/x", files=["a/**"]) == 0
    assert _claim(roster, name="b", lane="topico/x", files=["b/**"]) == 0
    assert len(roster.load()["agents"]) == 2


def test_release_removes_entry(roster):
    _claim(roster, name="mt5")
    assert roster.cmd_release(roster.argparse.Namespace(name="mt5")) == 0
    assert roster.load()["agents"] == []
    assert roster.cmd_release(roster.argparse.Namespace(name="mt5")) == 1


def test_list_marks_agent_without_window_as_dead(roster, capsys):
    _claim(roster, name="mt5")
    capsys.readouterr()  # descarta a saída do claim
    # a janela do roster sumiu (o agente fechou)
    roster.agent_windows = lambda: []
    assert roster.cmd_list(roster.argparse.Namespace(json=True)) == 0
    import json as _json
    rows = _json.loads(capsys.readouterr().out)
    assert rows["agents"][0]["state"] == "dead"


def test_resolve_reports_live_and_dead(roster, capsys):
    _claim(roster, name="mt5")
    assert roster.cmd_resolve(roster.argparse.Namespace(name="mt5")) == 0
    out = capsys.readouterr().out
    assert '"live": true' in out
    roster.agent_windows = lambda: []
    assert roster.cmd_resolve(roster.argparse.Namespace(name="mt5")) == 1
    out = capsys.readouterr().out
    assert '"live": false' in out


def test_resolve_unknown_name(roster, capsys):
    assert roster.cmd_resolve(roster.argparse.Namespace(name="fantasma")) == 1
    assert "nome desconhecido" in capsys.readouterr().out


def test_task_lifecycle(roster, capsys):
    args = roster.argparse.Namespace(
        title="medir DD v3.12", owner="mt5", lane="mt5/opt", files=[],
        note="")
    assert roster.cmd_task_add(args) == 0
    data = roster.load()
    assert data["tasks"][0]["id"] == "t-1"
    assert data["tasks"][0]["status"] == "working"
    assert roster.cmd_task_close(roster.argparse.Namespace(id="t-1")) == 0
    assert roster.load()["tasks"][0]["status"] == "done"
    assert roster.cmd_task_close(roster.argparse.Namespace(id="t-9")) == 1


def test_events_filter_scopes_commits_to_the_owner(roster, capsys, monkeypatch):
    """Commit do repo X só acorda o agente dono do repo X (lane-aware wake)."""
    _claim(roster, name="dono-mt5", lane="mt5/backtest", repo="mt5",
           files=["mql/**"])
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(
        "mudou: commit:mt5 abc123\nmudou: commit:nixos-ai def456\n"
        "mudou: queue 999\n"))
    assert roster.cmd_events(roster.argparse.Namespace(window="0xaaa")) == 0
    out = capsys.readouterr().out
    assert "commit:mt5" in out
    assert "commit:nixos-ai" not in out
    assert "queue 999" in out          # evento global acorda todo mundo


def test_events_filter_drops_foreign_repo(roster, capsys, monkeypatch):
    _claim(roster, name="dono-mt5", lane="mt5/backtest", repo="mt5",
           files=["mql/**"])
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(
        "mudou: commit:nixos-ai def456\n"))
    assert roster.cmd_events(roster.argparse.Namespace(window="0xaaa")) == 0
    assert capsys.readouterr().out.strip() == ""


def test_events_without_roster_is_legacy_global(roster, capsys, monkeypatch):
    """Sem claim: o filtro não existe (legado) — nada se perde."""
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(
        "mudou: commit:nixos-ai def456\n"))
    assert roster.cmd_events(roster.argparse.Namespace(window="0xaaa")) == 0
    assert "commit:nixos-ai" in capsys.readouterr().out


def test_overlaps_detects_glob_prefix():
    mod = roster_module()
    # glob vs arquivo concreto → reporta o arquivo concreto (mensagem útil)
    assert mod._overlaps(["mql/**"], ["mql/Expert/Trend.mq5"]) == ["mql/Expert/Trend.mq5"]
    assert mod._overlaps(["a/b/**"], ["a/c/**"]) == []
    assert mod._overlaps(["a/b"], ["a/b/c"]) == ["a/b/c"]
    assert mod._overlaps(["mql/**"], ["mql/**"]) == ["mql/**"]


def roster_module():
    spec = importlib.util.spec_from_file_location("agent_roster_static", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    os.environ.setdefault("AGENTS_ROSTER", "/tmp/opencode/roster-static.json")
    spec.loader.exec_module(mod)
    return mod
