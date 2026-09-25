#!/usr/bin/env python3
"""ux-repl-session.py — usuário simulado no REPL do space (diagnóstico).

Dirija o `jarvis dev` como um humano: PTY real, teclas com ritmo humano,
pausas Longas enquanto o modelo pensa. Captura a tela inteira e mede o
consumo de contexto por turno (prompt_tokens) pra detectar ring window
 cortando contexto cedo demais.

Uso: python3 ux-repl-session.py --space qwen4b --out /tmp/ux-repl.json
"""
from __future__ import annotations

import argparse
import json
import os
import pty
import re
import select
import subprocess
import time
from pathlib import Path

# Falas naturais de um dono com 7 CIDs usando o REPL: pedem coisas
# pequeno->maior, mezclam dúvida, tarefa e pedido de continuação.
TURNS = [
    ("oi, tudo certo?", 4),
    ("guarda isso aí: minha perícia do INSS é dia 28, preciso levar laudo e carta de concessão", 6),
    ("ok. agora me explica em 3 linhas o que é CRPS", 25),
    ("agora um trabalho de verdade: cria o arquivo /tmp/repl-teste/Plano.md com o conteúdo exato: 28/09 pericia INSS", 30),
    ("confere o que você escreveu lendo o arquivo de volta", 30),
    ("agora continua e me dá um resumo do que falta pra perícia", 40),
]

ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07")


def strip_ansi(s: str) -> str:
    return ANSI.sub("", s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default="qwen4b")
    ap.add_argument("--out", default="/tmp/ux-repl.json")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    # Comando REAL que o dono usa (o space aplica o env; sem atalho):
    cmd = ["jarvis", "space", "exec", args.space, "--", "jarvis", "dev"]
    env = os.environ.copy()
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        cmd, stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True,
    )
    os.close(slave)
    buf = ""
    transcript: list[dict] = []
    t0 = time.monotonic()
    turn_idx = 0
    last_send = 0.0

    def pump(seconds: float) -> None:
        nonlocal buf
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            r, _, _ = select.select([master], [], [], 0.3)
            if master in r:
                try:
                    chunk = os.read(master, 65536).decode("utf-8", "replace")
                except OSError:
                    return
                buf += chunk
            if time.monotonic() - args.timeout + t0 < 0 and proc.poll() is not None:
                return

    try:
        pump(28)  # carrega nix develop + modelo + REPL
        for text, wait in TURNS:
            # envia como humano: digita devagar
            for ch in text:
                os.write(master, ch.encode())
                time.sleep(0.012)
            os.write(master, b"\r")
            transcript.append({"turn": turn_idx, "user": text})
            pump(wait)
            screen = strip_ansi(buf)
            transcript[-1]["screen_tail"] = screen[-2500:]
            buf = ""
            turn_idx += 1
            if proc.poll() is not None:
                break
    finally:
        try:
            os.write(master, b"/exit\r")
            time.sleep(2)
        except OSError:
            pass
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        os.close(master)

    Path(args.out).write_text(
        json.dumps({"space": args.space, "turns": transcript},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"salvo: {args.out} ({len(transcript)} turnos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
