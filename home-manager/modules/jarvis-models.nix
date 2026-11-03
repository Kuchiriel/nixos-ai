# JARVIS models — symlinks declarativos em ~/.local/share (kokoro, whisper, openwakeword)
#
# POR QUE ESTE MÓDULO EXISTE (medido 03/11):
# Os links dos modelos viviam SÓ no módulo do wakeword — que está
# DESABILITADO desde 21/10 (o duplex de voz contínua o substituiu). Sem
# referência no closure do sistema, o GC levou os store paths e os symlinks
# em ~/.local/share ficaram BROKEN:
#   ~/.local/share/kokoro/config.json        -> quebrado
#   ~/.local/share/kokoro/kokoro-v1_0.pth    -> quebrado
#   ~/.local/share/kokoro/voices/af_heart.pt -> quebrado
#   ~/.local/share/jarvis/voice/models--Systran--faster-whisper-small/... -> quebrado
# Efeito: o TTS Kokoro caía no fallback (espeak = voz horrível) e o
# `jarvis stt` não achava o modelo. Aqui os modelos são referenciados pelo
# sistema (closure) e religados a cada activation — sem depender do wakeword.
{ config, lib, pkgs, ... }:
let
  cfg = config.services.jarvis-models;

  # Pacote que expõe os modelos declarativos em ~/.local/share (symlinks p/ store)
  modelsLink = pkgs.runCommand "jarvis-models-link" {} ''
    mkdir -p $out/lib
    cat > $out/lib/link-models.sh <<'EOF'
    #!/bin/sh
    set -e
    mkdir -p "$HOME/.local/share/kokoro" "$HOME/.local/share/openwakeword"
    ln -sf ${pkgs.aiModels.kokoro.config} "$HOME/.local/share/kokoro/config.json"
    ln -sf ${pkgs.aiModels.kokoro.model} "$HOME/.local/share/kokoro/kokoro-v1_0.pth"
    # Voice files — one per language
    mkdir -p "$HOME/.local/share/kokoro/voices"
    ln -sf ${pkgs.aiModels.kokoro.voice} "$HOME/.local/share/kokoro/af_heart.pt"
    ln -sf ${pkgs.aiModels.kokoro.voice} "$HOME/.local/share/kokoro/voices/af_heart.pt"
    ln -sf ${pkgs.aiModels.kokoro.voices.pf_dora} "$HOME/.local/share/kokoro/voices/pf_dora.pt"
    ln -sf ${pkgs.aiModels.kokoro.voices.pm_alex} "$HOME/.local/share/kokoro/voices/pm_alex.pt"
    ln -sf ${pkgs.aiModels.openwakeword.hey_jarvis} "$HOME/.local/share/openwakeword/hey_jarvis_v0.1.onnx"
    ln -sf ${pkgs.aiModels.openwakeword.embedding} "$HOME/.local/share/openwakeword/embedding_model.onnx"
    ln -sf ${pkgs.aiModels.openwakeword.melspectrogram} "$HOME/.local/share/openwakeword/melspectrogram.onnx"
    # STT small (faster-whisper, layout de cache HF): fonte de verdade em
    # modules/ai/models.nix (whisper-small, 4 arquivos). Declarativo —
    # sobrevive sem rede; o wget imperativo foi removido.
    STT_SNAP="$HOME/.local/share/jarvis/voice/models--Systran--faster-whisper-small/snapshots/main"
    mkdir -p "$STT_SNAP"
    ln -sf ${pkgs.aiModels.whisper-small.model} "$STT_SNAP/model.bin"
    ln -sf ${pkgs.aiModels.whisper-small.config} "$STT_SNAP/config.json"
    ln -sf ${pkgs.aiModels.whisper-small.vocabulary} "$STT_SNAP/vocabulary.txt"
    ln -sf ${pkgs.aiModels.whisper-small.tokenizer} "$STT_SNAP/tokenizer.json"
    EOF
    chmod +x $out/lib/link-models.sh
  '';
in
{
  options.services.jarvis-models = {
    # Sempre ligado: os modelos (kokoro/whisper/openwakeword) precisam estar
    # no closure do sistema e religados a cada activation, independente do
    # wakeword (desabilitado desde 21/10).
    enable = lib.mkEnableOption "Link the JARVIS models (kokoro/whisper/openwakeword) into ~/.local/share" true;
  };

  config = lib.mkIf cfg.enable {
    # Ligar os modelos a cada activation — sem isto os symlinks apodrecem
    # (o GC leva o store path e o link vira "No such file or directory").
    home.activation.jarvisModels = lib.hm.dag.entryAfter ["writeBoundary"] ''
      run ${modelsLink}/lib/link-models.sh
    '';
  };
}
