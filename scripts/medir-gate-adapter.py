"""Repete a medicao do gate N vezes por adapter, para a diferenca de 2 itens
do v9 contra o v10 ter significance.

POR QUE (19/11, sweep-2026-11, item #10): a primeira rodada deu v9 = 15/39 e
v10 = 13/39. Dois itens de diferenca em 39 nao provam nada: o proprio video
do VIDEU diz que "uma unica run e ruido" (e o laboratorio ja caçou a
alternancia EXATA de 5 passed/5 failed que era bug de instrumento). Entao: N
amostras, o MESMO conjunto, o MESMO prompt, e o intervalo.

O QUE ESTE SCRIPT FAZ:
1) sobe o MTP com o adapter pedido (na porta 8094, que ninguem usa — a 8096 e'
   do lab e ele MATA o processo que estiver na mesma porta);
2) roda o heldout3 N vezes, medindo token de entrada e saida por chamada;
3) reporta a acuracia media, o desvio, e a ACURACIA POR TOKEN.

O QUE ELE NAO FAZ: nao mexe no ab_loop.sh, no classify_turn do
duplex-voice.py (que e' de outra lane), no registry; nao derruba o servidor de
producao (:8092) e nao deixa a GPU com o braco.
"""
import json
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/home/nixos/projects/nixos-ai")
sys.path.insert(0, str(REPO / "benchmarks/voice"))

CLASS_SYS = (
    "Você é o JARVIS, assistente de voz. Classifique o turno do usuário em "
    "una palabra: RESPOND, WAIT, SILENCE ou BARGE."
)
LABELS = ("RESPOND", "WAIT", "SILENCE", "BARGE")
LLAMA = "/home/nixos/projects/llama.cpp/build-stock/bin/llama-server"
MODELO = "/var/lib/ai/models/Qwen3.5-4B-MTP-Q4_K_M.gguf"
PORTA = 8094


def rotulo_de(txt):
    limpo = re.sub(r"<think>.*?</think>", " ", txt or "", flags=re.DOTALL)
    limpo = limpo.strip().upper()
    for lab in LABELS:
        if limpo.startswith(lab):
            return lab
    for lab in LABELS:
        if re.search(r"\b" + lab + r"\b", limpo):
            return lab
    return None


def porta_viva(p):
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{p}/v1/models", timeout=3).read()
        return True
    except Exception:
        return False


def derruba(p):
    out = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True).stdout
    for ln in out.splitlines():
        if f":{p} " in ln:
            for pid in re.findall(r"pid=(\d+)", ln):
                try:
                    os.kill(int(pid), 9)
                except Exception:
                    pass


def vram_livre():
    r = subprocess.run(["nvidia-smi", "--query-gpu=memory.free",
                        "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=20)
    try:
        return int(r.stdout.strip().splitlines()[0])
    except Exception:
        return 0


def sobe(lora, base):
    derruba(PORTA)
    time.sleep(2)
    cmd = [LLAMA, "-m", MODELO, "--host", "127.0.0.1", "--port", str(PORTA),
           "-ngl", "99", "-t", "6", "-c", "12288", "-b", "256", "-ub", "256",
           "-fa", "off", "-ctk", "f16", "-ctv", "f16",
           "--alias", "jarvis-mtp-lab", "--parallel", "1", "--jinja",
           "--reasoning", "off", "--spec-type", "draft-mtp",
           "--lora", lora, "--lora-init-without-apply"]
    log = open("/tmp/opencode/mtp-lab.log", "wb")
    subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                     start_new_session=True)
    for _ in range(120):
        if porta_viva(PORTA):
            return True
        time.sleep(1)
    return False


def main():
    lora = sys.argv[1]
    n_predict = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 180
    nome = sys.argv[4] if len(sys.argv) > 4 else Path(lora).stem
    rodadas = int(sys.argv[5]) if len(sys.argv) > 5 else 3
    espera = int(sys.argv[6]) if len(sys.argv) > 6 else 10

    import urllib.request
    base = f"http://127.0.0.1:{PORTA}"

    print(f"1) {nome}: esperando a janela (VRAM >= 4300 e a 8096 do lab livre, "
          f"ate {espera} min)")
    t0 = time.time()
    while (time.time() - t0) < espera * 60:
        if vram_livre() >= 4300 and not porta_viva(8096):
            print(f"   janela: {vram_livre()} MiB livres, lab fora")
            break
        print(f"   VRAM {vram_livre()} MiB | lab "
              f"{'presente' if porta_viva(8096) else 'fora'} | faltam "
              f"{espera - int((time.time() - t0) // 60)} min", flush=True)
        time.sleep(30)
    else:
        print("   SEM JANELA: nao peguei a GPU do lab.")
        return 2

    print(f"2) subindo o MTP com {Path(lora).name}:")
    if not sobe(lora, base):
        print("   NAO respondeu em 120s")
        print(Path("/tmp/opencode/mtp-lab.log").read_text()[-800:])
        derruba(PORTA)
        return 1
    urllib.request.urlopen(urllib.request.Request(
        base + "/lora-adapters",
        data=json.dumps([{"id": 0, "scale": 1.0}]).encode(),
        headers={"Content-Type": "application/json"}), timeout=15).read()
    with urllib.request.urlopen(base + "/lora-adapters", timeout=15) as r:
        adapters = json.loads(r.read().decode())
    print(f"   adapter: {adapters}")

    try:
        from heldout3 import HELDOUT3
    except Exception:
        from heldout2 import HELDOUT2 as _H2
        HELDOUT3 = [(t, r, "heldout2") for t, r in _H2]

    accertos_rodadas = []
    tokens_total_rodadas = []
    por_rotulo_final, por_classe_final = {}, {}
    lat_rodadas = []
    for rodada in range(1, rodadas + 1):
        print(f"3) rodada {rodada}/{rodadas} ({len(HELDOUT3)} falas):")
        cert = 0
        pt, ct = [], []
        lat = []
        por_rotulo, por_classe = {}, {}
        for utter, expected, cls in HELDOUT3:
            payload = {
                "prompt": (f"<|im_start|>system\n{CLASS_SYS}<|im_end|>\n"
                           f"<|im_start|>user\n{utter}<|im_end|>\n"
                           f"<|im_start|>assistant\n"),
                "max_tokens": n_predict, "temperature": 0,
                "stop": ["<|im_end|>"]}
            req = urllib.request.Request(
                base + "/v1/completions", data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"})
            t = time.time()
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    j = json.loads(r.read().decode())
            except Exception as e:
                print(f"   ERRO {type(e).__name__}: {e}")
                break
            lat.append(time.time() - t)
            u = j.get("usage") or {}
            txt = (j.get("choices") or [{}])[0].get("text", "")
            if u.get("prompt_tokens"):
                pt.append(u["prompt_tokens"])
            if u.get("completion_tokens"):
                ct.append(u["completion_tokens"])
            got = rotulo_de(txt)
            cert += 1 if got == expected else 0
            por_rotulo[(expected, got or "NONE")] = por_rotulo.get((expected, got or "NONE"), 0) + 1
            por_classe[(cls, got or "NONE")] = por_classe.get((cls, got or "NONE"), 0) + 1
        n = len(lat)
        if not n:
            break
        accertos_rodadas.append(cert)
        tokens_total_rodadas.append(sum(pt) + sum(ct))
        lat_rodadas.append(statistics.median(lat))
        por_rotulo_final, por_classe_final = por_rotulo, por_classe
        print(f"   rodada {rodada}: {cert}/{n} = {cert/n:.1%} | "
              f"tokens {sum(pt)+sum(ct)} | lat mediana {statistics.median(lat):.1f}s")

    derruba(PORTA)
    if not accertos_rodadas:
        print("   (nenhuma medicao)")
        return 2

    n = len(HELDOUT3)
    media = statistics.mean(accertos_rodadas)
    desvio = statistics.pstdev(accertos_rodadas) if len(accertos_rodadas) > 1 else 0.0
    tok_medio = statistics.mean(tokens_total_rodadas)
    print(f"\n4) RESULTADO do {nome} ({len(accertos_rodadas)} rodadas):")
    print(f"   acertos por rodada: {accertos_rodadas}")
    print(f"   media {media:.1f}/{n} = {media/n:.1%} | desvio {desvio:.1f} item(ns)")
    print(f"   tokens por rodada: {[int(t) for t in tokens_total_rodadas]} "
          f"(media {tok_medio:.0f})")
    print(f"   latencia mediana: {[round(l,1) for l in lat_rodadas]} s")
    print(f"   ACURACIA POR TOKEN (media): {media:.1f} aprovacoes / "
          f"{tok_medio:.0f} tokens = {media / tok_medio * 1e6:.2f} por 1M token")
    print("   por rotulo (ultima rodada):")
    for (exp, got), q in sorted(por_rotulo_final.items()):
        print(f"     {exp:8} -> {got:8} {q}")

    out = {
        "adapter": nome, "lora_path": lora, "adapter_no_servidor": adapters,
        "n_predict": n_predict, "timeout": timeout, "rodadas": len(accertos_rodadas),
        "itens": n, "acertos_por_rodada": accertos_rodadas,
        "acertos_media": round(media, 2), "acuracia_media": round(media / n, 4),
        "desvio_itens": round(desvio, 2),
        "tokens_por_rodada": [int(t) for t in tokens_total_rodadas],
        "tokens_media": int(tok_medio),
        "lat_mediana_s": [round(l, 2) for l in lat_rodadas],
        "acuracia_por_1M_token": round(media / tok_medio * 1e6, 2),
        "por_rotulo": {f"{e}->{g}": q for (e, g), q in por_rotulo_final.items()},
        "por_classe": {f"{c}->{g}": q for (c, g), q in por_classe_final.items()},
    }
    Path(f"/tmp/opencode/token-{nome}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n   resultado: /tmp/opencode/token-{nome}.json")
    print("   servidor derrubado (a GPU volta)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
