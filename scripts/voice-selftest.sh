#!/usr/bin/env bash
# Self-test autônomo do pipeline de voz (sem microfone).
# TTS Kokoro sintetiza comandos → STT transcreve → voice_loop roteia.
# Uso: ./scripts/voice-selftest.sh
# Saída: PASS/FAIL por etapa + tabela de timings (session.json).
set -u
DIR=/tmp/voice-selftest
DBG=$DIR/debug
mkdir -p "$DBG"
rm -f "$DBG"/* "$DIR"/cmd-*.wav 2>/dev/null

declare -A CMDS=(
  ["horas"]="que horas são"
  ["doctor"]="como está o sistema"
  ["data"]="que dia é hoje"
)
declare -A WANT_STT=(
  ["horas"]="horas"
  ["doctor"]="sistema"
  ["data"]="dia"
)
PASS=0
FAIL=0
echo "=== 1. TTS synth ==="
for k in horas doctor data; do
  out=$(jarvis speak --no-play "${CMDS[$k]}" 2>/dev/null | tail -1)
  cp "$out" "$DIR/cmd-$k.wav" 2>/dev/null && echo "OK   $k -> $DIR/cmd-$k.wav" && PASS=$((PASS+1)) || { echo "FAIL tts $k"; FAIL=$((FAIL+1)); }
done
echo "=== 2. STT ==="
for k in horas doctor data; do
  txt=$(jarvis stt --language pt "$DIR/cmd-$k.wav" 2>/dev/null)
  if echo "$txt" | grep -qi "${WANT_STT[$k]}"; then echo "OK   stt/$k: $txt" && PASS=$((PASS+1)); else echo "FAIL stt/$k: $txt"; FAIL=$((FAIL+1)); fi
done
echo "=== 3. voice_loop --no-tts --debug-wav ==="
for k in horas doctor data; do
  if jarvis voice --no-tts --debug-wav "$DBG" "$DIR/cmd-$k.wav" >/tmp/voice-selftest/out-$k.txt 2>&1; then
    echo "OK   voice/$k rc=0: $(head -c 100 /tmp/voice-selftest/out-$k.txt)"
    PASS=$((PASS+1))
  else
    echo "FAIL voice/$k: $(head -c 200 /tmp/voice-selftest/out-$k.txt)"
    FAIL=$((FAIL+1))
  fi
done
echo "=== 4. timings (session.json) ==="
python3 - "$DBG" <<'EOF'
import json, glob, sys
for p in sorted(glob.glob(sys.argv[1] + '/*.json')):
    d = json.load(open(p))
    a = d.get('audio', {})
    print(f"{d.get('stt_s', '?'):>6}s stt | {d.get('route', '?'):>8} {d.get('route_s', '?'):>5}s | llm {d.get('llm_s', '?'):>6}s | tts {d.get('tts_s', '?'):>5}s | total {d.get('total_s', '?'):>6}s | {d.get('text','')[:50]}")
EOF
echo "=== PASS=$PASS FAIL=$FAIL ==="
[ "$FAIL" -eq 0 ]
