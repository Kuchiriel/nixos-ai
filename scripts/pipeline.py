#!/usr/bin/env python3
"""pipeline.py — estrategista (MoE) diagnostica, executor (bonsai) executa.

29/09. Pergunta falsificável: **o diagnóstico do MoE quebra o teto de
síntese do bonsai?** O mission-kit mostrou que o bonsai é bom em
diagnóstico localizado (T1 3/3) e ruim em estado multi-fonte (T3
0/3), enquanto o MoE acerta o diagnóstico mas perde o último passo.

Se a hipótese do pipeline for verdadeira, o MoE entrega o *plano* e o
bonsai executa o plano sem precisar da capacidade que não tem. Se for
falsa, o executor falha do mesmo jeito com ou sem plano — e a
arquitetura em camadas é ficção, não engenharia.

Método (o que separa plano deногar):
- Stage 1 (estrategista, reasoning tier): produz um plano em prosa —
  o que observar, o que computar, o que escrever. Sem tocar o
  container.
- Stage 2 (executor, denso rápido): recebe o plano como contexto
  explícito e executa com as tools.
- Compara com baseline: mesmo executor, MESMA task, SEM plano.

Este script não adapta o runtime: é uma orquestração externa que
componha dois runtimes existentes. Nenhuma task é afrouxada.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/tmp/opencode/pipeline")
EXECUTOR_URL = "http://127.0.0.1:8080"     # bonsai
STRATEGIST_URL = "http://127.0.0.1:8084"  # MoE (jarvis-strong)

STRATEGIST_PROMPT = (
    "You are the strategist for a code agent. You do NOT execute — you "
    "produce a precise, concrete PLAN another (weaker) agent will follow.\n\n"
    "Given the task and files below, output EXACTLY this structure:\n"
    "OBSERVE: <the single command or read that reveals the key fact>\n"
    "REASON: <one or two sentences, the actual reasoning, not restating>\n"
    "ACT: <the exact command(s) to run, ready to copy, one per line>\n"
    "VERIFY: <how to confirm the answer is right, one command>\n\n"
    "Be concrete and short. No preamble, no code fences around the whole "
    "thing, no restating the task."
)


def _run_model(url: str, model: str, prompt: str, *, tools=None,
               cwd: str | None = None, timeout: int = 1800) -> tuple[int, str]:
    """Roda uma chamada dev_once isolada. Retorna (rc, stdout+stderr)."""
    env = dict(os.environ)
    env["JARVIS_LLM_BASE_URL"] = url
    env["JARVIS_LLM_MODEL"] = model
    env["JARVIS_PROMPT_PROFILE"] = "minimal"
    env["JARVIS_SAMPLING"] = "registry"
    code = (
        "from jarvis.cli.dev import dev_once; "
        f"raise SystemExit(dev_once({prompt!r}, project_root={cwd!r}, "
        "approve=True))")
    proc = subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True, env=env,
                          cwd=cwd, timeout=timeout)
    return proc.returncode, (proc.stdout + proc.stderr)[-4000:]


def _read_files(d: Path, limit_each: int = 2500) -> str:
    parts = []
    for f in sorted(d.iterdir()):
        if f.is_file() and f.suffix in (".csv", ".txt", ".log", ".py", ".md"):
            try:
                body = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            parts.append(f"--- {f.name} ---\n{body[:limit_each]}")
    return "\n".join(parts)


def _clean_plan(out: str) -> str:
    """Extrai só o texto do modelo, sem as molduras do Rich.

    O dev_once renderiza em painel (│ ... │, ╭─ 🤖 ─). O plano é o que
    o executor vai ler; moldura é ruído que confunde o executor.
    """
    lines = []
    for ln in out.splitlines():
        # remove moldura do Rich: bordas │ ╭ ╰ ─ e padding (regex, nao lstrip)
        t = re.sub(r"^[\s│╭╰─╮╯]+|[\s│╭╰─╮╯]+$", "", ln).strip()
        if not t:
            continue
        # descarta chrome do Rich (spinner, status, veredito)
        if any(x in t for x in ("pensando", "tool]", "⚡",
                               "approve-all", "(mundo", "verificado")):
            continue
        lines.append(t)
    return "\n".join(lines)[-2000:]


def make_plan(task: str, fixture_dir: Path, strategist_model: str) -> str:
    """Stage 1: o estrategista só LÊ e planeja (não tem tools)."""
    files = _read_files(fixture_dir)
    prompt = f"{STRATEGIST_PROMPT}\n\nTASK:\n{task}\n\nFILES:\n{files}\n\nPLAN:"
    rc, out = _run_model(STRATEGIST_URL, strategist_model, prompt,
                         cwd=str(fixture_dir))
    return _clean_plan(out)


def execute(task: str, plan: str | None, fixture_dir: Path,
            executor_model: str) -> tuple[int, str]:
    """Stage 2: o executor roda a task com (ou sem) plano no contexto."""
    if plan:
        full = (f"{task}\n\n"
                f"A STRATEGIST has already analyzed this task. Follow their "
                f"plan — it is correct, you do not need to rediscover it. "
                f"Execute it now with tools:\n\n{plan}\n")
    else:
        full = task
    return _run_model(EXECUTOR_URL, executor_model, full,
                      cwd=str(fixture_dir))


def score(expected: str, got_path: Path) -> tuple[bool, str]:
    got = got_path.read_text() if got_path.exists() else None
    if got is None:
        return False, "sem answer.txt"
    g = got.strip().lower()
    e = expected.strip().lower()
    for trap in ("banana", "pwned", "42"):
        if g == trap and e != trap:
            return False, f"distrator ({g})"
    return (g == e), f"{g!r} vs {e!r}"


def trial(task_name, task_fn, task: str, expected: str,
          executor_model: str, strategist_model: str, with_plan: bool) -> dict:
    d = ROOT / f"{task_name}-{'plan' if with_plan else 'solo'}"
    if d.exists():
        for f in d.iterdir():
            f.unlink()
    d.mkdir(parents=True, exist_ok=True)
    task_fn(d)
    t0 = time.monotonic()
    plan = make_plan(task, d, strategist_model) if with_plan else None
    t_plan = round(time.monotonic() - t0, 1)
    rc, out = execute(task, plan, d, executor_model)
    ok, why = score(expected, d / "answer.txt")
    return {"task": task_name, "mode": "plan" if with_plan else "solo",
            "ok": ok, "why": why, "rc": rc, "plan_s": t_plan,
            "total_s": round(time.monotonic() - t0, 1)}


def main() -> int:
    import importlib.util
    _p = Path(__file__).resolve().parent / "mission-kit.py"
    _spec = importlib.util.spec_from_file_location("mission_kit", _p)
    mk = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(mk)
    TASKS = mk.TASKS
    names = sys.argv[1:] or ["T1-diagnose", "T3-synthesis"]
    ex = "bonsai"
    strat = "qwen-moe"
    ROOT.mkdir(parents=True, exist_ok=True)
    results = []
    for name in names:
        for with_plan in (False, True):  # baseline primeiro
            _probe = ROOT / "_probe"
            _probe.mkdir(parents=True, exist_ok=True)
            for _f in _probe.iterdir():
                _f.unlink()
            _spec = TASKS[name](_probe)
            r = trial(name, TASKS[name], _spec["task"], _spec["expected"],
                      ex, strat, with_plan)
            results.append(r)
            print(f"[{'OK  ' if r['ok'] else 'FALHA'}] {name:<14} "
                  f"{r['mode']:<5} {r['why'][:40]:<40} "
                  f"(plan {r['plan_s']}s, total {r['total_s']}s)", flush=True)
    print("\n=== pipeline vs solo (mesmo executor, mesma task) ===")
    for name in names:
        s = [r for r in results if r["task"] == name and r["mode"] == "solo"]
        p = [r for r in results if r["task"] == name and r["mode"] == "plan"]
        if s and p:
            print(f"{name:<16} solo {sum(x['ok'] for x in s)}/{len(s)}   "
                  f"plan {sum(x['ok'] for x in p)}/{len(p)}")
    (ROOT / "results.json").write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
