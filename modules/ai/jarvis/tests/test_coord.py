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
    # o cache do bus e global no modulo: cada teste comeca com o cache limpo
    module.invalidate_cache()
    module._CACHE.update({"state": {}, "issue": None, "updated_at": "",
                           "payloads": []})
    yield module
    module.invalidate_cache()


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


class TestCacheAndPending:
    """Cache (o watcher faz polling: sem cache estoura o rate limit do GitHub)
    e `pending` (só o que me cabe) — o contrato acordado com o Urubu."""

    def _fake_bus(self, coord, monkeypatch, payloads):
        calls = {"n": 0}

        def fake_gh_json(*args, **kwargs):
            if args[:2] == ("issue", "list"):
                return [{"number": 12, "title": "COORD", "url": "u"}]
            if len(args) >= 2 and args[0] == "api" and "comments?" in args[1]:
                calls["n"] += 1
                return [{"body": "```coord-json\n" + json.dumps(p) + "\n```"}
                        for p in payloads]
            if args[:2] == ("pr", "list"):
                return []
            raise AssertionError(f"gh_json inesperado: {args}")

        def fake_gh(*args, **kwargs):
            if args[:2] == ("issue", "list"):
                return json.dumps([{"number": 12}])
            if args[0] == "api":
                return "{}"
            raise AssertionError(f"gh inesperado: {args}")

        monkeypatch.setattr(coord, "gh", fake_gh)
        monkeypatch.setattr(coord, "gh_json", fake_gh_json)
        return calls

    def test_second_read_does_not_hit_github(self, coord, monkeypatch):
        calls = self._fake_bus(coord, monkeypatch, [_payload("a1")])
        coord.invalidate_cache()
        coord.bus_payloads()
        coord.bus_payloads()
        coord.bus_payloads()
        assert calls["n"] == 1, "cache nao evitou as chamadas ao GitHub"

    def test_force_bypasses_cache(self, coord, monkeypatch):
        calls = self._fake_bus(coord, monkeypatch, [_payload("a1")])
        coord.invalidate_cache()
        coord.bus_payloads()
        coord.bus_payloads(force=True)
        assert calls["n"] == 2

    def test_pending_returns_only_addressed(self, coord, monkeypatch):
        self._fake_bus(coord, monkeypatch, [
            _payload("a1", kind="msg", ts="2026-11-05T10:00:00Z") | {"to": "Onca"},
            _payload("b2", kind="msg", ts="2026-11-05T10:01:00Z") | {"to": "Outro"},
            _payload("c3", kind="claim", files=["docs/x.md"], ts="2026-11-05T10:02:00Z"),
        ])
        coord.invalidate_cache()
        items = coord.pending(agent="Onca", codename="Onca", lane="mt5",
                              files="backtest/*")
        assert len(items) == 1
        assert items[0]["agent"] == "a1"

    def test_pending_includes_overlapping_claim(self, coord, monkeypatch):
        self._fake_bus(coord, monkeypatch, [
            _payload("c3", kind="claim", files=["backtest/make_ini.py"],
                     ts="2026-11-05T10:02:00Z"),
        ])
        coord.invalidate_cache()
        items = coord.pending(agent="Onca", files="backtest/*")
        assert len(items) == 1
        assert items[0]["agent"] == "c3"

    def test_pending_since_filters_old(self, coord, monkeypatch):
        self._fake_bus(coord, monkeypatch, [
            _payload("a1", kind="msg", ts="2026-11-05T10:00:00Z") | {"to": "Onca"},
            _payload("b2", kind="msg", ts="2026-11-05T12:00:00Z") | {"to": "Onca"},
        ])
        coord.invalidate_cache()
        items = coord.pending(agent="Onca", since="2026-11-05T11:00:00Z")
        assert len(items) == 1
        assert items[0]["agent"] == "b2"

    def test_post_carries_to_and_invalidates_cache(self, coord, monkeypatch):
        posted = []

        def fake_gh(*args, **kwargs):
            if args[:2] == ("issue", "list"):
                return json.dumps([{"number": 12}])
            if args[0] == "api":
                body = args[args.index("-f") + 1].split("=", 1)[1]
                posted.append(body)
                return "{}"
            raise AssertionError(args)

        monkeypatch.setattr(coord, "gh", fake_gh)
        coord.invalidate_cache()
        coord.post(kind="msg", agent="Onca", to="Urubu", note="olá")
        payload = coord.parse_payloads([posted[0]])[0]
        assert payload["to"] == "Urubu"
        assert payload["kind"] == "msg"
        assert payload["agent"] == "Onca"


class TestCrossMachineAndCacheCoherence:
    """Bugs achados pelo Urubu em 05/11 (05/11 - 21:51):

    1. `bus_state` e `bus_payloads` mexiam no mesmo `_CACHE["at"]` com
       campos diferentes: uma leitura "envelhecia" o carimbo da outra e a
       lista de payloads podia ficar presa (msg nova nunca aparecia ⇒ o
       watcher ficava cego).
    2. `coord_msg` validava o destinatário contra o ROSTER LOCAL, rejeitando
       quem só existe no bus (outra máquina) — que é o caso cross-machine que
       o bus existe para resolver.
    """

    def test_state_and_payloads_are_coherent(self, coord, monkeypatch):
        """Uma leitura alimenta os dois: o payload novo tem que aparecer."""
        payloads = [_payload("a1", ts="2026-11-05T10:00:00Z")]
        calls = {"n": 0}

        def fake_gh_json(*args, **kwargs):
            if args[:2] == ("issue", "list"):
                return [{"number": 12}]
            if len(args) >= 2 and args[0] == "api" and "comments?" in args[1]:
                calls["n"] += 1
                return [{"body": "```coord-json\n" + json.dumps(p) + "\n```"}
                        for p in payloads]
            if args[:2] == ("pr", "list"):
                return []
            raise AssertionError(args)

        monkeypatch.setattr(coord, "gh_json", fake_gh_json)
        monkeypatch.setattr(coord, "gh", lambda *a, **k: "{}")
        coord.invalidate_cache()
        coord.bus_state()
        assert len(coord.bus_payloads()) == 1
        # chega payload novo no bus
        payloads.append(_payload("b2", ts="2026-11-05T11:00:00Z"))
        coord.invalidate_cache()
        coord.bus_state()
        got = coord.bus_payloads()
        assert len(got) == 2, "payload novo sumiu: state e payloads dessincronizados"

    def test_msg_to_agent_not_in_local_roster(self, coord, monkeypatch):
        """coord_msg aceita quem só existe no bus (outra máquina)."""
        from jarvis.core import coord_roster
        posted = {}

        def fake_send(to, message, agent=None, lane=""):
            posted["to"] = to
            posted["message"] = message
            return "coord: publicado"

        monkeypatch.setattr(coord_roster, "roster_agents", lambda: [
            {"name": "Onca", "codename": "Onca", "lane": "nixos-ai/coord-mcp"},
        ])
        monkeypatch.setattr(coord, "send", fake_send)
        out = coord_roster.send_message("crouton-alpha", "oi do celular")
        assert posted["to"] == "crouton-alpha"
        assert "bus" in out


class TestAliasAddressing:
    """06/11/2026: o bus endereca por codinome, mas o roster tambem tem NOME.

    Quem escreve manda pelo nome natural ('opencode-matheus'); o watcher
    resolve o codinome ('Onca') e comparava so com ele => a mensagem nao
    chegava em ninguem (o dono: 'ele mandou pra todo mundo menos vc').
    """

    def test_pending_accepts_roster_name(self, coord, monkeypatch):
        from jarvis.core import coord_roster
        monkeypatch.setattr(coord_roster, "roster_agents", lambda: [
            {"name": "opencode-matheus", "codename": "Onca", "lane": "infra"},
        ])
        coord.invalidate_cache()
        payloads = [{"kind": "msg", "agent": "Cervo", "to": "opencode-matheus",
                     "lane": "infra", "ts": "2026-11-06T10:00:00Z",
                     "note": "pelo nome do roster"}]
        monkeypatch.setattr(coord, "bus_payloads", lambda force=False: payloads)
        items = coord.pending(codename="Onca", agent="opencode-matheus")
        assert len(items) == 1, "msg endereçada pelo NOME do roster nao chegou"

    def test_pending_accepts_codename(self, coord, monkeypatch):
        from jarvis.core import coord_roster
        monkeypatch.setattr(coord_roster, "roster_agents", lambda: [
            {"name": "opencode-matheus", "codename": "Onca", "lane": "infra"},
        ])
        coord.invalidate_cache()
        payloads = [{"kind": "msg", "agent": "Cervo", "to": "Onca",
                     "lane": "infra", "ts": "2026-11-06T10:00:00Z",
                     "note": "pelo codinome"}]
        monkeypatch.setattr(coord, "bus_payloads", lambda force=False: payloads)
        items = coord.pending(codename="Onca")
        assert len(items) == 1
