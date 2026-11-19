#!/usr/bin/env python3
"""Checker do CHUNK C (SERA/H3): o inimigo CONTORNA o obstaculo curto.

5 testes deterministicos; gate H3 = 'cada chunk 5/5'.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from dungeon.map import DungeonMap  # noqa: E402
from dungeon.entities import Enemy, Player  # noqa: E402


def sala(w=10, h=10):
    return DungeonMap(w, h)


def obstaculo_curto(m, x=4, y1=2, y2=4):
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


def test_01_contorna_tres_casas():
    m = obstaculo_curto(sala())
    assert chega(m, Enemy(2, 3), Player(8, 3), 250), "nao contornou 3 casas"


def test_02_contorna_em_ambos_sentidos():
    m = obstaculo_curto(sala())
    assert chega(m, Enemy(8, 3), Player(2, 3), 250), "falhou no sentido inverso"


def test_03_contorna_com_player_acima():
    m = obstaculo_curto(sala())
    assert chega(m, Enemy(2, 6), Player(8, 1), 300), "falhou com player acima"


def test_04_contorna_com_player_abaixo():
    m = obstaculo_curto(sala())
    assert chega(m, Enemy(2, 1), Player(8, 6), 300), "falhou com player abaixo"


def test_05_desvia_e_nao_entra_na_parede():
    m = obstaculo_curto(sala())
    e, p = Enemy(2, 3), Player(8, 3)
    desviou = False
    for _ in range(250):
        e.update(p, m)
        assert not m.is_wall(e.x, e.y), "entrou na parede ao desviar"
        if e.y != 3:
            desviou = True
        if (e.x, e.y) == (p.x, p.y):
            break
    assert desviou, "nunca saiu da linha reta (nao houve desvio)"
    assert (e.x, e.y) == (p.x, p.y), "nao chegou ao player"
