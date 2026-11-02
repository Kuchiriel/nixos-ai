#!/usr/bin/env python3
"""measure-rehydrate-ab.py — A/B da injeção de resgate (M2/M3, 02/11).

PERPOSO: medir se a injeção do harness (plugin memory.js →
`experimental.chat.system.transform`) muda o COMPORTAMENTO do agente:
  A) com injeção   → o agente deve citar/chamar `jarvis_rehydrate`
  B) sem injeção   → o agente não tem como saber (flag
                     OPENCODE_NO_REHYDRATE_INJECT=1)
Métrica: (1) mencionou "rehydrate", (2) CHAMOU a tool jarvis_rehydrate,
(3) tokens consumidos (custo da regra).

O teste roda num diretório SEM AGENTS.md — senão o agente aprenderia a
resposta pelo contexto do repo e o A/B não provaria nada (2602.11988:
instrução no context file só é útil se mudar o comportamento).

USO:
  ./scripts/measure-rehydrate-ab.py [--model <id>] [--question "<pergunta>"]
  ./scripts/measure-rehydrate-ab.py --dry-run      # só mostra o plano

EXEMPLO:
  ./scripts/measure-rehydrate-ab.py --model local-uncensored-4b/jarvis-mtp-lora
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DB = Path.home() / ".local/share/opencode/opencode.db"
QUESTION = (
    "Você acabou de abrir uma sessão nova neste diretório. "
    "Qual é a PRIMEIRA ferramenta que você deve chamar antes de agir, "
    "e como você faria para falar com outro agente opencode desta máquina "
    "sem travar o typing do humano? Responda em no máximo 4 linhas."
)


def run_once(model: str, question: str, inject: bool, cwd: Path, timeout: int = 420) -> dict:
    env = dict(os.environ)
    env.pop("OPENCODE_NO_REHYDRATE_INJECT", None)
    if not inject:
        env["OPENCODE_NO_REHYDRATE_INJECT"] = "1"
    cmd = ["opencode", "run", "--model", model, question]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=timeout)
        dt = time.time() - t0
        return {"cmd": cmd, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-2000:],
                "rc": proc.returncode, "segundos": round(dt, 1), "inject": inject,
                "timeout": False}
    except subprocess.TimeoutExpired as e:
        # timeout é DADO, não crash: um agente em loop de tool call é exatamente
        # o que esta medição precisa enxergar.
        return {"cmd": cmd,
                "stdout": (e.stdout or b"").decode(errors="ignore")[-4000:] if isinstance(e.stdout, bytes) else (e.stdout or "")[-4000:],
                "stderr": (e.stderr or b"").decode(errors="ignore")[-2000:] if isinstance(e.stderr, bytes) else (e.stderr or "")[-2000:],
                "rc": -1, "segundos": round(time.time() - t0, 1), "inject": inject,
                "timeout": True}


def sessao_recem(directory: str) -> str | None:
    """Schema real (opencode.db v1.18.x): session(id, directory, tokens_input...)."""
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        row = c.execute(
            "SELECT id FROM session WHERE directory=? ORDER BY time_updated DESC LIMIT 1",
            (directory,)).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def metricas(session_id: str) -> dict:
    """Lê message/part do schema real: message(data JSON), part(data JSON)."""
    out = {"assistant_text": "", "tools": [], "tokens_in": 0, "tokens_out": 0}
    if not session_id:
        return out
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        rows = c.execute(
            "SELECT m.data, p.data FROM message m LEFT JOIN part p ON p.message_id = m.id "
            "WHERE m.session_id=? ORDER BY m.time_created, p.time_created",
            (session_id,)).fetchall()
    except Exception:
        return out
    for m_raw, p_raw in rows:
        try:
            info = json.loads(m_raw) if isinstance(m_raw, str) else (m_raw or {})
            part = json.loads(p_raw) if isinstance(p_raw, str) else (p_raw or {})
        except Exception:
            continue
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and info.get("role") == "assistant":
            out["assistant_text"] += part.get("text", "") or ""
        if part.get("type") == "tool":
            out["tools"].append(part.get("tool") or "?")
        tk = info.get("tokens") or {}
        if isinstance(tk, dict):
            out["tokens_in"] += int(tk.get("input") or 0)
            out["tokens_out"] += int(tk.get("output") or 0)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="local-uncensored-4b/jarvis-mtp-lora")
    ap.add_argument("--question", default=QUESTION)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="ab-rehydrate-"))
    print(f"# A/B da injeção de resgate (model={args.model})")
    print(f"# diretório de teste (sem AGENTS.md): {tmp}")

    if args.dry_run:
        print("cmd:", ["opencode", "run", "--model", args.model, args.question])
        return 0

    resultados = {}
    for inject in (True, False):
        rotulo = "A_com_injecao" if inject else "B_sem_injecao"
        print(f"\n== {rotulo} ==", flush=True)
        r = run_once(args.model, args.question, inject, tmp)
        sid = sessao_recem(str(tmp))
        m = metricas(sid) if sid else {}
        txt = (m.get("assistant_text") or r["stdout"]).lower()
        mentioned = "rehydrat" in txt
        called = any("rehydrate" in t.lower() for t in m.get("tools", []))
        resultados[rotulo] = {
            "rc": r["rc"], "segundos": r["segundos"], "session": sid,
            "timeout": r.get("timeout", False),
            "mencionou_rehydrate": mentioned, "chamou_tool": called,
            "tools": m.get("tools", []),
            "tokens_in": m.get("tokens_in", 0), "tokens_out": m.get("tokens_out", 0),
            "falha_template": "System message must be at the beginning" in (r["stderr"] + r["stdout"]),
            "resposta": (m.get("assistant_text") or r["stdout"])[:600],
        }
        print(f"  rc={r['rc']} {r['segundos']}s sessão={sid} timeout={r.get('timeout')}")
        print(f"  mencionou_rehydrate={mentioned} chamou_tool={called}")
        print(f"  tokens in={m.get('tokens_in', 0)} out={m.get('tokens_out', 0)}")
        if resultados[rotulo]["falha_template"]:
            print("  !! FALHA DE TEMPLATE: a injeção criou um 2º system message")
        print(f"  resposta: {resultados[rotulo]['resposta'][:300]!r}")

    print("\n== VEREDITO ==")
    a = resultados["A_com_injecao"]
    b = resultados["B_sem_injecao"]
    print(f"  A (com injeção): mencionou={a['mencionou_rehydrate']} chamou={a['chamou_tool']} "
          f"tokens_in={a['tokens_in']}")
    print(f"  B (sem injeção): mencionou={b['mencionou_rehydrate']} chamou={b['chamou_tool']} "
          f"tokens_in={b['tokens_in']}")
    delta = a["tokens_in"] - b["tokens_in"]
    print(f"  delta tokens_in (custo da regra) = {delta:+d}")
    if a["timeout"] or b["timeout"]:
        print("  ATENÇÃO: um dos runs estourou o timeout (loop de tool call ou "
              "modelo lento) — ver tokens_in.")
    if a["mencionou_rehydrate"] and not b["mencionou_rehydrate"]:
        print("  RESULTADO: a injeção muda o comportamento (A cita, B não).")
    elif a["chamou_tool"] and not b["chamou_tool"]:
        print("  RESULTADO: a injeção muda o comportamento (A chama a tool, B não).")
    else:
        print("  RESULTADO: sem diferença observável neste par — medir de novo "
              "(ou o modelo já sabia pelo contexto).")
    print(json.dumps(resultados, ensure_ascii=False, indent=2)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
