"""Mede o gate v10 (Kaggle) no heldout3, com o MESMO metodo do v9.

(19/11/2026, coord-naming) Backlog #08 — a peça que faltava: o comparativo
v9 x v10 no conjunto LIMPO (o heldout2 esta contaminado; o heldout3 tem 39
itens e 0 vazamento, provado pelo build_heldout3.py que so grava se
passar).

O METODO (o mesmo do v9, para o numero ser comparavel):
  - o mesmo runner (bench_heldout3.py) e o mesmo heldout3;
  - o mesmo servidor (o MTP 4B :8092), trocando SO o LoRA (v9 -> v10);
  - 3 amostras, como o doc do Codacus usou (o v9 deu 3 amostras identicas).

O QUE ESTE SCRIPT FAZ:
  1) sobe o MTP com o v10 (o mesmo comando do llama-swap --start-mtp, com o
     LoRA trocado) e mede o heldout3;
  2) devolve o v9 e mede de novo (o baseline da mesma maquina, na mesma hora);
  3) grava os dois JSON e imprime o delta.
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
LORA_V10 = MODELS / "loras" / "microturn-4b" / "microturn-4b-lora.gguf"
BIN = pathlib.Path("/home/nixos/projects/llama.cpp/build-stock/bin/llama-server")
PORT = 8092
ENV_SH = REPO / "modules/ai/jarvis/jarvis-env.sh"


def http_json(url, timeout=10):
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def stop_mtp():
    r = subprocess.run(["pgrep", "-f", f"llama-server -m {MTP}"],
                       capture_output=True, text=True)
    pids = [p for p in r.stdout.split() if p.strip()]
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except Exception:
            pass
    if pids:
        print(f"MTP derrubado (pids {pids})")
    time.sleep(4)
    return pids


def start_mtp(lora, tag):
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
    print(f"subindo o MTP com {tag}: {lora.name}")
    subprocess.Popen(cmd, stdout=log.open("w"), stderr=subprocess.STDOUT,
                     env=env, start_new_session=True)
    for _ in range(120):
        if http_json(f"http://127.0.0.1:{PORT}/v1/models", timeout=5):
            print(f"  :{PORT} responde ({tag})")
            return True
        time.sleep(2)
    print(f"  ERRO: o MTP nao respondeu ({tag}); log: {log}")
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
    v10_existe = LORA_V10.is_file()
    v9_existe = LORA_V9.is_file()
    print(f"v9: {v9_existe} | v10: {v10_existe}")

    resultado = {}
    # --- o v10 ---
    if v10_existe:
        stop_mtp()
        if start_mtp(LORA_V10, "v10"):
            resultado["v10"] = medir("v10")
    # --- o v9 (baseline, mesma maquina, mesma hora) ---
    if v9_existe:
        stop_mtp()
        if start_mtp(LORA_V9, "v9"):
            resultado["v9"] = medir("v9")

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
