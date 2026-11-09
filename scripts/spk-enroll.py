#!/usr/bin/env python3
"""spk-enroll.py — matricula a voz do dono para o gate de audio da voz.

POR QUE (medido 08/11, docs/auditoria/VOICE-AUDIO-GATE-2026-11-08.md):
o asrd (scripts/duplex-asrd.py) JA calcula embedding de falante por
segmento (WeSpeaker ResNet34 256-d, ONNX, ~83 ms/segmento na CPU) e
identifica contra perfis cadastrados (SPK_PROFILES) — mas o arquivo de
perfis nao existe, entao todo segmento sai `spk=?` (o log do duplex de
08/11 tem ZERO prefixos `[spk: ...]`). Este script e a metade que falta:
transforma alguns WAVs do dono no perfil que o asrd procura.

O perfil e DADO BIOMETRICO: ele fica em `data/spk-profiles.json` (machine
local, ignorado pelo git) e nunca sai da box (o modelo roda na CPU).

Uso:
    # 1) enroll: alguns WAVs da voz do dono (3-10, o mesmo microfone de uso)
    scripts/spk-enroll.py enroll dono wav1.wav wav2.wav wav3.wav

    # 2) verify: confere o perfil contra um WAV (a voz do dono => cos alto)
    scripts/spk-enroll.py verify dono /caminho/da/voz.wav

    # 3) status: mostra os perfis e a consistencia interna de cada um
    scripts/spk-enroll.py status

Saida JSON (--json) para consumo por tool.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO / "data" / "spk-profiles.json"
SPEAKER_RUNTIME = "wespeakerruntime"


def _speaker():
    import wespeakerruntime as w

    return w.Speaker(lang="en")


def embed(wav_path: str) -> np.ndarray:
    """Embedding 256-d normalizado do mesmo jeito que o asrd faz."""
    spk = _speaker()
    e = np.array(spk.extract_embedding(wav_path), dtype=float).ravel()
    return e / (np.linalg.norm(e) + 1e-9)


def load_profiles() -> dict[str, np.ndarray]:
    try:
        cfg = json.loads(PROFILE_PATH.read_text())
    except Exception:
        return {}
    return {k: np.array(v, dtype=float) for k, v in cfg.items()}


def save_profiles(profiles: dict[str, np.ndarray]) -> None:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(
        json.dumps({k: [round(float(x), 6) for x in v] for k, v in profiles.items()},
                   indent=1)
    )
    PROFILE_PATH.chmod(0o600)  # dado biometrico: so o dono


def enroll(name: str, wavs: list[str], replace: bool = False) -> dict:
    profiles = load_profiles()
    if name in profiles and not replace:
        raise SystemExit(f"perfil '{name}' ja existe (use --replace)")
    embs = []
    for w in wavs:
        if not Path(w).exists():
            raise SystemExit(f"wav nao encontrado: {w}")
        embs.append(embed(w))
    if len(embs) < 2:
        raise SystemExit("use pelo menos 2 WAVs (a consistencia interna precisa de comparacao)")
    centroid = np.mean(embs, axis=0)
    centroid = centroid / (np.linalg.norm(centroid) + 1e-9)
    # consistencia: cada amostra contra o centroide (o dono deve ser > 0.8)
    cons = [float(np.dot(e, centroid)) for e in embs]
    profiles[name] = centroid
    save_profiles(profiles)
    return {
        "action": "enroll",
        "name": name,
        "samples": len(embs),
        "min_consistency": round(min(cons), 4),
        "max_consistency": round(max(cons), 4),
        "mean_consistency": round(float(np.mean(cons)), 4),
        "profile": str(PROFILE_PATH),
        "note": ("consistencia baixa: WAVs de falantes diferentes ou ruido? "
                 "o dono costuma ficar > 0.8" if min(cons) < 0.8 else "ok"),
    }


def verify(name: str, wav: str) -> dict:
    profiles = load_profiles()
    if name not in profiles:
        raise SystemExit(f"perfil '{name}' nao existe (rode enroll antes)")
    e = embed(wav)
    cos = float(np.dot(e, profiles[name]))
    others = {k: round(float(np.dot(e, v)), 4) for k, v in profiles.items() if k != name}
    best = max(others, key=others.get) if others else None
    return {
        "action": "verify",
        "wav": wav,
        "target": name,
        "cosine": round(cos, 4),
        "other_profiles": others,
        "best_other": best,
        "verdict": ("owner" if cos >= 0.8 else
                    ("ambiguous" if best and others[best] > cos - 0.05 else "not-owner")),
    }


def status() -> dict:
    profiles = load_profiles()
    return {
        "action": "status",
        "path": str(PROFILE_PATH),
        "exists": PROFILE_PATH.exists(),
        "profiles": {k: {"dim": int(v.shape[0]), "norm": round(float(np.linalg.norm(v)), 4)}
                     for k, v in profiles.items()},
        "note": ("sem perfis: o asrd sai sempre com spk=? e o gate de audio nao tem "
                 "como separar a TV do dono" if not profiles else
                 "perfis presentes: o asrd deve identificar por cosseno"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("enroll", help="matricula a voz do dono")
    e.add_argument("name")
    e.add_argument("wavs", nargs="+")
    e.add_argument("--replace", action="store_true")

    v = sub.add_parser("verify", help="confere um WAV contra um perfil")
    v.add_argument("name")
    v.add_argument("wav")

    sub.add_parser("status", help="mostra os perfis matriculados")

    a = ap.parse_args(argv)
    try:
        if a.cmd == "enroll":
            out = enroll(a.name, a.wavs, a.replace)
        elif a.cmd == "verify":
            out = verify(a.name, a.wav)
        else:
            out = status()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        out = {"error": f"{type(e).__name__}: {e}"}
        print(json.dumps(out) if a.json else f"ERRO: {e}", file=sys.stderr)
        return 2

    print(json.dumps(out, indent=2) if a.json else _human(out))
    return 0


def _human(o: dict) -> str:
    if o.get("error"):
        return f"ERRO: {o['error']}"
    if o["action"] == "enroll":
        return (f"matriculado '{o['name']}' com {o['samples']} WAVs "
                f"(consistencia min {o['min_consistency']}, media {o['mean_consistency']}) "
                f"-> {o['profile']}\n{o['note']}")
    if o["action"] == "verify":
        return (f"{o['wav']} vs '{o['target']}': cos {o['cosine']} -> {o['verdict']} "
                f"(outros: {o['other_profiles']})")
    if not o["exists"]:
        return f"sem perfis em {o['path']}\n{o['note']}"
    return (f"{len(o['profiles'])} perfil(is) em {o['path']}: "
            + ", ".join(f"{k} ({v['dim']}d)" for k, v in o["profiles"].items()))


if __name__ == "__main__":
    sys.exit(main())
