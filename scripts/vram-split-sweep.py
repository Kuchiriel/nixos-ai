#!/usr/bin/env python3
"""Sweep de split GPU/CPU: onde o MoE (e o denso) perdem velocidade.

Pergunta que este script responde, com número local: "por que putting
mais pesos na GPU não muda o t/s?" — a intuição diz que deveria.

Hipóteses testáveis (da literatura):
  H1  **TG (geração) escala com o que está RESIDENTE na VRAM.** Se for
      verdade, num modelo 4B que cabe inteiro nos 6GB, -ngl 0 (CPU) vs
      -ngl 999 (GPU) deve dar um salto grande. Se NÃO der, o gargalo
      não é placement e a hipótese morre aqui (barato: 2,4GB).
  H2  **PP (prefill) é o que o threshold de offload controla.** No
      ik_llama.cpp, matmuls de experts na RAM só vão à GPU se
      batch >= 32 * total_experts/active_experts (≈1024 p/ 35B-A3B).
      Portanto variar o threshold só muda PP, nunca TG.
  H3  **TG com experts na RAM é limitado por BANDA DE RAM**, não por
      PCIe nem por clock. Se for isso, mais experts na VRAM só ajuda
      quando o *caminho ativo* cabe na VRAM — o que é impossível com
      6GB e um modelo de 20GB.

Método: para cada configuração, sobe o llama-server, espera /health,
manda um prompt FIXO (mesma seed, mesmo temperature), e lê PP/TG dos
`timings` que o próprio llama-server devolve. Amostra VRAM e
utilização da GPU durante a geração — porque "VRAM alocada" e "GPU
trabalhando" são coisas diferentes, e é exatamente essa diferença que
explica t/s igual em configs diferentes.

Nada é apagado; a evidência vai para JSON datado.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

EVIDENCE = Path("scripts/overnight-24-09/vram-split-sweep.json")

# PRECONDICAO (25/09): nenhuma outra llama-server pode estar rodando.
# Descobri o jeito caro: um sweep interrompido deixou o 27B vivo em RAM+VRAM
# e o bonsai de PRODUCAO caiu de 70,1 t/s (mediana de 3) para 38,7 t/s — uma
# variacao de 1,8x que eu tinha atribuido a 'bimodal inexplicavel' e quase
# chasei como bug de config. Nao era: era contencao. Vale para TODOS os
# numeros ja medidos: os que tinham outro processo vivo nao sao confiaveis.
# O sweep nao pode matar processos de terceiros; ele so RECUSA de medir.

# Prompt fixo: longo o bastante para ter PP mensurável, e o MESMO texto
# em toda configuração (é a variável de controle).
PROMPT = (
    "Escreva um relatório técnico detalhado de 4 parágrafos sobre como "
    "implementar cache de embeddings em um sistema de recuperação "
    "semântica local, cobrindo indexação, busca híbrida, reranking e "
    "avaliação de qualidade. Seja específico e use exemplos."
)


@dataclass
class Amostra:
    modelo: str
    rotulo: str
    ngl: int
    n_cpu_moe: int | None
    threads: int
    ctx: int
    port: int
    carregou: bool = False
    erro: str = ""
    pp_tps: float | None = None
    tg_tps: float | None = None
    tps_relatido: float | None = None
    segundos: float | None = None
    vram_mb: int | None = None
    vram_delta_mb: int | None = None
    vram_livre_antes_mb: int | None = None
    gpu_util_pct: int | None = None
    ram_rss_gb: float | None = None
    raw_timings: dict = field(default_factory=dict)


def nvidia(padrao: str) -> str:
    try:
        return subprocess.run(
            ["nvidia-smi", f"--query-gpu={padrao}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip().split("\n")[0]
    except Exception:  # noqa: BLE001
        return ""


def rss_gb(pid: int) -> float | None:
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return round(int(out) / 1048576, 2) if out else None
    except Exception:  # noqa: BLE001
        return None


def espera_saude(port: int, proc: subprocess.Popen, timeout: int = 900) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3):
                return True
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return False


def uma_config(binpath: str, modelo: str, rotulo: str, port: int, *,
               ngl: int, n_cpu_moe: int | None, threads: int, ctx: int,
               extra: list[str] | None = None,
               allow_contention: bool = False) -> Amostra:
    a = Amostra(modelo=os.path.basename(modelo), rotulo=rotulo, ngl=ngl,
                n_cpu_moe=n_cpu_moe, threads=threads, ctx=ctx, port=port)
    cmd = [binpath, "-m", modelo, "--host", "127.0.0.1", "--port", str(port),
           "-ngl", str(ngl), "-t", str(threads), "-c", str(ctx),
           "-fa", "on", "--cache-type-k", "q4_0", "--cache-type-v", "q4_0",
           "--jinja"]
    if n_cpu_moe is not None:
        cmd += ["--n-cpu-moe", str(n_cpu_moe)]
    if extra:
        cmd += extra
    # VRAM ABSOLUTA é inútil com outro modelo residente (medido 25/09: o
    # ngl0 reportou 4763MB que eram do bonsai, não do modelo testado). E
    # sem VRAM livre o ngl99 morre com cudaMalloc OOM. Então: snapshot
    # antes, delta depois, e recusa se não houver folga.
    vram_antes = int(nvidia("memory.used") or 0)
    # So conta MODELO DE CHAT. Embeddings e reranker sao servicos de apoio e
    # ficam parados durante a medicao; conta-los seria falso positivo (e o
    # sweep se recusaria sozinho, sem motivo real).
    chat_pids = []
    for pid in subprocess.run(["pgrep", "-f", "llama-server"],
                              capture_output=True, text=True).stdout.split():
        try:
            argv = open(f"/proc/{pid}/cmdline", "rb").read().decode("utf-8", "replace")
        except OSError:
            continue
        if not argv:
            continue
        low = argv.lower()
        if "vram-split-sweep" in low or "nix develop" in low:
            # O proprio sweep aparece no pgrep porque a linha de comando dele
            # contem o caminho do binario. Sem este guarda o precheck casa
            # consigo mesmo e recusa toda medicao (falso positivo).
            continue
        if ".gguf" not in low:
            continue   # so conta quem tem MODELO carregado, nao quem foi invocado
        if ("embed" in low or "rerank" in low or "bge-" in low or "nomic-" in low
                or "models-preset" in low or "--port 8080" in low):
            # Servico de apoio (embeddings/rerank) ou o ROUTER, que apenas
            # entrega os tiers sob demanda e nao segura VRAM. Contar qualquer
            # um deles seria falso positivo — o sweep se recusaria sozinho.
            continue
        chat_pids.append(pid)
    if len(chat_pids) > 0 and not allow_contention:
        a.erro = (f"outro llama-server de CHAT rodando (pids {','.join(chat_pids)}): "
                  "contaminaria a medicao. Pare o outro ou use --allow-contention")
        return a
    vram_total = int(nvidia("memory.total") or 0)
    a.vram_livre_antes_mb = vram_total - vram_antes
    if vram_total - vram_antes < 3500 and ngl > 0:
        a.erro = f"vram_ocupada({vram_antes}MB em uso de {vram_total}MB): pare o outro modelo"
        return a
    log = open(f"/tmp/sweep-{rotulo}.log", "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            preexec_fn=os.setsid)
    try:
        if not espera_saude(port, proc):
            a.erro = "nao_carregou"
            return a
        a.carregou = True
        payload = json.dumps({"model": "x", "prompt": PROMPT, "max_tokens": 300,
                              "temperature": 0.0, "seed": 7}).encode()
        t0 = time.time()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/completion", data=payload,
            headers={"Content-Type": "application/json"})
        # amostra VRAM/util DURANTE a geração
        amostras: list[tuple[int, int]] = []
        import threading

        def poll():
            while not fim.is_set():
                try:
                    amostras.append((int(nvidia("memory.used") or 0),
                                     int(nvidia("utilization.gpu") or 0)))
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(0.7)

        fim = threading.Event()
        th = threading.Thread(target=poll, daemon=True)
        th.start()
        resp = json.load(urllib.request.urlopen(req, timeout=600))
        fim.set()
        a.segundos = round(time.time() - t0, 2)
        tm = resp.get("timings") or {}
        a.raw_timings = {k: tm.get(k) for k in
                         ("prompt_n", "prompt_ms", "prompt_per_second",
                          "predicted_n", "predicted_ms", "predicted_per_second")}
        a.pp_tps = round(float(tm.get("prompt_per_second") or 0), 2) or None
        a.tg_tps = round(float(tm.get("predicted_per_second") or 0), 2) or None
        if amostras:
            a.vram_mb = max(x[0] for x in amostras)
            a.vram_delta_mb = max(x[0] for x in amostras) - vram_antes
            a.gpu_util_pct = round(sum(x[1] for x in amostras) / len(amostras))
        a.ram_rss_gb = rss_gb(proc.pid)
        return a
    except urllib.error.HTTPError as e:  # noqa: PERF203
        a.erro = f"http_{e.code}"
        return a
    except Exception as e:  # noqa: BLE001
        a.erro = f"{type(e).__name__}:{e}"[:120]
        return a
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            time.sleep(3)
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:  # noqa: BLE001
            pass
        log.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--ngl", default="0,99", help="lista de -ngl")
    ap.add_argument("--cpu-moe", default="", help="lista de --n-cpu-moe (MoE)")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--ctx", type=int, default=8192)
    ap.add_argument("--port", type=int, default=8901)
    ap.add_argument("--extra", default="", help="flags extras separadas por espaço")
    ap.add_argument("--allow-contention", action="store_true",
                    help="medir mesmo com outro llama-server vivo (NAO confiavel)")
    args = ap.parse_args()

    ngis = [int(x) for x in args.ngl.split(",") if x.strip()]
    moes = [int(x) for x in args.cpu_moe.split(",") if x.strip()] or [None]
    extra = args.extra.split() if args.extra else None

    resultados: list[Amostra] = []
    port = args.port
    for moe in moes:
        for ngl in ngis:
            rot = f"ngl{ngl}" + (f"-cmoe{moe}" if moe is not None else "")
            print(f"--- {rot}")
            a = uma_config(args.bin, args.model, rot, port, ngl=ngl,
                           n_cpu_moe=moe, threads=args.threads, ctx=args.ctx,
                           extra=extra, allow_contention=args.allow_contention)
            print(f"    carregou={a.carregou} PP={a.pp_tps} TG={a.tg_tps} "
                  f"vram={a.vram_mb}MB gpu={a.gpu_util_pct}% rss={a.ram_rss_gb}GB"
                  f"{' ERRO=' + a.erro if a.erro else ''}")
            resultados.append(a)
            port += 1
            time.sleep(5)

    ok = [a for a in resultados if a.tg_tps]
    base = min(ok, key=lambda a: a.tg_tps) if ok else None
    for a in ok:
        if base and base.tg_tps:
            a.tps_relatido = round(a.tg_tps / base.tg_tps, 2)

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    prev = []
    if EVIDENCE.exists():
        try:
            prev = json.loads(EVIDENCE.read_text(encoding="utf-8")).get("rodadas", [])
        except Exception:  # noqa: BLE001
            prev = []
    prev.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "modelo": args.model, "bin": args.bin,
                 "flags": {"threads": args.threads, "ctx": args.ctx, "extra": extra},
                 "resultados": [asdict(a) for a in resultados]})
    EVIDENCE.write_text(json.dumps({"rodadas": prev}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"\nevidence -> {EVIDENCE}")
    for a in resultados:
        print(f"  {a.rotulo:16s} PP={a.pp_tps} TG={a.tg_tps} x{a.tps_relatido} "
              f"vram={a.vram_mb}MB gpu={a.gpu_util_pct}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
