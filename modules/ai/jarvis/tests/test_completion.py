"""Completion policy: DONE só com evidência (P0.2) + erro nunca encerra (P0.3)."""

from __future__ import annotations

from jarvis.core.completion import check_completion, classify_error


def _msgs(*contents):
    return [{"role": "tool", "content": c} for c in contents]


def test_trailing_error_is_unverified():
    v = check_completion(_msgs("ok resultado", "ERROR: algo quebrou"))
    assert v.status == "UNVERIFIED"
    assert any("erro" in m for m in v.missing)


def test_zero_success_is_unverified():
    v = check_completion(_msgs("ERROR: x"))
    assert v.status == "UNVERIFIED"
    assert any("ground truth" in m for m in v.missing)


def test_clean_run_is_verified():
    v = check_completion(_msgs("conteúdo lido"))
    assert v.status == "VERIFIED"
    assert v.missing == []


def test_written_missing_file_is_unverified(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    msgs = [{"role": "tool", "content": "written"},
            {"role": "assistant", "tool_calls": [
                {"function": {"name": "write_file",
                              "arguments": {"path": "novo.txt"}}}]},
            {"role": "tool", "content": "written"}]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("não existe" in m for m in v.missing)


def test_written_py_compiles(tmp_path, monkeypatch):
    from jarvis.core.paths import use_project_root
    (tmp_path / "ok.py").write_text("x = 1\n")
    msgs = [{"role": "assistant", "tool_calls": [
        {"function": {"name": "write_file",
                      "arguments": {"path": "ok.py"}}}]},
            {"role": "tool", "content": "written"}]
    with use_project_root(tmp_path):
        v = check_completion(msgs)
    assert v.status == "VERIFIED"
    assert any("compila" in e for e in v.evidence)


def test_written_py_syntax_error(tmp_path, monkeypatch):
    from jarvis.core.paths import use_project_root
    (tmp_path / "bad.py").write_text("def f(:\n")
    msgs = [{"role": "assistant", "tool_calls": [
        {"function": {"name": "write_file",
                      "arguments": {"path": "bad.py"}}}]},
            {"role": "tool", "content": "written"}]
    with use_project_root(tmp_path):
        v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("não compila" in m for m in v.missing)


def test_classify_error_kinds():
    assert classify_error("ERROR: Command timed out after 60s") == "transient"
    assert classify_error("ERROR: Command denied by user") == "policy"
    assert classify_error("ERROR: File not found: x") == "missing"
    assert classify_error("ERROR: Malformed tool call structure") == "bad-request"
    assert classify_error("ERROR: algo estranho") == "failed"
    assert classify_error("conteúdo normal") == "ok"


def test_identical_error_thrice_is_stuck(tmp_path):
    """Mesmo erro 3x → STUCK com final honesto (P0.3)."""
    import json as jsonlib
    from unittest.mock import patch
    from jarvis.core.agent import Agent
    from jarvis.core.config import Config

    import sys
    sys.path.insert(0, "tests")
    from test_agent import FakeSession, FakeResponse  # noqa

    class AlwaysFail(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            self.calls += 1
            msg = {"role": "assistant", "content": "",
                   "tool_calls": [{
                       "id": "c1", "type": "function",
                       "function": {"name": "execute_shell",
                                   "arguments": jsonlib.dumps(
                                       {"cmd": "ls /definitely/not/here"})}}]}
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=AlwaysFail(),
                  audit_path=tmp_path / "a.jsonl")
    with patch("jarvis.core.agent.run_shell") as rs:
        import subprocess
        rs.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="no such file")
        result = agent.run("liste aquilo")
    assert result.verdict == "STUCK"
    assert result.verified is False
    assert "STUCK" in result.final_response


def test_text_claim_without_tools_is_unverified_then_continues():
    """Texto 'done' sem tools: turnos de verificação antes de fechar."""
    from unittest.mock import patch
    from jarvis.core.agent import Agent
    from jarvis.core.config import Config

    import sys
    sys.path.insert(0, "tests")
    from test_agent import FakeSession, FakeResponse  # noqa

    calls = {"n": 0}

    class TextThenTool(FakeSession):
        def post(self, url, json=None, timeout=120, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                msg = {"role": "assistant", "content": "done!"}
            elif calls["n"] == 2:
                msg = {"role": "assistant",
                       "content": "done!",
                       "tool_calls": [{
                           "id": "c1", "type": "function",
                           "function": {
                               "name": "read_file",
                               "arguments": '{"path": "x"}'}}]}
            else:
                msg = {"role": "assistant", "content": "lido, de verdade"}
            return FakeResponse({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=TextThenTool())
    with patch("jarvis.core.devtools.read_file",
               return_value={"ok": True, "content": "conteúdo",
                             "path": "x", "total_lines": 1}):
        result = agent.run("leia x")
    # 1º turno texto puro → verificação exige evidência → continua e lê.
    assert result.turns >= 2
    assert result.verdict == "VERIFIED"
    assert result.verified is True


def test_claimed_creation_without_write_is_unverified():
    """'Criei dobra.py' sem write_file no run = falsa conclusão (C2 real)."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "read_file",
                          "arguments": '{"path": "x"}'}}]},
        {"role": "tool", "content": "conteúdo"},
        {"role": "assistant",
         "content": "O arquivo `dobra.py` foi criado com o conteúdo."},
    ]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("sem escrita" in m for m in v.missing)


def test_pure_text_run_skips_claim_rule():
    """Run sem tools: regra de artefato não se aplica (Q&A puro)."""
    from jarvis.core.completion import check_completion
    v = check_completion([{"role": "assistant",
                           "content": "A capital é Brasília."}])
    assert v.status == "UNVERIFIED"  # zero ground truth (outra regra)


def test_denied_but_observed_is_unverified():
    """'X não existe' quando o ls listou X = falsa conclusão (N2 real)."""
    from jarvis.core.completion import check_completion
    msgs = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "execute_shell",
                          "arguments": '{"cmd": "ls"}'}}]},
        {"role": "tool", "content": "app.py\nservico.nix\nnotas.md"},
        {"role": "assistant",
         "content": "O arquivo servico.nix não existe no local."},
    ]
    v = check_completion(msgs)
    assert v.status == "UNVERIFIED"
    assert any("nega evidência" in m for m in v.missing)
