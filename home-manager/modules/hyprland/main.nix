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

  wayland.windowManager.hyprland = {
    enable = true;
    extraConfig = ''
      source = ~/.config/hyprland/dynamic.conf
    '';
    settings = {
      "$fileManager" = "$terminal --app-id floating_shell -e yazi";
      "$mainMod" = "SUPER";
      "$menu" = "wofi --show drun";
      "$terminal" = "foot";

      dwindle = {
        preserve_split = true;
        pseudotile = true;
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
          debug {
              damage_tracking = 0
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
          debug {
              damage_tracking = 2
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

      gestures = {
        workspace_swipe = true;
        workspace_swipe_forever = true;
        workspace_swipe_invert = false;
      };

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

      windowrulev2 = [
        "opacity 0.92 0.92,class:^(firefox)$"
        "opacity 0.9 0.9,class:^(foot)$"
        "bordersize 0, floating:0, onworkspace:w[t1]"
        "float,class:(mpv)|(imv)|(showmethekey-gtk)"
        "move 990 60,size 900 170,pin,noinitialfocus,class:(showmethekey-gtk)"
        "noborder,nofocus,class:(showmethekey-gtk)"
        "workspace 3,class:(obsidian)"
        "workspace 3,class:(zathura)"
        "workspace 4,class:(com.obsproject.Studio)"
        "workspace 5,class:(telegram)"
        "workspace 5,class:(vesktop)"
        "workspace 6,class:(teams-for-linux)"
        "suppressevent maximize, class:.*"
        "nofocus,class:^$,title:^$,xwayland:1,floating:1,fullscreen:0,pinned:0"
        "opacity 0.0 override, class:^(xwaylandvideobridge)$"
        "noanim, class:^(xwaylandvideobridge)$"
        "noinitialfocus, class:^(xwaylandvideobridge)$"
        "maxsize 1 1, class:^(xwaylandvideobridge)$"
        "noblur, class:^(xwaylandvideobridge)$"
        "nofocus, class:^(xwaylandvideobridge)$"
      ];

      workspace = [
        "w[tv1], gapsout:0, gapsin:0"
        "f[1], gapsout:0, gapsin:0"
      ];
    };

    systemd = {
      enable = true;
    };
  };
}
