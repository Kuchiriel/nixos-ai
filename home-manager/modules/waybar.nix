{ pkgs, ... }:

{
  programs.waybar = {
    enable = true;
    style = ''
      /* =========================================
         JARVIS AI_SYSTEM — WAYBAR STYLE
         ========================================= */

      * {
        border: none;
        border-radius: 0;
        font-family: "JetBrainsMono Nerd Font", "SymbolsNerdFont", sans-serif;
        font-size: 12.5px;
        min-height: 0;
      }

      /* ------------------------------
         BAR CONTAINER
         ------------------------------ */
      window#waybar {
        background: rgba(0, 0, 0, 0.85);
        border-bottom: 2px solid #00ffff;
        color: #00ffff;
      }

      /* ------------------------------
         MODULE BASE
         ------------------------------ */
      #workspaces button,
      #clock,
      #cpu,
      #memory,
      #battery,
      #network,
      #pulseaudio,
      #bluetooth,
      #backlight,
      #tray,
      #custom-files,
      #custom-weather,
      #custom-gpu,
      #custom-jarvis {
        padding: 0 12px;
        color: #00ffff;
        transition: all 0.25s ease;
      }

      /* ------------------------------
         WORKSPACES
         ------------------------------ */
      #workspaces button {
        background: transparent;
        color: #00ffff;
      }

      #workspaces button.active,
      #workspaces button.focused {
        background: rgba(0, 255, 255, 0.18);
        border-bottom: 2px solid #00ffff;
      }

      /* ------------------------------
         HOVER GLOW EFFECT
         ------------------------------ */
      #clock:hover,
      #cpu:hover,
      #memory:hover,
      #battery:hover,
      #network:hover,
      #pulseaudio:hover,
      #bluetooth:hover,
      #backlight:hover,
      #custom-files:hover,
      #custom-weather:hover,
      #custom-gpu:hover,
      #custom-jarvis:hover {
        text-shadow:
          0 0 4px #00ffff,
          0 0 8px #00ffff;
      }

      /* ------------------------------
         TRAY & TOOLTIP
         ------------------------------ */
      #tray {
        padding-right: 8px;
      }

      tooltip {
        background: rgba(0, 0, 0, 0.9);
        border: 1px solid #00ffff;
        color: #00ffff;
        padding: 6px;
      }
    '';

    settings = [{
      layer = "top";
      position = "top";
      height = 34;
      spacing = 10;

      modules-left = [
        "hyprland/workspaces"
        "hyprland/window"
      ];

      modules-center = [
        "clock"
      ];

      modules-right = [
        "custom/files"
        "cpu"
        "memory"
        "network"
        "bluetooth"
        "pulseaudio"
        "tray"
      ];

      "hyprland/workspaces" = {
        format = "{name} {windows}";
        window-rewrite-default = "󱓡";
        on-click = "activate";
        window-rewrite = {
          "title<.*youtube.*>" = "󰗃";
          "class<firefox>" = "";
          "class<foot>" = "";
          "class<code-oss>" = "󰨞";
          "class<pcmanfm-qt>" = "󰉋";
          "class<discord>" = "󰙯";
          "class<spotify>" = "";
        };
      };

      "hyprland/window" = {
        format = "󰖲 {title}";
        max-length = 40;
        separate-outputs = true;
      };

      clock = {
        format = " {:%H:%M}";
        tooltip = false;
      };

      "custom/files" = {
        format = "󰉋 Files";
        tooltip = "File Manager";
        on-click = "foot --app-id floating_shell -e yazi";
      };

      cpu = {
        interval = 2;
        format = " {usage}%";
        tooltip = false;
      };

      memory = {
        interval = 2;
        format = " {used:0.1f}G";
        tooltip = false;
      };

      network = {
        format-wifi = " {essid}";
        format-ethernet = "󰈀 Wired";
        format-disconnected = "󰤮 Disconnected";
        tooltip = false;
      };

      bluetooth = {
        format = " {status}";
        tooltip = false;
      };

      pulseaudio = {
        format = "{icon} {volume}%";
        format-icons = {
          headphone = "";
          default = [ "" "" "" ];
        };
        tooltip = false;
      };

      tray = {
        icon-size = 18;
        spacing = 6;
      };
    }];
  };
}
