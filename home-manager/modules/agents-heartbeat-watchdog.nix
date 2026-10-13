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
# REGRA: reinicia o loop SÓ se (a) o processo não existe E (b) há >= 2
# foots "OC |" (os 2 agentes vivos no Hyprland). Menos que 2 = o dono
# fechou = NÃO toca (evita o wtype-no-nada).
# Prova viva: journalctl --user -u agents-heartbeat-watchdog
let
  heartbeat-watchdog = pkgs.writeShellScriptBin "heartbeat-watchdog" ''
    set -u
    PATH=${pkgs.hyprland}/bin:${pkgs.coreutils}/bin:/run/current-system/sw/bin

    # 1. o loop já vive? -> nada a fazer
    if pgrep -f "agents-heartbeat.sh" >/dev/null 2>&1; then
      echo "[heartbeat-watchdog] loop vivo, ok"
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

    # 3. reinicia com log novo
    nohup setsid /home/nixos/projects/agents-heartbeat.sh \
      >> /tmp/opencode/heartbeat.log 2>&1 &
    echo "[heartbeat-watchdog] loop REINICIADO (foots=$NFOOTS)"
    /home/nixos/projects/team/tg.sh post \
      "[sandbox] heartbeat foi reanimado pelo watchdog (foots=$NFOOTS)" || true
  '';
in {
  home.packages = [ heartbeat-watchdog ];

  systemd.user.services.agents-heartbeat-watchdog = {
    Unit = {
      Description = "Reinicia o heartbeat dos agentes SO SE houver 2 janelas OC (evita wtype no nada)";
    };
    Service = {
      Type = "oneshot";
      ExecStart = "${heartbeat-watchdog}/bin/heartbeat-watchdog";
    };
  };

  systemd.user.timers.agents-heartbeat-watchdog = {
    Unit = {
      Description = "Watchdog do heartbeat dos agentes (a cada 5min)";
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
