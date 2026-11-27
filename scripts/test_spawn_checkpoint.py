"""Tests for the spawn checkpoint semantics (25/11, lane runtime-production).

O checkpoint do spawn precisa distinguir "ainda subindo" de "morreu", e
sempre fechar o arquivo. Medido antes do fix: 4 dos 29 state files estavam
presos em "starting" ha 2,6 dias, sem NENHUM processo vivo e sem
finished_at — o observer nao tinha como saber que estavam mortos.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

import pytest

PACK = pathlib.Path(__file__).resolve().parent      # scripts/
REPO = PACK.parent                                  # nixos-ai/


def _spawn_module():
    spec = importlib.util.spec_from_file_location("agent_spawn", PACK / "agent-spawn.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_spawn"] = mod
    spec.loader.exec_module(mod)
    return mod


def _isolated_home(tmp_path: pathlib.Path, opencode_body: str) -> pathlib.Path:
    """HOME isolado com a estrutura que o agent-spawn espera."""
    (tmp_path / "projects" / "nixos-ai").mkdir(parents=True, exist_ok=True)
    fakebin = tmp_path / "bin"
    fakebin.mkdir(exist_ok=True)
    oc = fakebin / "opencode"
    oc.write_text(opencode_body)
    oc.chmod(0o755)
    return fakebin


def _run_spawn(home: pathlib.Path, fakebin: pathlib.Path, task: str):
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"
    env["JARVIS_SPAWN_ALLOW_OVERRIDE"] = "1"
    env["PYTHONPATH"] = f"{REPO / 'modules/ai/jarvis/src'}:{env.get('PYTHONPATH', '')}"
    return subprocess.run(
        [sys.executable, str(PACK / "agent-spawn.py"), "--task", task,
         "--model", "gemini/gemini-2.5-flash"],
        capture_output=True, text=True, timeout=180, cwd=str(REPO), env=env)


def test_failure_path_records_status_rc_and_timestamps(tmp_path: pathlib.Path) -> None:
    """(25/11) Um spawn que sai != 0 grava status=failed + rc + os dois timestamps."""
    home = tmp_path / "home"
    home.mkdir()
    fakebin = _isolated_home(home, "#!/bin/sh\nexit 3\n")
    r = _run_spawn(home, fakebin, "prova sintetica isolada: falha do comando")
    out = json.loads(r.stdout)
    assert out["status"] == "failed"
    assert out["rc"] == 3
    assert out["started_at"] and out["finished_at"]
    assert out["finished_at"] >= out["started_at"]
    # e o STATE FILE tem o mesmo conteudo (o observer le o arquivo)
    files = list((home / ".local/state/jarvis/spawns").glob("*.json"))
    assert len(files) == 1
    st = json.loads(files[0].read_text())
    assert st["status"] == "failed"
    assert st["rc"] == 3
    assert st["finished_at"] >= st["started_at"]


def test_running_spawn_records_a_live_pid(tmp_path: pathlib.Path) -> None:
    """(25/11) Enquanto o spawn roda, o checkpoint tem o PID do opencode run.

    E o PID prova vida: sem ele, "starting" nao diz se o trabalho ainda anda.
    """
    home = tmp_path / "home"
    home.mkdir()
    fakebin = _isolated_home(home, "#!/bin/sh\nsleep 30\n")
    proc = subprocess.Popen(
        [sys.executable, str(PACK / "agent-spawn.py"), "--task",
         "prova sintetica isolada: spawn vivo", "--model", "gemini/gemini-2.5-flash"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=str(REPO),
        env={**os.environ, "HOME": str(home), "PATH": f"{fakebin}:{os.environ.get('PATH', '')}",
             "JARVIS_SPAWN_ALLOW_OVERRIDE": "1",
             "PYTHONPATH": f"{REPO / 'modules/ai/jarvis/src'}:{os.environ.get('PYTHONPATH', '')}"})
    try:
        state = None
        for _ in range(40):
            files = list((home / ".local/state/jarvis/spawns").glob("*.json"))
            if files:
                state = json.loads(files[0].read_text())
                if state.get("child_pid"):
                    break
            time.sleep(0.5)
        assert state is not None and state.get("child_pid"), "o PID do opencode run deve estar no checkpoint"
        assert state["status"] == "starting"
        assert state.get("finished_at") is None
        pid = int(state["child_pid"])
        os.kill(pid, 0)  # levanta se o processo existe
    finally:
        proc.kill()
        proc.wait(timeout=30)


def test_state_file_is_written_atomically(tmp_path: pathlib.Path) -> None:
    """(25/11) Um leitor nunca ve JSON pela metade (escrita atomica)."""
    mod = _spawn_module()
    # HOME e' lido no import (Path.home()); o teste aponta para um tmp
    mod.HOME = tmp_path
    target = tmp_path / ".local/state/jarvis/spawns" / "ses_teste.json"
    mod.write_spawn_state("ses_teste", {"status": "starting", "session": "ses_teste"})
    data = json.loads(target.read_text())
    assert data["status"] == "starting"
    # e nao sobrou arquivo temporario
    assert not list(target.parent.glob("*.tmp"))


def test_hub_derives_effective_status() -> None:
    """(25/11) O hub deriva o estado EFETIVO a partir do PID.

    starting + pid vivo = running; starting + pid morto = dead. Sem isso o
    observer via "starting" em spawns mortos ha dias.
    """
    hub = (REPO / "scripts" / "agent-hub.mjs").read_text()
    assert "function effectiveSpawnStatus" in hub
    assert "pidAlive" in hub
    # o hub expoe o campo derivado na resposta
    assert "effective_status" in hub
