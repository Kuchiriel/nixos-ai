{ pkgs, config, lib, ... }:
let
  baseEnv = [
    "NIXOS_OZONE_WL,1"
    "XDG_CURRENT_DESKTOP,Hyprland"
    "XDG_SESSION_TYPE,wayland"
    "XDG_SESSION_DESKTOP,Hyprland"
    "QT_QPA_PLATFORM,wayland"
    "QT_QPA_PLATFORMTHEME,qt6ct"
    "XDG_SCREENSHOTS_DIR,$HOME/screens"
  ];
in
{
  home.activation.generateHyprlandRuntimeConfig = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    mkdir -p $HOME/.config/hyprland
  '';
  home.file.".config/hyprland/dynamic.conf".text = "";
  wayland.windowManager.hyprland = {
    enable = true;
    # 26.05 mudou o default p/ "lua"; mantemos hyprlang (configs atuais)
    configType = "hyprlang";
    extraConfig = ''
      source = source = ~/.config/hyprland/dynamic.conf
    '';
    settings = {
      "$fileManager" = "$terminal --app-id floating_shell -e yazi";
      "$mainMod" = "SUPER";
      "$menu" = "wofi --show drun";
      "$terminal" = "foot";

      dwindle = {
        preserve_split = true;
        # pseudotile removido em Hyprland recente (dwindle:pseudotile deprecated)
      };

      env = baseEnv;

      exec-once = [
        "${pkgs.writeShellScriptBin "hyprland-runtime-setup" ''
          if systemd-detect-virt -q; then
            cat << 'EOF' > $HOME/.config/hyprland/dynamic.conf
          animations {
              enabled = false
          }
          cursor {
              no_hardware_cursors = true
          }
          decoration {
              rounding = 0
              active_opacity = 0.9
              inactive_opacity = 0.8
              blur {
                  enabled = false
              }
              shadow {
                  enabled = false
              }
          }
          general {
              allow_tearing = false
              border_size = 2
              col.active_border = rgba(00ffffcc) rgba(0088ffcc) 45deg
              col.inactive_border = rgba(595959aa)
              gaps_in = 2
              gaps_out = 4
              layout = dwindle
              resize_on_border = true
          }
          env = WLR_NO_HARDWARE_CURSORS,1
          env = WLR_RENDERER,pixman
          env = WLR_RENDER_NO_EXPLICIT_SYNC,1
          EOF
          else
            cat << 'EOF' > $HOME/.config/hyprland/dynamic.conf
          animations {
              enabled = true
              bezier = myBezier, 0.05, 0.9, 0.1, 1.05
              animation = windows, 1, 5, myBezier
              animation = workspaces, 1, 4, default, slide
          }
          cursor {
              no_hardware_cursors = false
          }
          decoration {
              rounding = 10
              active_opacity = 0.9
              inactive_opacity = 0.8
              blur {
                  enabled = false
              }
              shadow {
                  enabled = false
              }
          }
          general {
              allow_tearing = false
              border_size = 2
              col.active_border = rgba(00ffffcc) rgba(0088ffcc) 45deg
              col.inactive_border = rgba(595959aa)
              gaps_in = 5
              gaps_out = 10
              layout = dwindle
              resize_on_border = true
          }
          EOF
            if lspci | grep -qi nvidia; then
              cat << 'EOF' >> $HOME/.config/hyprland/dynamic.conf
          env = LIBVA_DRIVER_NAME,nvidia
          env = GBM_BACKEND,nvidia-drm
          env = __GLX_VENDOR_LIBRARY_NAME,nvidia
          EOF
            fi
          fi
        ''}/bin/hyprland-runtime-setup"
        "waybar"
        "wl-paste --type text --watch cliphist store"
        "wl-paste --type image --watch cliphist store"
      ];

      input = {
        follow_mouse = 1;
        kb_layout = "br";
      };

      bind = [
        "$mainMod, RETURN, exec, $terminal"
        "$mainMod, Q, killactive,"
        "$mainMod, E, exec, $fileManager"
        "$mainMod, R, exec, $menu"
        "$mainMod, V, togglefloating,"
        "$mainMod, F, fullscreen,"
        "$mainMod, 1, workspace, 1"
        "$mainMod, 2, workspace, 2"
        "$mainMod, 3, workspace, 3"
        "$mainMod, 4, workspace, 4"
        "$mainMod, 5, workspace, 5"
        "$mainMod, 6, workspace, 6"
        "$mainMod SHIFT, 1, movetoworkspace, 1"
        "$mainMod SHIFT, 2, movetoworkspace, 2"
        "$mainMod SHIFT, 3, movetoworkspace, 3"
        "$mainMod SHIFT, 4, movetoworkspace, 4"
        "$mainMod SHIFT, 5, movetoworkspace, 5"
        "$mainMod SHIFT, 6, movetoworkspace, 6"
      ];

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

      # Sintaxe correta para seletores do tipo class:^...$
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
        "suppress_event maximize, match:class ^(.*)$"
      ];

    };

    systemd = {
      enable = true;
    };
  };
}
