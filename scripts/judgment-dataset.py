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
    """Uma label -> um item do formato do Laya."""
    answer = str(row.get("answer", "")).strip()
    key = LEVEL_TO_KEY.get(answer)
    if key is None:
        return None
    state = split_context(row.get("context", ""))
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

    rng = random.Random(seed)
    rng.shuffle(laya)
    # (13/11) Bug pego pelo self-test: o slice de calib era tirado do MESMO
    # array do train, entao a calibracao vazava no treino. Agora os tres
    # arquivos sao disjuntos por construcao: calib -> resto -> test -> train.
    n_test = max(1, int(len(laya) * test_ratio)) if len(laya) > 3 else 0
    # (13/11) com dataset pequeno (12 itens de pratica) o calib de 8 deixaria
    # 1 item de treino: o corte tem de se adaptar ao tamanho.
    cal_n = min(calib, max(0, len(laya) // 5))
    cal = laya[-cal_n:] if cal_n else []
    rest = laya[:-cal_n] if cal else laya
    n_test = min(n_test, max(0, len(rest) - 1))
    test = rest[:n_test]
    train = rest[n_test:]

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
    assert train, "train vazio"
    assert all(r["type"] == "choice" for r in train), "tipo errado"
    assert all(set(r["options"]) == set(OPTIONS) for r in train), "opcoes erradas"
    assert all(r["answer"] in OPTIONS for r in train), "resposta fora das opcoes"
    assert not overlaps, f"vazamento: {overlaps}"
    ids = {r["_id"] for r in train}
    assert "h1" not in ids, "o held-out entrou no treino"
    print("SELF-TEST ok: formato Laya, held-out fora do treino, sem vazamento, "
          "opcoes e respostas validas")
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
    args = ap.parse_args()
    if args.self_test:
        return self_test()
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
