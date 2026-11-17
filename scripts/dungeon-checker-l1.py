#!/usr/bin/env python3
"""CHECKER L1 do lab do dungeon — escrito ANTES do agente e TRAVADO (444).

L1 = a tarefa mais burra possivel: ADICIONAR UM METODO PURO.
Nao ha pathfinding, nao ha estado, nao ha pygame em jogo (so o import).
Se o modelo nao passa aqui, nao faz sentido cobrar L2/L3 dele — e a escada
mede exatamente isso: onde a capacidade acaba.

O baseline NAO tem `distance_to`, entao o baseline falha 1/1. Qualquer
implementacao correta de distancia de Manhattan passa.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from dungeon.entities import Enemy, Player


def test_metodo_existe():
    e = Enemy(1, 1)
    assert hasattr(e, "distance_to"), (
        "Enemy nao tem o metodo distance_to(other)")


def test_distancia_manhattan():
    e = Enemy(1, 1)
    p = Player(4, 5)
    assert e.distance_to(p) == 7, (
        f"distance_to errado: esperado 7, veio {e.distance_to(p)!r}")


def test_distancia_zero_na_mesma_casa():
    e = Enemy(3, 3)
    p = Player(3, 3)
    assert e.distance_to(p) == 0


def test_nao_move_o_inimigo():
    e = Enemy(2, 2)
    p = Player(9, 9)
    e.distance_to(p)
    assert (e.x, e.y) == (2, 2), "distance_to mudou a posicao do inimigo"


def test_funciona_com_entidade_qualquer():
    """Player tambem e Entity: a assinatura tem de aceitar qualquer um."""
    e = Enemy(0, 0)
    assert e.distance_to(Player(2, 2)) == 4
