"""KB-REGRESSION: knowledge->behavior suite (PHASE 12, host-only).

Roda no host (integração: bonsai + world_check real). No sandbox Nix
não executa. Uso:
    nix develop --command python3 -m jarvis.benchmarks.kb_regression [--n 3]

Cobre: RAG causal (C0 vs C2), lesson value-free (B0 vs B3), outage
(Qdrant-down -> lessons_unavailable). Registra model/surface/condition/
N/world. Anti-stale: rmtree pre-run + exemplos neutros.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.core.config import Config  # noqa: E402
from jarvis.core.eval_harness import EvalHarness, TaskTemplate  # noqa: E402


def run_agent(prompt, with_memory=False, tool_class=None):
    import jarvis.core.agent as _ag
    _ag.human_approve = lambda cmd: True
    from jarvis.runtime.agent_runtime import AgentRuntime
    rt = AgentRuntime(Config(), memory=(_make_mem() if with_memory else None),
                      agent_kwargs={"approve": True,
                                    "tool_class": tool_class})
    res = rt.run(prompt)
    tools = [{"name": s.get("tool"), "args_preview": s.get("args", ""),
              "output": ""} for s in res.steps]
    return {"response": res.response, "final_response": res.response,
            "tool_calls": tools, "tools_called": tools, "turns": res.turns,
            "exit_code": 0, "verdict": res.verdict}


def _make_mem():
    os.environ.setdefault("JARVIS_QDRANT_COLLECTION_MEMORIES",
                          "kb_regress_lessons")
    from jarvis.core.memory import EpisodicMemory
    return EpisodicMemory()


RAG_TASK = ("Per the Judge Reliability Harness digest, how many actionable "
            "findings for JARVIS are listed? Write ONLY that value "
            "(e.g. 42) as the entire content of {out} using write_file.")
RAG_CHUNK = ("Actionable findings for JARVIS: 1. Formatting perturbs more "
             "than semantics. 2. Ordinal worse than binary. 3. Agentic is "
             "not free-response. 4. Small model can judge well and cheap. "
             "5. Stochastic stability. That is 5 findings total.")

COUNT_TASK = ("Read {data}, count how many lines contain FAIL, and write "
              "ONLY that number as the entire content of {out} using "
              "write_file.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--results", default="/tmp/kb-regression.jsonl")
    args = ap.parse_args()
    harness = EvalHarness(results_dir="/tmp/kb-regression")
    out = {"model": "bonsai:8080", "n": args.n,
           "start": time.strftime("%Y-%m-%dT%H:%M:%S"), "runs": []}

    # R1: RAG causal
    for arm, pre in (("C0", ""), ("C2", "RETRIEVED CONTEXT:\n%s\n\n" % RAG_CHUNK)):
        ok = 0
        for rep in range(args.n):
            d = f"/tmp/kb-regression/rag-{arm}-{rep}"
            shutil.rmtree(d, ignore_errors=True); os.makedirs(d, exist_ok=True)
            path = d + "/answer.txt"
            t = TaskTemplate(id=f"kb-rag-{arm}-{rep}", description="rag causal",
                             prompt=pre + RAG_TASK.format(out=path),
                             success_criteria={"file_exists": path,
                                               "world_check": "grep -qx '5' %s" % path},
                             timeout_s=300)
            ok += harness.run_task(t, lambda p: run_agent(p)).success
        out["runs"].append({"dim": "rag", "arm": arm,
                            "world_ok": f"{ok}/{args.n}"})
        print(f"RAG {arm}: {ok}/{args.n}", flush=True)

    # R2: lesson value-free
    from jarvis.core.memory import EpisodicMemory
    mem = EpisodicMemory()
    mem.remember_lesson(task="count pattern lines in file, write number",
                        error_pattern="miscounted by estimating",
                        fix="read the file, list every matching line, count the list length, write that number")
    for arm, with_mem in (("B0", False), ("B3", True)):
        ok = 0
        for rep in range(args.n):
            d = f"/tmp/kb-regression/lesson-{arm}-{rep}"
            shutil.rmtree(d, ignore_errors=True); os.makedirs(d, exist_ok=True)
            with open(d + "/data.txt", "w") as fh:
                fh.write("".join("row %d %s\n" % (i, "FAIL" if i % 5 == 0 else "fine")
                                 for i in range(1, 41)))
            t = TaskTemplate(id=f"kb-lesson-{arm}-{rep}", description="lesson",
                             prompt=COUNT_TASK.format(data=d + "/data.txt", out=d + "/count.txt"),
                             success_criteria={"file_exists": d + "/count.txt",
                                               "world_check": "grep -qx '8' %s/count.txt" % d},
                             timeout_s=300)
            ok += harness.run_task(t, lambda p: run_agent(p, with_mem=with_mem)).success
        out["runs"].append({"dim": "lesson", "arm": arm,
                            "world_ok": f"{ok}/{args.n}"})
        print(f"LESSON {arm}: {ok}/{args.n}", flush=True)

    # Persistência pós-reset (PHASE 6): fato -> agente fresco
    from jarvis.core.memory import EpisodicMemory
    mem = EpisodicMemory()
    mem.remember_fact("the vault code is QX-77 (kb regression)")
    ok = 0
    for rep in range(args.n):
        d = f"/tmp/kb-regression/persist-{rep}"
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        t = TaskTemplate(
            id=f"kb-persist-{rep}", description="persistence",
            prompt=("Write ONLY the vault code as the entire content of "
                    f"{d}/out.txt using write_file. No other text."),
            success_criteria={"file_exists": f"{d}/out.txt",
                              "world_check": f"grep -qx 'QX-77' {d}/out.txt"},
            timeout_s=300)
        ok += harness.run_task(
            t, lambda p: run_agent(p, with_memory=True)).success
    out["runs"].append({"dim": "persist", "arm": "B2",
                        "world_ok": f"{ok}/{args.n}"})
    print(f"PERSIST B2: {ok}/{args.n}", flush=True)

    # R8-shape permanente (fronteira documentada, não gate: 0/3 em 21/09).
    # Recover + bytes exatos; world decide; nunca falha o script.
    r8c = "alpha-42 {\u00e9} tail  \nsecond line\tend\n"
    ok = 0
    for rep in range(args.n):
        d = f"/tmp/kb-regression/r8-{rep}"
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        with open(d + "/src.txt", "w") as fh:
            fh.write(r8c)
        t = TaskTemplate(
            id=f"kb-r8-{rep}", description="r8 boundary",
            prompt=(f"Read {d}/missing.txt; it is absent, so read {d}/src.txt "
                    f"instead and write IDENTICAL bytes to {d}/o.txt using "
                    f"write_file."),
            success_criteria={}, timeout_s=300)
        harness.run_task(t, lambda p: run_agent(p))
        try:
            w = open(d + "/o.txt", "rb").read() == r8c.encode()
        except OSError:
            w = False
        ok += w
    out["runs"].append({"dim": "r8-boundary", "arm": "B2",
                        "world_ok": f"{ok}/{args.n}"})
    print(f"R8-BOUNDARY: {ok}/{args.n}", flush=True)

    with open(args.results, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())