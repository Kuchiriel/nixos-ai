#!/usr/bin/env python3
"""Bench de tiers: velocidade (TTFT/prefill/gen) + qualidade (PT-BR e lógica/código).

Contrato:
- NÃO gerencia servidores (usa os que estão no ar; sem pkill, sem start/stop).
- Casos PT-BR importados de canary tools/i18n (fonte única, sem duplicar).
- QA de tradução importado de traduzir.qa (idem).
- Saída: results/<tag>.json + linha p/ BENCHMARK-MATRIX.md.
- Uso: bench.py --endpoint http://127.0.0.1:8080 --model bonsai --tag bonsai-0710
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, "/home/nixos/projects/canary-official/tools/i18n")
from benchmark_modelos import CASOS_DIFICIES, CASOS_COMUNS  # noqa: E402
from traduzir import qa  # noqa: E402

# Lógica/código: resposta julgada por keyword (auditoria humana nos salvos).
LOGIC = [
    ("Todos os gatos são mamíferos. Tom é um gato. Tom é mamífero? Responda SIM ou NAO e 1 linha.", ["SIM"]),
    ("Sequência: 2, 6, 12, 20, 30. Qual o próximo? Responda só o número.", ["42"]),
    ("Ana diz: 'Beto mente'. Beto diz: 'Ana e eu mentimos'. Quem fala a verdade? 1 linha.", ["Ana", "nenhum", " paradoxo"]),
    ("Um trem a 60km/h anda 2h30. Distância? Responda só o número em km.", ["150"]),
]
CODING = [
    ("Escreva fizzbuzz em Python (função fizzbuzz(n)). Só código.", ["for", "if", "FizzBuzz", "fizzbuzz"]),
    ("Função Python que inverte uma string. Só código.", ["[::-1]", "reversed"]),
    ("Fibonacci iterativo em Python, função fib(n). Só código.", ["fib", "append", "range"]),
    ("SQL: selecione nome e preco da tabela produtos onde preco > 100. Só SQL.", ["SELECT", "WHERE", "100"]),
]

PROMPT_TRAD = "Traduza para PT-BR, só a tradução: {t}"


def chat(endpoint, model, messages, max_tokens=200, temperature=0.0, stream=False):
    data = json.dumps({"model": model, "messages": messages,
                       "max_tokens": max_tokens, "temperature": temperature,
                       "stream": stream}).encode()
    req = urllib.request.Request(f"{endpoint}/v1/chat/completions", data=data,
                                 headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    if not stream:
        r = json.load(urllib.request.urlopen(req, timeout=300))
        dt = time.monotonic() - t0
        ch = r["choices"][0]["message"]["content"]
        tm = r.get("timings", {})
        return ch, {"total_s": dt, "prompt_n": tm.get("prompt_n", 0),
                    "prompt_ms": tm.get("prompt_ms", 0),
                    "gen_n": tm.get("predicted_n", 0), "gen_ms": tm.get("predicted_ms", 0)}
    # streaming: TTFT = primeiro token
    ttft = None
    chunks = []
    with urllib.request.urlopen(req, timeout=300) as resp:
        for line in resp:
            s = line.decode(errors="ignore").strip()
            if not s.startswith("data:"):
                continue
            s = s[5:].strip()
            if s == "[DONE]":
                break
            try:
                d = json.loads(s).get("choices", [{}])[0].get("delta", {}).get("content") or ""
            except Exception:
                continue
            if d and ttft is None:
                ttft = time.monotonic() - t0
            chunks.append(d)
    return "".join(chunks), {"ttft_s": ttft, "total_s": time.monotonic() - t0}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()

    out = {"tag": a.tag, "model": a.model, "endpoint": a.endpoint,
           "ts": time.strftime("%Y-%m-%d %H:%M"), "speed": {}, "ptbr": {}, "logic": {}, "coding": {}}

    # 1. velocidade: prompt fixo, 1x stream (TTFT) + 3x normal (timings)
    sp, _ = chat(a.endpoint, a.model,
                 [{"role": "user", "content": "Explique fotossíntese em 3 frases."}],
                 max_tokens=120, stream=True)
    out["speed"]["ttft_s"] = None
    # re-mede com timings detalhados
    gens, pps = [], []
    for _ in range(3):
        _, tm = chat(a.endpoint, a.model,
                     [{"role": "user", "content": "Explique fotossíntese em 3 frases."}],
                     max_tokens=120)
        if tm["gen_ms"]:
            gens.append(tm["gen_n"] / (tm["gen_ms"] / 1000))
        if tm["prompt_ms"]:
            pps.append(tm["prompt_n"] / (tm["prompt_ms"] / 1000))
    # TTFT separado (stream puro)
    _, stm = chat(a.endpoint, a.model,
                  [{"role": "user", "content": "Diga ok."}],
                  max_tokens=5, stream=True)
    out["speed"] = {"ttft_s": round(stm["ttft_s"], 3) if stm["ttft_s"] else None,
                    "prefill_ts": round(sum(pps) / len(pps), 1) if pps else None,
                    "gen_ts": round(sum(gens) / len(gens), 1) if gens else None}

    # 2. PT-BR: difíceis + comuns, QA importado
    for nome, casos in (("dificeis", CASOS_DIFICIES), ("comuns", CASOS_COMUNS)):
        ok, det = 0, []
        for t in casos:
            pt, _ = chat(a.endpoint, a.model,
                         [{"role": "user", "content": PROMPT_TRAD.format(t=t)}],
                         max_tokens=150)
            falhas = qa(t, pt)
            if not falhas:
                ok += 1
            det.append({"en": t, "pt": pt.strip(), "falhas": falhas})
        out["ptbr"][nome] = {"ok": ok, "n": len(casos), "det": det}

    # 3. lógica + código por keyword
    for nome, casos in (("logic", LOGIC), ("coding", CODING)):
        ok, det = 0, []
        for prompt, keys in casos:
            r, _ = chat(a.endpoint, a.model, [{"role": "user", "content": prompt}],
                        max_tokens=250)
            hit = any(k.lower() in r.lower() for k in keys)
            if hit:
                ok += 1
            det.append({"prompt": prompt[:60], "out": r.strip()[:400], "hit": hit})
        out[nome] = {"ok": ok, "n": len(casos), "det": det}

    p = HERE / "results" / f"{a.tag}.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    pt = out["ptbr"]
    print(f"[{a.tag}] TTFT={out['speed']['ttft_s']}s prefill={out['speed']['prefill_ts']}t/s "
          f"gen={out['speed']['gen_ts']}t/s | PT-BR dif={pt['dificeis']['ok']}/{pt['dificeis']['n']} "
          f"com={pt['comuns']['ok']}/{pt['comuns']['n']} | logic={out['logic']['ok']}/{out['logic']['n']} "
          f"code={out['coding']['ok']}/{out['coding']['n']}")
    print(f"salvo {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
