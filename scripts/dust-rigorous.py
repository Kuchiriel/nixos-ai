#!/usr/bin/env python3
"""F5: DUST rigoroso (Q Labs 2026) sobre o MESMO ScaleLM do F2.

Secoes implementadas:
  2.1/2.2 — jitter de ativacoes por token; c_s = media(l_i) - l_i;
            r_t = sum_{s>=t} gamma^(s-t) c_s;
            ghat_t = -(1/(K sigma)) sum_i r_t^i a_t^i;
            G_W = sum_t ghat_t x_t^T.
  2.3     — grupos de camadas em forwards separados, cache do forward limpo,
            replay so a partir do bloco alvo, head jitterado nos logits,
            e eq. 4 (c_s = -<ghat_s, Delta o_s>) para q/k/v.
  3.3     — AdamW sobre os gradientes estimados.

Contagem: cada jitter de bloco e' 1 forward parcial; head e' CE-only.
Modo --match tokens (default): mesmos tokens vistos; DUST faz mais forwards.
Modo --match forwards: backprop usa accumulacao para igualar os forwards.
"""
from __future__ import annotations
import argparse, json, math, random, time
from pathlib import Path
import torch
import torch.nn.functional as F

SRC = Path("/home/nixos/projects/nixos-ai/scripts/scale-loop-ab.py")
DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")


def load_scale():
    import runpy
    return runpy.run_path(str(SRC))


def seed(s):
    random.seed(s); torch.manual_seed(s)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(s)


# ---- forward do ScaleLM com replay a partir de um bloco e jitter opcional ----

def attn_forward_dust(self, x, mask=None):
    """Copia de Attn.forward com jitters injetados (eq 2.2/2.3)."""
    b, t, d = x.shape
    jq = getattr(self, "_jq", None)
    jk = getattr(self, "_jk", None)
    jv = getattr(self, "_jv", None)
    jo = getattr(self, "_jo", None)
    q = x @ self.q
    k = x @ self.k
    v = x @ self.v
    if jq is not None: q = q + jq
    if jk is not None: k = k + jk
    if jv is not None: v = v + jv
    q = q.view(b, t, self.h, self.dh).transpose(1, 2)
    k = k.view(b, t, self.h, self.dh).transpose(1, 2)
    v = v.view(b, t, self.h, self.dh).transpose(1, 2)
    scale = math.sqrt(self.dh * self.h)
    att = torch.softmax(q @ k.transpose(-2, -1) / scale, -1)
    ao = (att @ v).transpose(1, 2).contiguous().view(b, t, d)  # attention output
    out = ao @ self.o
    if jo is not None: out = out + jo
    if self.scale_in:
        return F.normalize(x + self.alpha * out, dim=-1), ao
    return x + out, ao


def block_forward_dust(blk, x, jq=None, jk=None, jv=None, jo=None, jff=None):
    """Bloco com jitter; retorna (h, attention_output)."""
    ln_out = blk.ln(x)
    att = blk.att
    att._jq, att._jk, att._jv, att._jo = jq, jk, jv, jo
    h, ao = attn_forward_dust(att, ln_out)
    att._jq = att._jk = att._jv = att._jo = None
    f = blk.ff(ln_out)
    if jff is not None: f = f + jff
    if blk.scale_in:
        return F.normalize(h + blk.beta * f, dim=-1), ao
    return h + f, ao


def forward_replay(model, x, start=0, cache=None, target_block=-1, **jit):
    """Replica ScaleLM.forward, mas comeca no bloco `start` e aplica jitter."""
    t = x.shape[1]
    if start == 0:
        h = model.tok(x) + model.pos(torch.arange(t, device=x.device))
    else:
        h = cache[start]
    last_ao = None
    for i in range(start, len(model.blocks)):
        blk = model.blocks[i]
        kw = {k: v for k, v in jit.items() if i == target_block}
        if i == 2 and model.variant != "plain":
            u = h.detach().clone()
            for _ in range(3):
                h = F.normalize(h + u, dim=-1)
                h, last_ao = block_forward_dust(blk, h, **kw)
        else:
            h, last_ao = block_forward_dust(blk, h, **kw)
    logits = model.head(model.ln(h))
    return logits, last_ao


def capture_cache(model, x):
    """Forward limpo capturando estados de entrada dos blocos e logits."""
    cache = {}
    handles = []
    def hook_blk(i):
        def h(mod, inp, out):
            cache[i] = inp[0].detach()
        return h
    for i, blk in enumerate(model.blocks):
        handles.append(blk.register_forward_hook(hook_blk(i)))
    logits = model(x)
    for hnd in handles: hnd.remove()
    return cache, logits.detach()


def token_loss(logits, y):
    return F.cross_entropy(logits.float().reshape(-1, logits.size(-1)),
                           y.reshape(-1), reduction="none").view(y.shape)


def reward(c, gamma):
    """r_t = sum_{s>=t} gamma^(s-t) c_s (eq 1), vetorizado por reverso."""
    out = torch.zeros_like(c)
    run = torch.zeros_like(c[:, 0])
    for s in range(c.shape[1] - 1, -1, -1):
        run = gamma * run + c[:, s]
        out[:, s] = run
    return out


def grad_est(a, r, sigma, K):
    """ghat_t = -(1/(K sigma)) sum_i r_t^i a_t^i (eq 2)."""
    return -(r.unsqueeze(-1) * a).mean(dim=0) / sigma   # media ja divide K


@torch.no_grad()
def dust_step(model, opt, x, y, K=8, sigma=0.05, gamma=0.5, groups=None, K_block=None):
    # DUST estima o gradiente por populacao -- NAO usa autograd. Sem o
    # no_grad, ~40 forwards por passo retem grafos e estouram a VRAM.
    groups = groups or ("att_o", "ff_down", "head", "qkv")
    Kb = K_block or K   # blocos podem ter populacao menor que o head
    cache, clean_logits = capture_cache(model, x)
    base_loss = token_loss(clean_logits, y)
    fw = 1  # forward limpo
    ce_draws = 0
    grads = {}   # id(p) -> grad acumulado
    B, T = x.shape
    d = model.d

    def acc(p, g):
        grads[p] = grads.get(p, 0) + g

    # --- grupo att_o: erro no output da atencao (antes de o) ---
    if "att_o" in groups:
        for lvl in range(len(model.blocks)):
            ln_inputs = []
            hnd = model.blocks[lvl].ln.register_forward_hook(
                lambda m, i, o, S=ln_inputs: S.append(o.detach()))
            model(x)  # forward para capturar ln_out
            hnd.remove()
            X = ln_inputs[0]
            noises, losses = [], []
            for _ in range(Kb):
                a = torch.randn(B, T, d, device=x.device)
                logits, _ = forward_replay(model, x, start=lvl, cache=cache,
                                           target_block=lvl, jo=sigma * a)
                fw += 1
                noises.append(a)
                losses.append(token_loss(logits, y))
            stack = torch.stack(losses)
            c = stack.mean(0) - stack            # eq 2.2: media - perturbado
            ghat = grad_est(torch.stack(noises), reward(c, gamma), sigma, Kb)
            # G_o = sum_t ghat_t X_t^T ; X aqui e' a saida da atencao (antes de o)
            # aproximacao: X = ln_out (input de q/k/v/o) para o grad deo
            acc(model.blocks[lvl].att.o, torch.einsum("bpa,bps->as", ghat, X))
            if "qkv" in groups:
                # guardar erro estimado da atencao para eq 4
                pass

    # --- grupo ff_down (Linear 2 do MLP) ---
    if "ff_down" in groups:
        for lvl in range(len(model.blocks)):
            fin = []
            hnd = model.blocks[lvl].ff[1].register_forward_hook(
                lambda m, i, o, S=fin: S.append(o.detach()))
            _ = forward_replay(model, x, start=lvl, cache=cache)
            hnd.remove()
            X = fin[0]
            noises, losses = [], []
            for _ in range(Kb):
                a = torch.randn(B, T, d, device=x.device)
                logits, _ = forward_replay(model, x, start=lvl, cache=cache,
                                           target_block=lvl, jff=sigma * a)
                fw += 1
                noises.append(a); losses.append(token_loss(logits, y))
            stack = torch.stack(losses)
            c = stack.mean(0) - stack
            ghat = grad_est(torch.stack(noises), reward(c, gamma), sigma, Kb)
            lin = model.blocks[lvl].ff[2]
            acc(lin.weight, torch.einsum("bpa,bps->as", ghat, X))
            acc(lin.bias, ghat.sum((0, 1)))

    # --- grupo head: jitter direto nos logits (sec 2.3), CE-only ---
    if "head" in groups:
        noises, losses = [], []
        for _ in range(K * 4):  # population maior, custo baixo
            a = torch.randn(B, T, clean_logits.size(-1), device=x.device)
            noises.append(a)
            losses.append(token_loss(clean_logits + sigma * a, y))
        stack = torch.stack(losses)
        c = stack.mean(0) - stack
        ghat = grad_est(torch.stack(noises), reward(c, gamma), sigma, K * 4)
        ce_draws += K * 4
        H = model.ln(cache[len(model.blocks)]) if len(model.blocks) in cache else None
        if H is None:
            # ultima entrada de bloco nao e' entrada do head; recomputar
            H = []
            hnd = model.ln.register_forward_hook(lambda m, i, o, S=H: S.append(o.detach()))
            model(x); hnd.remove(); H = H[0]
        acc(model.head.weight, torch.einsum("bpa,bps->as", ghat, H))
        acc(model.head.bias, ghat.sum((0, 1)))
        fw += 0  # CE-only

    # --- q/k/v via eq 4: c_s = -<ghat_s, Delta o_s> ---
    if "qkv" in groups:
        for lvl in range(len(model.blocks)):
            X = []
            hnd = model.blocks[lvl].ln.register_forward_hook(
                lambda m, i, o, S=X: S.append(o.detach()))
            _ = forward_replay(model, x, start=lvl, cache=cache)
            hnd.remove()
            X = X[0]
            # erro estimado no output da atencao via jitter de att_o
            ao_noises, ao_losses, deltas = [], [], []
            for _ in range(Kb):
                a = torch.randn(B, T, d, device=x.device)
                lg, _ = forward_replay(model, x, start=lvl, cache=cache,
                                       target_block=lvl, jo=sigma * a)
                fw += 1
                ao_noises.append(a); ao_losses.append(token_loss(lg, y))
            st = torch.stack(ao_losses)
            ghat_o = grad_est(torch.stack(ao_noises), reward(st.mean(0) - st, gamma), sigma, Kb)
            for name in ("q", "k", "v"):
                noises, deltas = [], []
                for _ in range(Kb):
                    a = torch.randn(B, T, d, device=x.device)
                    _, ao = forward_replay(model, x, start=lvl, cache=cache,
                                           target_block=lvl,
                                           **{"j" + name: sigma * a})
                    fw += 1
                    noises.append(a); deltas.append(ao)
                # Delta o causado pelo jitter; c_s = -<ghat_o_s, Delta o_s>
                ds = torch.stack(deltas)
                c = -(ghat_o.unsqueeze(0) * ds).sum(-1)
                ghat = grad_est(torch.stack(noises), reward(c, gamma), sigma, Kb)
                acc(getattr(model.blocks[lvl].att, name),
                    torch.einsum("bpa,bps->as", ghat, X))

    opt.zero_grad()
    names = {id(p): n for n, p in model.named_parameters()}
    for p, g in grads.items():
        if tuple(g.shape) != tuple(p.shape):
            raise RuntimeError("DUST shape mismatch: param %s %s vs grad %s" %
                               (names.get(id(p), "?"), tuple(p.shape), tuple(g.shape)))
        p.grad = g
    opt.step()
    return float(base_loss.mean()), fw, ce_draws


def evaluate(model, vids, chars, device):
    model.eval(); tot = 0.0; cnt = 0
    with torch.no_grad():
        for k in range(0, len(vids) - 128, 128 * 24):
            ch = vids[k:k + 128 * 24]
            if len(ch) < 129: break
            xs = [ch[i:i + 128] for i in range(0, len(ch) - 128, 128)]
            if not xs: break
            x = torch.tensor(xs, device=device)
            y = torch.tensor([ch[i + 1:i + 1 + 128] for i in range(0, len(ch) - 128, 128)], device=device)
            tot += float(F.cross_entropy(model(x).reshape(-1, len(chars)), y.reshape(-1), reduction="sum"))
            cnt += y.numel()
    return tot / max(cnt, 1)


def run(scale, mode, match, steps, K, device, seed_v, groups=None, K_block=None):
    smod = load_scale()
    ScaleLM = smod["ScaleLM"]
    seed(seed_v)
    text = DATA.read_text(encoding="utf-8")
    n = int(len(text) * 0.9)
    chars = sorted(set(text)); stoi = {c: i for i, c in enumerate(chars)}
    ids = [stoi[c] for c in text[:n]]; vids = [stoi[c] for c in text[n:]]
    d = {10: 320, 50: 704, 150: 1216, 300: 1768}[scale]
    model = ScaleLM(len(chars), d, "ngpt_only").to(device)
    params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4, fused=True)
    # contagem explicita: DUST faz 1 limpo + K por bloco por grupo.
    # No modo 'forwards', backprop usa `accum` microbatches com `mb` sequencias
    # cada, mantendo ~as mesmas tokens por passo (8 x 128).
    accum = 1
    if match == "forwards":
        accum = min(8, 1 + K * 2)   # grupos att_o + ff_down (qkv e' extra)
    mb = max(1, 8 // accum) if match == "forwards" else 8
    steps_bp = steps
    t0 = time.perf_counter(); fw_total = 0; ce_total = 0; seen = 0
    model.train()
    for step in range(1, steps + 1):
        st = torch.randint(0, len(ids) - 128 - 1, (8,))
        if mode == "backprop" and match == "forwards":
            st = st[:mb]
        x = torch.tensor([ids[k:k + 128] for k in st.tolist()], device=device)
        y = torch.tensor([ids[k + 1:k + 1 + 128] for k in st.tolist()], device=device)
        if mode == "dust":
            lv, fw, ce = dust_step(model, opt, x, y, K=K, groups=groups, K_block=K_block)
            fw_total += fw; ce_total += ce; seen += x.numel()
        else:
            lv = 0.0
            for _ in range(accum):
                with torch.autocast(device_type=device, dtype=torch.bfloat16):
                    loss = F.cross_entropy(model(x).reshape(-1, len(chars)).float(), y.reshape(-1))
                (loss / accum).backward()
                lv += float(loss.detach()) / accum
                seen += x.numel(); fw_total += 1
            opt.step(); opt.zero_grad()
        if step % max(10, steps // 5) == 0:
            print(json.dumps({"scale": scale, "mode": mode, "step": step,
                              "loss": round(lv, 4), "fw": fw_total,
                              "tok": seen}), flush=True)
    train_s = time.perf_counter() - t0
    val = evaluate(model, vids, chars, device)
    r = {"scale_m": scale, "mode": mode, "match": match, "K": K, "K_block": K_block, "groups": list(groups) if groups else ["att_o","ff_down","head","qkv"],
         "params": params, "steps": steps, "steps_backprop": steps_bp,
         "val_loss": round(val, 4), "forwards": fw_total, "ce_draws": ce_total,
         "tokens": seen, "train_seconds": round(train_s, 1),
         "train_tok_s": round(seen / train_s, 1)}
    print("RESULT " + json.dumps(r), flush=True)
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["dust", "backprop"], required=True)
    ap.add_argument("--scale", type=int, default=10)
    ap.add_argument("--match", choices=["tokens", "forwards"], default="tokens")
    ap.add_argument("--steps", type=int, default=2400)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--blockK", type=int, default=0,
                    help="populacao dos blocos (head usa --K)")
    ap.add_argument("--groups", default="",
                    help="ex.: head (populacao grande so no head, CE-only)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    dev = a.device if torch.cuda.is_available() else "cpu"
    grp = tuple(g.strip() for g in a.groups.split(",") if g.strip()) or None
    r = run(a.scale, a.mode, a.match, a.steps, a.K, dev, a.seed, grp, a.blockK or None)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(r, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
