#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# NixOS-AI Launcher — GUI para todas as features do sistema
# Usa Yad (Yet Another Dialog) para interfaces GTK
#
# Uso:
#   nixos-ai-launcher          # Menu principal
#   nixos-ai-launcher --status # Status rápido
#   nixos-ai-launcher --dev    # Abre jarvis dev
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────
YAD="${YAD:-yad}"
JARVIS_DIR="${JARVIS_DIR:-$HOME/projects/nixos-ai/modules/ai/jarvis}"
ICON_DIR="/run/current-system/sw/share/icons"
THEME="Adwaita:dark"

# Cores para notify-send
COLOR_CYAN="#00ffff"
COLOR_GREEN="#50FA7B"
COLOR_RED="#FF5555"
COLOR_YELLOW="#FFB86C"
COLOR_PURPLE="#bb77ff"

# ── Helpers ───────────────────────────────────────────────────────────────

notify() {
    local title="$1" msg="$2" icon="${3:-dialog-information}"
    notify-send -t 3000 -i "$icon" "$title" "$msg" 2>/dev/null || true
}

run_in_terminal() {
    local title="$1" cmd="$2"
    foot --app-id floating_shell -e bash -c "$cmd; echo '--- Pressione Enter para fechar ---'; read" &
}

check_service() {
    local svc="$1"
    systemctl is-active "$svc" 2>/dev/null || echo "inactive"
}

gpu_info() {
    nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader 2>/dev/null || echo "N/A,N/A,N/A,N/A,N/A,N/A"
}

igpu_info() {
    local temp=$(cat /sys/class/drm/card0/device/hwmon/hwmon*/temp1_input 2>/dev/null | awk '{print int($1/1000)}' || echo "N/A")
    echo "Intel UHD 770,${temp}°C"
}

cpu_info() {
    local usage=$(top -bn1 | grep "Cpu(s)" | awk '{print int($2+$4)}')
    local temp=$(cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | head -1 | awk '{print int($1/1000)}' || echo "N/A")
    echo "${usage}%,${temp}°C"
}

ram_info() {
    free -h | awk '/^Mem:/ {printf "%s/%s (%.0f%%)", $3, $2, $3/$2*100}'
}

# ── Módulo: System Status ─────────────────────────────────────────────────

show_status() {
    local gpu=$(gpu_info)
    local igpu=$(igpu_info)
    local cpu=$(cpu_info)
    local ram=$(ram_info)
    local llama=$(check_service llama-cpp-server)
    local qdrant=$(check_service qdrant)
    local ww=$(check_service jarvis-wakeword)

    local text="
<b>═══ SYSTEM STATUS ═══</b>

<b>🖥️ Hardware</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  GPU (RTX 4050):     ${gpu}
  iGPU (Intel UHD):   ${igpu}
  CPU:                ${cpu}
  RAM:                ${ram}

<b>⚙️ Services</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  llama-cpp-server:   ${llama}
  qdrant:             ${qdrant}
  jarvis-wakeword:    ${ww}
"

    $YAD --title="System Status" \
        --width=500 --height=450 \
        --text="$text" \
        --text-align=left \
        --button="🔄 Refresh:1" \
        --button="Close:0" \
        --theme="$THEME" 2>/dev/null

    case $? in
        1) show_status ;;
    esac
}

# ── Módulo: Services ──────────────────────────────────────────────────────

show_services() {
    local llama=$(check_service llama-cpp-server)
    local qdrant=$(check_service qdrant)
    local ww=$(check_service jarvis-wakeword)
    local embed=$(check_service llama-cpp-embeddings)
    local rerank=$(check_service llama-cpp-rerank)

    local text="
<b>═══ SERVICE MANAGEMENT ═══</b>

<b>AI Services</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  llama-cpp (chat):       ${llama}
  llama-cpp (embeddings): ${embed}
  llama-cpp (rerank):     ${rerank}
  qdrant:                 ${qdrant}
  jarvis-wakeword:        ${ww}
"

    $YAD --title="Services" \
        --width=500 --height=400 \
        --text="$text" \
        --text-align=left \
        --button="Restart llama-cpp:1" \
        --button="Restart all AI:2" \
        --button="View logs:3" \
        --button="Close:0" \
        --theme="$THEME" 2>/dev/null

    case $? in
        1) sudo systemctl restart llama-cpp-server && notify "Services" "llama-cpp restarted" ;;
        2) sudo systemctl restart llama-cpp-server llama-cpp-embeddings llama-cpp-rerank qdrant && notify "Services" "All AI services restarted" ;;
        3) run_in_terminal "llama.cpp logs" "journalctl -u llama-cpp-server -f --no-pager" ;;
    esac
}

# ── Módulo: Jarvis ────────────────────────────────────────────────────────

show_jarvis() {
    local text="
<b>═══ JARVIS AI ═══</b>

<b>Features</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  🎤 Voice Pipeline:  STT → LLM → TTS
  💻 Dev CLI:         Code editing agent
  🧠 RAG:             Semantic code search
  🔍 Health:          System diagnostics

<b>Quick Actions</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"

    $YAD --title="Jarvis" \
        --width=450 --height=350 \
        --text="$text" \
        --text-align=left \
        --button="💻 Dev CLI:1" \
        --button="🔍 Health Check:2" \
        --button="🧠 RAG Index:3" \
        --button="🎤 Test STT:4" \
        --button="🔊 Test TTS:5" \
        --button="Close:0" \
        --theme="$THEME" 2>/dev/null

    case $? in
        1) foot --app-id jarvis-dev -e bash -c "cd ~/projects/nixos-ai && jarvis dev; exec bash" ;;
        2) run_in_terminal "jarvis doctor" "jarvis doctor 2>&1" ;;
        3) run_in_terminal "RAG index" "cd ~/projects/nixos-ai && jarvis rag index 2>&1" ;;
        4) run_in_terminal "STT test" "jarvis stt /tmp/test-stt.wav 2>&1 || echo 'Record with: pw-record /tmp/test-stt.wav'" ;;
        5) show_tts_test ;;
    esac
}

show_tts_test() {
    local text="Digite o texto para synthesizer com Kokoro TTS:"

    local result=$($YAD --title="TTS Test" \
        --width=400 --height=150 \
        --entry \
        --text="$text" \
        --button="Speak:1" \
        --button="Cancel:0" \
        --theme="$THEME" 2>/dev/null)

    if [ $? -eq 1 ] && [ -n "$result" ]; then
        run_in_terminal "TTS" "jarvis speak '$result' 2>&1"
    fi
}

# ── Módulo: Dev Tools ─────────────────────────────────────────────────────

show_devtools() {
    local text="
<b>═══ DEV TOOLS ═══</b>

<b>Build & Test</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Benchmark:    Performance test (prefill/decode t/s)
  Rebuild:      nixos-rebuild switch
  Tests:        Run jarvis pytest suite

<b>Code Quality</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Lint:         Ruff linter
  Format:       Code formatting
"

    $YAD --title="Dev Tools" \
        --width=450 --height=350 \
        --text="$text" \
        --text-align=left \
        --button="📊 Benchmark:1" \
        --button="🔨 Rebuild:2" \
        --button="🧪 Run Tests:3" \
        --button="🔍 Lint:4" \
        --button="Close:0" \
        --theme="$THEME" 2>/dev/null

    case $? in
        1) run_in_terminal "Benchmark" "cd ~/projects/nixos-ai && bash benchmark.sh --warmup --repeat 3 2>&1" ;;
        2) run_in_terminal "Rebuild" "cd ~/projects/nixos-ai && bash rebuild-host.sh 2>&1" ;;
        3) run_in_terminal "Tests" "cd ~/projects/nixos-ai && nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q 2>&1" ;;
        4) run_in_terminal "Linter" "cd ~/projects/nixos-ai && nix develop --command ruff check modules/ai/jarvis/src/ 2>&1" ;;
    esac
}

# ── Módulo: Hardware ──────────────────────────────────────────────────────

show_hardware() {
    local gpu=$(nvidia-smi --query-gpu=name,driver_version,vbios_version --format=csv,noheader 2>/dev/null || echo "N/A")
    local cpu_model=$(lscpu | grep "Model name" | sed 's/.*: *//' | head -1)
    local ram_total=$(free -h | awk '/^Mem:/ {print $2}')
    local disk=$(df -h / | awk 'NR==2 {printf "%s/%s (%s)", $3, $2, $5}')
    local kernel=$(uname -r)

    local text="
<b>═══ HARDWARE INFO ═══</b>

<b>🖥️ Components</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CPU:        ${cpu_model}
  GPU:        ${gpu}
  RAM:        ${ram_total}
  Disk:       ${disk}
  Kernel:     ${kernel}

<b>🔧 NixOS</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Config:     ~/projects/nixos-ai
  Flake:      nixos-ai (nitro-v15)
  Models:     ~/.local/share/jarvis/voice/
  Qdrant:     localhost:6333
  Embeddings: localhost:8081
  LLM:        localhost:8080
"

    $YAD --title="Hardware" \
        --width=500 --height=400 \
        --text="$text" \
        --text-align=left \
        --button="nvidia-smi:1" \
        --button="Close:0" \
        --theme="$THEME" 2>/dev/null

    case $? in
        1) run_in_terminal "nvidia-smi" "watch -n 2 nvidia-smi" ;;
    esac
}

# ── Menu Principal ────────────────────────────────────────────────────────

show_main_menu() {
    local llama=$(check_service llama-cpp-server)
    local status_icon="🔴"
    [ "$llama" = "active" ] && status_icon="🟢"

    local text="
<b>═══════════════════════════════════════════════════</b>
<b>         🤖 NixOS-AI Launcher v1.0</b>
<b>═══════════════════════════════════════════════════</b>

Bem-vindo ao hub central do seu sistema AI.

Status: ${status_icon} llama-cpp: ${llama}

<b>Features Disponíveis:</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📊 System Status    GPU, CPU, RAM, temperaturas
  ⚙️  Services        Gerenciar serviços AI
  🤖 Jarvis           Voice, Dev CLI, RAG, Health
  🔧 Dev Tools        Benchmark, rebuild, testes
  🖥️  Hardware        Info do sistema
"

    $YAD --title="NixOS-AI Launcher" \
        --width=550 --height=500 \
        --text="$text" \
        --text-align=left \
        --image="dialog-information" \
        --button="📊 System Status:1" \
        --button="⚙️ Services:2" \
        --button="🤖 Jarvis:3" \
        --button="🔧 Dev Tools:4" \
        --button="🖥️ Hardware:5" \
        --button="Exit:0" \
        --theme="$THEME" 2>/dev/null

    case $? in
        1) show_status ;;
        2) show_services ;;
        3) show_jarvis ;;
        4) show_devtools ;;
        5) show_hardware ;;
    esac
}

# ── Quick Status (notification style) ─────────────────────────────────────

quick_status() {
    local gpu=$(gpu_info)
    local llama=$(check_service llama-cpp-server)
    local icon="🟢"
    [ "$llama" != "active" ] && icon="🔴"

    notify-send -t 5000 \
        -i "dialog-information" \
        "<b>NixOS-AI Status</b>" \
        "${icon} llama-cpp: ${llama}\n📊 GPU: ${gpu}" 2>/dev/null || true
}

# ── Entry Point ───────────────────────────────────────────────────────────

case "${1:-}" in
    --status|-s)  quick_status ;;
    --dev|-d)     foot --app-id jarvis-dev -e bash -c "cd ~/projects/nixos-ai && jarvis dev; exec bash" ;;
    --services)   show_services ;;
    --hardware)   show_hardware ;;
    --help|-h)
        echo "NixOS-AI Launcher"
        echo ""
        echo "Uso:"
        echo "  nixos-ai-launcher          Menu principal"
        echo "  nixos-ai-launcher --status Status rápido (notification)"
        echo "  nixos-ai-launcher --dev    Abre jarvis dev"
        echo "  nixos-ai-launcher --services  Gerenciar serviços"
        echo "  nixos-ai-launcher --hardware  Info do hardware"
        ;;
    *)            show_main_menu ;;
esac
