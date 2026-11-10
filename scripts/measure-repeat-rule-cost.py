#!/usr/bin/env python3
"""measure-repeat-rule-cost.py — custo, em fala real, das regras de repetição.

POR QUE (10/11, coord-naming): a cadeia da voz tem um residual medido de UM
caso — a risada "Hahahaha" (remediação do sweep/owner com o código de hoje:
80 clipes, cru 66, casa 1). A regra de repetição COM separador (a que está
no asrd, `scripts/voice_text_rules.py`) não pega "Hahahaha" (não há
separador), e a regra concatenada do sweep também não (o padrão não são 3
repetições exatas de um mesmo grupo).

Este script mede, sobre as transcrições REAIS da casa (o cache de
`scripts/measure-voice-rule-cost.py`, `logs/audio-transcripts.json`, 1 817
falas do dono, da TV e de notícias), o custo de cada regra candidata em fala
real, e se ela pega o caso residual.

O TRADE-OFF que o número não esconde: a risada é SINAL SOCIAL que a casa
mantém DE PROPÓSITO (`SOCIAL_KEEP` no duplex-asrd.py: risada/aplauso/música,
"direção do dono: o agente usa"). Então matar "Hahahaha" mecanicamente
também mata a risada do dono quando ele ri.

USO
    python3 scripts/measure-repeat-rule-cost.py
    python3 scripts/measure-repeat-rule-cost.py --cache <outro.json>

EXEMPLO DE SAÍDA
    transcricoes reais no cache: 1817
      CONCAT (1-3 letras)        mata   0/1817 (0.00%)
      SEPARADO (regra de hoje)   mata  15/1817 (0.83%)
"""
import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = REPO / "logs" / "audio-transcripts.json"

# repeticao concatenada: uma silaba repetida 3+ vezes sem separador
# ("hahahaha" -> "ha" x4; "tataataata" -> "ta" x3)
CONCAT = re.compile(r"\b([a-z]{1,3}?)\1{2,}\b", re.I)

# repeticao com separador: a regra que esta no asrd hoje
SEPARADO = re.compile(r"\b(\w{1,4})\b(?:[\s,.;:'\"-]+\1\b){2,}", re.I)

# o caso que sobrou na remediacao do caminho da casa
RESIDUAL = "Hahahaha"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    args = ap.parse_args()

    cache_path = Path(args.cache)
    if not cache_path.is_file():
        print(f"cache ausente: {cache_path} (rode "
              f"scripts/measure-voice-rule-cost.py antes)")
        return 1
    cache = json.loads(cache_path.read_text())
    real = [(k, v) for k, v in cache.items() if v]

    print(f"transcricoes reais no cache: {len(real)}")
    report = {"n": len(real), "rules": {}}
    for name, rule in (("CONCAT (1-3 letras)", CONCAT),
                       ("SEPARADO (regra de hoje)", SEPARADO)):
        hits = [(k, v) for k, v in real if rule.search(v)]
        report["rules"][name] = {"kills": len(hits),
                                 "rate": round(len(hits) / max(1, len(real)), 5),
                                 "examples": [v[:80] for _k, v in hits[:8]]}
        print(f"  {name:26s} mata {len(hits):3d}/{len(real)} "
              f"({len(hits)/max(1,len(real)):.2%})")
        for _k, v in hits[:5]:
            print(f"       {v[:70]!r}")

    print(f"\ncaso residual da remediacao ({RESIDUAL!r}):")
    for key, name, rule in (("CONCAT (1-3 letras)", "CONCAT", CONCAT),
                            ("SEPARADO (regra de hoje)", "SEPARADO", SEPARADO)):
        pega = bool(rule.search(RESIDUAL))
        report["rules"][key]["catches_residual"] = pega
        print(f"  {name:10s} pega: {pega}")
    print("\nATENCAO: matar a risada tambem mata a risada REAL do dono — "
          "a casa mantem sinal social de proposito (SOCIAL_KEEP).")

    out = REPO / "logs" / "repeat-rule-cost.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"relatorio: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
