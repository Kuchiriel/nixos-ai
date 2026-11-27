#!/usr/bin/env python3
"""F51: evaluate a saved 150M checkpoint on the full-corpus held-out split.

This is deliberately not another training run. It loads the checkpoint's
state_dict, evaluates the same 200k-token validation window used by f32, and
never performs an update step or writes back to the checkpoint.
"""
from __future__ import annotations

import argparse
import json
import math
import runpy
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F


SRC = Path(__file__).with_name("scale-loop-ab.py")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--seq", type=int, default=256)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--val-ratio", type=float, default=0.01)
    parser.add_argument("--val-tokens", type=int, default=200_000)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    stats_path = Path(args.corpus).with_name(
        Path(args.corpus).name.replace(".npy", "-stats.json")
    )
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    tokens = np.load(args.corpus, mmap_mode="r")
    token_count = min(int(tokens.shape[0]), int(stats["n"]))
    train_count = int(token_count * (1.0 - args.val_ratio))
    val_count = token_count - train_count
    vocab = int(stats["vocab"])

    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    depth = int(checkpoint["d"])
    checkpoint_vocab = int(checkpoint["vocab"])
    if checkpoint_vocab != vocab:
        raise ValueError(
            f"checkpoint vocab {checkpoint_vocab} != corpus vocab {vocab}"
        )

    ScaleLM = runpy.run_path(str(SRC))["ScaleLM"]
    model = ScaleLM(vocab, depth, "ngpt_only")
    model.load_state_dict(checkpoint["state"], strict=True)
    model.to(args.device)
    model.eval()

    started = time.perf_counter()
    loss_sum = 0.0
    token_count_seen = 0
    correct = 0
    validation_limit = min(args.val_tokens, val_count - args.seq - 1)
    with torch.no_grad():
        # Mirror f32-wordlevel.py exactly: contiguous windows from offset 0,
        # grouped in batches of seq*batch. The previous implementation reused
        # the same offsets inside every group, which over-counted tokens.
        starts = np.arange(0, validation_limit, args.seq, dtype=np.int64)
        for group in range(0, len(starts), args.batch):
            offsets = starts[group:group + args.batch]
            if len(offsets) < 2:
                break
            x_numpy = np.stack(
                [np.asarray(tokens[train_count + j:train_count + j + args.seq])
                 for j in offsets]
            )
            y_numpy = np.stack(
                [np.asarray(tokens[train_count + j + 1:train_count + j + 1 + args.seq])
                 for j in offsets]
            )
            x = torch.from_numpy(x_numpy.astype(np.int64, copy=False)).to(args.device)
            y = torch.from_numpy(y_numpy.astype(np.int64, copy=False)).to(args.device)
            logits = model(x, causal=True)
            loss_sum += float(
                F.cross_entropy(
                    logits.reshape(-1, vocab).float(),
                    y.reshape(-1),
                    reduction="sum",
                )
            )
            correct += int((logits.argmax(-1) == y).sum())
            token_count_seen += y.numel()

    val_loss = loss_sum / max(token_count_seen, 1)
    result = {
        "checkpoint": args.checkpoint,
        "checkpoint_step": checkpoint.get("step"),
        "checkpoint_seed": checkpoint.get("seed"),
        "corpus": args.corpus,
        "tokens": token_count,
        "train_tokens": train_count,
        "val_tokens": val_count,
        "evaluated_tokens": token_count_seen,
        "vocab": vocab,
        "d": depth,
        "val_loss": round(val_loss, 4),
        "perplexity": round(math.exp(min(val_loss, 20)), 3),
        "acc": round(correct / max(token_count_seen, 1), 4),
        "seconds": round(time.perf_counter() - started, 1),
        "trained": False,
        "checkpoint_modified": False,
    }
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("RESULT " + json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
