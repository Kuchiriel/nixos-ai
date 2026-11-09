#!/usr/bin/env python3
"""spk-separability.py — mede se o gate de audio (matricula do dono) SEPARA vozes.

POR QUE (08/11, docs/auditoria/VOICE-AUDIO-GATE-2026-11-08.md): o gate de
texto ja esta em 0,923 de recall, e os 2 falsos positivos restantes sao da
TV e da auto-fala. O jeito barato de mata-los e o gate de falante (o asrd ja
embute WeSpeaker 256-d e agrupa por cosseno > 0,80). MAS isso so funciona se
o embedding separar vozes diferentes nas nossas condicoes — e ninguem mediu
isso ainda. Este script mede:

  intra-falante : cosseno entre takes da MESMA voz (o que o cluster precisa)
  inter-falante : cosseno entre vozes DIFERENTES (o ruido que o gate aceita)

VEREDITO (o que o dono precisa): se o inter ficar bem abaixo do limiar de
0,80 e o intra bem acima, a matricula funciona (o gate de audio resolve os
2 FP) e o wakeword NAO e necessario. Se os dois se misturarem, o honesto e'
o wakeword (a pend. 4 original) e nao mais machine learning.

Nao escreve nada: e' leitura do corpus. O embedding e' o mesmo do asrd
(WeSpeaker ResNet34 256-d, CPU) — nada sai da box.

Uso:
    scripts/spk-separability.py                     # mede o corpus da casa
    scripts/spk-separability.py --backend wespeaker # so o backend que separa
    scripts/spk-separability.py --json

AMBIENTE (medido 09/11): o runtime `wespeakerruntime` precisa de torchaudio
(commit 20346b3d: torchaudio no devShell) E do proprio pacote, que vive no
venv lab. O `nix develop` SOBRESCREVE o PYTHONPATH, entao o caminho entra
DENTRO do comando:

    nix develop --command env PYTHONPATH=<dir-com-o-wespeakerruntime> \
        python3 scripts/spk-separability.py --backend wespeaker

Se o dir do venv entrar no PYTHONPATH inteiro, o torchaudio/numpy quebrados
de lá sombreiam os bons do devShell (numpy 2.5.3 do venv pede libstdc++ e
libz do nix): copie SO o pacote wespeakerruntime para um dir proprio.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np

THRESHOLD = 0.80  # limiar de cluster do asrd (medido no applio-lab cross-video)

# Corpus da casa: (nome, diretorio, papel). 'intra' = mesma voz, takes
# diferentes; 'inter' = vozes diferentes.
DEFAULT_GROUPS: list[tuple[str, str, str]] = [
    ("ivan", "/home/nixos/projects/applio-lab/kaggle-ivan/ds", "intra"),
    ("aot-p1", "/home/nixos/Audio/_arquivo/aot-noregrets/p1", "intra"),
    ("aot-p2-spk0", "/home/nixos/Audio/_arquivo/aot-noregrets/p2/sep/htdemucs/mix", "inter"),
    ("makima", "/home/nixos/Audio/_arquivo/hunt-tts-download/hunt-audrey", "inter"),
]


LAB_VENV = "/home/nixos/.venvs/lab/lib/python3.13/site-packages"


def _speaker(backend: str):
    """Runtime WeSpeaker (256-d).

    Medido 09/11: ele vive SO no venv `lab` e o asrd roda com outro
    PYTHONPATH, entao em producao o import falha e o asrd usa o fallback
    MFCC. Da a medicao os DOIS backends.

    (09/11, sweep-2026-11) O venv `lab` esta com torchaudio SEM torch
    pareado, entao empurrar o venv inteiro no sys.path quebra o import
    ("Could not load this library: .../torchaudio/lib/_torchaudio.abi3.so")
    mesmo quando o torch correto esta no PYTHONPATH. Fix: tenta importar
    o runtime do ambiente CORRENTE primeiro (que e o caminho certo quando
    o torch e o torchaudio estao pareados, ex.: devShell com torchaudio
    + o modulo do venv via PYTHONPATH) e so cai no venv como ultimo
    recurso.
    """
    import sys

    if backend == "wespeaker":
        try:
            import wespeakerruntime as w

            return w.Speaker(lang="en")
        except Exception:
            if LAB_VENV not in sys.path:
                sys.path.insert(0, LAB_VENV)
    import wespeakerruntime as w

    return w.Speaker(lang="en")


def _mfcc_embed(path: str) -> np.ndarray | None:
    """O MESMO fallback do asrd (duplex-asrd.py:_embed): 13 MFCC mean+std."""
    try:
        import librosa
        import soundfile as sf

        y, sr = sf.read(path, dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)
        m = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, n_fft=512, hop_length=160)
        return np.concatenate([m.mean(axis=1), m.std(axis=1)])
    except Exception:
        return None


def embed(spk, path: str, backend: str) -> np.ndarray | None:
    if backend == "mfcc":
        e = _mfcc_embed(path)
        return None if e is None else e / (np.linalg.norm(e) + 1e-9)
    try:
        e = np.array(spk.extract_embedding(path), dtype=float).ravel()
        if e.size == 0:
            return None
        return e / (np.linalg.norm(e) + 1e-9)
    except Exception:
        return None


def collect(path: str, limit: int = 8) -> list[str]:
    d = Path(path).expanduser()
    if not d.exists():
        return []
    wavs = sorted(str(p) for p in d.glob("*.wav"))
    return wavs[:limit]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--backend", choices=("wespeaker", "mfcc", "both"), default="both")
    args = ap.parse_args(argv)

    backends = ["wespeaker", "mfcc"] if args.backend == "both" else [args.backend]
    results = {}
    for backend in backends:
        results[backend] = _measure(backend, args)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for backend, out in results.items():
            print(f"== backend {backend}")
            print(f"   grupos: {out.get('groups')}")
            print(f"   intra-falante: {out.get('intra')}")
            print(f"   inter-falante: {out.get('inter')}")
            print(f"   VEREDITO: {out.get('verdict')}")
    return 0


def _measure(backend: str, args) -> dict:
    try:
        spk = _speaker(backend) if backend == "wespeaker" else None
    except Exception as e:
        return {"error": f"backend {backend} indisponivel: {type(e).__name__}: {e}"}

    embs: dict[str, list[np.ndarray]] = {}
    names: list[str] = []
    for name, path, role in DEFAULT_GROUPS:
        files = collect(path, args.limit)
        if not files:
            continue
        got = [e for e in (embed(spk, f, backend) for f in files) if e is not None]
        if len(got) >= 2:
            embs[name] = got
            names.append(name)
            names_roles = {name: role}
        else:
            print(f"AVISO: {name} sem embeddings suficientes ({len(got)}) em {path}",
                  file=sys.stderr)

    if len(embs) < 2:
        print("ERRO: preciso de pelo menos 2 grupos com 2+ takes", file=sys.stderr)
        return 2

    intra: list[float] = []
    inter: list[float] = []
    pairs: list[dict] = []
    for a in names:
        for i in range(len(embs[a])):
            for j in range(i + 1, len(embs[a])):
                intra.append(cosine(embs[a][i], embs[a][j]))
    for ai, a in enumerate(names):
        for b in names[ai + 1:]:
            for ea in embs[a]:
                for eb in embs[b]:
                    c = cosine(ea, eb)
                    inter.append(c)
                    pairs.append({"a": a, "b": b, "cos": round(c, 4)})

    def stat(v: list[float]) -> dict:
        if not v:
            return {}
        return {"n": len(v), "min": round(min(v), 4), "max": round(max(v), 4),
                "mean": round(statistics.mean(v), 4),
                "p95": round(sorted(v)[int(len(v) * 0.95) - 1], 4)}

    overlap = bool(intra and inter and min(intra) < max(inter))
    verdict = ("separavel: a matricula funciona (gate de audio resolve os 2 FP)"
               if (intra and inter and min(intra) >= args.threshold
                   and max(inter) < args.threshold)
               else ("AMBIGUO: as distribuicoes se tocam — o gate por matricula "
                     "nao segura; o honesto e' o wakeword"
                     if overlap else
                     "separacao parcial: ve o detalhe antes de decidir"))

    out = {
        "backend": backend,
        "threshold": args.threshold,
        "groups": {n: len(embs[n]) for n in names},
        "intra": stat(intra),
        "inter": stat(inter),
        "worst_inter_pairs": sorted(pairs, key=lambda p: -p["cos"])[:5],
        "verdict": verdict,
        "note": ("a separação decide entre o gate de áudio (matrícula do dono) e o "
                 "wakeword; o corpus aqui é de vozes de treino/TTS, então é "
                 "condição DE LAB, não a sala do dono — a matrícula real é a "
                 "medição que vale"),
    }
    return out


if __name__ == "__main__":
    sys.exit(main())
