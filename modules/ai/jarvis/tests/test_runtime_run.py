"""AgentRuntime.run — paridade com Agent + sessão serializável (F7).

Sem LLM: FakeSession (padrão de test_agent.py). Prova que o runtime compõe
o loop canônico sem mudar semântica, e que a sessão checkpointa/restaura.
"""
import json as jsonlib

from jarvis.core.agent import Agent
from jarvis.core.config import Config
from jarvis.runtime.agent_runtime import AgentRuntime
from jarvis.runtime.session import AgentSession


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    """Servidor OpenAI-compatível simulado: executa 1 tool e responde."""

    def __init__(self, tool_output="stdout fake"):
        self.tool_output = tool_output
        self.calls = 0

    def get(self, url, timeout=5):
        return FakeResponse({"data": [{"id": "qwen2.5-coder-7b-instruct"}]})

    def post(self, url, json=None, timeout=120, **kw):
        self.calls += 1
        assert "chat/completions" in url
        if self.calls == 1:
            msg = {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "execute_shell",
                        "arguments": jsonlib.dumps({"cmd": "echo hello"}),
                    },
                }],
            }
        else:
            msg = {"role": "assistant", "content": f"done: {self.tool_output}"}
        return FakeResponse({"choices": [{"message": msg}]})


def test_runtime_parity_with_agent(tmp_path, monkeypatch) -> None:
    """Mesmo double, mesma task → mesmo veredito/turnos/resposta."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    cfg = Config()
    direct = Agent(cfg, session=FakeSession()).run("check the system")
    rt = AgentRuntime(cfg, http_session=FakeSession()).run("check the system")
    assert rt.verdict == direct.verdict
    assert rt.turns == direct.turns
    assert rt.response == direct.final_response
    assert rt.session.model_id == cfg.llm_model
    assert rt.session.ended_at >= rt.session.started_at > 0


def test_session_roundtrip_json(tmp_path) -> None:
    """Checkpoint/restore: to_dict → JSON → from_dict preserva o essencial."""
    s = AgentSession(task="t", model_id="m", termination="VERIFIED",
                     verified=True, turns=3, response="ok",
                     evidence=["e"], missing=[],
                     messages=[{"role": "user", "content": "t"}] * 60)
    d = s.to_dict()
    assert d["messages_truncated"] is True and len(d["messages"]) == 50
    blob = jsonlib.dumps(d)
    back = AgentSession.from_dict(jsonlib.loads(blob))
    assert (back.task, back.model_id, back.termination, back.turns,
            back.verified) == ("t", "m", "VERIFIED", 3, True)
    assert back.evidence == ["e"]


def test_session_ignores_unknown_fields() -> None:
    """Restaura sessões de versões futuras sem quebrar (forward-compat)."""
    s = AgentSession.from_dict({"task": "t", "future_field": 1})
    assert s.task == "t"
