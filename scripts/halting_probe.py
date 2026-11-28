#!/usr/bin/env python3
"""F124: probe de halting por token — SEM treino.

--check : valida o par (checkpoint, corpus) e so depois libera o gate;
          carrega o checkpoint, mede a loss no corpus de TREINO e exige
          |loss - val_loss publicado| <= tolerancia. Nao mede nada se falhar.
--run   : curva forcada depth1-4 + sweep KL epsilon + regra de F123 (F125)

Correcoes medidas em 28/11 (F133):
  * o corpus vem do JSON de treino do checkpoint (nao de um default fixo):
    ids com OUTRO remap de vocab dao loss ~9-13 (chute) e invalidam o gate;
  * o target y[:,-1] esta CORRETO (x=val[k:k+L], y=val[k+1:k+1+L], os
    logits da ultima posicao preveem val[k+L] = y[:,-1]);
  * o batching do probe esta correto: module halting e ab dao o mesmo valor;
  * o indice do KL no sweep: o primeiro passo nao tem KL contra um passo
    anterior. Deixar kl[:,0] = 0 fazia `(kl < eps).any(1)` ser True desde o
    indice 0, e `argmax` devolvia 0 para TODO eps — sweep identico e gate
    incapaz de escolher profundidade menor. Agora kl[:,0] = inf.
"""
import argparse, json, math, time
from pathlib import Path

B = Path("/home/nixos/work/hybrid")
EPS = [1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1e-1]


def _training_json_candidates(ckpt_path: str):
    """JSONs de treino candidatos para um checkpoint.

    O JSON costuma ficar no diretorio de TRABALHO (work/hybrid), enquanto o
    checkpoint fica em work/hybrid/checkpoints/ — por isso os dois diretorios
    sao procurados.
    """
    ckpt = Path(ckpt_path)
    stem = ckpt.stem
    base = stem.rsplit("-s", 1)[0]
    seen = set()
    for directory in (ckpt.parent, ckpt.parent.parent, B):
        for name in (stem + ".json", base + "*.json"):
            for candidate in sorted(directory.glob(name)):
                key = str(candidate)
                if key not in seen:
                    seen.add(key)
                    yield candidate


def corpus_for_checkpoint(ckpt_path: str, explicit: str = "") -> str:
    """Deriva o corpus de treino do checkpoint a partir do JSON publicado."""
    if explicit:
        return explicit
    for candidate in _training_json_candidates(ckpt_path):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        corpus = data.get("corpus")
        if corpus and Path(corpus).is_file():
            return corpus
    return ""


def published_val_loss(ckpt_path: str) -> float:
    for candidate in _training_json_candidates(ckpt_path):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            value = float(data["val_loss"])
        except Exception:
            continue
        if value == value:  # nao-NaN
            return value
    return float("nan")


def remap_fingerprint(corpus_path: str) -> str:
    """SHA curto do remap do sidecar stats (identifica a materializacao)."""
    import hashlib
    stats = Path(corpus_path).with_name(Path(corpus_path).name.replace(".npy", "-stats.json"))
    if not stats.exists():
        return ""
    try:
        data = json.loads(stats.read_text(encoding="utf-8"))
        remap = data.get("remap")
        canon = json.dumps(remap, sort_keys=True)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return ""


def choose_exit_step(kl, eps):
    """Primeiro passo t>=1 com KL < eps; fallback no ultimo passo.

    `kl` tem shape [B, loops] e kl[:,0] deve ser +inf (o primeiro passo nao
    tem KL contra um passo anterior). Devolve (exit_t, escolhidos_bool).
    """
    import torch
    loops = kl.shape[1]
    below = kl < eps
    any_below = below.any(dim=1)
    exit_t = below.float().argmax(dim=1)
    exit_t = torch.where(any_below, exit_t, torch.full_like(exit_t, loops - 1))
    return exit_t, any_below


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("check", "run"))
    ap.add_argument("--d", type=int, default=1216)
    ap.add_argument("--ckpt", default=str(B / "checkpoints/f75-simplefull-s42.pt"))
    ap.add_argument("--npy", default="", help="override do corpus (deve ser o de treino)")
    ap.add_argument("--tokens", type=int, default=200000)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--out", default=str(B / "halting-probe.json"))
    ap.add_argument("--tol", type=float, default=0.10,
                    help="tolerancia |loss medida - val_loss publicado| no --check")
    ap.add_argument("--check-tokens", type=int, default=2048)
    a = ap.parse_args()

    corpus = corpus_for_checkpoint(a.ckpt, a.npy)
    expected = published_val_loss(a.ckpt)
    if not corpus:
        print(json.dumps({"event": "check", "ok": False,
                          "error": "corpus de treino nao encontrado para o checkpoint",
                          "ckpt": a.ckpt}))
        raise SystemExit(3)

    if a.mode == "check":
        import torch, numpy as np, torch.nn.functional as F, runpy
        cls = runpy.run_path(str(B / "scale-loop-halting.py"))["ScaleLM"]
        model = cls(10000, a.d, "ngpt_only")
        ck = torch.load(a.ckpt, map_location="cpu", weights_only=False)
        model.load_state_dict(ck["state"], strict=True)
        model.eval()
        arr = np.load(corpus, mmap_mode="r")
        n = int(len(arr) * 0.99)
        val = arr[n:]
        L = 256
        loss_sum = 0.0
        tok = 0
        with torch.no_grad():
            for k in range(0, min(a.check_tokens, len(val) - L - 1), L):
                x = torch.tensor(np.asarray(val[k:k + L]), dtype=torch.long).unsqueeze(0)
                y = torch.tensor(np.asarray(val[k + 1:k + 1 + L]), dtype=torch.long).unsqueeze(0)
                out = model(x, causal=True)
                loss_sum += float(F.cross_entropy(out.reshape(-1, out.shape[-1]).float(), y.reshape(-1))) * y.numel()
                tok += y.numel()
        measured = loss_sum / max(tok, 1)
        delta = abs(measured - expected) if expected == expected else float("inf")
        ok = bool(tok > 0 and expected == expected and delta <= a.tol)
        report = {
            "event": "check", "ok": ok, "ckpt": a.ckpt, "corpus": corpus,
            "remap_sha": remap_fingerprint(corpus),
            "published_val_loss": expected if expected == expected else None,
            "measured_val_loss": round(measured, 4),
            "delta": round(delta, 4) if delta != float("inf") else None,
            "tol": a.tol, "tokens": tok,
            "no_train": True,
        }
        print(json.dumps(report))
        if not ok:
            print("auto-wake: probe --check REPROVADO (checkpoint/corpus nao casam); gate nao autorizado",
                  file=__import__("sys").stderr)
            raise SystemExit(4)
        return

    import torch, numpy as np, runpy
    cls = runpy.run_path(str(B / "scale-loop-halting.py"))["ScaleLM"]
    m = cls(10000, a.d, "ngpt_only").to(a.device)
    ck = torch.load(a.ckpt, map_location=a.device, weights_only=False)
    m.load_state_dict(ck["state"], strict=True); m.eval()
    arr = np.load(corpus, mmap_mode="r")
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
            kl = torch.full((p.shape[0], p.shape[1]), float("inf"))
            for t in range(1, p.shape[1]):
                # lgseq e' [B, loops, tokens, vocab]: soma sobre vocab e
                # media sobre posicoes -> [B] (um KL por amostra e por loop)
                kl[:, t] = (p[:, t] * (lp[:, t] - lp[:, t-1])).sum(-1).mean(1)
            exit_t, _ = choose_exit_step(kl, eps)
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
    r = {"checkpoint": a.ckpt, "corpus": corpus, "remap_sha": remap_fingerprint(corpus),
         "d": a.d, "tokens": cnt, "device": a.device,
         "forced": forced, "sweep": sweep, "chosen": chosen,
         "gate": "PASSA se chosen nao nulo (F123)", "seconds": round(time.perf_counter()-t0,1)}
    Path(a.out).write_text(json.dumps(r, indent=2)+"\n")
    print("RESULT " + json.dumps({"chosen": chosen, "gate": r["gate"]}))

if __name__ == "__main__":
    main()
