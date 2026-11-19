#!/usr/bin/env python3
"""Checker do CHUNK B (SERA/H3): o inimigo NUNCA entra na parede. 5 testes."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from dungeon.map import DungeonMap  # noqa: E402
from dungeon.entities import Enemy, Player  # noqa: E402


def sala(w=10, h=10):
    return DungeonMap(w, h)


def obstacle(m, x=4, y1=1, y2=3):
    for y in range(y1, y2 + 1):
        m._tiles[y][x] = "wall"
    return m


def chega(m, e, p, n):
    for _ in range(n):
        if (e.x, e.y) == (p.x, p.y):
            return True
        e.update(p, m)
        if m.is_wall(e.x, e.y):
            return False
    return (e.x, e.y) == (p.x, p.y)


def test_01_centro_da_parede():
    m = obstacle(sala())
    e, p = Enemy(3, 2), Player(8, 2)
    for _ in range(10):
        e.update(p, m)
        assert not m.is_wall(e.x, e.y), f"entrou na parede em {(e.x, e.y)}"


def test_02_desvio_curto():
    m = obstacle(sala())
    e, p = Enemy(1, 1), Player(8, 1)
    assert chega(m, e, p, 200), "nao chegou ou entrou na parede"


def test_03_desvio_duplo():
    m = obstacle(sala())
    for y in (5, 6, 7):
        m._tiles[y][6] = "wall"
    e, p = Enemy(1, 1), Player(8, 8)
    assert chega(m, e, p, 350), "nao passou pelos dois obstaculos"


def test_04_borda_do_mapa():
    m = sala()
    e, p = Enemy(1, 1), Player(8, 1)
    for _ in range(100):
        e.update(p, m)
        assert not m.is_wall(e.x, e.y), "entrou na parede da borda"
        if (e.x, e.y) == (p.x, p.y):
            break


def test_05_nao_teleporta():
    m = obstacle(sala())
    e, p = Enemy(1, 1), Player(8, 1)
    ant = (e.x, e.y)
    for _ in range(200):
        e.update(p, m)
        d = abs(e.x - ant[0]) + abs(e.y - ant[1])
        assert d <= 1, f"teleport de {d}: {ant} -> {(e.x, e.y)}"
        ant = (e.x, e.y)
        if (e.x, e.y) == (p.x, p.y):
            break
