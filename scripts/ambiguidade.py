"""ambiguidade.py — onde o RUBRIC e' ambiguo, e o que consertar primeiro.

POR QUE (24/11/2026, coord-naming) O paper novo do acervo (arXiv
2511.14117, "Distributions In, Distributions Out") diz: onde os anotadores
discordam de forma sistematica, a distribuicao e' o ground truth e o rotulo
colapsado descarta informacao. E o outro paper do acervo (2603.06865) diz o
que isso significa na pratica: concordancia baixa NAO e' evidencia de dado
ruim — e' **ambiguidade de instrucao**, ou seja, **a frase do rubric esta
ruim**.

A CASA TEM O DADO PARA ISSO, e ele ja estava no registro: cada label carrega
a resposta do DONO (`answer`) e o gabarito da casa (`key`) — o par e' a
"distribuicao" local (um so anotador, entao o par, nao um count vector).

O QUE ESTE SCRIPT FAZ (leitura pura do registro, nada de modelo e nada de
GPU):
  1) mede a AMBIGUIDADE por classe (a taxa em que o dono discorda do
     gabarito) — a classe mais ambigua e' a frase do rubric mais confusa;
  2) mede a INSTABILIDADE do proprio dono (o mesmo item julgado duas vezes
     com respostas diferentes) — o teto real da delegacao (arXiv 2510.07978);
  3) propoe a ORDEM das frases do rubric para consertar: cada `why` da casa
     (a justificativa do gabarito) com quantos labels ela afeta e quantos
     deles o dono contestou — **consertar a frase da casa vale para todos os
     labels futuros**, e o dono nao tem tempo para refazer julgamento;
  4) mostra, lado a lado, o porque da casa e o porque do dono nos itens
     contestados — o texto que o dono precisa ler para concordar ou recusar.

O QUE NAO FAZ: nao julga, nao inventa, nao mexe no registro, nao chama
modelo. O dono continua decidindo; aqui so se mede ONDE a casa esta
confusa.
"""
import argparse
import json
import pathlib
import re
from collections import Counter, defaultdict

REPO = pathlib.Path("/home/nixos/projects/nixos-ai")
DATA = REPO / "data" / "judgments"
LABELS = DATA / "labels.jsonl"
ITEMS = DATA / "uhrs-practice-items.jsonl"

LEVELS = ("3", "2", "1", "0")
LEVEL_NAMES = {"3": "highly relevant", "2": "moderately relevant",
               "1": "slightly relevant", "0": "not relevant"}


def load(path):
    rows = []
    p = pathlib.Path(path)
    if not p.is_file():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def norm(s):
    return str(s or "").strip().lower()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", default=str(LABELS))
    ap.add_argument("--items", default=str(ITEMS))
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    labels = load(args.labels)
    itens = load(args.items)
    # o porque da casa por item (o gabarito vem com a sua justificativa)
    why_casa = {str(it.get("id")): it.get("why", "") for it in itens
                if it.get("id") is not None}

    # ── 1) o par (dono, gabarito) por item ─────────────────────────────────
    por_item = defaultdict(list)
    for r in labels:
        rid = str(r.get("id") or "")
        if rid:
            por_item[rid].append(r)

    concord = Counter()
    diverg = Counter()
    contestados = []
    for rid, rs in por_item.items():
        for r in rs:
            key = norm(r.get("key"))
            ans = norm(r.get("answer"))
            if key not in LEVELS:
                continue          # item real (capturado): nao ha gabarito
            if ans == key:
                concord[key] += 1
            else:
                diverg[key] += 1
                contestados.append({
                    "id": rid,
                    "dono": ans, "gabarito": key,
                    "classe": key,
                    "why_casa": why_casa.get(rid, ""),
                    "why_dono": r.get("why_dono") or "",
                    "contexto": (r.get("context") or "")[:160],
                })

    # ── 2) a instabilidade do proprio dono (o teto real) ────────────────────
    instaveis = []
    for rid, rs in por_item.items():
        respostas = [norm(r.get("answer")) for r in rs]
        if len(respostas) > 1 and len(set(respostas)) > 1:
            instaveis.append({"id": rid, "respostas": respostas,
                              "why_casa": why_casa.get(rid, "")})

    # ── 3) as frases do rubric a consertar, em ordem de quanto custam ───────
    # cada `why` da casa e' a justificativa do gabarito; quantos labels ela
    # afeta e quantos o dono contestou = quanto vale consertar a frase.
    por_why = defaultdict(lambda: {"labels": 0, "contestados": 0, "classes": set(),
                                    "exemplo": ""})
    for rid, rs in por_item.items():
        w = why_casa.get(rid, "")
        if not w:
            continue
        for r in rs:
            key = norm(r.get("key"))
            if key not in LEVELS:
                continue
            d = por_why[w]
            d["labels"] += 1
            d["classes"].add(key)
            if norm(r.get("answer")) != key:
                d["contestados"] += 1
            if not d["exemplo"]:
                d["exemplo"] = (r.get("context") or "")[:120]

    frases = []
    for w, d in por_why.items():
        frases.append({
            "porque_da_casa": w,
            "labels": d["labels"],
            "contestados": d["contestados"],
            "taxa_de_contencao": round(d["contestados"] / max(1, d["labels"]), 3),
            "classes": sorted(d["classes"]),
            "exemplo": d["exemplo"],
        })
    frases.sort(key=lambda f: (-f["contestados"], -f["labels"]))

    # ── 4) a classe mais ambigua ────────────────────────────────────────────
    por_classe = {}
    for lv in LEVELS:
        n = concord[lv] + diverg[lv]
        if n:
            por_classe[lv] = {
                "classe": LEVEL_NAMES[lv],
                "julgados": n,
                "concordancia": concord[lv],
                "divergencias": diverg[lv],
                "ambiguidade": round(diverg[lv] / n, 3),
            }

    res = {
        "registro": args.labels,
        "labels": len(labels),
        "itens_distintos": len(por_item),
        "com_gabarito": sum(concord.values()) + sum(diverg.values()),
        "ambiguidade_por_classe": por_classe,
        "contestados": contestados,
        "instaveis": instaveis,
        "frases_a_consertar": frases,
    }

    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(res, ensure_ascii=False, indent=1))
        print(f"detalhe: {args.json}")

    print(f"registro: {args.labels}")
    print(f"labels: {len(labels)} | itens distintos: {len(por_item)} | "
          f"com gabarito (para comparar): {res['com_gabarito']}")
    if res["com_gabarito"]:
        tc = sum(concord.values())
        td = sum(diverg.values())
        print(f"\n1) AMBIGUIDADE POR CLASSE (dono x gabarito): "
              f"{tc} concordam, {td} contestam "
              f"({td/max(1,tc+td):.0%} de ambiguidade)")
        for lv, v in sorted(por_classe.items(),
                            key=lambda kv: -kv[1]["ambiguidade"]):
            print(f"   nivel {lv} ({v['classe']:22s}) "
                  f"julgados={v['julgados']:<3} "
                  f"ambiguidade={v['ambiguidade']:.0%} "
                  f"({v['divergencias']}/{v['julgados']})")
    if instaveis:
        print(f"\n2) O DONO FOI INSTAVEL EM {len(instaveis)} item(ns) "
              f"(o teto real da delegacao):")
        for it in instaveis[:6]:
            print(f"   {it['id']}: respostas {it['respostas']}")
    else:
        print("\n2) O DONO AINDA NAO FOI INSTAVEL EM NENHUM ITEM "
              "(falta julgar o mesmo item duas vezes)")
    print("\n3) AS FRASES DO RUBRIC PARA CONSERTAR (ordem de quanto custam):")
    if not frases:
        print("   (nenhuma label com gabarito ainda)")
    for f in frases[:6]:
        print(f"   [{f['contestados']}/{f['labels']} contestados, "
              f"taxa {f['taxa_de_contencao']:.0%}] {f['porque_da_casa'][:88]}")
        print(f"       classes: {f['classes']}")
    if contestados:
        print("\n4) OS ITENS CONTESTADOS (o porque da casa x o do dono):")
        for c in contestados[:6]:
            print(f"   {c['id']}: casa={c['gabarito']} dono={c['dono']}")
            print(f"       casa : {c['why_casa'][:92]}")
            print(f"       dono : {c['why_dono'][:92] or '(sem por que ainda)'}")
    print("\nO que a casa faz com isto: consertar a frase do rubric vale para "
          "TODOS os labels futuros (o dono nao tem tempo para refazer "
          "julgamento) — e o desacordo e' o sinal, nao o ruido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
