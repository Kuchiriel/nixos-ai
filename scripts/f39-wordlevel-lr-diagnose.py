#!/usr/bin/env python3
"""F39: diagnose 150M word-level seed instability with LR + warmup.

The F37 seed43 run stayed near loss 6 from the first logged step while the
seed42 run converged. This trainer makes the learning rate explicit,
supports a deterministic warmup, validates early (step 400 by default),
and preserves the full curve/best-checkpoint evidence.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import Counter
from contextlib import nullcontext
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import GPT2TokenizerFast


SRC = Path(__file__).with_name("scale-loop-ab.py")
CORPUS = Path("/home/nixos/Books/corpora/TinyStories-valid.txt")
TOKDIR = Path("/home/nixos/work/hybrid/gpt2-local")


def build_tokens(topk=10000, limit=20_000_000):
    tok = GPT2TokenizerFast.from_pretrained(str(TOKDIR), local_files_only=True)
    text = CORPUS.read_text(errors="ignore")[:limit]
    ids = tok.encode(text)
    common = [word for word, _ in Counter(ids).most_common(topk)]
    remap = {word: index for index, word in enumerate(common)}
    return [remap.get(word, 0) for word in ids], len(remap)


def evaluate(model, validation, seq, batch, device, vocab, max_tokens):
    """Evaluate on a bounded validation slice without changing train mode."""
    was_training = model.training
    model.eval()
    val_loss = 0.0
    tokens = 0
    correct = 0
    limit = min(max_tokens, len(validation) - seq - 1)
    with torch.no_grad():
        for offset in range(0, limit, seq * batch):
            contexts = [
                validation[offset + offset_in:offset + offset_in + seq]
                for offset_in in range(0, seq * batch, seq)
            ]
            contexts = [context for context in contexts if len(context) == seq]
            if len(contexts) < 2:
                break
            x = torch.tensor(contexts, device=device)
            y = torch.tensor(
                [
                    validation[offset + offset_in + 1:offset + offset_in + 1 + seq]
                    for offset_in in range(0, seq * len(contexts), seq)
                ],
                device=device,
            )
            logits = model(x, causal=True)
            val_loss += float(
                F.cross_entropy(
                    logits.reshape(-1, vocab).float(),
                    y.reshape(-1),
                    reduction="sum",
                )
            )
            correct += int((logits.argmax(-1) == y).sum())
            tokens += y.numel()
    if was_training:
        model.train()
    loss = val_loss / max(tokens, 1)
    return {
        "val_loss": round(loss, 6),
        "perplexity": round(math.exp(min(loss, 20)), 4),
        "acc": round(correct / max(tokens, 1), 6),
        "val_tokens": tokens,
    }


def checkpoint_path(pattern: str, step: int) -> Path:
    if "{step}" in pattern:
        return Path(pattern.replace("{step}", str(step)))
    return Path(f"{pattern}.step{step}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=9_600)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--warmup", type=int, default=500)
    parser.add_argument("--first-val-step", type=int, default=400)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--d", type=int, default=704)
    parser.add_argument("--seq", type=int, default=256)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--no-ss", action="store_true")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--val-every", type=int, default=4_000)
    parser.add_argument("--val-tokens", type=int, default=200_000)
    parser.add_argument("--ckpt", default="", help="checkpoint pattern; {step} is replaced")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.val_every <= 0:
        raise ValueError("val-every must be positive")

    import runpy

    ScaleLM = runpy.run_path(str(SRC))["ScaleLM"]
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    sequence, vocab = build_tokens()
    split = int(len(sequence) * 0.95)
    train, validation = sequence[:split], sequence[split:]
    print(
        json.dumps(
            {
                "tokens": len(sequence),
                "vocab": vocab,
                "train": len(train),
                "val": len(validation),
            }
        ),
        flush=True,
    )

    model = ScaleLM(vocab, args.d, "ngpt_only").to(args.device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=args.lr, fused=(args.device == "cuda")
    )
    started = time.perf_counter()
    model.train()
    curve = []
    best = None

    for step in range(1, args.steps + 1):
        warmup_scale = 1.0 if args.warmup <= 0 else min(1.0, step / args.warmup)
        current_lr = args.lr * warmup_scale
        for group in optimizer.param_groups:
            group["lr"] = current_lr
        offsets = torch.randint(0, len(train) - args.seq - 1, (args.batch,))
        x = torch.tensor([train[k:k + args.seq] for k in offsets.tolist()], device=args.device)
        y = torch.tensor([train[k + 1:k + 1 + args.seq] for k in offsets.tolist()], device=args.device)
        probability = 1.0 - step / args.steps
        if (not args.no_ss) and random.random() < probability and step % 4 == 0:
            with torch.no_grad():
                prefix = x[:, :32]
                for _ in range(32):
                    logits = model(prefix, causal=True)[:, -1, :]
                    prefix = torch.cat([prefix, logits.argmax(-1, keepdim=True)], dim=1)
                x = torch.cat([x[:, :32], prefix[:, 32:], x[:, 64:]], dim=1)
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
                        "p": round(probability, 3),
                        "lr": current_lr,
                    }
                ),
                flush=True,
            )

        if step == args.first_val_step or step % args.val_every == 0 or step == args.steps:
            metrics = evaluate(
                model,
                validation,
                args.seq,
                args.batch,
                args.device,
                vocab,
                args.val_tokens,
            )
            record = {"step": step, **metrics}
            if args.ckpt:
                path = checkpoint_path(args.ckpt, step)
                path.parent.mkdir(parents=True, exist_ok=True)
                torch.save(
                    {
                        "state": model.state_dict(),
                        "vocab": vocab,
                        "d": args.d,
                        "seq": args.seq,
                        "seed": args.seed,
                        "step": step,
                        "lr": current_lr,
                        "warmup": args.warmup,
                        "tokenizer": str(TOKDIR),
                        "validation": metrics,
                    },
                    path,
                )
                record["checkpoint"] = str(path)
            curve.append(record)
            if best is None or metrics["val_loss"] < best["val_loss"]:
                best = dict(record)
                print("BEST " + json.dumps(best), flush=True)
            print("VALID " + json.dumps(record), flush=True)

    if best is None:
        raise RuntimeError("no validation point was recorded")
    result = {
        "seed": args.seed,
        "steps": args.steps,
        "vocab": vocab,
        "tokens": len(sequence),
        "d": args.d,
        "scheduled_sampling": not args.no_ss,
        "lr": args.lr,
        "warmup": args.warmup,
        "first_val_step": args.first_val_step,
        "val_every": args.val_every,
        "val_tokens_limit": args.val_tokens,
        "curve": curve,
        "best": best,
        "final": curve[-1],
        "seconds": round(time.perf_counter() - started, 1),
    }
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("RESULT " + json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
