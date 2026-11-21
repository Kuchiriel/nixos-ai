"""O JSON publico do hub nao pode perder os gates de resolucao."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUB = ROOT / "scripts/agent-hub.mjs"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_pending_json_exposes_resolution_gates(tmp_path: Path) -> None:
    audit = tmp_path / "projects/nixos-ai/docs/audit"
    mesh = tmp_path / "projects/ai-mesh/docs"
    audit.mkdir(parents=True)
    mesh.mkdir(parents=True)
    (audit / "TECHNICAL-DEBT.md").write_text("# Debt\n", encoding="utf-8")
    (audit / "PROJECT-AUDIT-STATE.md").write_text("# State\n", encoding="utf-8")
    (mesh / "auto-improve-gaps.jsonl").write_text("", encoding="utf-8")
    (mesh / "auto-improve-resolution.json").write_text(json.dumps({
        "ts": "2026-11-21T19:34:18+00:00",
        "arquivadas": 46,
        "pendentes_de_fechamento": 0,
        "gate_ok": True,
        "evidence_ok": True,
        "error": "",
        "source": "auto-improve --audit (resolution)",
    }), encoding="utf-8")

    port = _free_port()
    env = dict(os.environ)
    env.update({"HOME": str(tmp_path), "PORT": str(port), "BIND": "127.0.0.1",
                "AGENT_HUB_TOKEN": "fixture-token"})
    proc = subprocess.Popen(["node", str(HUB)], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        payload = None
        deadline = time.time() + 15
        while time.time() < deadline:
            if proc.poll() is not None:
                out, err = proc.communicate(timeout=2)
                raise AssertionError(f"hub exited early: {out}\n{err}")
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/pending", timeout=2) as response:
                    payload = json.load(response)
                break
            except Exception:
                time.sleep(0.1)
        assert payload is not None, "hub /api/pending nao respondeu"
        resolution = payload["resolution"]
        assert resolution["evidence_ok"] is True
        assert resolution["gate_ok"] is True
        assert resolution["arquivadas"] == 46
        assert resolution["pendentes"] == 0
        assert payload["counts"]["resolution_evidence_ok"] is True
        assert payload["counts"]["resolution_gate_ok"] is True
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
