#!/usr/bin/env python3
"""Minimal QAT A/B for LittleBit-2 with the official implementation.

Usage: python littlebit_minimal_qat.py --use-itq {True,False} --out result.json
Uses only the official quantization patch; no deepspeed/HF Trainer.
"""
from __future__ import annotations
import argparse, json, math, os, time
from argparse import Namespace
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed
from quantization.utils import apply_littlebit_patch
from utils.datautils import get_qat_dataset, get_eval_loaders, load_tokenizer

MODEL = 'Qwen/Qwen3-0.6B'
STEPS = int(os.environ.get('LB_STEPS', '60'))
SEQ = int(os.environ.get('LB_SEQ', '512'))
EVAL_WINDOWS = int(os.environ.get('LB_EVAL_WINDOWS', '12'))
RESIDUAL = os.environ.get('LB_RESIDUAL', 'False') == 'True'

def args(use_itq):
    return Namespace(quant_func='SmoothSign', quant_mod='LittleBitLinear',
                     eff_bit=1.0, split_dim=1024, residual=RESIDUAL, kv_factor=1.0,
                     min_split_dim=8, use_itq=use_itq, itq_n_iter=50)

@torch.no_grad()
def ppl(model, loader, dev, windows=EVAL_WINDOWS, seqlen=SEQ):
    model.eval()
    data = loader.input_ids
    losses = []
    for i in range(min(windows, data.size(1) // seqlen - 1)):
        x = data[:, i * seqlen:(i + 1) * seqlen].to(dev)
        out = model(x, labels=x)
        losses.append(float(out.loss))
    return math.exp(sum(losses) / len(losses)), len(losses)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--use-itq', required=True, choices=['True', 'False'])
    ap.add_argument('--out', required=True)
    ap.add_argument('--device', default='cpu', choices=['cpu', 'cuda'])
    a = ap.parse_args()
    set_seed(42)
    dev = torch.device(a.device)
    torch.set_num_threads(int(os.environ.get('LB_THREADS', '8')))
    t0 = time.time()
    tok = load_tokenizer(MODEL)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, torch_dtype=torch.float32 if a.device == 'cpu' else torch.bfloat16, device_map='cpu',
        low_cpu_mem_usage=True, trust_remote_code=True)
    model.config.use_cache = False
    model = apply_littlebit_patch(model, args(a.use_itq == 'True'), do_train=True)
    # O patch deriva as escalas da SVD em float32; com o modelo em bf16 o
    # forward falha (float != BFloat16). Converter apenas as escalas.
    for m in model.modules():
        for attr in ('v1', 'v2', 'u1', 'u2', 'v1_R', 'v2_R', 'u1_R', 'u2_R'):
            t = getattr(m, attr, None)
            if torch.is_tensor(t):
                t.data = t.data.to(torch.float32 if a.device == 'cpu' else torch.bfloat16)
    model = model.to(dev)
    model.gradient_checkpointing_enable()
    model.train()
    patch_s = time.time() - t0
    train = get_qat_dataset('wikitext2', tok)
    params = [p for p in model.parameters() if p.requires_grad]
    if a.device == 'cuda':
        import bitsandbytes as bnb
        opt = bnb.optim.AdamW8bit(params, lr=4e-5)
    else:
        opt = torch.optim.AdamW(params, lr=4e-5)
    loader = get_eval_loaders('wikitext2', tok)
    ppl0, n0 = ppl(model, loader, dev)
    losses = []
    t1 = time.time()
    for step in range(STEPS):
        chunk = train[step % len(train)]['input_ids']
        x = torch.as_tensor(chunk[:SEQ], dtype=torch.long).unsqueeze(0).to(dev)
        out = model(x, labels=x)
        opt.zero_grad(set_to_none=True)
        out.loss.backward()
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step()
        losses.append(float(out.loss))
        if step % 20 == 0:
            print('step', step, 'loss', round(losses[-1], 4), flush=True)
    train_s = time.time() - t1
    ppl1, n1 = ppl(model, loader, dev)
    result = {'model': MODEL, 'device': a.device, 'use_itq': a.use_itq == 'True', 'steps': STEPS, 'residual': RESIDUAL,
              'seq': SEQ, 'eff_bit': 1.0,
              'patch_seconds': round(patch_s, 1), 'train_seconds': round(train_s, 1),
              'ppl_before': round(ppl0, 3), 'ppl_after': round(ppl1, 3),
              'eval_windows': [n0, n1], 'initial_loss': round(losses[0], 4),
              'final_loss': round(losses[-1], 4),
              'peak_vram_mib': (round(torch.cuda.max_memory_allocated() / 2**20)
                                if a.device == 'cuda' else None),
              'trainable_params': sum(p.numel() for p in params),
              'production_writes': False}
    with open(a.out, 'w') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    main()
