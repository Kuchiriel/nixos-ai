"""L9 runner (host-only integration; NOT in sandbox checkPhase).

Knowledge-persistent multi-step execution with arbitrary on-site rule.
Jail: /tmp/l9-run-* (R6 — never repo writes). World checker: l9_lib.
Uso: nix develop --command python3 -m jarvis.benchmarks.l9.run_l9 [n] [tool_class]
"""
import json
import os
import shutil
import sys

from jarvis.benchmarks.l9.l9_lib import check, fixture

import jarvis.core.agent as _ag
_ag.human_approve = lambda cmd: True

from jarvis.core.agent import Agent
from jarvis.core.config import Config
from jarvis.core.eval_harness import EvalHarness, TaskTemplate

PROMPT = """Workspace: {d}. It contains inventory.csv and manual.txt.
1. Inspect the workspace (list + read both files).
2. Follow the repair manual EXACTLY (it is site procedure).
3. Write {d}/report.json: array of {{"id","disposition","evidence"}} where
   evidence is the EXACT source CSV line for that row.
4. Write {d}/summary.txt with lines ok=N repaired=N quarantined=N
   skipped=N, plus one line starting 'observed-from-files:' (facts you
   read) and one line starting 'inferred:' (the rule you applied).
Use write_file with real content only. Repo writes forbidden."""


def run_agent(prompt, tool_class=None):
    agent = Agent(Config(), approve=True, memory=None, tool_class=tool_class)
    res = agent.run(prompt)
    tools = [{"name": s.get("tool"), "args_preview": s.get("args", ""),
              "output": ""} for s in res.steps]
    return {"response": res.final_response, "final_response": res.final_response,
            "tool_calls": tools, "tools_called": tools, "turns": res.turns,
            "exit_code": 0, "verdict": res.verdict}


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    tc = sys.argv[2] if len(sys.argv) > 2 else None
    tag = tc or "base"
    harness = EvalHarness(results_dir="/tmp/l9repo")
    ok = 0
    turns = []
    for rep in range(n):
        d = f"/tmp/l9repo-{tag}-{rep}"
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        fixture(d)
        t = TaskTemplate(
            id=f"l9-{tag}-{rep}", description="L9 multi-step",
            prompt=PROMPT.format(d=d),
            success_criteria={"file_exists": f"{d}/report.json"},
            timeout_s=600)
        r = harness.run_task(t, lambda p: run_agent(p, tc))
        err = check(d)
        r.criteria_met["l9_world"] = not err
        if err:
            r.success = False
        ok += r.success
        turns.append(r.total_turns)
        print(f"L9-{tag}-{rep}: {r.success} turns={r.total_turns} "
              f"check={err or 'OK'}", flush=True)
    out = {"world_ok": f"{ok}/{n}", "turns": turns}
    harness.save_results(f"l9-{tag}.jsonl")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())