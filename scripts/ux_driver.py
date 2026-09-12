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


def run_task(task: str, timeout_s: int = 300,
             approve: str = "y") -> dict:
    """Roda `jarvis dev --transcript` sob PTY. Retorna execução observada.

    approve: resposta enviada a prompts "Permitir?" ("y" simula humano
    cooperativo; "n" nega; None ignora e deixa travar até timeout).
    Cada aprovação é registrada (métrica approvals).
    """
    tpath = f"/tmp/ux-transcript-{os.getpid()}.json"
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
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()
    res = run_task(args.task, args.timeout)
    res["task"] = args.task
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "transcript"},
                     ensure_ascii=False, indent=1)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
