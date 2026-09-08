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
if [ -x /tmp/opencode/tts-venv/bin/python ] && [ -d /tmp/opencode/applio/rvc ]; then
  export JARVIS_RVC_PYTHON=/tmp/opencode/tts-venv/bin/python
  export JARVIS_RVC_APP_DIR=/tmp/opencode/applio
fi
if [ -f "$HOME/models/Jarvis_62e_434s_best_epoch.pth" ]; then
  export JARVIS_VOICE_CLONE_MODEL="$HOME/models/Jarvis_62e_434s_best_epoch.pth"
fi
if [ -f "$HOME/models/added_Jarvis_v2.index" ]; then
  export JARVIS_VOICE_CLONE_INDEX="$HOME/models/added_Jarvis_v2.index"
fi
