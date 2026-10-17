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
          # (17/10) bug histórico: "set 30" sem % = valor BRUTO 30/19200 = 0%
          # = tela preta. "set 30%" = 30% de verdade; -s salva o restore.
          on-timeout = "brightnessctl -s set 30%";
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

}
# (17/10) O agent-keepawake saiu daqui: mesclado no watcher único
# (modules/agents-watcher.nix → scripts/agents-watcher.sh, hold de
# systemd-inhibit sleep:idle enquanto houver agente vivo).
