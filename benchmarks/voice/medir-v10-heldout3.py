"""Mede o gate v10 no heldout3, DEVOLVENDO a GPU ao lab no fim.

O PROBLEMA (18/11, sweep-2026-11, redteam/matrix): a primeira tentativa de
subir o MTP com o v10 falhou com "cudaMalloc failed: out of memory" ao
alocar o KV cache. CAUSA: o laboratorio A/B estava RODANDO (ab_loop.control
= 'run') e tinha a GPU: o 35B-A3B (2.390 MiB) e o bonsai (2.276 MiB), com
so 720 MiB livres. Nao e' problema do v10: e' disputa de GPU.

A CORRECAO (na sequencia, sem brigar com o lab): o script ESPERA a janela em
que o lab devolve a GPU entre ciclos, sobe o braco, mede e DERRUBA o servidor
no fim. A regra da casa e' explicita: "NUNCA deixe a GPU com o braco e o
lab juntos" e "GPU emprestada, nao pegue sem coordinate" — entao a medicao
espera, e se a janela nao vier, ela sai sem medir e diz isso.

O QUE ESTE SCRIPT FAZ:
1) espera (ate N minutos) a VRAM livre chegar a um piso e o lab nao estar
   segurando a GPU;
2) sobe o MTP na :8096 com o LoRA pedido, com o adapter carregado;
3) roda o bench_heldout3 e imprime a acuracia por rotulo e por classe;
4) DERRUBA o servidor no fim (devolve a GPU).

O QUE ELE NAO FAZ: nao toca na producao (:8092), nao reinicia o opencode,
nao mexe no estado do lab, nao para o lab, nao toma a GPU a force.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/home/nixos/projects/nixos-ai")
LORA = sys.argv[1]
BASE = "http://127.0.0.1:8096"
ESPERA_MIN = int(sys.argv[2]) if len(sys.argv) > 2 else 30
VRAM_PISO = 4300        # MiB livres: o MTP precisa ~3600 + folga do KV
LLAMA = "/home/nixos/projects/llama.cpp/build-stock/bin/llama-server"
MODELO = "/var/lib/ai/models/Qwen3.5-4B-MTP-Q4_K_M.gguf"


def run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def vram_livre():
    r = run(["nvidia-smi", "--query-gpu=memory.free",
             "--format=csv,noheader,nounits"], timeout=30)
    try:
        return int(r.stdout.strip().splitlines()[0])
    except Exception:
        return 0


def lab_presente():
    r = run(["ps", "-eo", "args"], timeout=30)
    return any("ab_loop.sh" in ln for ln in r.stdout.splitlines())


def porta_viva(p):
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{p}/v1/models", timeout=3).read()
        return True
    except Exception:
        return False


def derruba(p):
    out = run(["ss", "-ltnp"], timeout=60).stdout
    for ln in out.splitlines():
        if f":{p} " in ln:
            for pid in re.findall(r"pid=(\d+)", ln):
                try:
                    os.kill(int(pid), 9)
                except Exception:
                    pass


print(f"1) esperando a janela do lab (piso {VRAM_PISO} MiB livres, ate "
      f"{ESPERA_MIN} min)")
inicio = time.time()
livre = 0
while (time.time() - inicio) < ESPERA_MIN * 60:
    ok, livre = (vram_livre() >= VRAM_PISO and not lab_presente()), vram_livre()
    if ok:
        print(f"   janela livre: {livre} MiB livres, lab fora")
        break
    print(f"   VRAM {livre} MiB | lab {'presente' if lab_presente() else 'fora'}"
          f" | faltam {ESPERA_MIN - int((time.time() - inicio) // 60)} min",
          flush=True)
    time.sleep(30)
else:
    print(f"   SEM JANELA em {ESPERA_MIN} min (VRAM {livre} MiB). A medicao do "
          f"v10 precisa da GPU; nao peguei a GPU do lab.")
    sys.exit(2)

print("\n2) subindo o MTP com", Path(LORA).name)
derruba(8096)
time.sleep(2)
log = "/tmp/opencode/mtp-lora-measure.log"
with open(log, "w") as f:
    subprocess.Popen(
        [LLAMA, "-m", MODELO, "--host", "127.0.0.1", "--port", "8096",
         "-ngl", "99", "-t", "6", "-c", "12288", "-b", "256", "-ub", "256",
         "-fa", "off", "-ctk", "f16", "-ctv", "f16",
         "--alias", "jarvis-mtp-lora", "--parallel", "1", "--jinja",
         "--reasoning", "off", "--spec-type", "draft-mtp",
         "--lora", LORA, "--lora-init-without-apply"],
        stdout=f, stderr=f, cwd="/tmp", start_new_session=True)
for i in range(90):
    if porta_viva(8096):
        print(f"   :8096 responde ({i}s), VRAM livre {vram_livre()} MiB")
        break
    time.sleep(1)
else:
    print("   NAO respondeu em 90s")
    print(open(log).read()[-600:])
    derruba(8096)
    sys.exit(1)

try:
    print("\n3) bench no heldout3:")
    r = subprocess.run(
        ["nix", "develop", "--command", "python3",
         "benchmarks/voice/bench_heldout3.py", "--base", BASE, "--json"],
        capture_output=True, text=True, timeout=3600, cwd=str(REPO))
    saida = (r.stdout or "") + (r.stderr or "")
    for l in saida.splitlines():
        if l.startswith("TOTAL") or re.match(r"^[A-Z]+\s+acc ", l):
            print("   ", l[:150])
    i = saida.rfind("\n{")
    if i > 0:
        j = saida.rfind("}") + 1
        d = json.loads(saida[i:j])
        Path("/tmp/opencode/heldout3-resultado.json").write_text(
            json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\n4) resumo:")
        print("   TOTAL", d["acertos"], "/", d["total"], "| lat",
              d["lat_media_ms"], "ms")
        for exp, v in d.get("por_rotulo", {}).items():
            print(f"     {exp:8} {v['acertos']}/{v['n']}  {v['pred']}")
        emer = ["mordida de animal", "inseto", "anafilaxia",
                "insolacao exaustao", "epistaxe", "meningite",
                "febre em crianca"]
        print("   as 7 classes de emergencia:")
        for c in emer:
            p = d.get("por_classe", {}).items()
            pc = d.get("por_classe", {}).get(c, {})
            print(f"     {c:22} n={pc.get('n','-')} {pc.get('pred')}")
finally:
    print("\n5) devolvendo a GPU:")
    derruba(8096)
    print("   :8096 derrubado")
