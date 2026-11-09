#!/usr/bin/env python3
"""voice-trigger-fixtures.py — gera os parquets do trigger bench (durable).

POR QUE (09/11, handoff HANDOFF-2026-11-09-bateria-e2e-3-bloqueadores): a
bateria E2E de voz reportava 'sem fixtures' nas 4 categorias porque os
parquets moraram em `/tmp/opencode/night-microturn/kaggle-pkg/` e a limpeza
do /tmp levou. Licao da casa: **fixture de eval nao vive em /tmp**.

Este script e' a metade que e' do coord-naming: o **schema**. O sweep
(ou qualquer um) traz a FONTE do audio (subset do Scicom/Emilia) e a
divisao por categoria; este script empacota no formato que o bench consome:

  <saida>/silence.parquet
  <saida>/nonspeech.parquet
  <saida>/music.parquet
  <saida>/reduplication.parquet

Cada linha tem as colunas que `scripts/duplex-eval.py` le:
  id    : identificador do audio
  audio : {"bytes": <FLAC embutido>, "path": <caminho de origem>}

O audio e' re-encodado em FLAC (o bench manda os bytes direto para o
endpoint do ASRD; WAV 增加ria o payload em ~4x).

Uso:
    # 1) manifesto: JSON {categoria: [caminhos de wav]}
    scripts/voice-trigger-fixtures.py --manifest /caminho/manifest.json \
        --out ~/.local/share/jarvis/voice-trigger

    # 2) ou linhas por categoria: silence=/caminho/silence.txt ...
    scripts/voice-trigger-fixtures.py --out DIR \
        silence=lista.txt nonspeech=lista.txt music=lista.txt reduplication=lista.txt

    # conferir
    scripts/voice-trigger-fixtures.py --verify DIR
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

CATEGORIES = ("silence", "nonspeech", "music", "reduplication")
DEFAULT_OUT = Path.home() / ".local/share/jarvis/voice-trigger"


def _flac_bytes(path: Path) -> bytes:
    """Re-encoda em FLAC (o bench manda os bytes crus para o ASRD)."""
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(str(path), dtype="int16", always_2d=False)
    if getattr(data, "ndim", 1) > 1:
        data = data.mean(axis=1).astype(np.int16)
    buf = io.BytesIO()
    sf.write(buf, data, sr, format="FLAC", subtype="PCM_16")
    return buf.getvalue()


def _manifest_paths(spec: str) -> list[Path]:
    """Uma entrada: caminho de .txt (uma por linha) ou caminho de .wav."""
    p = Path(spec).expanduser()
    if p.is_dir():
        return sorted(q for q in p.rglob("*.wav"))
    if p.suffix == ".wav":
        return [p]
    if p.exists():
        return [Path(line.strip()) for line in p.read_text().splitlines()
                if line.strip() and not line.startswith("#")]
    raise FileNotFoundError(spec)


def build(manifest: dict[str, list[Path]], out_dir: Path) -> dict:
    import pandas as pd

    out_dir.mkdir(parents=True, exist_ok=True)
    report = {}
    for cat, files in manifest.items():
        rows = []
        for f in files:
            if not f.exists():
                continue
            try:
                rows.append({"id": f.stem,
                             "audio": {"bytes": _flac_bytes(f), "path": str(f)}})
            except Exception as e:
                print(f"AVISO: {f}: {type(e).__name__}: {e}", file=sys.stderr)
        if not rows:
            report[cat] = {"rows": 0, "error": "sem audio utilizavel"}
            continue
        df = pd.DataFrame(rows)
        path = out_dir / f"{cat}.parquet"
        df.to_parquet(path, index=False)
        report[cat] = {"rows": len(rows), "path": str(path),
                       "bytes": path.stat().st_size}
    return report


def verify(out_dir: Path) -> int:
    """Le os parquets como o bench le (id + audio.bytes) e reporta."""
    import pandas as pd

    bad = 0
    for cat in CATEGORIES:
        p = out_dir / f"{cat}.parquet"
        if not p.is_file():
            print(f"{cat}: AUSENTE ({p})")
            bad += 1
            continue
        df = pd.read_parquet(p)
        ok_bytes = 0
        for _, row in df.iterrows():
            try:
                b = row["audio"]["bytes"]
                if isinstance(b, (bytes, bytearray)) and len(b) > 0:
                    ok_bytes += 1
            except Exception:
                pass
        print(f"{cat}: {len(df)} linhas | id ok={df['id'].notna().sum()} | "
              f"audio.bytes ok={ok_bytes} | {p.stat().st_size} bytes")
        if len(df) == 0 or ok_bytes < len(df):
            bad += 1
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--manifest", default="", help="JSON {categoria: [wavs]}")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--verify", default="", help="verifica os parquets deste dir")
    ap.add_argument("--limit", type=int, default=0, help="max por categoria (0 = tudo)")
    for c in CATEGORIES:
        ap.add_argument(c, nargs="?", default="", help=f"lista de {c}")
    args = ap.parse_args(argv)

    if args.verify:
        return verify(Path(args.verify).expanduser())

    manifest: dict[str, list[Path]] = {}
    if args.manifest:
        data = json.loads(Path(args.manifest).expanduser().read_text())
        for cat, files in data.items():
            manifest[cat] = [Path(f).expanduser() for f in files]
    else:
        for cat in CATEGORIES:
            spec = getattr(args, cat) or ""
            # aceita "silence=/path" (o shell passa o token inteiro) e "/path"
            if spec.startswith(f"{cat}="):
                spec = spec.split("=", 1)[1]
            if spec:
                manifest[cat] = _manifest_paths(spec)
    if not manifest:
        print("ERRO: use --manifest ou categoria=lista.txt", file=sys.stderr)
        return 2

    if args.limit:
        manifest = {k: v[: args.limit] for k, v in manifest.items()}

    out = Path(args.out).expanduser()
    report = build(manifest, out)
    print(json.dumps(report, indent=2))
    print(f"\nfixtures em: {out}")
    return verify(out)


if __name__ == "__main__":
    sys.exit(main())
