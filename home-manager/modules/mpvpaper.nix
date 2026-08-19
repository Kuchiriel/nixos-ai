{ pkgs, lib, jarvisEnvironment, ... }:
# mpvpaper — wallpaper animado (mp4 via mpv) — porta do legado.
#
# Condicional declarativa (água — segue o switch services.jarvis.environment
# passado via extraSpecialArgs: jarvisEnvironment):
#   - Host (bare metal): sobe com decode de vídeo por HARDWARE via VA-API
#     na iGPU Intel (hwdec) — a dGPU (RTX 4050) fica livre para o LLM.
#   - VM (lab): NÃO sobe — sem GPU, o decode em software roubaria CPU do
#     JARVIS; o hyprpaper estático cobre.
#
# Trocar o wallpaper: edite `video` abaixo (ou liste vários e alterne).
let
  isHost = jarvisEnvironment == "host";
in
{
  home.packages = [ pkgs.mpvpaper pkgs.mpv ];

  # VA-API Intel (iHD) para decode de vídeo na iGPU do host (Nitro V15:
  # Intel UHD 770). LIBVA_DRIVER_NAME=iHD força o driver Intel correto.
  home.sessionVariables = {
    LIBVA_DRIVER_NAME = "iHD";
  };

  systemd.user.services.mpvpaper = lib.mkIf isHost {
    Unit = {
      Description = "JARVIS — wallpaper animado (mpvpaper, mp4 na iGPU)";
      # Água: o serviço só EXISTE no host (services.jarvis.environment).
      # Na VM o hyprpaper estático cobre; o mpvpaper nem é definido.
      ConditionVirtualization = "!vm";  # rede de segurança extra
      After = [ "graphical-session.target" ];
    };
    Service = {
      # mpvpaper <opções mpv> <output> <vídeo> — loop infinito, sem som,
      # decode por hardware (VA-API → iGPU), escala para o monitor.
      ExecStart = lib.concatStringsSep " " [
        "${pkgs.mpvpaper}/bin/mpvpaper"
        "-o"
        ''"--hwdec=vaapi --loop --no-audio --no-osc --no-input-default-bindings --scale=bilinear"''
        "*"
        "${../assets/wallpapers}/brook-one-piece-requiem.1920x1080.mp4"
      ];
      Restart = "on-failure";
      RestartSec = 5;
    };
    Install = { WantedBy = [ "hyprland-session.target" ]; };
  };
}
