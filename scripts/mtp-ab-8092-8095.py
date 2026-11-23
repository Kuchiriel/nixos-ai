#!/usr/bin/env python3
"""A/B de latencia: 8092 (local 4B com MTP) vs 8095 (nv-gate/NIM).

HELDOT FIXO: 8 prompts curtos em ingles, mesma ordem nos dois lados.
Nao troca modelos, nao reinicia servicos, nao escreve segredos em disco.
Para 8092 mede tambem draft_n/draft_n_accepted (taxa de aceite MTP).
IMPORTANTE: os modelos sao DIFERENTES — o resultado isola a rota, nao o MTP.
"""
from __future__ import annotations
import json, os, sqlite3, time, urllib.request
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
DB = "/home/nixos/.local/share/opencode/opencode.db"


def credential() -> str:
    c = sqlite3.connect("file:" + DB + "?mode=ro", uri=True, timeout=5)
    row = c.execute("select value from credential where integration_id='nvidia' and active=1 limit 1").fetchone()
    if not row:
        return ""
    try:
        return str(json.loads(row[0]).get("key", ""))
    except Exception:
        return str(row[0])


def call(url: str, body: dict, auth: str = "") -> dict:
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = "Bearer " + auth
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read())
    elapsed = time.perf_counter() - t0
    return {"data": data, "elapsed": elapsed}


def main() -> int:
    auth = "" if os.environ.get("SKIP_GATE") else credential()
    out = {"heldout": len(PROMPTS), "max_tokens": 64, "temperature": 0,
           "note": "8092 = local Qwen3.5-4B MTP; 8095 = nv-gate NIM (modelo remoto diferente)",
           "rows": []}
    for p in PROMPTS:
        row = {"prompt": p[:48]}
        try:
            r = call("http://127.0.0.1:8092/v1/completions",
                     {"model": "jarvis-mtp-lora", "prompt": p,
                      "max_tokens": 64, "temperature": 0})
            t = r["data"].get("timings", {})
            n = t.get("predicted_n", 0)
            row["local"] = {"tokens": n, "seconds": round(r["elapsed"], 3),
                            "tok_s": round(t.get("predicted_per_second", n / r["elapsed"]), 2),
                            "draft_n": t.get("draft_n"), "draft_accepted": t.get("draft_n_accepted")}
        except Exception as e:
            row["local"] = {"error": str(e)[:120]}
        if auth:
            try:
                r = call("http://127.0.0.1:8095/v1/chat/completions",
                         {"model": "minimaxai/minimax-m3.1-flash",
                          "messages": [{"role": "user", "content": p}],
                          "max_tokens": 64, "temperature": 0}, auth)
                n = r["data"].get("usage", {}).get("completion_tokens", 0)
                row["gate"] = {"tokens": n, "seconds": round(r["elapsed"], 3),
                               "tok_s": round(n / r["elapsed"], 2) if r["elapsed"] else 0}
            except Exception as e:
                row["gate"] = {"error": str(e)[:120]}
        else:
            row["gate"] = {"error": "credencial nvidia ausente"}
        out["rows"].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    for side in ("local", "gate"):
        ok = [x[side] for x in out["rows"] if "tok_s" in x[side]]
        if ok:
            out[side + "_summary"] = {
                "n": len(ok),
                "mean_tok_s": round(sum(x["tok_s"] for x in ok) / len(ok), 2),
                "mean_latency_s": round(sum(x["seconds"] for x in ok) / len(ok), 3),
            }
    drafts = [x["local"] for x in out["rows"] if x["local"].get("draft_n")]
    if drafts:
        total = sum(x["draft_n"] for x in drafts)
        acc = sum(x["draft_accepted"] or 0 for x in drafts)
        out["mtp_acceptance"] = {"draft_tokens": total, "accepted": acc,
                                 "rate": round(acc / total, 4) if total else None}
    summary = {k: v for k, v in out.items() if k != "rows"}
    print("RESULT " + json.dumps(summary, ensure_ascii=False), flush=True)
    dest = Path(os.environ.get("MTP_AB_OUT", "/home/nixos/work/hybrid/mtp-ab-report.json"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
