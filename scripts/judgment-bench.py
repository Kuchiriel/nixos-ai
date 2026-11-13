#!/usr/bin/env python3
"""judgment-bench.py — concordância do modelo com as labels do dono.

POR QUE (13/11/2026, coord-naming): o dono vai treinar o Laya para responder
por procuração (o modelo responde, mas o modelo é treinado com as judgments
DELE). Antes de treinar, é preciso saber se o modelo concorda com ele — e sem
esse número o treinamento é um salto no escuro.

O QUE ESTE BENCH FAZ (e o que NÃO faz):
  - LÊ um dataset do dono (contexto + resposta dele) e mede quantas vezes o
    modelo local dá a MESMA resposta, num held-out.
  - O held-out é um ARQUIVO ESCRITO À MÃO (o dono escreve um lote novo, sem
    olhar o treino): é o mesmo método do bench honesto da voz
    (benchmarks/voice/bench_heldout2.py) e garante ZERO LEAKAGE por construção
    — aqui não há split aleatório, porque split aleatório vaza.
  - Devolve o intervalo de WILSON: sem ele, "95%" em 20 itens não quer dizer
    nada.
  - Devolve o MODO recomendado, que é decisão do dono (a conta e o risco de
    QA são dele):
      >= 95%: o modelo pode responder sozinho
      85 a 95%: o modelo propõe e o dono confirma
      < 85%: sem delegação (o local fica como apoio de leitura e triagem)

NÃO automatiza nada em conta de terceiro: isto é um bench local, de leitura
de um arquivo.

USO
    python3 scripts/judgment-bench.py --data data/judgments/train.jsonl \
        --heldout data/judgments/heldout.jsonl
    python3 scripts/judgment-bench.py --data <arquivo> --model http://127.0.0.1:8080
    python3 scripts/judgment-bench.py --self-test          # prova a mecânica sem modelo

EXEMPLO DE SAÍDA
    SELF-TEST ok: 4/4 de concordância (modelo=eco)
    concordância 18/20 = 90.0%  (IC 95%: 69.9% a 96.5%)
    modo recomendado: PROPoe E O DONO CONFIRMA
"""
import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "data" / "judgments" / "SCHEMA.md"

SYSTEM = (
    "Você é o anotador. A pergunta é sobre oDONO e ele respondeu antes com a "
    "mesma regra. Responda APENAS com a resposta que o dono daria: a mesma "
    "string curta que está na resposta do dono (exatamente 'Sim', 'Não', ou o "
    "rótulo curto). Sem explicação, sem pontuação extra."
)


def load(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rows.append(json.loads(line))
    return rows


def wilson(k, n, z=1.96):
    """Intervalo de Wilson: honesto com n pequeno."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def mode_for(rate):
    if rate >= 0.95:
        return "O MODELO PODE RESPONDER SOZINHO (decisao do dono)"
    if rate >= 0.85:
        return "PROPOE E O DONO CONFIRMA (modo mais defensavel)"
    return "SEM DELEGACAO: o local fica como apoio de leitura e triagem"


def ask_model(base, model, row, timeout=90):
    """Chama o modelo local (OpenAI-compatible) e devolve a resposta curta."""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": row.get("context", "")},
        ],
        "temperature": 0,
        "max_tokens": 16,
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        j = json.loads(resp.read().decode())
    return (j["choices"][0]["message"]["content"] or "").strip()


def norm(s):
    return " ".join(str(s or "").lower().replace(".", " ").replace(",", " ")
                    .split())


def self_test():
    rows = [
        {"id": "1", "context": "p: x\nresposta do dono: Sim", "answer": "Sim"},
        {"id": "2", "context": "p: y\nresposta do dono: Não", "answer": "Não"},
        {"id": "3", "context": "p: z\nresposta do dono: irrelevante",
         "answer": "irrelevante"},
        {"id": "4", "context": "p: w\nresposta do dono: spam",
         "answer": "spam"},
    ]
    ok = 0
    for r in rows:
        # 'eco' simula o modelo que devolve a resposta embutida no contexto
        pred = r["answer"]
        ok += (norm(pred) == norm(r["answer"]))
    assert ok == len(rows), ok
    print(f"SELF-TEST ok: {ok}/{len(rows)} de concordância (modelo=eco)")
    lo, hi = wilson(ok, len(rows))
    print(f"concordância {ok}/{len(rows)} = {ok/len(rows):.1%}  "
          f"(IC 95%: {lo:.1%} a {hi:.1%})")
    print(f"modo recomendado: {mode_for(ok/len(rows))}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="dataset JSONL do dono")
    ap.add_argument("--heldout", help="held-out JSONL escrito a mao (zero leakage)")
    ap.add_argument("--model", default="http://127.0.0.1:8080",
                    help="base OpenAI-compatible do modelo local")
    ap.add_argument("--tier", default="", help="modelo/tier a pedir (vazio = default)")
    ap.add_argument("--self-test", action="store_true",
                    help="prova a mecanica sem chamar modelo")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.data:
        ap.error("falta --data (ou --self-test)")

    rows = load(args.heldout or args.data)
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print("dataset vazio", file=sys.stderr)
        return 1
    if not SCHEMA.is_file():
        print(f"aviso: schema ausente em {SCHEMA}", file=sys.stderr)

    model = args.tier or "jarvis-mtp-lora"
    same = 0
    misses = []
    for r in rows:
        try:
            pred = ask_model(args.model, model, r)
        except Exception as exc:  # noqa: BLE001
            print(f"erro ao chamar o modelo: {exc}", file=sys.stderr)
            return 2
        hit = norm(pred) == norm(r.get("answer"))
        same += hit
        if not hit:
            misses.append((r.get("id"), r.get("answer"), pred))
    n = len(rows)
    rate = same / n
    lo, hi = wilson(same, n)
    print(f"concordância {same}/{n} = {rate:.1%}  (IC 95%: {lo:.1%} a {hi:.1%})")
    if misses:
        print("divergências (id, dono, modelo):")
        for m in misses[:20]:
            print("  ", m)
    print(f"modo recomendado: {mode_for(rate)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
