#!/usr/bin/env python3
"""F53: build a deterministic ~200 MB SimpleStories word-level corpus.

The source is the already-downloaded SimpleStories processed.parquet. Stories
are selected with diversity strata (theme/topic/style/feature) and a stable
hash order, then tokenized with the local GPT-2 tokenizer and remapped to the
10k most frequent ids. Output is an int32 NumPy array plus a sidecar stats
JSON, both compatible with f32-wordlevel.py --npy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from transformers import GPT2TokenizerFast


TOKDIR = Path("/home/nixos/work/hybrid/gpt2-local")


def stable_key(generation_id: str, story: str) -> str:
    return hashlib.sha256(f"{generation_id}\0{story}".encode("utf-8")).hexdigest()


def diversity_strata(row: dict) -> str:
    return "|".join(
        str(row.get(key, ""))
        for key in ("theme", "topic", "style", "feature")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", required=True)
    parser.add_argument("--text", default="", help="existing sampled text to reuse")
    parser.add_argument("--out", required=True)
    parser.add_argument("--stats", required=True)
    parser.add_argument("--derive-stats-only", action="store_true",
                        help="reuse an existing text/npy pair and only derive top-k remap stats")
    parser.add_argument("--target-bytes", type=int, default=200_000_000)
    parser.add_argument("--vocab", type=int, default=10_000)
    parser.add_argument("--batch-size", type=int, default=2_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    started = time.perf_counter()
    tokenizer = GPT2TokenizerFast.from_pretrained(str(TOKDIR), local_files_only=True)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.derive_stats_only:
        if not args.text:
            raise ValueError("--derive-stats-only requires --text")
        text_path = Path(args.text)
        if not text_path.is_file():
            raise FileNotFoundError(f"missing sampled text: {text_path}")
        if not output.is_file():
            raise FileNotFoundError(f"missing sampled npy: {output}")
        text = text_path.read_text(errors="ignore")
        chunk_size = 8_000_000
        counts: Counter[int] = Counter()
        for offset in range(0, len(text), chunk_size):
            counts.update(tokenizer.encode(text[offset:offset + chunk_size]))
        top = [token for token, _ in counts.most_common(args.vocab)]
        remap = {token: index for index, token in enumerate(top)}
        mapped = np.load(output, mmap_mode="r")
        stats = {
            "n": int(mapped.shape[0]),
            "vocab": int(len(remap)),
            "remap": {str(token): index for token, index in remap.items()},
            "source": str(args.parquet),
            "source_bytes": len(text.encode("utf-8")),
            "derived_from": str(text_path),
            "seed": args.seed,
            "strata": None,
            "seconds": round(time.perf_counter() - started, 1),
        }
        Path(args.stats).write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
        print("RESULT " + json.dumps({
            "out": str(output),
            "tokens": stats["n"],
            "vocab": stats["vocab"],
            "source_bytes": stats["source_bytes"],
            "derived_from": str(text_path),
            "seconds": stats["seconds"],
        }), flush=True)
        return 0

    parquet = pq.ParquetFile(args.parquet)
    columns = ["generation_id", "story", "theme", "topic", "style", "feature"]
    selected_texts: list[str] = []
    selected_bytes = 0
    strata_seen: Counter[str] = Counter()
    total_rows = 0

    for batch in parquet.iter_batches(batch_size=args.batch_size, columns=columns):
        rows = batch.to_pylist()
        # Stable hash order inside each parquet batch, with diversity strata
        # round-robin so one prolific theme cannot dominate the sample.
        rows.sort(key=lambda row: stable_key(str(row["generation_id"]), str(row["story"])))
        by_stratum: dict[str, list[dict]] = {}
        for row in rows:
            by_stratum.setdefault(diversity_strata(row), []).append(row)
        stratum_names = sorted(by_stratum)
        cursors = {name: 0 for name in stratum_names}
        while selected_bytes < args.target_bytes and any(
            cursors[name] < len(by_stratum[name]) for name in stratum_names
        ):
            for name in stratum_names:
                if cursors[name] >= len(by_stratum[name]):
                    continue
                row = by_stratum[name][cursors[name]]
                cursors[name] += 1
                story = str(row["story"])
                encoded = story.encode("utf-8")
                if selected_bytes + len(encoded) > args.target_bytes:
                    continue
                selected_texts.append(story)
                selected_bytes += len(encoded)
                strata_seen[name] += 1
                total_rows += 1
                if selected_bytes >= args.target_bytes:
                    break
        if selected_bytes >= args.target_bytes:
            break

    if not selected_texts:
        raise RuntimeError("no stories selected from SimpleStories parquet")
    text = "\n".join(selected_texts)
    encoded = tokenizer.encode(text, add_special_tokens=False)
    counts = Counter(encoded)
    top = [token for token, _ in counts.most_common(args.vocab)]
    remap = {token: index for index, token in enumerate(top)}
    mapped = np.asarray([remap.get(token, 0) for token in encoded], dtype=np.int32)

    np.save(output, mapped, allow_pickle=False)
    stats = {
        "n": int(mapped.shape[0]),
        "vocab": int(len(remap)),
        "remap": {str(token): index for token, index in remap.items()},
        "source": str(args.parquet),
        "source_bytes": selected_bytes,
        "selected_rows": total_rows,
        "target_bytes": args.target_bytes,
        "seed": args.seed,
        "strata": len(strata_seen),
        "stratum_counts": dict(strata_seen.most_common()),
        "seconds": round(time.perf_counter() - started, 1),
    }
    Path(args.stats).write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print("RESULT " + json.dumps({
        "out": str(output),
        "tokens": stats["n"],
        "vocab": stats["vocab"],
        "source_bytes": stats["source_bytes"],
        "selected_rows": stats["selected_rows"],
        "strata": stats["strata"],
        "seconds": stats["seconds"],
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
