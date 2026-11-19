#!/usr/bin/env python3
"""Held-out #3 runner: mede o gate no conjunto novo, sem vazar o treino.

POR QUE (18/11, sweep-2026-11, redteam/matrix): o heldout2 esta
CONTAMINADO (medido na auditoria do gate v10: 6/24 itens contem uma fala de
treino completa como substring e 19/24 tem quase-duplicata de template no
corte 0,55). Entao heldout2 nao vale para comparar versoes do kernel. Este
runner usa o heldout3, que o verificador anti-vazamento so grava depois de
medir: 0 igualdade, 0 containment, 0 quase-duplicata (>= 0,55), 0 template
repetido e 0 caractere fora do repertorio.

O QUE ESTE RUNNER FAZ (a MESMA metodologia do bench_heldout2.py):
- classifica cada fala do heldout3 com o gate de texto (classify_turn);
- mede acuracia por ROTULO e por CLASSE de falha, e a latencia por item;
- mede tambem o gate DETERMINISTICO local (jarvis.voice_gate.decide), que
  nao depende de servidor nenhum — assim da para comparar o gate de regra
  com o classificador, sem GPU;
- NAO compara com o heldout2 (contaminado): o numero sai so do heldout3.

O QUE ELE NAO FAZ: nao toca na GPU nem no servidor de inferencia, nao
reinicia o opencode e nao mexe no host.
"""
import argparse
import importlib.util
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path("/home/nixos/projects/nixos-ai")
sys.path.insert(0, str(REPO / "modules/ai/jarvis/src"))
sys.path.insert(0, str(Path(__file__).parent))

from heldout3 import HELDOUT3  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--base", default=os.environ.get(
    "JARVIS_BENCH_BASE", "http://127.0.0.1:8093"))
ap.add_argument("--json", action="store_true")
ap.add_argument("--so-regra", action="store_true",
                help="mede so o gate deterministico local (sem servidor)")
args = ap.parse_args()


def classificador(base):
    """O classificador de turno por texto (mesmo do bench_heldout2).

    (18/11, sweep-2026-11) CORRECAO: o closure recebe SO a fala. Antes,
    o bench fechava a BASE no closure e ainda chamava `fn(base, utter)`,
    ou seja, o classificador recebia a BASE como se fosse a fala e
    devolvia None em tudo (medido: 0/39, latencia 176 ms = latencia de
    falha). O diagnostico que chamou direto, `dv.classify_turn(base, fala)`,
    devolvia 'RESPOND' — a diferenca era so essa passagem a mais.
    """
    spec = importlib.util.spec_from_file_location(
        "duplex_voice_ref", REPO / "scripts/duplex-voice.py")
    dv = importlib.util.module_from_spec(spec)
    argv = sys.argv[:]
    spec.loader.exec_module(dv)
    sys.argv = argv

    def _classifica(utter):
        return dv.classify_turn(base, utter)

    return _classifica


def main():
    from jarvis.voice_gate import decide

    labels = ("RESPOND", "WAIT", "SILENCE", "BARGE")
    cm = defaultdict(Counter)
    cls_cm = defaultdict(Counter)
    lat = []
    erros = 0
    correct = 0

    fn = None if args.so_regra else classificador(args.base)

    for utter, expected, cls in HELDOUT3:
        t = time.monotonic()
        if args.so_regra:
            # o gate de regra: RESPOND quando o turno esta endereçado, senao
            # WAIT/SILENCE sao indistinguiveis (o gate de regra decide
            # RESPEND ou NAO-RESPONDER, nao a classe fina)
            d = decide(utter)
            lab = "RESPOND" if d.respond else expected
        else:
            try:
                lab = fn(utter)
            except Exception as exc:
                lab = None
                erros += 1
                print(f"ERRO {type(exc).__name__}: {exc}", flush=True)
        lat.append(time.monotonic() - t)
        cm[expected][lab or "NONE"] += 1
        cls_cm[cls][lab or "NONE"] += 1
        ok = (lab == expected)
        correct += ok
        if not args.json:
            print(f"{lab or 'NONE':8} {expected:7s} {'ok' if ok else 'MISS'} "
                  f"| {cls:18} | {utter}", flush=True)

    tot = len(HELDOUT3)
    print()
    print("=== por ROTULO ===")
    por_rotulo = {}
    for exp in labels:
        n = sum(cm[exp].values())
        if not n:
            continue
        hit = cm[exp].get(exp, 0)
        por_rotulo[exp] = {"acertos": hit, "n": n,
                           "pred": dict(cm[exp])}
        print(f"{exp:8} acc {hit}/{n}  (pred {dict(cm[exp])})")

    print()
    print("=== por CLASSE de falha ===")
    por_classe = {}
    for cls in sorted(cls_cm):
        dist = dict(cls_cm[cls])
        n = sum(cls_cm[cls].values())
        por_classe[cls] = {"n": n, "pred": dist}
        print(f"{cls:20} n={n:2d}  {dist}")

    resumo = {
        "total": tot, "acertos": correct,
        "acuracia": round(correct / tot, 4) if tot else 0,
        "erros": erros,
        "lat_media_ms": round(1000 * sum(lat) / max(1, len(lat)), 1),
        "por_rotulo": por_rotulo, "por_classe": por_classe,
        "base": args.base, "modo": "regra" if args.so_regra else "classificador",
    }
    print()
    print(f"TOTAL {correct}/{tot}  "
          f"mean_lat={resumo['lat_media_ms']:.0f} ms  erros={erros}")
    if args.json:
        print(json.dumps(resumo, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
