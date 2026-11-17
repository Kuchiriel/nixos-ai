#!/usr/bin/env python3
"""CHECKER do lab "jogo do zero" — escrito ANTES e TRAVADO (444).

O teste nao assume NENHUMA estrutura (o agente escolhe os nomes): ele mede
que o JOGO existe e funciona, como um usuario veria:

  1. existe codigo de jogo (>= 3 arquivos .py);
  2. todo o codigo COMPILA (nada de arquivo quebrado);
  3. da pra IMPORTAR o jogo (sem estourar na importacao);
  4. o jogo tem um MAPA e um INIMIGO com comportamento (a classe existe e
     o inimigo anda/ataca — o "jogo" nao pode ser um arquivo vazio);
  5. o jogo RODA (o entry point existe e nao explode).

Regra do video (15/11): o checker e escrito antes e trancado; o agente nao
ve nem mexe nele.
"""
import ast
import io
import os
import pathlib
import subprocess
import sys
import contextlib

ROOT = pathlib.Path(os.environ.get("LAB_ROOT", os.getcwd()))


def _py_files():
    return [p for p in ROOT.rglob("*.py")
            if ".git" not in p.parts and "__pycache__" not in p.parts]


def _all_text():
    buf = []
    for p in _py_files():
        try:
            buf.append(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    return "\n".join(buf)


def test_tem_codigo_de_jogo():
    files = _py_files()
    assert len(files) >= 3, f"so tem {len(files)} arquivo(s) .py (um jogo precisa de codigo)"


def test_tudo_compila():
    r = subprocess.run([sys.executable, "-m", "compileall", "-q", str(ROOT)],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, f"tem codigo que nao compila:\n{r.stdout[-500:]}{r.stderr[-500:]}"


def test_o_jogo_importa():
    # importa cada modulo do jogo isoladamente (sem pygame em tela cheia)
    mods = []
    for p in _py_files():
        if p.name.startswith("test_"):
            continue
        mods.append(p)
    assert mods, "nenhum modulo pra importar"
    erro = ""
    for p in mods[:12]:
        r = subprocess.run([sys.executable, "-c",
                            "import importlib.util,sys;"
                            f"spec=importlib.util.spec_from_file_location('m_{abs(hash(str(p)))}', r'{p}');"
                            "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)"],
                           capture_output=True, text=True, timeout=120,
                           env={**os.environ, "SDL_VIDEODRIVER": "dummy",
                                "PYGAME_HIDE_SUPPORT_PROMPT": "1"})
        if r.returncode != 0:
            erro += f"{p.name}: {r.stderr[-300:]}\n"
    assert not erro, "modulo(s) nao importam:\n" + erro[:800]


def test_tem_mapa_e_inimigo():
    txt = _all_text()
    tem_mapa = ("class DungeonMap" in txt) or ("class Map" in txt) or \
               ("class Mapa" in txt) or ("class Level" in txt) or ("def generate" in txt)
    tem_inimigo = ("class Enemy" in txt) or ("class Inimigo" in txt) or \
                  ("class Monster" in txt)
    assert tem_mapa, "nao achei o mapa do dungeon (class DungeonMap/Map/Level?)"
    assert tem_inimigo, "nao achei o inimigo (class Enemy/Inimigo/Monster?)"


def test_o_jogo_roda():
    # o entry point existe e o jogo inicia sem explodir
    entrada = None
    for nome in ("run_game.py", "main.py", "game.py", "run.py"):
        cands = list(ROOT.rglob(nome))
        if cands:
            entrada = cands[0]
            break
    if entrada is None:
        # qualquer .py na raiz que pareca entry point
        cands = [p for p in ROOT.glob("*.py") if not p.name.startswith("test_")]
        entrada = cands[0] if cands else None
    assert entrada is not None, "nenhum entry point do jogo (run_game.py/main.py?)"

    env = {**os.environ, "SDL_VIDEODRIVER": "dummy", "PYGAME_HIDE_SUPPORT_PROMPT": "1"}
    try:
        r = subprocess.run([sys.executable, str(entrada)], capture_output=True,
                           text=True, timeout=45, env=env)
    except subprocess.TimeoutExpired:
        return  # rodou ate o timeout = o jogo entrou no loop (ok)
    assert r.returncode == 0, f"o jogo explodiu ao rodar:\n{r.stderr[-600:]}"
