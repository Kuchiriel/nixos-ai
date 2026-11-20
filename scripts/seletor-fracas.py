"""seletor-fracas.py — o proximo item que o dono deve julgar.

(20/11/2026, coord-naming) POR QUE ISTO EXISTE (a regra do acervo,
arXiv 2603.06865 "Counting on Consensus"): **desacordo e' informacao, nao
ruido**. Concordancia baixa nao e' evidencia de dado ruim — e' ambiguidade
de instrucao ou efeito de interface. E o paper do reward hacking por rubric
(2607.28802) diz o outro lado: treinar so no gabarito ensinaria o modelo
a agradar o rubric, e o dono precisa de um modelo que responda COMO ELE.

O PROBLEMA QUE ESTE SCRIPT RESOLVE: o orçamento de labels do dono e'
escasso (ele tem 50 dias sem beneficio e PCD). Julgar item espalhado
gasta o mesmo tempo e rende pouco. O item de maior valor e' o de FRONTEIRA
— onde o rubric (gabarito) e o dono divergem, ou onde a classe e' rara e o
modelo erra nela.

O QUE ELE FAZ, a partir de um unico dado — o registro unico do dono
(data/judgments/labels.jsonl):
  1) mede, por classe, o ACERTO DO DONO (o `key`/gabarito quando existe, e
     a repetibilidade quando o mesmo item foi julgado mais de uma vez);
  2) marca os itens de FRONTEIRA: as classes raras, as classes onde o
     dono discorda do rubric, e os itens onde o proprio dono mudou de
     resposta (a repetibilidade baixa = a fronteira mais informativa);
  3) propoe a ORDEM em que julgar (o de maior valor primeiro) e diz o
     porque de cada um;
  4) nao julga nada e nao inventa: so usa o que o dono ja respondeu.

O QUE ELE NAO FAZ: nao escolhe item pra o dono (ele mostra a ordem e o
porque; a decisao e' do dono), nao mexe no registro, nao chama modelo.
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
    return " ".join(str(s or "").lower().replace(".", " ").replace(",", " ")
                     .split())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", default=str(LABELS))
    ap.add_argument("--items", default=str(ITEMS))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limite", type=int, default=8,
                    help="quantos itens proposer (o dono e' PCD: a fila e' "
                         "curta e o porque vem junto)")
    args = ap.parse_args()

    labels = load(args.labels)
    itens = load(args.items)

    # ── 1) o que o dono ja respondeu, por item ─────────────────────────────
    por_id = defaultdict(list)
    for r in labels:
        rid = str(r.get("id") or "")
        if rid:
            por_id[rid].append(r)

    # a repetibilidade do dono (o teto real da delegacao, arXiv 2510.07978):
    # o mesmo item julgado mais de uma vez
    repetibilidade = {}
    for rid, rs in por_id.items():
        respostas = [norm(r.get("answer")) for r in rs]
        if len(respostas) > 1:
            iguais = len(set(respostas)) == 1
            repetibilidade[rid] = {"n": len(respostas), "estavel": iguais,
                                   "respostas": respostas}

    # ── 2) o gabarito dos itens de pratica ────────────────────────────────
    gabarito = {str(it.get("id")): str(it.get("answer")) for it in itens
                 if it.get("id") is not None}

    # ── 3) o acerto do dono por classe (quando ha gabarito) ────────────────
    acertos = Counter()
    por_classe = Counter()
    divergencias = []
    for rid, rs in por_id.items():
        key = gabarito.get(rid)
        for r in rs:
            ans = norm(r.get("answer"))
            if key is None:
                continue
            classe = key
            por_classe[classe] += 1
            if ans == norm(key):
                acertos[classe] += 1
            else:
                divergencias.append({
                    "id": rid, "dono": ans, "rubric": norm(key),
                    "classe": classe,
                    "why": next((it.get("why") for it in itens
                                 if str(it.get("id")) == rid), ""),
                })

    # ── 4) a ORDEM de valor: fronteira primeiro ─────────────────────────────
    # o valor de um item e' quanto ele ensina:
    #   - o dono discordou do rubric => e' a fronteira (2603.06865: o
    #     desacordo e' onde a instrucao esta ambigua)
    #   - a classe e' rara no conjunto => o modelo nunca viu o suficiente
    #   - o dono mudou de resposta no mesmo item => o item e' ambiguo por
    #    construction (e o training no gabarito ensinaria errado)
    lembretes = []
    for d in divergencias:
        lembretes.append({
            "id": d["id"], "motivo": "dono-divergiu-do-rubric",
            "classe": d["classe"],
            "detalhe": (f"dono disse {d['dono']} (nivel {d['classe']} = "
                        f"{LEVEL_NAMES.get(d['classe'], '?')}), o rubric diz "
                        f"{d['rubric']}"),
            "why": d["why"],
        })
    for rid, rep in repetibilidade.items():
        if not rep["estavel"]:
            lembretes.append({
                "id": rid, "motivo": "dono-mudou-de-resposta",
                "classe": gabarito.get(rid, "?"),
                "detalhe": (f"o mesmo item, {rep['n']} julgamentos, respostas "
                            f"{rep['respostas']} — o item e' ambiguo por "
                            f"construction"),
                "why": "",
            })
    # as classes raras do conjunto de itens (o modelo nao viu o suficiente)
    cont = Counter(str(it.get("answer")) for it in itens if it.get("answer"))
    for classe, n in sorted(cont.items(), key=lambda kv: kv[1]):
        if n <= 2:
            lembretes.append({
                "id": "", "motivo": "classe-rara-no-conjunto",
                "classe": classe,
                "detalhe": (f"a classe {classe} ({LEVEL_NAMES.get(classe,'?')}) "
                            f"tem {n} item(ns) no conjunto de pratica — o "
                            f"modelo quase nao viu essa fronteira"),
                "why": "",
            })

    # o cap: o dono e' PCD, a fila e' curta
    lembretes = lembretes[: args.limite]

    # ── 5) o estado do dono, por classe ────────────────────────────────────
    estado = {}
    for classe in sorted(set(list(por_classe) + list(gabarito.values()))):
        n = por_classe.get(classe, 0)
        a = acertos.get(classe, 0)
        estado[classe] = {
            "julgados": n,
            "acerto_do_dono": a,
            "taxa": round(a / n, 3) if n else None,
            "itens_no_conjunto": cont.get(classe, 0),
            "classe": LEVEL_NAMES.get(classe, classe),
        }

    saida = {
        "registro": args.labels,
        "labels_lidas": len(labels),
        "itens_distintos": len(por_id),
        "repetibilidade": repetibilidade,
        "estado_por_classe": estado,
        "divergencias": divergencias,
        "proximos": lembretes,
    }

    if args.json:
        print(json.dumps(saida, ensure_ascii=False, indent=1))
        return 0

    print(f"registro: {args.labels}")
    print(f"labels lidas: {len(labels)} | itens distintos: {len(por_id)}")
    if repetibilidade:
        est = sum(1 for r in repetibilidade.values() if r["estavel"])
        print(f"repetibilidade do dono: {est}/{len(repetibilidade)} itens "
              f"estaveis (o teto real da delegacao)")
    else:
        print("repetibilidade do dono: ainda nao medida (o mesmo item "
              "precisa ser julgado duas vezes)")
    print("\npor CLASSE (o julgamento do dono contra o rubric):")
    for classe, v in sorted(estado.items()):
        taxa = ("-" if v["taxa"] is None
                else f"{v['taxa']:.0%}")
        print(f"  nivel {classe} ({v['classe']:22s}) "
              f"julgados={v['julgados']:<3} acerto={taxa:>5} "
              f"itens_no_conjunto={v['itens_no_conjunto']}")
    print("\nPROXIMOS (a ordem que mais ensina por minuto de label do dono):")
    if not lembretes:
        print("  (nenhum item de fronteira ainda: falta o dono julgar os "
              "itens de pratica para o 'key' existir)")
    for i, l in enumerate(lembretes, 1):
        quem = l["id"] or "(conjunto)"
        print(f"  {i}. [{l['motivo']}] {quem}")
        print(f"     {l['detalhe']}")
        if l.get("why"):
            print(f"     porque: {l['why'][:110]}")
    print("\nO proximo item e' do dono (a decisao e' dele); o porque vem junto "
          "para o tempo dele render.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
