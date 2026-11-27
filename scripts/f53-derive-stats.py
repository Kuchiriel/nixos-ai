#!/usr/bin/env python3
"""Derive f32-compatible top-k stats from an existing SimpleStories sample.

The corpus text and int32 token array already exist on the host. This helper
does not resample or re-tokenize the corpus: it counts ids in bounded text
chunks to derive the top-k remap and writes the sidecar stats JSON required
by ``f32-wordlevel.py --npy``.
"""
from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter
from pathlib import Path

import numpy as np
from transformers import GPT2TokenizerFast


TOKDIR = Path("/home/nixos/work/hybrid/gpt2-local")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True)
    parser.add_argument("--npy", required=True)
    parser.add_argument("--stats", required=True)
    parser.add_argument("--vocab", type=int, default=10_000)
    parser.add_argument("--chunk-size", type=int, default=8_000_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    started = time.perf_counter()
    text_path = Path(args.text)
    npy_path = Path(args.npy)
    if not text_path.is_file():
        raise FileNotFoundError(f"missing sampled text: {text_path}")
    if not npy_path.is_file():
        raise FileNotFoundError(f"missing sampled npy: {npy_path}")

    tokens = np.load(npy_path, mmap_mode="r")
    if tokens.dtype != np.int32:
        raise ValueError(f"expected int32 corpus, got {tokens.dtype}")

    tokenizer = GPT2TokenizerFast.from_pretrained(str(TOKDIR), local_files_only=True)
    text = text_path.read_text(errors="ignore")
    counts: Counter[int] = Counter()
    for offset in range(0, len(text), args.chunk_size):
        counts.update(tokenizer.encode(text[offset:offset + args.chunk_size]))
    top = [token for token, _ in counts.most_common(args.vocab)]
    remap = {token: index for index, token in enumerate(top)}
    vocab = len(remap)

    max_id = int(tokens[:].max()) if tokens.shape[0] else -1
    if max_id >= vocab:
        raise ValueError(f"corpus contains id {max_id} but vocab is only {vocab}")

    stats = {
        "n": int(tokens.shape[0]),
        "vocab": int(vocab),
        "remap": {str(token): index for token, index in remap.items()},
        "source": str(text_path),
        "source_bytes": len(text.encode("utf-8")),
        "derived_from": str(npy_path),
        "seed": args.seed,
        "chunk_size": args.chunk_size,
        "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
        "seconds": round(time.perf_counter() - started, 1),
    }
    Path(args.stats).write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print("RESULT " + json.dumps({
        "stats": args.stats,
        "n": stats["n"],
        "vocab": stats["vocab"],
        "max_id": max_id,
        "source_bytes": stats["source_bytes"],
        "peak_rss_bytes": stats["peak_rss_bytes"],
        "seconds": stats["seconds"],
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
