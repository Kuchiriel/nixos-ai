#!/usr/bin/env python3
"""A/B valido do MTP: mesmo GGUF, mesmos flags, so --spec-type muda.

Uso: mtp_same_ab.py <url> <alias> <saida.json>
Aguarda o modelo carregar (503) antes de medir. Nao escreve segredos.
"""
from __future__ import annotations
import json, sys, time, urllib.request
from pathlib import Path

PROMPTS = [
    "Explain in two sentences why speculative decoding can speed up LLM inference.",
    "What is the difference between a token and a byte in LLM serving?",
    "List three risks of running a 4B model on a 6 GB consumer GPU.",
    "How does KV cache reuse reduce time to first token?",
    "Describe in two sentences what binary quantization does to float weights.",
    "Why does RAG need provenance metadata on every indexed chunk?",
    "Give one sentence on why a cosine learning-rate schedule is used in QAT.",
    "Explain what a tailnet is and why it avoids exposing a residential IP.",
]


def call(url: str, alias: str, prompt: str) -> dict:
    body = json.dumps({"model": alias, "prompt": prompt, "max_tokens": 64,
                       "temperature": 0}).encode()
    req = urllib.request.Request(url + "/v1/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def main() -> int:
    url, alias, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    # espera o modelo sair do estado "Loading model"
    for _ in range(90):
        try:
            first = call(url, alias, PROMPTS[0])
            if "timings" in first:
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        raise SystemExit("modelo nao ficou pronto")
    rows = []
    for p in [first] if False else PROMPTS:
        d = call(url, alias, p)
        t = d.get("timings", {})
        rows.append({"prompt": p[:42], "tokens": t.get("predicted_n"),
                     "tok_s": round(t.get("predicted_per_second", 0), 2),
                     "seconds": round(t.get("predicted_ms", 0) / 1000, 3),
                     "draft_n": t.get("draft_n", 0),
                     "draft_accepted": t.get("draft_n_accepted", 0)})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    total_draft = sum(r["draft_n"] or 0 for r in rows)
    total_acc = sum(r["draft_accepted"] or 0 for r in rows)
    summary = {"n": len(rows),
               "mean_tok_s": round(sum(r["tok_s"] for r in rows) / len(rows), 2),
               "mean_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 3),
               "draft_tokens": total_draft, "draft_accepted": total_acc,
               "accept_rate": round(total_acc / total_draft, 4) if total_draft else None}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False) + "\n")
    print("RESULT " + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
