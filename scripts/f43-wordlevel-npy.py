#!/usr/bin/env python3
"""F43: 150M word-level training on the large streamed NumPy corpus.

The full TinyStories corpus is hundreds of millions of int32 tokens.
Materializing it as a Python list would exhaust host memory. This trainer keeps
the corpus as a NumPy memmap and copies only the current training/validation
batches to PyTorch.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F


SRC = Path(__file__).with_name("scale-loop-ab.py")
TOKDIR = Path("/home/nixos/work/hybrid/gpt2-local")


def batch_numpy(tokens, offsets: np.ndarray, length: int):
    return np.stack([np.asarray(tokens[offset:offset + length]) for offset in offsets])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--stats", required=True)
    parser.add_argument("--steps", type=int, default=9_600)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--d", type=int, default=1_216)
    parser.add_argument("--seq", type=int, default=256)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--warmup", type=int, default=500)
    parser.add_argument("--val-ratio", type=float, default=0.01)
    parser.add_argument("--val-tokens", type=int, default=200_000)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--ckpt", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    stats = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    tokens = np.load(args.corpus, mmap_mode="r")
    token_count = min(int(tokens.shape[0]), int(stats["n"]))
    if token_count <= args.seq + 1:
        raise ValueError("corpus is too short for the requested sequence")
    train_count = int(token_count * (1.0 - args.val_ratio))
    val_count = token_count - train_count
    vocab = int(stats["vocab"])
    remap = {int(key): int(value) for key, value in (stats.get("remap") or {}).items()}
    print(
        json.dumps(
            {
                "corpus": args.corpus,
                "tokens": token_count,
                "train": train_count,
                "val": val_count,
                "vocab": vocab,
                "d": args.d,
            }
        ),
        flush=True,
    )

    import runpy

    ScaleLM = runpy.run_path(str(SRC))["ScaleLM"]
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    model = ScaleLM(vocab, args.d, "ngpt_only").to(args.device)
    params = sum(parameter.numel() for parameter in model.parameters())
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=args.lr, fused=(args.device == "cuda")
    )
    started = time.perf_counter()
    model.train()
    for step in range(1, args.steps + 1):
        offsets = np.random.randint(0, train_count - args.seq - 1, size=args.batch)
        x_numpy = batch_numpy(tokens, offsets, args.seq)
        y_numpy = batch_numpy(tokens, offsets + 1, args.seq)
        x = torch.from_numpy(x_numpy.astype(np.int64, copy=False)).to(args.device)
        y = torch.from_numpy(y_numpy.astype(np.int64, copy=False)).to(args.device)
        scale = 1.0 if args.warmup <= 0 else min(1.0, step / args.warmup)
        for group in optimizer.param_groups:
            group["lr"] = args.lr * scale
        autocast = (
            torch.autocast(device_type=args.device, dtype=torch.bfloat16)
            if args.device == "cuda"
            else nullcontext()
        )
        with autocast:
            logits = model(x, causal=True).reshape(-1, vocab).float()
            loss = F.cross_entropy(logits, y.reshape(-1))
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if step % 400 == 0:
            print(
                json.dumps(
                    {
                        "step": step,
                        "loss": round(float(loss.detach()), 4),
                        "lr": round(args.lr * scale, 8),
                    }
                ),
                flush=True,
            )

    model.eval()
    val_loss_sum = 0.0
    val_tokens = 0
    correct = 0
    validation_limit = min(args.val_tokens, val_count - args.seq - 1)
    with torch.no_grad():
        for offset in range(0, validation_limit, args.seq * args.batch):
            offsets = np.arange(
                offset,
                min(offset + args.seq * args.batch, validation_limit),
                args.seq,
                dtype=np.int64,
            )
            if len(offsets) < 2:
                break
            x_numpy = batch_numpy(tokens, offsets + train_count, args.seq)
            y_numpy = batch_numpy(tokens, offsets + train_count + 1, args.seq)
            x = torch.from_numpy(x_numpy.astype(np.int64, copy=False)).to(args.device)
            y = torch.from_numpy(y_numpy.astype(np.int64, copy=False)).to(args.device)
            logits = model(x, causal=True)
            val_loss_sum += float(
                F.cross_entropy(
                    logits.reshape(-1, vocab).float(),
                    y.reshape(-1),
                    reduction="sum",
                )
            )
            correct += int((logits.argmax(-1) == y).sum())
            val_tokens += y.numel()
    validation_loss = val_loss_sum / max(val_tokens, 1)
    result = {
        "seed": args.seed,
        "steps": args.steps,
        "vocab": vocab,
        "tokens": token_count,
        "train_tokens": train_count,
        "val_tokens": val_count,
        "d": args.d,
        "params": params,
        "corpus": args.corpus,
        "lr": args.lr,
        "warmup": args.warmup,
        "val_loss": round(validation_loss, 4),
        "perplexity": round(math.exp(min(validation_loss, 20)), 3),
        "acc": round(correct / max(val_tokens, 1), 4),
        "seconds": round(time.perf_counter() - started, 1),
    }
    if args.ckpt:
        torch.save(
            {
                "state": model.state_dict(),
                "vocab": vocab,
                "d": args.d,
                "seq": args.seq,
                "seed": args.seed,
                "tokenizer": str(TOKDIR),
                "remap": remap,
                "corpus": args.corpus,
                "validation": result,
            },
            args.ckpt,
        )
        result["checkpoint"] = args.ckpt
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("RESULT " + json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
