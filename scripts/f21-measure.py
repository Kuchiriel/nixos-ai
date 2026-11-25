#!/usr/bin/env python3
"""F21: 300M loop_spec + last-loop KV on the F12 16-position protocol.

Trains one 300M checkpoint for a requested variant and seed, then evaluates
teacher-forced accuracy/calibration on 64 context + 16 target tokens.  For
``loop_spec`` it also compares full causal inference, per-loop KV caching,
and last-loop KV caching.  Plain/nGPT use the same training and full-causal
evaluation so every architecture arm is comparable.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

SRC = Path(__file__).with_name("scale-loop-ab.py")
DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")
CONTEXT_TOKENS = 64
TARGET_TOKENS = 16
PROMPT_SEED = 1234
PROMPT_MARGIN = 160  # exact F12 start bound (context 64 + evaluation margin)


def ece(conf: list[float], corr: list[int], bins: int = 10) -> float:
    """Expected calibration error, including the final bin's right edge."""
    if not conf:
        return 0.0
    out = 0.0
    for index in range(bins):
        lo = index / bins
        hi = (index + 1) / bins
        if index == bins - 1:
            rows = [i for i, value in enumerate(conf) if lo <= value <= hi]
        else:
            rows = [i for i, value in enumerate(conf) if lo <= value < hi]
        if not rows:
            continue
        accuracy = sum(corr[i] for i in rows) / len(rows)
        confidence = sum(conf[i] for i in rows) / len(rows)
        out += len(rows) / len(conf) * abs(accuracy - confidence)
    return out


def fixed_starts(total: int, prompts: int, target_tokens: int = TARGET_TOKENS) -> list[int]:
    """F12-compatible fixed prompt starts (independent of model seed)."""
    if total < PROMPT_MARGIN:
        raise ValueError("validation split is shorter than the F12 prompt margin")
    rng = random.Random(PROMPT_SEED)
    return [rng.randint(0, total - PROMPT_MARGIN) for _ in range(prompts)]


def summarize(per_position: dict[int, dict[str, list[float]]], bins: int = 10) -> dict:
    """Aggregate exact token-level accuracy/ECE and preserve per-position rows."""
    all_conf: list[float] = []
    all_corr: list[int] = []
    positions = []
    for position in sorted(per_position):
        data = per_position[position]
        conf = list(data["conf"])
        corr = list(data["corr"])
        all_conf.extend(conf)
        all_corr.extend(corr)
        positions.append({
            "pos": position,
            "conf": round(sum(conf) / len(conf), 4),
            "acc": round(sum(corr) / len(corr), 4),
            "ece": round(ece(conf, corr, bins), 4),
            "n": len(corr),
        })
    return {
        "acc_all": round(sum(all_corr) / len(all_corr), 4),
        "ece_all": round(ece(all_conf, all_corr, bins), 4),
        "per_position": positions,
    }


def tokens_until_answer(entropies: list[float], threshold: float = 0.5) -> int:
    """Dory/F20 stopping rule: three low-entropy generated positions."""
    if not entropies:
        return 0
    stop_at = len(entropies)
    for index in range(2, len(entropies)):
        if max(entropies[index - 2:index + 1]) < threshold:
            stop_at = index + 1
            break
    return stop_at


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--steps", type=int, default=4800)
    parser.add_argument("--prompts", type=int, default=100)
    parser.add_argument("--target-tokens", type=int, default=TARGET_TOKENS)
    parser.add_argument("--depth", type=int, default=1768, help="1216=150M, 1768=300M")
    parser.add_argument("--variant", choices=["plain", "ngpt_only", "loop_spec"], default="loop_spec")
    parser.add_argument("--causal-train", action="store_true",
                        help="train with the same causal mask used by KV inference")
    parser.add_argument("--modes", default="full,per_loop,last")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.target_tokens != TARGET_TOKENS:
        raise ValueError("F21 protocol requires exactly 16 target tokens")
    modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
    allowed_modes = {"full", "per_loop", "last"}
    if not modes or any(mode not in allowed_modes for mode in modes):
        raise ValueError("modes must be a subset of full,per_loop,last")
    if args.variant != "loop_spec" and modes != ["full"]:
        raise ValueError("plain/ngpt_only arms require only the full causal mode")

    import runpy
    import torch
    import torch.nn.functional as F

    ScaleLM = runpy.run_path(str(SRC))["ScaleLM"]
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    text = DATA.read_text(encoding="utf-8")
    split = int(len(text) * 0.9)
    chars = sorted(set(text))
    stoi = {char: index for index, char in enumerate(chars)}
    ids = [stoi[char] for char in text[:split]]
    validation = [stoi[char] for char in text[split:]]

    model = ScaleLM(len(chars), args.depth, args.variant).to(args.device)
    params = sum(parameter.numel() for parameter in model.parameters())
    optimizer = torch.optim.Adafactor(
        model.parameters(), lr=3e-4, beta2_decay=-0.8, eps=(None, 0.001)
    )
    model.train()
    for step in range(1, args.steps + 1):
        offsets = torch.randint(0, len(ids) - 129, (8,))
        x = torch.tensor([ids[k:k + 128] for k in offsets.tolist()], device=args.device)
        y = torch.tensor([ids[k + 1:k + 129] for k in offsets.tolist()], device=args.device)
        with torch.autocast(device_type=args.device, dtype=torch.bfloat16):
            logits = model(x, causal=True) if args.causal_train else model(x)
            loss = F.cross_entropy(logits.reshape(-1, len(chars)).float(), y.reshape(-1))
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if step % 600 == 0:
            print(json.dumps({"step": step, "loss": round(float(loss.detach()), 4)}), flush=True)

    model.eval()
    generation_entropies = []
    with torch.no_grad():
        generated = torch.zeros((1, 1), dtype=torch.long, device=args.device)
        for _ in range(128):
            logits = model(generated)[:, -1, :]
            log_probabilities = torch.log_softmax(logits.float(), -1)
            entropy = float(-(log_probabilities.exp() * log_probabilities).sum())
            generation_entropies.append(entropy)
            next_token = logits.argmax(-1, keepdim=True)
            generated = torch.cat([generated, next_token], dim=1)
    tokens_to_answer = tokens_until_answer(generation_entropies)
    starts = fixed_starts(len(validation), args.prompts, args.target_tokens)
    rows = []
    with torch.no_grad():
        for mode in modes:
            per_position = {
                position: {"conf": [], "corr": []} for position in range(args.target_tokens)
            }
            peak = 0
            started = time.perf_counter()
            for start in starts:
                if args.device == "cuda":
                    torch.cuda.reset_peak_memory_stats()
                context = validation[start:start + CONTEXT_TOKENS]
                targets = validation[
                    start + CONTEXT_TOKENS:start + CONTEXT_TOKENS + args.target_tokens
                ]

                if mode == "full":
                    hidden = torch.tensor([context], device=args.device)
                    for position, target in enumerate(targets):
                        logits = model(hidden, causal=True)[0, -1, :].float()
                        probabilities = torch.softmax(logits, -1)
                        confidence = float(probabilities.max())
                        prediction = int(probabilities.argmax())
                        per_position[position]["conf"].append(confidence)
                        per_position[position]["corr"].append(int(prediction == target))
                        if position + 1 < len(targets):
                            hidden = torch.cat(
                                [hidden, torch.tensor([[target]], device=args.device)], dim=1
                            )
                else:
                    state = {"caches": {}, "u": None}
                    output = None
                    for position, token in enumerate(context):
                        output = model.forward_cached(
                            torch.tensor([[token]], device=args.device), position, state, mode
                        )
                    for position, target in enumerate(targets):
                        probabilities = torch.softmax(output[0, 0, :].float(), -1)
                        confidence = float(probabilities.max())
                        prediction = int(probabilities.argmax())
                        per_position[position]["conf"].append(confidence)
                        per_position[position]["corr"].append(int(prediction == target))
                        if position + 1 < len(targets):
                            output = model.forward_cached(
                                torch.tensor([[target]], device=args.device),
                                CONTEXT_TOKENS + position,
                                state,
                                mode,
                            )
                if args.device == "cuda":
                    peak = max(peak, torch.cuda.max_memory_allocated())

            elapsed = time.perf_counter() - started
            summary = summarize(per_position)
            rows.append({
                "mode": mode,
                "acc": summary["acc_all"],
                "ece": summary["ece_all"],
                "peak_vram_bytes": peak,
                "seconds": round(elapsed, 1),
                "prompts_per_s": round(args.prompts / elapsed, 2),
                "per_position": summary["per_position"],
            })

    result = {
        "protocol": {
            "name": "F12-16",
            "context_tokens": CONTEXT_TOKENS,
            "target_tokens": args.target_tokens,
            "teacher_forcing": True,
            "prompts": args.prompts,
            "variant": args.variant,
            "depth": args.depth,
            "params": params,
            "steps": args.steps,
            "causal_train": args.causal_train,
            "tokens_until_answer": tokens_to_answer,
        },
        "seed": args.seed,
        "prompts": args.prompts,
        "rows": rows,
    }
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("RESULT " + json.dumps({
        "protocol": result["protocol"],
        "seed": args.seed,
        "rows": [{key: row[key] for key in (
            "mode", "acc", "ece", "peak_vram_bytes", "seconds", "prompts_per_s"
        )} for row in rows],
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
