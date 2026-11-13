#!/bin/sh
# Wrapper for PrismML llama.cpp fork (Ternary Bonsai Q2_0 kernels + CUDA).
# LD_LIBRARY_PATH (nix store libs + driver) é definido pelo systemd Environment
# em modules/services/llama-cpp.nix — ver profile `bonsai` em modules/ai/models.nix.
# (13/11) b10743 (adfffbe41) foi perdido na limpeza de disco; o b10735
# (presente, 24/09) le os mesmos layouts Q2_0/PQ2_0/PTQ — e o build que o
# router usava antes do b10743. Perde-se so o kernel de CPU extra do b10743;
# se o bonsai regredir, rebuildar o fork PrismML-Eng/llama.cpp em adfffbe41.
#
# ATENCAO: este caminho e o LD_LIBRARY_PATH em modules/services/llama-cpp.nix
# sao o mesmo valor em DOIS lugares. Trocar o build exige trocar os dois, senao
# o service roda com binario velho e o rebuild nao evidencia. (A regra de
# 'models.nix como fonte unica' ainda nao cobre este par; candidato a var.)
exec /home/nixos/projects/prism-bin/llama-prism-b10735-842b188/llama-server "$@"

