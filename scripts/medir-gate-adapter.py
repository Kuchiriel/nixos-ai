"""Mede o gate no heldout3 com um LoRA, com TIMEOUT e n_predict HONESTOS,
e DEGRAIS o token (a metrica do item #10).

POR QUE ESTE SCRIPT EXISTE (19/11, sweep-2026-11, item #10 + (a)/(b)/(c) da
frota): a frota mediu no heldout3: 35B+LoRA duplex = 9/39 (61s/token, 2,4h/cilo),
4B MTP+LoRA v9 = 29/39 (4,6-5,5s/token, 3min/cilo) e 8B denso SEM LoRA =
0-1/39, porque o n_predict=6 CORTA "SILENCE" (7 caracteres) em "SILE" e o
timeout de 8 s do classify_turn mede o TIMEOUT, nao o modelo.

ACHEI TRES ARMADILHAS DE INSTRUMENTO (todas medidas aqui):
1. o PROMPT tem de ser o do classificador OFICIAL, palavra por palavra: o
   CLASS_SYS oficial DESCREVE cada rotulo (o LoRA foi treinado com ele). Com
   uma versao encurtada o v9 deu 15/39 em vez de 29/39.
2. o classify_turn usa o endpoint /completion (formato llama.cpp), que NAO
   devolve `usage`: o token tem de ser lido no /v1/completions. Entao este
   script mede o rotulo no /completion (o caminho do classificador real) e o
   token no /v1/completions (o caminho que devolve o usage).
3. a porta 8096 e' DO LAB e ele MATA o processo que estiver na mesma porta
   (medido: 'RemoteDisconnected'). A porta livre e' a 8094.

O QUE ESTE SCRIPT MEDE (por adapter):
  - acuracia por rotulo e por classe, no heldout3 (39 itens, sem vazamento);
  - token de entrada e de saida por chamada, via o usage do /v1/completions;
  - a ACURACIA POR TOKEN: aprovacoes por 1M token.

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

# (19/11, sweep-2026-11) MEDIDO: o CLASS_SYS oficial DESCREVE cada rotulo
# (o LoRA foi treinado com ele). A primeira versao deste script usava uma
# versao encurtada e deu v9 = 15/39, contra 29/39 da frota com o
# classificador oficial. O prompt tem de ser o do classificador REAL.
CLASS_SYS = ("Você é o JARVIS, assistente de voz. Classifique o turno do "
             "usuário em uma palavra: RESPOND (fala completa que pede "
             "resposta), WAIT (frase incompleta, mais vem), SILENCE "
             "(backchannel/ruído ou fala completa NÃO dirigida ao assistente, "
             "como TV/narração/música), ou BARGE (o dono interrompeu sua fala).")
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


def sobe(lora):
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
    espera = int(sys.argv[6]) if len(sys.argv) > 6 else 12

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
    if not sobe(lora):
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
    lat_rodadas = []
    por_rotulo_final, por_classe_final = {}, {}
    for rodada in range(1, rodadas + 1):
        print(f"3) rodada {rodada}/{rodadas} ({len(HELDOUT3)} falas):")
        cert = 0
        pt, ct = [], []
        lat = []
        por_rotulo, por_classe = {}, {}
        for utter, expected, cls in HELDOUT3:
            prompt = (f"<|im_start|>system\n{CLASS_SYS}<|im_end|>\n"
                      f"<|im_start|>user\n{utter}<|im_end|>\n"
                      f"<|im_start|>assistant\n")
            # (19/11) MEDIDO: o /completion (formato llama.cpp, o caminho do
            # classify_turn) NAO devolve usage; o /v1/completions devolve. Entao
            # o rotulo vem do /completion (o classificador real) e o token do
            # /v1/completions (o unico com usage).
            t = time.time()
            t = time.time()
            try:
                # (19/11, sweep-2026-11) MEDIDO: no /v1/completions o
                # orcamento e' `max_tokens` (o `n_predict` e' do
                # /completion), o texto vem em `choices[0].text` (o `content`
                # e' do /completion) e o `usage` so existe aqui. Entao UMA
                # inferencia traz o rotulo E o token real.
                req = urllib.request.Request(
                    base + "/v1/completions",
                    data=json.dumps({"prompt": prompt, "max_tokens": n_predict,
                                     "temperature": 0, "stop": ["<|im_end|>"],
                                     "cache_prompt": True}).encode(),
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    j = json.loads(r.read().decode())
                ch = (j.get("choices") or [{}])[0]
                txt = str(ch.get("text") or ch.get("message", {}).get("content") or "")
                u = j.get("usage") or {}
            except Exception as e:
                print(f"   ERRO {type(e).__name__}: {e}")
                break
            lat.append(time.time() - t)
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
    print(f"   tokens por rodada: {[int(t) for t in tokens_total_rodadas]} (media {tok_medio:.0f})")
    print(f"   latencia mediana: {[round(l,1) for l in lat_rodadas]} s")
    print(f"   ACURACIA POR TOKEN: {media:.1f} / {tok_medio:.0f} = "
          f"{media / tok_medio * 1e6:.2f} por 1M token")
    print("   por rotulo:")
    for (exp, got), q in sorted(por_rotulo_final.items()):
        print(f"     {exp:8} -> {got:8} {q}")

    out = {
        "adapter": nome, "lora_path": lora, "adapter_no_servidor": adapters,
        "n_predict": n_predict, "timeout": timeout,
        "rodadas": len(accertos_rodadas), "itens": n,
        "acertos_por_rodada": accertos_rodadas,
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
