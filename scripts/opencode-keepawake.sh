#!/usr/bin/env bash
# opencode-keepawake.sh — inibe tela de apagar/trancar/suspender quando
# agentes opencode estão vivos. hypridle (ignore_dbus_inhibit=false) respeta
# o lock systemd-inhibit, então este loop segura o idle timer.
#
# Detecção: processo 'opencode' (TUI ou serve) OU 'duplex-voice.py' (voz).
# Se nenhum agente vivo → libera (tela volta a apagar normalmente).
#
# USO: systemd user service (nixos-ai home-manager, agents-keepawake.service)
set -u

while true; do
    # detecta qualquer processo de agente
    if pgrep -f "opencode" >/dev/null 2>&1 || pgrep -f "duplex-voice" >/dev/null 2>&1; then
        # segura o lock por 55s (re-check a cada ciclo)
        systemd-inhibit --what=sleep:idle --why="opencode/duplex agent ativo" \
            --who="agents-keepawake" sleep 55 &
        INHIBIT_PID=$!
        wait $INHIBIT_PID 2>/dev/null || true
    else
        # sem agente → não inibe (tela apaga normalmente)
        sleep 30
    fi
done
