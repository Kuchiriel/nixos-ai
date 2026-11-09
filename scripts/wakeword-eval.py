#!/usr/bin/env python3
"""wakeword-eval.py — mede o wakeword da casa sobre o corpus de voz.

POR QUE (09/11, docs/auditoria/WAKEWORD-GATE-DESIGN-2026-11-09.md): o gate
de texto ja da recall 0,923 e a via de falante foi MEDIDA e nao fecha (intra
p95 0,6435 contra inter p95 0,5751 com limiar 0,82). O wakeword e' o sinal
que separa a TV do dono com confianca. Antes de ligar, mede-se: quantos
segmentos disparam, com que score, e como o limiar muda o resultado.

REUSO (nao reimplementa): o scorer da casa e' `modules/ai/ww_scorer.py`
(mel + embedding + classifier ONNX direto, com os 3 modelos pinados em
modules/ai/models.nix e linkados em ~/.local/share/openwakeword). Esta tool
apenas o executa em lote e resume a distribuicao de score.

O que mede (por segmento de logs/audio/):
  - o score maximo do `hey_jarvis` no segmento
  - quantos segmentos disparam acima de cada limiar
  - a calibracao com positivo/negativo quando as pastas existem
    (o proprio scorer tem --calibrate --target-fpr)

Nao mexe em servico nem em config: e' leitura do corpus.

Uso:
    scripts/wakeword-eval.py --limit 200
    scripts/wakeword-eval.py --positive-dir D1 --negative-dir D2 --target-fpr 0.01
    scripts/wakeword-eval.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCORER = REPO / "modules/ai/ww_scorer.py"
MODELS = Path.home() / ".local/share/openwakeword"
AUDIO_DIRS = [REPO / "logs/audio"]


def _score(wav: Path) -> float | None:
    """Score do wakeword no WAV (None se o scorer falhar)."""
    try:
        out = subprocess.run(
            [sys.executable, str(SCORER), "--models", str(MODELS),
             "--wav", str(wav), "--threshold", "0"],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        return None
    txt = (out.stdout or "").strip()
    import re

    for line in reversed(txt.splitlines()):
        # o scorer imprime "score=0.0001" (o numero vem depois do "=")
        m = re.search(r"([0-9]*\.?[0-9]+)\s*$", line.strip())
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--thresholds", default="0.3,0.5,0.7,0.9")
    ap.add_argument("--positive-dir", default="")
    ap.add_argument("--negative-dir", default="")
    ap.add_argument("--target-fpr", type=float, default=0.01)
    args = ap.parse_args(argv)

    if not SCORER.exists():
        print(f"ERRO: scorer da casa ausente: {SCORER}", file=sys.stderr)
        return 2
    if not MODELS.exists():
        print(f"ERRO: modelos do wakeword ausentes: {MODELS}", file=sys.stderr)
        return 2

    # modo calibracao: o proprio scorer escolhe o limiar (positivo x negativo)
    if args.positive_dir and args.negative_dir:
        cmd = [sys.executable, str(SCORER), "--models", str(MODELS),
               "--wav", str(AUDIO_DIRS[0] / "x.wav"),
               "--calibrate", "--positive-dir", args.positive_dir,
               "--negative-dir", args.negative_dir,
               "--target-fpr", str(args.target_fpr)]
        print("nota: --calibrate precisa de --wav valido; rodando com o primeiro wav")
        cmd = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        print(cmd.stdout[-2000:] or cmd.stderr[-2000:])
        return cmd.returncode

    wavs: list[Path] = []
    for d in AUDIO_DIRS:
        if d.exists():
            wavs.extend(sorted(d.rglob("*.wav")))
    wavs = wavs[: args.limit]
    if not wavs:
        print("ERRO: nenhum wav encontrado em logs/audio", file=sys.stderr)
        return 2

    scores: list[tuple[str, float]] = []
    for w in wavs:
        s = _score(w)
        if s is not None:
            scores.append((w.name, s))
    if not scores:
        print("ERRO: nenhum segmento avaliado", file=sys.stderr)
        return 2

    ths = [float(t) for t in args.thresholds.split(",") if t.strip()]
    vals = sorted(s for _, s in scores)
    out = {
        "segments": len(scores),
        "score": {
            "min": round(vals[0], 4),
            "p50": round(vals[len(vals) // 2], 4),
            "p90": round(vals[int(len(vals) * 0.9) - 1], 4),
            "max": round(vals[-1], 4),
        },
        "fired_above": {str(t): sum(1 for _, s in scores if s >= t) for t in ths},
        "top5": [{"wav": n, "score": round(s, 4)}
                 for n, s in sorted(scores, key=lambda x: -x[1])[:5]],
        "note": ("a rotulagem dono x TV exige casar o wav com o log do duplex; "
                 "este script mede a distribuicao de score — o wakeword puro e' "
                 "um padrao acustico, entao o FP real vem do RUIDO/AMBIENTE e "
                 "nao da TV (que raramente diz 'hey jarvis')"),
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"segmentos: {out['segments']}")
        print(f"score: {out['score']}")
        print(f"disparam acima: {out['fired_above']}")
        print("top5:", out["top5"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
