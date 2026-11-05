"""Testes do bus de coordenação entre agentes (`jarvis.core.coord`).

Sem rede: o `gh` é mockado. O que é testado é o PROTOCOLO (parse do
coord-json, estado por agente, colisão de escopo, TTL) — a parte que precisa
ser igual em qualquer implementação (Node no mt5, Python no MCP).

Referência: arXiv 2605.18747 — "consistent shared state across multiple
agents" é desafio em aberto; o bus transforma isso em estado compartilhado
+ artefato estruturado (a claim) + verificação mecânica (colisão).
"""

import json
import time

import pytest


@pytest.fixture
def coord():
    from jarvis.core import coord as module
    return module


def _payload(agent, kind="claim", files=(), ts=None, lane="infra", intent="x"):
    return {
        "kind": kind,
        "agent": agent,
        "lane": lane,
        "files": list(files),
        "intent": intent,
        "note": "",
        "pr": None,
        "head": "",
        "ts": ts or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _comment(payload):
    body = "**claim** de `x`\n\n```coord-json\n" + json.dumps(payload) + "\n```"
    return {"body": body}


class TestParse:
    def test_extracts_coord_json(self, coord):
        payload = _payload("a1", files=["backtest/*"])
        bodies = [_comment(payload)["body"], "sem fence", "```coord-json\nnao é json\n```"]
        out = coord.parse_payloads(bodies)
        assert len(out) == 1
        assert out[0]["agent"] == "a1"
        assert out[0]["files"] == ["backtest/*"]

    def test_ignores_malformed(self, coord):
        assert coord.parse_payloads(["```coord-json\n{nao fecha\n```"]) == []


class TestState:
    def test_latest_message_per_agent_wins(self, coord):
        older = _payload("a1", ts="2026-11-05T10:00:00Z", intent="antigo")
        newer = _payload("a1", ts="2026-11-05T11:00:00Z", intent="novo")
        state = coord.current_state([older, newer])
        assert list(state) == ["a1"]
        assert state["a1"]["intent"] == "novo"

    def test_done_is_not_active(self, coord):
        state = coord.current_state([_payload("a1", kind="done")])
        assert coord.active_claims(state) == {}

    def test_claim_older_than_ttl_is_dead(self, coord, monkeypatch):
        monkeypatch.setenv("COORD_TTL_H", "1")
        old = _payload("a1", ts="2026-11-05T00:00:00Z")
        state = coord.current_state([old])
        assert coord.active_claims(state) == {}


class TestOverlap:
    @pytest.mark.parametrize("a,b", [
        ("backtest/*", "backtest/make_ini.py"),
        ("backtest/make_ini.py", "backtest/make_ini.py"),
        ("backtest", "backtest/make_ini.py"),
        ("AGENTS.md", "AGENTS.md"),
        ("tools/*.mjs", "tools/coord.mjs"),
    ])
    def test_overlaps(self, coord, a, b):
        assert coord.overlaps(a, b) is True

    @pytest.mark.parametrize("a,b", [
        ("backtest/*", "AGENTS.md"),
        ("modules/ai/jarvis/*", "modules/ai/nixos/*"),
        ("a/b", "c/d"),
    ])
    def test_no_overlap(self, coord, a, b):
        assert coord.overlaps(a, b) is False

    def test_glob_covers_subtree(self, coord):
        """`dir/*` cobre `dir/sub/arquivo.py` — colisão tem que aparecer."""
        assert coord.overlaps(
            "modules/ai/jarvis/*",
            "modules/ai/jarvis/src/jarvis/core/laya_classifier.py",
        ) is True



class TestCollisions:
    def test_detects_scope_collision(self, coord):
        state = coord.current_state([
            _payload("a1", files=["backtest/*"]),
            _payload("b2", files=["backtest/make_ini.py"]),
        ])
        found = coord.collisions(state)
        assert len(found) == 1
        assert {found[0]["a"], found[0]["b"]} == {"a1", "b2"}

    def test_disjoint_scopes_do_not_collide(self, coord):
        state = coord.current_state([
            _payload("a1", files=["backtest/*"]),
            _payload("b2", files=["AGENTS.md"]),
        ])
        assert coord.collisions(state) == []


class TestBusWithFakeGh:
    """post/read/check contra um `gh` fake — valida o formato do protocolo."""

    def _install_fake_gh(self, coord, monkeypatch, comments=None):
        comments = list(comments or [])
        posted: list[dict] = []

        def fake_gh(*args, **kwargs):
            if args[:2] == ("issue", "list"):
                return json.dumps([{"number": 12, "title": "COORD", "url": "u"}])
            if args[:2] == ("api", "repos/Kuchiriel/mt5/issues/12/comments"):
                if "-f" in args:
                    body = args[args.index("-f") + 1].split("=", 1)[1]
                    posted.append({"body": body})
                    comments.append({"body": body})
                return "{}"
            raise AssertionError(f"gh call inesperado: {args}")

        def fake_gh_json(*args, **kwargs):
            if args[:2] == ("issue", "list"):
                return [{"number": 12, "title": "COORD", "url": "u"}]
            if len(args) >= 2 and args[0] == "api" and "comments?" in args[1]:
                return [{"body": c["body"]} for c in comments]
            if args[:2] == ("pr", "list"):
                return []
            raise AssertionError(f"gh_json call inesperado: {args}")


        monkeypatch.setattr(coord, "gh", fake_gh)
        monkeypatch.setattr(coord, "gh_json", fake_gh_json)
        monkeypatch.setenv("COORD_REPO", "Kuchiriel/mt5")
        monkeypatch.setenv("COORD_LABEL", "coord")
        return posted

    def test_post_writes_coord_json_comment(self, coord, monkeypatch):
        posted = self._install_fake_gh(coord, monkeypatch)
        out = coord.post(kind="claim", agent="a1", lane="infra",
                         files="backtest/*,AGENTS.md", intent="reconciliar", pr=13)
        assert "a1" in out
        assert len(posted) == 1
        assert "```coord-json" in posted[0]["body"]
        payload = coord.parse_payloads([posted[0]["body"]])[0]
        assert payload["agent"] == "a1"
        assert payload["files"] == ["backtest/*", "AGENTS.md"]
        assert payload["pr"] == 13

    def test_post_rejects_unknown_kind(self, coord, monkeypatch):
        self._install_fake_gh(coord, monkeypatch)
        with pytest.raises(ValueError):
            coord.post(kind="banana")

    def test_read_lists_agents_and_collisions(self, coord, monkeypatch):
        self._install_fake_gh(coord, monkeypatch, comments=[
            _comment(_payload("a1", files=["backtest/*"])),
            _comment(_payload("b2", files=["backtest/make_ini.py"])),
        ])
        out = coord.read()
        assert "a1" in out and "b2" in out
        assert "colis" in out.lower()

    def test_check_reports_collision(self, coord, monkeypatch):
        self._install_fake_gh(coord, monkeypatch, comments=[
            _comment(_payload("b2", files=["backtest/make_ini.py"])),
        ])
        out = coord.check(agent="a1", files="backtest/*")
        assert "colisão de claim" in out.lower()
        assert "b2" in out

    def test_check_clean_scope(self, coord, monkeypatch):
        self._install_fake_gh(coord, monkeypatch, comments=[
            _comment(_payload("b2", files=["AGENTS.md"])),
        ])
        out = coord.check(agent="a1", files="backtest/*")
        assert "colisão de claim" not in out.lower()
