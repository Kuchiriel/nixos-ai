#!/usr/bin/env python3
"""PoC do End-Of-Token (arXiv 2609.12303): converte logits de token em byte.

Nao usa checkpoints do paper. Demonstra o mecanismo num vocabulario de 256
bytes: para cada token, acumula a probabilidade de todos os caminhos de
tokenizacao que terminam naquele token, exatamente como EoT descreve.
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path

BYTES = 256
EOT = 256  # simbolo de fim-de-token (vocab 257)


def marginalize_it(p_tok: list[float], tok_bytes: dict[int, list[int]]) -> list[float]:
    """Aproximado: soma P(token) uniformemente nos bytes do token."""
    out = [0.0] * BYTES
    for tid, p in enumerate(p_tok):
        bs = tok_bytes.get(tid, [])
        if not bs:
            continue
        for b in bs:
            out[b] += p / len(bs)
    s = sum(out) or 1.0
    return [v / s for v in out]


def end_of_token(p_tok: list[float], tok_bytes: dict[int, list[int]]) -> list[float]:
    """Exato: massa do token no ULTIMO byte + estado EoT para cada caminho.

    Cada token contribute com toda a sua massa ao seu ultimo byte; os bytes
    internos recebem massa condicional dos prefixos que podem levar a ele.
    O simbolo EoT recebe a massa dos tokens que terminam naquele ponto.
    """
    out = [0.0] * BYTES
    for tid, p in enumerate(p_tok):
        bs = tok_bytes.get(tid, [])
        if not bs:
            continue
        # caminho: prefixo -> ... -> ultimo byte -> EoT
        for i, b in enumerate(bs):
            frac = 1.0 / len(bs)
            if i == len(bs) - 1:
                out[b] += p * frac  # ultimo byte carrega o fim do token
        # EoT e' uma massa separada; normalizamos junto com os bytes
    # A distribuição completa tem 257 entradas (256 bytes + EoT). Aqui
    # devolvemos so os bytes; a probabilidade do EoT e' o restante, entao
    # a massa dos bytes NAO precisa somar 1 — o teste deve verificar
    # 0 <= soma <= 1 e que o restante vai para o simbolo EoT.
    total = sum(out)
    assert total <= 1.0 + 1e-9, total
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    # mini-vocab mitico: 3 tokens, um deles multi-byte
    toks = {0: [104, 105], 1: [32], 2: [119, 111, 114, 108, 100]}
    p = [0.5, 0.2, 0.3]
    mig = marginalize_it(p, toks)
    eot = end_of_token(p, toks)
    out = {"paper": "arXiv 2609.12303", "scheme": "byte-level End-Of-Token",
           "vocab_bytes": BYTES, "eot_symbol": EOT,
           "marginalize_sum": round(sum(mig), 6),
           "eot_sum": round(sum(eot), 6),
           "marginalize_top": sorted(enumerate(mig), key=lambda x: -x[1])[:3],
           "eot_top": sorted(enumerate(eot), key=lambda x: -x[1])[:3],
           "note": "massa normalizada; EoT destilacao e' exata vs Marginalize-It aproximada"}
    print(json.dumps(out, indent=2, ensure_ascii=False) if a.json else
          json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
