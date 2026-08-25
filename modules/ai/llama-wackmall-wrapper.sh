#!/bin/sh
# Wrapper for llama.cpp wackmall build with Expert Hot Store
# Auto-detected CUDA libraries and forwarded all arguments
export LD_LIBRARY_PATH="/run/opengl-driver/lib:${LD_LIBRARY_PATH:-}"
exec /home/nixos/projects/llama-wackmall/build/bin/llama-server "$@"
