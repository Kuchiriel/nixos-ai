#!/usr/bin/env bash
# bench-llm.sh — benchmark padrão da casa (consolida os one-offs de 24/09).
# Protocolo: warmup 2×64 + 3 reps n=128 (PP: prompts DISTINTOS por rep —
# cache-trap mata o número); binário path+version NA evidência (R1 BINARIES.md);
# router dance opcional (-R). Saída: TSV stdout (pipe-friendly) + append JSONL.
#
# Uso:
#   scripts/bench-llm.sh -b <wrapper|bin> -m <model.gguf> [-n N] [-g tag] [-o out] [-R] -- [flags do server...]
#   scripts/bench-llm.sh -b /home/nixos/projects/nixos-ai/modules/ai/llama-ik-wrapper.sh \
#       -m /nix/store/...-Qwen3.6-35B-A3B-UD-Q4_K_M.gguf -n 2 -g ik35-base -- -ngl 45 --n-cpu-moe 35 -t 8
#   ATENÇÃO: flags do server SEMPRE após `--` (getopts come `-ngl` como `-n gl`!).
#   -R = para/religa llama-cpp-server (router) em volta do bench
#   -n N = reps (default 3) · -g "tag" = rótulo no resultado
# stdin: nada. stdout: TSV tag/rep/tgs/pps. stderr: logs do server.
# side-effects: server efêmero :8095 (se ocupado: pkill anterior); nenhum arquivo
#               além do --out (default /tmp/bench-results.jsonl).
set -euo pipefail
BIN="" MODEL="" REPS=3 TAG="bench" ROUTER=0 OUT=/tmp/bench-results.jsonl PORT=8095
while getopts "b:m:n:g:o:R" o; do case $o in
  b) BIN=$OPTARG;; m) MODEL=$OPTARG;; n) REPS=$OPTARG;; g) TAG=$OPTARG;;
  o) OUT=$OPTARG;; R) ROUTER=1;; *) echo "flag inválida" >&2; exit 1;;
esac; done
[ -z "$BIN" ] || [ -z "$MODEL" ] && { echo "precisa -b e -m" >&2; exit 1; }
# Guard 24/09: `-ngl` sem `--` é comido como `-n gl` (REPS vira lixo e o
# server morre com arg posicional). Falha cedo com mensagem útil.
case "$REPS" in ''|*[!0-9]*) echo "REPS inválido ('$REPS'): flags do server vão após \`--\`" >&2; exit 1;; esac
shift $((OPTIND-1)); EXTRA="$@"

run() { $BIN "$@"; }   # -b = PREFIXO de comando (ex.: "bash run-prism.sh llama-server" ou wrapper direto)

# Evidência R1: binário versionado no log
echo "BIN=$(readlink -f "$BIN" 2>/dev/null || echo "$BIN")" >&2
run --version >&2 2>/dev/null || true

if [ $ROUTER = 1 ]; then sudo systemctl stop llama-cpp-server; trap "sudo systemctl start llama-cpp-server" EXIT; fi
pkill -f "port $PORT" 2>/dev/null || true; sleep 2
# Guard VRAM 24/09: um server órfão de bench anterior (4.5GB) impediu o
# router de carregar e a suíte mediu 0/3 achando que era o modelo. Aborta
# se outro llama-server segura peso de modelo além das embeddings/rerank.
# (if, NUNCA `[ ] && exit` — com set -e o false mata o script em silêncio)
for _w in 1 2 3 4 5 6 7 8 9 10; do
  _other=$(for p in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null); do
             m=$(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits 2>/dev/null | awk -F', ' -v P=$p '$1==P {print $2}')
             if [ "${m:-0}" -gt 1200 ]; then echo x; fi; done | wc -l)
  if [ "${_other:-0}" -eq 0 ]; then break; fi
  sleep 3
done
if [ "${_other:-0}" -gt 0 ]; then
  _used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
  echo "ABORT: outro llama-server com ${_used}MiB em uso — VRAM ocupada, veredito seria inválido" >&2
  exit 1
fi


run -m "$MODEL" --host 127.0.0.1 --port $PORT $EXTRA > /tmp/bench-srv-$TAG.log 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null; pkill -f "port $PORT" 2>/dev/null' EXIT
for i in $(seq 1 300); do
  curl -sf --max-time 2 http://127.0.0.1:$PORT/health >/dev/null 2>&1 && break
  kill -0 $PID 2>/dev/null || { echo "server morreu no load" >&2; exit 1; }
  sleep 2
done
curl -sf --max-time 2 http://127.0.0.1:$PORT/health >/dev/null || { echo "server não subiu (ver /tmp/bench-srv-$TAG.log)" >&2; exit 1; }

# warmup (2×) — PP usa prompts distintos por rep (cache-trap: prompt_n=1)
gen_prompt() { python3 -c "print('def f$i(x): ' + 'x' * $1 + ' return x' * $1)"; }
for w in 1 2; do
  curl -sf --max-time 300 http://127.0.0.1:$PORT/completion -H 'Content-Type: application/json' \
    -d "{\"prompt\": \"$(gen_prompt $w)\", \"n_predict\": 64}" >/dev/null
done
for r in $(seq 1 $REPS); do
  curl -sf --max-time 300 http://127.0.0.1:$PORT/completion -H 'Content-Type: application/json' \
    -d "{\"prompt\": \"$(gen_prompt $((10 + r)))\", \"n_predict\": 128}" \
    | python3 -c "
import json,sys
d=json.load(sys.stdin); t=d.get('timings',{})
print(f\"$TAG\trep$r\t{t.get('predicted_per_second',0):.1f}\t{t.get('prompt_per_second',0):.0f}\")
json.dump({'tag':'$TAG','rep':$r,'tg':t.get('predicted_per_second',0),'pp':t.get('prompt_per_second',0)}, open('$OUT','a'))"
done
