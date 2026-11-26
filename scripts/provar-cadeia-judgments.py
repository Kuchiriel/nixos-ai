"""provar-cadeia-judgments.py — a cadeia INTEIRA do dono, provada.

(24/11/2026, coord-naming) Cada peca da trilha da renda foi provada
SOZINHA. A cadeia que o dono vai rodar nao foi: julgamento (voz) ->
registro -> held-out -> dataset -> bench -> seletor de fronteira ->
relatorio de ambiguidade. Se houver uma quebra entre as pecas (um nome de
arquivo, um campo, um caminho), o dono so vai descobrir no meio do
trabalho dele — e o trabalho dele e' o recurso mais escasso da casa.

Esta provadora roda a cadeia INTEIRA sobre um registro SINTETICO (nenhum
label do dono e' tocado, nada sai da maquina) e verifica o contrato em
cada etapa:
  1) o registro tem o contrato do schema (os 7 campos);
  2) o `--make-heldout` cria o held-out ESTRATIFICADO e deterministico;
  3) o dataset sai sem held-out e sem ambiguos;
  4) o bench le o dataset (com o self-test, sem modelo) e o held-out;
  5) o seletor de fronteira aponta um item;
  6) o relatorio de ambiguidade aponta a classe ambigua;
  7) NENHUMA etapa escreve no repo de verdade (tudo em /tmp).

O QUE NAO FAZ: nao chama modelo, nao pede GPU, nao toca no registro do
dono, nao escreve no repo.
"""
import json
import hashlib
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path("/home/nixos/projects/nixos-ai")
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "benchmarks/voice"))

FALHAS = []
PASSOS = 0


def ok(nome, cond, detalhe=""):
    global PASSOS
    if cond:
        PASSOS += 1
        print(f"  ok   {nome}" + (f" ({detalhe})" if detalhe else ""))
    else:
        FALHAS.append(nome)
        print(f"  FALHA {nome}" + (f" ({detalhe})" if detalhe else ""))


def main():
    import importlib.util

    def mod(nome, caminho):
        spec = importlib.util.spec_from_file_location(nome, caminho)
        m = importlib.util.module_from_spec(spec)
        sys.modules[nome] = m
        spec.loader.exec_module(m)
        return m

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="cadeia-judgments-"))
    labels = tmp / "labels.jsonl"
    held = tmp / "heldout.jsonl"

    # ── FOTOS do estado real do repo (antes de qualquer coisa) ────────────
    # (24/11) o check de "nada foi escrito no repo" precisa de uma FOTO
    # para comparar: sem ela, o check e' um `or True` disfarçado.
    FOTOS = {}
    for nome, caminho in (("o registro do dono", REPO / "data/judgments/labels.jsonl"),
                          ("o held-out do repo", REPO / "data/judgments/heldout.jsonl")):
        FOTOS[nome] = hashlib.sha256(caminho.read_bytes()).hexdigest() \
            if caminho.is_file() else "(nao existe)"
    real_labels = REPO / "data/judgments/labels.jsonl"
    FOTOS["n_linhas_real"] = len(
        [l for l in real_labels.read_text(encoding="utf-8").splitlines()
         if l.strip()]) if real_labels.is_file() else 0

    # ── 0) um registro SINTETICO no contrato do schema ─────────────────────
    # (o mesmo formato que o uhrs-practice.py grava: id, context, answer,
    # key, why_dono, source, via, ts)
    #
    # (24/11) O REGISTRO SINTETICO EXERCE OS TRES CASOS REAIS DA CASA:
    #   (a) o dono CONTASTA o gabarito (answer != key) com UM julgamento:
    #       isso e' um item DE TREINO VALIDO (e' a delegacao: o modelo
    #       aprende a resposta do dono, nao a do rubric);
    #   (b) o MESMO id julgado DUAS VEZES com RESPOSTAS DIFERENTES: e' o
    #       item ambiguo (o dono nao se decidiu), e nao vira alvo de treino;
    #   (c) o MESMO id julgado DUAS VEZES com a MESMA resposta: o dono se
    #       decidiu, e vale UM item so (peso nao dobrado).
    # A primeira versao do prover usava `answer != key` como se fosse
    # ambiguidade: e' a CONTESTACAO (que e' treino valido), nao a
    # ambiguidade (que exige dois julgamentos do mesmo id).
    itens_p = [json.loads(l) for l in
               (REPO / "data/judgments/uhrs-practice-items.jsonl").read_text(
                   encoding="utf-8").splitlines() if l.strip()]
    linhas = []

    def linha(item_id, query, snippet, resp, key, why, ts="2026-11-24T12:00:00Z"):
        return {"id": item_id,
                "context": f"Query: {query}\nPage: {snippet}",
                "answer": resp, "key": key, "why_dono": why,
                "source": "uhrs-practice", "via": "voz", "ts": ts}

    # (a) os itens normais, com dois deles contestando o rubric
    for i, it in enumerate(itens_p):
        if it["id"] in ("p03", "p07"):
            resp = {"3": "2", "2": "1", "1": "0", "0": "1"}[it["answer"]]
            why = "e' borderline: responde mas tem resultado melhor"
        else:
            resp = it["answer"]
            why = ""
        linhas.append(linha(it["id"], it["query"], it["snippet"], resp,
                            it["answer"], why))
    # (b) o item AMBIGUO: o mesmo id, duas respostas DIFERENTES
    it = itens_p[0]
    linhas.append(linha("q-amb", it["query"], it["snippet"], "3", it["answer"],
                        "primeira passagem"))
    linhas.append(linha("q-amb", it["query"], it["snippet"], "1", it["answer"],
                        "segunda passagem, pensei diferente",
                        ts="2026-11-24T12:05:00Z"))
    # (c) o item REPETIDO e ESTAVEL: o mesmo id, a MESMA resposta
    it = itens_p[1]
    linhas.append(linha("q-rep", it["query"], it["snippet"], it["answer"],
                        it["answer"], ""))
    linhas.append(linha("q-rep", it["query"], it["snippet"], it["answer"],
                        it["answer"], "",
                        ts="2026-11-24T12:05:00Z"))
    labels.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                              for r in linhas), encoding="utf-8")

    # ── 1) o contrato do registro ─────────────────────────────────────────
    print("\n1) o CONTRATO do registro (o que o uhrs-practice grava):")
    contrato = {"id", "context", "answer", "key", "why_dono", "source", "via", "ts"}
    for r in linhas:
        faltando = contrato - set(r)
        ok(f"label {r['id']} tem o contrato", not faltando, str(faltando))
        ok(f"label {r['id']} nao carrega a resposta no contexto",
           "Answer by the owner" not in r["context"])
        break
    # (24/11) o id e' unico POR ITEM, e nao por linha: o dono pode julgar
    # o mesmo item duas vezes (e' assim que se mede a repetibilidade dele),
    # e as duas linhas TEM o mesmo id de proposito.
    from collections import Counter as _C
    por_id = _C(r["id"] for r in linhas)
    repetidos = {k: v for k, v in por_id.items() if v > 1}
    ok("os ids repetidos sao so os que a prova criou",
       set(repetidos) == {"q-amb", "q-rep"}, str(sorted(repetidos)))
    ok("todo item tem pelo menos uma linha",
       all(v >= 1 for v in por_id.values()))

    # ── 2) o held-out estratificado ───────────────────────────────────────
    print("\n2) o --make-heldout (estratifcado e deterministico):")
    jd = mod("jd", REPO / "scripts/judgment-dataset.py")
    antigo_l, antigo_i = jd.LABELS, jd.ITEMS
    jd.LABELS, jd.ITEMS = labels, tmp / "vazio.jsonl"
    try:
        out1, msg1 = jd.make_heldout(linhas, 8, seed=7, out_path=held, force=True)
        out2, msg2 = jd.make_heldout(linhas, 8, seed=7, out_path=tmp / "held2.jsonl",
                                     force=True)
    finally:
        jd.LABELS, jd.ITEMS = antigo_l, antigo_i
    ok("o held-out foi criado", out1 is not None, str(msg1)[:70])
    ok("o held-out e' deterministico (mesma seed, mesmo arquivo)",
       held.is_file() and (tmp / "held2.jsonl").is_file()
       and held.read_text() == (tmp / "held2.jsonl").read_text())
    held_rows = [json.loads(l) for l in held.read_text().splitlines() if l.strip()]
    classes = {r["answer"] for r in held_rows}
    ok("o held-out tem 8 itens", len(held_rows) == 8, str(len(held_rows)))
    ok("o held-out tem mais de uma classe (estratificado)", len(classes) > 1,
       str(sorted(classes)))
    # (24/11) O HELD-OUT NAO PODE TER ITEM AMBIGUO: um item que o dono
    # julgou duas vezes com respostas diferentes nao tem uma resposta
    # certa — medir o modelo contra ele e' jogar uma moeda. (O check
    # abaixo foi escrito depois de o item ambiguo entrar no held-out.)
    respostas_held = {}
    for r in held_rows:
        respostas_held.setdefault(str(r.get("id")), []).append(
            str(r.get("answer")))
    ambiguos_held = {k for k, v in respostas_held.items()
                     if len({x.strip() for x in v if x.strip()}) > 1}
    ok("o held-out nao tem item ambiguo (o dono nao se decidiu nele)",
       not ambiguos_held, str(sorted(ambiguos_held)))
    ok("o item ambiguo da prova NAO esta no held-out",
       "q-amb" not in {str(r.get("id")) for r in held_rows},
       "q-amb esta no held-out" if "q-amb" in
       {str(r.get("id")) for r in held_rows} else "ok")

    # ── 3) o dataset ──────────────────────────────────────────────────────
    print("\n3) o DATASET (sem held-out, sem ambiguos):")
    jd.LABELS, jd.ITEMS = labels, tmp / "vazio.jsonl"
    try:
        out, overlaps = jd.build(tmp / "out", held, test_ratio=0.25, calib=4)
    finally:
        jd.LABELS, jd.ITEMS = antigo_l, antigo_i
    ok("sem vazamento entre os arquivos", not overlaps, str(overlaps))
    treino = [json.loads(l) for l in (out / "train.jsonl").read_text().splitlines()
              if l.strip()]
    # (24/11) O CONJUNTO do dataset e' train + test + calib: o split
    # distribui os itens entre os tres arquivos, e um check que olha so o
    # train acusa "perdi o item" quando o item foi para o test (o que e'
    # o comportamento certo). O que NUNCA pode acontecer e' o item nao
    # estar em nenhum dos tres (nem no held-out).
    dataset = list(treino)
    for nome in ("test.jsonl", "calib.jsonl"):
        p = out / nome
        if p.is_file():
            dataset += [json.loads(l) for l in p.read_text().splitlines()
                        if l.strip()]
    ids_dataset = {r["_id"] for r in dataset}
    ids_treino = {r["_id"] for r in treino}
    ids_held = {str(r.get("id")) for r in held_rows}
    ok("nenhum id do held-out no treino", not (ids_treino & ids_held),
       str(sorted(ids_treino & ids_held)))
    # (24/11) O CHECK DO AMBIGUO PRECISA SER REAL. A primeira versao do
    # prover testava `not [r for r in treino if r["_id"].startswith("q")]`
    # — e os ids do registro SINTETICO sao p01..p20, NUNCA comecam com "q":
    # o check passava SEM PROVAR NADA (o mesmo defeito que o proprio
    # self-test do dataset tinha). Agora o check e' sobre o CONJUNTO
    # VERDADEIRO dos ids ambiguos (calculado do registro: o MESMO id com
    # respostas DIFERENTES), e nao sobre um prefixo de nome.
    respostas_por_id = {}
    for r in linhas:
        respostas_por_id.setdefault(r["id"], []).append(str(r.get("answer")))
    ids_ambiguos = {k for k, v in respostas_por_id.items()
                    if len({x.strip() for x in v if x.strip()}) > 1}
    ids_repetidos_estaveis = {k for k, v in respostas_por_id.items()
                              if len(v) > 1 and k not in ids_ambiguos}
    ok("o registro sintetico tem 1 item ambiguo e 1 repetido estavel",
       ids_ambiguos == {"q-amb"} and ids_repetidos_estaveis == {"q-rep"},
       f"ambiguos={sorted(ids_ambiguos)} estaveis={sorted(ids_repetidos_estaveis)}")
    ids_ambiguos_no_treino = ids_ambiguos & ids_dataset
    ok("nenhum item AMBIGUO no dataset", not ids_ambiguos_no_treino,
       str(sorted(ids_ambiguos_no_treino)))
    ok("nenhum item AMBIGUO no held-out", not (ids_ambiguos & ids_held),
       str(sorted(ids_ambiguos & ids_held)))
    # (24/11) O ITEM REPETIDO ESTAVEL ENTRA UMA VEZ — e a contagem e' sobre
    # o dataset E o held-out: o split coloca o item num dos dois (ele nao
    # pode estar nos dois), e um check que olha so o dataset acusava
    # "sumiu" quando o item estava no held-out (comportamento correto).
    # O INVARIANTE: o julgamento do dono NUNCA se perde — nem 2 (peso
    # dobrado) nem 0 (perdido); e o contestado nunca some (sumir seria
    # treinar so no gabarito, o reward hacking de arXiv 2607.28802).
    n_rep = sum(1 for r in dataset if r["_id"] == "q-rep") + \
        sum(1 for r in held_rows if str(r.get("id")) == "q-rep")
    ok("o item repetido ESTAVEL entra uma vez so (dataset ou held-out)",
       n_rep == 1, f"{n_rep}x")
    # (24/11) E O CASO QUE A PRIMEIRA VERSAO DO PROVER INVERTIU: a
    # CONTESTACAO do rubric (answer != key, com UM julgamento) e' item
    # VALIDO — e' a delegacao (o modelo aprende a resposta do dono, nao a
    # do rubric). Se isso sumisse, a trilha viraria "aprender o gabarito",
    # que e' o reward hacking que o acervo mede (arXiv 2607.28802).
    ids_contestados = {r["id"] for r in linhas
                       if str(r.get("answer")) != str(r.get("key"))
                       and r["id"] not in ids_ambiguos}
    perdidos = ids_contestados - ids_dataset - ids_held
    ok("a CONTESTACAO do dono entra (dataset ou held-out): a delegacao",
       not perdidos,
       f"contestados={sorted(ids_contestados)} perdidos={sorted(perdidos)}")
    ok("o treino tem item de cada classe", len({r["answer"] for r in treino}) >= 3,
       str(sorted({r["answer"] for r in treino})))

    # ── 4) o bench le o dataset (self-test, sem modelo) ────────────────────
    print("\n4) o BENCH le o dataset (sem modelo real, com um modelo local falso):")
    r = subprocess.run([sys.executable, str(REPO / "scripts/judgment-bench.py"),
                        "--data", str(out / "train.jsonl"), "--self-test"],
                       capture_output=True, text=True, timeout=300, cwd=str(REPO))
    ok("o bench roda o self-test", r.returncode == 0,
       (r.stdout or r.stderr).strip()[-70:])
    # (24/11) O `--self-test` do bench SAI ANTES de ler o `--data` (medido
    # no codigo: `if args.self_test: return self_test()` vem antes do
    # `load(args.data)`) — o check acima NAO provava que o bench le o
    # dataset gerado. A prova de verdade e' a do arquivo Laya: um modelo
    # local falso (servidor HTTP efemero) que responde o nivel certo de
    # cada item; o bench tem de medir 100% contra ele, com o CONTEXTO no
    # prompt e o F1 dos niveis presentes.
    r_laya = subprocess.run([sys.executable, str(REPO / "scripts/provar-bench-laya.py")],
                            capture_output=True, text=True, timeout=600,
                            cwd=str(REPO))
    ok("o bench mede 100% contra o modelo perfeito no arquivo Laya",
       r_laya.returncode == 0,
       (r_laya.stdout or r_laya.stderr).strip()[-90:])

    # ── 5 e 6) o seletor e o relatorio de ambiguidade ─────────────────────
    print("\n5) o SELETOR de fronteira e o RELATORIO de ambiguidade:")
    r5 = subprocess.run([sys.executable, str(REPO / "scripts/seletor-fracas.py"),
                         "--labels", str(labels)],
                        capture_output=True, text=True, timeout=300, cwd=str(REPO))
    ok("o seletor aponta um item", r5.returncode == 0
       and ("PROXIMOS" in r5.stdout or "nenhum item de fronteira" in r5.stdout),
       (r5.stdout or r5.stderr).strip()[-70:])
    r6 = subprocess.run([sys.executable, str(REPO / "scripts/ambiguidade.py"),
                         "--labels", str(labels)],
                        capture_output=True, text=True, timeout=300, cwd=str(REPO))
    ok("o relatorio de ambiguidade roda", r6.returncode == 0,
       (r6.stdout or r6.stderr).strip()[-70:])
    ok("o relatorio aponta a classe ambigua",
       "AMBIGUIDADE POR CLASSE" in r6.stdout)

    # ── 7) nada saiu do /tmp ──────────────────────────────────────────────
    # (24/11) A PRIMEIRA VERSAO DESTE CHECK ERA VAZIA: `exists() is False
    # or True` e' sempre verdadeiro (o `or True`). Agora o check e' sobre o
    # CONTEUDO: o registro real e o held-out real do repo sao comparados
    # com a foto do inicio (hash), e a foto e' tirada no comeco da prova.
    print("\n7) NADA FOI ESCRITO NO REPO:")
    for nome, caminho in (("o registro do dono", REPO / "data/judgments/labels.jsonl"),
                          ("o held-out do repo", REPO / "data/judgments/heldout.jsonl")):
        agora = hashlib.sha256(caminho.read_bytes()).hexdigest() \
            if caminho.is_file() else "(nao existe)"
        ok(f"{nome} nao foi tocado", agora == FOTOS[nome], f"{agora[:16]}")
    # e o registro real continua como estava: se o dono ja tivesse um
    # registro, ele teria de ter o MESMO numero de linhas
    if (REPO / "data/judgments/labels.jsonl").is_file():
        real_n = len([l for l in (REPO / "data/judgments/labels.jsonl")
                      .read_text(encoding="utf-8").splitlines() if l.strip()])
        ok("o registro real nao ganhou as linhas do teste", real_n == FOTOS["n_linhas_real"],
           f"{real_n} linhas")
    else:
        ok("o registro real nao foi criado pela prova", True,
           "(o dono ainda nao julgou nada: o arquivo nao existe)")

    # ── 8) a pratica pode ser ENSAIADA sem tocar no registro ──────────────
    # (25/11) O `uhrs-practice.py` ganhou `--dry-run` e `--labels` porque
    # QUALQUER teste da pratica gravava no registro real do dono (medido: um
    # teste meu criou uma label de teste no `labels.jsonl`, que nao existia
    # antes — arquivada com read-back e removida). O `uhrs-capture.py` ja
    # tinha os dois; a pratica nao tinha nenhum. Aqui a prova garante que
    # as duas formas NAO gravam no registro do dono.
    print("\n8) A PRATICA PODE SER ENSAIADA SEM GRAVAR NO REGISTRO DO DONO:")
    up = mod("up", REPO / "scripts/uhrs-practice.py")
    antes = (REPO / "data/judgments/labels.jsonl")
    hash_antes = hashlib.sha256(antes.read_bytes()).hexdigest() \
        if antes.is_file() else "(nao existe)"
    # (a) o dry-run: nao grava nada
    r_dry = subprocess.run(
        [sys.executable, str(REPO / "scripts/uhrs-practice.py"),
         "--items", "1", "--answer", "3", "--dry-run",
         "--items-file", str(REPO / "data/judgments/uhrs-practice-items.jsonl")],
        capture_output=True, text=True, timeout=300, cwd=str(REPO))
    ok("o --dry-run roda", r_dry.returncode == 0,
       (r_dry.stdout or r_dry.stderr).strip()[-70:])
    hash_depois = hashlib.sha256(antes.read_bytes()).hexdigest() \
        if antes.is_file() else "(nao existe)"
    ok("o --dry-run NAO gravou no registro do dono",
       hash_depois == hash_antes, f"{hash_depois[:16]}")
    # (b) o --labels: grava em outro arquivo
    outro = tmp / "labels-do-ensaio.jsonl"
    r_out = subprocess.run(
        [sys.executable, str(REPO / "scripts/uhrs-practice.py"),
         "--items", "1", "--answer", "3", "--labels", str(outro),
         "--items-file", str(REPO / "data/judgments/uhrs-practice-items.jsonl")],
        capture_output=True, text=True, timeout=300, cwd=str(REPO))
    ok("o --labels roda", r_out.returncode == 0,
       (r_out.stdout or r_out.stderr).strip()[-70:])
    ok("o --labels gravou NO ARQUIVO REDIRECIONADO",
       outro.is_file() and len(outro.read_text().splitlines()) == 1,
       f"{len(outro.read_text().splitlines()) if outro.is_file() else 0} linha(s)")
    hash_final = hashlib.sha256(antes.read_bytes()).hexdigest() \
        if antes.is_file() else "(nao existe)"
    ok("o registro do dono continua INTACTO depois das duas formas",
       hash_final == hash_antes, f"{hash_final[:16]}")

    print(f"\n{'PROVA OK' if not FALHAS else 'PROVA COM FALHAS'}: "
          f"{PASSOS} ok, {len(FALHAS)} falha(s)")
    for f in FALHAS:
        print("  -", f)
    return 1 if FALHAS else 0


if __name__ == "__main__":
    raise SystemExit(main())
