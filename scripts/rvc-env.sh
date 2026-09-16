#!/usr/bin/env bash
# RVC voice-clone env — FONTE CANÔNICA para shells interativos (bash+zsh).
# Source este arquivo em vez de exportar manualmente:
#   source /home/nixos/projects/nixos-ai/scripts/rvc-env.sh
# (home.nix já faz isso em programs.bash.initExtra e programs.zsh.initContent)
#
# NÃO exporta LD_LIBRARY_PATH: o python do venv usa o loader nix-ld
# (patchelf aplicado por rvc-spike-bootstrap.sh) e resolve libstdc++/libz
# sozinho — sem store paths hardcoded, sem quebra por GC.
# Reconstrói pós-reboot com: ./scripts/rvc-spike-bootstrap.sh
# Stack PERSISTENTE primeiro (16/09): kvenv + Applio do lab + assets em
# ~/models/rvc-assets (symlinks predictors/embedders no checkout). O spike
# /tmp/opencode morreu no reboot — ficou só como fallback.
#
# O kvenv (torch pip) precisa do loader do lab-env.sh (libstdc++/CUDA via
# LD_LIBRARY_PATH — sem isso: 'libstdc++.so.6 not found'). Incorporado aqui
# pra o env ser autosso (um source só).
if [ -x "$HOME/kvenv/bin/python" ] && [ -d "$HOME/projects/applio-lab/Applio/rvc" ]; then
  export LD_LIBRARY_PATH="/nix/store/3lpf2hl979sfmyb9f573xq1bz3xkds0v-cuda-merged-12.9/lib:/run/opengl-driver/lib:/nix/store/7vafhlh0lmcvi75jfyy09qwr4m3x1ks3-gcc-15.2.0-lib/lib:/nix/store/483x61iy35irm4wr2b7dwzihljhp6da2-zlib-1.3.2/lib:${LD_LIBRARY_PATH:-}"
  export JARVIS_RVC_PYTHON="$HOME/kvenv/bin/python"
  export JARVIS_RVC_APP_DIR="$HOME/projects/applio-lab/Applio"
elif [ -x /tmp/opencode/tts-venv/bin/python ] && [ -d /tmp/opencode/applio/rvc ]; then
  export JARVIS_RVC_PYTHON=/tmp/opencode/tts-venv/bin/python
  export JARVIS_RVC_APP_DIR=/tmp/opencode/applio
fi
if [ -f "$HOME/models/Jarvis_62e_434s_best_epoch.pth" ]; then
  export JARVIS_VOICE_CLONE_MODEL="$HOME/models/Jarvis_62e_434s_best_epoch.pth"
fi
if [ -f "$HOME/models/added_Jarvis_v2.index" ]; then
  export JARVIS_VOICE_CLONE_INDEX="$HOME/models/added_Jarvis_v2.index"
fi
