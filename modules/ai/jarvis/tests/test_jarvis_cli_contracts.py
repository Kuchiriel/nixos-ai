"""Contratos básicos do jarvis-cli (meta-tools/rehydrate/session-resume).

Testes de integração leve via subprocess: validam shape/JSON e modos aceitos,
sem acoplar a scores exatos ou dependências frágeis. Devem rodar em nix develop.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


def _repo_root() -> Path:
    for p in Path(__file__).resolve().parents:
        if (p / "scripts" / "jarvis-cli.sh").is_file():
            return p
    raise RuntimeError("repo root com scripts/jarvis-cli.sh não encontrado")


ROOT = _repo_root()
CLI = str(ROOT / "scripts" / "jarvis-cli.sh")


def _run(*args: str, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    return subprocess.run(
        [CLI, *args],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )


def _json_stdout(cp: subprocess.CompletedProcess[str]):
    assert cp.returncode == 0, f"rc={cp.returncode}\nstdout={cp.stdout}\nstderr={cp.stderr}"
    out = cp.stdout.strip()
    assert out, f"stdout vazio\nstderr={cp.stderr}"
    return json.loads(out)


def test_tools_search_json_shape_embedding_or_fallback():
    data = _json_stdout(_run("tools-search", "session resume", "--json"))
    assert data.get("query") == "session resume"
    assert data.get("mode") in ("embedding", "substring", "fallback", "all")
    assert isinstance(data.get("results"), list)
    assert len(data["results"]) >= 1
    assert "limit" in data or data.get("mode") in ("all", "substring", "fallback")
    r0 = data["results"][0]
    assert isinstance(r0.get("name"), str) and r0["name"]
    assert "description" in r0


def test_tools_search_empty_json_lists_all():
    data = _json_stdout(_run("tools-search", "", "--json"))
    assert data.get("mode") == "all"
    assert isinstance(data.get("results"), list)
    assert len(data["results"]) >= 10
    assert all("name" in r and "description" in r for r in data["results"][:5])


def test_tool_tools_search_json_structured():
    data = _json_stdout(_run("tool", "tools_search", "rehydrate", "--json"))
    assert data.get("query") == "rehydrate"
    assert data.get("mode") in ("embedding", "substring", "fallback", "all")
    assert isinstance(data.get("results"), list)
    assert len(data["results"]) >= 1


def test_tool_tools_search_json_flag_position():
    data = _json_stdout(_run("tool", "tools_search", "--json", "rehydrate"))
    assert data.get("query") == "rehydrate"
    assert isinstance(data.get("results"), list)


def test_rehydrate_json_shape():
    cp = _run("rehydrate", "--json")
    # rehydrate pode ser lento; em ambientes mínimos ainda deve retornar JSON com texto
    assert cp.returncode == 0, f"rc={cp.returncode}\nstdout={cp.stdout}\nstderr={cp.stderr}"
    out = cp.stdout.strip()
    assert out, f"stdout vazio\nstderr={cp.stderr}"
    data = json.loads(out)
    assert data.get("tool") == "rehydrate"
    assert isinstance(data.get("text"), str)


def test_session_resume_json_shape():
    data = _json_stdout(_run("session-resume", "--json"))
    assert data.get("tool") == "session_resume"
    assert isinstance(data.get("args"), dict)
    assert isinstance(data.get("text"), str)


def test_tools_search_text_mode_nonempty():
    cp = _run("tools-search", "session resume")
    assert cp.returncode == 0, f"rc={cp.returncode}\nstdout={cp.stdout}\nstderr={cp.stderr}"
    assert "session_resume" in cp.stdout or "tool" in cp.stdout.lower()


def test_tool_rejects_non_json_args_for_generic_tool():
    cp = _run("tool", "remember", "not-json")
    # deve falhar com mensagem clara, não traceback de json.loads não tratado no bash wrapper
    assert cp.returncode != 0
    combined = (cp.stdout + cp.stderr).lower()
    assert "json" in combined or "erro" in combined
