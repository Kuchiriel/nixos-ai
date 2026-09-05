#!/bin/sh
# Wrapper for PrismML llama.cpp fork (Ternary Bonsai Q2_0 kernels + CUDA).
# LD_LIBRARY_PATH (nix store libs + driver) é definido pelo systemd Environment
# em modules/services/llama-cpp.nix — ver profile `bonsai` em modules/ai/models.nix.
exec /home/nixos/projects/prism-bin/llama-prism-b10660-e311ed3/llama-server "$@"
