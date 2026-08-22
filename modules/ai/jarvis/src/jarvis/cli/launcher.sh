#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# NixOS-AI Launcher — GUI para todas as features do sistema
# Usa Yad (Yet Another Dialog) para interfaces GTK
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail

YAD="${YAD:-yad}"
THEME="Adwaita:dark"

# ── Helpers ───────────────────────────────────────────────────────────────

notify() {
    notify-send -t 3000 -i "${3:-dialog-information}" "$1" "$2" 2>/dev/null || true
}

run_in_terminal() {
    foot --app-id floating_shell -e bash -c "$2; echo '--- Pressione Enter para fechar ---'; read" &
}

check_service() {
    systemctl is-active "$1" 2>/dev/null || echo "inactive"
}

gpu_info() {
    nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo "N/A"
}

cpu_info() {
    local usage=$(top -bn1 | grep "Cpu(s)" | awk '{print int($2+$4)}')
    local temp=$(cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | head -1 | awk '{print int($1/1000)}' 2>/dev/null || echo "N/A")
    echo "${usage}%,${temp}°C"
}

ram_info() {
    free -h | awk '/^Mem:/ {printf "%s/%s (%.0f%%)", $3, $2, $3/$2*100}'
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu Principal
# ═══════════════════════════════════════════════════════════════════════════

main_menu() {
    local llama=$(check_service llama-cpp-server)
    local status_icon="🔴"
    [ "$llama" = "active" ] && status_icon="🟢"

    local text="<b>═══════════════════════════════════════</b>
<b>       🤖 NixOS-AI Launcher v1.0</b>
<b>═══════════════════════════════════════</b>

Status: ${status_icon} llama-cpp: ${llama}

<b>Features:</b>
  📊 System Status — GPU, CPU, RAM, temperaturas
  ⚙️  Services — Gerenciar serviços AI
  🤖 Jarvis — Voice, Dev CLI, RAG, Health
  🔧 Dev Tools — Benchmark, rebuild, testes
  🖥️  Hardware — Info do sistema"

    $YAD --title="NixOS-AI Launcher" \
        --width=480 --height=420 \
        --text="$text" \
        --text-align=left \
        --image="dialog-information" \
        --button="📊 Status:1" \
        --button="⚙️ Services:2" \
        --button="🤖 Jarvis:3" \
        --button="🔧 DevTools:4" \
        --button="🖥️ Hardware:5" \
        --button="gtk-quit:0" \
        --theme="$THEME" 2>/dev/null
    local rc=$?

    case $rc in
        1) menu_status ;;
        2) menu_services ;;
        3) menu_jarvis ;;
        4) menu_devtools ;;
        5) menu_hardware ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: System Status
# ═══════════════════════════════════════════════════════════════════════════

menu_status() {
    local gpu=$(gpu_info)
    local cpu=$(cpu_info)
    local ram=$(ram_info)
    local llama=$(check_service llama-cpp-server)
    local qdrant=$(check_service qdrant)
    local ww=$(check_service jarvis-wakeword)

    $YAD --title="System Status" \
        --width=480 --height=350 \
        --text="<b>═══ SYSTEM STATUS ═══</b>

<b>🖥️ Hardware</b>
  GPU (RTX 4050):   ${gpu}
  CPU:              ${cpu}
  RAM:              ${ram}

<b>⚙️ Services</b>
  llama-cpp:        ${llama}
  qdrant:           ${qdrant}
  jarvis-wakeword:  ${ww}" \
        --text-align=left \
        --button="gtk-refresh:1" \
        --button="gtk-go-back:2" \
        --button="gtk-quit:0" \
        --theme="$THEME" 2>/dev/null
    local rc=$?

    case $rc in
        1) menu_status ;;  # Refresh
        2) main_menu ;;    # Back
    esac
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: Services
# ═══════════════════════════════════════════════════════════════════════════

menu_services() {
    local llama=$(check_service llama-cpp-server)
    local embed=$(check_service llama-cpp-embeddings)
    local rerank=$(check_service llama-cpp-rerank)
    local qdrant=$(check_service qdrant)

    $YAD --title="Services" \
        --width=480 --height=350 \
        --text="<b>═══ SERVICE MANAGEMENT ═══</b>

<b>AI Services</b>
  llama-cpp (chat):       ${llama}
  llama-cpp (embeddings): ${embed}
  llama-cpp (rerank):     ${rerank}
  qdrant:                 ${qdrant}" \
        --text-align=left \
        --button="Restart llama-cpp:1" \
        --button="Restart all AI:2" \
        --button="View logs:3" \
        --button="gtk-go-back:4" \
        --button="gtk-quit:0" \
        --theme="$THEME" 2>/dev/null
    local rc=$?

    case $rc in
        1) sudo systemctl restart llama-cpp-server
           notify "Services" "llama-cpp restarted"
           menu_services ;;
        2) sudo systemctl restart llama-cpp-server llama-cpp-embeddings llama-cpp-rerank qdrant
           notify "Services" "All AI services restarted"
           menu_services ;;
        3) run_in_terminal "logs" "journalctl -u llama-cpp-server -f --no-pager" ;;
        4) main_menu ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: Jarvis
# ═══════════════════════════════════════════════════════════════════════════

menu_jarvis() {
    $YAD --title="Jarvis" \
        --width=450 --height=320 \
        --text="<b>═══ JARVIS AI ═══</b>

<b>Features</b>
  💻 Dev CLI — Code editing agent
  🔍 Health — System diagnostics
  🧠 RAG — Semantic code search
  🎤 Voice — STT → LLM → TTS" \
        --text-align=left \
        --button="💻 Dev CLI:1" \
        --button="🔍 Health:2" \
        --button="🧠 RAG Index:3" \
        --button="🔊 Test TTS:4" \
        --button="gtk-go-back:5" \
        --button="gtk-quit:0" \
        --theme="$THEME" 2>/dev/null
    local rc=$?

    case $rc in
        1) foot --app-id jarvis-dev -e bash -c "cd ~/projects/nixos-ai && jarvis dev; exec bash" ;;
        2) run_in_terminal "doctor" "jarvis doctor 2>&1" ;;
        3) run_in_terminal "RAG" "cd ~/projects/nixos-ai && jarvis rag index 2>&1" ;;
        4) menu_tts_test ;;
        5) main_menu ;;
    esac
}

menu_tts_test() {
    local result=$($YAD --title="TTS Test" \
        --width=400 --height=120 \
        --entry \
        --text="Digite o texto para TTS:" \
        --button="gtk-ok:1" \
        --button="gtk-cancel:0" \
        --theme="$THEME" 2>/dev/null)
    local rc=$?

    if [ $rc -eq 1 ] && [ -n "$result" ]; then
        run_in_terminal "TTS" "jarvis speak '$result' 2>&1"
    fi
    menu_jarvis
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: Dev Tools
# ═══════════════════════════════════════════════════════════════════════════

menu_devtools() {
    $YAD --title="Dev Tools" \
        --width=450 --height=300 \
        --text="<b>═══ DEV TOOLS ═══</b>

<b>Build & Test</b>
  📊 Benchmark — Performance test
  🔨 Rebuild — nixos-rebuild switch
  🧪 Tests — pytest suite

<b>Code Quality</b>
  🔍 Lint — Ruff linter" \
        --text-align=left \
        --button="📊 Benchmark:1" \
        --button="🔨 Rebuild:2" \
        --button="🧪 Tests:3" \
        --button="🔍 Lint:4" \
        --button="gtk-go-back:5" \
        --button="gtk-quit:0" \
        --theme="$THEME" 2>/dev/null
    local rc=$?

    case $rc in
        1) run_in_terminal "Benchmark" "cd ~/projects/nixos-ai && bash benchmark.sh --warmup --repeat 3 2>&1" ;;
        2) run_in_terminal "Rebuild" "cd ~/projects/nixos-ai && bash rebuild-host.sh 2>&1" ;;
        3) run_in_terminal "Tests" "cd ~/projects/nixos-ai && nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q 2>&1" ;;
        4) run_in_terminal "Linter" "cd ~/projects/nixos-ai && nix develop --command ruff check modules/ai/jarvis/src/ 2>&1" ;;
        5) main_menu ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: Hardware
# ═══════════════════════════════════════════════════════════════════════════

menu_hardware() {
    local gpu=$(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null || echo "N/A")
    local cpu=$(lscpu | grep "Model name" | sed 's/.*: *//' | head -1)
    local ram=$(free -h | awk '/^Mem:/ {print $2}')
    local disk=$(df -h / | awk 'NR==2 {printf "%s/%s (%s)", $3, $2, $5}')
    local kernel=$(uname -r)

    $YAD --title="Hardware" \
        --width=480 --height=350 \
        --text="<b>═══ HARDWARE INFO ═══</b>

<b>🖥️ Components</b>
  CPU:    ${cpu}
  GPU:    ${gpu}
  RAM:    ${ram}
  Disk:   ${disk}
  Kernel: ${kernel}

<b>🔧 Services</b>
  LLM:        localhost:8080
  Embeddings: localhost:8081
  Qdrant:     localhost:6333" \
        --text-align=left \
        --button="nvidia-smi:1" \
        --button="gtk-go-back:2" \
        --button="gtk-quit:0" \
        --theme="$THEME" 2>/dev/null
    local rc=$?

    case $rc in
        1) run_in_terminal "nvidia-smi" "watch -n 2 nvidia-smi" ;;
        2) main_menu ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════════════
# Quick Status (notification)
# ═══════════════════════════════════════════════════════════════════════════

quick_status() {
    local gpu=$(gpu_info)
    local llama=$(check_service llama-cpp-server)
    local icon="🟢"
    [ "$llama" != "active" ] && icon="🔴"
    notify-send -t 5000 -i "dialog-information" \
        "<b>NixOS-AI Status</b>" \
        "${icon} llama-cpp: ${llama}\n📊 GPU: ${gpu}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════════════════

case "${1:-}" in
    --status|-s)  quick_status ;;
    --dev|-d)     foot --app-id jarvis-dev -e bash -c "cd ~/projects/nixos-ai && jarvis dev; exec bash" ;;
    --services)   menu_services ;;
    --hardware)   menu_hardware ;;
    --help|-h)
        echo "NixOS-AI Launcher"
        echo "  (sem args)    Menu principal"
        echo "  --status      Status rápido (notification)"
        echo "  --dev         Abre jarvis dev"
        echo "  --services    Gerenciar serviços"
        echo "  --hardware    Info do hardware"
        ;;
    *)            main_menu ;;
esac
