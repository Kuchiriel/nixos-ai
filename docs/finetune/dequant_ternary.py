"""Dequantize ternary GGUF (inference-exact values) -> HF safetensors FP16.
Why: LoRA must train against the SAME activations inference sees.
Unpacked repo is dense-FP (425 uniques) != ternary behavior.
STATUS 21/09: non-Q2_0 tensors OK (145); Q2_0_g64 needs PrismML grouped decoder
(QK2_0=64, values {-1,0,+1,+2} per wackmall ggml-quants.c; g64 grouping unverified).
Parked until DPO-synth400 eval decides if mismatch-free base is needed.
Usage: python3 dequant_ternary.py <in.gguf> <out_dir>  (copies config/tokenizer from unpacked)
"""
import json
import os
import shutil
import sys

import numpy as np
import torch
from gguf import GGUFReader
from safetensors.torch import save_file

SRC = sys.argv[1] if len(sys.argv) > 1 else "/nix/store/nc3rnnsmz17mnhbqfry1xiw3lk5sni0x-Ternary-Bonsai-8B-Q2_0_g64.gguf"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/home/nixos/.cache/bonsai-ternary-fp16"
UNPACKED = "/home/nixos/.cache/bonsai-unpacked"

from gguf.quants import dequantize
from gguf.constants import GGMLQuantizationType
reader = GGUFReader(SRC)
tensors = {}
for t in reader.tensors:
    name = str(t.name)
    try:
        data = dequantize(t.data, t.tensor_type)
    except Exception as e:
        print("SKIP", name, t.tensor_type, str(e)[:80])
        continue
    arr = np.asarray(data, dtype=np.float32)
    # skip non-weight metadata tensors
    if arr.ndim == 0:
        continue
    tensors[name] = torch.from_numpy(arr.astype(np.float16))
print("tensors:", len(tensors))
os.makedirs(OUT, exist_ok=True)
save_file(tensors, os.path.join(OUT, "model.safetensors"))
for fn in ("config.json", "tokenizer.json", "tokenizer_config.json",
           "special_tokens_map.json", "merges.txt", "added_tokens.json",
           "generation_config.json", "chat_template.jinja"):
    src = os.path.join(UNPACKED, fn)
    if os.path.exists(src):
        shutil.copy(src, os.path.join(OUT, fn))
print("SAVED", OUT)
