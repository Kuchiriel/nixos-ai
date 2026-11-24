{ pkgs, lib, ... }: {
  services.hypridle = {
    enable = true;
    settings = {
      general = {
        # (24/11, pedido do dono) A maquina e' acessada por remoto: NADA
        # pode suspender, hibernar ou TRAVAR A SESSAO por automacao. Medido:
        #   - o logind de notebook suspende ao fechar a tampa
        #     (HandleLidSwitch=suspend, via busctl);
        #   - o hypridle travava a sessao em 5 min de idle e suspendia em
        #     20 min (estes dois listeners sairam);
        #   - o bind da tampa chamava `loginctl lock-session` (protecao de
        #     tela) — saiu em binds.nix.
        # O lock_cmd fica VAZIO: e' o que fazia a protecao de tela aparecer
        # quando a sessao era travada. O dono pediu a protecao desligada.
        before_sleep_cmd = "";
        after_sleep_cmd = "hyprctl dispatch dpms on";
        ignore_dbus_inhibit = false;
        lock_cmd = "";
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
          # (24/11) O lock automatico de 5 min saiu: com acesso remoto, a
          # protecao de tela prendia o dono fora da sessao. O lock manual
          # (SUPER+L) tambem nao mostra mais nada (lock_cmd vazio).
          timeout = 300;
          on-timeout = "notify-send 'Screen' 'Sem bloqueio automatico (acesso remoto)' 2>/dev/null || true";
          on-resume = "systemctl restart bluetooth.service 2>/dev/null || true";
        }
        {
          timeout = 600;
          on-timeout = "hyprctl dispatch dpms off";
          on-resume = "hyprctl dispatch dpms on";
        }
      ];
    };
  };

  # (24/11) A unit passa a apontar EXPLICITAMENTE para a config gerada
  # (~/.config/hypr/hypridle.conf). Sem isso o hypridle usa o caminho
  # padrao e a config do store, que nao e' a mesma coisa quando a unit
  # esta no home-manager: o ponto e' haver UM arquivo de config, gerado
  # pelo Nix, e a unit lendo exatamente ele.
  systemd.user.services.hypridle = {
    serviceConfig.ExecStart = lib.mkDefault
      "${pkgs.hypridle}/bin/hypridle -c %h/.config/hypr/hypridle.conf";
  };

}
# (17/10) O agent-keepawake saiu daqui: mesclado no watcher único
# (modules/agents-watcher.nix → scripts/agents-watcher.sh, hold de
# systemd-inhibit sleep:idle enquanto houver agente vivo).
