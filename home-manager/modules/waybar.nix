{ pkgs, lib, jarvisEnvironment, ... }:
# Waybar — perfil por ambiente (água: segue services.jarvis.environment
# passado via extraSpecialArgs: jarvisEnvironment).
#   VM  (lab): sem battery/bluetooth/backlight (não existem na VM — davam
#       popups de erro); clock/cpu/memory/network/workspaces/custom-jarvis.
#   host (bare metal): full — battery, bluetooth, backlight, tudo.
let
  isHost = jarvisEnvironment == "host";
  # módulos só de hardware real (determinístico, não lib.mkIf)
  hostOnlyModules = if isHost then [ "battery" "bluetooth" "backlight" ] else [];
  # definições dos módulos só de hardware (merge determinístico)
  hostOnlySettings = lib.optionalAttrs isHost {
    battery = {
      format = "{icon} {capacity}%";
      format-icons = [ "" "" "" "" "" ];
      tooltip = false;
    };
    backlight = {
      format = "󰃠 {percent}%";
      tooltip = false;
    };
    bluetooth = {
      format = " {status}";
      tooltip = false;
    };
  };
in
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
         JARVIS STATES (porta do legado)
         ------------------------------ */
      #custom-jarvis {
        background: rgba(0, 255, 255, 0.12);
        border-bottom: 2px solid #00ffff;
      }

      #custom-jarvis.idle {
        color: #aaaaaa;
      }

      #custom-jarvis.listening,
      #custom-jarvis.initializing {
        color: #00ffff;
        animation: jarvis-pulse 1s infinite;
      }

      #custom-jarvis.transcribing {
        color: #ffaa00;
      }

      #custom-jarvis.thinking {
        color: #bb77ff;
        animation: jarvis-pulse 1.2s infinite;
      }

      #custom-jarvis.speaking {
        color: #00ff88;
      }

      #custom-jarvis.error {
        color: #ff0000;
        animation: jarvis-blink 0.4s infinite;
      }

      #custom-jarvis.done {
        color: #00ff88;
      }

      @keyframes jarvis-pulse {
        0% { opacity: 1; }
        50% { opacity: 0.4; }
        100% { opacity: 1; }
      }

      @keyframes jarvis-blink {
        0% { opacity: 1; }
        50% { opacity: 0.2; }
        100% { opacity: 1; }
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

    settings = [({
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
        "custom/jarvis"
        "custom/files"
        "cpu"
        "memory"
      ] ++ hostOnlyModules ++ [
        "network"
        "pulseaudio"
        "tray"
      ];

      # JARVIS — estado da IA (porta do legado waybar-jarvis-status.sh)
      "custom/jarvis" = {
        exec = "${pkgs.jarvis}/bin/jarvis-waybar 2>/dev/null || echo '{\"text\": \"IDLE 🤖\", \"class\": \"idle\"}'";
        exec-on-event = true;
        interval = 2;
        return-type = "json";
        on-click = "foot --app-id floating_shell -e jarvis dev";
      };

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
    } // hostOnlySettings)];
  };
}
