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
        elif key == "file_absent":
            path, _, needle = spec.partition("::")
            try:
                ok = needle not in Path(path).read_text(encoding="utf-8",
                                                        errors="replace")
            except OSError:
                ok = True
        else:
            ok = False
        ok_parts.append(ok)
        if not ok:
            missed.append(f"{key}:{spec}")
    return (all(ok_parts) if ok_parts else False), missed


def run_suite(tasks: list[dict], approve: str = "y",
              timeout_s: int = 180, rounds: int = 2) -> list[dict]:
    results = []
    for t in tasks:
        if t.get("setup"):
            subprocess.run(t["setup"].split(" && "), shell=False,
                           capture_output=True) if False else None
            import shlex
            subprocess.run(["bash", "-c", t["setup"]],
                           capture_output=True, timeout=30)
        tool_calls_all = []
        msgs_all = []
        attempts = []
        world_ok = False
        missed = []
        t0 = time.monotonic()
        # Verifier-in-the-loop (§10 + FINDINGS harness-video): até `rounds`
        # tentativas; se o mundo reprovar E houver claims, o feedback vira
        # prompt da rodada seguinte. A mentira vira retry acionável.
        for attempt in range(1, max(1, rounds) + 1):
            # Mundo limpo POR ROUND (24/09 forense: round 1 criou um ARQUIVO
            # chamado 'inside' → mkdir dos rounds 2-3 morria ENOTDIR pra
            # sempre — round de feedback herda veneno do round anterior).
            if t.get("setup"):
                subprocess.run(["bash", "-c", t["setup"]],
                               capture_output=True, timeout=30)
            elif attempt > 1 and t.get("teardown"):
                subprocess.run(["bash", "-c", t["teardown"]],
                               capture_output=True, timeout=30)
            if attempt == 1:
                prompt = t["prompt"]
            else:
                prompt = (
                    f"{t['prompt']}\n\n"
                    f"FEEDBACK from an independent world check on your "
                    f"previous attempt (you claimed completion, but these "
                    f"are NOT satisfied): {'; '.join(missed)}.\n"
                    f"Continue and ACTUALLY complete the task — do not "
                    f"claim done until it truly exists."
                )
            r = run_task(prompt, timeout_s=timeout_s, approve=approve)
            out_raw = _ansi(str(r.get("output", "")))
            trans = r.get("transcript") or {}
            msgs = trans.get("messages", []) if isinstance(trans, dict) else []
            tools = []
            for m in msgs:
                for tc in (m.get("tool_calls") or []):
                    if isinstance(tc, dict) and tc.get("name"):
                        tools.append(tc["name"])
            world_ok, missed = check_world(t.get("world"), out_raw)
            attempts.append({"round": attempt, "world_ok": world_ok,
                             "missed": missed, "turns": len(msgs)})
            tool_calls_all.extend(tools)
            msgs_all.extend(msgs)
            if world_ok:
                break
        elapsed = time.monotonic() - t0
        results.append({
            "task_id": t["id"],
            "tier": t.get("tier", "?"),
            "world_ok": world_ok,
            "first_pass": attempts[0]["world_ok"] if attempts else False,
            "rounds_used": len(attempts),
            "missed": missed,
            "turns": len(msgs_all),
            "tool_calls": tool_calls_all,
            "wrong_tools": [],
            "false_done": bool(
                not world_ok and msgs_all
                and msgs_all[-1].get("role") == "assistant"
                and (msgs_all[-1].get("content") or "").strip()),
            "elapsed_s": round(elapsed, 1),
            "rc": r.get("rc"),
        })
        # teardown final: limpa o mundo do último round
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


def preflight(model: str = "bonsai", base_url: str = None) -> None:
    """ABORTA se a infra do LLM não está de pé (24/09 forense: um server
    órfão de bench segurava 4.5GB, o router não carregava o bonsai, tudo
    deu 500 e a suíte somou 0/3 como se fosse falha do MODELO). Regra:
    /health sozinho NÃO basta (o b10735 responde ok mesmo com o modelo
    unloaded) — exige uma completion real.
    """
    import json as _json
    import urllib.request as _u
    base = (base_url or os.environ.get(
        "JARVIS_LLM_BASE_URL", "http://127.0.0.1:8080/v1")).rstrip("/")
    body = _json.dumps({"model": model, "max_tokens": 16,
                        "chat_template_kwargs": {"enable_thinking": False},
                        "messages": [{"role": "user", "content": "ok"}]}
                       ).encode()
    req = _u.Request(f"{base}/chat/completions", data=body,
                      headers={"Content-Type": "application/json"})
    try:
        with _u.urlopen(req, timeout=120) as r:
            out = _json.loads(r.read().decode())
        msg = (out.get("choices") or [{}])[0].get("message", {})
        # `content` vazio com `reasoning_content` = o modelo gastou o budget
        # pensando (Qwen3/MoE) — ainda é evidência de que SERVE (24/09).
        if not ((msg.get("content") or "").strip()
                or (msg.get("reasoning_content") or "").strip()):
            raise ValueError("resposta vazia (sem content nem reasoning)")
    except Exception as e:
        raise SystemExit(
            f"PREFLIGHT FALHOU ({type(e).__name__}: {e})\n"
            f"LLM em {base} (model={model}) não está servindo. "
            f"Abortando SEM medir — score de modelo com infra caída é "
            f"veredito inválido (incidente 24/09).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=["easy", "medium", "hard", "ptbr", "all"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--rounds", type=int, default=2,
                    help="tentativas máximas c/ feedback de mundo (1 = antigo)")
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
    if args.tier and args.tier != "all":
        tasks = [t for t in tasks if t["tier"] == args.tier]

    preflight(model=os.environ.get("JARVIS_LLM_MODEL", "bonsai"))

    results = run_suite(tasks, rounds=args.rounds)
    summary = summarize(results)
    stamp = time.strftime("%Y-%m-%d__%H-%M-%S")
    out_path = args.out or f"/tmp/opencode/harness-suite-{stamp}.json"
    with open(out_path, "w") as f:
        json.dump({"ts": stamp, "summary": summary, "results": results},
                  f, ensure_ascii=False, indent=2)

    print(f"=== SUITE {stamp} ===")
    for tier, s in summary["by_tier"].items():
        print(f"  {tier}: {s['ok']}/{s['n']} world_ok")
    first_pass = sum(1 for r in results if r.get("first_pass"))
    retried = sum(1 for r in results
                  if r.get("rounds_used", 1) > 1 and r["world_ok"])
    print(f"  TOTAL: {summary['world_ok']}/{summary['total']} | "
          f"first_pass={first_pass} | salvos_por_retry={retried} | "
          f"false_done={summary['false_done']} | "
          f"avg={summary['avg_elapsed_s']}s")
    print(f"salvo: {out_path}")


if __name__ == "__main__":
    main()
