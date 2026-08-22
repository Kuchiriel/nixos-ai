{ pkgs, lib, jarvisEnvironment, ... }:
# mpvpaper — wallpaper animado (mp4 via mpv) — porta do legado Manjaro.
#
# Legado (hyprland.conf do Manjaro):
#   exec-once = env DRI_PRIME=pci-0000_00_02_0 mpvpaper -f -p -n 30 -l background \
#     -o "--no-audio --hwdec=vaapi --loop" '*' ~/Vídeos/Wallpapers
#
# Condicional declarativa:
#   - Host (bare metal): decode por HARDWARE via VA-API na iGPU Intel (UHD 770)
#     — a dGPU (RTX 4050) fica livre para o LLM.
#     DRI_PRIME força o decode na iGPU via VA-API.
#   - VM (lab): NÃO sobe — sem GPU, o decode em software roubaria CPU.
#
# Wallpapers: home-manager/assets/wallpapers/*.mp4 (copiados do legado Manjaro)
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
      # Porta do legado Manjaro (corrigido para NixOS):
      #   DRI_PRIME=pci-0000_00_02_0 → força decode na iGPU Intel
      #   -p → presentation mode (sem bordas, fullscreen)
      #   -n 30 → limita a 30 FPS (economiza CPU/GPU)
      #   -l background → camada background (abaixo de janelas)
      #   --hwdec=vaapi → decode por hardware VA-API na iGPU Intel
      #   --no-audio → sem áudio do wallpaper
      #   --loop → repete wallpaper infinitamente
      #   --framedrop=vo → drop frames no output (evita travamento longo)
      # NOTA: --vo=gpu REMOVIDO — mpvpaper só suporta libmpv (ignora vo).
      # NOTA: hwdec=vaapi (não auto-safe) — auto-safe pode escolher a RTX em vez
      # da iGPU. DRI_PRIME + LIBVA_DRIVER_NAME=iHD força o decode no device certo.
      Environment = [
        "DRI_PRIME=pci-0000:00:02.0"
        "WAYLAND_DISPLAY=wayland-1"
        "XDG_RUNTIME_DIR=/run/user/1000"
      ];
      ExecStart = lib.concatStringsSep " " [
        "${pkgs.mpvpaper}/bin/mpvpaper"
        "-p" "-n" "30" "-l" "background"
        "-o"
        ''"--no-audio --hwdec=vaapi --loop --framedrop=vo"''
        "*"
        "${wallpapersDir}"
      ];
      Restart = "on-failure";
      RestartSec = 5;
    };
    Install = { WantedBy = [ "hyprland-session.target" ]; };
  };
}
