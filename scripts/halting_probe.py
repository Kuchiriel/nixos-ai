#!/usr/bin/env python3
"""F124: probe de halting por token — SEM treino.

--check : so guarda/estado, nao carrega modelo nem GPU
--run   : curva forcada depth1-4 + sweep KL epsilon + regra de F123 (F125)
"""
import argparse, json, math, time
from pathlib import Path

B = Path("/home/nixos/work/hybrid")
EPS = [1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1e-1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("check", "run"))
    ap.add_argument("--d", type=int, default=1216)
    ap.add_argument("--ckpt", default=str(B / "checkpoints/f75-simplefull-s42.pt"))
    ap.add_argument("--npy", default="/home/nixos/Books/corpora/tinystories-full-ids.npy")
    ap.add_argument("--tokens", type=int, default=200000)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--out", default=str(B / "halting-probe.json"))
    a = ap.parse_args()
    if a.mode == "check":
        print(json.dumps({"event": "check", "eps": EPS, "no_train": True,
                          "protocol": "docs/f123-halting-gate-detalhe-2026-11-27.md"}))
        return
    import torch, numpy as np, runpy
    cls = runpy.run_path(str(B / "scale-loop-halting.py"))["ScaleLM"]
    m = cls(10000, a.d, "ngpt_only").to(a.device)
    ck = torch.load(a.ckpt, map_location=a.device, weights_only=False)
    m.load_state_dict(ck["state"], strict=True); m.eval()
    arr = np.load(a.npy, mmap_mode="r")
    val = arr[int(len(arr) * 0.99):]
    L, bs, N = 256, 4, a.tokens
    forced = {}
    traces = []
    t0 = time.perf_counter()
    with torch.no_grad():
        for t in (1, 2, 3, 4):
            vl = corr = cnt = 0
            for k in range(0, N, L * bs):
                xs = [val[k+j:k+j+L] for j in range(0, L*bs, L)]
                xs = [z for z in xs if len(z) == L]
                if len(xs) < 2: break
                x = torch.tensor(np.asarray(xs), dtype=torch.long, device=a.device)
                y = torch.tensor(np.asarray([val[k+j+1:k+j+1+L] for j in range(0, L*len(xs), L)]),
                                 dtype=torch.long, device=a.device)
                lg, tr = m(x, causal=True, max_loops=t, return_trace=True)
                lp = torch.log_softmax(lg[:, -1, :].float(), -1)
                # x = val[k:k+L]; y = val[k+1:k+1+L]; logits da ultima
                # posicao preveem val[k+L] = y[:, -1]
                vl += float(-lp.gather(1, y[:, -1:]).sum()); corr += int((lp.argmax(-1)==y[:, -1]).sum()); cnt += y.shape[0]
            forced[f"depth{t}"] = {"val_loss": round(vl/cnt, 4), "acc": round(corr/cnt, 4)}
        # trajetoria completa (depth4) para readouts post-hoc
        for k in range(0, N, L * bs):
            xs = [val[k+j:k+j+L] for j in range(0, L*bs, L)]
            xs = [z for z in xs if len(z) == L]
            if len(xs) < 2: break
            x = torch.tensor(np.asarray(xs), dtype=torch.long, device=a.device)
            y = torch.tensor(np.asarray([val[k+j+1:k+j+1+L] for j in range(0, L*len(xs), L)]),
                             dtype=torch.long, device=a.device)
            _, tr = m(x, causal=True, max_loops=4, return_trace=True)
            traces.append((torch.stack(tr, 1).float().cpu(), y[:, -1].cpu()))
    sweep = []
    for eps in EPS:
        vl = corr = cnt = depth_sum = 0
        for lgseq, yy in traces:
            lp = torch.log_softmax(lgseq, -1)
            p = lp.exp()
            kl = torch.zeros(p.shape[0], p.shape[1])
            for t in range(1, p.shape[1]):
                # lgseq e' [B, loops, tokens, vocab]: soma sobre vocab e
                # media sobre posicoes -> [B] (um KL por amostra e por loop)
                kl[:, t] = (p[:, t] * (lp[:, t] - lp[:, t-1])).sum(-1).mean(1)
            exit_t = (kl < eps).float().argmax(1)
            exit_t = torch.where((kl < eps).any(1), exit_t, torch.ones_like(exit_t) * (p.shape[1]-1))
            chosen = lgseq[torch.arange(p.shape[0]), exit_t, -1, :]
            lpc = torch.log_softmax(chosen, -1)
            vl += float(-lpc.gather(1, yy[:, None]).sum())
            corr += int((lpc.argmax(-1) == yy).sum()); cnt += yy.numel(); depth_sum += int(exit_t.sum()) + 1
        sweep.append({"eps": eps, "avg_depth": round(depth_sum/cnt, 3),
                      "val_loss": round(vl/cnt,4), "acc": round(corr/cnt,4)})
    base = forced["depth4"]
    valid = [s for s in sweep if s["val_loss"] <= base["val_loss"]+0.01
             and s["acc"] >= base["acc"]-0.01 and s["avg_depth"] <= 3.2]
    chosen = max(valid, key=lambda s: s["avg_depth"]) if valid else None
    r = {"checkpoint": a.ckpt, "d": a.d, "tokens": cnt, "device": a.device,
         "forced": forced, "sweep": sweep, "chosen": chosen,
         "gate": "PASSA se chosen nao nulo (F123)", "seconds": round(time.perf_counter()-t0,1)}
    Path(a.out).write_text(json.dumps(r, indent=2)+"\n")
    print("RESULT " + json.dumps({"chosen": chosen, "gate": r["gate"]}))

if __name__ == "__main__":
    main()
