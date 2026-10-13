{ config, lib, pkgs, ... }:
# agents-heartbeat-watchdog — o coração do loop dos 2 agentes com
# segurança condicional (13/10, dono: "antes funcionava com timer, mas
# pode ser watchdog mas CONDICIONAL só se tiver 2 janelas opencode,
# pra evitar bug de ficar mandando wtype no nada").
#
# O problema real (13/10): o loop agents-heartbeat.sh girou 1h20 em
# silêncio quando perdeu os foots (o `[ -z "$ENDS" ] && continue` não
# loga nada) e o dono notou os agentes "parados".
#
# (13/10 09:0x, CORREÇÃO — dono: "n tava funcionando… se tiver errado
# arrume oq ele fez") — o watchdog guardava o script ANTIGO
# time-based de 20min (exatamente o que o dono rejeitou: "working ou
# idle based, resolve melhor essa comunicação"). Agora guarda o
# agents-watcher.sh v2 (5min, WORKING/IDLE por CPU-delta calibrado,
# acorda SÓ idle E fila-mudou/15min-fallback — ver o cabeçalho dele).
#
# REGRA: reinicia o watcher SÓ se (a) o processo não existe E (b) há
# >= 2 foots "OC |" (os 2 agentes vivos no Hyprland). Menos que 2 = o
# dono fechou = NÃO toca (evita o wtype-no-nada).
# Prova viva: journalctl --user -u agents-heartbeat-watchdog
let
  heartbeat-watchdog = pkgs.writeShellScriptBin "heartbeat-watchdog" ''
    set -u
    PATH=${pkgs.hyprland}/bin:${pkgs.coreutils}/bin:/run/current-system/sw/bin

    # 1. o watcher já vive? -> nada a fazer
    if pgrep -f "agents-watcher.sh" >/dev/null 2>&1; then
      echo "[heartbeat-watchdog] watcher vivo, ok"
      exit 0
    fi

    # 2. quantos foots OC | existem? (a condição do dono)
    NFOOTS=$(hyprctl clients -j 2>/dev/null | python3 -c "
import json, sys
try:
    j = json.load(sys.stdin)
except Exception:
    print(0); sys.exit(0)
print(sum(1 for c in j if c.get('class') == 'foot'
          and (c.get('title') or "").startswith('OC |')))
" 2>/dev/null || echo 0)
    if [ "$NFOOTS" -lt 2 ]; then
      echo "[heartbeat-watchdog] sem as 2 janelas opencode (n=$NFOOTS) - NAO inicio (wtype-no-nada)"
      exit 0
    fi

    # 3. reinicia o watcher v2 (working/idle, 5min) com log novo
    nohup setsid /home/nixos/projects/agents-watcher.sh 300 \
      >> /tmp/opencode/watcher.log 2>&1 &
    echo "[heartbeat-watchdog] watcher v2 REINICIADO (foots=$NFOOTS)"
    /home/nixos/projects/team/tg.sh post \
      "[sandbox] watcher v2 (working/idle) foi reanimado pelo watchdog (foots=$NFOOTS)" || true
  '';
in {
  home.packages = [ heartbeat-watchdog ];

  systemd.user.services.agents-heartbeat-watchdog = {
    Unit = {
      Description = "Reinicia o watcher v2 (working/idle) dos agentes SO SE houver 2 janelas OC (evita wtype no nada)";
    };
    Service = {
      Type = "oneshot";
      ExecStart = "${heartbeat-watchdog}/bin/heartbeat-watchdog";
    };
  };

  systemd.user.timers.agents-heartbeat-watchdog = {
    Unit = {
      Description = "Watchdog do watcher dos agentes (a cada 5min)";
    };
    Timer = {
      OnCalendar = "*:0/5";
      Persistent = true;
    };
    Install = {
      WantedBy = [ "timers.target" ];
    };
  };
}
