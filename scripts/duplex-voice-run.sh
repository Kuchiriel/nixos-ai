#!/usr/bin/env bash
# duplex-voice-run.sh — runner do modo voz duplex (v6.2, madrugada 18/10).
# DIVISÃO DE ENVS (por medição, 30× de diferença!):
#   - MAIN + ASR-child: venv do KARAAK (ctranslate2 rápido: 71ms quente
#     vs 2.2s+ do env jarvis) — taskset E-cores 12-15.
#   - TTS daemon (duplex-ttsd.py): env JARVIS (kokoro) — o cliente sobe
#     sozinho (Tts._ensure_daemon resolve o python do wrapper vivo).
#   - llama-duplex-35b: P-cores 0-11 (pinned pelo systemd via taskset).
set -euo pipefail
# LIMPEZA DE ÓRFÃOS (18/10): o kill do cliente deixa os DAEMONS filhos
# vivos (ttsd em especial = múltiplos faladores no mesmo FIFO — a fonte
# do "ele não cala a boca"). Padrões não casam com ESTE script (run.sh).
for pat in "duplex-ttsd.py" "duplex-asrd.py" "scripts/duplex-voice.py"; do
  pkill -f "$pat" 2>/dev/null || true
done
sleep 1
PYBIN=/home/nixos/projects/karaok/.venv/bin/python3
[ -x "$PYBIN" ] || { echo "duplex-voice-run: venv karaok não achado" >&2; exit 1; }
exec taskset -c 12-15 "$PYBIN" \
  /home/nixos/projects/nixos-ai/scripts/duplex-voice.py "$@"
