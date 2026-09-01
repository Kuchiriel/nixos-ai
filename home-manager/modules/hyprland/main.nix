{
  lib,
  jarvisEnvironment,
  projectLib,
  ...
}: let
  inherit (projectLib) colors;
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
in {
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
        "col.active_border" = colors.hypr.activeBorder;
        "col.inactive_border" = colors.hypr.inactiveBorder;
        gaps_in = 5;
        gaps_out = 10;
        layout = "dwindle";
        resize_on_border = true;
      };

      decoration = {
        rounding = 10;
        active_opacity = 0.9;
        inactive_opacity = 0.8;
        blur = {
          enabled = false;
        };
        shadow = {
          enabled = true;
          range = 15;
          render_power = 3;
          color = colors.hypr.shadow;
        };
      };

      animations = {
        enabled = true;
        bezier = "myBezier, 0.05, 0.9, 0.1, 1.05";
        animation = [
          "windows, 1, 5, myBezier"
          "workspaces, 1, 4, default, slide"
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
        # Wurm Standalone: game fullscreen on ws3 + macro floating overlay
        "workspace 3, match:class ^(com.wurmonline.client.launcherfx.WurmMain)$"
        "fullscreen 1, match:class ^(com.wurmonline.client.launcherfx.WurmMain)$"
        "opacity 1.0 override 1.0 override, match:class ^(com.wurmonline.client.launcherfx.WurmMain)$"
        "workspace 3, match:title (Wurm Macro)"
        "float 1, match:title (Wurm Macro)"
        "size 320 200, match:title (Wurm Macro)"
        "move 100 100, match:title (Wurm Macro)"
        "opacity 0.9 0.9, match:title (Wurm Macro)"
        "suppress_event maximize, match:class ^(.*)$"
      ];
    };

    systemd = {
      enable = true;
    };
  };
}
