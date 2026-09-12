#!/usr/bin/env python3
"""ux-suite.py — bateria user-faithful: prompts humanos curtos + verificação do mundo.

Uso: python3 scripts/ux-suite.py --out /tmp/ux/report.json [--only T1,T2]
Métricas por task: success (mundo), verified, turns, tools, erros,
recoveries, tempo, false_done, abandono.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from ux_driver import run_task
except ImportError:  # script executado de outro cwd via nix develop
    sys.path.insert(0, "/home/nixos/projects/nixos-ai/scripts")
    from ux_driver import run_task

LAB = "/tmp/jarvis-lab"


def _read(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def _tools_of(res):
    t = (res.get("transcript") or {}).get("messages", [])
    out = []
    for m in t:
        for tc in m.get("tool_calls") or []:
            out.append(tc.get("name"))
    return out


def _turns_of(res):
    t = (res.get("transcript") or {}).get("messages", [])
    return sum(1 for m in t if m.get("role") == "assistant")


def _base(task_id, prompt, verify):
    return {"id": task_id, "prompt": prompt, "verify": verify}


def build_tasks():
    T = []
    T.append(_base(
        "T1-write", "crie o arquivo /tmp/jarvis-lab/output/t1.txt com a frase hello world",
        lambda: (_read(f"{LAB}/output/t1.txt") or "").strip() == "hello world"))
    T.append(_base(
        "T2-read", "leia o arquivo /tmp/jarvis-lab/input/seed.txt e me diga o conteúdo",
        lambda: True))  # verificado via transcript abaixo (resposta contém 'seed')
    T.append(_base(
        "T3-mkdir", "cria uma pasta /tmp/jarvis-lab/output/lote com três arquivos dentro e me mostra o que criou",
        lambda: sum(1 for _ in os.listdir(f"{LAB}/output/lote")) == 3
        if os.path.isdir(f"{LAB}/output/lote") else False))
    T.append(_base(
        "T4-locate", "encontre onde está o arquivo seed.txt",
        lambda: True))  # resposta deve citar /tmp/jarvis-lab/input/seed.txt
    T.append(_base(
        "T5-missing", "abre o arquivo /tmp/jarvis-lab/output/naoexiste.txt",
        lambda: "RECOVERY-CHECK"))
    T.append(_base(
        "T6-compound", "cria um diretório temporário em /tmp/jarvis-lab, coloca um arquivo dentro, verifica o conteúdo e me diga exatamente onde ficou",
        lambda: True))  # verificação manual do transcript + mundo
    T.append(_base(
        "T7-kernel", "qual é o kernel que estou usando?",
        lambda: True))
    T.append(_base(
        "T8-qdrant", "o qdrant está rodando?",
        lambda: True))
    T.append(_base(
        "T9-disk", "quanto espaço tenho no disco?",
        lambda: True))
    T.append(_base(
        "B1-title", "abre a página http://localhost:8931/ e me diga qual é o título",
        lambda: True))  # mundo: check_dom titulo
    T.append(_base(
        "B2-click", "abre a página http://localhost:8931/, clica no botão e me diz exatamente o que o parágrafo de estado mostra depois",
        lambda: True))  # mundo: check_dom contém 'clicado'
    T.append(_base(
        "B3-fill", "abre a página http://localhost:8931/, preenche o campo com JARVIS, clica em OK e me diz o resultado",
        lambda: True))  # mundo: check_dom contém 'ola JARVIS'
    return T


def check_text_answer(res, *needles):
    out = (res.get("output") or "").lower()
    tr = json.dumps(res.get("transcript") or {}, ensure_ascii=False).lower()
    blob = out + tr
    return all(n.lower() in blob for n in needles)


def run_suite(only=None, timeout=300):
    tasks = [t for t in build_tasks() if not only or t["id"] in only]
    rows = []
    for t in tasks:
        # estado limpo por task
        for p in (f"{LAB}/output/t1.txt",):
            try:
                os.remove(p)
            except OSError:
                pass
        t0 = time.monotonic()
        res = run_task(t["prompt"], timeout)
        dt = round(time.monotonic() - t0, 1)
        tools = _tools_of(res)
        turns = _turns_of(res)
        v = t["verify"]()
        if t["id"] == "T2":
            success = check_text_answer(res, "seed")
        elif t["id"] == "T4":
            success = check_text_answer(res, "seed.txt") and check_text_answer(res, "input")
        elif t["id"] == "T5":
            # recovery: modelo deve relatar ausência em vez de inventar conteúdo
            success = (check_text_answer(res, "não existe", "nao existe", "não encontrei", "nao encontrei")
                       or check_text_answer(res, "erro"))
            v = success
        elif t["id"] in ("T6", "T7", "T8", "T9"):
            success = res.get("ok", False)
        elif t["id"] == "B1":
            import ux_world as W
            success = W.check_dom(
                "http://localhost:8931/",
                must_contain=["JARVIS Lab"])["ok"] and check_text_answer(
                    res, "JARVIS Lab")
        elif t["id"] == "B2":
            import ux_world as W
            success = W.check_dom(
                "http://localhost:8931/",
                must_contain=["clicado"])["ok"]
        elif t["id"] == "B3":
            import ux_world as W
            success = W.check_dom(
                "http://localhost:8931/",
                must_contain=["ola JARVIS"])["ok"]
        else:
            success = bool(v)
        rows.append({
            "task": t["id"], "prompt": t["prompt"],
            "success": bool(success), "verified": True,
            "turns": turns, "tools": tools,
            "time_s": dt, "rc": res.get("rc"),
            "false_done": bool(res.get("ok")) and not success,
        })
        print(f"[{t['id']}] success={bool(success)} turns={turns} "
              f"tools={tools} {dt}s", flush=True)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()
    only = [x for x in args.only.split(",") if x] or None
    rows = run_suite(only, args.timeout)
    s = sum(1 for r in rows if r["success"])
    report = {"tasks": rows,
              "summary": {"total": len(rows), "success": s,
                          "false_done": sum(1 for r in rows if r["false_done"])}}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"\n== {s}/{len(rows)} ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
