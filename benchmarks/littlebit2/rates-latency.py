#!/usr/bin/env python3
"""Measure LittleBit compression at several bitrates and forward latency."""
import json, time
from argparse import Namespace
import torch
from transformers import AutoModelForCausalLM
from quantization.utils import apply_littlebit_patch
from quantization.modules import LittleBitLinear

MODEL = 'Qwen/Qwen3-0.6B'
torch.set_num_threads(8)

def cfg(eff, residual):
    return Namespace(quant_func='SmoothSign', quant_mod='LittleBitLinear',
                     eff_bit=eff, split_dim=1024, residual=residual,
                     kv_factor=1.0, min_split_dim=8, use_itq=False, itq_n_iter=50)

def load():
    return AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float32,
                                                device_map='cpu', low_cpu_mem_usage=True,
                                                trust_remote_code=True)

def stats(m):
    orig = new = n = 0
    for mod in m.modules():
        if isinstance(mod, LittleBitLinear):
            a, b = mod.in_features, mod.out_features
            orig += a * b * 32   # FP32 baseline (modelo carregado em FP32)
            new += a * b * float(mod._eff_bit_actual)
            n += 1
    return {'layers': n, 'fp32_mb': round(orig / 8 / 1e6, 1),
            'quant_mb': round(new / 8 / 1e6, 1),
            'compression_x': round(orig / new, 2)}

def latency(m, x, n=8):
    m.eval()
    with torch.no_grad():
        for _ in range(2):
            m(x, labels=x)
        t0 = time.perf_counter()
        for _ in range(n):
            m(x, labels=x)
        return round((time.perf_counter() - t0) * 1000 / n, 1)

def main():
    x = torch.randint(0, 1000, (1, 256))
    out = {'model': MODEL, 'notes': 'latencia em CPU generica (sem kernel MatMul-free)'}
    m = load()
    out['original'] = {'params': sum(p.numel() for p in m.parameters()),
                       'latency_ms': latency(m, x)}
    del m
    rates = []
    for eff, residual in ((1.0, False), (1.0, True), (0.55, False), (0.1, False)):
        m = load()
        m.config.use_cache = False
        m = apply_littlebit_patch(m, cfg(eff, residual), do_train=True)
        row = {'eff_bit': eff, 'residual': residual, **stats(m),
               'latency_ms': latency(m, x)}
        rates.append(row)
        del m
    out['quantized'] = rates
    print(json.dumps(out, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
