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


def test_no_relevant_match_falls_back_to_full_suite(monkeypatch):
    """Arquivo sem teste homonimo deve disparar a suite inteira, nao
    test_agent.py isolado."""
    executed_cmds = []

    def fake_run_command(cmd: str, timeout: int = 60):
        executed_cmds.append((cmd, timeout))
        return True, "1 passed", 10

    monkeypatch.setattr(validator_mod, "run_command", fake_run_command)
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

    def fake_run_command(cmd: str, timeout: int = 60):
        executed_cmds.append((cmd, timeout))
        return True, "1 passed", 10

    monkeypatch.setattr(validator_mod, "run_command", fake_run_command)
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
