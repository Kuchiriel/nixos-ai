"""Harbor adapter — mapeamento instruction→runtime→context+ATIF (F10).

Sem harbor instalado (imports guarded) e sem LLM: FakeSession prova o
mapeamento; teste de presença prova a interface BaseAgent (name/version/
setup/run) casando com o guia custom-agents.
"""
import asyncio
import json as jsonlib

from jarvis.runtime import harbor_agent as ha


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = 0

    def get(self, url, timeout=5):
        return FakeResponse({"data": [{"id": "m"}]})

    def post(self, url, json=None, timeout=120, **kw):
        self.calls += 1
        if self.calls == 1:
            msg = {"role": "assistant", "content": "",
                   "tool_calls": [{
                       "id": "c1", "type": "function",
                       "function": {"name": "execute_shell",
                                   "arguments": jsonlib.dumps(
                                       {"cmd": "echo hello"})}}]}
        else:
            msg = {"role": "assistant", "content": "done"}
        return FakeResponse({"choices": [{"message": msg}]})


class Ctx:
    def __init__(self):
        self.commands_executed = 0
        self.exit_code = 0
        self.n_input_tokens = 0
        self.n_output_tokens = 0
        self.cost_usd = 0.0
        self.error_message = None


def test_interface_matches_harbor_guide(tmp_path, monkeypatch) -> None:
    """name/version/setup/run com as assinaturas do guia custom-agents."""
    import inspect
    assert ha.JarvisHarborAgent.name() == "jarvis-kernel"
    assert ha.JarvisHarborAgent.SUPPORTS_ATIF is True
    sig = inspect.signature(ha.JarvisHarborAgent.run)
    assert list(sig.parameters) == ["self", "instruction", "environment",
                                    "context"]
    agent = ha.JarvisHarborAgent(logs_dir=tmp_path)
    asyncio.run(agent.setup(environment=None))
    assert agent.version() == "1.0.0"


def test_run_maps_runtime_to_context(tmp_path, monkeypatch) -> None:
    """instruction → runtime.run(FakeSession) → context + trajectory.json."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    import jarvis.runtime.agent_runtime as _rt

    real = _rt.AgentRuntime

    class RT(real):
        def __init__(self, *a, **k):
            super().__init__(*a, http_session=FakeSession(), **k)

    monkeypatch.setattr(_rt, "AgentRuntime", RT)
    agent = ha.JarvisHarborAgent(logs_dir=tmp_path)
    ctx = Ctx()
    asyncio.run(agent.run("do the thing", environment=None, context=ctx))
    assert ctx.commands_executed >= 1
    traj = jsonlib.loads((tmp_path / "trajectory.json").read_text())
    assert traj["agent"] == "jarvis-kernel"
    assert "verdict" in traj and "steps" in traj
    sess = jsonlib.loads((tmp_path / "session.json").read_text())
    assert sess["task"] == "do the thing"
