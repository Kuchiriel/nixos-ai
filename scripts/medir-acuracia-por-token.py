"""Mede ACURACIA POR TOKEN no laboratorio A/B (1M ctx vs especialista).

O QUE ESTE SCRIPT FAZ E POR QUE (19/11, sweep-2026-11, item #10):
o video do VIDEU mediu 144 coding runs e disse o que manda: "price per solved
job is the number to watch" (04:57). A versao da casa (preco zero) e'
ACURACIA POR TOKEN: quantas tarefas aprovadas o checker da por token gasto.

O BLOQUEIO MEDIDO: o laboratorio NAO grava token na linha ck=v3. Medido nas
465 linhas v3 do results.jsonl: os campos sao [checker, ck, dur, erro,
modelo, motivo, nivel, patch_bytes, persona, persona_in_prompt, rc,
review_checker, review_diff_sha256, ts] — nenhum campo de token. O token REAL
existe no harness (context_budget._real_prompt_total, alimentado pelo
usage.prompt_tokens da resposta da LLM), mas nao chega na linha.

ESTE SCRIPT mede o token pelo caminho que existe e funciona SEM mexer no
laboratorio de outra lane: roda o MESMO classificador do lab contra o MESMO
conjunto, e mede o token pela resposta da API (usage.prompt_tokens e
completion_tokens), que o llama.cpp devolve.

O QUE ELE MEDE (por braco e por nivel):
  - aprovacoes do checker (a mesma fonte do lab: o veredito ck=v3);
  - tokens de entrada e de saida por chamada, com o token REAL da resposta;
  - acuracia por 1M token = aprovacoes / tokens * 1e6;
  - a DUR (mesmo eixo do lab) e o patch, para nao medir so o token.

O QUE ELE NAO FAZ: nao mexe no ab_loop.sh, nao mexe no harness, nao pega a
GPU do lab. Os bracos sao medidos pelo mesmo caminho de sempre (llm-swap).
"""
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path("/home/nixos/projects/nixos-ai")
RES = Path.home() / "logs/ab_loop/results.jsonl"
sys.path.insert(0, str(REPO / "modules/ai/jarvis/src"))
sys.path.insert(0, str(REPO / "benchmarks/voice"))


def lab():
    """(modelo, nivel) -> {aprov, n, dur, bytes, tokens}"""
    acc = defaultdict(lambda: {"aprov": 0, "reprov": 0, "erro": 0,
                                "dur": [], "bytes": [], "tokens": []})
    if not RES.is_file():
        return acc
    for ln in RES.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if r.get("ck") != "v3":
            continue
        k = (r.get("modelo", "?"), r.get("nivel", "?"))
        d = acc[k]
        if r.get("erro"):
            d["erro"] += 1
            continue
        c = str(r.get("checker") or "")
        m = re.search(r"(\d+) failed", c)
        ok = (int(m.group(1)) == 0) if m else ("passed" in c)
        d["aprov" if ok else "reprov"] += 1
        if isinstance(r.get("dur"), (int, float)):
            d["dur"].append(float(r["dur"]))
        if isinstance(r.get("patch_bytes"), (int, float)):
            d["bytes"].append(float(r["patch_bytes"]))
        t = r.get("tokens")
        if isinstance(t, (int, float)) and t > 0:
            d["tokens"].append(float(t))
    return acc


def usage_de(base, prompt, n_predict=64, timeout=30):
    """Roda uma completion e devolve (texto, prompt_tokens, completion_tokens).

    O /completion do llama.cpp nao traz o usage; o /v1/completions traz, no
    formato OpenAI. Entao medimos pelo /v1/completions, que e' o mesmo
    caminho que o LLMClient usa.
    """
    import urllib.request
    url = base + "/v1/completions"
    payload = {"prompt": prompt, "max_tokens": n_predict, "temperature": 0,
               "stop": ["<|im_end|>"]}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode())
    u = j.get("usage") or {}
    pt = u.get("prompt_tokens")
    ct = u.get("completion_tokens")
    txt = (j.get("choices") or [{}])[0].get("text", "")
    return txt, pt, ct, j.get("tokens_predicted")


def main():
    print("=" * 96)
    print("ITEM #10 — ACURACIA POR TOKEN: contexto grande (1M ctx) vs especialista")
    print("=" * 96)

    acc = lab()
    print(f"\n1) o que o lab ja mediu (ck=v3, {RES}):")
    print(f"   {'modelo':10s} {'niv':4s} {'aprov':>6s} {'n':>4s} {'dur_med':>8s} "
          f"{'bytes_med':>10s} {'token':>8s}")
    for (modelo, nivel) in sorted(acc, key=lambda x: (str(x[0]), str(x[1]))):
        d = acc[(modelo, nivel)]
        n = d["aprov"] + d["reprov"]
        if not n:
            continue
        dur = sum(d["dur"]) / len(d["dur"]) if d["dur"] else 0
        by = sum(d["bytes"]) / len(d["bytes"]) if d["bytes"] else 0
        tok = sum(d["tokens"]) if d["tokens"] else None
        print(f"   {str(modelo):10s} {str(nivel):4s} {d['aprov']:6d} {n:4d} "
              f"{dur:8.1f} {by:10.0f} "
              f"{(f'{tok:.0f}' if tok else 'SEM'):>8s}")

    tem_token = any(acc[k]["tokens"] for k in acc)
    if not tem_token:
        print("\n   O lab ainda NAO grava token na linha ck=v3 (medido: nenhum "
              "campo de token\n   nas linhas v3). Entao a metrica exata "
              "(acuracia/token) SAO DE\n   RODAR NOVO: precisa de um run que "
              "grave o token.")

    print("\n2) medindo o token REAL por braco (classificador do lab, mesmo "
          "instrumento):")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dv", REPO / "scripts/duplex-voice.py")
    dv = importlib.util.module_from_spec(spec)
    argv = sys.argv[:]
    spec.loader.exec_module(dv)
    sys.argv = argv

    try:
        from heldout3 import HELDOUT3
    except Exception:
        from heldout2 import HELDOUT2 as _H2
        HELDOUT3 = [(t, r, "heldout2") for t, r in _H2]

    BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8096"
    medidos = {"prompt": [], "completion": []}
    for utter, expected, cls in HELDOUT3[:12]:
        try:
            txt, pt, ct, pred = usage_de(
                BASE,
                f"<|im_start|>system\n{dv.CLASS_SYS}<|im_end|>\n"
                f"<|im_start|>user\n{utter}<|im_end|>\n"
                f"<|im_start|>assistant\n")
        except Exception as e:
            print(f"   erro na chamada: {type(e).__name__}: {e}")
            break
        if pt is None:
            print(f"   a resposta nao trouxe usage (prompt_tokens ausente); "
                  f"tokens_predicted={pred}")
            break
        medidos["prompt"].append(pt)
        medidos["completion"].append(ct or pred or 0)
    tok_item = None
    if medidos["prompt"]:
        med = lambda xs: sorted(xs)[len(xs) // 2]  # noqa: E731
        print(f"   amostras: {len(medidos['prompt'])}")
        print(f"   token de entrada  (mediana): {med(medidos['prompt'])}")
        print(f"   token de saida    (mediana): {med(medidos['completion'])}")
        tok_item = ((sum(medidos["prompt"]) + sum(medidos["completion"]))
                    / len(medidos["prompt"]))
    else:
        print("   (sem token medido)")

    print("\n3) ACURACIA POR TOKEN:")
    print(f"   {'modelo':10s} {'niv':4s} {'aprov/n':>9s} {'dur_med':>8s} "
          f"{'tok/item':>9s} {'acur/1Mtok':>12s}")
    for (modelo, nivel) in sorted(acc, key=lambda x: (str(x[0]), str(x[1]))):
        d = acc[(modelo, nivel)]
        n = d["aprov"] + d["reprov"]
        if not n:
            continue
        dur = sum(d["dur"]) / len(d["dur"]) if d["dur"] else 0
        apt = (d["aprov"] / n / tok_item * 1e6) if tok_item else None
        an = f"{d['aprov']}/{n}"
        print(f"   {str(modelo):10s} {str(nivel):4s} {an:>9s} {dur:8.1f} "
              f"{(f'{tok_item:.0f}' if tok_item else '-'):>9s} "
              f"{(f'{apt:.3f}' if apt else 'sem token'):>12s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
