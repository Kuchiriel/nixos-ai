{ config, lib, pkgs, ... }:

# JARVIS Wakeword Daemon — portado do legado (Manjaro) com a calibração validada.
#
# Calibração de áudio (docs/architecture/legacy-audio-calibration.md):
#   - threshold 0.85 (evolução 0.05→0.15→0.30→0.70→0.75→0.65→0.85, menos false positives)
#   - cooldown 5s anti-loop (sem ele, o beep de confirmação re-triggerava o wakeword)
#   - silence adaptativo: 40% drop do pico RMS por 1.0s = parar gravação
#   - kill TTS/audiobook ao trigger (para o usuário falar)
#   - RNNoise: desativado (plugin LADSPA indisponível no nixpkgs — pendência documentada)

let
  cfg = config.services.jarvis-wakeword;

  openwakewordPkg = pkgs.python3Packages.buildPythonPackage rec {
    pname = "openwakeword";
    version = "0.6.0";
    src = pkgs.python3Packages.fetchPypi {
      inherit pname version;
      sha256 = "sha256-NoWNkPEYPjB0hVl6kSpOPDOEsU6pkj+D/q/658FWVWU=";
    };
    # nixpkgs 26.05 (python 3.13): buildPythonPackage exige format explícito
    format = "setuptools";
    propagatedBuildInputs = with pkgs.python3Packages; [
      numpy
      onnxruntime
      scipy
      scikit-learn
      requests
      sounddevice
      tqdm
    ];
    doCheck = false;
  };

  jarvisPythonEnv = pkgs.python3.withPackages (ps: with ps; [
    numpy
    requests
    openwakewordPkg
  ]);

  # Comando de processamento do áudio capturado (Fase 8: STT → LLM → TTS).
  # Hoje apenas registra o arquivo; o hook real entra com o STT.
  brainCmd = cfg.brainCommand;

  # Pacote que expõe os modelos declarativos em ~/.local/share (symlinks p/ store)
  modelsLink = pkgs.runCommand "jarvis-models-link" { } ''
    mkdir -p $out/lib
    cat > $out/lib/link-models.sh <<'EOF'
    #!/bin/sh
    set -e
    mkdir -p "$HOME/.local/share/kokoro" "$HOME/.local/share/openwakeword"
    ln -sf ${pkgs.aiModels.kokoro.config} "$HOME/.local/share/kokoro/config.json"
    ln -sf ${pkgs.aiModels.kokoro.model} "$HOME/.local/share/kokoro/kokoro-v1_0.pth"
    ln -sf ${pkgs.aiModels.kokoro.voice} "$HOME/.local/share/kokoro/af_heart.pt"
    ln -sf ${pkgs.aiModels.openwakeword.hey_jarvis} "$HOME/.local/share/openwakeword/hey_jarvis_v0.1.onnx"
    ln -sf ${pkgs.aiModels.openwakeword.embedding} "$HOME/.local/share/openwakeword/embedding_model.onnx"
    ln -sf ${pkgs.aiModels.openwakeword.melspectrogram} "$HOME/.local/share/openwakeword/melspectrogram.onnx"
    EOF
    chmod +x $out/lib/link-models.sh
  '';

  jarvisScript = pkgs.writers.writePython3Bin "jarvis-wakeword-daemon" {
    flakeIgnore = [ "E501" "E231" ];
    # libraries espera pacotes (ou função), não um env pronto — passar o env
    # resultava em PYTHONPATH vazio (import numpy falhava em runtime)
    libraries = (ps: with ps; [ numpy requests openwakewordPkg ]);
  } ''
    import json
    import os
    import subprocess
    import time
    import wave
    import numpy as np
    from openwakeword.model import Model

    RATE = ${toString cfg.rate}
    CHUNK = 512
    THRESHOLD = ${toString cfg.threshold}
    DEVICE = "${cfg.device}"
    COOLDOWN = ${toString cfg.cooldownSeconds}
    MAX_RECORD = ${toString cfg.maxRecordSeconds}
    SILENCE_DROP = ${toString cfg.silenceDrop}
    RMS_GATE = ${if cfg.rmsGate != null then toString cfg.rmsGate else "None"}
    KILL_TTS = ${if cfg.killTTSOnTrigger then "True" else "False"}
    BRAIN_CMD = ${builtins.toJSON brainCmd}
    # Modelos do store Nix (linkados em ~/.local/share/openwakeword pelo activation)
    WAKEWORD_MODEL = "${config.home.homeDirectory}/.local/share/openwakeword/hey_jarvis_v0.1.onnx"
    MELSPEC_MODEL = "${config.home.homeDirectory}/.local/share/openwakeword/melspectrogram.onnx"
    EMBEDDING_MODEL = "${config.home.homeDirectory}/.local/share/openwakeword/embedding_model.onnx"
    STARTUP_SOUND = "${pkgs.sound-theme-freedesktop}/share/sounds/freedesktop/stereo/service-login.oga"
    BEEP_SOUND = "${pkgs.sound-theme-freedesktop}/share/sounds/freedesktop/stereo/message-new-instant.oga"


    def update_status(state, text=""):
        try:
            with open("/tmp/jarvis-status.json", "w") as f:
                json.dump({"state": state, "text": text}, f)
        except Exception:
            pass


    def notify(title, msg, icon="audio-input-microphone"):
        env = os.environ.copy()
        try:
            subprocess.Popen(
                ["${pkgs.libnotify}/bin/notify-send", "-t", "3000", "-i", icon, title, msg],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


    def play_sound(path):
        try:
            subprocess.run(
                ["${pkgs.libcanberra-gtk3}/bin/canberra-gtk-play", "--file", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


    def main():
        oww = Model(
            wakeword_model_paths=[WAKEWORD_MODEL],
            melspec_model_path=MELSPEC_MODEL,
            embedding_model_path=EMBEDDING_MODEL,
            inference_framework="onnx",
        )
        with open("/tmp/jarvis-wakeword-status", "w") as f:
            f.write(f"READY|{time.time()}")
        update_status("initializing", "Iniciando...")
        play_sound(STARTUP_SOUND)
        notify("JARVIS", "Sistemas Ativos.", "emblem-default")

        print(f"[WW] Starting arecord {DEVICE} @ {RATE}Hz (Threshold: {THRESHOLD}, Cooldown: {COOLDOWN}s)", flush=True)

        def start_arecord():
            return subprocess.Popen(
                ["${pkgs.alsa-utils}/bin/arecord", "-D", DEVICE, "-f", "S16_LE", "-r", str(RATE), "-c", "2"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )

        arecord_proc = start_arecord()
        update_status("idle", "🎤 Ouvindo...")

        last_trigger_time = 0
        pulse_state = 0
        chunk_count = 0

        while True:
            try:
                data = arecord_proc.stdout.read(CHUNK * 4)
                if not data:
                    print("[WW] No data from arecord, restarting...", flush=True)
                    time.sleep(1)
                    arecord_proc = start_arecord()
                    continue

                audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                mono = (audio_np[::2] + audio_np[1::2]) * 0.5
                # Normalização calibrada do legado: DC removal + ganho fixo
                mono_norm = np.clip((mono - np.mean(mono)) * 10.0, -32768, 32767).astype(np.int16)
                oww.predict(mono_norm)
                score = oww.prediction_buffer['hey_jarvis_v0.1'][-1]
                rms = np.sqrt(np.mean(mono**2))

                chunk_count += 1

                # Pulsing waybar status (a cada ~800ms)
                if chunk_count % 50 == 0:
                    pulse_symbols = ["🎤", "🎙️"]
                    update_status("idle", f"{pulse_symbols[pulse_state % 2]} Ouvindo...")
                    pulse_state += 1

                if chunk_count % 10 == 0:
                    print(f"[WW] Score: {score:.4f}, RMS: {rms:.0f}, Threshold: {THRESHOLD}", flush=True)

                # RMS gate opcional (filtro de ruído ambiente, calibrado em 2093 no legado)
                if RMS_GATE is not None and rms > RMS_GATE and score <= THRESHOLD:
                    continue

                # Trigger com cooldown anti-loop (sem ele, o beep re-triggerava o wakeword)
                if score > THRESHOLD and (time.time() - last_trigger_time) > COOLDOWN:
                    last_trigger_time = time.time()
                    print(f"[WW] ✅ TRIGGER: score {score:.4f} > threshold {THRESHOLD}", flush=True)

                    # Kill TTS/audiobook para o usuário falar (lição do legado)
                    if KILL_TTS:
                        for pat in ["paplay", "aplay", "enhanced_audiobook.py"]:
                            subprocess.run(["pkill", "-9", pat], stderr=subprocess.DEVNULL)

                    update_status("listening", "Gravando...")
                    play_sound(BEEP_SOUND)

                    # Captura com silence adaptativo: 40% drop do pico RMS por 1.0s
                    frames = []
                    silence_start = None
                    record_start = time.time()
                    max_rms_seen = rms

                    while time.time() - record_start < MAX_RECORD:
                        chunk_data = arecord_proc.stdout.read(CHUNK * 4)
                        if not chunk_data:
                            break
                        frames.append(chunk_data)
                        c_rms = np.sqrt(np.mean(np.frombuffer(chunk_data, dtype=np.int16).astype(np.float32)**2))
                        max_rms_seen = max(max_rms_seen, c_rms)
                        silence_threshold = max_rms_seen * SILENCE_DROP
                        if c_rms < silence_threshold:
                            if silence_start is None:
                                silence_start = time.time()
                            elif time.time() - silence_start > 1.0:
                                break
                        else:
                            silence_start = None

                    timestamp = int(time.time())
                    temp_wav = f"/tmp/jarvis_cmd_{timestamp}.wav"
                    with wave.open(temp_wav, "wb") as wf:
                        wf.setnchannels(2)
                        wf.setsampwidth(2)
                        wf.setframerate(RATE)
                        wf.writeframes(b"".join(frames))
                    print(f"[WW] 📼 Capturado: {temp_wav} ({len(frames)} chunks)", flush=True)

                    if BRAIN_CMD:
                        update_status("processing", "Pensando...")
                        try:
                            subprocess.run(BRAIN_CMD + [temp_wav], timeout=30)
                        except Exception as e:
                            print(f"[WW] brain error: {str(e)[:100]}", flush=True)

                    # Reset: restart arecord e recarrega modelo (limpa estado do trigger)
                    arecord_proc.terminate()
                    time.sleep(1.0)
                    update_status("idle", "Aguardando...")
                    arecord_proc = start_arecord()
                    print(f"[WW] arecord restarted PID: {arecord_proc.pid}", flush=True)
            except Exception as e:
                print(f"[WW] ERROR: {str(e)[:100]}", flush=True)
                time.sleep(0.1)


    if __name__ == "__main__":
        main()
  '';
in
{
  options.services.jarvis-wakeword = {
    enable = lib.mkEnableOption "Jarvis Wakeword Daemon";
    threshold = lib.mkOption {
      type = lib.types.float;
      default = 0.85;
      description = "Sensibilidade limite de ativação da wake word (calibrado: 0.85).";
    };
    device = lib.mkOption {
      type = lib.types.str;
      default = "hw:1,7";
      description = "Dispositivo ALSA de captura (legado: hw:1,7, bypass PyAudio).";
    };
    rate = lib.mkOption {
      type = lib.types.int;
      default = 16000;
      description = "Taxa de amostragem da captura.";
    };
    cooldownSeconds = lib.mkOption {
      type = lib.types.int;
      default = 5;
      description = "Lockout anti-loop após trigger (o beep re-triggerava sem ele).";
    };
    maxRecordSeconds = lib.mkOption {
      type = lib.types.int;
      default = 12;
      description = "Limite máximo de gravação após trigger.";
    };
    silenceDrop = lib.mkOption {
      type = lib.types.float;
      default = 0.6;
      description = "Fração do pico RMS que define silêncio (0.6 = 40% drop, silence adaptativo).";
    };
    rmsGate = lib.mkOption {
      type = lib.types.nullOr lib.types.int;
      default = null;
      description = "Gate RMS de ruído ambiente (legado calibrou 2093). null = desabilitado.";
    };
    killTTSOnTrigger = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Mata TTS/audiobook ao trigger para o usuário falar.";
    };
    brainCommand = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = ''
        Comando de processamento do áudio capturado (Fase 8: STT → LLM → TTS).
        Recebe o path do WAV como argumento.

        No host final, com voz habilitada (pacote `jarvis-voice` no PATH):
          brainCommand = [ "jarvis" "voice" ];
        (faster-whisper STT com VAD calibrado + Kokoro TTS — ver
        docs/architecture/legacy-audio-calibration.md)
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ jarvisPythonEnv jarvisScript modelsLink ];

    # Cria os symlinks dos modelos declarativos (store → ~/.local/share)
    home.activation.jarvisModels = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      run ${modelsLink}/lib/link-models.sh
    '';

    systemd.user.services.jarvis-wakeword = {
      Unit = {
        Description = "Jarvis Neural Core Wakeword Daemon";
        After = [ "graphical-session.target" ];
      };
      Service = {
        ExecStart = "${jarvisScript}/bin/jarvis-wakeword-daemon";
        Restart = "always";
        RestartSec = "5s";
      };
      Install = {
        WantedBy = [ "graphical-session.target" ];
      };
    };
  };
}
