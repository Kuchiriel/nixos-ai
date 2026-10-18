#!/usr/bin/env python3
"""websearch.py — busca tavily p/ o duplex (18/10 14:00). O inline de
shell era um ninho de aspas quebrado (Traceback toda chamada). Uso:
    python3 websearch.py "query"     → até 3 resultados (nome — url)"""
import json
import os
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
        print("ERRO: sem TAVILY no /etc/litellm.env")
        return
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        json.dumps({"query": q, "max_results": 3}).encode(),
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=20))
        outs = [f"{r.get('name', '')} — {r.get('url', '')}"
                for r in d.get("results", [])[:3]]
        print(" ; ".join(outs) if outs else "(sem resultados)")
    except Exception as exc:  # noqa: BLE001
        print(f"ERRO: {exc}")

if __name__ == "__main__":
    main()
