#!/usr/bin/env python3
"""loop-close.py — semente do laço que se fecha (F-supervisor, 26/09).

O "real deal" além do template: a máquina que transforma evals em
melhoria. v1 = mede → classifica → propõe (não aplica sozinho):

  1. Roda a bateria (--engine runtime) no subset.
  2. Classifica cada falha na taxonomia (contexto/restrição/verificação/
     planejamento/modelo) a partir de missed+turns+tools.
  3. Falha de HARNESS vira lesson candidata (--apply-lessons grava).
     Falha de MODEL vira evidência p/ troca de modelo.
  4. Salva relatório datado (o diff entre linhas = a melhora).

Uso:
  python3 scripts/loop-close.py --tier easy --rounds 1 [--apply-lessons]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

SYS = Path(__file__).resolve().parent
sys.path.insert(0, str(SYS))

import importlib.util as _ilu  # harness-suite.py tem hífen (não importável)

_spec = _ilu.spec_from_file_location("harness_suite", SYS / "harness-suite.py")
HS = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(HS)

# Classe → arquivos-alvo p/ patch do nightwatch (pequenos e precisos).
_CLASS_TARGETS = {
    "verification": ["modules/ai/jarvis/src/jarvis/core/completion.py",
                     "modules/ai/jarvis/tests/test_completion.py"],
    "constraint": ["modules/ai/jarvis/src/jarvis/core/devtools.py"],
    "context": ["modules/ai/jarvis/src/jarvis/runtime/context.py"],
    "planning": ["modules/ai/jarvis/src/jarvis/runtime/agent_runtime.py"],
}


def file_tasks(results: list[dict], project: str = "nixos-ai") -> int:
    """Falha de HARNESS vira Task do nightwatch (risk medium = com review).

    Acceptance = reproduzir a task da bateria (mundo decide). Retorna nº.
    """
    sys.path.insert(0, str(Path.home() /
                           "projects/nixos-ai/modules/ai/jarvis/src"))
    from nightwatch.task_queue import TaskQueue, Task
    q = TaskQueue(project=project)
    n = 0
    for r in results:
        cls = r.get("failure_class", "")
        if cls not in _CLASS_TARGETS:
            continue
        tid = r["task_id"]
        desc = (f"[loop-close] Falha {cls} em {tid}: {r.get('failure_why','')} "
                f"(missed={r.get('missed')}). Reproduzir: "
                f"python3 scripts/loop-close.py --tier {r.get('tier','?')} "
                f"--rounds 1 --only {tid}. Corrigir o componente sem quebrar "
                f"os testes existentes; a task só completa se a bateria voltar "
                f"a passar.")
        t = Task(id=f"lc-{int(time.time())}-{tid.replace('/', '-')[:24]}",
                 project=project, description=desc, priority=4,
                 risk="medium", target_files=_CLASS_TARGETS[cls][:2],
                 acceptance_criteria=f"loop-close --only {tid} world_ok",
                 language="python")
        if q.add_task(t):
            n += 1
    print(f"LOOP-CLOSE: {n} tasks arquivadas p/ o nightwatch")
    return n


def classify(result: dict) -> tuple[str, str]:
    """missed+turns+tools → (classe, motivo). Taxonomia deepset adaptada."""
    if result.get("world_ok"):
        return "ok", ""
    missed = " ".join(result.get("missed", [])).lower()
    turns = result.get("turns", 0)
    if "output_contains" in missed:
        return "verification", "resposta sem o conteúdo (juízo, não mundo)"
    if "file_exists" in missed or "file_absent" in missed:
        return "planning", "arquivo esperado nunca criado (coreografia)"
    if "file_contains" in missed or "file_equals" in missed:
        return "constraint", "conteúdo fora do contrato (formato/valor)"
    if turns >= 8:
        return "context", "teto de turnos (perdeu o fio?)"
    if not result.get("tool_calls"):
        return "model", "zero tool calls (alucinação sem agir)"
    return "model", "falha sem assinatura de harness"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="easy")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--only", default=None)
    ap.add_argument("--apply-lessons", action="store_true",
                    help="grava lesson candidata p/ falhas de HARNESS")
    ap.add_argument("--file-tasks", action="store_true",
                    help="arquiva falhas de HARNESS como tasks do nightwatch")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    challenges = json.load(open(SYS / "harness-challenges.json"))
    tasks = [t for t in challenges["tasks"] if t.get("tier") == args.tier]
    if args.only:
        tasks = [t for t in tasks if args.only in t["id"]]
    tasks, bad = HS.preflight_tasks(tasks)
    print(f"LOOP-CLOSE: {len(tasks)} tasks, {len(bad)} reprovadas no oráculo")

    t0 = time.monotonic()
    results = HS.run_suite(tasks, rounds=args.rounds, engine="runtime")
    for r in results:
        cls, why = classify(r)
        r["failure_class"] = cls
        r["failure_why"] = why

    by_class: dict[str, int] = {}
    for r in results:
        by_class[r["failure_class"]] = by_class.get(r["failure_class"], 0) + 1
    ok = by_class.get("ok", 0)
    print(f"LOOP-CLOSE: {ok}/{len(results)} ok {by_class} "
          f"({time.monotonic() - t0:.0f}s)")

    lessons: list[dict] = []
    for r in results:
        if r["failure_class"] in ("planning", "constraint", "verification",
                                  "context"):
            lessons.append({
                "task": f"loop-close {r['task_id']} ({r['failure_class']})",
                "error_pattern": f"{r['task_id']}: {r['failure_why']} "
                                 f"(missed={r.get('missed')})",
                "fix": "INVESTIGAR: falha com assinatura de harness — "
                       "reproduzir, localizar componente, patch + re-medir",
            })
    if lessons:
        print(f"LOOP-CLOSE: {len(lessons)} lessons candidatas (harness)")
        for le in lessons:
            print(f"  - [{le['task']}] {le['error_pattern'][:100]}")
        if args.apply_lessons:
            sys.path.insert(0, str(Path.home() /
                                   "projects/nixos-ai/modules/ai/jarvis/src"))
            from jarvis.core.config import Config
            from jarvis.core.memory import EpisodicMemory
            mem = EpisodicMemory(Config())
            for le in lessons:
                mem.remember_lesson(task=le["task"],
                                    error_pattern=le["error_pattern"],
                                    fix=le["fix"])
            print(f"LOOP-CLOSE: {len(lessons)} lessons GRAVADAS")
    else:
        print("LOOP-CLOSE: nenhuma falha de harness (só model/ok)")

    if args.file_tasks:
        file_tasks(results)

    stamp = time.strftime("%Y-%m-%d__%H-%M-%S")
    out = args.out or f"/tmp/opencode/loop-close-{stamp}.json"
    with open(out, "w") as f:
        json.dump({"ts": stamp, "tier": args.tier, "engine": "runtime",
                   "by_class": by_class, "results": results,
                   "lessons": lessons}, f, ensure_ascii=False, indent=2)
    print(f"LOOP-CLOSE salvo: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
