#!/usr/bin/env bash
# agents-keepawake.sh — inibe o idle (tela) enquanto houver agente vivo.
# hypridle (ignore_dbus_inhibit=false) respeita o lock systemd-inhibit,
# então este loop segura o idle timer.
#
# Detecção: opencode (TUI/CLI/serve) | freebuff | buffy | duplex-voice (voz).
# Sem nenhum agente → não inibe (a tela volta a apagar normalmente).
#
# AUTO-MATCH (a lição): o cmdline do PRÓPRIO script e o do systemd-inhibit
# NÃO podem conter os padrões — senão o pgrep acha a si mesmo e a tela
# nunca mais dorme. Por isso o script se chama agents-keepawake.sh (não
# "opencode-*") e o --why não diz "opencode".
#
# USO: systemd user service (nixos-ai home-manager, agents-keepawake.service)
set -u

while true; do
    if pgrep -u "$USER" -f '[o]pencode|[f]reebuff|[b]uffy|[d]uplex-voice' >/dev/null 2>&1; then
        # segura o lock por 55s (re-check a cada ciclo)
        systemd-inhibit --what=sleep:idle --mode=block \
            --who="agents-keepawake" --why="agente de IA ativo" sleep 55 &
        wait $! 2>/dev/null || true
    else
        # sem agente → não inibe (tela apaga normalmente)
        sleep 30
    fi
done
