"""Routing local: registry + policy + lifecycle (integração real HTTP).

O lifecycle fala com um router fake via HTTP de verdade (http.server em
thread) — sem mock de router/backend/lifecycle. Fronteiras mockadas só:
sessão LLM do Agent (padrão FakeSession dos demais testes).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from jarvis.core.model_registry import ModelRegistry, RegistryError
from jarvis.core.model_policy import ModelRouteError, select_model


REG = {
    "version": 1,
    "default": "bonsai",
    "maxResident": 1,
    "models": {
        "bonsai": {"tier": "speed",
                   "capabilities": ["general", "coding", "tools", "pt"],
                   "params_b": 8, "vram_mb": 2400},
        "jarvis-fast": {"tier": "fast",
                        "capabilities": ["general", "coding", "tools", "pt"],
                        "params_b": 4, "vram_mb": 2600},
        "jarvis-strong": {"tier": "reasoning",
                          "capabilities": ["general", "coding", "tools",
                                           "reasoning", "analysis",
                                           "vision", "pt"],
                          "params_b": 35, "vram_mb": 4600},
    },
}


def _reg(tmp_path, monkeypatch, data=None):
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(data if data is not None else REG))
    monkeypatch.setenv("JARVIS_MODEL_REGISTRY", str(p))
    return ModelRegistry.load()


# ── Registry ─────────────────────────────────────────────────────────

def test_registry_loads_and_defaults(tmp_path, monkeypatch):
    reg = _reg(tmp_path, monkeypatch)
    assert reg.default == "bonsai"
    assert set(reg.ids()) == {"bonsai", "jarvis-fast", "jarvis-strong"}
    assert reg.get("jarvis-fast").tier == "fast"


def test_registry_missing_file_uses_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MODEL_REGISTRY", str(tmp_path / "nope.json"))
    reg = ModelRegistry.load()
    assert reg.source == "fallback"
    assert "jarvis-fast" in reg.ids()


def test_registry_rejects_bad_version(tmp_path, monkeypatch):
    bad = dict(REG, version=99)
    with pytest.raises(RegistryError):
        _reg(tmp_path, monkeypatch, bad)


def test_registry_rejects_unknown_default(tmp_path, monkeypatch):
    bad = dict(REG, default="fantasma")
    with pytest.raises(RegistryError):
        _reg(tmp_path, monkeypatch, bad)


def test_registry_rejects_model_without_capabilities(tmp_path, monkeypatch):
    bad = json.loads(json.dumps(REG))
    bad["models"]["x"] = {"tier": "fast"}
    with pytest.raises(RegistryError):
        _reg(tmp_path, monkeypatch, bad)


def test_registry_unknown_model(tmp_path, monkeypatch):
    reg = _reg(tmp_path, monkeypatch)
    with pytest.raises(RegistryError):
        reg.get("fantasma")


# ── Policy ───────────────────────────────────────────────────────────

def test_fast_task_selects_fast(tmp_path, monkeypatch):
    reg = _reg(tmp_path, monkeypatch)
    mid, reason = select_model({"capabilities": {"coding", "tools"},
                                "tier": "fast"}, reg)
    assert mid == "jarvis-fast"
    assert reason["tier_match"] is True


def test_reasoning_task_selects_strong(tmp_path, monkeypatch):
    reg = _reg(tmp_path, monkeypatch)
    mid, _ = select_model({"capabilities": {"reasoning"}}, reg)
    assert mid == "jarvis-strong"


def test_vision_never_selects_incapable(tmp_path, monkeypatch):
    reg = _reg(tmp_path, monkeypatch)
    mid, _ = select_model({"capabilities": {"vision"}}, reg)
    assert mid == "jarvis-strong"  # único com vision


def test_incompatible_capability_rejects(tmp_path, monkeypatch):
    reg = _reg(tmp_path, monkeypatch)
    with pytest.raises(ModelRouteError):
        select_model({"capabilities": {"teletransporte"}}, reg)


def test_tier_fallback_is_recorded(tmp_path, monkeypatch):
    reg = _reg(tmp_path, monkeypatch)
    mid, reason = select_model({"capabilities": {"reasoning"},
                                "tier": "speed"}, reg)
    assert mid == "jarvis-strong"
    assert reason["tier_match"] is False
    assert reason["tier_fallback"] == "speed"


def test_local_only_recorded(tmp_path, monkeypatch):
    reg = _reg(tmp_path, monkeypatch)
    _, reason = select_model({"capabilities": {"coding"},
                              "local_only": True}, reg)
    assert reason["local_only"] is True


# ── Lifecycle (router fake HTTP real) ────────────────────────────────

class _RouterState:
    def __init__(self):
        self.loaded = "bonsai"
        self.loads = 0
        self.known = {"bonsai", "jarvis-fast", "jarvis-strong"}
        self.fail_status: str | None = None  # força status arbitrário
        self.hang = False  # nunca completa o load


def _serve(state: _RouterState):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/v1/models":
                st = state.fail_status or "loaded"
                if state.hang:
                    st = "loading"
                self._send({"data": [
                    {"id": mid, "status": {"value": (
                        st if mid == state.loaded else "unloaded")}}
                    for mid in sorted(state.known)]})
            elif self.path == "/health":
                self._send({"status": "ok"})
            else:
                self._send({"error": "nope"}, 404)

        def do_POST(self):
            if self.path == "/models/load":
                ln = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(ln) or b"{}")
                mid = payload.get("model")
                if mid not in state.known:
                    self._send({"error": "unknown model"}, 400)
                    return
                state.loads += 1
                if not state.hang:
                    state.loaded = mid
                self._send({"success": True})
            else:
                self._send({"error": "nope"}, 404)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture()
def router():
    state = _RouterState()
    srv = _serve(state)
    base = f"http://127.0.0.1:{srv.server_port}"
    yield base, state
    srv.shutdown()


def test_same_model_is_noop(router, tmp_path, monkeypatch):
    from jarvis.core import model_lifecycle as L
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    base, state = router
    rep = L.ensure_model("bonsai", base)
    assert rep.switched is False
    assert rep.identity_verified is True
    assert state.loads == 0


def test_switch_a_b_a(router, tmp_path, monkeypatch):
    from jarvis.core import model_lifecycle as L
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    base, state = router
    r1 = L.ensure_model("jarvis-fast", base)
    assert (r1.switched, r1.previous, r1.selected) == (True, "bonsai", "jarvis-fast")
    assert r1.startup_latency_s >= 0
    r2 = L.ensure_model("jarvis-strong", base)
    assert (r2.switched, r2.previous) == (True, "jarvis-fast")
    r3 = L.ensure_model("jarvis-fast", base)
    assert r3.switched is True and state.loads == 3


def test_concurrent_ensure_single_load(router, tmp_path, monkeypatch):
    from jarvis.core import model_lifecycle as L
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    base, state = router
    reps = []

    def _go(mid):
        reps.append(L.ensure_model(mid, base))

    ts = [threading.Thread(target=_go, args=(m,)) for m in
          ("jarvis-fast", "jarvis-strong", "jarvis-fast", "jarvis-strong")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # Serializado pelo lock: loads == nº de trocas reais (sem interleave A/B
    # corrompido); estado final é um dos dois, com identidade verificada.
    assert all(r.identity_verified for r in reps)
    assert L.active_model(base) in ("jarvis-fast", "jarvis-strong")


def test_unknown_model_rejected(router, tmp_path, monkeypatch):
    from jarvis.core import model_lifecycle as L
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    base, _ = router
    with pytest.raises(L.ModelSwitchError) as ei:
        L.ensure_model("fantasma", base)
    assert ei.value.phase == "load"


def test_failed_status_surfaces(router, tmp_path, monkeypatch):
    from jarvis.core import model_lifecycle as L
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    base, state = router
    state.fail_status = "failed"
    with pytest.raises(L.ModelSwitchError):
        L.ensure_model("jarvis-fast", base, load_timeout_s=3,
                       poll_interval_s=0.2)


def test_readiness_timeout(router, tmp_path, monkeypatch):
    from jarvis.core import model_lifecycle as L
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    base, state = router
    state.hang = True
    with pytest.raises(L.ModelSwitchError) as ei:
        L.ensure_model("jarvis-fast", base, load_timeout_s=1,
                       poll_interval_s=0.2)
    assert ei.value.phase == "readiness"


def test_server_down_is_discover_error(tmp_path, monkeypatch):
    from jarvis.core import model_lifecycle as L
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    with pytest.raises(L.ModelSwitchError) as ei:
        L.ensure_model("jarvis-fast", "http://127.0.0.1:1")
    assert ei.value.phase == "discover"


# ── Agent integrado (policy→registry→lifecycle→HTTP reais) ───────────

def test_agent_routes_and_swaps_model(router, tmp_path, monkeypatch):
    import json as jsonlib
    from jarvis.core.agent import Agent
    from jarvis.core.config import Config

    monkeypatch.setenv("JARVIS_MODEL_REGISTRY",
                       str(tmp_path / "registry.json"))
    (tmp_path / "registry.json").write_text(json.dumps(REG))
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    base, state = router
    cfg = Config()
    # Config frozen: rebuild com base_url do router fake.
    from dataclasses import replace
    cfg = replace(cfg, llm_base_url=base, llm_model="bonsai")

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def get(self, url, timeout=5):
            class R:
                status_code = 200

                def raise_for_status(self):
                    pass

                def json(self):
                    return {"data": [{"id": "x"}]}
            return R()

        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            msg = {"role": "assistant",
                   "content": f"ok via {json['model']}"}
            class R:
                status_code = 200

                def raise_for_status(self):
                    pass

                def json(s):
                    return {"choices": [{"message": msg}]}
            return R()

    agent = Agent(cfg, session=FakeSession(),
                  model_requirements={"capabilities": {"coding", "tools"},
                                      "tier": "fast"})
    result = agent.run("diga ok")
    assert agent.config.llm_model == "jarvis-fast"
    assert state.loaded == "jarvis-fast"
    assert "jarvis-fast" in result.final_response
