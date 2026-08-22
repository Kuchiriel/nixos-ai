{ pkgs, config, lib, jarvisEnvironment, ... }:
let
  isHost = jarvisEnvironment == "host";

  baseEnv = [
    "NIXOS_OZONE_WL,1"
    "XDG_CURRENT_DESKTOP,Hyprland"
    "XDG_SESSION_TYPE,wayland"
    "XDG_SESSION_DESKTOP,Hyprland"
    "QT_QPA_PLATFORM,wayland"
    "QT_QPA_PLATFORMTHEME,qt6ct"
    "XDG_SCREENSHOTS_DIR,$HOME/screens"
  ];

  # NVIDIA env vars — RTX 4050 NO HOST apenas.
  # Na VM (sem GPU), essas vars quebram VA-API e causam erros no waybar/mpvpaper.
  # No host, LIBVA_DRIVER_NAME=nvidia é SOBRESCREVIDO por mpvpaper.nix para iHD
  # (iGPU Intel UHD 770 faz o decode de vídeo; RTX fica livre para o LLM).
  nvidiaEnv = lib.optionalAttrs isHost {
    GBM_BACKEND = "nvidia-drm";
    __GLX_VENDOR_LIBRARY_NAME = "nvidia";
  };
in

{
  wayland.windowManager.hyprland = {
    enable = true;
    configType = "hyprlang";

    settings = {
      "$fileManager" = "$terminal --app-id floating_shell -e yazi";
      "$mainMod" = "SUPER";
      "$menu" = "rofi -show drun -theme jarvis-cyan";
      "$terminal" = "foot";

      dwindle = {
        preserve_split = true;
      };

      env = baseEnv ++ (lib.mapAttrsToList (n: v: "${n},${v}") nvidiaEnv);

      exec-once = [
        "waybar"
        "wl-paste --type text --watch cliphist store"
        "wl-paste --type image --watch cliphist store"
      ];

      general = {
        border_size = 2;
        "col.active_border" = "rgba(00ffffcc) rgba(0088ffcc) 45deg";
        "col.inactive_border" = "rgba(595959aa)";
        gaps_in = 5;
        gaps_out = 10;
        layout = "dwindle";
        resize_on_border = true;
      };

      decoration = {
        rounding = 12;
        active_opacity = 0.95;
        inactive_opacity = 0.85;
        blur = {
          enabled = true;
          size = 8;
          passes = 3;
          noise = 0.02;
          contrast = 1.0;
          brightness = 0.9;
          vibrancy = 0.2;
          vibrancy_darkness = 0.5;
          new_optimizations = true;
          xray = false;
        };
        shadow = {
          enabled = true;
          range = 20;
          render_power = 4;
          color = "rgba(00ffff44)";
          offset = "0, 4";
        };
      };

      animations = {
        enabled = true;
        bezier = [
          "myBezier, 0.05, 0.9, 0.1, 1.05"
          "smooth, 0.25, 0.1, 0.25, 1.0"
          "easeOutBack, 0.34, 1.56, 0.64, 1"
        ];
        animation = [
          "windows, 1, 4, myBezier"
          "windowsOut, 1, 4, smooth, popin 80%"
          "fade, 1, 3, smooth"
          "workspaces, 1, 4, default, slide"
          "layers, 1, 3, smooth, fade"
          "specialWorkspace, 1, 4, smooth, slidevert"
        ];
      };

      input = {
        follow_mouse = 1;
        kb_layout = "br";
      };

      # Keybinds ficam em binds.nix (porta do legado Manjaro + JARVIS AI)

      master = {
        mfact = 0.5;
        new_on_top = true;
        new_status = "slave";
      };

      misc = {
        disable_hyprland_logo = true;
        force_default_wallpaper = 0;
      };

      monitor = ",preferred,auto,1";

      windowrule = [
        "opacity 0.92 0.92, match:class ^(firefox)$"
        "opacity 0.90 0.90, match:class ^(foot)$"
        "float 1, match:class ^(mpv)$"
        "float 1, match:class ^(imv)$"
        "float 1, match:class ^(showmethekey-gtk)$"
        "move 990 60, match:class ^(showmethekey-gtk)$"
        "size 900 170, match:class ^(showmethekey-gtk)$"
        "pin 1, match:class ^(showmethekey-gtk)$"
        "workspace 3, match:class ^(obsidian)$"
        "workspace 3, match:class ^(zathura)$"
        "workspace 4, match:class ^(com.obsproject.Studio)$"
        "workspace 5, match:class ^(telegram)$"
        "float 1, match:class ^.*[Ww]urm.*$"
        "opacity 1.0 override 1.0 override, match:class ^.*[Ww]urm.*$"
        "suppress_event maximize, match:class ^(.*)$"
        "float 1, match:title ^(Wurm Macro)$"
        "pin 1, match:title ^(Wurm Macro)$"
        "opacity 0.9 0.9, match:title ^(Wurm Macro)$"
      ];
    };

    systemd = {
      enable = true;
    };
  };
}
