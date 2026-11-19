#!/usr/bin/env python3
"""Valida os 3 checkers do chunking contra o BASELINE PRE-A* (deve falhar)
e contra a solucao A* (deve passar 5/5). E' o contrato do lab doctor.

O baseline atual do dungeon JA TEM A* (commit e47e976), entao o laboratorio
'inteiro' mede uma tarefa resolvida. Para o experimento de chunking fazemos
o baseline voltar ao commit 3432567 (movimento direto), que e' o que os
checkers de L2/L3 foram escritos para medir.
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

SRC = Path("/home/nixos/projects/jarvis-dungeon")
CHECKERS = Path("/home/nixos/work/chunk-checkers")
REPO = "/home/nixos/projects/nixos-ai"


def pre_astar_source():
    r = subprocess.run(["git", "-C", str(SRC), "show", "3432567:src/dungeon/entities.py"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise SystemExit("nao consegui ler o baseline pre-A*")
    return r.stdout


def run(lane, checker):
    dest = lane / "checker.py"
    if dest.exists():
        dest.chmod(0o644)
    shutil.copy2(checker, dest)
    dest.chmod(0o644)
    r = subprocess.run(
        ["nix", "develop", "--command", "bash", "-c",
         f"set -o pipefail; cd {lane} && python3 -m pytest -q checker.py 2>&1 | tail -3"],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    out = " | ".join(x for x in (r.stdout or "").splitlines() if "passed" in x or "failed" in x)
    return (0 if "5 passed" in out else 1), out[:120]


ok = True
for chunk in "abc":
    checker = CHECKERS / f"checker-chunk-{chunk}.py"
    with tempfile.TemporaryDirectory(prefix=f"chunkdoc-{chunk}-") as td:
        lane = Path(td)
        shutil.copytree(SRC, lane, dirs_exist_ok=True)
        # 1) baseline PRE-A* (deve FALHAR)
        (lane / "src/dungeon/entities.py").write_text(pre_astar_source(), encoding="utf-8")
        rc0, out0 = run(lane, checker)
        print(f"chunk {chunk} PRE-A*  rc={rc0}  {out0}")
        # 2) baseline ATUAL com A* (deve PASSAR 5/5)
        shutil.copy2(SRC / "src/dungeon/entities.py", lane / "src/dungeon/entities.py")
        rc1, out1 = run(lane, checker)
        print(f"chunk {chunk} A*       rc={rc1}  {out1}")
        if rc0 == 0 or rc1 != 0:
            ok = False
print("\nVEREDITO:", "VALIDO (pre-A* falha, A* passa 5/5)" if ok else "INVALIDO")
