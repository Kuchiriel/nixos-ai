#!/usr/bin/env bash
# Converte um adapter LoRA (saida do Kaggle ou de um treino local) para GGUF.
# Nao toca em producao: o destino default e um ARQUIVO NOVO em /tmp/opencode,
# nunca o --lora da unit. Depois, a troca e um passo manual do dono (a voz e viva).
#
# Uso:
#   benchmarks/voice/convert-gate-lora.sh <adapter_dir> [outfile]
#
# <adapter_dir>: diretorio com adapter_model.safetensors + adapter_config.json
#                (saida do kernel Kaggle "duplex-gate-lora", baixada com
#                "kaggle kernels output kuchiriel/duplex-gate-lora -p <dir>")
# [outfile]    : caminho do .gguf de saida (default /tmp/opencode/<nome>-<outtype>.gguf)
#
# Exemplo apos o kernel completar:
#   mkdir -p /tmp/opencode/gate-out && kaggle kernels output kuchiriel/duplex-gate-lora -p /tmp/opencode/gate-out
#   benchmarks/voice/convert-gate-lora.sh /tmp/opencode/gate-out/duplex_gate_lora /tmp/opencode/duplex-gate-v3-lora.q8_0.gguf
#
# Ambiente: usa o venv do karaok (tem transformers/torch) + LD_LIBRARY_PATH do nix glm.
set -euo pipefail

ADAPTER="${1:?uso: convert-gate-lora.sh <adapter_dir> [outfile]}"

if [ ! -f "$ADAPTER/adapter_model.safetensors" ] && [ ! -f "$ADAPTER/adapter_model.bin" ]; then
  echo "erro: $ADAPTER nao parece um adapter PEFT (falta adapter_model.safetensors/bin)" >&2
  exit 1
fi

NAME="$(basename "$ADAPTER")"
OUT="${2:-/tmp/opencode/${NAME}-q8_0.gguf}"
KARAOK_VENV=/home/nixos/projects/karaok/.venv/bin/python3
LLAMA_CONVERT=/home/nixos/projects/llama.cpp/convert_lora_to_gguf.py

if [ ! -x "$KARAOK_VENV" ]; then
  echo "erro: venv karaok nao encontrado em $KARAOK_VENV" >&2
  exit 1
fi
if [ ! -f "$LLAMA_CONVERT" ]; then
  echo "erro: convert_lora_to_gguf.py nao encontrado em $LLAMA_CONVERT" >&2
  exit 1
fi

LD_LIBRARY_PATH=/nix/store/dqj57l1prad38vjrad4bs9d977i4q5zm-gcc-15.3.0-lib/lib:/nix/store/6s4wm3zl2y0v5g998n2g88k1zh3vf2pr-zlib-1.3.2/lib \
  "$KARAOK_VENV" "$LLAMA_CONVERT" \
  --base /var/lib/ai/models/Qwen3.5-4B-MTP-Q4_K_M.gguf \
  --outtype q8_0 \
  --outfile "$OUT" \
  "$ADAPTER"

echo "adapter convertido em: $OUT"
echo "NAO aplicado em producao. A/B contra o held-out de 52 antes de trocar o --lora da unit."
