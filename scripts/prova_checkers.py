#!/usr/bin/env python3
"""Prova que os checkers da escada PASSAM para uma solucao correta.

Sem isso o checker nao esta validado: um checker que reprova todo mundo pode
estar simplesmente errado (foi o que aconteceu com o L3 v2 — mapa sem
passagem). Aqui montamos uma implementacao de referencia (BFS + Manhattan) e
exigimos 100% de aprovacao em L1/L2/L3.
"""
import collections
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = "343256793dc06a1a011adf360b611b1e652d7f79"
SRC = Path.home() / "projects/jarvis-dungeon"
REPO = Path.home() / "projects/nixos-ai"

ANTIGO = '''    def update(self, player: Player, game_map: DungeonMap) -> None:
        """Simple AI: move toward player if adjacent."""
        dx = 0
        dy = 0
        if abs(self.x - player.x) > abs(self.y - player.y):
            dx = 1 if player.x > self.x else -1
        else:
            dy = 1 if player.y > self.y else -1

        new_x, new_y = self.x + dx, self.y + dy
        if not game_map.is_wall(new_x, new_y):
            self.x, self.y = new_x, new_y'''

NOVO = '''    def distance_to(self, other) -> int:
        """Manhattan distance to another entity."""
        return abs(self.x - other.x) + abs(self.y - other.y)

    def update(self, player: Player, game_map: DungeonMap) -> None:
        """Walk toward the player, going around walls (BFS)."""
        if (self.x, self.y) == (player.x, player.y):
            return
        inicio = (self.x, self.y)
        alvo = (player.x, player.y)
        fila = collections.deque([inicio])
        veio_de = {inicio: None}
        while fila:
            atual = fila.popleft()
            if atual == alvo:
                break
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (atual[0] + dx, atual[1] + dy)
                if n not in veio_de and not game_map.is_wall(*n):
                    veio_de[n] = atual
                    fila.append(n)
        if alvo not in veio_de:
            return
        passo = alvo
        while veio_de[passo] is not None and veio_de[passo] != inicio:
            passo = veio_de[passo]
        self.x, self.y = passo'''


def main() -> int:
    lane = Path(tempfile.mkdtemp(prefix="lane-ref-"))
    for nome in subprocess.run(
            ["git", "-C", str(SRC), "ls-tree", "-r", "--name-only", BASE],
            capture_output=True, text=True, check=True).stdout.split():
        if "__pycache__" in nome:
            continue
        destino = lane / nome
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(subprocess.run(
            ["git", "-C", str(SRC), "show", f"{BASE}:{nome}"],
            capture_output=True, text=True, check=True).stdout, encoding="utf-8")

    ent = lane / "src/dungeon/entities.py"
    txt = ent.read_text(encoding="utf-8")
    if ANTIGO not in txt:
        print("ERRO: bloco do Enemy.update nao encontrado no baseline", file=sys.stderr)
        return 2
    txt = txt.replace(ANTIGO, NOVO, 1).replace(
        "import pygame\n", "import collections\nimport pygame\n", 1)
    ent.write_text(txt, encoding="utf-8")

    (lane / "conftest.py").write_text(
        'import os, sys\n'
        'sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))\n',
        encoding="utf-8")

    checkers = {"L1": "dungeon-checker-l1.py",
                "L2": "dungeon-checker-l2.py",
                "L3": "dungeon-checker.py"}
    print("lane:", lane)
    falhou = False
    for nivel, arquivo in checkers.items():
        alvo = lane / f"c_{nivel}.py"
        shutil.copy2(REPO / "scripts" / arquivo, alvo)
        r = subprocess.run(
            ["nix", "develop", str(REPO), "-c", "bash", "-c",
             f"cd {lane} && python3 -m pytest -q --tb=line -rf {alvo.name}"],
            capture_output=True, text=True, timeout=600)
        saida = (r.stdout + r.stderr).strip().splitlines()
        resumo = next((l for l in reversed(saida) if "passed" in l or "failed" in l), "?")
        print(f"{nivel}: {resumo}")
        if r.returncode != 0:
            falhou = True
            print("\n".join([l for l in saida if "FAILED" in l or "assert" in l or "Error" in l][-8:]))
    print("RESULTADO:", "FALHOU (checker invalido)" if falhou else "OK — os 3 passam")
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
