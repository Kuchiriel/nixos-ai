#!/usr/bin/env python3
"""harness-suite.py — desafios progressivos p/ jarvis dev (E2E real).

Reusa scripts/ux_driver.py (PTY real + transcript) + verificação
independente do mundo (ux_world style). Prompts NATURAIS, sem hints
(protocolo 14). Resultados JSONL com timestamp — trackea evolução
(baseline → modificações → comparar; sistema que evolui, não regride).

Uso:
  python3 scripts/harness-suite.py [--tier easy|medium|hard] [--out FILE]
  python3 scripts/harness-suite.py --compare FILE1 FILE2
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ux_driver import run_task


def _ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def check_world(world: dict, output: str) -> tuple[bool, list[str]]:
    """Verificação independente: mundo, não resposta (§10 WORLD STATE)."""
    ok_parts, missed = [], []
    for key, spec in (world or {}).items():
        if key == "file_exists":
            ok = os.path.isfile(spec)
        elif key == "file_contains":
            path, _, needle = spec.partition("::")
            try:
                ok = needle in Path(path).read_text(encoding="utf-8",
                                                     errors="replace")
            except OSError:
                ok = False
        elif key == "output_contains":
            ok = spec.lower() in output.lower()
        else:
            ok = False
        ok_parts.append(ok)
        if not ok:
            missed.append(f"{key}:{spec}")
    return (all(ok_parts) if ok_parts else False), missed


def run_suite(tasks: list[dict], approve: str = "y",
              timeout_s: int = 180) -> list[dict]:
    results = []
    for t in tasks:
        if t.get("setup"):
            subprocess.run(t["setup"].split(" && "), shell=False,
                           capture_output=True) if False else None
            import shlex
            subprocess.run(["bash", "-c", t["setup"]],
                           capture_output=True, timeout=30)
        out_raw = ""
        tool_calls = 0
        t0 = time.monotonic()
        r = run_task(t["prompt"], timeout_s=timeout_s, approve=approve)
        elapsed = time.monotonic() - t0
        out_raw = _ansi(str(r.get("output", "")))
        # tool calls reais do transcript (estrutura FLAT: name+args)
        trans = r.get("transcript") or {}
        msgs = trans.get("messages", []) if isinstance(trans, dict) else []
        tools = []
        for m in msgs:
            for tc in (m.get("tool_calls") or []):
                if isinstance(tc, dict) and tc.get("name"):
                    tools.append(tc["name"])
        world_ok, missed = check_world(t.get("world"), out_raw)
        results.append({
            "task_id": t["id"],
            "tier": t.get("tier", "?"),
            "world_ok": world_ok,
            "missed": missed,
            "turns": len(msgs),
            "tool_calls": tools,
            "wrong_tools": [],
            "false_done": bool(
                not world_ok and msgs
                and msgs[-1].get("role") == "assistant"
                and (msgs[-1].get("content") or "").strip()),
            "elapsed_s": round(elapsed, 1),
            "rc": r.get("rc"),
        })
        # teardown
        if t.get("teardown"):
            subprocess.run(["bash", "-c", t["teardown"]],
                           capture_output=True, timeout=30)
    return results


def summarize(results: list[dict]) -> dict:
    by_tier: dict[str, dict[str, int]] = {}
    for r in results:
        tier = r["tier"]
        by_tier.setdefault(tier, {"n": 0, "ok": 0})
        by_tier[tier]["n"] += 1
        by_tier[tier]["ok"] += 1 if r["world_ok"] else 0
    return {
        "total": len(results),
        "world_ok": sum(1 for r in results if r["world_ok"]),
        "false_done": sum(1 for r in results if r["false_done"]),
        "by_tier": by_tier,
        "avg_elapsed_s": round(
            sum(r["elapsed_s"] for r in results) / max(1, len(results)), 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=["easy", "medium", "hard"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"))
    args = ap.parse_args()

    if args.compare:
        old = json.load(open(args.compare[0]))
        new = json.load(open(args.compare[1]))
        print(f"EVOLUÇÃO: {old['summary']['world_ok']}/{old['summary']['total']}"
              f" → {new['summary']['world_ok']}/{new['summary']['total']}")
        for r_new in new.get("results", []):
            r_old = next((r for r in old.get("results", [])
                          if r["task_id"] == r_new["task_id"]), {})
            delta = r_new["world_ok"] - r_old.get("world_ok", 0)
            mark = "↑" if delta > 0 else ("↓" if delta < 0 else "=")
            print(f"  {mark} {r_new['task_id']} ({r_new['tier']}): "
                  f"{r_old.get('world_ok', 0)} → {r_new['world_ok']}")
        return

    tasks = json.load(open(Path(__file__).parent / "harness-challenges.json"))
    tasks = tasks["tasks"]
    if args.tier:
        tasks = [t for t in tasks if t["tier"] == args.tier]

    results = run_suite(tasks)
    summary = summarize(results)
    stamp = time.strftime("%Y-%m-%d__%H-%M-%S")
    out_path = args.out or f"/tmp/opencode/harness-suite-{stamp}.json"
    with open(out_path, "w") as f:
        json.dump({"ts": stamp, "summary": summary, "results": results},
                  f, ensure_ascii=False, indent=2)

    print(f"=== SUITE {stamp} ===")
    for tier, s in summary["by_tier"].items():
        print(f"  {tier}: {s['ok']}/{s['n']} world_ok")
    print(f"  TOTAL: {summary['world_ok']}/{summary['total']} | "
          f"false_done={summary['false_done']} | "
          f"avg={summary['avg_elapsed_s']}s")
    print(f"salvo: {out_path}")


if __name__ == "__main__":
    main()
