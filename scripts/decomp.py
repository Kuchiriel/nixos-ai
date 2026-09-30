#!/usr/bin/env python3
"""decomp.py — o gargalo é decomposição ou execução?

29/29, continuação do pipeline. A hypothese refinada: o executor não
falha por não SABER a resposta (ele acerta o diagnóstico quando
guinchado), e não falha por não QUERER executar — falha em converter
plano em sequência de tool calls.

Teste decisivo: **executar o ACT do plano mecanicamente, sem modelo
no meio.** Se o harness sozinho executa o plano do MoE e acerta, a
decomposição é o gargalo e a correção é uma tool de plano. Se falha
também, o gargalo é o plano em si (conteúdo), não a decomposição.

Este script não adapta o runtime: orquestra dev_once numa fase e
rodada determinística na outra, e reporta as duas.
"""
from __future__ import annotations

import importlib.util as _iu
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path("/tmp/opencode/decomp")
STRATEGIST_URL = "http://127.0.0.1:8084"
STRATEGIST_MODEL = "qwen-moe"


def _mk():
    p = Path(__file__).resolve().parent / "mission-kit.py"
    s = _iu.spec_from_file_location("mission_kit", p)
    m = _iu.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _pl():
    p = Path(__file__).resolve().parent / "pipeline.py"
    s = _iu.spec_from_file_location("pipeline", p)
    m = _iu.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def extract_act(plan: str) -> str:
    """Bloco ACT cru: o texto é para o SHELL interpretar, não para eu
    adivinhar fronteiras de comando. O plano pode ter comando multi-
    linha (`python3 -c "` abre e fecha aspas em linhas separadas) —
    regex por linha erra isso. Devolvo o bloco inteiro e deixo o bash
    fazer o parsing, que é o executor correto de qualquer forma.
    """
    lines = plan.splitlines()
    try:
        i = next(k for k, l in enumerate(lines)
                 if l.strip().startswith("ACT:"))
    except StopIteration:
        return ""
    body = lines[i][lines[i].index("ACT:") + 4:].strip()
    tail: list[str] = []
    for l in lines[i + 1:]:
        t = l.strip()
        if re.match(r"^(VERIFY|OBSERVE|REASON)\s*:", t):
            break
        if t.startswith("```"):  # fecha/abre cerca
            continue
        tail.append(l)
    return (body + "\n" + "\n".join(tail)).strip()


def run_mechanical(act: str, cwd: Path) -> dict:
    """Executa o bloco ACT inteiro — sem LLM no meio.

    Um bloco ACT é um script (pode ter python3 -c multilinha, &&, etc.).
    Bash interpreta o bloco inteiro de uma vez, que é o que um agente
    faria ao colar o plano num terminal.
    """
    try:
        p = subprocess.run(["bash", "-c", act], cwd=cwd,
                           capture_output=True, text=True, timeout=90)
        return {"cmd": act[:70], "rc": p.returncode,
                "out": p.stdout[-160:], "err": p.stderr[-160:]}
    except subprocess.TimeoutExpired:
        return {"cmd": act[:70], "rc": 124, "out": "", "err": "timeout"}


def main() -> int:
    mk, pl = _mk(), _pl()
    task = sys.argv[1] if len(sys.argv) > 1 else "T3-synthesis"
    ROOT.mkdir(parents=True, exist_ok=True)

    d = ROOT / f"{task}-mech"
    if d.exists():
        for f in d.iterdir():
            f.unlink()
    d.mkdir(parents=True, exist_ok=True)
    spec = mk.TASKS[task](d)

    print(f"=== {task} — esperado: {spec['expected'].strip()}")
    plan = pl.make_plan(spec["task"], d, STRATEGIST_MODEL)
    Path(ROOT / f"plan-{task}.txt").write_text(plan)
    act = extract_act(plan)
    print(f"\nACT extraído:\n{act[:400] if act else '(vazio)'}")

    if not act:
        print("\nRESULTADO: nenhum comando mecânico extraído do plano")
        return 1

    res = run_mechanical(act, d)
    print(f"\nexecução mecânica (sem modelo): rc={res['rc']}")
    if res["out"].strip():
        print("  out:", res["out"].strip()[:100])
    if res["err"].strip():
        print("  err:", res["err"].strip()[:100])

    ans = d / "answer.txt"
    got = ans.read_text() if ans.exists() else None
    ok = got is not None and got.strip() == spec["expected"].strip()
    print(f"\n{'ACERTO' if ok else 'ERRO'} — answer.txt = "
          f"{(got or '(sem arquivo)').strip()[:40]!r}")
    (ROOT / f"mech-{task}.json").write_text(json.dumps(
        {"task": task, "act": act, "result": res, "ok": ok,
         "got": got, "expected": spec["expected"]}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
