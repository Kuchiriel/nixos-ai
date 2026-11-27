#!/usr/bin/env python3
"""F104: byte+EOT 257 symbols — paired d=1312 training preparation.

This wrapper deliberately supports --check only in the F104 lane.  The real
training path is implemented but is never launched by --check.  It loads the
existing ScaleLM implementation and the canonical f32-wordlevel trainer with
byte-EOT defaults fixed to the preregistered F102 gate.
"""
from __future__ import annotations

import argparse
import json
import os
import runpy
from pathlib import Path

NPY = Path("/home/nixos/work/hybrid/byte-eot-ids.npy")
STATS = Path("/home/nixos/work/hybrid/byte-eot-ids-stats.json")
SCALE_SRC = Path("/home/nixos/projects/nixos-ai/scripts/scale-loop-ab.py")
TRAIN_SRC = Path("/home/nixos/projects/nixos-ai/scripts/f32-wordlevel.py")
EXPECTED_IDS = 24_918_286
EXPECTED_VOCAB = 257
EXPECTED_D = 1312


def check() -> int:
    result = {
        "event": "F104-byte-EOT-check",
        "trainer": str(TRAIN_SRC),
        "scale_model": str(SCALE_SRC),
        "corpus": str(NPY),
        "stats": str(STATS),
        "expected_ids": EXPECTED_IDS,
        "expected_vocab": EXPECTED_VOCAB,
        "d": EXPECTED_D,
        "no_train": True,
        "gpu_guard": "run-byte-eot.sh --check",
    }
    errors = []
    if not NPY.is_file():
        errors.append("corpus ausente")
    if not STATS.is_file():
        errors.append("stats ausente")
    if not TRAIN_SRC.is_file():
        errors.append("trainer ausente")
    if not SCALE_SRC.is_file():
        errors.append("scale model ausente")
    if STATS.is_file():
        try:
            stats = json.loads(STATS.read_text(encoding="utf-8"))
            result["stats_measured"] = {
                "n": stats.get("n"),
                "vocab": stats.get("vocab"),
                "eot_id": stats.get("eot_id"),
                "eot_count": stats.get("eot_count"),
            }
            if stats.get("n") != EXPECTED_IDS:
                errors.append(f"ids esperado {EXPECTED_IDS}, medido {stats.get('n')}")
            if stats.get("vocab") != EXPECTED_VOCAB:
                errors.append(f"vocab esperado {EXPECTED_VOCAB}, medido {stats.get('vocab')}")
        except Exception as exc:
            errors.append(f"stats invalido: {exc}")
    result["ok"] = not errors
    result["errors"] = errors
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not errors else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="validate artifacts and print the F104 contract; never train")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--steps", type=int, default=9600)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--seq", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--warmup", type=int, default=500)
    parser.add_argument("--out", default="/home/nixos/work/hybrid/f104-byte-eot-d1312-s42.json")
    parser.add_argument("--ckpt", default="/home/nixos/work/hybrid/checkpoints/f104-byte-eot-d1312-s42.pt")
    args = parser.parse_args()

    if args.check:
        return check()

    # The launcher is responsible for refusing a busy GPU.  Keep this second
    # guard here so direct invocation cannot accidentally overlap a live job.
    if args.device == "cuda":
        import subprocess
        query = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10, check=False)
        pids = [line.strip() for line in query.stdout.splitlines()
                if line.strip() and line.strip() != "2882380"]
        if pids:
            print("F104: GPU ocupada por jobs CUDA=" + ",".join(pids), flush=True)
            return 9

    os.environ["BYTE_EOT_D"] = str(EXPECTED_D)
    os.environ["BYTE_EOT_NPY"] = str(NPY)
    os.environ["BYTE_EOT_EXPECTED_IDS"] = str(EXPECTED_IDS)
    sys_argv = [
        str(TRAIN_SRC),
        "--npy", str(NPY),
        "--d", str(EXPECTED_D),
        "--steps", str(args.steps),
        "--seed", str(args.seed),
        "--batch", str(args.batch),
        "--seq", str(args.seq),
        "--no-ss",
        "--lr", str(args.lr),
        "--warmup", str(args.warmup),
        "--device", args.device,
        "--ckpt", args.ckpt,
        "--out", args.out,
    ]
    old_argv = __import__("sys").argv
    try:
        __import__("sys").argv = sys_argv
        runpy.run_path(str(TRAIN_SRC), run_name="__main__")
    finally:
        __import__("sys").argv = old_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
