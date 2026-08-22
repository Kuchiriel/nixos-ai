{ pkgs, lib, jarvisEnvironment, m3taLib, ... }:
let
  colors = m3taLib.colors;
  isHost = jarvisEnvironment == "host";
  hostOnlyModules = if isHost then [ "battery" "bluetooth" "backlight" ] else [];
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

  # Scripts bash — output APENAS valores ASCII puro.
  # Ícones Nerd Font ficam no campo `format` do módulo waybar.
  # NOTA: em strings Nix '', \n é literal (backslash+n), NÃO interpola.
  # No printf, \n gera nova linha — para JSON válido precisamos de \\n
  # que o printf imprime como literal \n.
  cpuScript = pkgs.writeShellScriptBin "waybar-cpu" ''
    get_cpu() {
      awk '/^cpu / {print ($2+$3+$4+$5+$6+$7+$8), $5}' /proc/stat
    }
    
    read -r total1 idle1 < <(get_cpu)
    sleep 0.5
    read -r total2 idle2 < <(get_cpu)
    
    total_diff=$((total2 - total1))
    idle_diff=$((idle2 - idle1))
    
    if [ "$total_diff" -gt 0 ]; then
      CPU=$(( (100 * (total_diff - idle_diff)) / total_diff ))
    else
      CPU=0
    fi

    if [ "$CPU" -ge 80 ]; then CLASS="high"
    elif [ "$CPU" -ge 50 ]; then CLASS="medium"
    else CLASS="low"
    fi
    
    read LOAD _rest _ < /proc/loadavg
    printf '{"text": "%s%%", "tooltip": "Load: %s\\nUsage: %s%%", "class": "%s"}\n' "$CPU" "$LOAD" "$CPU" "$CLASS"
  '';  

  memoryScript = pkgs.writeShellScriptBin "waybar-memory" ''
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
    printf '{"text": "%sG", "tooltip": "RAM: %sG / %sG (%s%%)\\nSwap: %sG", "class": "%s"}\n' "$MEM_USED_GB" "$MEM_USED_GB" "$MEM_TOTAL_GB" "$MEM_PCT" "$SWAP_GB" "$CLASS"
  '';

  gpuScript = pkgs.writeShellScriptBin "waybar-gpu" ''
    if ! command -v nvidia-smi &>/dev/null; then
        printf '{"text": "N/A", "tooltip": "nvidia-smi not found", "class": "disabled"}\n'
        exit 0
    fi
    GPU_UTIL=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
    GPU_TEMP=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
    GPU_MEM=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
    GPU_MEM_TOTAL=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    if [ -z "$GPU_UTIL" ]; then
        printf '{"text": "N/A", "tooltip": "GPU not detected", "class": "disabled"}\n'
        exit 0
    fi
    GPU_MEM_GB=$(awk "BEGIN {printf \"%.1f\", $GPU_MEM / 1024}")
    GPU_MEM_TOTAL_GB=$(awk "BEGIN {printf \"%.1f\", $GPU_MEM_TOTAL / 1024}")
    if [ "$GPU_UTIL" -ge 80 ]; then CLASS="high"
    elif [ "$GPU_UTIL" -ge 50 ]; then CLASS="medium"
    else CLASS="low"
    fi
    printf '{"text": "%s%%", "tooltip": "%s\\nUsage: %s%%\\nTemp: %sC\\nVRAM: %sGB / %sGB", "class": "%s"}\n' "$GPU_UTIL" "$GPU_NAME" "$GPU_UTIL" "$GPU_TEMP" "$GPU_MEM_GB" "$GPU_MEM_TOTAL_GB" "$CLASS"
  '';

  igpuScript = pkgs.writeShellScriptBin "waybar-igpu" ''
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
    printf '{"text": "%sMHz", "tooltip": "Intel UHD 770\\nFreq: %s/%s MHz (%s%%)\\nPower: %s", "class": "%s"}\n' "$CUR" "$CUR" "$MAX" "$PCT" "$STATUS" "$CLASS"
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
      * {
        border: none;
        border-radius: 0;
        font-family: ${m3taLib.fonts.cssFamily};
        font-size: ${toString m3taLib.fonts.mono.size}px;
        min-height: 0;
      }

      window#waybar {
        background: ${colors.waybar.bg};
        border-bottom: ${colors.waybar.border};
        color: ${colors.waybar.text};
        font-size: ${toString m3taLib.fonts.mono.size}px;
        min-height: 34px;
        margin: 4px 8px 0 8px;
        border-radius: 10px;
      }

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
      #custom-gpu,
      #custom-igpu,
      #custom-cpu,
      #custom-memory,
      #custom-jarvis {
        padding: 0 16px;
        color: ${colors.waybar.text};
        font-size: ${toString m3taLib.fonts.mono.size}px;
        transition: all 0.25s ease;
      }

      #workspaces button {
        background: transparent;
        color: ${colors.waybar.text};
      }

      #workspaces button.active,
      #workspaces button.focused {
        background: rgba(0, 255, 255, 0.18);
        border-bottom: ${colors.waybar.border};
      }

      #clock:hover,
      #cpu:hover,
      #memory:hover,
      #battery:hover,
      #network:hover,
      #pulseaudio:hover,
      #bluetooth:hover,
      #backlight:hover,
      #custom-files:hover,
      #custom-gpu:hover,
      #custom-igpu:hover,
      #custom-cpu:hover,
      #custom-memory:hover,
      #custom-jarvis:hover {
        text-shadow: 0 0 4px ${colors.waybar.text}, 0 0 8px ${colors.waybar.text};
      }

      #custom-gpu.low { color: ${colors.status.success}; }
      #custom-gpu.medium { color: ${colors.status.warning}; }
      #custom-gpu.high { color: ${colors.status.error}; text-shadow: 0 0 6px ${colors.status.error}; }
      #custom-gpu.disabled { color: #666666; }

      #custom-igpu.low { color: ${colors.status.success}; }
      #custom-igpu.medium { color: ${colors.status.warning}; }
      #custom-igpu.high { color: ${colors.status.error}; text-shadow: 0 0 6px ${colors.status.error}; }

      #custom-cpu.low { color: ${colors.status.success}; }
      #custom-cpu.medium { color: ${colors.status.warning}; }
      #custom-cpu.high { color: ${colors.status.error}; text-shadow: 0 0 6px ${colors.status.error}; }

      #custom-memory.low { color: ${colors.status.success}; }
      #custom-memory.medium { color: ${colors.status.warning}; }
      #custom-memory.high { color: ${colors.status.error}; text-shadow: 0 0 6px ${colors.status.error}; }

      #battery.warning { color: ${colors.status.warning}; }
      #battery.critical { color: ${colors.status.error}; text-shadow: 0 0 6px ${colors.status.error}; }
      #battery.charging { color: ${colors.status.success}; }

      #custom-jarvis {
        background: rgba(0, 255, 255, 0.12);
        border-bottom: ${colors.waybar.border};
        color: #00ffff;
      }
      #custom-jarvis.idle { color: #00ffff; opacity: 0.5; }
      #custom-jarvis.listening,
      #custom-jarvis.initializing { color: #00ffff; animation: jarvis-pulse 1s infinite; }
      #custom-jarvis.transcribing { color: #00ffff; animation: jarvis-pulse 0.8s infinite; }
      #custom-jarvis.thinking { color: #00ffff; animation: jarvis-pulse 1.2s infinite; }
      #custom-jarvis.speaking { color: #00ffff; }
      #custom-jarvis.error { color: ${colors.status.error}; animation: jarvis-blink 0.4s infinite; }
      #custom-jarvis.done { color: ${colors.status.success}; }

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

      #tray { padding-right: 8px; }
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

      "custom/jarvis" = {
        exec = "${pkgs.jarvis}/bin/jarvis-waybar 2>/dev/null || echo '{\\\"text\\\": \\\"IDLE\\\", \\\"class\\\": \\\"idle\\\"}'";
        exec-on-event = true;
        interval = 2;
        return-type = "json";
        format = "{}";
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
        format = "󰍛 {}";
        exec = "${cpuScript}/bin/waybar-cpu";
        interval = 3;
        return-type = "json";
        tooltip = true;
        on-click = "foot --app-id floating_shell -e btm";
      };

      "custom/memory" = {
        format = "󰘚 {}";
        exec = "${memoryScript}/bin/waybar-memory";
        interval = 5;
        return-type = "json";
        tooltip = true;
        on-click = "foot --app-id floating_shell -e btm";
      };

      "custom/gpu" = {
        format = "󰢮 {}";
        exec = "${gpuScript}/bin/waybar-gpu";
        interval = 3;
        return-type = "json";
        tooltip = true;
        on-click = "foot --app-id floating_shell -e nvidia-smi";
      };

      "custom/igpu" = {
        format = "󰢮 {}";
        exec = "${igpuScript}/bin/waybar-igpu";
        interval = 5;
        return-type = "json";
        tooltip = true;
        on-click = "foot --app-id floating_shell -e sudo intel_gpu_top";
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
