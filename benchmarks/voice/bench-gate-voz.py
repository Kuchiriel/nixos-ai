"""bench-gate-voz.py — o gate medido no CANAL DE VOZ (o que falta).

(23/11/2026, coord-naming) POR QUE ISTO EXISTE: o acervo mediu que um
turno falado custa **-12 pontos de Pass@1** pelo front-end de voz
(harness-voice-bridge.md) e que o **PF < 10 %** para todo modelo na cadeia
de ferramentas por voz (VoiceAgentBench, arXiv 2510.07978). O `bench_heldout3.py`
classifica o item como **TEXTO** — ou seja, o gate da casa NUNCA foi medido
no canal por onde ele realmente trabalha (o audio do dono transcrito pelo
whisper). E o que se mede no texto e' o numero que decide o modo de
delegacao.

O QUE ESTE BENCH FAZ:
  1) sintetiza audio de cada item do heldout3 (a voz local da casa, o piper;
     sem depender de rede);
  2) transcreve o audio pelo mesmo ASR do cliente (o whisper :8097, o mesmo
     que produz o 'SEGMENTO:' do log);
  3) classifica a TRANSCRICAO com o gate (o mesmo classify_turn) e compara
     com o gabarito;
  4) mede o gate em DUAS condicoes e mostra a diferenca:
       TEXTO  = a transcricao ideal (o item como escrito)  -> o limite de cima
       VOZ    = o que o ASR de verdade devolveu            -> o numero real
  5) o custo de cada transricao (o tempo do ASR) e o quanto o front-end
     de voz destrói do item (a diferenca entre o item e a transcricao).

O QUE NAO FAZ: nao mexe no registro do dono, nao inventa rotulo, nao
chama o classificador do telefone do dono (o heldout3 e' texto: o audio e'
sintetizado). O numero do gate no texto ja existe (o bench_heldout3); este
mede o que NINGUEM mediu: o gate depois do ASR.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request
from collections import Counter

REPO = pathlib.Path("/home/nixos/projects/nixos-ai")
sys.path.insert(0, str(REPO / "modules/ai/jarvis/src"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "benchmarks/voice"))

LEVEL_NAMES = {"3": "highly relevant", "2": "moderately relevant",
               "1": "slightly relevant", "0": "not relevant"}


def reexecutar_com_o_ambiente_correto():
    """Reexecuta o bench no ambiente do duplex VIVO, se o atual nao servir.

    (25/11) MEDIDO: o comando que os docs mandavam
    (`python3 benchmarks/voice/bench-gate-voz.py`) MORREVA com
    "ModuleNotFoundError: No module named 'numpy'". E com o venv do karaok
    sem o `LD_LIBRARY_PATH`, morria com "libstdc++.so.6: cannot open
    shared object file". As DUAS coisas sao resolvidas pelo mesmo caminho
    que o duplex vivo usa (medido no processo vivo):
      - o interpretador: `~/projects/karaok/.venv/bin/python3`;
      - as libs: `scripts/asrd_env.py --print` (o mesmo resolver do
        `duplex-voice-run.sh`).

    Aqui o bench se reexecuta sozinho, para o comando documentado
    funcionar. Se nao der para reexecutar, a mensagem diz o comando
    exato, em vez de um traceback de import.
    """
    if os.environ.get("BENCH_GATE_VOZ_REEXEC") == "1":
        return None
    # o python atual ja serve? (numpy e as libs do sistema)
    try:
        import numpy  # noqa: F401
        import sounddevice  # noqa: F401
        return None
    except Exception as exc:
        primeiro = str(exc).splitlines()[0][:90]
    py = pathlib.Path.home() / "projects/karaok/.venv/bin/python3"
    if not py.is_file():
        print(f"ERRO: este bench precisa do venv do karaok (numpy): {primeiro}\n"
              f"       o interpretador nao esta em {py}", file=sys.stderr)
        return None
    env = dict(os.environ)
    try:
        ld = subprocess.run([sys.executable, str(REPO / "scripts/asrd_env.py"),
                             "--print"], capture_output=True, text=True,
                            timeout=120).stdout.strip()
    except Exception:
        ld = ""
    if ld:
        env["LD_LIBRARY_PATH"] = ld + (
            (":" + env["LD_LIBRARY_PATH"]) if env.get("LD_LIBRARY_PATH") else "")
    env["BENCH_GATE_VOZ_REEXEC"] = "1"
    print(f"[bench-gate-voz] reexecutando no ambiente do duplex vivo "
          f"({py})...", file=sys.stderr)
    return subprocess.run([str(py), str(pathlib.Path(__file__).resolve())] +
                          sys.argv[1:], env=env).returncode


def carregar_heldout():
    from heldout3 import HELDOUT3
    return HELDOUT3


def asr_disponivel():
    """O whisper da casa (:8097) responde?"""
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8097/health", timeout=4) as r:
            return r.status == 200
    except Exception:
        return False


def sintetizar(texto, destino, voz=None):
    """Sintetiza o audio do item (piper local). Devolve (ok, erro).

    (23/11) A voz e' a MESMA do duplex: o binario estatico
    ~/models/piper/bin/piper com /var/lib/ai/models/piper/pt_BR-faber-medium.onnx
    (medido no duplex: 0,033 de fator, 0,177 s de inferencia para 5,3 s de
    audio). Medir o gate com a voz que o dono OUVE e' o que importa; um TTS
    diferente mediria um front-end que a casa nao usa.
    """
    destino = pathlib.Path(destino)
    piper = pathlib.Path.home() / "models/piper/bin/piper"
    if not piper.is_file():
        return False, f"piper ausente em {piper}"
    modelo = voz or "/var/lib/ai/models/piper/pt_BR-faber-medium.onnx"
    if not pathlib.Path(modelo).is_file():
        return False, f"voz ausente: {modelo}"
    r = subprocess.run([str(piper), "--model", modelo,
                        "--output_file", str(destino)],
                       input=texto.encode(), capture_output=True, timeout=60)
    if r.returncode != 0 or not destino.is_file() or destino.stat().st_size < 1000:
        return False, (r.stderr or b"falhou").decode(errors="replace")[:160]
    return True, ""


def transcrever(wav, modelo=None):
    """Transcreve pelo whisper da casa (o mesmo ASR do cliente).

    (23/11) O CONTRATO EXATO do cliente (scripts/duplex-asrd.py:254-276):
    multipart/form-data com o campo 'file' (o WAV cru), o 'prompt' de
    vocabulario e 'response_format=verbose_json' (que expoe
    no_speech_prob/avg_logprob por segmento — as defesas anti-halluc). O
    whisper-server recusa WAV cru em /inference ('Invalid request'): o que
    ele quer e o multipart.
    """
    import urllib.request
    wav = pathlib.Path(wav)
    buf = wav.read_bytes()
    boundary = "----JARVIS"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; "
        f"name=\"file\"; filename=\"item.wav\"\r\n"
        f"Content-Type: audio/wav\r\n\r\n").encode() + buf + b"\r\n"
    body += (f"--{boundary}\r\nContent-Disposition: form-data; "
             f"name=\"response_format\"\r\n\r\nverbose_json\r\n").encode()
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8097/inference", data=body,
        headers={"Content-Type":
                 f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=90) as r:
        j = json.loads(r.read().decode())
    return str(j.get("text") or "").strip()


def classificador_disponivel(base, timeout=20.0):
    """O classificador responde? (o veredito de transporte, medido ANTES)

    (25/11) MEDIDO: com o MTP parado, o bench NAO falhava — ele media
    39 itens, o classificador devolvia `None` (conexao recusada) e a
    saida era "voz: 0/39 = 0.0%", um numero FALSO que parece "o gate
    quebrou". E' a mesma regra da lane: um timeout que corta o rotulo
    produz veredito invalido; uma conexao recusada tambem. A medicao
    agora para ANTES, com o comando que resolve.
    """
    try:
        req = urllib.request.Request(base.rstrip("/") + "/v1/models",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return bool([m.get("id") for m in (data.get("data") or []) if m.get("id")])
    except Exception:
        return False


def main():
    # (25/11) O comando documentado precisa FUNCIONAR: se o interpretador
    # atual nao tem as libs do duplex, o bench se reexecuta no ambiente
    # certo (o do processo vivo) em vez de morrer com um traceback.
    rc = reexecutar_com_o_ambiente_correto()
    if rc is not None:
        return rc

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8092")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", default="")
    ap.add_argument("--voz", default="", help="modelo piper (default: o do sistema)")
    args = ap.parse_args()

    itens = carregar_heldout()
    if args.limit:
        itens = itens[: args.limit]

    if not asr_disponivel():
        print("ERRO: o whisper da casa (:8097) nao responde — o ASR do "
              "cliente esta parado; sem ele nao ha canal de voz para medir.",
              file=sys.stderr)
        return 2

    # (25/11) O CLASSIFICADOR TEM DE RESPONDER ANTES DE MEDIR. Sem esta
    # checagem, um MTP parado media "0/39" (o `None` da conexao recusada
    # entrava como resposta errada do modelo) — um numero falso que
    # parece "o gate quebrou" e que decide o modo de delegacao.
    if not classificador_disponivel(args.base):
        print(f"ERRO: o classificador ({args.base}) nao responde. A medicao "
              f"NAO foi feita: um classificador parado devolveria `None` "
              f"para todos os itens e o resultado sairia 0%, que e' um numero "
              f"FALSO (veredito de transporte virando veredito de modelo).",
              file=sys.stderr)
        print("Para levantar o MTP (perfil lora, :8092): "
              "bash scripts/llama-swap.sh --start-mtp lora", file=sys.stderr)
        print("Se a GPU estiver emprestada a outro treino, ESPERE: pega-la "
              "sem coordenacao derruba a voz da casa.", file=sys.stderr)
        return 2

    # o classificador (o mesmo do bench_heldout3)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "duplex_voice", REPO / "scripts/duplex-voice.py")
    dv = importlib.util.module_from_spec(spec)
    sys.modules["duplex_voice"] = dv
    spec.loader.exec_module(dv)

    tmp = pathlib.Path("/tmp/opencode/gate-voz")
    tmp.mkdir(parents=True, exist_ok=True)

    linhas = []
    stats = {"n": 0, "ok_texto": 0, "ok_voz": 0, "asr_erros": 0,
             "asr_ms": [], "dif_por_item": []}
    por_rotulo_texto = Counter()
    por_rotulo_voz = Counter()
    por_classe_voz = Counter()

    for i, (utter, esperado, cls) in enumerate(itens):
        wav = tmp / f"item-{i:02d}.wav"
        ok, err = sintetizar(utter, wav, args.voz or None)
        if not ok:
            print(f"[{i}] sintese falhou: {err}", file=sys.stderr)
            stats["asr_erros"] += 1
            continue
        t0 = time.monotonic()
        transc = transcrever(wav)
        ms = (time.monotonic() - t0) * 1000
        stats["asr_ms"].append(ms)

        # 1) o gate no TEXTO (o limite de cima)
        lab_texto = dv.classify_turn(args.base, utter)
        # 2) o gate na TRANSCRICAO (o numero real)
        lab_voz = dv.classify_turn(args.base, transc) if transc else None

        stats["n"] += 1
        por_rotulo_texto[lab_texto or "NONE"] += 1
        por_rotulo_voz[lab_voz or "NONE"] += 1
        if lab_voz == esperado:
            stats["ok_voz"] += 1
            por_classe_voz[cls] += 1
        if lab_texto == esperado:
            stats["ok_texto"] += 1
        # o quanto o front-end de voz destruiu do item
        dif = _dif(utter, transc)
        stats["dif_por_item"].append(dif)
        linhas.append({"id": i, "classe": cls, "esperado": esperado,
                       "texto": utter, "transcricao": transc,
                       "gate_texto": lab_texto, "gate_voz": lab_voz,
                       "asr_ms": round(ms, 1), "dif_palavras": dif})
        print(f"[{i:02d}] {cls:20s} esperado={esperado} "
              f"texto={lab_texto or 'NONE':8s} voz={lab_voz or 'NONE':8s} "
              f"asr={ms:6.0f}ms | {transc[:60]}", flush=True)

    n = max(1, stats["n"])
    res = {
        "base": args.base,
        "itens": stats["n"],
        "acertos_texto": stats["ok_texto"],
        "acertos_voz": stats["ok_voz"],
        "acc_texto": round(stats["ok_texto"] / n, 4),
        "acc_voz": round(stats["ok_voz"] / n, 4),
        "delta_voz_menos_texto": round((stats["ok_voz"] - stats["ok_texto"]) / n, 4),
        "asr_ms_medio": round(sum(stats["asr_ms"]) / max(1, len(stats["asr_ms"])), 1),
        "asr_erros": stats["asr_erros"],
        "dif_palavras_media": round(
            sum(stats["dif_por_item"]) / max(1, len(stats["dif_por_item"])), 2),
        "gate_texto": dict(por_rotulo_texto),
        "gate_voz": dict(por_rotulo_voz),
        "acertos_voz_por_classe": dict(por_classe_voz),
        "linhas": linhas,
    }
    print("\n=== O GATE NO CANAL DE VOZ (heldout3, texto sintetizado) ===")
    print(f"itens: {res['itens']} | texto: {res['acertos_texto']}/{res['itens']} "
          f"({res['acc_texto']:.1%}) | voz: {res['acertos_voz']}/{res['itens']} "
          f"({res['acc_voz']:.1%})")
    print(f"delta voz menos texto: {res['delta_voz_menos_texto']:+.1%} | "
          f"ASR medio: {res['asr_ms_medio']:.0f} ms | "
          f"palavras perdidas pelo front-end: {res['dif_palavras_media']:.2f} por item")
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(res, ensure_ascii=False, indent=1))
        print(f"detalhe: {args.json}")
    return 0


def _dif(a, b):
    """Quantas palavras do original NAO sobreviveram a transcricao."""
    wa = str(a or "").lower().split()
    wb = set(str(b or "").lower().split())
    return sum(1 for w in wa if w not in wb)


if __name__ == "__main__":
    raise SystemExit(main())
