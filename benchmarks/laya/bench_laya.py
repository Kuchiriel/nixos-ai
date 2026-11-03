#!/usr/bin/env python3
"""Bench do Laya fine-tuned (dificuldade) — PT-BR de voz.

O Laya (`laya-jarvis-difficulty`, ModernBERT-large fine-tuned, ONNX CPU) é o
classificador PRIMÁRIO de dificuldade em `core/model_policy.py:classify_difficulty`
(regex é o fallback). O dono pediu para TESTAR o modelo fine-tuned — este
script mede, em vez de acreditar na nota do card (95,6% acc).

O que mede:
  - acc por classe e macro-F1 (argmax da Laya vs rótulo);
  - confiança (prob do argmax) — para calibrar um threshold de "escalate";
  - latência por inferência (o hot path do duplex paga isso);
  - quantas vezes a Laya devolve None (=> cai no regex) e com queagreement;
  - divergência Laya vs regex (quem acerta mais).

Dataset: falas curtas PT-BR no estilo do duplex (comandos, perguntas de sala,
tarefas harder) — é o uso real, não inglês de benchmark.

Uso:
    python3 benchmarks/laya/bench_laya.py            # tabela + resumo
    python3 benchmarks/laya/bench_laya.py --json     # JSON
    LAYA_MODEL_DIR=/home/nixos/models/laya-onnx python3 benchmarks/laya/bench_laya.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "modules/ai/jarvis/src"))

# (prompt, esperado) — falas de voz PT-BR, 8 por classe.
DATASET: list[tuple[str, str]] = [
    # ── simple ────────────────────────────────────────────────────────────
    ("que horas são", "simple"),
    ("Jarvis, que dia é hoje?", "simple"),
    ("toca uma música", "simple"),
    ("Jarvis, liga a luz", "simple"),
    ("qual é a capital do Brasil", "simple"),
    ("obrigado", "simple"),
    ("repete isso", "simple"),
    ("desliga a tv", "simple"),
    # ── moderate ─────────────────────────────────────────────────────────
    ("explica como funciona o roteamento de modelos", "moderate"),
    ("resume o que você fez ontem", "moderate"),
    ("Jarvis, monta um e-mail curto para o cliente pedindo prazo", "moderate"),
    ("qual a diferença entre memória e RAG?", "moderate"),
    ("me lembra de comprar pão amanhã", "moderate"),
    ("traduz essa frase para inglês: bom dia, tudo bem?", "moderate"),
    ("como faço para o Jarvis responder em português?", "moderate"),
    ("lista os arquivos do diretório de scripts", "moderate"),
    # ── hard ─────────────────────────────────────────────────────────────
    ("desenha a arquitetura de um sistema de voz duplex com cancelamento de eco e streaming de STT", "hard"),
    ("explica por que o driver NVIDIA quebra com kernel 7.2 e propose um plano de mitigação", "hard"),
    ("faz um plano de implantação para rotear o LLM entre local e nuvem com fallback", "hard"),
    ("analisa por que o duplex ignora a maioria das falas e corrige o gate", "hard"),
    ("escreve um ensaio sobre arquitectura de software", "hard"),
    ("calcula a probabilidade de uma chamada Poisson com lambda 4", "hard"),
    ("projetar um sistema distribuído com cache distribuído e consistência eventual", "hard"),
    ("depura um erro de deadlock em código concorrente em Go", "hard"),
]


def _regex_label(prompt: str) -> str:
    """Fallback do model_policy (regex) — mesmo caminho, sem Laya."""
    # Força o fallback: chama a função com o Laya indisponível.
    import jarvis.core.laya_classifier as lc
    from jarvis.core.model_policy import classify_difficulty

    orig = lc.classify_difficulty_laya
    lc.classify_difficulty_laya = lambda *a, **k: None  # type: ignore[assignment]
    try:
        return classify_difficulty(prompt, 0)
    finally:
        lc.classify_difficulty_laya = orig  # type: ignore[assignment]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    from jarvis.core.laya_classifier import classify_choice

    options = {
        "simple": "greetings, greetings, short factual questions, simple lookups, yes/no, formatting, translation of a phrase",
        "moderate": "code explanation, multi-step instructions, moderate reasoning, drafting emails, summarizing text, standard analysis",
        "hard": "complex reasoning, architecture design, debugging multi-file systems, mathematics proofs, creative writing, long context synthesis, expert domain questions",
    }
    question = "How difficult is this request for a small local language model?"

    t_load = time.perf_counter()
    probe = classify_choice(state="teste", question=question, options=options)
    load_s = time.perf_counter() - t_load
    if probe is None:
        print("LAYA INDISPONIVEL (onnxruntime/tokenizer/modelo) — nada a medir", file=sys.stderr)
        return 2

    rows: list[dict] = []
    for prompt, expected in DATASET:
        t0 = time.perf_counter()
        probs = classify_choice(state=prompt, question=question, options=options)
        ms = (time.perf_counter() - t0) * 1000
        if probs is None:
            rows.append({"prompt": prompt, "expected": expected, "laya": None,
                         "regex": _regex_label(prompt), "ms": round(ms, 1), "conf": None})
            continue
        laya = max(probs, key=probs.get)
        rows.append({
            "prompt": prompt,
            "expected": expected,
            "laya": laya,
            "regex": _regex_label(prompt),
            "conf": round(probs[laya], 3),
            "ms": round(ms, 1),
            "ok": laya == expected,
            "probs": {k: round(v, 3) for k, v in probs.items()},
        })

    valid = [r for r in rows if r.get("laya")]
    n = len(valid)
    acc = sum(1 for r in valid if r["ok"]) / n if n else 0.0
    classes = ("simple", "moderate", "hard")
    per_class = {}
    f1s = []
    for c in classes:
        tp = sum(1 for r in valid if r["expected"] == c and r["laya"] == c)
        fp = sum(1 for r in valid if r["expected"] != c and r["laya"] == c)
        fn = sum(1 for r in valid if r["expected"] == c and r["laya"] != c)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per_class[c] = {"acc": round(sum(1 for r in valid if r["expected"] == c and r["laya"] == c)
                                     / max(1, sum(1 for r in valid if r["expected"] == c)), 3),
                        "precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3)}
        f1s.append(f1)
    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0
    lat = [r["ms"] for r in valid] or [0.0]
    agree = sum(1 for r in valid if r["regex"] == r["laya"]) / n if n else 0.0
    regex_acc = sum(1 for r in valid if r["regex"] == r["expected"]) / n if n else 0.0
    none_hits = len(rows) - len(valid)

    summary = {
        "n": n,
        "none_hits": none_hits,
        "load_s": round(load_s, 2),
        "laya_acc": round(acc, 3),
        "macro_f1": round(macro_f1, 3),
        "regex_acc": round(regex_acc, 3),
        "agreement_laya_regex": round(agree, 3),
        "ms_mean": round(statistics.mean(lat), 1),
        "ms_p95": round(sorted(lat)[int(len(lat) * 0.95) - 1], 1) if lat else None,
        "ms_max": round(max(lat), 1),
        "per_class": per_class,
    }

    if args.json:
        print(json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False))
        return 0

    print(f"LAYA_BENCH n={n} acc={summary['laya_acc']} macro_f1={summary['macro_f1']} "
          f"regex_acc={summary['regex_acc']} agree={summary['agreement_laya_regex']} "
          f"none={none_hits} load={summary['load_s']}s "
          f"ms(mean/p95/max)={summary['ms_mean']}/{summary['ms_p95']}/{summary['ms_max']}")
    for c in classes:
        pc = per_class[c]
        print(f"  {c:9s} acc={pc['acc']:.3f} p={pc['precision']:.3f} r={pc['recall']:.3f} f1={pc['f1']:.3f}")
    print("--- detalhe ---")
    for r in rows:
        mark = "OK " if r.get("ok") else ("ERR" if r.get("laya") else "NUL")
        print(f"  {mark} exp={r['expected']:8s} laya={r['laya']!s:8s} regex={r['regex']:8s} "
              f"conf={r.get('conf')} ms={r['ms']:6.1f} | {r['prompt'][:58]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
