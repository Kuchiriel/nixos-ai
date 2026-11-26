#!/usr/bin/env python3
"""Benchmark pareado de modelos locais: tok/s, latencia e aceite MTP.

Nao troca modelos de producao: sobe llama-server em porta temporaria com
takeover/release do residente. Uso: bench_llm_fixed.py <porta> <modelo> <saida>
"""
from __future__ import annotations
import json, sys, time, urllib.request
from pathlib import Path

PROMPTS = [
    "Explain in two sentences why speculative decoding can speed up LLM inference.",
    "What is the difference between a token and a byte in LLM serving?",
    "List three risks of running a 4B model on a 6 GB consumer GPU.",
    "How does KV cache reuse reduce time to first token?",
]


def call(url, alias, prompt):
    body = json.dumps({"model": alias, "prompt": prompt, "max_tokens": 64,
                       "temperature": 0}).encode()
    req = urllib.request.Request(url + "/v1/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read())


def main():
    port, model, alias, out = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
    url = "http://127.0.0.1:" + port
    first = None
    for _ in range(120):
        try:
            first = call(url, alias, PROMPTS[0])
            if "timings" in first:
                break
        except Exception:
            pass
        time.sleep(2)
    if not first or "timings" not in first:
        raise SystemExit("modelo nao ficou pronto")
    rows = []
    samples = [first] + [call(url, alias, p) for p in PROMPTS[1:]]
    for i, d in enumerate(samples):
        t = d.get("timings", {})
        rows.append({"i": i, "prompt_tokens": t.get("prompt_n"),
                     "tokens": t.get("predicted_n"),
                     "tok_s": round(t.get("predicted_per_second", 0), 2),
                     "seconds": round(t.get("predicted_ms", 0) / 1000, 3),
                     "draft_n": t.get("draft_n", 0),
                     "draft_accepted": t.get("draft_n_accepted", 0)})
    summary = {"model": model, "alias": alias, "n": len(rows),
               "mean_tok_s": round(sum(r["tok_s"] for r in rows)/len(rows), 2),
               "mean_seconds": round(sum(r["seconds"] for r in rows)/len(rows), 3),
               "draft_tokens": sum(r["draft_n"] for r in rows),
               "draft_accepted": sum(r["draft_accepted"] for r in rows)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    print("RESULT " + json.dumps(summary))


if __name__ == "__main__":
    main()
