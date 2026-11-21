#!/usr/bin/env python3
"""judgment-dataset.py — as labels do dono viram dataset no formato do Laya.

POR QUE (13/11/2026, coord-naming): o dono vai treinar o Laya para responder
por procuracao (o modelo responde, treinado com as judgments DELE). O repo
`mt5` ja tem o pipeline de treino do Laya, com o dataset no formato
`{"type": "choice", "state": ..., "question": ..., "options": {...},
"answer": ...}` — e um julgamento de relevancia e' EXATAMENTE um choice de 4
opcoes (Highly / Moderately / Slightly / Not Relevant). : nao precisa de
treinador novo: as labels viram dataset no formato que o pipeline do dono ja
consome.

O QUE ESTE SCRIPT FAZ:
  1) le as labels do dono (data/judgments/labels.jsonl, o formato de
     data/judgments/SCHEMA.md) e os itens de pratica (uhrs-practice-items);
  2) escreve train.jsonl / test.jsonl / calib.jsonl no FORMATO DO LAYA;
  3) garante ZERO LEAKAGE: um id so pode estar em um dos tres arquivos (o
     held-out do dono e' lido de um arquivo separado e NAO entra no treino);
  4) avisa se a distribuicao das classes esta torta (um modelo que so viu
     "3" aprende um prior, nao o rubric).

O QUE ELE NAO FAZ: treinar (o treino e' o pipeline do dono, no Kaggle, com o
base em HF — o router serve GGUF, e LoRA nao se treina em GGUF), e nem servir:
depois do treino o adapter vira GGUF (benchmarks/voice/convert-gate-lora.sh, o
mesmo script da casa) e o bench mede a concordancia (scripts/judgment-bench.py).

USO
    python3 scripts/judgment-dataset.py --out data/judgments/laya
    python3 scripts/judgment-dataset.py --out data/judgments/laya \
        --heldout data/judgments/heldout.jsonl
    python3 scripts/judgment-dataset.py --self-test
"""
import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "judgments"
LABELS = DATA / "labels.jsonl"
ITEMS = DATA / "uhrs-practice-items.jsonl"

QUESTION = "How relevant is the page for the query?"
OPTIONS = {
    "HIGHLY": "Highly Relevant: the page answers the query directly and "
              "completely, and it is the best possible result",
    "MODERATELY": "Moderately Relevant: the page answers the query and is a "
                  "good page, but a better result exists",
    "SLIGHTLY": "Slightly Relevant: the page is on the same topic and useful "
                "in part, but it does not answer the query",
    "NOT": "Not Relevant: the page does not answer the query and does not "
           "help the user get to the answer",
}
# o level (0 a 3) -> o rotulo do dataset
LEVEL_TO_KEY = {"3": "HIGHLY", "2": "MODERATELY", "1": "SLIGHTLY", "0": "NOT"}


def load_jsonl(path):
    rows = []
    p = Path(path)
    if not p.is_file():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rows.append(json.loads(line))
    return rows


def split_context(context):
    """O contexto do dono vem como 'Query: ...\\nPage: ...\\nAnswer by the
    owner: ...'. O dataset do Laya separa state (o contexto) e answer."""
    state = context
    for marker in ("\nAnswer by the owner:", "\nResposta do dono:"):
        if marker in context:
            state = context.split(marker, 1)[0]
            break
    state = state.replace("Query:", "Query:").strip()
    return state


def to_laya(row):
    """Uma label -> um item do formato do Laya.

    (21/11) O `state` carrega o RACIOCINIO DO DONO (o `why_dono`), nao so o
    texto. Sem isso o adapter aprende o rotulo e nao a decisao: treinar assim
    e' o mesmo que treinar no gabarito, que e' o reward hacking por rubric
    que o acervo mede (arXiv 2607.28802). E o gabarito (o `key`) e' o
    porque DE QUEM ESCREVEU o item — nenhum dos dois entra no state, senao o
    modelo aprenderia a copiar a resposta da casa.
    """
    answer = str(row.get("answer", "")).strip()
    key = LEVEL_TO_KEY.get(answer)
    if key is None:
        return None
    state = split_context(row.get("context", ""))
    why = str(row.get("why_dono") or "").strip()
    if why:
        state = f"{state}\nThe owner's reason: {why}"
    return {"type": "choice",
            "state": state,
            "question": QUESTION,
            "options": dict(OPTIONS),
            "answer": key,
            "_id": row.get("id", "")}


def write_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def build(out_dir, heldout_path, seed=7, test_ratio=0.25, calib=8):
    labels = load_jsonl(LABELS)
    items = load_jsonl(ITEMS)
    # os itens de pratica entram com o gabarito como label (o dono ainda nao
    # respondeu, mas o gabarito e' a resposta certa segundo o rubric)
    for it in items:
        labels.append({"id": "prat-" + it["id"],
                       "context": f"Query: {it['query']}\nPage: {it['snippet']}",
                       "answer": it["answer"],
                       "source": "practice-key"})

    heldout_ids = set()
    heldout = []
    if heldout_path:
        for r in load_jsonl(heldout_path):
            heldout.append(r)
            if r.get("id"):
                heldout_ids.add(str(r["id"]))

    # ZERO LEAKAGE: o que esta no held-out NUNCA entra no treino
    train_src = [r for r in labels if str(r.get("id")) not in heldout_ids]
    laya = [x for x in (to_laya(r) for r in train_src) if x]
    held_laya = [x for x in (to_laya(r) for r in heldout) if x]

    # (14/11) O CORTE E' POR GRUPO DE ITEM, NAO POR LINHA. O dono foi
    # instruido a julgar alguns itens DUAS VEZES (e' assim que se mede a
    # repetibilidade dele = o teto real da delegacao, base arXiv
    # 2510.07978). Cortando por linha, as duas respostas do mesmo item
    # podiam cair em arquivos diferentes (uma no treino, outra no teste) =
    # leakage, que e' o defeito que o proprio script promete evitar.
    groups = {}
    for row in laya:
        groups.setdefault(str(row.get("_id")), []).append(row)
    gids = list(groups)
    rng = random.Random(seed)
    rng.shuffle(gids)

    def take_groups(pool, n_groups):
        """Pega n GRUPOS inteiros do pool (o item vai inteiro)."""
        chosen, taken = [], 0
        for gid in pool:
            if taken >= n_groups:
                break
            chosen.append(gid)
            taken += len(groups[gid])
        return chosen, pool[len(chosen):]

    n_test = max(1, int(len(laya) * test_ratio)) if len(laya) > 3 else 0
    # (13/11) com dataset pequeno (12 itens de pratica) o calib de 8 deixaria
    # 1 item de treino: o corte tem de se adaptar ao tamanho.
    cal_n = min(calib, max(0, len(laya) // 5))
    # calib: primeiro (em grupos inteiros)
    cal_groups, rest_gids = take_groups(gids, cal_n)
    cal = [row for gid in cal_groups for row in groups[gid]]
    # test: em seguida, sempre deixando pelo menos um grupo para o treino
    n_test_groups = max(1, int(round(len(rest_gids) * test_ratio))) \
        if len(rest_gids) > 1 else 0
    test_groups, rest_gids = take_groups(rest_gids, n_test_groups)
    test = [row for gid in test_groups for row in groups[gid]]
    # train: o que sobrou
    train = [row for gid in rest_gids for row in groups[gid]]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "train.jsonl", train)
    write_jsonl(out / "test.jsonl", test)
    write_jsonl(out / "calib.jsonl", cal)
    if held_laya:
        write_jsonl(out / "heldout.jsonl", held_laya)

    # saneza: sem ids repetidos entre os arquivos
    ids = {"train": {r.get("_id") for r in train},
           "test": {r.get("_id") for r in test},
           "calib": {r.get("_id") for r in cal},
           "heldout": {r.get("_id") for r in held_laya}}
    overlaps = []
    keys = list(ids)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            common = ids[a] & ids[b]
            if common:
                overlaps.append((a, b, sorted(common)[:5]))

    dist = Counter(r["answer"] for r in train)
    print(f"labels lidas: {len(labels)} | items de pratica: {len(items)}")
    print(f"train={len(train)} test={len(test)} calib={len(cal)} "
          f"heldout={len(held_laya)}")
    print(f"distribuicao do treino: {dict(dist)}")
    if dist and len(dist) == 1:
        print("AVISO: o treino tem uma classe so => o modelo aprenderia um "
              "prior, nao o rubric. Colete mais exemplos das outras classes.")
    print(f"vazamento entre arquivos: {overlaps if overlaps else 'nenhum'}")
    return out, overlaps


def make_heldout(labels, n, seed=7, out_path=None, force=False):
    """Cria o held-out: ids das labels REAIS do dono, estratificado por classe.

    (14/11) O held-out nao existia e nao tinha caminho de criacao (o
    SCHEMA.md mandava o dono escrever a mao — invitation para errar e
    esquecer). Aqui ele e' criado de forma deterministica (seed), estratificado
    pela classe (para o held-out ter a mesma mistura do treino, senao o F1
    por nivel mede uma classe que o modelo nunca viu), e SO das labels reais
    do dono: os itens de pratica sinteticos (source='practice-key') ficam de
    fora, porque eles servem para treino, nao para medir generalizacao.

    O `build()` ja exclui os ids do held-out do treino, entao o held-out e'
    honesto POR CONSTRUCAO: nao existe caminho em que o arquivo medido entre
    no treino.
    """
    real = [r for r in labels
            if r.get("source") != "practice-key"
            and not str(r.get("id", "")).startswith("prat-")
            and str(r.get("answer", "")) in LEVEL_TO_KEY]
    if not real:
        return None, "sem labels reais do dono (as de pratica nao contam)"
    by_class = {}
    for r in real:
        by_class.setdefault(str(r.get("answer")), []).append(r)
    rng = random.Random(seed)
    for key in by_class:
        rng.shuffle(by_class[key])
    # round-robin pelas classes: garante presenca de todas
    picked, cursor = [], {k: 0 for k in by_class}
    keys = sorted(by_class)
    while len(picked) < n and any(cursor[k] < len(by_class[k]) for k in keys):
        for k in keys:
            if len(picked) >= n:
                break
            if cursor[k] < len(by_class[k]):
                picked.append(by_class[k][cursor[k]])
                cursor[k] += 1
    out = Path(out_path or (DATA / "heldout.jsonl"))
    if out.exists() and not force:
        return None, (f"{out} ja existe (use --force para sobrescrever; "
                      f"ele guarda as labels que o dono ja julgou)")
    out.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(out, picked)
    dist = Counter(str(r.get("answer")) for r in picked)
    return out, (f"held-out criado: {len(picked)} itens | "
                 f"distribuicao {dict(dist)} | {out}")


def self_test():
    """Prova a conversao: uma label vira item do formato Laya, o held-out nao
    vaza para o treino e a classe torta avisa."""
    tmp = Path("/tmp/opencode/judgment-ds-selftest")
    tmp.mkdir(parents=True, exist_ok=True)
    held = tmp / "heldout.jsonl"
    write_jsonl(held, [{"id": "h1",
                        "context": "Query: q\nPage: p\nAnswer by the owner: 2",
                        "answer": "2"}])
    # duas labels no rotulo do Laya + uma no held-out
    fake_labels = tmp / "labels.jsonl"
    write_jsonl(fake_labels, [
        {"id": "a1", "context": "Query: q1\nPage: p1", "answer": "3"},
        {"id": "a2", "context": "Query: q2\nPage: p2", "answer": "0"},
        {"id": "a3", "context": "Query: q3\nPage: p3", "answer": "3"},
    ])
    global LABELS, ITEMS
    old_labels, old_items = LABELS, ITEMS
    LABELS, ITEMS = fake_labels, tmp / "vazio.jsonl"
    try:
        out, overlaps = build(tmp / "out", held, test_ratio=0.34, calib=1)
    finally:
        LABELS, ITEMS = old_labels, old_items
    train = load_jsonl(out / "train.jsonl")
    test = load_jsonl(out / "test.jsonl")
    calib = load_jsonl(out / "calib.jsonl")
    assert train, "train vazio"
    assert all(r["type"] == "choice" for r in train), "tipo errado"
    assert all(set(r["options"]) == set(OPTIONS) for r in train), "opcoes erradas"
    assert all(r["answer"] in OPTIONS for r in train), "resposta fora das opcoes"
    assert not overlaps, f"vazamento: {overlaps}"
    ids = {r["_id"] for r in train}
    assert "h1" not in ids, "o held-out entrou no treino"
    # (14/11) o mesmo item julgado duas vezes tem de ficar NO MESMO arquivo
    # (leakage): os ids de cada arquivo nao podem se cruzar
    per_file = [{r["_id"] for r in rows_} for rows_ in (train, test, calib)]
    for i, a in enumerate(per_file):
        for b in per_file[i + 1:]:
            assert not (a & b), f"item repetido em dois arquivos: {a & b}"

    # (14/11) prova do caso que motivou o corte: o mesmo item julgado duas
    # vezes (o dono medindo a propria repetibilidade) fica no mesmo arquivo.
    tmp2 = Path("/tmp/opencode/judgment-ds-selftest2")
    tmp2.mkdir(parents=True, exist_ok=True)
    write_jsonl(tmp2 / "heldout.jsonl", [])
    dup = tmp2 / "labels.jsonl"
    write_jsonl(dup, [
        {"id": "r1", "context": "Query: q\nPage: p", "answer": "3"},
        {"id": "r1", "context": "Query: q\nPage: p", "answer": "2"},
        {"id": "r2", "context": "Query: q2\nPage: p2", "answer": "0"},
        {"id": "r3", "context": "Query: q3\nPage: p3", "answer": "1"},
    ])
    old_labels, old_items = LABELS, ITEMS
    LABELS, ITEMS = dup, tmp2 / "vazio.jsonl"
    try:
        out2, ov2 = build(tmp2 / "out", tmp2 / "heldout.jsonl", test_ratio=0.34,
                          calib=1)
    finally:
        LABELS, ITEMS = old_labels, old_items
    assert not ov2, f"vazamento com repeticao: {ov2}"
    where = {}
    for fname in ("train.jsonl", "test.jsonl", "calib.jsonl"):
        for r in load_jsonl(out2 / fname):
            where.setdefault(str(r["_id"]), set()).add(fname)
    dup_files = where.get("r1", set())
    assert len(dup_files) == 1, f"o item repetido foi dividido: {dup_files}"
    print("SELF-TEST ok: formato Laya, held-out fora do treino, sem vazamento, "
          "opcoes e respostas validas, e o item julgado duas vezes fica no "
          "mesmo arquivo")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DATA / "laya"))
    ap.add_argument("--heldout", default=str(DATA / "heldout.jsonl"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--test-ratio", type=float, default=0.25)
    ap.add_argument("--calib", type=int, default=8)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--make-heldout", type=int, default=0,
                    help="cria o held-out com N labels REAIS do dono "
                         "(estratificado por classe, deterministico)")
    ap.add_argument("--force", action="store_true",
                    help="sobrescreve o held-out existente")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.make_heldout:
        labels = load_jsonl(LABELS)
        out, msg = make_heldout(labels, args.make_heldout, args.seed,
                                force=args.force)
        print(msg)
        if out is None:
            return 1
        print("agora: python3 scripts/judgment-dataset.py  (o build ja exclui "
              "esses ids do treino) e python3 scripts/judgment-bench.py "
              "--heldout data/judgments/heldout.jsonl")
        return 0
    out, overlaps = build(args.out, args.heldout, args.seed, args.test_ratio,
                          args.calib)
    if overlaps:
        print("ERRO: vazamento entre os arquivos; nao treine com isso.",
              file=sys.stderr)
        return 1
    print(f"\ndataset do Laya em: {out}")
    print("proximo passo (o pipeline do dono): treinar com esse dataset, "
          "converter o adapter (benchmarks/voice/convert-gate-lora.sh), servir "
          "e medir a concordancia (scripts/judgment-bench.py --model <url>).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
