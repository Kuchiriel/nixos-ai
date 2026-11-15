#!/usr/bin/env python3
"""dungeon-ab.py — o A/B do jarvis-dungeon: o MESMO trabalho, dois modelos.

(15/11, crouton-alpha) O legado (~/projects/team, 11 relatorios) rodou o
dungeon com o BONSAI e deu 8 FAIL em 10 — o agente planejava certo (5
etapas com deps) mas executava mal (assumia arquivo em vez de ler) e
raciocinava em ingles num contexto PT-BR. O dono: "foi feito com bonsai
ainda modelo ruim em ptbr e erra muito, hoje temos qwen 4b mtp".

O QUE FAZ (video Codacus: checker escrito ANTES e trancado):
  1. SANDBOX: copia o jarvis-dungeon para um worktree temporario — o
     agente NAO toca o repo real (regra da casa + do video);
  2. a MESMA task (A* pathfinding), o mesmo formato de plano/avaliacao do
     harness da casa (nightwatch/harness.py: SafeEditor + Evaluator);
  3. o CHECKER FIXADO e o proprio objetivo: `pytest test_astar.py` (4/4);
  4. grava o veredito por modelo + em que passo falhou.

uso:
  python3 scripts/dungeon-ab.py --models bonsai mtp        # A/B
  python3 scripts/dungeon-ab.py --models mtp --dry-run    # so o plano
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
REPO = HOME / "projects/nixos-ai"
DUNGEON = HOME / "projects/jarvis-dungeon"
REPORTS = REPO / "docs/operations"

# os dois modelos (medidos HOJE: o router so serve bonsai; o MTP esta no :8092)
MODELOS = {
    "bonsai": {"base_url": "http://127.0.0.1:8080/v1", "model": "bonsai"},
    "mtp":    {"base_url": "http://127.0.0.1:8092/v1", "model": "jarvis-mtp-lora"},
}

TASK = (
    "Implement A* pathfinding for enemies in src/dungeon/entities.py: the Enemy "
    "class must use heapq to compute a path to the player, recalculate it when "
    "the target moves, and fall back to simple movement when no path is found. "
    "The unit tests in test_astar.py must pass (4/4). Read the existing code "
    "before editing; do not assume files exist."
)


def tem_servidor(base_url: str) -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(base_url + "/models", timeout=6) as r:
            return r.getcode() == 200
    except Exception:
        return False


def sandbox(tag: str) -> Path:
    """Copia o dungeon para um worktree isolado (o agente nao toca o repo real)."""
    dst = Path("/tmp/dungeon-ab") / f"{tag}-{int(time.time())}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(DUNGEON, dst)
    shutil.rmtree(dst / ".git", ignore_errors=True)
    return dst


def roda_teste(cwd: Path) -> dict:
    """O CHECKER FIXADO: o objetivo da task, medido de forma objetiva."""
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_astar.py"],
                       cwd=cwd, capture_output=True, text=True, timeout=300)
    tail = (r.stdout or "")[-800:]
    return {"rc": r.returncode, "pass": "4 passed" in tail or "5 passed" in tail,
            "out": tail}


def plano_com_modelo(base_url: str, model: str, task: str) -> dict:
    """Um turno de plano (a mesma coisa que o legado pedia: 5 etapas com deps)."""
    sys.path.insert(0, str(REPO / "modules/ai/jarvis/src"))
    os.environ["JARVIS_LLM_BASE_URL"] = base_url
    os.environ["JARVIS_LLM_MODEL"] = model
    os.environ["JARVIS_DISABLE_THINKING"] = "1"
    try:
        from nightwatch.harness import Harness, HarnessConfig
    except Exception as exc:  # noqa: BLE001
        return {"erro": f"harness indisponivel: {exc}"}
    cfg = HarnessConfig(project="jarvis-dungeon", max_tasks=1, max_retries=1,
                        llm_base_url=base_url, llm_model=model,
                        telegram_notifications=False, use_llm_discovery=False,
                        use_scripted_discovery=False, auto_approve=True)
    try:
        h = Harness(cfg)
    except Exception as exc:  # noqa: BLE001
        return {"erro": f"harness nao instanciou: {exc}"}
    return {"harness": type(h).__name__, "model": model, "task": task[:80]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["bonsai", "mtp"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rel = {"ts": datetime.now().isoformat(timespec="seconds"), "resultados": []}
    for tag in args.models:
        cfg = MODELOS.get(tag)
        if not cfg:
            print(f"modelo desconhecido: {tag}", file=sys.stderr)
            continue
        vivo = tem_servidor(cfg["base_url"])
        print(f"[{tag}] {cfg['base_url']} servidor vivo: {vivo}", flush=True)
        item = {"modelo": tag, "base_url": cfg["base_url"], "model": cfg["model"],
                "servidor_vivo": vivo}
        if not vivo:
            item["veredito"] = "SEM SERVIDOR"
            rel["resultados"].append(item)
            continue
        if args.dry_run:
            item.update(plano_com_modelo(cfg["base_url"], cfg["model"], TASK))
            rel["resultados"].append(item)
            continue
        sb = sandbox(tag)
        item["sandbox"] = str(sb)
        item["plano"] = plano_com_modelo(cfg["base_url"], cfg["model"], TASK)
        item["teste_final"] = roda_teste(sb)
        item["veredito"] = "PASS" if item["teste_final"]["pass"] else "FAIL"
        rel["resultados"].append(item)
        print(f"[{tag}] veredito: {item['veredito']}", flush=True)

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"DUNGEON-AB-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    out.write_text(json.dumps(rel, ensure_ascii=False, indent=1))
    print("relatorio:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
