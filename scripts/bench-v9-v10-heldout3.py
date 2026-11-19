"""Mede o gate v10 (Kaggle) no heldout3, com o MESMO metodo do v9.

(19/11/2026, coord-naming) Backlog #08 — a peça que faltava: o comparativo
v9 x v10 no conjunto LIMPO (o heldout2 esta contaminado; o heldout3 tem 39
itens e 0 vazamento, provado pelo build_heldout3.py que so grava se
passar).

O METODO (o mesmo do v9, para o numero ser comparavel):
  - o mesmo runner (bench_heldout3.py) e o mesmo heldout3;
  - o mesmo comando de servidor do llama-swap --start-mtp, trocando SO o LoRA
    (v9 -> v10);
  - 3 amostras, como o doc do Codacus usou (o v9 deu 3 amostras identicas).

O QUE ESTE SCRIPT FAZ:
  1) sobe o MTP com o v10 (o mesmo comando do llama-swap --start-mtp, com o
     LoRA trocado) e mede o heldout3;
  2) devolve o v9 e mede de novo (o baseline da mesma maquina, na mesma hora);
  3) grava os dois JSON e imprime o delta.

(19/11, auditoria-runtime) CORRECOES DE PRODUCAO — este script sequestrava a
porta de PRODUCAO:
  - PORT era 8092, a porta do default do sistema (o `llama-uncensored-4b`
    declarativo). O script subia um server NAO supervisionado por cima do
    default e, se era interrompido, deixava o server vivo: medido em
    19/11 05:30, o processo ficou de pe ate as 13h com o adapter v1 (81 MB)
    em vez do v9 (2,9 MB) do registry — o `duplex` classificava com o
    adapter errado e a VRAM ficava presa, impedindo a unit de subir.
  - `stop_mtp()` matava por PATTERN (`pgrep -f 'llama-server -m <mtp>'`),
    ou seja, matava o default de PRODUCAO tambem.
  - `LORA_V10` apontava para `microturn-4b-lora.gguf`, que e' o adapter v1
    (o legado de 81 MB), nao o v10: o "v10" medido seria o v1 com nome novo.
AGORA: porta de medicao dedicada (8094), o v10 aponta para o arquivo real
(conversao do Kaggle) e falha alto se ele nao existir, o default de producao
nao e' tocado (nada de matar por pattern) e o server do script e' derrubado
sempre, inclusive em Ctrl-C.
"""
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

REPO = pathlib.Path("/home/nixos/projects/nixos-ai")
MODELS = pathlib.Path("/var/lib/ai/models")
MTP = MODELS / "Qwen3.5-4B-MTP-Q4_K_M.gguf"
LORA_V9 = MODELS / "loras" / "microturn-4b" / "microturn-4b-lora-v9.gguf"
# (19/11, auditoria-runtime) O v10 e' o adapter convertido do Kaggle (PEFT ->
# GGUF), que vive em /tmp ate ser promovido ao diretorio de producao. O
# arquivo em MODELS/.../microturn-4b-lora.gguf (81 MB) e' o v1 LEGADO: usar
# ele como "v10" media o v1 com nome novo.
LORA_V10 = pathlib.Path("/tmp/opencode/v10-lora-gguf/microturn-4b-lora-v10.gguf")
LORA_V1_LEGADO = MODELS / "loras" / "microturn-4b" / "microturn-4b-lora.gguf"
BIN = pathlib.Path("/home/nixos/projects/llama.cpp/build-stock/bin/llama-server")
# (19/11) Porta de MEDICAO. 8092 e' o default do sistema (producao): usar
# ela sequestrava o default (medido: server orfao ate as 13h com o adapter
# errado). 8096 e' do laboratorio A/B e 8094 a porta livre de medicao.
PORT = 8094
PORTA_PRODUCAO = 8092
ENV_SH = REPO / "modules/ai/jarvis/jarvis-env.sh"

# o processo que ESTE script subiu (unico que ele pode derrubar)
_server_pid = None


def _stop_server():
    """Derruba SO o server que este script subiu (nunca por pattern)."""
    global _server_pid
    if not _server_pid:
        return
    try:
        os.killpg(os.getpgid(_server_pid), signal.SIGTERM)
    except Exception:
        try:
            os.kill(_server_pid, signal.SIGTERM)
        except Exception:
            pass
    print(f"  MTP de medicao derrubado (pid {_server_pid})")
    _server_pid = None
    time.sleep(3)


def _on_signal(signum, frame):
    _stop_server()
    raise SystemExit(128 + signum)


def _vram_livre_mib():
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        return int(r.stdout.strip().splitlines()[0])
    except Exception:
        return None


def http_json(url, timeout=10):
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def porta_ocupada(port):
    import socket
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_mtp(lora, tag):
    global _server_pid
    if porta_ocupada(PORT):
        print(f"  ERRO: a porta de medicao {PORT} ja esta ocupada por outro "
              f"processo — medir agora seria medir o server de outra pessoa. "
              f"Use outra porta ou derrube o dono do processo.")
        return False
    if porta_ocupada(PORTA_PRODUCAO):
        print(f"  AVISO: o default de producao esta de pe na {PORTA_PRODUCAO}; "
              f"esta medicao NAO o toca (o script nunca mata producao), mas a "
              f"VRAM pode nao caber dois MTP ao mesmo tempo.")
    livre = _vram_livre_mib()
    if livre is not None and livre < 4300:
        print(f"  ERRO: VRAM livre {livre} MiB (< 4300): o MTP de medicao nao "
              f"cabe sem derrubar o default. Espere a janela de VRAM "
              f"(regra da casa: 1 LLM por vez) e rode de novo.")
        return False
    env = dict(os.environ)
    nix_ld = "/run/current-system/sw/share/nix-ld/lib"
    if pathlib.Path(nix_ld).is_dir():
        env["NIX_LD_LIBRARY_PATH"] = nix_ld
    cmd = [str(BIN), "-m", str(MTP), "--host", "127.0.0.1", "--port", str(PORT),
           "-ngl", "99", "-t", "6", "-c", "12288", "-b", "256", "-ub", "256",
           "-fa", "off", "-ctk", "f16", "-ctv", "f16",
           "--alias", "jarvis-mtp-lora", "--parallel", "1", "--jinja",
           "--reasoning", "off", "--spec-type", "draft-mtp",
           "--lora", str(lora), "--lora-init-without-apply"]
    log = pathlib.Path(f"/tmp/opencode/mtp-{tag}.log")
    print(f"subindo o MTP de MEDICAO com {tag}: {lora.name} (porta {PORT})")
    proc = subprocess.Popen(cmd, stdout=log.open("w"), stderr=subprocess.STDOUT,
                            env=env, start_new_session=True)
    _server_pid = proc.pid
    for _ in range(120):
        if http_json(f"http://127.0.0.1:{PORT}/v1/models", timeout=5):
            print(f"  :{PORT} responde ({tag})")
            return True
        time.sleep(2)
    print(f"  ERRO: o MTP nao respondeu ({tag}); log: {log}")
    _stop_server()
    return False


def medir(tag, amostras=3):
    """Mede o heldout3 com o MTP da porta PORT."""
    results = []
    for i in range(amostras):
        r = subprocess.run(
            ["bash", "-c",
             f'source "{ENV_SH}" >/dev/null 2>&1; '
             f'export PYTHONPATH="$JARVIS_SRC:${{PYTHONPATH:-}}"; '
             f'"$JARVIS_PY" "{REPO}/benchmarks/voice/bench_heldout3.py" '
             f'--base http://127.0.0.1:{PORT}'],
            capture_output=True, text=True, timeout=3600, cwd=str(REPO))
        txt = r.stdout or ""
        i_json = txt.find("{")
        resumo = {}
        if i_json >= 0:
            try:
                resumo = json.loads(txt[i_json:])
            except Exception:
                resumo = {}
        # o runner imprime o texto ANTES do json; o resumo vem do json
        resumo.setdefault("total", len(txt.splitlines()))
        out = pathlib.Path(f"/tmp/opencode/{tag}-heldout3-amostra{i+1}.json")
        out.write_text(txt)
        acc = resumo.get("acertos", resumo.get("total", "?"))
        lat = resumo.get("lat_media_ms", "?")
        print(f"  {tag} amostra {i+1}: {acc}/{resumo.get('total','?')} | "
              f"lat {lat} ms | erros {resumo.get('erros','?')}")
        results.append({"acertos": acc, "total": resumo.get("total"),
                        "acuracia": resumo.get("acuracia"),
                        "lat_media_ms": lat,
                        "lat_max_ms": resumo.get("lat_max_ms"),
                        "erros": resumo.get("erros"),
                        "por_rotulo": resumo.get("por_rotulo"),
                        "saida": str(out)})
    return results


def main():
    # (19/11) Ctrl-C e SIGTERM derrubam o server de medicao: um orfao na
    # porta de medicao ainda sequestra VRAM e vira default sombra.
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    import atexit
    atexit.register(_stop_server)

    v10_existe = LORA_V10.is_file()
    v9_existe = LORA_V9.is_file()
    print(f"v9: {v9_existe} ({LORA_V9}) | v10: {v10_existe} ({LORA_V10})")
    if not v10_existe and LORA_V1_LEGADO.is_file():
        print(f"  AVISO: o v10 (convertido do Kaggle) NAO esta em {LORA_V10}. "
              f"O arquivo {LORA_V1_LEGADO.name} (81 MB) e' o v1 LEGADO e nao "
              f"serve como v10: medir com ele seria medir o v1 com nome novo. "
              f"Converta o v10 antes de rodar.")

    resultado = {}
    try:
        # --- o v10 ---
        if v10_existe:
            if start_mtp(LORA_V10, "v10"):
                resultado["v10"] = medir("v10")
                _stop_server()
        # --- o v9 (baseline, mesma maquina, mesma hora) ---
        if v9_existe:
            if start_mtp(LORA_V9, "v9"):
                resultado["v9"] = medir("v9")
                _stop_server()
    finally:
        _stop_server()

    pathlib.Path("/tmp/opencode/v9-v10-heldout3.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=1))
    print("\n=== RESUMO ===")
    for tag, res in resultado.items():
        acertos = [r["acertos"] for r in res]
        lat = [r["lat_media_ms"] for r in res]
        print(f"{tag}: acertos {acertos} | lat_media {lat}")
    if "v9" in resultado and "v10" in resultado:
        a9 = resultado["v9"][0]["acertos"]
        a10 = resultado["v10"][0]["acertos"]
        tot = resultado["v9"][0]["total"]
        print(f"delta v10-v9: {a10-a9} de {tot} "
              f"({(a10-a9)/max(1,tot)*100:+.1f} pontos percentuais)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
