#!/bin/sh
# Wrapper for ik_llama.cpp fork (MoE offload: -n-cpu-moe/--cpu-moe + CUDA).
# LD_LIBRARY_PATH (nix store libs + driver) é definido pelo systemd Environment
# em modules/services/llama-cpp.nix — ver profile `chat` em modules/ai/models.nix.
# (13/11) build migrado para o NVMe junto dos modelos (o checkout em
# ~/projects/ik_llama.cpp foi removido na limpeza).
exec /var/lib/ai/models/ik-llama/build/bin/llama-server "$@"
