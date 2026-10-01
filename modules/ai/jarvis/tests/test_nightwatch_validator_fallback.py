"""Regression test: run_targeted_tests() must never silently narrow the
import pytest
pytestmark = pytest.mark.integration
safety net to a single unrelated file when no test matches the change.

Contexto: antes desta correção, mudar um arquivo sem teste homônimo (ex:
paths.py, context_budget.py, checkpoint.py) fazia o gate rodar só
test_agent.py (~28 testes) em vez da suíte real (605 testes), antes de
commitar direto em main. Sem teste dedicado protegendo esse comportamento,
o bug sobreviveu a pelo menos 3 reescritas do nightwatch (cli/nightwatch.py
antigo -> safety.py -> validator.py).
"""
from __future__ import annotations

import nightwatch.validator as validator_mod
from jarvis.core import testenv


def test_no_relevant_match_falls_back_to_full_suite(monkeypatch):
    """Arquivo sem teste homonimo deve disparar a suite inteira, nao
    test_agent.py isolado."""
    executed_cmds = []

    def fake_run_pytest(target, **kw):
        executed_cmds.append((" ".join(str(target).split()) + " " + str(kw.get("extra_args", "")), kw.get("timeout", 120)))
        return testenv.TestRun(ok=True, passed=1, failed=0, python_used="py")

    monkeypatch.setattr(testenv, "run_pytest", fake_run_pytest)
    monkeypatch.setattr(
        validator_mod,
        "discover_test_files",
        lambda: ["modules/ai/jarvis/tests/test_agent.py",
                 "modules/ai/jarvis/tests/test_hackmd.py"],
    )

    # Nome de módulo que não bate com nenhum test_*.py por substring
    report = validator_mod.run_targeted_tests(
        ["modules/ai/jarvis/src/nightwatch/paths.py"]
    )

    assert report.passed is True
    assert len(executed_cmds) == 1
    cmd, timeout = executed_cmds[0]
    assert "test_agent.py" not in cmd, (
        f"regrediu para o fallback antigo (arquivo unico e nao relacionado): {cmd}"
    )
    # Command should target the full test suite (absolute or relative path)
    assert "tests" in cmd or "pytest" in cmd
    assert timeout >= 600  # suite completa precisa de mais tempo que 1 arquivo


def test_relevant_match_still_uses_targeted_fast_path(monkeypatch):
    """Quando existe teste homonimo, continua rodando so ele (rapido) —
    a correcao nao deve forcar full-suite sempre."""
    executed_cmds = []

    def fake_run_pytest(target, **kw):
        executed_cmds.append((" ".join(str(target).split()) + " " + str(kw.get("extra_args", "")), kw.get("timeout", 120)))
        return testenv.TestRun(ok=True, passed=1, failed=0, python_used="py")

    monkeypatch.setattr(testenv, "run_pytest", fake_run_pytest)
    monkeypatch.setattr(
        validator_mod,
        "discover_test_files",
        lambda: ["modules/ai/jarvis/tests/test_hackmd.py"],
    )

    report = validator_mod.run_targeted_tests(
        ["modules/ai/jarvis/src/jarvis/core/hackmd.py"]
    )

    assert report.passed is True
    assert len(executed_cmds) == 1
    cmd, _ = executed_cmds[0]
    assert "test_hackmd.py" in cmd
