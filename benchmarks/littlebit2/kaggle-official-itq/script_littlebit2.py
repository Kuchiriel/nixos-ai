#!/usr/bin/env python3
"""Run the official LittleBit-2 ITQ variant in its own Kaggle session."""
import os
import subprocess
import sys

REPO = "/kaggle/working/nixos-ai"


def run(command, **kwargs):
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True, **kwargs)


run(["git", "clone", "-q", "https://github.com/Kuchiriel/nixos-ai.git", REPO])
os.chdir(REPO)
env = os.environ.copy()
env["LB_VARIANT"] = "littlebit2"
run([sys.executable, "benchmarks/littlebit2/kaggle-official/script.py"], env=env)
