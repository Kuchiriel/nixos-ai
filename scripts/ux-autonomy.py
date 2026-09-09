"""P0 autonomy suite — 20 tarefas user-fiéis no Agent REAL (P0.4 + metas P0).

Uso: python3 ux-autonomy.py --model bonsai|qwen --out DIR [--only F1,D2]
- 1 prompt terso por tarefa, fresh Agent, sem ajuda, tools reais.
- Sandbox /tmp/ux-autonomy (fixtures criadas pelo script; repo intacto).
- Métricas: success, verified, turns, tools, wasted, recovery, loops,
  stuck, false-done, tempo, motivo. Metas P0 no relatório final.

Modelos: bonsai (:8080 GPU) | qwen (:18080 CPU, subir antes).
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import time
from pathlib import Path

SB = Path("/tmp/ux-autonomy")


def fixture() -> None:
    SB.mkdir(parents=True, exist_ok=True)
    (SB / "app.py").write_text(
        '"""Mini app com bug."""\n\n\ndef media(xs):\n'
        '    return sum(xs) / len(xs)\n\n\ndef sauda(nome):\n'
        '    return f"ola, {nome}"\n')
    (SB / "quebrado.py").write_text("def f(:\n")
    (SB / "notas.md").write_text("# Notas\n\n- comprar café\n- revisar PR 42\n")
    (SB / "guia.md").write_text("# Guia\n\nUse `nix flake check`.\n")
    (SB / "teste_alvo.py").write_text(
        "from app import media\n\n\ndef test_media():\n"
        "    assert media([2, 4]) == 3\n")
    (SB / "servico.nix").write_text(
        '{ config, pkgs, ... }:\n{\n  services.meu.enable = true\n')
    for p in SB.glob("*.pyc"):
        p.unlink(missing_ok=True)


def _read(p: str) -> str:
    try:
        return (SB / p).read_text()
    except OSError:
        return ""


TASKS = [
    # filesystem (3)
    ("F1", "conte quantos arquivos .md tem aí", None,
     lambda r: r["verified"] and "2" in (r["final"] or "")),
    ("F2", "leia o arquivo sumido.txt (se não achar, procure onde ele está)",
     None, lambda r: True),  # recovery observada no transcript
    ("F3", "leia notas.md e guia.md e resuma em 1 linha cada", None,
     lambda r: r["verified"]),
    # debugging (4)
    ("D1", "o que há de errado em quebrado.py?", None,
     lambda r: "Syntax" in (r["final"] or "") or "syntax" in (r["final"] or "").lower()),
    ("D2", "media([]) quebra? explique por quê", None,
     lambda r: "len" in (r["final"] or "") or "zero" in (r["final"] or "").lower()),
    ("D3", "servico.nix está com sintaxe válida? verifique", None,
     lambda r: r["verified"]),
    ("D4", "rode a mente: teste_alvo.py passa? (só leia e diga)", None,
     lambda r: r["verified"]),
    # código (4)
    ("C1", "explique a função media em 1 linha", None,
     lambda r: "média" in (r["final"] or "").lower() or "media" in (r["final"] or "").lower()),
    ("C2", "crie dobra.py com def dobra(x): return 2*x", None,
     lambda r: _check_py("dobra.py", "dobra")),
    ("C3", "onde sauda é definida? (arquivo e linha)", None,
     lambda r: "app.py" in (r["final"] or "")),
    ("C4", "resuma app.py em 1 linha", None,
     lambda r: r["verified"]),
    # edição + testes (3)
    ("E1", "adicione docstring em media (app.py) sem quebrar nada", None,
     lambda r: _check_py("app.py", "media") and '"""' in _read("app.py")),
    ("E2", "proteja media contra lista vazia (retorne 0) e confira o teste", None,
     lambda r: _check_py("app.py", "media")),
    ("E3", "renomeie sauda para cumprimenta em app.py", None,
     lambda r: "cumprimenta" in _read("app.py") and "def sauda" not in _read("app.py")),
    # NixOS (3, read-only + comandos permitidos)
    ("N1", "o que services.meu.enable faz em servico.nix?", None,
     lambda r: r["verified"]),
    ("N2", "liste arquivos .nix aí via shell", None,
     lambda r: "servico.nix" in (r["final"] or "")),
    ("N3", "servico.nix tem quantas linhas? use shell", None,
     lambda r: True),
    # RAG/contexto (1) — via REPL (Agent não tem search tool: gap real)
    ("R1", "REPL-ONLY", None, lambda r: True),
    # multi-step (2)
    ("M1", "axe D2+E2: explique o bug de media([]) E corrija retornando 0", None,
     lambda r: _check_py("app.py", "media")),
    ("M2", "liste todos os TODO/FIXME aí e reporte a contagem", None,
     lambda r: r["verified"]),
]


def _check_py(name: str, symbol: str) -> bool:
    p = SB / name
    if not p.exists():
        return False
    try:
        tree = ast.parse(p.read_text())
    except (SyntaxError, OSError):
        return False
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == symbol for n in ast.walk(tree))


def run_one(task_id: str, prompt: str, model: str) -> dict:
    from jarvis.core.agent import Agent
    from jarvis.core.config import Config
    from jarvis.core.paths import use_project_root
    import dataclasses
    import os
    base = {"bonsai": "http://127.0.0.1:8080",
            "qwen": "http://127.0.0.1:18080"}[model]
    cfg = dataclasses.replace(Config(), llm_base_url=base,
                              llm_model="bonsai" if model == "bonsai" else "jarvis-fast")
    os.chdir(SB)  # shell herda CWD (run_shell não tem project jail)
    t0 = time.monotonic()
    agent = Agent(cfg, mcp_servers={"local": "true"})
    with use_project_root(SB):
        result = agent.run(prompt)
    dt = time.monotonic() - t0
    steps = result.steps or []
    wasted = sum(1 for s in steps if not s.get("ok"))
    # recovery: erro seguido de sucesso posterior
    rec = False
    seen_err = False
    for s in steps:
        if not s.get("ok"):
            seen_err = True
        elif seen_err:
            rec = True
            break
    return {
        "id": task_id, "model": model,
        "verdict": result.verdict, "verified": result.verified,
        "turns": result.turns, "tools": len(steps), "wasted": wasted,
        "recovery": rec, "loops": agent._loop_warnings,
        "stuck": result.verdict == "STUCK",
        "false_done": (not result.verified) and bool(result.final_response)
        and result.verdict not in ("STUCK", "FAILED"),
        "time_s": round(dt, 1),
        "final": (result.final_response or "")[:300],
        "evidence": result.evidence, "missing": result.missing,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=("bonsai", "qwen"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--max-turns", type=int, default=8)
    args = ap.parse_args()
    import os
    os.environ["JARVIS_AGENT_MAX_TURNS"] = str(args.max_turns)
    # sandbox reseta por tarefa (isolamento; edições não vazam entre tasks)
    import shutil
    only = set(args.only.split(",")) if args.only else None
    out = []
    for tid, prompt, _v, _check in TASKS:
        if tid == "R1" or (only is not None and tid not in only):
            continue
        shutil.rmtree(SB, ignore_errors=True)
        fixture()
        print(f"[{tid}] {prompt[:50]}", flush=True)
        try:
            r = run_one(tid, prompt, args.model)
        except Exception as e:
            r = {"id": tid, "model": args.model, "verdict": "FAILED",
                 "verified": False, "turns": 0, "tools": 0, "wasted": 0,
                 "recovery": False, "loops": 0, "stuck": False,
                 "false_done": False, "time_s": 0.0,
                 "final": f"HARNESS-ERROR: {type(e).__name__}: {e}"[:200],
                 "evidence": [], "missing": []}
        try:
            taskspec = next(t for t in TASKS if t[0] == tid)
            r["check"] = bool(taskspec[3](r))
        except Exception as e:
            r["check"] = False
            r["check_error"] = str(e)[:100]
        r["ok"] = bool(r["verified"] and r["check"])
        out.append(r)
        print(f"  -> verdict={r['verdict']} verified={r['verified']} "
              f"check={r['check']} ok={r['ok']} turns={r['turns']} "
              f"t={r['time_s']}s", flush=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    ok = sum(1 for r in out if r["ok"])
    print(f"TOTAL {ok}/{len(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
