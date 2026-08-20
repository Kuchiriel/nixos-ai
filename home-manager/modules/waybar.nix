{ pkgs, lib, jarvisEnvironment, ... }:
# Waybar — perfil por ambiente (água: segue services.jarvis.environment
# passado via extraSpecialArgs: jarvisEnvironment).
#   VM  (lab): sem battery/bluetooth/backlight (não existem na VM — davam
#       popups de error); clock/cpu/memory/network/workspaces/custom-jarvis.
#   host (bare metal): full — battery, bluetooth, backlight, GPU, tudo.
#
# Porta do legado Manjaro (waybar-gpu.sh, waybar-jarvis-status.sh):
#   - custom/gpu: nvidia-smi com states low/medium/high + VRAM/tooltip
#   - custom/jarvis: estado da IA (idle/listening/thinking/speaking/error)
#   - on-click em cada módulo abre TUI tool em foot (btm, yazi, nmtui, etc)
let
  isHost = jarvisEnvironment == "host";
  # módulos só de hardware real (determinístico, não lib.mkIf)
  hostOnlyModules = if isHost then [ "battery" "bluetooth" "backlight" ] else [];
  # definições dos módulos só de hardware (merge determinístico)
  hostOnlySettings = lib.optionalAttrs isHost {
    battery = {
      format = "{icon} {capacity}%";
      format-icons = [ "" "" "" "" "" ];
      tooltip = false;
    };
    backlight = {
      format = "󰃠 {percent}%";
      tooltip = false;
    };
    bluetooth = {
      format = " {status}";
      tooltip = false;
      on-click = "foot --app-id floating_shell -e bluetuith";
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
         GPU USAGE STATES (porta do legado)
         ------------------------------ */
      #custom-gpu.low {
        color: #50FA7B;
      }

      #custom-gpu.medium {
        color: #FFB86C;
      }

      #custom-gpu.high {
        color: #FF5555;
        text-shadow: 0 0 6px #FF5555;
      }

      #custom-gpu.disabled {
        color: #666666;
      }

      /* ------------------------------
         BATTERY STATES
         ------------------------------ */
      #battery.warning {
        color: #ffaa00;
      }

      #battery.critical {
        color: #ff5555;
        text-shadow: 0 0 6px #ff5555;
      }

      #battery.charging {
        color: #50FA7B;
      }

      /* ------------------------------
         JARVIS AI STATUS STATES (porta do legado)
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
        "custom/gpu"
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
          "class<firefox>" = "";
          "class<foot>" = "";
          "class<code-oss>" = "󰨞";
          "class<pcmanfm-qt>" = "󰉋";
          "class<discord>" = "󰙯";
          "class<spotify>" = "";
        };
      };

      "hyprland/window" = {
        format = "󰖲 {title}";
        max-length = 40;
        separate-outputs = true;
      };

      clock = {
        format = " {:%H:%M}";
        tooltip = false;
        on-click = "foot --app-id floating_shell -e calcurse";
      };

      "custom/files" = {
        format = "󰉋 Files";
        tooltip = "File Manager (yazi)";
        on-click = "foot --app-id floating_shell -e yazi";
      };

      cpu = {
        interval = 2;
        format = " {usage}%";
        tooltip = false;
        on-click = "foot --app-id floating_shell -e btm";
      };

      memory = {
        interval = 2;
        format = " {used:0.1f}G";
        tooltip = false;
        on-click = "foot --app-id floating_shell -e btm";
      };

      # GPU monitor via nvidia-smi (porta do legado waybar-gpu.sh)
      # Mostra uso%, VRAM, temperatura com states low/medium/high
      "custom/gpu" = {
        exec = ''
          bash -c '
          if ! command -v nvidia-smi &>/dev/null; then
              echo "{\"text\": \"GPU N/A\", \"tooltip\": \"nvidia-smi not found\", \"class\": \"disabled\"}"
              exit 0
          fi
          GPU_UTIL=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
          GPU_TEMP=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
          GPU_MEM=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
          GPU_MEM_TOTAL=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
          GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
          if [ -z "$GPU_UTIL" ]; then
              echo "{\"text\": \"GPU N/A\", \"tooltip\": \"GPU not detected\", \"class\": \"disabled\"}"
              exit 0
          fi
          GPU_MEM_GB=$(awk "BEGIN {printf \"%.1f\", $GPU_MEM / 1024}")
          GPU_MEM_TOTAL_GB=$(awk "BEGIN {printf \"%.1f\", $GPU_MEM_TOTAL / 1024}")
          if [ "$GPU_UTIL" -ge 80 ]; then CLASS="high"
          elif [ "$GPU_UTIL" -ge 50 ]; then CLASS="medium"
          else CLASS="low"
          fi
          echo "{\"text\": \"GPU ''${GPU_UTIL}%\", \"tooltip\": \"''${GPU_NAME}\nUsage: ''${GPU_UTIL}%\nTemp: ''${GPU_TEMP}C\nVRAM: ''${GPU_MEM_GB}GB / ''${GPU_MEM_TOTAL_GB}GB\", \"class\": \"$CLASS\"}"
          '
        '';
        interval = 3;
        return-type = "json";
        tooltip = true;
        on-click = "foot --app-id floating_shell -e nvidia-smi";
      };

      network = {
        format-wifi = " {essid}";
        format-ethernet = "󰈀 Wired";
        format-disconnected = "󰤮 Disconnected";
        tooltip = false;
        on-click = "foot --app-id floating_shell -e nmtui-connect";
      };

      pulseaudio = {
        format = "{icon} {volume}%";
        format-icons = {
          headphone = "";
          default = [ "" "" "" ];
        };
        tooltip = false;
        on-click = "foot --app-id floating_shell -e ncpamixer";
      };

      tray = {
        icon-size = 18;
        spacing = 6;
      };
    } // hostOnlySettings)];
  };
}
