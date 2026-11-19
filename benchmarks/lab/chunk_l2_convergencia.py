#!/usr/bin/env python3
"""Item #18 / H3 (SERA): chunking com verifier por subtarefa.

Metrica: TAXA DE CONVERGENCIA — quantos dos 3 chunks passam 5/5, e em quantas
amostras. Compara:
  - braço UNICO: a task L2 inteira, checker=scripts/dungeon-checker-l2.py (5 tests)
  - braço CHUNKS: as 3 subtarefas (A=move, B=nunca-parede, C=contorna), cada
    uma com seu checker proprio; convergencia = chunks 5/5.

Os checkers ja passaram no lab doctor (pre-A* falha, A* passa 5/5).

Este script NAO roda o harness A/B inteiro (isso e' o lab, outra lane): ele
mede a convergencia do baseline e da solucao de referencia, para dar o LIMITE
inferior e superior do experimento. Se o baseline pre-A* ja passa os chunks,
o experimento e' invalido; se falha e A* passa, os checkers separam as duas
condicoes e o A/B com modelo pode rodar.

Saida: /tmp/opencode/chunk-l2-convergencia.json
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

SRC = Path("/home/nixos/projects/jarvis-dungeon")
CHECKERS = Path("/home/nixos/work/chunk-checkers")
SCRIPTS = Path("/home/nixos/projects/nixos-ai/scripts")
REPO = "/home/nixos/projects/nixos-ai"


def baseline_pre_astar():
    r = subprocess.run(["git", "-C", str(SRC), "show", "3432567:src/dungeon/entities.py"],
                       capture_output=True, text=True, timeout=30)
    return r.stdout


def pytest_count(lane, checker_path, target="checker.py"):
    dest = lane / target
    if dest.exists():
        dest.chmod(0o644)
    shutil.copy2(checker_path, dest)
    dest.chmod(0o644)
    r = subprocess.run(
        ["nix", "develop", "--command", "bash", "-c",
         f"cd {lane} && python3 -m pytest -q {target} 2>&1 | tail -3"],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    out = r.stdout or ""
    passed = 0
    failed = 0
    for tok in out.split():
        if tok.isdigit():
            pass
    import re
    m = re.search(r"(\d+) passed", out)
    passed = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) failed", out)
    failed = int(m.group(1)) if m else 0
    return {"passed": passed, "failed": failed, "ok": failed == 0 and passed >= 5}


def measure(label, source_text):
    safe = "".join(ch if ch.isalnum() else "_" for ch in label)[:24]
    with tempfile.TemporaryDirectory(prefix=f"chunkab-{safe}-") as td:
        lane = Path(td)
        shutil.copytree(SRC, lane, dirs_exist_ok=True)
        (lane / "src/dungeon/entities.py").write_text(source_text, encoding="utf-8")
        chunks = {}
        for c in "abc":
            chunks[c] = pytest_count(lane, CHECKERS / f"checker-chunk-{c}.py")
        single = pytest_count(lane, SCRIPTS / "dungeon-checker-l2.py", target="checker_single.py")
        return {"label": label,
                "chunks_5_5": sum(1 for v in chunks.values() if v["ok"]),
                "chunks": chunks,
                "single_l2": single}


rows = [
    measure("pre-A* (baseline que o L2 foi escrito para medir)", baseline_pre_astar()),
    measure("A* (solucao de referencia)", (SRC / "src/dungeon/entities.py").read_text(encoding="utf-8")),
]
Path("/tmp/opencode/chunk-l2-convergencia.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
for r in rows:
    print(f"{r['label'][:52]:52} chunks 5/5={r['chunks_5_5']}/3 "
          f"single={r['single_l2']['passed']}/5")
print("JSON=/tmp/opencode/chunk-l2-convergencia.json")
