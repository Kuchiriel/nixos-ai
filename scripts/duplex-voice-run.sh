#!/usr/bin/env bash
# duplex-voice-run.sh — runner do modo voz duplex (v6.2, madrugada 18/10).
# DIVISÃO DE ENVS (por medição, 30× de diferença!):
#   - MAIN + ASR-child: venv do KARAAK (ctranslate2 rápido: 71ms quente
#     vs 2.2s+ do env jarvis) — taskset E-cores 12-15.
#   - TTS daemon (duplex-ttsd.py): env JARVIS (kokoro) — o cliente sobe
#     sozinho (Tts._ensure_daemon resolve o python do wrapper vivo).
#   - llama-duplex-35b: P-cores 0-11 (pinned pelo systemd via taskset).
set -euo pipefail
NIXAI="$(cd "$(dirname "$(realpath "$0")")/.." && pwd)"
# whisper-server GPU (18/10 09:00): 83ms/segmento medido. Sem ele vivo,
# o asrd v4 não transcreve. Sobe se precisa (porta 8097).
# (20/10 03:50) WHISPER_MODEL: env var p/ swap sem editar o script.
# (08:45) DEFAULT = turbo-q5_0 (produção provada 20/10: 900MiB residência
# < small 868+overhead, PT-BR impecável, 234ms/seg, multilingue 99 idiomas).
WHISPER_MODEL="${WHISPER_MODEL:-$HOME/models/whisper/ggml-large-v3-turbo-q5_0.bin}"
# (10:40) WHISPER_LANG: 'pt' (default — auto-detect ALUCINA traduções
# EN na voz piper/PT: 'que dia é hoje' → 'I wish that day is today';
# PT travado = confiável p/ o uso diário) | 'auto' = multilingue
# (dono testando EN/JA/ZH ou capturando mídia estrangeira).
WHISPER_LANG="${WHISPER_LANG:-pt}"
LANG_FLAG=""
[ "$WHISPER_LANG" != "auto" ] && LANG_FLAG="-l $WHISPER_LANG"
if ! curl -s -o /dev/null --max-time 2 http://127.0.0.1:8097/health 2>/dev/null \
   && ! curl -s -o /dev/null --max-time 2 -F x=1 http://127.0.0.1:8097/inference 2>/dev/null; then
  # (03/11) O whisper-server é um SERVIÇO systemd (whisper-server.service,
  # modules/services/whisper-server.nix): sem ele o processo morria no
  # boot com CUDA OOM (VRAM disputada com o 4B-MTP) e o duplex ficava
  # SURDO. O fallback manual abaixo só cobre dev sem systemd.
  if systemctl start whisper-server.service 2>/dev/null; then
    echo "duplex-voice-run: whisper-server.service iniciado" >&2
  else
    setsid nohup "${WHISPER_CPP_DIR:-$HOME/projects/whisper.cpp}/build/bin/whisper-server" \
      -m "$WHISPER_MODEL" $LANG_FLAG --port 8097 --host 127.0.0.1 \
      > /tmp/opencode/whisper-server.log 2>&1 < /dev/null &
  fi
  # Espera o ASR ficar pronto (o modelo carrega em ~5-20 s; sem isso o
  # cliente nasce com o ASR mudo e só descobre minutos depois).
  for _i in $(seq 1 30); do
    curl -s -o /dev/null --max-time 2 http://127.0.0.1:8097/health 2>/dev/null && break
    sleep 1
  done
fi
# LIMPEZA DE ÓRFÃOS (18/10): o kill do cliente deixa os DAEMONS filhos
# vivos (ttsd em especial = múltiplos faladores no mesmo FIFO — a fonte
# do "ele não cala a boca"). Padrões não casam com ESTE script (run.sh).
for pat in "duplex-ttsd.py" "duplex-asrd.py" "scripts/duplex-voice.py"; do
  pkill -f "$pat" 2>/dev/null || true
done
sleep 1
KARAOK_DIR="${KARAOK_DIR:-$HOME/projects/karaok}"
PYBIN="${KARAOK_PY:-$KARAOK_DIR/.venv/bin/python3}"
[ -x "$PYBIN" ] || { echo "duplex-voice-run: venv karaok não achado" >&2; exit 1; }
# (10/11, coord-naming) O CLIENTE tambem precisa do libstdc++/libz: o numpy
# do venv karaok é uma wheel que espera o runtime do sistema, e sem isso o
# CLIENTE morre no import — foi assim que a voz caiu (medido 10/11: o log do
# start termina em "libstdc++.so.6: cannot open shared object file"). O
# fix do asrd (scripts/asrd_env.py) resolvia o filho ASRD, mas nao este
# caminho; agora o runner resolve os mesmos diretorios antes do exec.
# (O resolver antigo pedia "nixpkgs#gcc.lib", que NAO existe nesta nixpkgs,
# e a falha era engolida — por isso a resolucao vive agora em asrd_env.py.)
_LD_PATHS="$(python3 "$NIXAI/scripts/asrd_env.py" --print 2>/dev/null || true)"
if [ -n "$_LD_PATHS" ]; then
  export LD_LIBRARY_PATH="${_LD_PATHS}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
else
  echo "duplex-voice-run: nao consegui resolver libstdc++/libz (asrd_env.py --print)" >&2
fi
exec taskset -c 12-15 "$PYBIN" \
  "$NIXAI/scripts/duplex-voice.py" "$@"
