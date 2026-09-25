{
  pkgs,
  lib,
  jarvisEnvironment,
  ...
}:
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
in {
  home.packages = [pkgs.mpvpaper pkgs.mpv];

  # VA-API Intel (iHD) para decode de vídeo na iGPU do host (Nitro V15:
  # Intel UHD 770). LIBVA_DRIVER_NAME=iHD força o driver Intel correto.
  home.sessionVariables = {
    LIBVA_DRIVER_NAME = "iHD";
  };

  systemd.user.services.mpvpaper = lib.mkIf isHost {
    Unit = {
      Description = "JARVIS — wallpaper animado (mpvpaper, mp4 na iGPU)";
      ConditionVirtualization = "!vm"; # rede de segurança extra
      After = ["graphical-session.target"];
    };
    Service = {
      # Flags validadas ao vivo em 25/09 (antes: wallpapers PARADOS):
      #   SEM -p → auto-pause disparava sempre no Hyprland (frame-callback
      #     da layer nunca chega; manpage admite "might not work as intended")
      #   SEM --framedrop=vo + COM --video-sync=display-desync → com
      #     framedrop a apresentação travava (929 frames dropados, tempo
      #     congelado em 00:00:00); desync apresenta no relógio do vídeo
      #     (1-2 drops/roda = jitter normal de vsync).
      #   --fps=24 → teto cinematográfico (medido: 30fps=render 11%,
      #     15fps=render 8%; 24 = meio-termo suave sem gastar à toa).
      #   -n 30 → SLIDESHOW (troca de vídeo a cada 30s, não limite de FPS).
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
        "-n"
        "30"
        "-l"
        "background"
        "-o"
        ''"--no-audio --hwdec=vaapi --loop --video-sync=display-desync --fps=24"''
        "*"
        "${wallpapersDir}"
      ];
      Restart = "on-failure";
      RestartSec = 5;
    };
    Install = {WantedBy = ["hyprland-session.target"];};
  };
}
