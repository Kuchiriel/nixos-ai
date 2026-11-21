#!/usr/bin/env python3
"""GPU forward latency: original vs LittleBit at 1.0/0.1 bpp (fp16)."""
import json, time
from argparse import Namespace
import torch
from transformers import AutoModelForCausalLM
from quantization.utils import apply_littlebit_patch
from quantization.modules import LittleBitLinear

MODEL = 'Qwen/Qwen3-0.6B'
def cfg(eff):
    return Namespace(quant_func='SmoothSign', quant_mod='LittleBitLinear',
                     eff_bit=eff, split_dim=1024, residual=False,
                     kv_factor=1.0, min_split_dim=8, use_itq=False, itq_n_iter=50)

def latency(m, x, n=20):
    m.eval()
    with torch.no_grad():
        for _ in range(3): m(x, labels=x)
        torch.cuda.synchronize(); t0 = time.perf_counter()
        for _ in range(n): m(x, labels=x)
        torch.cuda.synchronize()
        return round((time.perf_counter() - t0) * 1000 / n, 2)

def main():
    x = torch.randint(0, 1000, (1, 256), device='cuda')
    out = {'model': MODEL, 'device': 'cuda', 'seq': 256,
           'notes': 'PyTorch generico (sem kernel MatMul-free do paper)'}
    m = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float16,
                                             device_map='cuda', trust_remote_code=True)
    out['original_ms'] = latency(m, x); del m; torch.cuda.empty_cache()
    for eff in (1.0, 0.1):
        m = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.float16,
                                                 device_map='cpu', low_cpu_mem_usage=True,
                                                 trust_remote_code=True)
        m.config.use_cache = False
        m = apply_littlebit_patch(m, cfg(eff), do_train=True)
        for mod in m.modules():
            for attr in ('v1','v2','u1','u2','v1_R','v2_R','u1_R','u2_R'):
                t = getattr(mod, attr, None)
                if torch.is_tensor(t): t.data = t.data.to(torch.float16)
        m = m.cuda()
        out[f'quant_{eff}_ms'] = latency(m, x)
        del m; torch.cuda.empty_cache()
    print(json.dumps(out, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
