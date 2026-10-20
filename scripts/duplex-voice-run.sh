#!/usr/bin/env bash
# duplex-voice-run.sh — runner do modo voz duplex (v6.2, madrugada 18/10).
# DIVISÃO DE ENVS (por medição, 30× de diferença!):
#   - MAIN + ASR-child: venv do KARAAK (ctranslate2 rápido: 71ms quente
#     vs 2.2s+ do env jarvis) — taskset E-cores 12-15.
#   - TTS daemon (duplex-ttsd.py): env JARVIS (kokoro) — o cliente sobe
#     sozinho (Tts._ensure_daemon resolve o python do wrapper vivo).
#   - llama-duplex-35b: P-cores 0-11 (pinned pelo systemd via taskset).
set -euo pipefail
# whisper-server GPU (18/10 09:00): 83ms/segmento medido. Sem ele vivo,
# o asrd v4 não transcreve. Sobe se precisa (porta 8097).
# (20/10 03:50) WHISPER_MODEL: env var p/ swap sem editar o script.
# (08:45) DEFAULT = turbo-q5_0 (produção provada 20/10: 900MiB residência
# < small 868+overhead, PT-BR impecável, 234ms/seg, multilingue 99 idiomas).
WHISPER_MODEL="${WHISPER_MODEL:-/home/nixos/models/whisper/ggml-large-v3-turbo-q5_0.bin}"
# (10:40) WHISPER_LANG: 'pt' (default — auto-detect ALUCINA traduções
# EN na voz piper/PT: 'que dia é hoje' → 'I wish that day is today';
# PT travado = confiável p/ o uso diário) | 'auto' = multilingue
# (dono testando EN/JA/ZH ou capturando mídia estrangeira).
WHISPER_LANG="${WHISPER_LANG:-pt}"
LANG_FLAG=""
[ "$WHISPER_LANG" != "auto" ] && LANG_FLAG="-l $WHISPER_LANG"
if ! curl -s -o /dev/null --max-time 2 http://127.0.0.1:8097/health 2>/dev/null \
   && ! curl -s -o /dev/null --max-time 2 -F x=1 http://127.0.0.1:8097/inference 2>/dev/null; then
  setsid nohup /home/nixos/projects/whisper.cpp/build/bin/whisper-server \
    -m "$WHISPER_MODEL" $LANG_FLAG --port 8097 --host 127.0.0.1 \
    > /tmp/opencode/whisper-server.log 2>&1 < /dev/null &
  sleep 6
fi
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
