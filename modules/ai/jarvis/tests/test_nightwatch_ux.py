"""Nightwatch + lições do UX-abismo: disciplina, evidência, retry."""
import json


def test_llm_choke_point_has_discipline(monkeypatch, capsys) -> None:
    from nightwatch import harness as H

    seen = {}

    class FakeResp:
        content = "[]"
        tool_calls = []

    class FakeClient:
        def __init__(self, cfg):
            pass

        def chat_with_tools(self, messages, **kw):
            seen["sys"] = messages[0]["content"]
            return FakeResp()

    monkeypatch.setattr("jarvis.providers.llm.LLMClient", FakeClient)
    out = H._default_call_llm("faça X", 100)
    assert out == "[]"
    assert "TOOL_USE_DISCIPLINE" in seen["sys"]
    assert "Locate first" in seen["sys"]
    err = capsys.readouterr().err
    assert "llm-call start" in err and "llm-call done" in err


def test_llm_failure_is_honest(monkeypatch, capsys) -> None:
    from nightwatch import harness as H

    class BadClient:
        def __init__(self, cfg):
            raise RuntimeError("sem servidor")

    monkeypatch.setattr("jarvis.providers.llm.LLMClient", BadClient)
    out = H._default_call_llm("faça X", 100)
    assert out.startswith("ERROR:")
    assert "FAILED" in capsys.readouterr().err


def test_evidence_verdict() -> None:
    from nightwatch.harness import _verify_completion_evidence
    assert _verify_completion_evidence("abc123", ["a.py"]) == (True, "")
    ok, why = _verify_completion_evidence(None, ["a.py"])
    assert not ok and "commit" in why
    ok, why = _verify_completion_evidence("abc123", [])
    assert not ok and "arquivos" in why
    ok, why = _verify_completion_evidence("", None)
    assert not ok


def test_discovery_retries_once_then_gives_up(capsys) -> None:
    import concurrent.futures
    from nightwatch import harness as H

    calls = []

    def _flaky(prompt, max_tokens):
        calls.append(1)
        if len(calls) == 1:
            raise concurrent.futures.TimeoutError()
        return json.dumps([{
            "description": "Create missing unit tests for login handler",
            "target_files": [], "acceptance_criteria": "pytest passes",
            "priority": 5, "risk": "low"}])

    tasks = H._discover_llm_tasks(_flaky, "nixos-ai")
    assert len(calls) == 2
    assert len(tasks) == 1
    assert tasks[0].description.startswith("Create missing")


def test_discovery_twice_timeout_returns_empty(capsys) -> None:
    import concurrent.futures
    from nightwatch import harness as H

    def _hung(prompt, max_tokens):
        raise concurrent.futures.TimeoutError()

    assert H._discover_llm_tasks(_hung, "nixos-ai") == []
    assert "twice" in capsys.readouterr().err


def test_extract_json_array_tolerant() -> None:
    from nightwatch.harness import _extract_json_array
    arr = [{"description": "Create missing unit tests now", "priority": 5}]
    assert _extract_json_array("prosa\n```json\n" + __import__("json").dumps(arr) + "\n```\nmais prosa") == arr
    assert _extract_json_array("texto ] com [ colchetes } soltos") == []
    tricky = '[{"description": "Fix [bracket] bug in parser", "target_files": []}] trailing [garbage'
    got = _extract_json_array("aqui:\n" + tricky)
    assert len(got) == 1 and "[bracket]" in got[0]["description"]


def test_discovery_parses_fenced_response() -> None:
    import json
    from nightwatch import harness as H

    arr = [{"description": "Create missing unit tests for login handler",
            "target_files": [], "acceptance_criteria": "pytest passes",
            "priority": 5, "risk": "low"}]
    tasks = H._discover_llm_tasks(
        lambda p, m: "Segue:\n```json\n" + json.dumps(arr) + "\n```\nFim.",
        "nixos-ai")
    assert len(tasks) == 1
