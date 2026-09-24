#!/bin/sh
# Wrapper for ik_llama.cpp fork (MoE offload: -n-cpu-moe/--cpu-moe + CUDA).
# LD_LIBRARY_PATH (nix store libs + driver) é definido pelo systemd Environment
# em modules/services/llama-cpp.nix — ver profile `chat` em modules/ai/models.nix.
exec /home/nixos/projects/ik_llama.cpp/build/bin/llama-server "$@"
