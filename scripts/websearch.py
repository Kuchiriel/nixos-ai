#!/usr/bin/env python3
"""websearch.py — busca tavily p/ o duplex. Uso:
    python3 websearch.py "query"  → RESPOSTA sintetizada + snippets"""
import json
import os
import re
import sys
import urllib.request


def main():
    q = " ".join(sys.argv[1:]).strip()
    if not q:
        print("ERRO: query vazia")
        return
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        try:
            for line in open("/etc/litellm.env"):
                if line.startswith(("TAVILY", "TAVILY_API_KEY")):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except Exception:
            pass
    if not key:
        print("ERRO: sem TAVILY_API_KEY")
        return
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        json.dumps({"query": q, "max_results": 3}).encode(),
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=20))
    except Exception as exc:  # noqa: BLE001
        print(f"ERRO: {exc}")
        return
    outs = []
    ans = (d.get("answer") or "").strip()
    if ans:
        outs.append(f"RESPOSTA: {ans[:300]}")
    for r in d.get("results", [])[:3]:
        nome = r.get("name") or r.get("title") or "(s/t)"
        trecho = (r.get("content") or "")[:180].replace("\n", " ")
        trecho = re.sub(r"(?<=[\d,.])\s*(R\$|US\$)", r" \1", trecho)
        outs.append(f"{nome}: {trecho} [{r.get('url', '')}]")
    print(" ; ".join(outs) if outs else "(sem resultados)")


if __name__ == "__main__":
    main()
