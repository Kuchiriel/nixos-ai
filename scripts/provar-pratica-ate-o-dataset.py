"""provar-pratica ate o dataset.py — o caminho REAL, do veredito falado ate o dataset.

(25/11/2026, coord-naming) A provadora da cadeia (provar-cadeia-judgments.py)
monta o registro SINTETICO na mao. Isso prova o dataset, mas nao prova o
comeco do caminho: o `uhrs-practice.py` speaking o veredito do dono, o
`record_label` gravando a linha no contrato e o `judgment-dataset.py`
consumindo essa linha.

Esta prova usa o `record_label` e o `DuplexVoice` REAIS (nada reimplementado),
com um log de voz falso (nada de microfone) e um arquivo de labels em /tmp
(nada no repo). A sequencia e' a do dono:
  1) o log de voz traz as transcricoes (o que o ASR teria escrito);
  2) o leitor devolve o veredito falado, um por vez;
  3) o `record_label` grava a linha (resposta do DONO, gabarito no `key`,
     sem a resposta no contexto);
  4) o `judgment-dataset.py` consome o registro e produz o dataset;
  5) o bench le o dataset (com um modelo local falso) e mede.

O QUE NAO FAZ: nao abre microfone, nao pede GPU, nao escreve no repo, nao
chega perto do registro real do dono.
"""
import http.server
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import importlib.util

REPO = pathlib.Path("/home/nixos/projects/nixos-ai")
sys.path.insert(0, str(REPO / "scripts"))


def mod(nome, caminho):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    m = importlib.util.module_from_spec(spec)
    sys.modules[nome] = m
    spec.loader.exec_module(m)
    return m


def main():
    up = mod("uhrs_practice", REPO / "scripts/uhrs-practice.py")
    jd = mod("jd", REPO / "scripts/judgment-dataset.py")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="prova-pratica-"))
    log = tmp / "voz.log"
    labels = tmp / "labels.jsonl"
    held = tmp / "heldout.jsonl"

    itens = up.load_items(up.ITEMS)
    print(f"1) os itens de pratica que o dono vai julgar: {len(itens)} "
          f"(ids {itens[0]['id']}..{itens[-1]['id']})")

    # ── 2) o leitor de voz REAL, alimentado por um log falso ───────────────
    # (o log e' o que o ASR escreveria: o mesmo formato que o duplex usa)
    vereditos = ["muito relevante", "moderadamente relevante",
                 "levemente relevante", "nao relevante"]
    log.write_text("[10:00:00] rms=1 | <no voice> -> <listen>\n")
    voz = up.DuplexVoice(log)
    lidos = []
    for v in vereditos:
        with log.open("a") as fh:
            fh.write(f"  SEGMENTO: {v}\n")
        got = voz.poll()
        lidos.append(got)
    print(f"2) o leitor de voz leu {len(lidos)} vereditos: {lidos}")
    assert lidos == vereditos, f"o leitor leu outra coisa: {lidos}"
    assert voz.poll() == "", "o leitor re-leu a mesma transcricao"

    # ── 3) o record_label REAL grava o registro ───────────────────────────
    for i, it in enumerate(itens[:4]):
        resp = up.parse_answer(lidos[i % len(lidos)])
        up.record_label(it, resp, "voz", path=labels,
                        why_dono="e' a fronteira: responde mas tem resultado melhor"
                        if i == 1 else None)
    rows = [json.loads(l) for l in labels.read_text().splitlines() if l.strip()]
    print(f"3) o registro gravou {len(rows)} labels")
    contrato = {"id", "context", "answer", "key", "why_dono", "source", "via", "ts"}
    for r in rows:
        assert contrato <= set(r), f"faltou campo: {contrato - set(r)}"
        assert "Answer by the owner" not in r["context"], r
        assert r["via"] == "voz", r
        assert str(r["answer"]) in ("0", "1", "2", "3"), r
    assert any(r["why_dono"] for r in rows), "o porque do dono nao foi gravado"
    print("   contrato ok (id, context, answer, key, why_dono, source, via, ts), "
          "sem a resposta no contexto, com o porque do dono")

    # ── 4) o judgment-dataset consome o registro ──────────────────────────
    old = jd.LABELS, jd.ITEMS
    jd.LABELS, jd.ITEMS = labels, tmp / "vazio.jsonl"
    try:
        out_h, msg = jd.make_heldout(rows, 2, seed=7, out_path=held, force=True)
        out, overlaps = jd.build(tmp / "out", held, test_ratio=0.25, calib=1)
    finally:
        jd.LABELS, jd.ITEMS = old
    print(f"4) o dataset saiu do registro: {msg.split('|')[0].strip()} | "
          f"vazamento: {overlaps if overlaps else 'nenhum'}")
    assert not overlaps, overlaps
    laya = [json.loads(l) for l in (out / "train.jsonl").read_text().splitlines()
            if l.strip()]
    for nome in ("test.jsonl", "calib.jsonl"):
        p = out / nome
        if p.is_file():
            laya += [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    print(f"   itens no dataset: {len(laya)}")
    # o item contestado (o segundo) tem de estar no dataset com a RESPOSTA
    # DO DONO (e nao com o gabarito): e' a delegacao.
    contestado = [r for r in rows if r["why_dono"]][0]
    alvo = [r for r in laya if r["_id"] == contestado["id"]]
    print(f"   o item contestado ({contestado['id']}): dono="
          f"{contestado['answer']} gabarito={contestado['key']}")
    if alvo:
        assert alvo[0]["answer"] == jd.LEVEL_TO_KEY[contestado["answer"]], \
            f"o dataset traz o gabarito, nao a resposta do dono: {alvo[0]}"
        print("   e no dataset ele carrega a RESPOSTA DO DONO (nao o gabarito)")

    # ── 5) o bench le o dataset e mede (modelo local falso) ────────────────
    # (25/11) O MODELO FALSO responde a RESPOSTA DO DONO (o que esta no
    # dataset), e nao o gabarito: e' assim que o bench tem de dar 100%. Se
    # ele respondesse o gabarito, o bench mediria 0/1 — o que seria a
    # DELEGACAO funcionando (o dataset carrega o julgamento do dono, nao o
    # rubric) e nao um defeito, mas a prova nao poderia afirmar o numero.
    estado = {"n": 0, "contextos": []}
    # (25/11) O MAPA E' PELA PAGINA, e nao pela consulta: tres itens de
    # pratica tem a MESMA consulta ("how long does a passport renewal
    # take") e o mapa por consulta respondia a resposta de outro item
    # (medido: o bench mediu 0/1 com o modelo respondendo o gabarito).
    # A pagina (o snippet) e' unica por item.
    dono_por_pagina = {it["snippet"]: r["answer"] for it, r in zip(itens, rows)}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            payload = json.dumps({"data": [{"id": "modelo-perfeito"}]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload.encode())

        def do_POST(self):
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n) or b"{}")
            user = ""
            for m in body.get("messages", []):
                if m.get("role") == "user":
                    user = m.get("content", "")
            m = re.search(r"Page:\s*(.+)", user)
            num = "3"
            if m:
                pagina = m.group(1).strip().splitlines()[0]
                resp = dono_por_pagina.get(pagina)
                if resp is not None:
                    num = resp
            estado["n"] += 1
            estado["contextos"].append(user)
            payload = json.dumps({"choices": [{"message": {"content": num}}]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload.encode())

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    porta = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        r = subprocess.run(
            [sys.executable, str(REPO / "scripts/judgment-bench.py"),
             "--data", str(out / "train.jsonl"),
             "--model", f"http://127.0.0.1:{porta}/v1"],
            capture_output=True, text=True, timeout=300, cwd=str(REPO))
    finally:
        srv.shutdown()
    txt = (r.stdout or "") + (r.stderr or "")
    print("5) o bench contra o dataset que veio da voz:")
    for l in txt.splitlines()[:6]:
        print("   ", l[:110])
    if r.returncode != 0:
        print(f"\nPROVA COM FALHAS: o bench saiu com rc={r.returncode}")
        return 1
    if not any("Query:" in c for c in estado["contextos"]):
        print("\nPROVA COM FALHAS: o modelo nao recebeu o contexto do item")
        return 1
    # o bench tem de dar 100% contra o modelo que responde a RESPOSTA DO
    # DONO (o que esta no dataset) — e o F1 tem de aparecer
    m = re.search(r"concordância (\d+)/(\d+)", txt)
    if not m or m.group(1) != m.group(2):
        print(f"\nPROVA COM FALHAS: o bench nao mediu 100% contra o modelo "
              f"que responde o dono ({m.group(0) if m else 'sem saida'})")
        return 1
    print(f"\nPROVA OK: o veredito FALADO (log falso, leitor real) virou label "
          f"no contrato, virou dataset sem vazamento, e o bench leu esse "
          f"dataset com o contexto no prompt ({estado['n']} chamadas, "
          f"{m.group(0)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
