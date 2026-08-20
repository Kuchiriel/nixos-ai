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
      format-icons = [ "󰂎" "󰁺" "󰁌" "󰁞" "󰂀" "󰁹" ];
      format-charging = " {capacity}%";
      tooltip = false;
    };
    backlight = {
      format = "󰃠 {percent}%";
      tooltip = false;
    };
    bluetooth = {
      format = "󰂯 {status}";
      tooltip = false;
      on-click = "foot --app-id floating_shell -e bluetuith";
    };
  };

  # Scripts bash para módulos custom — isolados via writeScriptBin para
  # evitar problemas de escaping Nix '' ↔ aspas bash.
  cpuScript = pkgs.writeScriptBin "waybar-cpu" ''
    read -r user nice system idle rest < /proc/stat
    total=$((user+nice+system+idle))
    CPU=$(( (user+nice+system)*100/total ))
    if [ "$CPU" -ge 80 ]; then CLASS="high"
    elif [ "$CPU" -ge 50 ]; then CLASS="medium"
    else CLASS="low"
    fi
    read LOAD _rest _ < /proc/loadavg
    echo "{\"text\": \"󰍛 ${CPU}%\", \"tooltip\": \"Load: ${LOAD}\nUsage: ${CPU}%\", \"class\": \"$CLASS\"}"
  '';

  memoryScript = pkgs.writeScriptBin "waybar-memory" ''
    while read -r key val rest; do
      case "$key" in
        MemTotal:)  MEM_TOTAL=$val ;;
        MemAvailable:) MEM_AVAIL=$val ;;
        SwapTotal:) SWAP_TOTAL=$val ;;
        SwapFree:)  SWAP_FREE=$val ;;
      esac
    done < /proc/meminfo
    MEM_USED=$((MEM_TOTAL - MEM_AVAIL))
    MEM_PCT=$((MEM_USED * 100 / MEM_TOTAL))
    MEM_USED_GB=$(awk "BEGIN {printf \"%.1f\", $MEM_USED / 1048576}")
    MEM_TOTAL_GB=$(awk "BEGIN {printf \"%.1f\", $MEM_TOTAL / 1048576}")
    SWAP_USED=$((SWAP_TOTAL - SWAP_FREE))
    SWAP_GB=$(awk "BEGIN {printf \"%.1f\", $SWAP_USED / 1048576}")
    if [ "$MEM_PCT" -ge 85 ]; then CLASS="high"
    elif [ "$MEM_PCT" -ge 60 ]; then CLASS="medium"
    else CLASS="low"
    fi
    echo "{\"text\": \"󰘚 ${MEM_USED_GB}G\", \"tooltip\": \"RAM: ${MEM_USED_GB}G / ${MEM_TOTAL_GB}G (${MEM_PCT}%)\nSwap: ${SWAP_GB}G\", \"class\": \"$CLASS\"}"
  '';

  gpuScript = pkgs.writeScriptBin "waybar-gpu" ''
    if ! command -v nvidia-smi &>/dev/null; then
        echo "{\"text\": \"󰢮 GPU N/A\", \"tooltip\": \"nvidia-smi not found\", \"class\": \"disabled\"}"
        exit 0
    fi
    GPU_UTIL=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
    GPU_TEMP=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
    GPU_MEM=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
    GPU_MEM_TOTAL=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    if [ -z "$GPU_UTIL" ]; then
        echo "{\"text\": \"󰢮 GPU N/A\", \"tooltip\": \"GPU not detected\", \"class\": \"disabled\"}"
        exit 0
    fi
    GPU_MEM_GB=$(awk "BEGIN {printf \"%.1f\", $GPU_MEM / 1024}")
    GPU_MEM_TOTAL_GB=$(awk "BEGIN {printf \"%.1f\", $GPU_MEM_TOTAL / 1024}")
    if [ "$GPU_UTIL" -ge 80 ]; then CLASS="high"
    elif [ "$GPU_UTIL" -ge 50 ]; then CLASS="medium"
    else CLASS="low"
    fi
    echo "{\"text\": \"󰢮 ${GPU_UTIL}%\", \"tooltip\": \"${GPU_NAME}\nUsage: ${GPU_UTIL}%\nTemp: ${GPU_TEMP}C\nVRAM: ${GPU_MEM_GB}GB / ${GPU_MEM_TOTAL_GB}GB\", \"class\": \"$CLASS\"}"
  '';

  igpuScript = pkgs.writeScriptBin "waybar-igpu" ''
    CUR=$(cat /sys/class/drm/card1/gt_cur_freq_mhz 2>/dev/null || echo 0)
    MAX=$(cat /sys/class/drm/card1/gt_max_freq_mhz 2>/dev/null || echo 1500)
    STATUS=$(cat /sys/class/drm/card1/device/power/runtime_status 2>/dev/null || echo "unknown")
    if [ "$MAX" -gt 0 ] 2>/dev/null; then
        PCT=$((CUR * 100 / MAX))
    else
        PCT=0
    fi
    if [ "$PCT" -ge 80 ]; then CLASS="high"
    elif [ "$PCT" -ge 40 ]; then CLASS="medium"
    else CLASS="low"
    fi
    FREQ="${CUR}MHz"
    echo "{\"text\": \"󰢮 ${FREQ}\", \"tooltip\": \"Intel UHD 770\nFreq: ${CUR}/${MAX} MHz (${PCT}%)\nPower: ${STATUS}\", \"class\": \"$CLASS\"}"
  '';
in
{
  fonts.fontconfig.enable = true;

  home.packages = with pkgs; [
    nerd-fonts.jetbrains-mono
    nerd-fonts.symbols-only
  ] ++ [
    cpuScript
    memoryScript
    gpuScript
    igpuScript
  ];

  programs.waybar = {
    enable = true;
    style = ''
      /* =========================================
         JARVIS AI_SYSTEM — WAYBAR STYLE
         ========================================= */

      * {
        border: none;
        border-radius: 0;
        font-family: "JetBrainsMono Nerd Font", "Symbols Nerd Font", sans-serif;
        font-size: 14px;
        min-height: 0;
      }

      /* ------------------------------
         BAR CONTAINER
         ------------------------------ */
      window#waybar {
        background: #0a0a0a;
        border-bottom: 2px solid #00ffff;
        color: #00ffff;
        font-size: 14px;
        min-height: 34px;
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
      #custom-igpu,
      #custom-cpu,
      #custom-memory,
      #custom-jarvis {
        padding: 0 16px;
        color: #00ffff;
        font-size: 14px;
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
      #custom-igpu:hover,
      #custom-cpu:hover,
      #custom-memory:hover,
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

      #custom-igpu.low {
        color: #50FA7B;
      }

      #custom-igpu.medium {
        color: #FFB86C;
      }

      #custom-igpu.high {
        color: #FF5555;
        text-shadow: 0 0 6px #FF5555;
      }

      #custom-gpu.disabled {
        color: #666666;
      }

      /* ------------------------------
         CPU USAGE STATES
         ------------------------------ */
      #custom-cpu.low {
        color: #50FA7B;
      }

      #custom-cpu.medium {
        color: #FFB86C;
      }

      #custom-cpu.high {
        color: #FF5555;
        text-shadow: 0 0 6px #FF5555;
      }

      /* ------------------------------
         MEMORY USAGE STATES
         ------------------------------ */
      #custom-memory.low {
        color: #50FA7B;
      }

      #custom-memory.medium {
        color: #FFB86C;
      }

      #custom-memory.high {
        color: #FF5555;
        text-shadow: 0 0 6px #FF5555;
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
        "custom/cpu"
        "custom/memory"
        "custom/gpu"
        "custom/igpu"
      ] ++ hostOnlyModules ++ [
        "network"
        "pulseaudio"
        "tray"
      ];

      # JARVIS — estado da IA (porta do legado waybar-jarvis-status.sh)
      "custom/jarvis" = {
        exec = "${pkgs.jarvis}/bin/jarvis-waybar 2>/dev/null || echo '{\\\"text\\\": \\\"IDLE 🤖\\\", \\\"class\\\": \\\"idle\\\"}'";
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

      "custom/cpu" = {
        exec = "${cpuScript}/bin/waybar-cpu";
        interval = 3;
        return-type = "json";
        tooltip = true;
        on-click = "foot --app-id floating_shell -e btm";
      };

      "custom/memory" = {
        exec = "${memoryScript}/bin/waybar-memory";
        interval = 5;
        return-type = "json";
        tooltip = true;
        on-click = "foot --app-id floating_shell -e btm";
      };

      "custom/gpu" = {
        exec = "${gpuScript}/bin/waybar-gpu";
        interval = 3;
        return-type = "json";
        tooltip = true;
        on-click = "foot --app-id floating_shell -e nvidia-smi";
      };

      "custom/igpu" = {
        exec = "${igpuScript}/bin/waybar-igpu";
        interval = 5;
        return-type = "json";
        tooltip = true;
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
          headphone = "󰋋";
          default = [ "󰕿" "󰖀" "󰕾" ];
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
