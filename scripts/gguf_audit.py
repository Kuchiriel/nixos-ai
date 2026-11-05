#!/usr/bin/env python3
"""Audit GGUFs: real dims -> KV/token -> ctx fit.
Reads only file headers (fast, no model load).
Usage: gguf_audit.py [modelsdir]  (default ~/models, JSON to stdout)
Method (same as bonsai profile comment): KV q4_0 ~= 0.5625 B/elem;
KV/tok = 2 * layers * kv_heads * head_dim * 0.5625.
Fit rule (6GB VRAM box): ctx <= min(native, floor((budget - weights -
overhead) / kv_per_tok)), rounded down to pow2. Deployed (colocated)
values are SMALLER than solo values: MoE slices + embeddings + router
share the same 6GB (see profiles budget comments in modules/ai/models.nix).
MoE/hybrid models: formula overstates ~2x (linear-attn layers carry
little KV) — measured runtime values win (ex: MoE 35B = 45MB @ 8k).
"""
import glob
import json
import os
import struct
import sys

SZ = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
FMT = {0: 'B', 1: 'b', 2: 'H', 3: 'h', 4: 'I', 5: 'i', 6: 'f',
       7: '?', 10: 'Q', 11: 'q', 12: 'd'}
WANT = ('block_count', 'context_length', 'embedding_length',
        'feed_forward_length', 'attention.head_count',
        'attention.head_count_kv', 'attention.key_length',
        'attention.value_length')


def read_meta(path):
    """Authoritative dims. head_dim := attention.key_length (what llama.cpp
    allocates!) — NOT hidden/heads (Qwen3.x decouples them: 2560 hidden
    with 128-dim heads). Falls back to hidden/heads only if key_length
    absent. Lesson paid 03/10 (64k miscalc on the 4B)."""
    f = open(path, 'rb')
    assert f.read(4) == b'GGUF'
    ver, nt, nkv = struct.unpack('<IQQ', f.read(20))
    out = {}
    for _ in range(nkv):
        ln = struct.unpack('<Q', f.read(8))[0]
        if ln > 200:
            break
        k = f.read(ln).decode(errors='replace')
        t = struct.unpack('<I', f.read(4))[0]
        if t == 8:
            ln2 = struct.unpack('<Q', f.read(8))[0]
            v = f.read(ln2)[:120].decode(errors='replace')
        elif t == 9:
            at = struct.unpack('<I', f.read(4))[0]
            if at == 8:
                n = struct.unpack('<Q', f.read(8))[0]
                for _ in range(min(n, 3)):
                    ln3 = struct.unpack('<Q', f.read(8))[0]
                    f.read(ln3)
            else:
                n = struct.unpack('<Q', f.read(8))[0]
                f.read(n * SZ.get(at, 1))
            continue
        else:
            v = struct.unpack('<' + FMT[t], f.read(SZ[t]))[0]
        if '.' in k and k.split('.', 1)[1] in WANT + (
                'attention.key_length', 'attention.value_length'):
            out[k] = v
    return out


def analyze(path):
    size_gb = os.path.getsize(path) / 1e9
    m = read_meta(path)
    pre = next(iter(m)).split('.')[0] if m else '?'
    L = m.get(f'{pre}.block_count')
    H = m.get(f'{pre}.embedding_length')
    hq = m.get(f'{pre}.attention.head_count')
    hkv = m.get(f'{pre}.attention.head_count_kv')
    nctx = m.get(f'{pre}.context_length')
    # head_dim: key_length FIRST (authoritative). Derivation lies on Qwen3.x.
    hd = m.get(f'{pre}.attention.key_length')
    if hd is None and H and hq:
        hd = H // hq
    kv_per_tok = None
    if L and hkv and hd:
        kv_per_tok = 2 * L * hkv * hd * 0.5625  # q4_0 KV
    return {'file': os.path.basename(path), 'gb': round(size_gb, 2),
            'arch': pre, 'layers': L, 'hidden': H, 'q_heads': hq,
            'kv_heads': hkv, 'head_dim': hd, 'native_ctx': nctx,
            'kv_b_per_tok': round(kv_per_tok) if kv_per_tok else None}


if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/models')
    rows = []
    for p in sorted(glob.glob(os.path.join(d, '*.gguf'))):
        try:
            rows.append(analyze(p))
        except Exception as e:
            rows.append({'file': os.path.basename(p), 'error': str(e)[:60]})
    print(json.dumps(rows, indent=1))
