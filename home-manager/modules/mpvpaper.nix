{ pkgs, lib, jarvisEnvironment, ... }:
# mpvpaper — wallpaper animado (mp4 via mpv) — porta do legado Manjaro.
#
# Legado (hyprland.conf do Manjaro):
#   exec-once = env DRI_PRIME=pci-0000_00_02_0 mpvpaper -f -p -n 30 -l background \
#     -o "--no-audio --hwdec=vaapi --vo=gpu" '*' ~/Vídeos/Wallpapers
#
# Condicional declarativa:
#   - Host (bare metal): decode por HARDWARE via VA-API na iGPU Intel (UHD 770)
#     — a dGPU (RTX 4050) fica livre para o LLM.
#     DRI_PRIME força o decode na iGPU; --vo=gpu usa OpenGL na iGPU.
#   - VM (lab): NÃO sobe — sem GPU, o decode em software roubaria CPU.
#
# Wallpapers: /etc/jarvis/wallpapers/*.mp4 (copiados do legado via Nix store)
let
  isHost = jarvisEnvironment == "host";
  wallpapersDir = ../assets/wallpapers;
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
      ConditionVirtualization = "!vm";  # rede de segurança extra
      After = [ "graphical-session.target" ];
    };
    Service = {
      # Porta fiel do legado Manjaro:
      #   DRI_PRIME=pci-0000_00_02_0 → força decode na iGPU Intel
      #   -f → fork (mpvpaper retorna imediato)
      #   -p → presentation mode (sem bordas, fullscreen)
      #   -n 30 → limita a 30 FPS (economiza CPU/GPU)
      #   -l background → camada background (abaixo de janelas)
      #   --hwdec=vaapi → decode por hardware (VA-API → iGPU)
      #   --vo=gpu → renderização OpenGL (na iGPU)
      #   --no-audio → sem áudio do wallpaper
      Environment = "DRI_PRIME=pci-0000_00_02.0";
      ExecStart = lib.concatStringsSep " " [
        "${pkgs.mpvpaper}/bin/mpvpaper"
        "-f" "-p" "-n" "30" "-l" "background"
        "-o"
        ''"--no-audio --hwdec=vaapi --vo=gpu --loop"''
        "*"
        "${wallpapersDir}"
      ];
      Restart = "on-failure";
      RestartSec = 5;
    };
    Install = { WantedBy = [ "hyprland-session.target" ]; };
  };
}
