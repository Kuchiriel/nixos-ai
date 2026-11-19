#!/usr/bin/env python3
"""Mede o gate de voz (heldout3) em varios bracos e salva o JSON do resultado.

PROPOSITO
    Backlog #08 (Lince): "Codacus 35B-A3B em 6GB via expert-cache vs 8B denso"
    — QUALIDADE (acuracia no heldout3, o conjunto limpo) e DUR (duracao por
    ciclo: subida do modelo + 39 classificacoes + teardown).

    O runner oficial do heldout3 e `benchmarks/voice/bench_heldout3.py`
    (Cervo/sweep). Este script NAO o substitui: ele usa o MESMO conjunto
    (`benchmarks/voice/heldout3.py`), o MESMO prompt (`CLASS_SYS` de
    `scripts/duplex-voice.py`) e o MESMO parse de rotulo, e acrescenta o que
    o oficial nao tem:
      - N amostras no MESMO servidor (o oficial roda 1 vez);
      - o timeout por chamada e parametrizavel (o oficial usa 8 s, que o 35B
        nao alcanca: 2,2 s POR TOKEN => ~25 s por fala);
      - o ciclo de vida do braco (sobe o 35B pelo unit do registry, que e a
        fonte de verdade dos flags, e devolve a GPU no fim);
      - o braco sem LoRA (o 8B denso nao tem LoRA de voz: o POST
        /lora-adapters do classificador oficial FALHA e o official runner
        marca tudo como NONE — medindo o harness, nao o modelo).

USO
    cd ~/projects/nixos-ai
    # 35B do Codacus (unit do registry, porta 8085), 3 amostras:
    nix develop --command python3 scripts/bench-35b-codacus.py --arm 35b --samples 3
    # 8B denso (bonsai, porta 8080), sem LoRA:
    nix develop --command python3 scripts/bench-35b-codacus.py --arm 8b --samples 3 --lora off
    # fumaca (2 itens) contra um servidor ja no ar:
    nix develop --command python3 scripts/bench-35b-codacus.py --arm none \
        --base http://127.0.0.1:8085 --lora on --limite 2

EXEMPLO DE SAIDA
    {"arm": "35b", "acertos": 31, "total": 39, "acuracia": 0.7949,
     "lat_media_ms": 15432.1, "dur_ciclo_s": 641.2, ...}

DEPENDENCIAS
    numpy/requests vivem no devShell: rode sempre sob `nix develop`.
"""
import argparse
import importlib.util
import json
import os
import re
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path("/home/nixos/projects/nixos-ai")
UNIT_35B = "llama-duplex-35b.service"
PORT_35B = 8085
PORT_8B = 8080


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    argv = sys.argv[:]
    spec.loader.exec_module(mod)
    sys.argv = argv
    return mod


def carregar():
    """Importa o conjunto (heldout3) e o classificador oficial (duplex-voice)."""
    sys.path.insert(0, str(REPO / "modules/ai/jarvis/src"))
    sys.path.insert(0, str(REPO / "benchmarks/voice"))
    from heldout3 import HELDOUT3  # noqa: E402
    dv = _load(REPO / "scripts/duplex-voice.py", "dv_ref")
    return HELDOUT3, dv


def classificar(dv, base, utter, lora, timeout):
    """Uma fala -> rotulo. Mesmo prompt/parse do classificador oficial.

    lora=True  : aplica o adapter 0 antes da chamada (igual ao oficial).
    lora=False : nao toca em /lora-adapters (para o braco sem LoRA de voz).
    """
    t0 = time.monotonic()
    try:
        if lora:
            dv.http(base + "/lora-adapters", [{"id": 0, "scale": 1.0}], timeout=10)
        prompt = (f"<|im_start|>system\n{dv.CLASS_SYS}<|im_end|>\n"
                  f"<|im_start|>user\n{utter}<|im_end|>\n"
                  f"<|im_start|>assistant\n")
        j = dv.http(base + "/completion", {
            "prompt": prompt, "n_predict": 6, "temperature": 0,
            "stop": ["<|im_end|>"], "cache_prompt": True}, timeout=timeout)
        raw = str(j.get("content", "")).strip()
        out = re.sub(r"<think>.*?</think>", " ", raw, flags=re.DOTALL).strip().upper()
        for lab in dv.CLASS_LABELS:
            if out.startswith(lab):
                return lab, raw, time.monotonic() - t0, None
        for lab in dv.CLASS_LABELS:
            if re.search(r"\b" + lab + r"\b", out):
                return lab, raw, time.monotonic() - t0, None
        return None, raw, time.monotonic() - t0, "sem_rotulo"
    except Exception as exc:
        return None, "", time.monotonic() - t0, f"{type(exc).__name__}: {exc}"


def espera_pronto(base, timeout=1800):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            import urllib.request
            with urllib.request.urlopen(base + "/v1/models", timeout=5) as r:
                if r.status == 200:
                    return time.time() - t0
        except Exception:
            time.sleep(5)
    return None


def sh(cmd, timeout=300):
    return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True,
                          text=True, timeout=timeout)


def amostra(dv, base, itens, lora, timeout):
    cm = defaultdict(Counter)
    cls_cm = defaultdict(Counter)
    lat = []
    erros = []
    correct = 0
    for utter, expected, cls in itens:
        lab, raw, dt, err = classificar(dv, base, utter, lora, timeout)
        lat.append(dt * 1000)
        cm[expected][lab or "NONE"] += 1
        cls_cm[cls][lab or "NONE"] += 1
        if lab == expected:
            correct += 1
        if err:
            erros.append({"fala": utter[:60], "erro": err, "raw": raw[:80]})
    total = len(itens)
    return {
        "total": total, "acertos": correct,
        "acuracia": round(correct / total, 4) if total else 0,
        "erros": len(erros), "erros_detalhe": erros[:5],
        "lat_media_ms": round(statistics.mean(lat), 1) if lat else 0,
        "lat_mediana_ms": round(statistics.median(lat), 1) if lat else 0,
        "lat_p95_ms": round(sorted(lat)[int(0.95 * (len(lat) - 1))], 1) if lat else 0,
        "lat_min_ms": round(min(lat), 1) if lat else 0,
        "lat_max_ms": round(max(lat), 1) if lat else 0,
        "por_rotulo": {k: {"n": sum(v.values()), "acertos": v.get(k, 0),
                           "pred": dict(v)} for k, v in cm.items()},
        "por_classe": {k: {"n": sum(v.values()), "pred": dict(v)}
                       for k, v in sorted(cls_cm.items())},
    }


def oficial(base, timeout=1800):
    """Roda o runner oficial (benchmarks/voice/bench_heldout3.py) como afericao."""
    r = subprocess.run([sys.executable, str(REPO / "benchmarks/voice/bench_heldout3.py"),
                        "--base", base, "--json"], capture_output=True, text=True,
                       timeout=timeout, cwd=str(REPO))
    try:
        return json.loads(r.stdout[r.stdout.index("{"):])
    except Exception:
        return {"rc": r.returncode, "stdout": r.stdout[-400:], "stderr": r.stderr[-400:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["35b", "8b", "none"], default="none")
    ap.add_argument("--base", default=None)
    ap.add_argument("--lora", choices=["on", "off"], default="on")
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--limite", type=int, default=0,
                    help="usa so N itens (fumaca); 0 = conjunto inteiro")
    ap.add_argument("--timeout", type=int, default=180,
                    help="timeout por chamada, em segundos")
    ap.add_argument("--out", default=None)
    ap.add_argument("--oficial", action="store_true",
                    help="roda tambem o runner oficial (afericao de metodo)")
    ap.add_argument("--nao-parar", action="store_true",
                    help="nao desliga o braco no fim (para medir depois)")
    args = ap.parse_args()

    HELDOUT3, dv = carregar()
    itens = HELDOUT3[:args.limite] if args.limite else HELDOUT3
    lora = args.lora == "on"

    base = args.base
    if args.arm == "35b":
        base = base or f"http://127.0.0.1:{PORT_35B}"
        if not args.nao_parar:
            print("subindo o 35B pelo unit do registry (flags em models.nix)...", flush=True)
            sh(["sudo", "-n", "systemctl", "start", UNIT_35B])
        dt = espera_pronto(base)
        if dt is None:
            print(f"ERRO: {base} nao respondeu", file=sys.stderr)
            return 2
        print(f"35B de pe em {dt:.0f}s", flush=True)
    elif args.arm == "8b":
        base = base or f"http://127.0.0.1:{PORT_8B}"
        print("subindo o 8B denso (llm-swap.sh bonsai)...", flush=True)
        sh(["bash", str(REPO / "scripts/llm-swap.sh"), "bonsai"], timeout=900)
        dt = espera_pronto(base)
        if dt is None:
            print(f"ERRO: {base} nao respondeu", file=sys.stderr)
            return 2
        print(f"8B de pe em {dt:.0f}s", flush=True)
    else:
        if not base:
            print("ERRO: --arm none exige --base", file=sys.stderr)
            return 2
        dt = espera_pronto(base, timeout=60)
        if dt is None:
            print(f"ERRO: {base} nao respondeu", file=sys.stderr)
            return 2

    ciclo_t0 = time.time()
    destino = args.out or (REPO / "benchmarks/model-tiers/results" /
                            f"heldout3-{args.arm}-{time.strftime('%Y%m%d-%H%M%S')}.json")
    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    amostras = []
    out = {
        "arm": args.arm, "base": base, "lora": lora, "samples": args.samples,
        "itens": len(itens), "subida_s": round(dt, 1) if dt else None,
        "dur_ciclo_s": None,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "amostras": amostras,
        "acuracia_media": None, "acertos_medio": None, "lat_media_ms_media": None,
    }

    def salvar():
        out["dur_ciclo_s"] = round(time.time() - ciclo_t0, 1)
        if amostras:
            out["acuracia_media"] = round(sum(a["acuracia"] for a in amostras) / len(amostras), 4)
            out["acertos_medio"] = round(sum(a["acertos"] for a in amostras) / len(amostras), 2)
            out["lat_media_ms_media"] = round(
                sum(a["lat_media_ms"] for a in amostras) / len(amostras), 1)
        Path(destino).write_text(json.dumps(out, ensure_ascii=False, indent=1))

    for i in range(args.samples):
        t0 = time.time()
        a = amostra(dv, base, itens, lora, args.timeout)
        a["dur_amostra_s"] = round(time.time() - t0, 1)
        amostras.append(a)
        salvar()  # salva APOS cada amostra: um ciclo de 45 min nao pode
        # ser perdido se o processo for interrompido no meio
        print(f"amostra {i+1}/{args.samples}: {a['acertos']}/{a['total']} "
              f"({a['acuracia']*100:.1f}%) lat_media={a['lat_media_ms']:.0f}ms "
              f"dur={a['dur_amostra_s']:.0f}s erros={a['erros']}", flush=True)

    if args.oficial:
        out["oficial"] = oficial(base)
        salvar()

    print(json.dumps({k: v for k, v in out.items() if k != "amostras"},
                     ensure_ascii=False, indent=1))
    print(f"resultado: {destino}")

    if args.arm == "35b" and not args.nao_parar:
        sh(["sudo", "-n", "systemctl", "stop", UNIT_35B])
        print("35B desligado")
    elif args.arm == "8b" and not args.nao_parar:
        sh(["bash", str(REPO / "scripts/llm-swap.sh"), "release"])
        print("GPU devolvida")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
