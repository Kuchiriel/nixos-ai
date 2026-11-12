"""nix_eval / nix_check no MCP — argv puro, sem shell (11/11).

REGRESSAO REAL: os handlers montavam `cd path && nix ... 2>&1` e mandavam isso
para um runner que faz shlex e executa SEM shell. O `&&`, os redirects e as
aspas viravam argumentos literais do `nix` -> o tool falhava sempre. Os testes
abaixo travam o contrato: argv exato, cwd explicito e mensagens de erro claras.
"""

from __future__ import annotations

import subprocess

import pytest

try:
    from jarvis import mcp_server as m
except Exception as exc:  # pragma: no cover - sandbox sem deps do core
    pytest.skip(f"jarvis.mcp_server indisponivel: {exc}", allow_module_level=True)


class _Calls:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return self.result


def test_nix_eval_uses_argv_and_json(monkeypatch):
    fake = _Calls(subprocess.CompletedProcess(["nix"], 0, stdout="5\n", stderr=""))
    monkeypatch.setattr(m.subprocess, "run", fake)

    assert m.call_tool("nix_eval", {"expr": "2 + 3"}) == "5"
    argv, kwargs = fake.calls[0]
    assert argv == ["nix", "eval", "--json", "--expr", "2 + 3"]
    assert kwargs["timeout"] == 30
    assert "shell" not in kwargs


def test_nix_eval_empty_expression_is_rejected(monkeypatch):
    fake = _Calls(subprocess.CompletedProcess(["nix"], 0, stdout="", stderr=""))
    monkeypatch.setattr(m.subprocess, "run", fake)

    assert m.call_tool("nix_eval", {}) == "ERROR: empty expression"
    assert fake.calls == [], "nao deve executar nix sem expressao"


def test_nix_eval_timeout_has_clear_message(monkeypatch):
    def boom(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))

    monkeypatch.setattr(m.subprocess, "run", boom)
    assert m.call_tool("nix_eval", {"expr": "1"}) == "ERROR: nix eval timed out"


def test_nix_eval_falls_back_to_stderr(monkeypatch):
    fake = _Calls(subprocess.CompletedProcess(["nix"], 1, stdout="", stderr="error: boom"))
    monkeypatch.setattr(m.subprocess, "run", fake)
    assert m.call_tool("nix_eval", {"expr": "1"}) == "error: boom"


def test_nix_check_uses_cwd_and_never_shell(monkeypatch, tmp_path):
    fake = _Calls(subprocess.CompletedProcess(["nix"], 0, stdout="all good\n", stderr=""))
    monkeypatch.setattr(m.subprocess, "run", fake)

    assert m.call_tool("nix_check", {"path": str(tmp_path)}) == "all good"
    argv, kwargs = fake.calls[0]
    assert argv == ["nix", "flake", "check"]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["timeout"] == 120
    assert "shell" not in kwargs


def test_nix_check_missing_path_does_not_spawn_nix(monkeypatch, tmp_path):
    fake = _Calls(subprocess.CompletedProcess(["nix"], 0, stdout="", stderr=""))
    monkeypatch.setattr(m.subprocess, "run", fake)

    missing = tmp_path / "nao-existe"
    out = m.call_tool("nix_check", {"path": str(missing)})
    assert out.startswith("ERROR: path not found")
    assert fake.calls == []


def test_nix_check_nonzero_returns_output_without_shell_quoting(monkeypatch, tmp_path):
    fake = _Calls(subprocess.CompletedProcess(["nix"], 1, stdout="", stderr="x & y failed"))
    monkeypatch.setattr(m.subprocess, "run", fake)

    out = m.call_tool("nix_check", {"path": str(tmp_path)})
    assert out == "x & y failed"
