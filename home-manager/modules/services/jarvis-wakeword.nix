{
  config,
  lib,
  pkgs,
  ...
}:
# JARVIS Wakeword Daemon — portado do legado (Manjaro) com a calibração validada.
#
# Calibração de áudio (docs/architecture/legacy-audio-calibration.md):
#   - threshold 0.85 (evolução 0.05→0.15→0.30→0.70→0.75→0.65→0.85, menos false positives)
#   - cooldown 5s anti-loop (sem ele, o beep de confirmação re-triggerava o wakeword)
#   - silence adaptativo: 40% drop do pico RMS por 1.0s = parar gravação
#   - kill TTS/audiobook ao trigger (para o usuário falar)
#   - RNNoise: ativado via PipeWire filter-chain em nixos/modules/audio.nix
let
  cfg = config.services.jarvis-wakeword;
  micTarget =
    if cfg.device == "default"
    then "rnnoise_source"
    else cfg.device;

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

  jarvisPythonEnv = pkgs.python3.withPackages (ps:
    with ps; [
      numpy
      requests
      openwakewordPkg
    ]);

  # Comando de processamento do áudio capturado (Fase 8: STT → LLM → TTS).
  # Hoje apenas registra o arquivo; o hook real entra com o STT.
  brainCmd = cfg.brainCommand;

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
    EOF
    chmod +x $out/lib/link-models.sh
  '';

  jarvisScript =
    pkgs.writers.writePython3Bin "jarvis-wakeword-daemon" {
      flakeIgnore = ["E501" "E231" "E226" "F541"];
      # libraries espera pacotes (ou função), não um env pronto — passar o env
      # resultava em PYTHONPATH vazio (import numpy falhava em runtime)
      libraries = ps: with ps; [ numpy onnxruntime ];
    } ''
      import glob
      import json
      import os
      import random
      import shutil
      import subprocess
      import time
      import wave
      import numpy as np

      RATE = ${toString cfg.rate}
      CHUNK = 512
      DEVICE = "${micTarget}"
      COOLDOWN = ${toString cfg.cooldownSeconds}
      KILL_TTS = ${
        if cfg.killTTSOnTrigger
        then "True"
        else "False"
      }
      BRAIN_CMD = ${builtins.toJSON brainCmd}
      WW_THRESHOLD = "${toString cfg.wakeThreshold}"
      ACK_LANG = "${if cfg.ackLang == null then "auto" else cfg.ackLang}"
      WW_SCORER = "${../../../modules/ai/ww_scorer.py}"
      OWW_MODELS = os.path.expanduser("~/.local/share/openwakeword")
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


      ACK_PHRASES = {
          "en": ["Yes, sir?", "At your service, sir.", "How may I assist?", "Certainly, sir."],
          "pt": ["Pois não, senhor?", "Às ordens, senhor.", "Como posso ajudar?", "Certamente, senhor."],
      }


      def _ack_lang():
          if ACK_LANG != "auto":
              return ACK_LANG
          lang = (os.environ.get("LANG", "") + os.environ.get("LC_ALL", "")).lower()
          return "pt" if lang.startswith("pt") else "en"


      def _play_ack():
          """Ack no idioma do sistema (ou cfg). WAVs gerados 1x e cacheados por idioma."""
          try:
              lang = _ack_lang()
              phrases = ACK_PHRASES.get(lang, ACK_PHRASES["en"])
              ackdir = os.path.expanduser(f"~/.local/share/jarvis/voice/ack-{lang}")
              os.makedirs(ackdir, exist_ok=True)
              existing = sorted(glob.glob(os.path.join(ackdir, "*.wav")))
              if not existing:
                  print(f"[WW] Gerando respostas {lang} (1a vez)...", flush=True)
                  for i, phrase in enumerate(phrases):
                      subprocess.run(["jarvis", "speak", "--no-play", phrase],
                                     capture_output=True, timeout=180)
                      cands = sorted(
                          glob.glob(os.path.expanduser("~/.local/share/jarvis/voice/tts/*.wav")),
                          key=os.path.getmtime)
                      if cands:
                          shutil.move(cands[-1], os.path.join(ackdir, f"ack{i}.wav"))
                  existing = sorted(glob.glob(os.path.join(ackdir, "*.wav")))
              if existing:
                  subprocess.run(["pw-play", random.choice(existing)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
          except Exception as e:
              print(f"[WW] ACK falhou: {e}", flush=True)


      def kill_orphan_pw_record():
          """Mate processos pw-record órfãos (de runs anteriores)."""
          try:
              import signal
              my_pid = os.getpid()
              for line in subprocess.check_output(["pgrep", "-f", "pw-record"], text=True).splitlines():
                  pid = int(line.strip())
                  if pid != my_pid:
                      try:
                          os.kill(pid, signal.SIGKILL)
                          print(f"[WW] Killed orphan pw-record PID {pid}", flush=True)
                      except OSError:
                          pass
          except Exception:
              pass


      def main():
          kill_orphan_pw_record()
          with open("/tmp/jarvis-wakeword-status", "w") as f:
              f.write(f"READY|{time.time()}")
          update_status("initializing", "Iniciando...")
          play_sound(STARTUP_SOUND)
          notify("JARVIS", "Sistemas Ativos.", "emblem-default")

          # VAD mode: RMS-based voice detection + STT verification
          # openwakeword model doesn't work with PipeWire audio on NixOS.
          # Fallback: detect speech onset via RMS, record, then STT checks
          # if the user said 'Hey Jarvis'.
          PW_RECORD = "${pkgs.pipewire}/bin/pw-record"
          # Adaptive VAD: speech = RMS > baseline * 1.5, silence = RMS < baseline * 1.1
          noise_baseline = 500  # Updated during silence (rolling average)
          print(f"[WW] Starting pw-record {DEVICE} @ {RATE}Hz (VAD adaptive mode, Cooldown: {COOLDOWN}s)", flush=True)

          def start_arecord():
              return subprocess.Popen(
                  [PW_RECORD, "--target", DEVICE, "--format", "s16",
                   "--rate", str(RATE), "--channels", "2", "-"],
                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
              )

          arecord_proc = start_arecord()
          update_status("idle", "󰆪 Aguardando...")

          last_trigger_time = 0
          pulse_state = 0
          chunk_count = 0
          WARMUP_CHUNKS = 50  # ~1s warmup
          speaking = False
          silence_start = None
          speech_frames = []
          speech_buf = []  # buffer for consecutive speech chunks

          while True:
              try:
                  data = arecord_proc.stdout.read(CHUNK * 4)
                  if not data:
                      print("[WW] No data from arecord, restarting...", flush=True)
                      time.sleep(1)
                      arecord_proc = start_arecord()
                      continue

                  # Converte o buffer bruto mantendo os limites corretos do int16
                  audio_np = np.frombuffer(data, dtype=np.int16)

                  # Trata os canais de forma segura para evitar clipping/estouro na soma
                  if len(audio_np) >= 2:
                      mono = (audio_np[::2].astype(np.int32) + audio_np[1::2].astype(np.int32)) // 2
                      mono = np.clip(mono, -32768, 32767).astype(np.float32)
                  else:
                      mono = audio_np.astype(np.float32)

                  # Calcula o RMS real sem overflow geométrico
                  rms = np.sqrt(np.mean(mono**2)) if len(mono) > 0 else 0
                  chunk_count += 1

                  # Sistema deWaybar/Pulsing status — nunca sobrescreve
                  # pipeline ativa (brain transcrevendo/pensando/falando).
                  if chunk_count % 50 == 0:
                      try:
                          with open("/tmp/jarvis-status.json") as _sf:
                              _cur = json.load(_sf).get("state", "idle")
                      except Exception:
                          _cur = "idle"
                      if _cur in ("idle", "listening"):
                          pulse_symbols = ["  ", "  "]
                          update_status("idle", f"{pulse_symbols[pulse_state % 2]} Ouvindo...")
                          pulse_state += 1

                  if chunk_count % 10 == 0:
                      print(f"[WW] RMS: {rms:.0f} (baseline={noise_baseline:.0f}, gate={max(noise_baseline * 1.5, 250):.0f})", flush=True)

                  # Ignora o aquecimento inicial do mic
                  if chunk_count < WARMUP_CHUNKS:
                      continue

                  # Atualiza o ruído de fundo de forma suave (Filtro Passa-Baixa)
                  if not speaking:
                      if rms < noise_baseline * 1.2:
                          # Taxa de aprendizado menor para a ventoinha do notebook não estourar o ganho
                          noise_baseline = noise_baseline * 0.95 + rms * 0.05

                      # Evita que o gate caia a zero e cause ganho infinito
                      speech_gate = max(noise_baseline * 1.6, 400)
                  else:
                      speech_gate = max(noise_baseline * 1.6, 400)
                      speech_gate = max(noise_baseline * 1.5, 250)

                  # Cooldown check
                  if (time.time() - last_trigger_time) < COOLDOWN:
                      continue

                  # VAD: detect speech onset
                  # 1. Ignore very quiet audio (electronic noise)
                  if rms < 50:
                      continue

                  # 2. Adaptive threshold: 50% above baseline (was 10%)
                  # 3. Require 3 consecutive chunks (was 2)
                  if not speaking:
                      # Windowed onset: 3 of last 5 chunks (syllable
                      # valleys reset a strict consecutive counter)
                      speech_buf.append(1 if rms > speech_gate else 0)
                      speech_buf = speech_buf[-5:]
                      if sum(speech_buf) >= 3:
                          speaking = True
                          speech_frames = [data]
                          silence_start = None
                          speech_buf = []
                          print(f"[WW] 🎤 Speech detected (RMS={rms:.0f}, baseline={noise_baseline:.0f}, gate={speech_gate:.0f})", flush=True)
                      continue

                  # Currently speaking — accumulate frames
                  speech_frames.append(data)

                  # Check for silence (adaptive: < baseline * 1.1 for 2s, min 1s recording)
                  recording_duration = len(speech_frames) * CHUNK / RATE
                  if rms < noise_baseline * 1.1 and recording_duration > 3.0:
                      if silence_start is None:
                          silence_start = time.time()
                      elif time.time() - silence_start > 2.0:
                          # End of speech — save WAV and process
                          speaking = False
                          last_trigger_time = time.time()
                          print(f"[WW] ✅ Speech ended ({len(speech_frames)} chunks, {len(speech_frames)*CHUNK/RATE:.1f}s)", flush=True)

                      # Kill TTS/audiobook para o usuário falar
                      if KILL_TTS:
                          for pat in ["paplay", "aplay", "enhanced_audiobook.py"]:
                              subprocess.run(["pkill", "-9", pat], stderr=subprocess.DEVNULL)

                      # Sem beep aqui: só responde após wakeword confirmado.

                      # Save the speech we already captured
                      timestamp = int(time.time())
                      temp_wav = f"/tmp/jarvis_cmd_{timestamp}.wav"
                      with wave.open(temp_wav, "wb") as wf:
                          wf.setnchannels(2)
                          wf.setsampwidth(2)
                          wf.setframerate(RATE)
                          wf.writeframes(b"".join(speech_frames))
                      print(f"[WW] 📼 Capturado: {temp_wav} ({len(speech_frames)} chunks, {len(speech_frames)*CHUNK/RATE:.1f}s)", flush=True)
                      speech_frames = []

                      if BRAIN_CMD:
                          # 1. Scorer hey_jarvis (ONNX, barato) ANTES do STT:
                          # ruído/TV é descartado aqui, sem 40s de CPU.
                          try:
                              import sys as _sys
                              _score = subprocess.run(
                                  [_sys.executable, WW_SCORER, "--models",
                                   os.path.expanduser(OWW_MODELS),
                                   "--wav", temp_wav,
                                   "--threshold", WW_THRESHOLD],
                                  capture_output=True, text=True, timeout=60,
                              )
                              print(f"[WW] 🎯 {(_score.stdout or "").strip()}", flush=True)
                              if _score.returncode != 0:
                                  print(f"[WW] 🔇 wakeword rejeitado, ignorando", flush=True)
                                  update_status("idle", "󰆪 Aguardando...")
                                  arecord_proc.terminate()
                                  time.sleep(0.5)
                                  arecord_proc = start_arecord()
                                  continue
                              print(f"[WW] 🫡 Hey Jarvis confirmado", flush=True)
                              _play_ack()
                          except Exception as _ww_err:
                              print(f"[WW] ⚠️ scorer falhou: {_ww_err}, seguindo p/ STT", flush=True)
                          # 2. Pre-check: run STT, skip if no speech detected
                          try:
                              import shutil as _shutil
                              # Quick STT check
                              # Modelo small (não tiny): PT-BR curto alucina
                              # ou esvazia no tiny; small custa ~30s mas ouve.
                              _stt_args = [BRAIN_CMD[0], "stt", "--model", "small", temp_wav]
                              if _ack_lang() == "pt":
                                  _stt_args += ["--language", "pt"]
                              _stt_check = subprocess.run(
                                  _stt_args,
                                  # Cold start: faster-whisper carrega o
                                  # modelo a cada chamada (~20-40s CPU)
                                  timeout=90, capture_output=True, text=True,
                              )
                              _stt_text = (_stt_check.stdout or "").strip()
                              if not _stt_text or _stt_text.startswith("ERROR"):
                                  print(f"[WW] ⏭️ No speech in audio (STT: '{_stt_text[:50]}'), skipping brain", flush=True)
                                  update_status("idle", "󰆪 Aguardando...")
                                  # Reset for next recording
                                  arecord_proc.terminate()
                                  time.sleep(0.5)
                                  arecord_proc = start_arecord()
                                  continue
                              print(f"[WW] 🗣️ STT detected: '{_stt_text[:80]}'", flush=True)
                          except Exception as _stt_err:
                              print(f"[WW] ⚠️ STT pre-check failed: {_stt_err}", flush=True)

                          update_status("processing", "Pensando...")
                          try:
                              if not _shutil.which(BRAIN_CMD[0]):
                                  print(f"[WW] ❌ BRAIN_CMD '{BRAIN_CMD[0]}' não encontrado no PATH", flush=True)
                                  update_status("error", f"Comando '{BRAIN_CMD[0]}' não encontrado")
                              else:
                                  result = subprocess.run(
                                      BRAIN_CMD + [temp_wav],
                                      timeout=30,
                                      capture_output=True, text=True,
                                  )
                                  if result.returncode != 0:
                                      stderr_msg = (result.stderr or "")[:300]
                                      stdout_msg = (result.stdout or "")[:300]
                                      # Mostra stdout tb (STT output, agent response)
                                      combined = stdout_msg + stderr_msg
                                      print(f"[WW] ❌ brain falhou (exit {result.returncode}): {combined[:200]}", flush=True)
                                      update_status("error", f"Erro: {stderr_msg[:60]}")
                                  else:
                                      print(f"[WW] ✅ brain OK: {(result.stdout or "")[:100]}", flush=True)
                                      update_status("done", "Concluído")
                          except subprocess.TimeoutExpired:
                              print("[WW] ⏰ brain timeout (30s) — STT/LLM/TTS travou", flush=True)
                              update_status("error", "Timeout: pipeline nao respondeu")
                          except Exception as e:
                              print(f"[WW] ❌ brain error: {str(e)[:100]}", flush=True)
                              update_status("error", f"Exceção: {str(e)[:60]}")

                      # Reset: kill agressivo do pw-record (PipeWire segura o processo)
                      try:
                          arecord_proc.kill()
                      except Exception:
                          pass
                      try:
                          arecord_proc.wait(timeout=3)
                      except Exception:
                          pass
                      time.sleep(0.5)
                      update_status("idle", "Aguardando...")
                      arecord_proc = start_arecord()
                      print(f"[WW] pw-record restarted PID: {arecord_proc.pid}", flush=True)
              except Exception as e:
                  print(f"[WW] ERROR: {str(e)[:100]}", flush=True)
                  time.sleep(0.1)


      if __name__ == "__main__":
          main()
    '';
in {
  options.services.jarvis-wakeword = {
    enable = lib.mkEnableOption "Jarvis Wakeword Daemon";
    threshold = lib.mkOption {
      type = lib.types.float;
      default = 0.85;
      description = "Sensibilidade limite de ativação da wake word (calibrado: 0.85).";
    };
    device = lib.mkOption {
      type = lib.types.str;
      default = "rnnoise_source";
      description = ''
        Fonte de captura do PipeWire.
        "rnnoise_source" = source virtual do pipewire com denoise (recomendado);
        "default" = fallback apenas se a fonte do denoise não estiver disponível.
      '';
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
    wakeThreshold = lib.mkOption {
      type = lib.types.float;
      default = 0.3;
      description = "Score mínimo do hey_jarvis ONNX (0.99 positivo real, ruído <0.18 medido).";
    };
    rmsGate = lib.mkOption {
      type = lib.types.nullOr lib.types.int;
      default = null;
      description = "Gate RMS de ruído ambiente (legado calibrou 2093). null = desabilitado.";
    };
    ackLang = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Idioma do ack falado (pt|en). null = auto pelo LANG do sistema.";
    };
    killTTSOnTrigger = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Mata TTS/audiobook ao trigger para o usuário falar.";
    };
    brainCommand = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [];
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
    home.packages = [jarvisPythonEnv jarvisScript modelsLink];

    # Cria os symlinks dos modelos declarativos (store → ~/.local/share)
    home.activation.jarvisModels = lib.hm.dag.entryAfter ["writeBoundary"] ''
      run ${modelsLink}/lib/link-models.sh
      # Pré-baixa modelo STT tiny (multilingual, ~75MB, PT-BR) — evita timeout
      STT_DIR="$HOME/.local/share/jarvis/voice"
      TINY_DIR="$STT_DIR/models--Systran--faster-whisper-tiny/snapshots/main"
      if [ ! -f "$TINY_DIR/model.bin" ]; then
        mkdir -p "$TINY_DIR"
        echo "[jarvis] Baixando modelo STT tiny (multilingual)..."
        for f in model.bin config.json vocabulary.txt tokenizer.json; do
          wget -q --timeout=30 "https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/$f" -O "$TINY_DIR/$f" 2>/dev/null || true
        done
      fi
    '';

    systemd.user.services.jarvis-wakeword = {
      Unit = {
        Description = "Jarvis Neural Core Wakeword Daemon";
        After = ["graphical-session.target"];
      };
      Service = {
        ExecStart = "${jarvisScript}/bin/jarvis-wakeword-daemon";
        Restart = "always";
        RestartSec = "5s";
        # PATH needs jarvis-voice for BRAIN_CMD (jarvis voice <wav>)
        Environment = [
          "PATH=${lib.makeBinPath [pkgs.jarvis-voice pkgs.pipewire pkgs.sox pkgs.procps]}:${pkgs.coreutils}/bin:${pkgs.gnugrep}/bin:${pkgs.findutils}/bin"
        ];
      };
      Install = {
        WantedBy = ["graphical-session.target"];
      };
    };
  };
}
