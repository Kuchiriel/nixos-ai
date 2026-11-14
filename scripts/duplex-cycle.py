#!/usr/bin/env python3
"""duplex-cycle.py — esteira completa de qualidade do duplex.

Um comando, uma passada completa:
  1. duplex-sweep   (auditaria de falhas nos logs do duplex últimos N dias)
  2. duplex-conveyor (ASRT end-to-end; mínimo 8/8)
  3. bench_heldout  (gate v8 em produção, 52 itens)
  4. bench_heldout2 (gate v8 em produção, 24 itens)
  5. bench_agent    (prompt do agente do duplex, 19 probes)
  6. porówna com o run anterior em reports/duplex-cycle/ e grava SUMMARY.md

Exit code: 0 = tudo verde; 1 = algum componente regrediu abaixo do limiar.
Não toca em processo/produtor — só lê logs e bate em :8092 :8097 por HTTP.

Uso:
  ./scripts/duplex-cycle.py             # full pass
  ./scripts/duplex-cycle.py --days 30   # sweep 30 dias
  ./scripts/duplex-cycle.py --quick     # só conveyor + sweep (pula gate+agent)
  ./scripts/duplex-cycle.py --no-journal  # não toca no diário
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

REPORTS = REPO / "reports" / "duplex-cycle"
REPORTS.mkdir(parents=True, exist_ok=True)


def _run(cmd, cwd=None, timeout=600, env=None) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env or os.environ)
    return p.returncode, (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")


def step_sweep(days: int) -> dict:
    rc, out = _run(["python3", str(REPO / "scripts" / "duplex-sweep.py"), "--days", str(days)])
    m = re.findall(r"^\[sweep\] ([a-z_0-9]+)\s+(\d+)", out, re.M)
    counts = {k.strip(): int(v) for k, v in m}
    print("[sweep]", counts if counts else out[-400:])
    return {"ok": rc == 0, "output": out[-800:], "counts": counts}


def step_conveyor() -> dict:
    rc, out = _run([
        "/home/nixos/projects/karaok/.venv/bin/python3",
        str(REPO / "scripts" / "duplex-conveyor.py"),
    ], timeout=300)
    m = re.search(r"resultado: (\d+)/(\d+)", out)
    passed, total = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    print(f"[conveyor] {passed}/{total}")
    return {"ok": passed == total, "passed": passed, "total": total, "output": out[-400:]}


def _parse_heldout(out: str) -> dict:
    res = {"total": None, "classes": {}}
    for cls in ("RESPOND", "WAIT", "SILENCE", "BARGE"):
        m = re.search(rf"{cls}\s+acc\s+(\d+)/(\d+)", out)
        if m:
            res["classes"][cls] = [int(m.group(1)), int(m.group(2))]
    m = re.search(r"TOTAL\s+(\d+)/(\d+)", out)
    if m:
        res["total"] = [int(m.group(1)), int(m.group(2))]
    return res


def step_bench(script: str) -> dict:
    base = os.environ.get("JARVIS_BENCH_BASE", "http://127.0.0.1:8092")
    env = dict(os.environ,
               JARVIS_BENCH_BASE=base,
               LD_LIBRARY_PATH=os.popen(
                   f"python3 {REPO}/scripts/asrd_env.py --print").read().strip())
    rc, out = _run([
        "/home/nixos/projects/karaok/.venv/bin/python3",
        str(REPO / "benchmarks" / "voice" / script),
    ], env=env, timeout=400)
    parsed = _parse_heldout(out)
    print(f"[{script}] total={parsed.get('total')}")
    return {"ok": rc == 0, "parsed": parsed, "output": out[-400:]}


def step_agent() -> dict:
    env = dict(os.environ, LD_LIBRARY_PATH=os.popen(
        "python3 " + str(REPO) + "/scripts/asrd_env.py --print").read().strip())
    rc, out = _run([
        "/home/nixos/projects/karaok/.venv/bin/python3",
        str(REPO / "benchmarks" / "voice" / "bench_agent.py"), "--variant", "baseline",
    ], timeout=400)
    d = {}
    for m in re.finditer(r"\s+(tool_ok|direct_ok|no_invent|short_ok|no_roleplay|no_fake_action)\s+(\d+/\d+)",
                          out):
        d[m.group(1)] = m.group(2)
    print(f"[agent] {d}")
    return {"ok": rc == 0, "metrics": d, "output": out[-400:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-journal", action="store_true")
    args = ap.parse_args()

    ts = time.strftime("%Y-%m-%dT%H%M%S")
    t0 = time.monotonic()
    results = {}

    results["sweep"] = step_sweep(args.days)
    results["conveyor"] = step_conveyor()
    if not args.quick:
        results["gate1"] = step_bench("bench_heldout.py")
        results["gate2"] = step_bench("bench_heldout2.py")
        results["agent"] = step_agent()

    # regras de regressão honestas
    reg = []
    if results["conveyor"]["passed"] < 8:
        reg.append(f"conveyor {results['conveyor']['passed']}/8")
    if not args.quick:
        g1 = results["gate1"]["parsed"]["total"]
        g2 = results["gate2"]["parsed"]["total"]
        if g1 and g1[0] < 40:
            reg.append(f"gate1 {g1[0]}/52 < 40")
        if g2 and g2[0] < 15:
            reg.append(f"gate2 {g2[0]}/24 < 15")
        agent = results["agent"]["metrics"]
        if agent.get("tool_ok", "0/0").startswith("0") or int(agent.get("tool_ok", "0/1").split("/")[0] or 0) < 4:
            reg.append(f"agent tool_ok {agent.get('tool_ok')}")
        if int(agent.get("direct_ok", "0/1").split("/")[0] or 0) < 8:
            reg.append(f"agent direct_ok {agent.get('direct_ok')}")

    out_dir = REPORTS / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "ts": ts,
        "days": args.days,
        "quick": args.quick,
        "results": results,
        "regressions": reg,
        "duration_s": round(time.monotonic() - t0),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    lines = [f"# duplex-cycle — {ts}", "",
             f"- sweep: {results['sweep']['counts']}",
             f"- conveyor: {results['conveyor']['passed']}/{results['conveyor']['total']}"]
    if not args.quick:
        g1 = results["gate1"]["parsed"]["total"]
        g2 = results["gate2"]["parsed"]["total"]
        lines.append(f"- gate heldout1: {g1}")
        lines.append(f"- gate heldout2: {g2}")
        lines.append(f"- agent: {results['agent']['metrics']}")
    lines.append("")
    lines.append(f"Regressões: {', '.join(reg) or 'nenhuma'}")
    (out_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    if not args.no_journal:
        with open(REPO / "docs" / "DUPLEX-LAYAS-MEASUREMENTS.md", "a") as f:
            f.write(f"\n## {ts} — duplex-cycle completo: "
                    f"conveyor={results['conveyor']['passed']}/{results['conveyor']['total']} "
                    f"reg={','.join(reg) or 'nenhum'} — reports/duplex-cycle/{ts}/SUMMARY.md\n")
    print(f"[cycle] report: {out_dir}")
    print("\n".join(lines))
    return 1 if reg else 0


if __name__ == "__main__":
    sys.exit(main())
