{
  pkgs,
  lib,
  jarvisEnvironment,
  projectLib,
  ...
}: let
  inherit (projectLib) colors;
  isHost = jarvisEnvironment == "host";
  hostOnlyModules =
    if isHost
    then ["battery" "bluetooth" "backlight"]
    else [];
  hostOnlySettings = lib.optionalAttrs isHost {
    battery = {
      format = "{icon} {capacity}%";
      format-icons = ["󰂎" "󰁺" "󰁌" "󰁞" "󰂀" "󰁹"];
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

  # ── Audiobook waybar + menu scripts ──────────────────────────────────────
  audiobookMenuScript = pkgs.writeShellScriptBin "jarvis-audiobook-menu" ''
    choice=$(echo -e "📚 Scan livros\n📖 Listar livros\n▶️  Tocar livro\n⏸  Pausar\n▶️  Continuar\n⏹  Parar\n📊 Status" | \
      wofi --dmenu --prompt "Audiobook:" --width 400 --height 350)
    case "$choice" in
      *"Scan"*) jarvis audiobook scan 2>&1 | wofi --dmenu --prompt "Resultado:" --width 600 || true ;;
      *"Listar"*) jarvis audiobook list 2>&1 | wofi --dmenu --prompt "Livros:" --width 600 || true ;;
      *"Tocar"*)
        books=$(jarvis audiobook list 2>/dev/null | grep -oP '^\d+\.\s+\K.*' || true)
        if [ -z "$books" ]; then
          notify-send "📚 Audiobook" "Nenhum livro encontrado. Execute Scan primeiro."
          exit 0
        fi
        book=$(echo "$books" | wofi --dmenu --prompt "Livro:" --width 600 --height 400)
        if [ -n "$book" ]; then
          notify-send "▶️ Audiobook" "Reproduzindo: $book"
          jarvis audiobook play "$book" 2>&1 | head -5 &
        fi
        ;;
      *"Pausar"*) jarvis audiobook pause 2>/dev/null; notify-send "⏸ Audiobook" "Pausado" ;;
      *"Continuar"*) jarvis audiobook resume 2>/dev/null; notify-send "▶️ Audiobook" "Continuando..." ;;
      *"Parar"*) jarvis audiobook stop 2>/dev/null; notify-send "⏹ Audiobook" "Reprodução parada" ;;
      *"Status"*) jarvis audiobook status 2>&1 | wofi --dmenu --prompt "Status:" --width 500 || true ;;
    esac
  '';

  audiobookWaybarScript = pkgs.writeShellScriptBin "jarvis-audiobook-waybar" ''
    status=$(jarvis audiobook status 2>/dev/null)
    if echo "$status" | grep -q "Tocando\|playing"; then
      book=$(echo "$status" | grep -oP 'Livro: \K.*' | head -1)
      chunk=$(echo "$status" | grep -oP 'Chunk: \K\d+' | head -1)
      total=$(echo "$status" | grep -oP '/ \K\d+' | head -1)
      printf '{"text":"󰏤","tooltip":"▶ %s — chunk %s/%s","class":"audiobook-playing"}' "$book" "$chunk" "$total"
    elif echo "$status" | grep -q "Pausado\|paused"; then
      book=$(echo "$status" | grep -oP 'Livro: \K.*' | head -1)
      printf '{"text":"󰏤","tooltip":"⏸ %s — pausado","class":"audiobook-paused"}' "$book"
    else
      printf '{"text":"","tooltip":"Audiobook: idle","class":"audiobook-idle"}'
    fi
  '';
in {
  fonts.fontconfig.enable = true;

  home.packages = with pkgs;
    [
      nerd-fonts.jetbrains-mono
      nerd-fonts.symbols-only
    ]
    ++ [
      cpuScript
      memoryScript
      gpuScript
      igpuScript
      audiobookMenuScript
      audiobookWaybarScript
    ];

  programs.waybar = {
    enable = true;
    style = ''
      * {
        border: none;
        border-radius: 0;
        font-family: ${projectLib.fonts.cssFamily};
        font-size: ${toString projectLib.fonts.mono.size}px;
        min-height: 0;
      }

      window#waybar {
        background: ${colors.waybar.bg};
        border-bottom: ${colors.waybar.border};
        color: ${colors.waybar.text};
        font-size: ${toString projectLib.fonts.mono.size}px;
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
      #custom-memory {
        padding: 0 16px;
        color: ${colors.waybar.text};
        font-size: ${toString projectLib.fonts.mono.size}px;
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

      /* ── Jarvis Waybar Module ─────────────────────────────────────────── */
      #custom-jarvis {
        background: rgba(0, 255, 255, 0.08);
        border-bottom: ${colors.waybar.border};
        color: #00ffff;
        padding: 0 6px;
        font-weight: bold;
      }
      #custom-jarvis.idle { color: #00ffff; opacity: 0.4; }
      #custom-jarvis.listening {
        color: #00ffff;
        animation: jarvis-glow 1s ease-in-out infinite;
        background: rgba(0, 255, 255, 0.15);
      }
      #custom-jarvis.initializing {
        color: #00ffff;
        animation: jarvis-spin 2s linear infinite;
      }
      #custom-jarvis.transcribing {
        color: #00ffff;
        animation: jarvis-pulse 0.6s ease-in-out infinite;
        background: rgba(0, 255, 255, 0.12);
      }
      #custom-jarvis.thinking {
        color: #FFB86C;
        animation: jarvis-pulse 1.2s ease-in-out infinite;
      }
      #custom-jarvis.speaking {
        color: #50FA7B;
        animation: jarvis-glow 1s ease-in-out infinite;
      }
      #custom-jarvis.error {
        color: #FF5555;
        animation: jarvis-blink 0.4s step-end infinite;
        background: rgba(255, 85, 85, 0.15);
      }
      #custom-jarvis.done {
        color: #50FA7B;
      }

      /* ── Audiobook Module ─────────────────────────────────────────────── */
      #custom-audiobook {
        background: rgba(0, 255, 255, 0.05);
        border-bottom: ${colors.waybar.border};
        color: #00ffff;
        padding: 0 4px;
        font-weight: bold;
      }
      #custom-audiobook.audiobook-playing {
        color: #00ffff;
        animation: jarvis-glow 2s ease-in-out infinite;
      }
      #custom-audiobook.audiobook-paused { color: #00ffff; opacity: 0.5; }
      #custom-audiobook.audiobook-idle { color: #00ffff; opacity: 0.2; }

      /* ── Hardware Modules ─────────────────────────────────────────────── */
      #custom-cpu, #custom-memory, #custom-gpu, #custom-igpu {
        padding: 0 4px;
        font-weight: bold;
      }
      #custom-cpu.high, #custom-memory.high, #custom-gpu.high {
        color: #FF5555;
      }
      #custom-cpu.medium, #custom-memory.medium, #custom-gpu.medium {
        color: #FFB86C;
      }
      #custom-cpu.low, #custom-memory.low, #custom-gpu.low {
        color: #50FA7B;
      }

      /* ── Animations (waybar CSS: opacity only, single selectors) ──────── */
      @keyframes jarvis-pulse {
        0% { opacity: 1; }
        50% { opacity: 0.3; }
        100% { opacity: 1; }
      }
      @keyframes jarvis-glow {
        0% { opacity: 1; }
        50% { opacity: 0.5; }
        100% { opacity: 1; }
      }
      @keyframes jarvis-blink {
        0% { opacity: 1; }
        50% { opacity: 0.15; }
        100% { opacity: 1; }
      }
      @keyframes jarvis-spin {
        0% { opacity: 1; }
        25% { opacity: 0.5; }
        50% { opacity: 0.2; }
        75% { opacity: 0.5; }
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

    settings = [
      ({
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

          modules-right =
            [
              "custom/jarvis"
              "custom/audiobook"
              "custom/files"
              "custom/cpu"
              "custom/memory"
              "custom/gpu"
              "custom/igpu"
            ]
            ++ hostOnlyModules
            ++ [
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

          "custom/audiobook" = {
            exec = "${audiobookWaybarScript}/bin/jarvis-audiobook-waybar";
            exec-on-event = true;
            interval = 5;
            return-type = "json";
            format = "{}";
            on-click = "${audiobookMenuScript}/bin/jarvis-audiobook-menu";
            tooltip = true;
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
            format = "󰍛 CPU {}";
            exec = "${cpuScript}/bin/waybar-cpu";
            interval = 3;
            return-type = "json";
            tooltip = true;
            on-click = "foot --app-id floating_shell -e btm";
          };

          "custom/memory" = {
            format = "󰘚 RAM {}";
            exec = "${memoryScript}/bin/waybar-memory";
            interval = 5;
            return-type = "json";
            tooltip = true;
            on-click = "foot --app-id floating_shell -e btm";
          };

          "custom/gpu" = {
            format = "󰢝 GPU {}";
            exec = "${gpuScript}/bin/waybar-gpu";
            interval = 3;
            return-type = "json";
            tooltip = true;
            on-click = "foot --app-id floating_shell -e nvidia-smi";
          };

          "custom/igpu" = {
            format = "󰢮 iGPU {}";
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
              default = ["󰕿" "󰖀" "󰕾"];
            };
            tooltip = false;
            on-click = "foot --app-id floating_shell -e ncpamixer";
          };

          tray = {
            icon-size = 18;
            spacing = 6;
          };
        }
        // hostOnlySettings)
    ];
  };
}
