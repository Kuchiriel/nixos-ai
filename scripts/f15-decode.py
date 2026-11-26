#!/usr/bin/env python3
"""F15: decode com KV cache REAL no ScaleLM 150M loop_spec.

Implementa:
  - prefill: forward completo capturando K/V (por bloco, por loop)
  - decode passo a passo com cache (per-loop e last-loop/sobrescrita)
  - verificacao de equivalencia de logits vs forward cheio no ultimo token
  - medicao de pico de VRAM e tokens/s
"""
from __future__ import annotations
import argparse, json, math, random, time
from pathlib import Path
import torch
import torch.nn.functional as F

SRC = Path("/home/nixos/projects/nixos-ai/scripts/scale-loop-ab.py")
DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")


def qkv_for(att, x, loop, spec):
    d = x.shape[-1]
    if spec:
        modq = att._spec_adapters[("q", loop)]
        modv = att._spec_adapters[("v", loop)]
        q = modq(x)
        v = modv(x)
    else:
        q = x @ att.q
        v = x @ att.v
    k = x @ att.k
    b, t, _ = x.shape
    q = q.view(b, t, att.h, att.dh).transpose(1, 2)
    k = k.view(b, t, att.h, att.dh).transpose(1, 2)
    v = v.view(b, t, att.h, att.dh).transpose(1, 2)
    return q, k, v


def attn_out(att, q, k, v, scale):
    a = torch.softmax(q @ k.transpose(-2, -1) / scale, -1)
    o = (a @ v).transpose(1, 2).contiguous().view(q.shape[0], q.shape[2], -1)
    return o @ att.o


def block_step(blk, h, cache, mode, loop=0, spec=True):
    ln = blk.ln(h)
    q, k, v = qkv_for(blk.att, ln, loop, spec)
    t = h.shape[1]
    if cache is None:
        ck, cv = k, v
    else:
        if mode == "last":
            # last-loop: sobrescreve cache anterior (1 loop de KV)
            ck, cv = k, v
        else:
            ck = torch.cat([cache[0], k], dim=2)
            cv = torch.cat([cache[1], v], dim=2)
    scale = math.sqrt(blk.att.dh * blk.att.h)
    o = attn_out(blk.att, q, ck, cv, scale)
    # Attn.forward original: x + alpha*out, com L2 se scale_in (x = ln)
    h = F.normalize(ln + blk.att.alpha * o, dim=-1) if blk.att.scale_in else ln + o
    f = blk.ff(ln)
    if blk.scale_in:
        h = F.normalize(h + blk.beta * f, dim=-1)
    else:
        h = h + f
    return h, (ck, cv)


def full_logits(model, x):
    return model(x)[:, -1, :].float()


def cached_prefill_decode(model, x, mode, spec):
    """Processa x (B,T) com cache; retorna logits no ultimo token e caches."""
    b, T = x.shape
    h = model.tok(x) + model.pos(torch.arange(T, device=x.device))
    caches = {}
    for i, blk in enumerate(model.blocks):
        if i == 2 and model.variant != "plain":
            u = h.detach().clone()
            for l in range(4):
                h = F.normalize(h + u, dim=-1)
                h, c = block_step(blk, h, None, mode, l, spec)
                caches[(i, l)] = c
        else:
            h, c = block_step(blk, h, None, mode, 0, False)
            caches[(i, 0)] = c
    return model.head(model.ln(h[:, -1:, :])).float(), caches


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["per_loop", "last"], default="last")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--steps", type=int, default=2400)
    ap.add_argument("--seed", type=int, default=43)
    ap.add_argument("--prompts", type=int, default=100)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    import runpy
    ScaleLM = runpy.run_path(str(SRC))["ScaleLM"]
    random.seed(a.seed); torch.manual_seed(a.seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(a.seed)
    text = DATA.read_text(encoding="utf-8")
    n = int(len(text)*0.9)
    chars = sorted(set(text)); stoi = {c:i for i,c in enumerate(chars)}
    ids = [stoi[c] for c in text[:n]]; vids = [stoi[c] for c in text[n:]]
    model = ScaleLM(len(chars), 1216, "loop_spec").to(a.device)
    opt = torch.optim.Adafactor(model.parameters(), lr=3e-4,
                                beta2_decay=-0.8, eps=(None, 0.001))
    model.train()
    for step in range(1, a.steps+1):
        st = torch.randint(0, len(ids)-128-1, (8,))
        x = torch.tensor([ids[k:k+128] for k in st.tolist()], device=a.device)
        y = torch.tensor([ids[k+1:k+1+128] for k in st.tolist()], device=a.device)
        with torch.autocast(device_type=a.device, dtype=torch.bfloat16):
            loss = F.cross_entropy(model(x).reshape(-1,len(chars)).float(), y.reshape(-1))
        opt.zero_grad(); loss.backward(); opt.step()
        if step % 600 == 0:
            print(json.dumps({"step":step,"loss":round(float(loss),4)}), flush=True)
    model.eval()
    rng = random.Random(1234)
    starts = [rng.randint(0, len(vids)-160) for _ in range(a.prompts)]
    diffs, acc_full, acc_cache = [], 0, 0
    peak = 0; t0 = time.perf_counter()
    with torch.no_grad():
        for k in starts:
            ctx = vids[k:k+64]; tgt = vids[k+64]
            x = torch.tensor([ctx], device=a.device)
            if a.device == "cuda": torch.cuda.reset_peak_memory_stats()
            lf = full_logits(model, x)
            lc, _ = cached_prefill_decode(model, x, a.mode, True)
            diffs.append(float((lf - lc).abs().max()))
            acc_full += int(int(lf.argmax()) == tgt)
            acc_cache += int(int(lc.argmax()) == tgt)
            if a.device == "cuda":
                peak = max(peak, torch.cuda.max_memory_allocated())
    dt = time.perf_counter()-t0
    r = {"mode": a.mode, "seed": a.seed, "prompts": a.prompts,
         "acc_full": round(acc_full/a.prompts,4),
         "acc_cached": round(acc_cache/a.prompts,4),
         "max_logit_diff": round(max(diffs),4),
         "mean_logit_diff": round(sum(diffs)/len(diffs),4),
         "peak_vram_bytes": peak,
         "eval_seconds": round(dt,1),
         "prompts_per_s": round(a.prompts/dt,2)}
    Path(a.out).write_text(json.dumps(r,indent=2)+"\n")
    print("RESULT "+json.dumps(r), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
