#!/usr/bin/env python3
"""CHECKER L2 do lab do dungeon — escrito ANTES do agente e TRAVADO (444).

L2 = desviar de UM obstaculo curto, sem pathfinding completo.
Da para passar com uma regra local (tenta a direcao livre que mais aproxima,
depois as laterais), sem BFS/A*. E o degrau do meio da escada:

  L1 adicionar metodo  ->  L2 desviar de perto  ->  L3 contornar parede inteira

Todos os testes daqui usam o obstaculo de proposito: o baseline (movimento
direto que so checa is_wall) trava em (2,1) e falha TODOS — nao ha teste
"de graca" inflando o placar do baseline.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from dungeon.map import DungeonMap
from dungeon.entities import Enemy, Player


def _sala(cols=8, rows=8):
    return DungeonMap(cols, rows)


def _obstaculo_curto(m, x=3, y1=1, y2=3):
    for y in range(y1, y2 + 1):
        m._tiles[y][x] = "wall"
    return m


def _obstaculo_duplo(m):
    """Dois obstaculos escalonados: exige desviar duas vezes."""
    for y in (1, 2, 3):
        m._tiles[y][3] = "wall"
    for y in (4, 5, 6):
        m._tiles[y][5] = "wall"
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


def test_fixture_tem_passagem():
    """SANIDADE: os cenarios do L2 tem de ser possiveis."""
    assert _tem_caminho(_obstaculo_curto(_sala()), (1, 1), (6, 1))
    assert _tem_caminho(_obstaculo_duplo(_sala()), (1, 1), (6, 6))


def test_move_mesmo_com_passo_direto_bloqueado():
    """O caso que separa L2 do baseline: o passo direto esta na parede."""
    m = _obstaculo_curto(_sala())
    e = Enemy(2, 1)
    p = Player(6, 1)
    e.update(p, m)
    assert (e.x, e.y) != (2, 1), (
        "o inimigo ficou parado com o passo direto bloqueado")


def test_contorna_obstaculo_curto():
    m = _obstaculo_curto(_sala())
    e = Enemy(1, 1)
    p = Player(6, 1)
    for _ in range(200):
        if (e.x, e.y) == (p.x, p.y):
            break
        e.update(p, m)
    assert (e.x, e.y) == (p.x, p.y), (
        f"o inimigo nao contornou o obstaculo curto (parou em {(e.x, e.y)})")


def test_contorna_dois_obstaculos():
    m = _obstaculo_duplo(_sala())
    e = Enemy(1, 1)
    p = Player(6, 6)
    for _ in range(300):
        if (e.x, e.y) == (p.x, p.y):
            break
        e.update(p, m)
    assert (e.x, e.y) == (p.x, p.y), (
        f"o inimigo nao passou pelos dois obstaculos (parou em {(e.x, e.y)})")


def test_nunca_entra_na_parede_durante_o_desvio():
    m = _obstaculo_curto(_sala())
    e = Enemy(1, 1)
    p = Player(6, 1)
    passos = 0
    for _ in range(200):
        e.update(p, m)
        assert not m.is_wall(e.x, e.y), (
            f"o inimigo entrou na parede em {(e.x, e.y)}")
        passos += 1
        if (e.x, e.y) == (p.x, p.y):
            break
    assert (e.x, e.y) == (p.x, p.y) and passos < 60, (
        f"nao chegou em tempo razoavel (parou em {(e.x, e.y)}, {passos} passos)")
