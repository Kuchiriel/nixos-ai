{pkgs, ...}: {
  security.rtkit.enable = true;
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    alsa.support32Bit = true;
    pulse.enable = true;

    # Denoise RNNoise (werman/noise-suppression-for-voice via nixpkgs
    # `rnnoise-plugin`): cria o source virtual `rnnoise_source` com supressão
    # de ruído em tempo real (ventoinha + sons de casa do notebook).
    # O wakeword/STT apontam para esse source em vez do device cru.
    # Parâmetros VAD do legado (calibrados em ambiente ruidoso):
    #   - VAD Threshold 50% (fala vs. ruído)
    #   - VAD Grace 200ms (não corta início de palavra)
    # 03/11 (FluidVoice): cancelamento de ECO (AEC3 do WebRTC — o mesmo
    # motor do app FluidVoice, via webrtc-audio-processing que já está na
    # closure do pipewire) ANTES do RNNoise.
    # monitor.mode = true => a referência (far-end) vem do MONITOR do sink
    # default: qualquer TTS que saia pelos alto-falantes (pw-play, mpv,
    # canberra) é cancelado do mic — sem wrapper de pw-play, sem sink extra.
    # O módulo cria um source virtual (echo_cancel_source):
    #   mic -> AEC3 -> echo_cancel_source -> RNNoise -> rnnoise_source -> STT
    # Sem isso, no duplex o Kokoro volta pro microfone e o STT transcreve a
    # própria resposta (o VAD por RMS não distingue TTS de voz).
    # CUIDADO: se este módulo não carregar, o target "echo_cancel_source"
    # não existe — por isso o wakeword tem fallback para rnnoise_source.
    extraConfig.pipewire = {
      "98-echo-cancel" = {
        "context.modules" = [
          {
            name = "libpipewire-module-echo-cancel";
            args = {
              "library.name" = "aec/libspa-aec-webrtc";
              "monitor.mode" = true;
              "capture.props" = {
                "node.name" = "capture.echo_cancel_source";
                "node.passive" = true;
                "audio.rate" = 48000;
                "webrtc.noise_suppression" = true;
                "webrtc.gain_control" = true;
                "webrtc.high_pass_filter" = true;
              };
              "source.props" = {
                "node.name" = "echo_cancel_source";
                "media.class" = "Audio/Source";
                "audio.rate" = 48000;
              };
            };
          }
        ];
      };
      "99-input-denoising" = {
        "context.modules" = [
          {
            name = "libpipewire-module-filter-chain";
            args = {
              "node.description" = "Noise Canceling source";
              "media.name" = "Noise Canceling source";
              "filter.graph" = {
                nodes = [
                  {
                    type = "ladspa";
                    name = "rnnoise";
                    plugin = "${pkgs.rnnoise-plugin}/lib/ladspa/librnnoise_ladspa.so";
                    label = "noise_suppressor_mono";
                    control = {
                      "VAD Threshold (%)" = 50.0;
                      "VAD Grace Period (ms)" = 200;
                      "Retroactive VAD Grace (ms)" = 0;
                    };
                  }
                ];
              };
              "capture.props" = {
                "node.name" = "capture.rnnoise_source";
                "node.passive" = true;
                "audio.rate" = 48000;
                # AEC3 antes do RNNoise: o source do echo-cancel e a entrada
                # (o eco da propria voz ja foi removido antes da supressao).
                "node.target" = "echo_cancel_source";
              };
              "playback.props" = {
                "node.name" = "rnnoise_source";
                "media.class" = "Audio/Source";
                "audio.rate" = 48000;
              };
            };
          }
        ];
      };
    };
  };
}
