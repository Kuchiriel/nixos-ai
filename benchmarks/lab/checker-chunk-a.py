#!/usr/bin/env python3
"""Checker do CHUNK A (SERA/H3): o inimigo SE MOVE em direção ao player.

5 testes deterministicos. Trancado (444) quando copiado para a lane.
So mede o comportamento (distancia diminui), nao nomes de metodos.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from dungeon.map import DungeonMap  # noqa: E402
from dungeon.entities import Enemy, Player  # noqa: E402


def sala(w=10, h=10):
    return DungeonMap(w, h)


def dist(e, p):
    return abs(e.x - p.x) + abs(e.y - p.y)


def barreira_vertical(m, x, y1, y2):
    for y in range(y1, y2 + 1):
        m._tiles[y][x] = "wall"
    return m


def test_01_move_em_espaco_livre():
    m = sala()
    e, p = Enemy(1, 1), Player(8, 1)
    d0 = dist(e, p)
    e.update(p, m)
    assert dist(e, p) < d0, f"nao aproximou: {d0} -> {dist(e, p)}"


def test_02_move_com_passo_direto_bloqueado():
    m = barreira_vertical(sala(), 4, 1, 3)
    e, p = Enemy(3, 1), Player(8, 1)
    d0 = dist(e, p)
    e.update(p, m)
    assert (e.x, e.y) != (3, 1), "ficou parado com a parede na frente"
    # Ao contornar, a distancia de Manhattan PODE aumentar 1 passo — e legitimo.
    # O que importa e' que se moveu para uma casa livre.
    assert not m.is_wall(e.x, e.y), "se moveu para dentro da parede"


def test_03_aproxima_ate_chegar():
    m = sala()
    e, p = Enemy(1, 1), Player(8, 1)
    for _ in range(80):
        if (e.x, e.y) == (p.x, p.y):
            break
        e.update(p, m)
        assert not m.is_wall(e.x, e.y), "entrou na parede"
    assert (e.x, e.y) == (p.x, p.y), f"nao chegou: {(e.x, e.y)}"


def test_04_nao_fica_parado_em_loop():
    m = barreira_vertical(sala(), 4, 1, 3)
    e, p = Enemy(1, 1), Player(8, 1)
    pos = set()
    for _ in range(40):
        e.update(p, m)
        pos.add((e.x, e.y))
    assert len(pos) > 2, f"poucas posicoes distintas: {len(pos)}"


def test_05_respeita_limites_do_mapa():
    m = sala()
    e, p = Enemy(1, 1), Player(8, 8)
    for _ in range(200):
        e.update(p, m)
        assert 0 <= e.x < m.width and 0 <= e.y < m.height, f"fora do mapa: {(e.x, e.y)}"
