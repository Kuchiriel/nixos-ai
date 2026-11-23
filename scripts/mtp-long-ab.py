#!/usr/bin/env python3
"""MTP A/B com prompt longo (~1k tokens) e parallel>1.

Mesmo GGUF/LoRA/flags; so --spec-type muda. Gera o prompt longo localmente
(repetindo frases tecnicas distincts) e mede 8 requisicoes com max_tokens=64.
Uso: mtp_long_ab.py <url> <alias> <out.json>
"""
from __future__ import annotations
import json, sys, time, urllib.request
from pathlib import Path

BASE = [
    "Explain in two sentences why speculative decoding can speed up LLM inference.",
    "What is the difference between a token and a byte in LLM serving?",
    "List three risks of running a 4B model on a 6 GB consumer GPU.",
    "How does KV cache reuse reduce time to first token?",
    "Describe in two sentences what binary quantization does to float weights.",
    "Why does RAG need provenance metadata on every indexed chunk?",
    "Give one sentence on why a cosine learning-rate schedule is used in QAT.",
    "Explain what a tailnet is and why it avoids exposing a residential IP.",
]


def long_prompt(target_tokens=1000):
    txt = "Context: " + " ".join(BASE)
    while len(txt.split()) < target_tokens:
        txt += " " + " ".join(BASE)
    return txt[: target_tokens * 6]


def call(url, alias, prompt):
    body = json.dumps({"model": alias, "prompt": prompt, "max_tokens": 64,
                       "temperature": 0}).encode()
    req = urllib.request.Request(url + "/v1/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read())


def main():
    url, alias, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    prompt = long_prompt(1000)
    print("prompt_words", len(prompt.split()), flush=True)
    first = None
    for _ in range(90):
        try:
            first = call(url, alias, prompt)
            if "timings" in first:
                break
        except Exception:
            pass
        time.sleep(2)
    if not first or "timings" not in first:
        raise SystemExit("modelo nao ficou pronto")
    rows = []
    samples = [first] + [call(url, alias, prompt) for _ in range(7)]
    for d in samples:
        t = d.get("timings", {})
        rows.append({"prompt_tokens": t.get("prompt_n"),
                     "tokens": t.get("predicted_n"),
                     "tok_s": round(t.get("predicted_per_second", 0), 2),
                     "seconds": round(t.get("predicted_ms", 0)/1000, 3),
                     "draft_n": t.get("draft_n", 0),
                     "draft_accepted": t.get("draft_n_accepted", 0)})
    td = sum(r["draft_n"] or 0 for r in rows)
    ta = sum(r["draft_accepted"] or 0 for r in rows)
    # primeira requisicao = sem cache; demais reaproveitam o prefixo (prompt_n cai)
    cold = rows[0]
    summary = {"n": len(rows), "cold_prompt_tokens": cold["prompt_tokens"],
               "cold_tok_s": cold["tok_s"], "cold_seconds": cold["seconds"],
               "warm_mean_tok_s": round(sum(r["tok_s"] for r in rows)/len(rows), 2),
               "mean_seconds": round(sum(r["seconds"] for r in rows)/len(rows), 3),
               "draft_tokens": td, "draft_accepted": ta,
               "accept_rate": round(ta/td, 4) if td else None}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    print("RESULT " + json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
