#!/usr/bin/env python3
"""Mede tokens efetivos ate <answer> (parada antecipada) no modelo treinado.

Carrega link+LoRA salvos e gera ate 256 tokens sem teto artificial; depois
conta quantos tokens foram necessarios ate a primeira ocorrencia de
`<answer>` ou `Answer:` no texto. Compara modo latente (k passos de
HybridLink) vs modo texto puro, no mesmo heldout e mesmo modelo.
"""
from __future__ import annotations
import argparse, json, re, time
from pathlib import Path
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "/home/nixos/work/hybrid/models/qwen3-0.6b"
MARKERS = ("<answer>", "Answer:")


def load(model, tok, adapters: Path, dev):
    ck = torch.load(adapters, map_location="cpu", weights_only=False)
    link = model.get_input_embeddings()  # placeholder, substituido abaixo
    hidden = model.get_input_embeddings().embedding_dim
    from torch import nn
    link = nn.Linear(hidden, hidden, bias=False, dtype=model.dtype).to(dev)
    link.load_state_dict(ck["link"])
    lora = ck["lora"]
    params = dict(model.named_parameters())
    loaded = 0
    for name, tensor in lora.items():
        # checkpoint salvo pelo wrapper LoRALinear: nome sem o `.base`
        key = name if name in params else ("model." + name if "model." + name in params else None)
        if key is None:
            alt = name.replace("model.", "", 1)
            key = alt if alt in params else None
        if key:
            with torch.no_grad():
                params[key].copy_(tensor.to(params[key].device, params[key].dtype))
            loaded += 1
    return link, loaded


def generate(model, tok, question, link=None, k=0, max_new=256):
    ids = tok("Q: " + question + ("\nThink:\n" if link is not None else "\nThink step by step:\n"),
              return_tensors="pt").input_ids.to(model.device)
    t0 = time.perf_counter()
    out = model(input_ids=ids, use_cache=False)
    seq = model.get_input_embeddings()(ids)
    if link is not None:
        for _ in range(k):
            h = out.hidden_states[-1][:, -1, :]
            e = link(h)
            if e.dim() == 3:
                e = e[:, -1, :]
            seq = torch.cat([seq, e.unsqueeze(1)], dim=1)
            out = model(inputs_embeds=seq, use_cache=False)
    gen = []
    for _ in range(max_new):
        nxt = out.logits[:, -1, :].argmax(dim=-1)
        gen.append(int(nxt.item()))
        seq = torch.cat([seq, model.get_input_embeddings()(nxt.view(1, 1))], dim=1)
        out = model(inputs_embeds=seq, use_cache=False)
    elapsed = time.perf_counter() - t0
    text = tok.decode(gen, skip_special_tokens=True)
    return text, gen, elapsed


def effective_tokens(text: str, gen: list[int], tok) -> int:
    lo = min([text.find(m) for m in MARKERS if m in text] or [len(text)])
    if lo == len(text):
        return len(gen)
    return max(1, len(tok.encode(text[:lo])))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adapters", type=Path, default=Path("/home/nixos/work/hybrid/poc-answerable/adapters.pt"))
    ap.add_argument("--rows", type=Path, default=Path("/home/nixos/work/hybrid/poc-answerable/rows.json"))
    ap.add_argument("--eval", type=int, default=6)
    ap.add_argument("--latent-steps", type=int, default=2)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--out", type=Path, default=Path("/home/nixos/work/hybrid/poc-earlystop/report.json"))
    a = ap.parse_args()
    torch.set_num_threads(8)
    dev = a.device if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if dev == "cuda" else torch.float32
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForCausalLM.from_pretrained(MODEL, dtype=dtype, output_hidden_states=True).to(dev)
    model.config.use_cache = False
    # reinstala os wrappers LoRALinear (os tensores A/B nao existem no base)
    import importlib.util, sys
    src = Path(__file__).with_name("hybrid-link-poc.py")
    spec = importlib.util.spec_from_file_location("hlp", src)
    hlp = importlib.util.module_from_spec(spec); spec.loader.exec_module(hlp)
    hlp.install_lora(model)
    link, n = load(model, tok, a.adapters, dev)
    if n == 0:
        raise SystemExit("nenhum tensor LoRA carregado — abortando medicao invalida")
    data = json.loads(a.rows.read_text())[-a.eval:]
    rows = []
    for r in data:
        row = {"q": r["question"][:50], "answer": r["answer"][:40]}
        for mode in ("latent", "text"):
            text, gen, el = generate(model, tok, r["question"],
                                     link if mode == "latent" else None,
                                     a.latent_steps if mode == "latent" else 0)
            eff = effective_tokens(text, gen, tok)
            row[mode] = {"generated": len(gen), "effective": eff,
                         "seconds": round(el, 3),
                         "eff_tok_s": round(eff / el, 2) if el else 0,
                         "has_marker": any(m in text for m in MARKERS)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    out = {"schema": 1, "adapters": str(a.adapters), "lora_tensors_loaded": n,
           "k": a.latent_steps, "cap": 256, "rows": rows,
           "mean_effective_latent": round(sum(x["latent"]["effective"] for x in rows)/len(rows), 1),
           "mean_effective_text": round(sum(x["text"]["effective"] for x in rows)/len(rows), 1),
           "mean_eff_tok_s_latent": round(sum(x["latent"]["eff_tok_s"] for x in rows)/len(rows), 2),
           "mean_eff_tok_s_text": round(sum(x["text"]["eff_tok_s"] for x in rows)/len(rows), 2)}
    le, te = out["mean_effective_latent"], out["mean_effective_text"]
    out["token_reduction_pct"] = round(100 * (te - le) / te, 1) if te else 0
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print("RESULT " + json.dumps({k: v for k, v in out.items() if k != "rows"}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
