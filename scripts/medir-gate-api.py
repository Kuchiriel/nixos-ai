"""Mede o gate no heldout3 com o BRAÇO DE 1M DE CONTEXTO (api), na mesma
metrica de token dos adapters locais.

POR QUE (19/11, sweep-2026-11, item #10): a hipotese do video do VIDEU e'
"modelos 1M ctx vs especialistas" e a metrica e' ACURACIA POR TOKEN. ate
aqui eu medi os tres adapters LOCAIS (v9, v10 e o de 81 MB que esta em
producao). Falta a outra ponta: o modelo de 1M de contexto, que no laboratorio
e' o braco `api` (o nemotron-3-ultra-550b-a55b, via o nv-gate na :8095).

O QUE ESTE SCRIPT FAZ:
1) descobre o endpoint do braco `api` na MESMA configuracao que o lab usa
   (nightwatch.dungeon.MODELOS["api"]);
2) roda o heldout3 com o prompt EXATO do classificador oficial (o CLASS_SYS
   completo, que descreve cada rotulo — a versao encurtada muda o resultado),
   N rodadas, medindo o token de entrada e saida que a API devolve;
3) reporta acuracia, token e ACURACIA POR TOKEN, na MESMA formula dos
   adapters locais, para a tabela ser comparavel.

O QUE ELE NAO FAZ: nao mexe no ab_loop.sh, no classify_turn do
duplex-voice.py (que e' de outra lane), no registry; nao derruba o servidor de
producao (:8092) e nao pega a GPU do lab (esta medida e' pela API, sem GPU).
"""
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

REPO = Path("/home/nixos/projects/nixos-ai")
sys.path.insert(0, str(REPO / "modules/ai/jarvis/src"))
sys.path.insert(0, str(REPO / "benchmarks/voice"))

# (19/11, sweep-2026-11) MEDIDO: o CLASS_SYS oficial DESCREVE cada rotulo
# (o LoRA foi treinado com ele). Uma versao encurtada muda o resultado.
CLASS_SYS = ("Você é o JARVIS, assistente de voz. Classifique o turno do "
             "usuário em uma palavra: RESPOND (fala completa que pede "
             "resposta), WAIT (frase incompleta, mais vem), SILENCE "
             "(backchannel/ruído ou fala completa NÃO dirigida ao assistente, "
             "como TV/narração/música), ou BARGE (o dono interrompeu sua fala).")
LABELS = ("RESPOND", "WAIT", "SILENCE", "BARGE")


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


def main():
    n_predict = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 180
    rodadas = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    braco = sys.argv[4] if len(sys.argv) > 4 else "api"
    espera_429 = float(sys.argv[5]) if len(sys.argv) > 5 else 20.0

    from nightwatch.dungeon import MODELOS
    cfg = MODELOS[braco]
    base = cfg["base_url"].rstrip("/")
    modelo = cfg["model"]
    print(f"1) braco '{braco}': {modelo} em {base}")

    envf = Path.home() / ".config/opencode/keys.env"
    if envf.is_file():
        for ln in envf.read_text().splitlines():
            if ln.startswith("NVIDIA_API_KEY="):
                os.environ["NVIDIA_API_KEY"] = ln.split("=", 1)[1].strip().strip('"')
                break
    headers = {"Content-Type": "application/json"}
    if os.environ.get("NVIDIA_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['NVIDIA_API_KEY']}"

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
        print(f"2) rodada {rodada}/{rodadas} ({len(HELDOUT3)} falas):")
        cert = 0
        pt, ct = [], []
        lat = []
        por_rotulo, por_classe = {}, {}
        for utter, expected, cls in HELDOUT3:
            payload = {
                "model": modelo,
                "messages": [
                    {"role": "system", "content": CLASS_SYS},
                    {"role": "user", "content": utter}],
                "max_tokens": n_predict, "temperature": 0}
            import urllib.error
            import urllib.request
            req = urllib.request.Request(
                base + "/chat/completions", data=json.dumps(payload).encode(),
                headers=headers)
            t = time.time()
            j = None
            for tentativa in range(4):
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as r:
                        j = json.loads(r.read().decode())
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 429:
                        # (19/11) MEDIDO: o nv-gate e' 8 RPM + burst 2; o 429
                        # aqui e' a FILA da cota, nao um erro do modelo. Entao
                        # espera e tenta de novo, e o veredito nao se perde.
                        espera = espera_429 * (tentativa + 1)
                        print(f"   429 (cota): esperando {espera:.0f}s", flush=True)
                        time.sleep(espera)
                        continue
                    print(f"   ERRO HTTP {e.code}")
                    break
                except Exception as e:
                    print(f"   ERRO {type(e).__name__}: {e}")
                    break
            if j is None:
                break
            lat.append(time.time() - t)
            u = j.get("usage") or {}
            txt = ""
            for ch in (j.get("choices") or []):
                txt = (ch.get("message") or {}).get("content") or ch.get("text") or ""
                if txt:
                    break
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

    if not accertos_rodadas:
        print("   (nenhuma medicao)")
        return 2

    n = len(HELDOUT3)
    media = statistics.mean(accertos_rodadas)
    desvio = statistics.pstdev(accertos_rodadas) if len(accertos_rodadas) > 1 else 0.0
    tok_medio = statistics.mean(tokens_total_rodadas)
    print(f"\n3) RESULTADO do {braco} ({len(accertos_rodadas)} rodadas):")
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
        "adapter": braco, "modelo": modelo, "base": base,
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
    Path(f"/tmp/opencode/token-{braco}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n   resultado: /tmp/opencode/token-{braco}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
