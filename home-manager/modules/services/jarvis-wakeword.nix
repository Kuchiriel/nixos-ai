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
      flakeIgnore = ["E501" "E231" "E226" "F541" "E117"];
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
      MAX_RECORD = ${toString cfg.maxRecordSeconds}
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
      ERROR_SOUND = "${pkgs.sound-theme-freedesktop}/share/sounds/freedesktop/stereo/dialog-error.oga"
      PRE_ROLL_CHUNKS = 15  # ~770ms pre-roll buffer before speech onset


      def update_status(state, text=""):
          try:
              with open("/tmp/jarvis-status.json", "w") as f:
                  json.dump({"state": state, "text": text}, f)
          except Exception:
              pass
          try:
              subprocess.run(["pkill", "-RTMIN+8", "waybar"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             timeout=2)
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


      def _rvc_ready():
          """Spike RVC presente? (/tmp efêmero — some no reboot)."""
          py = os.environ.get("JARVIS_RVC_PYTHON", "")
          app = os.environ.get("JARVIS_RVC_APP_DIR", "")
          if not py or not os.path.exists(py):
              return False
          return os.path.exists(os.path.join(app, "rvc", "infer", "infer.py"))


      def _gen_ack(ackdir, phrases, clone):
          """Gera os WAVs de ack (clone ou puro). Retorna lista existente."""
          os.makedirs(ackdir, exist_ok=True)
          existing = sorted(glob.glob(os.path.join(ackdir, "*.wav")))
          if not existing:
              tag = " +clone" if clone else ""
              print(f"[WW] Gerando respostas (1a vez){tag}...", flush=True)
              for i, phrase in enumerate(phrases):
                  cmd = ["jarvis", "speak", "--no-play", phrase]
                  if clone:
                      cmd.append("--clone")
                  subprocess.run(cmd, capture_output=True, timeout=300)
                  cands = sorted(
                      glob.glob(os.path.expanduser("~/.local/share/jarvis/voice/tts/*.wav")),
                      key=os.path.getmtime)
                  if cands:
                      shutil.move(cands[-1], os.path.join(ackdir, f"ack{i}.wav"))
              existing = sorted(glob.glob(os.path.join(ackdir, "*.wav")))
          return existing


      def _play_ack():
          """Ack no timbre do pipeline (clone se o spike existe, senão puro).

          Cache separado por modo; regenera o clone se o .pth for mais novo
          que o cache (treino novo → ack novo, sem rebuild).
          """
          try:
              lang = _ack_lang()
              phrases = ACK_PHRASES.get(lang, ACK_PHRASES["en"])
              base = os.path.expanduser(f"~/.local/share/jarvis/voice/ack-{lang}")
              existing = []
              if _rvc_ready():
                  cdir = base + "-clone"
                  try:
                      model = os.environ.get("JARVIS_VOICE_CLONE_MODEL", "")
                      models = [model] if model else sorted(glob.glob(
                          os.path.expanduser("~/models/Jarvis_*_best_epoch.pth")))
                      if models and os.path.exists(models[0]):
                          cur = sorted(glob.glob(os.path.join(cdir, "*.wav")))
                          if cur and os.path.getmtime(models[0]) > os.path.getmtime(cur[0]):
                              print(f"[WW] Modelo RVC novo, regenerando ack...", flush=True)
                              shutil.rmtree(cdir, ignore_errors=True)
                  except OSError:
                      pass
                  existing = _gen_ack(cdir, phrases, True)
                  if not existing:
                      print(f"[WW] clone indisponível, ack simples", flush=True)
              if not existing:
                  existing = _gen_ack(base, phrases, False)
              if existing:
                  picked = random.choice(existing)
                  print(f"[WW] 🔊 ack: {os.path.basename(os.path.dirname(picked))}/{os.path.basename(picked)}", flush=True)
                  subprocess.run(["pw-play", picked],
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
          speech_peak = 0.0  # pico RMS da fala atual (endpoint relativo, legado)
          suppress_until = 0.0  # anti self-trigger: ignora onset após brain/TTS
          followup_until = 0.0  # conversa: 1 captura pós-brain dispensa wake
          expect_command_until = 0.0  # two-phase: comando puro pós-ack
          echo_until = 0.0  # ignora onsets no eco do ack (sem drenar áudio)
          speech_buf = []  # buffer for consecutive speech chunks
          pre_roll = []  # circular buffer: last N chunks before speech onset (~770ms)
          BRAIN_TIMEOUT = 120  # STT cold start ~30s + LLM + TTS

          def _process_speech():
              """Loop VAD entregou uma captura: wake → (ack) → comando → brain.

              Two-phase (forense 2026-09): o wake e o comando andam juntos na
              mesma janela SÓ no one-breath (>3s). Caso comum: confirma o wake,
              toca o ack, e OUVE O COMANDO numa captura nova — sem wake junto
              na transcrição e sem turno LLM para "hey jarvis" sozinho.
              """
              nonlocal followup_until, expect_command_until, echo_until
              if KILL_TTS:
                  for pat in ["pw-play", "paplay", "aplay", "enhanced_audiobook.py"]:
                      subprocess.run(["pkill", "-9", pat], stderr=subprocess.DEVNULL)
              timestamp = int(time.time())
              temp_wav = f"/tmp/jarvis_cmd_{timestamp}.wav"
              with wave.open(temp_wav, "wb") as wf:
                  wf.setnchannels(2)
                  wf.setsampwidth(2)
                  wf.setframerate(RATE)
                  wf.writeframes(b"".join(speech_frames))
              duration_s = len(speech_frames) * CHUNK / RATE
              print(f"[WW] 📼 Capturado: {temp_wav} ({len(speech_frames)} chunks, {duration_s:.1f}s)", flush=True)
              if not BRAIN_CMD:
                  _restart_capture()
                  return
              # Fase 2 ou follow-up: comando puro, sem scorer.
              if time.time() < expect_command_until or time.time() < followup_until:
                  if time.time() < followup_until:
                      followup_until = 0.0  # uso único
                      print(f"[WW] 💬 follow-up (sem wake, conversa ativa)", flush=True)
                  else:
                      expect_command_until = 0.0
                      print(f"[WW] 💬 comando pós-ack (two-phase)", flush=True)
                  play_sound(BEEP_SOUND)  # confirma que ouviu (sem ack de 2s)
                  _run_brain(temp_wav)
                  return
              # Fase 1: verifica o wake.
              if not _score_wake(temp_wav):
                  return  # rejeitado (restart interno)
              print(f"[WW] 🫡 Hey Jarvis confirmado", flush=True)
              update_status("listening", "🎤 Ouvindo...")
              notify("Jarvis", "Ouvindo…")
              play_sound(BEEP_SOUND)
              # Sempre ack + fase 2 (one-breath removido: heurística por duração
              # errava "wake + pausa" e queimava o comando — forense 2026-09).
              _play_ack()
              # Eco do ack: ignora onsets por 1s (NÃO drena por tempo — dreno
              # cego comia o comando do usuário; forense 2026-09). O pre-roll
              # continua enchendo, então nada se perde.
              echo_until = time.time() + 1.0
              speech_frames.clear()
              pre_roll.clear()
              speech_buf.clear()
              expect_command_until = time.time() + 12
              update_status("listening", "Fale agora…")
              print(f"[WW] 👂 fase 2: ouvindo comando (12s)", flush=True)

          def _score_wake(temp_wav):
              """Roda o verificador offline. True = wake confirmado."""
              nonlocal suppress_until
              import sys as _sys
              try:
                          _score = subprocess.run(
                              [_sys.executable, WW_SCORER, "--models",
                               os.path.expanduser(OWW_MODELS),
                               "--wav", temp_wav,
                               "--threshold", WW_THRESHOLD],
                              capture_output=True, text=True, timeout=60,
                          )
              except Exception as _ww_err:
                  print(f"[WW] ⚠️ scorer falhou: {_ww_err}, seguindo p/ STT", flush=True)
                  return True
              print(f"[WW] 🎯 {(_score.stdout or "").strip()}", flush=True)
              if _score.returncode != 0:
                  print(f"[WW] 🔇 wakeword rejeitado, ignorando", flush=True)
                  update_status("idle", "󰆪 Aguardando...")
                  suppress_until = time.time() + 3
                  _restart_capture()
                  return False
              return True

          def _restart_capture():
              """Reinicia o pw-record com re-kill e aviso de órfão."""
              nonlocal arecord_proc
              try:
                  arecord_proc.kill()
              except Exception:
                  pass
              try:
                  arecord_proc.wait(timeout=3)
              except Exception:
                  try:
                      arecord_proc.kill()
                  except Exception:
                      pass
                  print(f"[WW] ⚠️ pw-record não morreu no wait — possível órfão", flush=True)
              time.sleep(0.5)
              update_status("idle", "Aguardando...")
              arecord_proc = start_arecord()
              print(f"[WW] pw-record restarted PID: {arecord_proc.pid}", flush=True)

          def _run_brain(temp_wav):
              """STT → LLM → TTS + pós-turno. Retorna o rc (2 = vazio/wake puro)."""
              nonlocal suppress_until, followup_until, expect_command_until
              import shutil as _shutil
              update_status("transcribing", "Transcrevendo...")
              _rc = 1
              try:
                  if not _shutil.which(BRAIN_CMD[0]):
                      print(f"[WW] ❌ BRAIN_CMD '{BRAIN_CMD[0]}' não encontrado no PATH", flush=True)
                      update_status("error", f"Comando '{BRAIN_CMD[0]}' não encontrado")
                  else:
                      result = subprocess.run(
                          BRAIN_CMD + [temp_wav],
                          timeout=BRAIN_TIMEOUT,
                          capture_output=True, text=True,
                      )
                      _rc = result.returncode
                      if result.returncode == 2:
                          # Turno vazio (ruído/wake puro): idle silencioso, SEM
                          # erro/notify/follow-up (forense 2026-09).
                          update_status("idle", "󰆪 Aguardando...")
                          print(f"[WW] 💤 turno vazio (rc=2)", flush=True)
                      elif result.returncode != 0:
                          stderr_msg = (result.stderr or "")[:300]
                          stdout_msg = (result.stdout or "")[:300]
                          combined = stdout_msg + stderr_msg
                          print(f"[WW] ❌ brain falhou (exit {result.returncode}): {combined[:200]}", flush=True)
                          update_status("error", f"Erro: {stderr_msg[:60]}")
                          notify("Jarvis", f"Erro no pipeline: {stderr_msg[:80]}")
                          play_sound(ERROR_SOUND)
                      else:
                          print(f"[WW] ✅ brain OK: {(result.stdout or "")[:100]}", flush=True)
                          update_status("done", "Concluído")
                          # Follow-up SÓ em turno real: rc=2 (voz vazia/wake
                          # puro) ou stderr marcado NÃO estendem — senão
                          # capturas de ruído viram loop infinito (2026-09).
                          _err = result.stderr or ""
                          if result.returncode == 0 and "(voz vazia)" not in _err and "(só wakeword" not in _err:
                              # Conversa: próxima captura em 20s dispensa o wake.
                              followup_until = time.time() + 20
              except subprocess.TimeoutExpired:
                  print(f"[WW] ⏰ brain timeout ({BRAIN_TIMEOUT}s) — STT/LLM/TTS travou", flush=True)
                  update_status("error", f"Timeout: pipeline nao respondeu ({BRAIN_TIMEOUT}s)")
                  notify("Jarvis", "Pipeline de voz não respondeu (timeout)")
                  play_sound(ERROR_SOUND)
              except Exception as e:
                  print(f"[WW] ❌ brain error: {str(e)[:100]}", flush=True)
                  update_status("error", f"Exceção: {str(e)[:60]}")
                  notify("Jarvis", f"Erro: {str(e)[:80]}")
                  play_sound(ERROR_SOUND)
              # Supressão pós-brain: cauda do TTS ainda está no ar; sem isso o
              # daemon captura a própria voz (self-trigger, forense 2026-09).
              # 5s (antes 8s): follow-up abre em seguida (até 20s).
              suppress_until = time.time() + 5
              expect_command_until = 0.0
              _restart_capture()
              return _rc

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

                  # Sistema deWaybar/Pulsing status — mostra vida SEM tocar em
                  # estado de pipeline (transcribing/thinking/speaking/busy/
                  # done/error/listening são donos do brain; rebaixar p/ idle
                  # dessincronizava notify × waybar — forense 2026-09).
                  if chunk_count % 50 == 0:
                      try:
                          with open("/tmp/jarvis-status.json") as _sf:
                              _cur = json.load(_sf).get("state", "idle")
                      except Exception:
                          _cur = "idle"
                      if _cur == "idle":
                          pulse_symbols = ["  ", "  "]
                          update_status("idle", f"{pulse_symbols[pulse_state % 2]} Ouvindo...")
                          pulse_state += 1

                  if chunk_count % 10 == 0:
                      print(f"[WW] RMS: {rms:.0f} (baseline={noise_baseline:.0f}, gate={max(noise_baseline * 1.5, 250):.0f})", flush=True)

                  # Ignora o aquecimento inicial do mic
                  if chunk_count < WARMUP_CHUNKS:
                      continue

                  # Pre-roll: mantém últimos PRE_ROLL_CHUNKS chunks (~770ms)
                  # antes do onset de fala para capturar o início da frase.
                  pre_roll.append(data)
                  if len(pre_roll) > PRE_ROLL_CHUNKS:
                      pre_roll.pop(0)

                  # Atualiza o ruído de fundo (Passa-Baixa bilateral com clamp).
                  # Forense 2026-09 (ao vivo): baseline travava em ~38 (só aprendia
                  # p/ baixo) e o fim-por-silêncio (baseline*1.1=42) ficava
                  # inalcançável no ruído real (~250) → toda captura estourava em
                  # MAX_RECORD 12s, diluindo a fala e matando o score do wakeword.
                  if not speaking:
                      if rms < noise_baseline * 1.2:
                          noise_baseline = noise_baseline * 0.95 + rms * 0.05
                      elif rms < 3000:
                          noise_baseline = noise_baseline * 0.998 + rms * 0.002
                      noise_baseline = max(200.0, min(noise_baseline, 3000.0))

                      speech_gate = max(noise_baseline * 1.6, 400)
                  else:
                      speech_gate = max(noise_baseline * 1.5, 250)

                  # Cooldown check
                  if (time.time() - last_trigger_time) < COOLDOWN:
                      continue

                  # VAD: detect speech onset (forense 2026-09: 3/5 com gate 400
                  # disparava no ruído ~500 → loop de capturas de 12s).
                  # 1. Ignore very quiet audio (electronic noise)
                  if rms < 50:
                      continue

                  # 2. Adaptive threshold: 80% above baseline, floor 450
                  # 3. Require 4 of last 6 chunks above gate
                  if not speaking:
                      if time.time() < suppress_until:
                          speech_buf = []
                          continue
                      if time.time() < echo_until:
                          speech_buf = []
                          continue
                      # Fase 2 expirou sem comando: volta a idle.
                      if expect_command_until and time.time() >= expect_command_until:
                          expect_command_until = 0.0
                          update_status("idle", "󰆪 Aguardando...")
                          print(f"[WW] ⌛ fase 2 expirou sem comando", flush=True)
                          continue
                      onset_gate = max(noise_baseline * 1.8, 450)
                      speech_buf.append(1 if rms > onset_gate else 0)
                      speech_buf = speech_buf[-6:]
                      if sum(speech_buf) >= 4:
                          speaking = True
                          speech_peak = float(rms)
                          # Pre-roll: inclui os últimos ~770ms antes do onset
                          speech_frames = list(pre_roll) + [data]
                          silence_start = None
                          speech_buf = []
                          update_status("listening", "🎤 Ouvindo...")
                          print(f"[WW] 🎤 Speech detected (RMS={rms:.0f}, baseline={noise_baseline:.0f}, gate={speech_gate:.0f}, pre_roll={len(pre_roll)} chunks)", flush=True)
                      continue

                  # Currently speaking — accumulate frames
                  speech_frames.append(data)
                  # Decay lento: em 12s o pico cai a ~70% (não ~15%) para o
                  # endpoint continuar valendo em capturas longas ruidosas.
                  speech_peak = max(float(rms), speech_peak * 0.999)

                  # Fim-por-silêncio relativo ao pico (legado: 40% drop do pico
                  # RMS) com pisos: funciona mesmo com baseline descalibrada.
                  silence_gate = max(noise_baseline * 1.1, speech_peak * 0.4, 200.0)

                  # Check for silence or max duration
                  recording_duration = len(speech_frames) * CHUNK / RATE
                  if recording_duration > MAX_RECORD:
                      # Hard limit — stop recording and process
                      speaking = False
                      last_trigger_time = time.time()
                      update_status("processing", "Gravação máxima atingida")
                      print(f"[WW] ⏱️ Max record reached ({MAX_RECORD}s)", flush=True)
                      _process_speech()
                  elif rms < silence_gate and recording_duration > 1.0:
                      # Silence detected: abaixo do gate por 1.5s (mín 1s gravado).
                      # 2.5s nunca segurava no ruído oscilante → tudo ia a 12s.
                      if silence_start is None:
                          silence_start = time.time()
                      elif time.time() - silence_start > 1.5:
                          speaking = False
                          last_trigger_time = time.time()
                          update_status("transcribing", "Transcrevendo...")
                          print(f"[WW] ✅ Speech ended ({len(speech_frames)} chunks, {len(speech_frames)*CHUNK/RATE:.1f}s, gate={silence_gate:.0f})", flush=True)
                          _process_speech()
                  else:
                      # Speech continuing — reset silence timer
                      silence_start = None
              except Exception as e:
                  print(f"[WW] ERROR: {str(e)[:100]}", flush=True)
                  time.sleep(0.1)


      if __name__ == "__main__":
          main()
    '';
in {
  options.services.jarvis-wakeword = {
    enable = lib.mkEnableOption "Jarvis Wakeword Daemon";
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
      default = 10;
      description = "Limite máximo de gravação após trigger.";
    };
    silenceDrop = lib.mkOption {
      type = lib.types.float;
      default = 0.6;
      description = "Fração do pico RMS que define silêncio (0.6 = 40% drop, silence adaptativo).";
    };
    wakeThreshold = lib.mkOption {
      type = lib.types.float;
      default = 0.4;
      description = "Score mínimo do hey_jarvis ONNX. Forense 2026-09: 0.5 rejeitava wake real (0.49) no ruído; ruído fica <0.15.";
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
      # Pré-baixa modelo STT small (multilingual, ~500MB, PT-BR correto) — evita timeout
      STT_DIR="$HOME/.local/share/jarvis/voice"
      SMALL_DIR="$STT_DIR/models--Systran--faster-whisper-small/snapshots/main"
      if [ ! -f "$SMALL_DIR/model.bin" ]; then
        mkdir -p "$SMALL_DIR"
        echo "[jarvis] Baixando modelo STT small (multilingual)..."
        for f in model.bin config.json vocabulary.txt tokenizer.json; do
          wget -q --timeout=30 "https://huggingface.co/Systran/faster-whisper-small/resolve/main/$f" -O "$SMALL_DIR/$f" 2>/dev/null || true
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
          "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"
          "DISPLAY=:0"
          "WAYLAND_DISPLAY=wayland-1"
          # Voz do TTS segue o ackLang (pm_alex p/ pt) em vez do LANG do sistema
          # (forense 2026-09: resposta sem acentos caía em af_heart).
          "JARVIS_TTS_LANG=${if cfg.ackLang == null then "auto" else cfg.ackLang}"
          # Modelo STT: espelha modules/ai/models.nix (whisper-small).
          # Trocar o modelo = trocar aqui junto (fonte de verdade é o .nix).
          "JARVIS_STT_MODEL=small"
          # Spike RVC (efêmero em /tmp — some no reboot; voice_clone faz
          # fallback p/ TTS puro quando ausente). Libs via nix (sem hash fixo).
          "JARVIS_RVC_PYTHON=/tmp/opencode/tts-venv/bin/python"
          "JARVIS_RVC_APP_DIR=/tmp/opencode/applio"
          "JARVIS_RVC_LD_PATH=${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.zlib}/lib"
          "JARVIS_VOICE_CLONE_MODEL=${config.home.homeDirectory}/models/Jarvis_62e_434s_best_epoch.pth"
          "JARVIS_VOICE_CLONE_INDEX=${config.home.homeDirectory}/models/added_Jarvis_v2.index"
        ];
      };
      Install = {
        WantedBy = ["graphical-session.target"];
      };
    };
  };
}
# rebuild 1788743158
