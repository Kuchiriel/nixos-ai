#!/usr/bin/env python3
"""PoC do mecanismo HybridAgent (arXiv 2610.18861) em Qwen3-0.6B.

Nao usa os checkpoints prontos (8B/14B). Implementa:
  - HybridLink: W linear que projeta o ultimo hidden state de volta para o
    espaco de embeddings, permitindo passos de pensamento latente;
  - LoRA manual (r=4) nas projecoes q/v (sem dependencia de peft);
  - dados: togethercomputer/HybridAgent-HybridSFT-v2, onde o texto dentro
    de <latent>...</latent> e' o pensamento interno a ser omitido.

Treino: CE only no texto VISIVEL apos K passos latentes.
Avaliacao: tokens de texto gerados vs baseline textual e presenca da resposta.
CPU, small-scale, nothing written to production.
"""
from __future__ import annotations
import argparse, json, os, re, time, urllib.parse, urllib.request
from pathlib import Path
import torch
from torch import nn
from transformers import AutoModelForCausalLM, AutoTokenizer

DATASET = "togethercomputer/HybridAgent-HybridSFT-v2"
MODEL = "/home/nixos/work/hybrid/models/qwen3-0.6b"
HF = "https://datasets-server.huggingface.co/rows"


def rows(n: int, cache: Path) -> list[dict]:
    if cache.is_file():
        return json.loads(cache.read_text())[:n]
    q = urllib.parse.urlencode({"dataset": DATASET, "config": "default",
                                "split": "train", "offset": 0, "length": n})
    with urllib.request.urlopen(HF + "?" + q, timeout=60) as r:
        data = json.loads(r.read())
    out = []
    for row in data.get("rows", []):
        r0 = row["row"]
        for rd in r0.get("rounds") or []:
            if not isinstance(rd, dict) or not isinstance(rd.get("assistant"), str):
                continue
            a = rd["assistant"]
            m = re.search(r"<latent>(.*?)</latent>", a, re.S)
            if not m or "<answer>" not in a:
                continue
            visible = (a[:m.start()] + a[m.end():]).replace("<think>", "").replace("</think>", "")
            answer = re.search(r"<answer>(.*?)</answer>", a, re.S)
            if not answer:
                continue
            out.append({"id": r0.get("id"), "question": r0.get("question", ""),
                        "latent": m.group(1).strip()[:400],
                        "visible": visible.strip()[:400],
                        "answer": answer.group(1).strip()[:80]})
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out[:200], ensure_ascii=False))
    return out[:n]


class LoRALinear(nn.Module):
    def __init__(self, base: nn.Linear, r: int = 4, alpha: float = 8.0):
        super().__init__()
        self.base = base
        self.base.weight.requires_grad_(False)
        if self.base.bias is not None:
            self.base.bias.requires_grad_(False)
        self.A = nn.Parameter((torch.randn(r, base.in_features) * 0.01).to(base.weight.device, base.weight.dtype))
        self.B = nn.Parameter(torch.zeros(base.out_features, r, device=base.weight.device, dtype=base.weight.dtype))
        self.scale = alpha / r

    def forward(self, x):
        return self.base(x) + (x @ self.A.T) @ self.B.T * self.scale


def install_lora(model, r=4):
    layers = model.model.layers
    for layer in layers:
        for name in ("q_proj", "v_proj"):
            setattr(layer.self_attn, name,
                    LoRALinear(layer.self_attn.__getattr__(name), r=r))
    return model


def lora_params(model):
    return [p for n, p in model.named_parameters()
            if p.requires_grad and (".A" in n or ".B" in n)]


def train(model, tok, link, data, steps: int, k: int, lr: float,
          hybrid_sft: bool = False):
    """HybridSFT: CE no texto visivel + CE de leitura nos spans latentes."""
    model.train(); link.train()
    opt = torch.optim.AdamW(lora_params(model) + list(link.parameters()), lr=lr)
    E = model.get_input_embeddings().weight
    losses, aux_losses = [], []
    for i in range(steps):
        row = data[i % len(data)]
        prompt = "Q: " + row["question"] + "\nThink:\n"
        target = row["visible"] + "\nAnswer: " + row["answer"]
        ids = tok(prompt, return_tensors="pt", truncation=True, max_length=48).input_ids.to(model.device)
        tgt = tok(target, return_tensors="pt", truncation=True, max_length=40).input_ids.to(model.device)
        emb = model.get_input_embeddings()(ids)
        out = model(inputs_embeds=emb, use_cache=False)
        h = out.hidden_states[-1][:, -1, :]

        # k passos latentes, cada um com seu alvo de leitura (HybridSFT)
        lat_targets = []
        if hybrid_sft:
            lids = tok(row["latent"], return_tensors="pt", truncation=True,
                       max_length=32).input_ids[0].tolist()
            if not lids:
                lids = [tok.eos_token_id]
            step = max(1, len(lids) // k)
            lat_targets = [lids[min(j * step, len(lids) - 1)] for j in range(k)]

        seq = emb
        lat_logits = []
        for j in range(k):
            e = link(h)
            seq = torch.cat([seq, e.unsqueeze(1)], dim=1)
            out = model(inputs_embeds=seq, use_cache=False)
            h = out.hidden_states[-1][:, -1, :]
            if hybrid_sft:
                lat_logits.append(e @ E.T)

        full = torch.cat([seq, model.get_input_embeddings()(tgt[:, :-1])], dim=1)
        out3 = model(inputs_embeds=full, use_cache=False)
        logits = out3.logits[:, seq.shape[1] - 1:, :]
        loss = nn.functional.cross_entropy(logits.reshape(-1, logits.size(-1)),
                                           tgt.reshape(-1))
        aux = torch.zeros((), device=model.device)
        if hybrid_sft and lat_logits:
            targets = torch.tensor(lat_targets, device=model.device)
            aux = sum(nn.functional.cross_entropy(lg, targets[j:j + 1])
                      for j, lg in enumerate(lat_logits)) / len(lat_logits)
            loss = loss + 0.5 * aux
        opt.zero_grad(); loss.backward(); opt.step()
        if loss.is_cuda and (i + 1) % 25 == 0:
            torch.cuda.empty_cache()
        losses.append(round(float(loss.detach()), 4))
        aux_losses.append(round(float(aux.detach()), 4))
        if (i + 1) % 25 == 0:
            print(json.dumps({"step": i + 1, "loss": losses[-1],
                              "aux": aux_losses[-1]}), flush=True)
    return losses, aux_losses


@torch.no_grad()
def generate(model, tok, link, question: str, k: int, max_new: int = 64) -> tuple[str, int, float]:
    """Modo latente: k passos continuous + geracao de texto visivel."""
    model.eval(); link.eval()
    ids = tok("Q: " + question + "\nThink:\n", return_tensors="pt").input_ids.to(model.device)
    t0 = time.perf_counter()
    emb = model.get_input_embeddings()(ids)
    out = model(inputs_embeds=emb, use_cache=False)
    seq = emb
    for _ in range(k):
        h = out.hidden_states[-1][:, -1, :]
        e = link(h)
        seq = torch.cat([seq, e.unsqueeze(1)], dim=1)
        out = model(inputs_embeds=seq, use_cache=False)
    gen_ids = []
    for _ in range(max_new):
        nxt = out.logits[:, -1, :].argmax(dim=-1)
        if int(nxt.item()) == tok.eos_token_id:
            break
        gen_ids.append(int(nxt.item()))
        seq = torch.cat([seq, model.get_input_embeddings()(nxt.view(1, 1))], dim=1)
        out = model(inputs_embeds=seq, use_cache=False)
    elapsed = time.perf_counter() - t0
    return tok.decode(gen_ids, skip_special_tokens=True), len(gen_ids), elapsed


@torch.no_grad()
def generate_text(model, tok, question: str, max_new: int = 64) -> tuple[str, int, float]:
    """Baseline: modo texto puro (sem HybridLink)."""
    model.eval()
    ids = tok("Q: " + question + "\nThink step by step:\n", return_tensors="pt").input_ids.to(model.device)
    t0 = time.perf_counter()
    out = model(input_ids=ids, use_cache=False)
    gen_ids = []
    for _ in range(max_new):
        nxt = out.logits[:, -1, :].argmax(dim=-1)
        if int(nxt.item()) == tok.eos_token_id:
            break
        gen_ids.append(int(nxt.item()))
        ids = torch.cat([ids, nxt.view(1, 1)], dim=1)
        out = model(input_ids=ids, use_cache=False)
    elapsed = time.perf_counter() - t0
    return tok.decode(gen_ids, skip_special_tokens=True), len(gen_ids), elapsed


def answer_hit(gold: str, generated: str) -> bool:
    g = re.sub(r"[^a-z0-9]+", "", gold.lower())
    t = re.sub(r"[^a-z0-9]+", "", generated.lower())
    return bool(g) and g[:8] in t


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows", type=int, default=40)
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--latent-steps", type=int, default=2)
    ap.add_argument("--eval", type=int, default=5)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--max-new", type=int, default=64)
    ap.add_argument("--hybrid-sft", action="store_true",
                    help="CE auxiliar de leitura nos spans <latent>")
    ap.add_argument("--out", type=Path, default=Path("/home/nixos/work/hybrid/poc"))
    a = ap.parse_args()
    torch.set_num_threads(min(12, os.cpu_count() or 4))
    t0 = time.time()
    data = rows(a.rows, a.out / "rows.json")
    print(json.dumps({"rows_loaded": len(data), "seconds": round(time.time()-t0, 1)}), flush=True)
    tok = AutoTokenizer.from_pretrained(MODEL)
    dev = a.device if a.device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu")
    dtype = torch.bfloat16 if dev == "cuda" else torch.float32
    model = AutoModelForCausalLM.from_pretrained(MODEL, dtype=dtype, output_hidden_states=True).to(dev)
    model.config.use_cache = False
    model.gradient_checkpointing_enable()
    install_lora(model)
    hidden = model.get_input_embeddings().embedding_dim
    link = nn.Linear(hidden, hidden, bias=False, dtype=model.dtype).to(dev)
    losses, aux = train(model, tok, link, data, a.steps, a.latent_steps,
                        lr=2e-4, hybrid_sft=a.hybrid_sft)
    ev = []
    for row in data[a.eval * -1:]:
        gen, n, el = generate(model, tok, link, row["question"], a.latent_steps, a.max_new)
        txt, nt, et = generate_text(model, tok, row["question"], a.max_new)
        baseline_words = len(re.findall(r"\S+", row["latent"] + " " + row["visible"]))
        ev.append({"answer": row["answer"], "latent_tokens": n,
                   "latent_seconds": round(el, 3), "latent_tok_s": round(n / el, 2) if el else 0,
                   "text_tokens": nt, "text_seconds": round(et, 3),
                   "text_tok_s": round(nt / et, 2) if et else 0,
                   "baseline_thought_words": baseline_words,
                   "hit": answer_hit(row["answer"], gen),
                   "text_hit": answer_hit(row["answer"], txt),
                   "sample": gen[:160]})
    mean_lat = sum(x["latent_tokens"] for x in ev) / len(ev)
    mean_txt = sum(x["text_tokens"] for x in ev) / len(ev)
    mean_tok_s_l = sum(x["latent_tok_s"] for x in ev) / len(ev)
    mean_tok_s_t = sum(x["text_tok_s"] for x in ev) / len(ev)
    report = {"paper": "arXiv 2610.18861", "model": MODEL,
              "train_rows": min(a.rows, len(data)), "steps": a.steps,
              "latent_steps": a.latent_steps, "device": str(dev),
              "hybrid_sft": bool(a.hybrid_sft),
              "train_loss_first_last": [losses[0], losses[-1]],
              "aux_loss_first_last": [aux[0], aux[-1]] if aux else None,
              "eval": ev,
              "mean_latent_tokens": round(mean_lat, 2),
              "mean_text_tokens": round(mean_txt, 2),
              "mean_latent_tok_s": round(mean_tok_s_l, 2),
              "mean_text_tok_s": round(mean_tok_s_t, 2),
              "baseline_mean_words": round(sum(x["baseline_thought_words"] for x in ev) / len(ev), 2),
              "answer_hit_rate": round(sum(x["hit"] for x in ev) / len(ev), 3),
              "text_hit_rate": round(sum(x["text_hit"] for x in ev) / len(ev), 3),
              "elapsed_seconds": round(time.time() - t0, 1)}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    torch.save({"link": link.state_dict(),
                "lora": {n: p for n, p in model.named_parameters() if ".A" in n or ".B" in n}},
               a.out / "adapters.pt")
    print("RESULT " + json.dumps(report, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
