"""Prova do conserto do bench: o arquivo Laya agora e' lido certo.

(24/11/2026, coord-naming) O proprio docstring do bench mandava
    python3 scripts/judgment-bench.py --data data/judgments/train.jsonl
mas esse arquivo e' do Laya: contexto no campo `state` e resposta na CHAVE
("MODERATELY"). O bench lia `row.get("context")`, que dava vazio, e comparava
"MODERATELY" com a resposta numerica do modelo, dando 0% com qualquer modelo.

ESTA PROVA (sem GPU, sem rede): um servidor HTTP local que responde com o
nivel certo de cada item (um "modelo perfeito") e o bench rodado contra o
arquivo Laya gerado. O esperado agora e' 100% de concordancia. Antes do
conserto o mesmo comando dava 0%.

O servidor e' local e efemero: porta livre, shut down no fim, nada toca a
GPU nem a rede de fora.
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
    jd = mod("jd", REPO / "scripts/judgment-dataset.py")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="prova-bench-laya-"))
    labels = tmp / "labels.jsonl"
    held = tmp / "held.jsonl"
    held.write_text("")
    rows = [{"id": f"q{i:02d}", "context": f"Query: q{i:02d}\nPage: p{i:02d}",
             "answer": str(i % 4), "key": str(i % 4),
             "source": "uhrs-qualification", "via": "voz"} for i in range(20)]
    labels.write_text("".join(json.dumps(r) + "\n" for r in rows))

    old = jd.LABELS, jd.ITEMS
    jd.LABELS, jd.ITEMS = labels, tmp / "vazio.jsonl"
    try:
        out, _ov = jd.build(tmp / "out", held, test_ratio=0.25, calib=4)
    finally:
        jd.LABELS, jd.ITEMS = old

    # o held-out do dono (formato do registro: contexto + numero)
    held.write_text("".join(json.dumps(r) + "\n" for r in rows[:8]))

    laya_path = out / "train.jsonl"
    laya = [json.loads(l) for l in laya_path.read_text().splitlines() if l.strip()]
    print(f"arquivo Laya gerado: {len(laya)} itens | "
          f"campos: {sorted(laya[0].keys())}")

    # ── o "modelo perfeito": um servidor HTTP local que devolve o nivel ───
    # (o contexto que chega no prompt e' o `state` do item; o servidor
    # responde o numero correspondente ao que o proprio bench mandou)
    estado = {"n": 0, "contextos": []}
    # o mapa id -> numero, tirado do REGISTRO DE ORIGEM (o split de treino
    # tem so uma parte dos itens)
    gold_por_id = {r["id"]: r["answer"] for r in rows}
    gold_por_num = {int(r["id"][1:]): r["answer"] for r in rows}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            # (24/11) o `pick_model` do bench so faz o POST se o
            # GET /v1/models anunciar um id (medido no codigo: `if not
            # model: continue`). Sem este endpoint o bench descartava o
            # servidor como "nenhum modelo local respondeu".
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
            # (24/11) a resposta e' escolhida pelo CONTEUDO do prompt (o
            # `Query: qNN` do item), e nao pela ordem das chamadas: o
            # `pick_model` do bench faz um POST de "ping" antes, e contar
            # as chamadas deslocava todas as respostas em uma.
            m = re.search(r"Query:\s*q(\d+)", user)
            num = "3"
            if m:
                # (24/11) o mapa vem do REGISTRO DE ORIGEM, e nao do
                # split de treino: o split tem so 12 dos 20 itens, e
                # indexar por ele respondia a resposta de outro item.
                gold = gold_por_num.get(int(m.group(1)))
                if gold is not None:
                    num = gold
            estado["n"] += 1
            estado["contextos"].append(user)
            payload = json.dumps({"choices": [{"message": {"content": num}}]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload.encode())

    def run_bench(caminho, rotulo):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        porta = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            r = subprocess.run(
                [sys.executable, str(REPO / "scripts/judgment-bench.py"),
                 "--data", str(caminho),
                 "--model", f"http://127.0.0.1:{porta}/v1"],
                capture_output=True, text=True, timeout=300, cwd=str(REPO))
        finally:
            srv.shutdown()
        txt = (r.stdout or "") + (r.stderr or "")
        print(f"\n--- o bench contra {rotulo} ---")
        for l in txt.splitlines()[:12]:
            print("   ", l[:110])
        return r, txt

    r, txt = run_bench(laya_path, "o arquivo Laya (train.jsonl)")

    # ── o que a prova exige ───────────────────────────────────────────────
    problemas = []
    if r.returncode != 0:
        problemas.append(f"o bench saiu com rc={r.returncode}: "
                         f"{txt.strip()[-120:]}")
    if "concordância 12/12 = 100.0%" not in txt:
        problemas.append("o bench nao mediu 100% contra o modelo perfeito")
    # o prompt tem de carregar o CONTEXTO (estado antes: vazio)
    if not any("Query: q" in c for c in estado["contextos"]):
        problemas.append("o modelo nao recebeu o contexto do item "
                         "(o prompt ia vazio)")
    # e o F1 por nivel tem de ter os niveis que EXISTEM no arquivo medido
    # (estado antes: nada, porque o gold era a chave e nao o numero)
    niveis = {"HIGHLY": "3", "MODERATELY": "2", "SLIGHTLY": "1",
              "NOT": "0"}
    esperados = {niveis[r["answer"]] for r in laya}
    for lv in sorted(esperados):
        if f"nivel {lv}: F1" not in txt:
            problemas.append(f"o F1 do nivel {lv} nao aparece (o arquivo "
                             f"medido tem esse nivel)")
    # e o F1 nao pode aparecer para um nivel que o arquivo NAO tem
    for lv in ("3", "2", "1", "0"):
        if lv not in esperados and f"nivel {lv}: F1" in txt:
            problemas.append(f"o F1 do nivel {lv} aparece mas o arquivo "
                             f"medido nao tem esse nivel")

    # ── o MESMO bench contra o held-out (o formato do dono) ───────────────
    # (o caminho que decide a delegacao: --heldout com o arquivo do dono)
    r2, txt2 = run_bench(held, "o held-out (formato do dono)")
    if r2.returncode != 0:
        problemas.append(f"o bench contra o held-out saiu com rc={r2.returncode}")
    m = re.search(r"concordância (\d+)/(\d+)", txt2)
    if not m or m.group(1) != m.group(2):
        problemas.append(f"o bench contra o held-out nao mediu 100% "
                         f"(modelo perfeito): {m.group(0) if m else 'sem saida'}")

    if problemas:
        print("\nPROVA COM FALHAS:")
        for p in problemas:
            print("  -", p)
        return 1
    print(f"\nPROVA OK: o bench le o arquivo Laya (contexto no prompt, "
          f"{estado['n']} chamadas, 12/12 = 100% contra o modelo perfeito, "
          f"F1 dos niveis presentes) E o held-out do dono (100% tambem)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
