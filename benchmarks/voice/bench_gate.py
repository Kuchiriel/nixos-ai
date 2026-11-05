#!/usr/bin/env python3
"""Bench do GATE de endereçamento do duplex (o bug do dono: "ignora quase tudo").

Diagnóstico: em `scripts/duplex-voice.py`, com `GATE_MODE="on"`, um RESPOND
do classificador LoRA só vira resposta se `_addressed(heard)` for True — e
`_addressed` (linha 247) exige **"Jarvis" (fuzzy)**. O "?" e os verbos de
comando foram removidos depois do caso da TV ("where's the one?"). Resultado:
falas do dono sem a palavra-mágica são descartadas → FN alto.

Este bench mede, com o código REAL do duplex (import), cada variante de gate
sobre um dataset rotulado PT-BR no estilo de voz:

  enderecado  → `_addressed` (atual, com GATE_MODE=on)
  lora        → `classify_turn` == RESPOND (LoRA micro-turn no 4B:8092)
  intent      → `classify_intent` ∈ {QUESTION, COMMAND} (4B + GBNF, hoje
                MORTO no código — definido na 304, nunca chamado)
  proposto    → enderecado OR intent
  lora+prop   → lora AND (enderecado OR intent)  [o hot path real]

Métricas: TP/FP/FN do "responder", precision/recall/F1, latência por variante.

Uso:
    python3 benchmarks/voice/bench_gate.py --base http://127.0.0.1:8092
    python3 benchmarks/voice/bench_gate.py --json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# (falas, esperado) — "RESPOND" = o dono quer resposta; "IGNORE" = TV/sala/
# backchannel; "WAIT" = frase incompleta (o merge deve segurar).
DATASET: list[tuple[str, str]] = [
    # ── RESPOND (sem "Jarvis" = o caso que o gate atual descarta) ────────
    ("que horas são", "RESPOND"),
    ("acende a luz do escritório", "RESPOND"),
    ("arruma a cafeteira", "RESPOND"),
    ("toca uma música", "RESPOND"),
    ("está muito frio aqui", "RESPOND"),
    ("me lembra de comprar pão amanhã", "RESPOND"),
    ("qual o status do sistema", "RESPOND"),
    ("abre o navegador", "RESPOND"),
    ("desliga o som da sala", "RESPOND"),
    ("preciso de uma ideia para o jantar", "RESPOND"),
    ("Jarvis, que dia é hoje", "RESPOND"),
    ("vai chover hoje?", "RESPOND"),
    # ── IGNORE (TV, sala, backchannel) ──────────────────────────────────
    ("where's the one?", "IGNORE"),
    ("obrigado", "IGNORE"),
    ("hum", "IGNORE"),
    ("[música]", "IGNORE"),
    ("[risadas]", "IGNORE"),
    ("vamos embora", "IGNORE"),
    ("cheguei tarde hoje", "IGNORE"),
    ("isso é muito bom", "IGNORE"),
    ("passa o sal", "IGNORE"),
    ("ele disse que vem amanhã", "IGNORE"),
    ("a música tá tocando baixinho", "IGNORE"),
    ("Jarvis, desliga a luz", "RESPOND"),
    # ── WAIT (incompleto → segurar e reavaliar) ─────────────────────────
    ("então eu queria te dizer", "WAIT"),
    ("deixa eu ver uma coisa", "WAIT"),
    ("a gente tava falando sobre", "WAIT"),
]


def _load_duplex():
    """Importa o módulo real do duplex (main guard no fim → seguro)."""
    path = REPO / "scripts/duplex-voice.py"
    spec = importlib.util.spec_from_file_location("duplex_voice_ref", path)
    mod = importlib.util.module_from_spec(spec)
    sys.argv = [str(path)]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8092")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    dv = _load_duplex()
    base = args.base

    rows: list[dict] = []
    for utter, expected in DATASET:
        t0 = time.perf_counter()
        addressed = dv._addressed(utter)
        ms_addr = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        lab = dv.classify_turn(base, utter)
        ms_lora = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        intent = dv.classify_intent(base, utter)
        ms_int = (time.perf_counter() - t0) * 1000

        intent_cmd = intent in ("QUESTION", "COMMAND")
        variants = {
            "enderecado": addressed,
            "lora": lab == "RESPOND",
            "intent": intent_cmd,
            "proposto": bool(addressed or intent_cmd),
            "lora+prop": bool(lab == "RESPOND" and (addressed or intent_cmd)),
        }
        rows.append({
            "utter": utter, "expected": expected, "lora_label": lab, "intent": intent,
            "addressed": bool(addressed),
            "ms": {"enderecado": round(ms_addr, 1), "lora": round(ms_lora, 1),
                   "intent": round(ms_int, 1)},
            "variants": variants,
        })

    names = ["enderecado", "lora", "intent", "proposto", "lora+prop"]
    summary = {}
    for v in names:
        tp = sum(1 for r in rows if r["expected"] == "RESPOND" and r["variants"][v])
        fn = sum(1 for r in rows if r["expected"] == "RESPOND" and not r["variants"][v])
        fp = sum(1 for r in rows if r["expected"] != "RESPOND" and r["variants"][v])
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        summary[v] = {"tp": tp, "fn": fn, "fp": fp, "precision": round(prec, 3),
                      "recall": round(rec, 3), "f1": round(f1, 3)}

    lat_lora = [r["ms"]["lora"] for r in rows]
    lat_int = [r["ms"]["intent"] for r in rows]
    meta = {
        "ms_lora_mean": round(statistics.mean(lat_lora), 1),
        "ms_lora_max": round(max(lat_lora), 1),
        "ms_intent_mean": round(statistics.mean(lat_int), 1),
        "ms_intent_max": round(max(lat_int), 1),
        "n": len(rows),
    }

    if args.json:
        print(json.dumps({"summary": summary, "meta": meta, "rows": rows},
                         indent=2, ensure_ascii=False))
        return 0

    print("GATE_BENCH n={n} (base={base})".format(n=meta["n"], base=base))
    for v in names:
        s = summary[v]
        print(f"  {v:11s} TP={s['tp']:2d} FN={s['fn']:2d} FP={s['fp']:2d} "
              f"p={s['precision']:.3f} r={s['recall']:.3f} f1={s['f1']:.3f}")
    print(f"  latência: lora mean={meta['ms_lora_mean']}ms max={meta['ms_lora_max']}ms | "
          f"intent mean={meta['ms_intent_mean']}ms max={meta['ms_intent_max']}ms")
    print("--- detalhe (FN = dono fala e é ignorado) ---")
    for r in rows:
        if r["expected"] == "RESPOND" and not r["variants"]["proposto"]:
            mark = "FN  "
        elif r["expected"] != "RESPOND" and r["variants"]["proposto"]:
            mark = "FP  "
        else:
            mark = "    "
        print(f"  {mark} exp={r['expected']:7s} addr={int(r['addressed'])} "
              f"lora={r['lora_label']!s:8s} intent={r['intent']!s:11s} | {r['utter'][:46]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
