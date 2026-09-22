{ pkgs, ... }: {
  services.hypridle = {
    enable = true;
    settings = {
      general = {
        before_sleep_cmd = "loginctl lock-session";
        after_sleep_cmd = "hyprctl dispatch dpms on";
        ignore_dbus_inhibit = false;
        lock_cmd = "pidof hyprlock || hyprlock";
      };

      listener = [
        {
          timeout = 180;
          on-timeout = "brightnessctl -s set 30";
          on-resume = "brightnessctl -r";
        }
        {
          timeout = 300;
          on-timeout = "loginctl lock-session";
          on-resume = "systemctl restart bluetooth.service 2>/dev/null || true";
        }
        {
          timeout = 600;
          on-timeout = "hyprctl dispatch dpms off";
          on-resume = "hyprctl dispatch dpms on";
        }
        {
          timeout = 1200;
          on-timeout = "systemctl suspend";
        }
      ];
    };
  };

  # Noites de agentes (opencode/freebuff/buffy) não podem ser mortas pelo
  # suspend de 20min do hypridle. Este serviço segura um lock de inibição
  # (sleep:idle, mode=block) enquanto qualquer agente estiver rodando e
  # LIBERA sozinho ≤4min depois que o último sai (lock expira sem renovação).
  # O logind nega o `systemctl suspend` enquanto o lock existe; tela pode
  # apagar (dpms) — processos seguem vivos.
  systemd.user.services.agent-keepawake = {
    Unit = {
      Description = "Inibe suspend/idle enquanto agentes de IA estiverem rodando";
      After = [ "graphical-session.target" ];
    };
    Service = {
      Type = "simple";
      ExecStart = toString (pkgs.writeShellScript "agent-keepawake" ''
        while true; do
          # [x] trick: não casa com o próprio pgrep na cmdline deste script
          if pgrep -u "$USER" -f '[o]pencode|[f]reebuff|[b]uffy' >/dev/null 2>&1; then
            systemd-inhibit --what=sleep:idle --who=agents --mode=block \
              --why="agentes de IA ativos" sleep 240
          else
            sleep 60
          fi
        done
      '');
      Restart = "on-failure";
      RestartSec = "30s";
    };
    Install.WantedBy = [ "default.target" ];
  };
}
