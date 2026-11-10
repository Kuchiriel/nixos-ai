#!/usr/bin/env python3
"""check-text-chars.py — trava os caracteres que nao devem sair da casa.

POR QUE (10/11, coord-naming): duas notas de bus minhas saíram com caractere
CJK no meio do texto ("Nota de感谢", "a副本") e a lição escrita em memoria nao
segurou — o que segura é MECANICO. Este script é esse passo: antes de postar
nota, commit ou memória, rode-o sobre o texto.

O que bloqueia: CJK, formas de largura total, emoji e setas (regra do dono:
sem setas, sem emoji). O que passa: acentuação pt-BR e tipografia comum
(traço, aspas).

USO
    python3 scripts/check-text-chars.py <arquivo>
    echo "$TEXTO" > /tmp/nota.txt && python3 scripts/check-text-chars.py /tmp/nota.txt

EXEMPLO
    $ python3 scripts/check-text-chars.py nota.txt
    PROBLEMA: 1 caractere(s) proibido(s)
      linha 1: '副' (U+526F) | a副本 perde



Blocks CJK, full-width forms, emoji and arrows (the owner's rule: no arrows,
no emoji). Portuguese accents and the usual typography (em dash, quotes) are
allowed.

Usage: python3 cjk_check.py <file>
Exit 1 (and print the offending lines) when something is found.
"""
import re
import sys

BAD = re.compile(
    "["
    "\u2e80-\u303f"      # CJK radicals, punctuation, symbols
    "\u3040-\u30ff"      # kana
    "\u3400-\u4dbf"      # CJK ext A
    "\u4e00-\u9fff"      # CJK unified
    "\uf900-\ufaff"      # compatibility ideographs
    "\uff00-\uffef"      # full-width forms
    "\U0001f000-\U0001faff"  # emoji
    "\u2190-\u21ff"      # arrows
    "\u2b00-\u2bff"      # misc symbols and arrows
    "]"
)


ARROWS = re.compile("[\u2190-\u21ff\u2b00-\u2bff]")


def main(path, allow_arrows=False):
    bad = []
    arrows = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            for m in BAD.finditer(line):
                ch = m.group(0)
                if allow_arrows and ARROWS.fullmatch(ch):
                    arrows.append((n, ch, line.strip()[:70]))
                else:
                    bad.append((n, ch, line.strip()[:70]))
    if arrows:
        print(f"nota: {len(arrows)} seta(s) (convernao dos docs da casa, "
              f"permitido com --allow-arrows)")
    if bad:
        print(f"PROBLEMA: {len(bad)} caractere(s) proibido(s)")
        for n, ch, line in bad:
            print(f"  linha {n}: {ch!r} (U+{ord(ch):04X}) | {line}")
        return 1
    print("OK: nenhum caractere proibido")
    return 0


if __name__ == "__main__":
    _args = sys.argv[1:]
    _allow = "--allow-arrows" in _args
    _args = [a for a in _args if a != "--allow-arrows"]
    raise SystemExit(main(_args[0], allow_arrows=_allow))
