"""Testes do handoff (CLI) — pacote de contexto para IAs web."""

from __future__ import annotations

from pathlib import Path

from jarvis.cli.main import _cmd_handoff
import argparse


class _Capture:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, s: str = "") -> None:
        self.lines.append(s)


def _run_handoff(tmp_path: Path, monkeypatch, *, task: str | None = None,
                 prompt_only: bool = False, with_agents: bool = True) -> str:
    if with_agents:
        (tmp_path / "AGENTS.md").write_text(
            "# AGENTS.md\npremissa-1\npremissa-2\n", encoding="utf-8",
        )
    monkeypatch.chdir(tmp_path)

    args = argparse.Namespace(task=task, prompt_only=prompt_only)
    cap = _Capture()
    monkeypatch.setattr("builtins.print", cap)
    rc = _cmd_handoff(args)
    assert rc == 0
    return "\n".join(cap.lines)


def test_handoff_includes_agents_and_task(tmp_path, monkeypatch) -> None:
    out = _run_handoff(tmp_path, monkeypatch, task="revisar o models.nix")
    assert "premissa-1" in out
    assert "TAREFA: revisar o models.nix" in out
    assert "AGENTS.md" in out


def test_handoff_without_agents_warns(tmp_path, monkeypatch) -> None:
    out = _run_handoff(tmp_path, monkeypatch, with_agents=False, task="x")
    assert "TAREFA: x" in out


def test_handoff_prompt_only_skips_agents(tmp_path, monkeypatch) -> None:
    out = _run_handoff(tmp_path, monkeypatch, prompt_only=True)
    assert "AGENTS.md" not in out
    assert "TAREFA: (descreva aqui" in out


def test_handoff_caps_embedded_protocol(tmp_path, monkeypatch) -> None:
    """AGENTS.md injection stops before the embedded BUFFY protocol (19/11)."""
    big = "# AGENTS.md\npin-rule-1\n" + ("x\n" * 500) + \
          "## BUFFY.md — nixos-ai Execution Protocol\n" + ("y\n" * 500)
    (tmp_path / "AGENTS.md").write_text(big, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cap2 = _Capture()
    monkeypatch.setattr("builtins.print", cap2)
    assert _cmd_handoff(argparse.Namespace(task="x", prompt_only=False)) == 0
    out = "\n".join(cap2.lines)
    assert "pin-rule-1" in out
    assert "protocolo completo" in out
    assert "y\ny" not in out  # embedded protocol NOT injected
