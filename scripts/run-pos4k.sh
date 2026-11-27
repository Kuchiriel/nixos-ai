#!/bin/bash
# F99: preparacao de posicao 4096. SEM treino por aqui.
# --check  → so guard, nao executa nada
# --test   → forward rapido em seq4096 (CPU, modelo pequeno), sem GPU
set -uo pipefail
if [ "${1:-}" = "--check" ]; then
  echo "POS4K: --check OK (sem treino, sem GPU; modo=${2:-})"
  exit 0
fi
if [ "${1:-}" != "--test" ]; then
  echo "POS4K: so --check e --test sao permitidos nesta frente" >&2
  exit 2
fi
cd /home/nixos/work/hybrid || exit 8
G=$(ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="$G:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib"
export OMP_NUM_THREADS=1
MODE="${POS_MODE:-learned}"
POS_MODE="$MODE" POS_ROWS=4096 /home/nixos/.venvs/finetune/bin/python -u - <<'PY'
import json, os, time, torch, runpy
Mode = os.environ.get("POS_MODE", "learned")
cls = runpy.run_path("/home/nixos/work/hybrid/scale-loop-pos4k.py")["ScaleLM"]
m = cls(1000, 128, "ngpt_only")  # pequeno: so prova capacidade, nao performance
ids = torch.randint(0, 1000, (1, 4096))
t0 = time.perf_counter()
with torch.no_grad():
    out = m(ids, causal=True)
r = {"pos_mode": Mode, "pos_rows": m.pos.num_embeddings,
     "seq": 4096, "out_shape": list(out.shape),
     "logits_finite": bool(torch.isfinite(out).all()),
     "seconds": round(time.perf_counter() - t0, 2)}
print("RESULT " + json.dumps(r))
PY
