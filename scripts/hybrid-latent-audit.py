#!/usr/bin/env python3
"""PoC: share de tokens 'pensamento' convertíveis em modo latente.

Fonte externa (medida): togethercomputer/HybridAgent-HybridSFT-v2 tem
`rounds[].assistant` com spans <think>...</think> — exatamente o trecho que
o HybridAgent (arXiv 2610.18861) rotearia para o modo latente.
Fonte interna: logs consolidados do agent hub têm linhas `[reasoning]`.

READ-ONLY: só GET na HuggingFace e leitura de arquivos locais.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

HF = "https://datasets-server.huggingface.co/rows"
DATASET = "togethercomputer/HybridAgent-HybridSFT-v2"


def fetch_rows(n: int) -> list[str]:
    q = urllib.parse.urlencode({"dataset": DATASET, "config": "default",
                                "split": "train", "offset": 0, "length": n})
    with urllib.request.urlopen(HF + "?" + q, timeout=45) as r:
        data = json.loads(r.read())
    out = []
    for row in data.get("rows", []):
        for rd in (row.get("row", {}).get("rounds") or []):
            if isinstance(rd, dict) and isinstance(rd.get("assistant"), str):
                out.append(rd["assistant"])
    return out


def share(texts: list[str], marker: str) -> dict:
    total = thought = 0
    for t in texts:
        words = len(re.findall(r"\S+", t))
        if marker == "think":
            inner = sum(len(re.findall(r"\S+", s)) for s in
                        re.findall(r"<think>(.*?)</think>", t, flags=re.S))
        else:
            inner = sum(len(re.findall(r"\S+", s)) for s in
                        t.split("[reasoning]")[1:])
            inner = min(inner, words)
        total += words
        thought += inner
    return {"texts": len(texts), "words_total": total, "words_think": thought,
            "share": round(thought / total, 4) if total else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows", type=int, default=100)
    ap.add_argument("--local-log", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    out = {"hybridagent_paper_claim": {"token_reduction": "35.5%-54.7%",
                                       "source": "arXiv 2610.18861"},
           "dataset": DATASET}
    try:
        texts = fetch_rows(a.rows)
        out["external_sft_share"] = share(texts, "think")
    except Exception as exc:
        out["external_error"] = str(exc)[:200]
    if a.local_log and a.local_log.is_file():
        text = a.local_log.read_text(encoding="utf-8", errors="ignore")
        out["local_hub_share"] = share([text], "reasoning")
    out["verdict"] = ("PROMISSOR" if out.get("external_sft_share", {}).get("share", 0) >= 0.3
                      else "INSUFICIENTE")
    print(json.dumps(out, indent=2, ensure_ascii=False) if a.json else
          json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
