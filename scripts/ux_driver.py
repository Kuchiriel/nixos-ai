#!/usr/bin/env python3
"""ux-driver.py — human driver: roda `jarvis dev` como um humano faria.

PTY real + stdin observado + stdout capturado + timeout duro +
transcript JSON do próprio CLI + verificação externa do mundo.
Uso:
  python3 scripts/ux-driver.py --task "..." --out /tmp/ux/run1.json
"""
from __future__ import annotations

import argparse
import json
import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path


def run_task(task: str, timeout_s: int = 300,
             approve: str = "y") -> dict:
    """Roda `jarvis dev --transcript` sob PTY. Retorna execução observada.

    approve: resposta enviada a prompts "Permitir?" ("y" simula humano
    cooperativo; "n" nega; None ignora e deixa travar até timeout).
    Cada aprovação é registrada (métrica approvals).
    """
    # Transcript único por run (PID + timestamp ms + contador): a suite
    # roda N tasks no MESMO processo e PID puro sobrescrevia os anteriores
    # (só o último transcript sobrevivia — evidência perdida).
    global _run_counter
    try:
        _run_counter += 1
    except NameError:
        _run_counter = 1
    tpath = (f"/tmp/ux-transcript-{os.getpid()}-"
             f"{int(time.time() * 1000)}-{_run_counter}.json")
    cmd = ["jarvis", "dev", task, "--transcript", tpath]
    t0 = time.monotonic()
    m_out, s_out = pty.openpty()
    try:
        p = subprocess.Popen(
            cmd, stdin=s_out, stdout=s_out, stderr=s_out,
            text=False, close_fds=True)
    except FileNotFoundError:
        os.close(m_out)
        os.close(s_out)
        return {"ok": False, "error": "jarvis não encontrado no PATH",
                "elapsed_s": 0.0}
    os.close(s_out)
    buf = b""
    approvals = 0
    tail = b""
    try:
        while True:
            if p.poll() is not None:
                break
            if time.monotonic() - t0 > timeout_s:
                p.kill()
                try:
                    p.wait(timeout=10)
                except Exception:
                    pass
                buf += b"\n[DRIVER: TIMEOUT]"
                break
            r, _, _ = select.select([m_out], [], [], 1.0)
            if r:
                try:
                    chunk = os.read(m_out, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                tail = (tail + chunk)[-200:]
                # Prompt de aprovação do Rich/Confirm ("Permitir?").
                # Responde como humano cooperativo e registra.
                if approve and b"Permitir?" in tail:
                    try:
                        os.write(m_out, (approve + "\n").encode())
                    except OSError:
                        pass
                    approvals += 1
                    buf += f"\n[DRIVER: approval #{approvals} -> {approve}]\n".encode()
                    tail = b""
    finally:
        try:
            os.close(m_out)
        except OSError:
            pass
    try:
        p.wait(timeout=10)
    except Exception:
        pass
    elapsed = time.monotonic() - t0
    text = buf.decode("utf-8", errors="replace")
    transcript = None
    try:
        with open(tpath, encoding="utf-8") as f:
            transcript = json.load(f)
    except Exception:
        pass
    return {
        "ok": p.returncode == 0,
        "rc": p.returncode,
        "elapsed_s": round(elapsed, 1),
        "approvals": approvals,
        "output": text[-6000:],
        "transcript": transcript,
        "engine": "dev",
    }


def run_task_runtime(task: str, timeout_s: int = 180) -> dict:
    """Engine runtime (KERNEL): AgentRuntime.run in-process.

    Diferenças honestas vs run_task (engine dev):
    - Mede a FONTE (source tree, kernel atual), não o binário instalado.
    - Sem PTY aprovações: approval_callback sempre-True (paridade com o
      approve=y do driver humano) — approvals="auto".
    - Sem kill duro: vale o budget interno do Agent (MAX_TURNS/MAX_TIME_S);
      timeout_s documenta o teto desejado; elapsed real é registrado.
    Retorna o MESMO shape (ok/rc/elapsed/output/transcript) + engine.
    """
    t0 = time.monotonic()
    try:
        repo = Path(__file__).resolve().parents[1]
        src = repo / "modules/ai/jarvis/src"
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        from jarvis.runtime.agent_runtime import AgentRuntime
        from jarvis.core.config import get_config
        rt = AgentRuntime(
            get_config(),
            agent_kwargs={"approve": True,
                          "approval_callback": lambda cmd: True})
        r = rt.run(task)
        msgs = r.session.messages or []
        chunks: list[str] = []
        for m in msgs:
            c = m.get("content")
            if isinstance(c, str) and c.strip():
                chunks.append(c)
            elif isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("text"):
                        chunks.append(str(b["text"]))
        text = "\n".join(chunks)[-6000:]
        return {
            "ok": r.verdict == "VERIFIED",
            "rc": 0,
            "elapsed_s": round(time.monotonic() - t0, 1),
            "approvals": "auto",
            "output": text,
            "transcript": {"messages": msgs},
            "engine": "runtime",
            "verdict": r.verdict,
            "turns": r.turns,
        }
    except Exception as e:  # noqa: BLE001 — rc=1, mundo decide o resto
        return {
            "ok": False,
            "rc": 1,
            "elapsed_s": round(time.monotonic() - t0, 1),
            "approvals": "auto",
            "output": f"ENGINE ERROR: {type(e).__name__}: {e}"[-6000:],
            "transcript": {"messages": []},
            "engine": "runtime",
            "verdict": "FAILED",
            "turns": 0,
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--world-check", default=None,
                    help="comando shell de verificação externa do mundo (§11); "
                         "gravado no JSON — rc do CLI sozinho NÃO prova sucesso")
    args = ap.parse_args()
    res = run_task(args.task, args.timeout)
    res["task"] = args.task
    if args.world_check:
        rc = subprocess.run(["bash", "-c", args.world_check],
                            capture_output=True, text=True, timeout=30)
        res["world_check"] = {"cmd": args.world_check, "rc": rc.returncode,
                              "out": (rc.stdout + rc.stderr)[-400:]}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "transcript"},
                     ensure_ascii=False, indent=1)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
