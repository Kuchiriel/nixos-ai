{
  pkgs,
  lib,
  jarvisEnvironment,
  ...
}:
# Sunshine — host de game-streaming (Moonlight no celular, 4G via VPN).
# Stack remota do dono: ssh + telegram + moonlight.
# Input (uinput) já liberado: hardware.uinput.enable + grupos input/uinput
# no host. Firewall: hosts/nitro-v15/configuration.nix (47984-48010).
# Primeiro uso: https://localhost:47990 → criar usuário/senha → parear o
# Moonlight com o PIN. Fora de casa: Tailscale (recomendado) ou port-forward.
let
  isHost = jarvisEnvironment == "host";
in {
  home.packages = [pkgs.sunshine];

  systemd.user.services.sunshine = lib.mkIf isHost {
    Unit = {
      Description = "Sunshine — game streaming p/ Moonlight (remoto 4G)";
      After = ["graphical-session.target"];
      PartOf = ["graphical-session.target"];
    };
    Service = {
      Environment = [
        "WAYLAND_DISPLAY=wayland-1"
        "XDG_RUNTIME_DIR=/run/user/1000"
      ];
      ExecStart = "${pkgs.sunshine}/bin/sunshine";
      Restart = "on-failure";
      RestartSec = "5";
    };
    Install = {
      WantedBy = ["graphical-session.target"];
    };
  };
}
