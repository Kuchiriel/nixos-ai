#!/usr/bin/env python3
"""CHECKER do lab do dungeon — escrito ANTES do agente e TRAVADO (444).

Regra do video (15/11): "write the checker before you run, then lock it".
Este checker nao sabe nada da implementacao: ele mede o que o USUARIO
pediu (o inimigo acha o caminho ate o jogador contornando parede). Qualquer
implementacao que satisfaca isso passa (A*, BFS, o que for).

── v3 (17/11) — O BUG QUE INVALIDOU 537 MEDICOES ────────────────────────
Na v2 a parede interna ia de y=1 a y=8 num mapa 10x10. As bordas do mapa
(y=0 e y=9) ja sao parede, entao a coluna x=5 fechava a sala em DUAS METADES
SEM PASSAGEM. O teste `test_inimigo_contorna_parede_interna` exigia o
IMPOSSIVEL: nenhum modelo — nem um A* perfeito — poderia passar. Prova:
BFS no mapa devolvia "sem caminho" (medido 17/11).
Agora a parede vai de y=1 a y=7 e deixa a passagem em (5,8). E o proprio
checker tem um teste de SANIDADE do fixture (test_mapa_tem_passagem): se
alguem reintroduzir um mapa impossivel, o checker falha na hora, em vez de
culpar o modelo por 9 horas.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from dungeon.map import DungeonMap
from dungeon.entities import Enemy, Player


def _mapa(cols=10, rows=10):
    return DungeonMap(cols, rows)


def _parede_interna(m, x=5, y1=1, y2=7):
    """Parede com PASSAGEM: vai de y1 ate y2 (inclusive), deixando y2+1 livre."""
    for y in range(y1, y2 + 1):
        m._tiles[y][x] = "wall"
    return m


def _tem_caminho(m, inicio, fim):
    fila = collections.deque([inicio])
    vistos = {inicio}
    while fila:
        x, y = fila.popleft()
        if (x, y) == fim:
            return True
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n not in vistos and not m.is_wall(*n):
                vistos.add(n)
                fila.append(n)
    return False


def test_mapa_tem_passagem():
    """SANIDADE DO FIXTURE: o cenario do veredito tem de ser POSSIVEL.

    Este teste nao olha o agente: ele guarda o CHECKER de si mesmo. A v2
    pedia o impossivel e reprovou todo mundo por 9 horas.
    """
    m = _parede_interna(_mapa())
    assert _tem_caminho(m, (1, 1), (8, 8)), (
        "FIXTURE INVALIDO: a parede fecha o mapa e o objetivo e impossivel")


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
