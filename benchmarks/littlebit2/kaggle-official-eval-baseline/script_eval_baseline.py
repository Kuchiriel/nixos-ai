#!/usr/bin/env python3
"""Evaluate the preserved official LittleBit-2 baseline checkpoint."""
import os
import subprocess
import sys

REPO = "/kaggle/working/nixos-ai"
BASELINE = "/kaggle/input/littlebit2-official-baseline-qwen3-0-6b/checkpoint"


def run(command, **kwargs):
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True, **kwargs)


run(["git", "clone", "-q", "https://github.com/Kuchiriel/nixos-ai.git", REPO])
os.chdir(REPO)
env = os.environ.copy()
env["LB_BASELINE_PATH"] = BASELINE
run([sys.executable, "benchmarks/littlebit2/kaggle-official/script.py"], env=env)
