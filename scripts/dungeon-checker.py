#!/usr/bin/env python3
"""CHECKER do lab do dungeon — escrito ANTES do agente e TRAVADO (444).

Regra do video (15/11): "write the checker before you run, then lock it".
Este checker nao sabe nada da implementacao: ele mede o que o USUARIO
pediu (o inimigo acha o caminho ate o jogador contornando parede). Qualquer
implementacao que satisfaca isso passa (A*, BFS, o que for).

O teste que DISCRIMINA (o baseline, com movimento direto, nao passa):
  3. com uma parede interna, o inimigo chega no jogador.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from dungeon.map import DungeonMap
from dungeon.entities import Enemy, Player


def _mapa(cols=10, rows=10):
    return DungeonMap(cols, rows)


def _parede_interna(m, x=5, y1=1, y2=8):
    for y in range(y1, y2 + 1):
        m._tiles[y][x] = "wall"
    return m


def test_inimigo_move():
    m = _mapa()
    e = Enemy(1, 1)
    p = Player(8, 8)
    antes = (e.x, e.y)
    e.update(p, m)
    assert (e.x, e.y) != antes, "Enemy.update() nao moveu o inimigo"


def test_inimigo_chega_no_jogador_em_sala_vazia():
    m = _mapa()
    e = Enemy(1, 1)
    p = Player(8, 8)
    for _ in range(300):
        if (e.x, e.y) == (p.x, p.y):
            break
        e.update(p, m)
    assert (e.x, e.y) == (p.x, p.y), (
        f"o inimigo nao chegou no jogador (parou em {(e.x, e.y)})")


def test_inimigo_contorna_parede_interna():
    m = _parede_interna(_mapa())
    e = Enemy(1, 1)
    p = Player(8, 8)
    for _ in range(600):
        if (e.x, e.y) == (p.x, p.y):
            break
        e.update(p, m)
    assert (e.x, e.y) == (p.x, p.y), (
        f"com parede interna o inimigo nao chegou (parou em {(e.x, e.y)})")


def test_inimigo_nao_atravessa_parede():
    m = _parede_interna(_mapa())
    e = Enemy(1, 1)
    p = Player(8, 8)
    for _ in range(50):
        e.update(p, m)
        assert not m.is_wall(e.x, e.y), (
            f"o inimigo entrou na parede em {(e.x, e.y)}")
