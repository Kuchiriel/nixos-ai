#!/bin/sh
# Wrapper for PrismML llama.cpp fork (Ternary Bonsai Q2_0 kernels + CUDA).
# LD_LIBRARY_PATH (nix store libs + driver) é definido pelo systemd Environment
# em modules/services/llama-cpp.nix — ver profile `bonsai` em modules/ai/models.nix.
# b10743 (25/09): traz os kernels de CPU dos quants ternarios que faltavam
# no b10735 — SSE2/SSSE3 vec_dot para PTQ1_0/PQ2_0 (#248) e PQ2_0 AVX-512
# VNNI gemm (#256). Verificado: build 10743, commit adfffbe41.
#
# ATENCAO: este caminho e o LD_LIBRARY_PATH em modules/services/llama-cpp.nix
# sao o mesmo valor em DOIS lugares. Trocar o build exige trocar os dois, senao
# o service roda com binario velho e o rebuild nao evidencia. (A regra de
# 'models.nix como fonte unica' ainda nao cobre este par; candidato a var.)
exec /home/nixos/projects/prism-bin/llama-prism-b10743-adfffbe/llama-server "$@"

