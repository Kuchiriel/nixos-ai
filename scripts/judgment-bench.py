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
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "data" / "judgments" / "SCHEMA.md"

SYSTEM = (
    "Você é o anotador de relevância de busca (o mesmo rubric do UHRS da "
    "Microsoft). Julgue a página para a consulta.\n"
    "Responda com UMA das quatro opções, e nada mais:\n"
    "3 = highly relevant: a página responde a consulta de forma direta e "
    "completa, e é o melhor resultado possível\n"
    "2 = moderately relevant: a página responde a consulta e é boa, mas existe "
    "um resultado melhor\n"
    "1 = slightly relevant: é do mesmo tema e ajuda em parte, mas não "
    "responde a consulta\n"
    "0 = not relevant: não responde a consulta nem ajuda o usuário a chegar "
    "na resposta\n"
    "Desempate: prefira a página que ENTREGA a informação; a mais recente "
    "quando o conteúdo é temporal; a fonte primária; uma resposta direta no "
    "lugar de uma resposta enterrada.\n"
    "Resposta: apenas o número (3, 2, 1 ou 0)."
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



def active_model(base: str, wanted: str = "", timeout: float = 10.0) -> str:
    """Descobre o modelo que o servidor local tem CARREGADO.

    (14/11) Bug pego no teste: o router :8080 anuncia so o que esta
    carregado (medido: ['bonsai']) e pedir 'jarvis-mtp-lora' a ele da 400 —
    o tier do duplex roda na porta 8092, nao no router. Descobrir o id evita
    a chamada quebrada (e o self-test nao pegaria isso, porque ele nao fala
    com o modelo).
    """
    if wanted:
        return wanted
    try:
        url = base.rstrip("/") + "/v1/models"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        ids = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
        if ids:
            return ids[0]
    except Exception:
        pass
    return "bonsai"


def pick_model(bases, wanted: str = "", timeout: float = 10.0):
    """Escolhe (base, modelo) testando de verdade: o primeiro que responder.

    (14/11) Medido agora: o router :8080 anuncia 'bonsai' mas nao consegue
    carregar o modelo (HTTP 500 'model name=bonsai failed to load'), enquanto
    o 4B do duplex em :8092 (alias jarvis-mtp-lora) responde normal. Por isso
    a escolha nao e' 'o primeiro que anuncia': e' o primeiro que RESPONDE.
    """
    import urllib.error
    wanted = wanted or ""
    for base in bases:
        model = wanted
        try:
            with urllib.request.urlopen(base.rstrip("/") + "/v1/models",
                                        timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            ids = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
            model = wanted or (ids[0] if ids else "")
        except Exception:
            ids = []
        if not model:
            continue
        body = {"model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "temperature": 0, "max_tokens": 4}
        req = urllib.request.Request(
            base.rstrip("/") + "/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                json.loads(resp.read().decode())
            return base, model
        except Exception:
            continue
    return None, ""

def ask_model(base, model, row, timeout=90):
    """Chama o modelo local (OpenAI-compatible) e devolve a resposta curta."""
    ctx, _dropped = sanitize_context(row.get("context", ""))
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": ctx},
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


# (14/11) O CONTEXTO NAO PODE LEVAR A RESPOSTA. Medido: com a resposta do
# dono no fim do contexto (o formato que o uhrs-practice.py gravava ate
# 14/11, e o que o SCHEMA.md ainda descrevia), o bench media 11/12 = 91,7%
# — o modelo lia a resposta no prompt. Com o contexto limpo, 7/12 = 58,3%.
# Um numero falso e' pior do que nenhum numero: ele decide o modo de
# delegacao. Entao o bench SANITIZA o contexto antes de chamar o modelo e
# avisa quantos itens ele teve de limpar.
LEAK_MARKERS = ("answer by the owner", "resposta do dono", "resposta do owner",
                "owner answer", "gabarito", "answer by the owner:")


def sanitize_context(ctx):
    """Tira do contexto qualquer linha que entregue a resposta.

    Devolve (contexto_limpo, quantas_linhas_tirou).
    """
    text = str(ctx or "")
    kept, dropped = [], 0
    for line in text.splitlines():
        low = line.lower()
        if any(m in low for m in LEAK_MARKERS):
            dropped += 1
            continue
        kept.append(line)
    return "\n".join(kept).strip(), dropped


# (14/11) MEDIR NO TREINO E' MEDIR MEMORIZACAO. Sem --heldout, o bench
# media em `args.data`, que depois do treino e' o proprio arquivo de treino.
# Descobre-se aqui os ids de treino para avisar com o numero exato.
def train_ids(repo):
    """Todos os ids que entraram em algum split de treino."""
    ids = set()
    candidates = [Path(repo) / "data" / "judgments" / "train.jsonl"]
    laya = Path(repo) / "data" / "judgments" / "laya"
    if laya.is_dir():
        candidates += sorted(laya.glob("train*.jsonl"))
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = row.get("_id", row.get("id"))
            if rid is not None:
                ids.add(str(rid))
    return ids


def item_id(row):
    """O id do item: 'id' no schema do dono, '_id' no formato Laya.

    (14/11) Bug: o bench usava so `id`, e o dataset Laya usa `_id` => as
    divergencias saiam com id=None e a repetibilidade do dono colapsava
    todos os itens em um grupo so (medido: "0/1 = 0.0%" com 4 itens).
    """
    for key in ("id", "_id"):
        val = row.get(key)
        if val is not None and str(val) != "":
            return str(val)
    return ""


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
    # (14/11) o self-test agora prova o ponto que decide o numero: o
    # contexto que entrega a resposta e' limpo antes do prompt.
    leaky = ("Query: q\nPage: p\nAnswer by the owner: 3", 1)
    ctx, dropped = sanitize_context(leaky[0])
    assert dropped == 1, f"nao limpou a linha que entrega a resposta: {ctx}"
    assert "owner" not in ctx.lower(), ctx
    assert "3" not in ctx, ctx
    clean = ("Query: q\nPage: p", 0)
    ctx2, dropped2 = sanitize_context(clean[0])
    assert dropped2 == 0 and ctx2 == clean[0], ctx2
    # (14/11) o id do item nos DOIS formatos: 'id' (schema do dono) e
    # '_id' (dataset Laya). Sem isso a repetibilidade colapsava tudo num
    # grupo so e as divergencias saiam com id=None.
    assert item_id({"id": "q-1"}) == "q-1", item_id({"id": "q-1"})
    assert item_id({"_id": "prat-p01"}) == "prat-p01", item_id({"_id": "x"})
    assert item_id({"id": "a", "_id": "b"}) == "a", item_id({"id": "a", "_id": "b"})
    print(f"SELF-TEST ok: {ok}/{len(rows)} de concordância (modelo=eco) e o "
          f"contexto com a resposta e' limpo antes do prompt")
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
    ap.add_argument("--tier", default="",
                    help="modelo a pedir (vazio = o que o servidor tem carregado)")
    ap.add_argument("--self-test", action="store_true",
                    help="prova a mecanica sem chamar modelo")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.data:
        ap.error("falta --data (ou --self-test)")

    measured_on_train = False
    if args.heldout:
        rows = load(args.heldout)
        source = args.heldout
    else:
        rows = load(args.data)
        source = args.data
        measured_on_train = True
    # (14/11) avisar se o que esta sendo medido tem ids de TREINO: o numero
    # mede memorizacao, nao concordancia de julgamento.
    tr = train_ids(REPO)
    if tr and rows:
        row_ids = {item_id(r) for r in rows if item_id(r)}
        common = row_ids & tr
        if common:
            print(f"AVISO: {len(common)} id(s) deste arquivo tambem entraram "
                  f"no split de TREINO (ex.: {sorted(common)[:5]}). Medir aqui "
                  f"mede MEMORIZACAO, nao concordancia de julgamento — use o "
                  f"held-out para o numero que decide a delegacao.")
        elif measured_on_train:
            print("AVISO: medindo sem --heldout. Use --heldout "
                  "data/judgments/heldout.jsonl para o numero honesto.")
    # (14/11) 'unparsed' NAO e' divergencia do modelo: e' uma fala do dono
    # que o bench nao entendeu. Contar isso afundaria a concordancia por um
    # motivo que nao e' do modelo, e o numero que decide a delegacao tem de
    # ser honesto. As linhas sao puladas e contadas.
    unparsed = [r for r in rows if str(r.get("answer", "")).strip().lower()
                == "unparsed"]
    rows = [r for r in rows if r not in unparsed]
    if unparsed:
        print(f"AVISO: {len(unparsed)} label(s) com answer='unparsed' (fala do "
              f"dono nao entendida) foram puladas: nao sao erro do modelo.")
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print("dataset vazio", file=sys.stderr)
        return 1
    if not SCHEMA.is_file():
        print(f"aviso: schema ausente em {SCHEMA}", file=sys.stderr)

    base, model = pick_model([args.model, "http://127.0.0.1:8092"], args.tier)
    if not base:
        print("ERRO: nenhum modelo local respondeu (router :8080 carregando "
              "com falha e 4B :8092 sem resposta)", file=sys.stderr)
        return 2
    same = 0
    misses = []
    predictions = []          # (gold, pred) por item: UMA chamada por item
    cleaned = 0              # itens cujo contexto entregava a resposta
    for r in rows:
        _ctx, dropped = sanitize_context(r.get("context", ""))
        cleaned += 1 if dropped else 0
        try:
            pred = ask_model(base, model, r)
        except Exception as exc:  # noqa: BLE001
            print(f"erro ao chamar o modelo: {exc}", file=sys.stderr)
            return 2
        gold = norm(r.get("answer"))
        predictions.append((gold, norm(pred)))
        hit = gold == norm(pred)
        same += hit
        if not hit:
            misses.append((item_id(r), r.get("answer"), pred))
    n = len(rows)
    if cleaned:
        print(f"AVISO: {cleaned} item(ns) tinham a resposta do dono DENTRO do "
              f"context (leak): tirei antes de chamar o modelo. Sem isso o "
              f"bench mede o modelo lendo a resposta (91,7% em vez de 58,3% "
              f"medido hoje).")
    rate = same / n
    lo, hi = wilson(same, n)
    print(f"concordância {same}/{n} = {rate:.1%}  (IC 95%: {lo:.1%} a {hi:.1%})")

    # (13/11) ACORDO POR CLASSE (F1 por nivel). Medido o overall esconde ONDE
    # a regra falha: se o modelo erra sempre no "moderately", o overall
    # parece ok e o rubric esta mal especificado nesse nivel. Base: arXiv
    # 2603.06865 (metrica de concordancia para anotacao em NLP) e o
    # padrao da casa em arxiv-2510.07978 (a concordancia do judge se compara
    # com a concordancia ENTRE ANOTADORES, nao com 100%).
    tp = Counter()
    fp = Counter()
    fn = Counter()
    # (14/11) usa a MESMA resposta da concordancia (uma chamada por item)
    for gold, pred in predictions:
        if gold == pred:
            tp[gold] += 1
        else:
            fp[pred or "(vazio)"] += 1
            fn[gold or "(vazio)"] += 1
    print("F1 por nivel (o nivel em que a regra falha aparece aqui):")
    levels = [k for k in ("3", "2", "1", "0") if (tp[k] + fn[k])]
    for k in levels:
        prec = tp[k] / (tp[k] + fp[k]) if (tp[k] + fp[k]) else 0.0
        rec = tp[k] / (tp[k] + fn[k]) if (tp[k] + fn[k]) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        print(f"  nivel {k}: F1 {f1:.2f} (prec {prec:.2f} rec {rec:.2f}, "
              f"{tp[k]}/{tp[k]+fn[k]} acertados)")

    # teto humano: se o mesmo id foi julgado mais de uma vez com respostas
    # diferentes, a repetibilidade do dono e' o teto real da delegacao.
    by_id = {}
    for r in rows:
        by_id.setdefault(item_id(r), []).append(norm(r.get("answer")))
    repeated = {k: v for k, v in by_id.items() if len(v) > 1}
    if repeated:
        agree = sum(1 for v in repeated.values() if len(set(v)) == 1)
        self_rate = agree / len(repeated)
        print(f"repetibilidade do dono (mesmo id, respostas diferentes): "
              f"{agree}/{len(repeated)} = {self_rate:.1%}  => este e' o TETO "
              f"real da delegacao")
    else:
        print("teto humano: ainda nao medido (o dono precisa julgar alguns "
              "itens duas vezes)")

    if misses:
        print("divergências (id, dono, modelo):")
        for m in misses[:20]:
            print("  ", m)
    print(f"modo recomendado: {mode_for(rate)}")
    if measured_on_train:
        print("ATENCAO: esta medicao foi feita SEM held-out (o proprio arquivo "
              "medido pode ter virado treino). O veredito acima so vale para o "
              "held-out; rode com --heldout data/judgments/heldout.jsonl.")
    print("LEMBRETE (arXiv 2510.07978): o limiar e' a repetibilidade do "
          "dono, nao 100% — se o proprio dono so concorda consigo mesmo em X%, "
          "o modelo nao pode passar de X%.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
