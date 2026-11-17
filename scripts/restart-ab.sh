#!/bin/bash
# restart-ab.sh — reinicia o loop A/B com seguranca.
#
# O padrao do pgrep mora NESTE ARQUIVO, nunca na linha do SSH: `pgrep -f
# "scripts/ab_loop.sh"` casa com o proprio `bash -c` que o invoca (matamos o
# shell remoto duas vezes hoje). Aqui o comando do SSH e' so "bash restart-ab.sh".
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="/home/nixos/.local/state/jarvis/nightwatch"
LOG_DIR="/home/nixos/logs/ab_loop"
cd "$REPO" || exit 1

# 1) mata o loop e os filhos do harness (por PID, nunca pkill -f)
for P in $(pgrep -f 'scripts/ab_loop\.sh'); do
    [ "$P" = "$$" ] && continue
    kill -9 "$P" 2>/dev/null
done
for P in $(pgrep -f 'nightwatch\.dungeon'); do
    kill -9 "$P" 2>/dev/null
done

# 2) devolve a GPU (libera o residente da casa)
bash "$REPO/scripts/llm-swap.sh" release >/dev/null 2>&1

# 3) estado limpo
rm -f "$STATE/RUNNING.lock" "$STATE/ab_loop.pid"
printf 'run' > "$STATE/ab_loop.control"

# 4) sobe o loop, destacado do shell (sobrevive ao SSH)
mkdir -p "$LOG_DIR"
AB_LEVELS="${AB_LEVELS:-L1 L2 L3}" AB_SLEEP="${AB_SLEEP:-25}" AB_MODELS="${AB_MODELS:-bonsai mtp api}" \
    nohup setsid bash "$REPO/scripts/ab_loop.sh" \
    > "$LOG_DIR/launch.log" 2>&1 < /dev/null &

sleep 2
echo "novo pid: $(cat "$STATE/ab_loop.pid" 2>/dev/null || echo '(sem pidfile)')"
pgrep -af 'scripts/ab_loop\.sh' | head -3
