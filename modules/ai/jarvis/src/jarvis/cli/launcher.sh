#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# NixOS-AI Launcher v2.0 — GUI completa para todas as features do sistema
# Usa Yad para interfaces GTK com navegação robusta (loop while)
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail

YAD="${YAD:-yad}"
THEME="Adwaita:dark"
PROJECT_DIR="${PROJECT_DIR:-$HOME/projects/nixos-ai}"

# ── Helpers ───────────────────────────────────────────────────────────────

notify() {
    notify-send -t 4000 -i "${3:-dialog-information}" "$1" "$2" 2>/dev/null || true
}

run_in_terminal() {
    local title="${1:-Terminal}"
    local cmd="${2:-bash}"
    foot --app-id "floating_${title}" -e bash -c "
        echo '═══ ${title} ═══'
        echo ''
        eval '${cmd}'
        echo ''
        echo '─── Pressione Enter para fechar ───'
        read
    " &
}

check_service() {
    systemctl is-active "$1" 2>/dev/null || echo "inactive"
}

check_service_enabled() {
    systemctl is-enabled "$1" 2>/dev/null || echo "disabled"
}

service_icon() {
    local status=$(check_service "$1")
    [ "$status" = "active" ] && echo "🟢" || echo "🔴"
}

gpu_info() {
    nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo "N/A"
}

igpu_info() {
    local temp=$(cat /sys/class/drm/card*/device/hwmon/hwmon*/temp1_input 2>/dev/null | head -1 | awk '{print int($1/1000)}' 2>/dev/null || echo "N/A")
    local usage=$(cat /sys/class/drm/card*/device/hwmon/hwmon*/freq1_cur 2>/dev/null | head -1 || echo "0")
    local max=$(cat /sys/class/drm/card*/device/hwmon/hwmon*/freq1_max 2>/dev/null | head -1 || echo "1")
    local pct=0
    [ "$max" -gt 0 ] 2>/dev/null && pct=$(( usage * 100 / max ))
    echo "iGPU: ${temp}°C, ${pct}%"
}

cpu_info() {
    local usage=$(top -bn1 | grep "Cpu(s)" | awk '{print int($2+$4)}')
    local temp=$(cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | head -1 | awk '{print int($1/1000)}' 2>/dev/null || echo "N/A")
    echo "${usage}% @ ${temp}°C"
}

ram_info() {
    free -h | awk '/^Mem:/ {printf "%s/%s (%.0f%%)", $3, $2, $3/$2*100}'
}

disk_info() {
    df -h / | awk 'NR==2 {printf "%s/%s (%s)", $3, $2, $5}'
}

vram_info() {
    nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null | awk -F', ' '{printf "%s/%s", $1, $2}' || echo "N/A"
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu Principal
# ═══════════════════════════════════════════════════════════════════════════

main_menu() {
    while true; do
        local llama=$(service_icon llama-cpp-server)
        local qdrant=$(service_icon qdrant)
        local gaming=$(service_icon jarvis-gaming-watcher)
        local gpu=$(gpu_info)
        local ram=$(ram_info)

        $YAD --title="NixOS-AI Launcher v2.0" \
            --width=520 --height=520 \
            --text="<b>════════════════════════════════════════════</b>
<b>         🤖 NixOS-AI Launcher v2.0</b>
<b>════════════════════════════════════════════</b>

<b>Status Rápido:</b>
  ${llama} llama-cpp    ${qdrant} qdrant    ${gaming} gaming
  📊 GPU: ${gpu}
  💾 RAM: ${ram}

<b>─── Categorias ───────────────────────────────</b>

  🖥️  <b>System</b>     — Status, hardware, monitoramento
  ⚙️  <b>Services</b>   — Gerenciar serviços AI
  🤖 <b>Jarvis</b>     — Voice, Dev CLI, RAG, Health
  🔧 <b>Dev Tools</b>  — Build, test, benchmark, lint
  🧰 <b>Tools</b>      — opencode, aider, pi agent
  🌐 <b>MCPs</b>       — Servidores MCP (tavily, nixos)
  📡 <b>Waybar</b>     — Configuração do waybar
  🗑️  <b>Maintenance</b> — Nix store, flake update, logs" \
            --text-align=left \
            --image="dialog-information" \
            --button="🖥️ System:1" \
            --button="⚙️ Services:2" \
            --button="🤖 Jarvis:3" \
            --button="🔧 DevTools:4" \
            --button="🧰 Tools:5" \
            --button="🌐 MCPs:6" \
            --button="📡 Waybar:7" \
            --button="🗑️ Maintenance:8" \
            --button="gtk-quit:0" \
            --theme="$THEME" 2>/dev/null
        local rc=$?

        case $rc in
            1) menu_system ;;
            2) menu_services ;;
            3) menu_jarvis ;;
            4) menu_devtools ;;
            5) menu_tools ;;
            6) menu_mcps ;;
            7) menu_waybar ;;
            8) menu_maintenance ;;
            0|*) break ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: System Status
# ═══════════════════════════════════════════════════════════════════════════

menu_system() {
    while true; do
        local gpu=$(gpu_info)
        local igpu=$(igpu_info)
        local cpu=$(cpu_info)
        local ram=$(ram_info)
        local disk=$(disk_info)
        local vram=$(vram_info)
        local kernel=$(uname -r)
        local uptime=$(uptime -p | sed 's/up //')

        local llama=$(check_service llama-cpp-server)
        local embed=$(check_service llama-cpp-embeddings)
        local rerank=$(check_service llama-cpp-rerank)
        local qdrant=$(check_service qdrant)
        local gaming=$(check_service jarvis-gaming-watcher)

        $YAD --title="System Status" \
            --width=520 --height=480 \
            --text="<b>═══ SYSTEM STATUS ═══</b>

<b>🖥️ Hardware</b>
  CPU:       ${cpu}
  GPU (RTX): ${gpu}
  ${igpu}
  RAM:       ${ram}
  VRAM:      ${vram}
  Disk:      ${disk}
  Kernel:    ${kernel}
  Uptime:    ${uptime}

<b>⚙️ Services</b>
  llama-cpp-server:     ${llama}
  llama-cpp-embeddings: ${embed}
  llama-cpp-rerank:     ${rerank}
  qdrant:               ${qdrant}
  gaming-watcher:       ${gaming}

<b>🔌 Endpoints</b>
  LLM:        http://localhost:8080/v1
  Embeddings: http://localhost:8081/v1
  Qdrant:     http://localhost:6333" \
            --text-align=left \
            --button="🔄 Refresh:1" \
            --button="📊 nvidia-smi:2" \
            --button="📈 htop:3" \
            --button="gtk-go-back:99" \
            --theme="$THEME" 2>/dev/null
        local rc=$?

        case $rc in
            1) continue ;;  # Refresh (re-loop)
            2) run_in_terminal "nvidia-smi" "watch -n 2 nvidia-smi" ;;
            3) run_in_terminal "htop" "htop" ;;
            99|0|*) return ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: Services
# ═══════════════════════════════════════════════════════════════════════════

menu_services() {
    while true; do
        local llama=$(service_icon llama-cpp-server)
        local embed=$(service_icon llama-cpp-embeddings)
        local rerank=$(service_icon llama-cpp-rerank)
        local qdrant=$(service_icon qdrant)
        local gaming=$(service_icon jarvis-gaming-watcher)

        local llama_status=$(check_service llama-cpp-server)
        local embed_status=$(check_service llama-cpp-embeddings)
        local rerank_status=$(check_service llama-cpp-rerank)
        local qdrant_status=$(check_service qdrant)
        local gaming_status=$(check_service jarvis-gaming-watcher)

        $YAD --title="Service Management" \
            --width=520 --height=420 \
            --text="<b>═══ SERVICE MANAGEMENT ═══</b>

<b>🧠 AI Services</b>
  ${llama} llama-cpp-server     (${llama_status})
  ${embed} llama-cpp-embeddings (${embed_status})
  ${rerank} llama-cpp-rerank     (${rerank_status})

<b>🔍 Infrastructure</b>
  ${qdrant} qdrant               (${qdrant_status})

<b>🎮 Monitoring</b>
  ${gaming} gaming-watcher       (${gaming_status})" \
            --text-align=left \
            --button="🔄 Restart llama-cpp:1" \
            --button="🔄 Restart embeddings:2" \
            --button="🔄 Restart rerank:3" \
            --button="🔄 Restart qdrant:4" \
            --button="🔄 Restart ALL AI:5" \
            --button="📋 Logs:6" \
            --button="gtk-go-back:99" \
            --theme="$THEME" 2>/dev/null
        local rc=$?

        case $rc in
            1) sudo systemctl restart llama-cpp-server && notify "Services" "llama-cpp restarted" ;;
            2) sudo systemctl restart llama-cpp-embeddings && notify "Services" "embeddings restarted" ;;
            3) sudo systemctl restart llama-cpp-rerank && notify "Services" "rerank restarted" ;;
            4) sudo systemctl restart qdrant && notify "Services" "qdrant restarted" ;;
            5) sudo systemctl restart llama-cpp-server llama-cpp-embeddings llama-cpp-rerank qdrant && notify "Services" "All AI services restarted" ;;
            6) run_in_terminal "Logs" "journalctl -u llama-cpp-server -u qdrant --no-pager -n 50" ;;
            99|0|*) return ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: Jarvis
# ═══════════════════════════════════════════════════════════════════════════

menu_jarvis() {
    while true; do
        $YAD --title="Jarvis AI" \
            --width=520 --height=420 \
            --text="<b>═══ JARVIS AI ═══</b>

<b>💻 Development</b>
  Dev CLI    — Code editing agent (REPL interativo)
  Launcher   — Esta GUI (vocë está aqui!)

<b>🎤 Voice Pipeline</b>
  Voice      — STT → LLM → TTS (pipeline completo)
  STT        — Speech-to-Text (faster-whisper)
  TTS        — Text-to-Speech (Kokoro-82M)

<b>🧠 Intelligence</b>
  RAG Index  — Indexar codebase para busca semântica
  RAG Search — Buscar no código por significado
  Intent     — Classificação de intenção
  Emotion    — Detecção de emoção

<b>🔧 Diagnostics</b>
  Doctor     — Health check do sistema
  Waybar     — Status para waybar" \
            --text-align=left \
            --button="💻 Dev CLI:1" \
            --button="🎤 Voice:2" \
            --button="🗣️ STT Only:3" \
            --button="🔊 TTS Test:4" \
            --button="🧠 RAG Search:5" \
            --button="🔍 Doctor:6" \
            --button="📊 Waybar Status:7" \
            --button="gtk-go-back:99" \
            --theme="$THEME" 2>/dev/null
        local rc=$?

        case $rc in
            1) foot --app-id jarvis-dev -e bash -c "cd ${PROJECT_DIR} && jarvis dev; exec bash" && return ;;
            2) run_in_terminal "Jarvis Voice" "cd ${PROJECT_DIR} && jarvis voice 2>&1" ;;
            3) run_in_terminal "Jarvis STT" "cd ${PROJECT_DIR} && jarvis stt 2>&1" ;;
            4) menu_tts_test ;;
            5) menu_rag_search ;;
            6) run_in_terminal "Doctor" "cd ${PROJECT_DIR} && jarvis doctor 2>&1" ;;
            7) run_in_terminal "Waybar" "cd ${PROJECT_DIR} && jarvis waybar 2>&1" ;;
            99|0|*) return ;;
        esac
    done
}

menu_tts_test() {
    local result=$($YAD --title="TTS Test" \
        --width=400 --height=120 \
        --entry \
        --text="Digite o texto para TTS (Kokoro):" \
        --button="🔊 Speak:1" \
        --button="gtk-cancel:0" \
        --theme="$THEME" 2>/dev/null)
    local rc=$?

    if [ $rc -eq 1 ] && [ -n "$result" ]; then
        run_in_terminal "TTS" "cd ${PROJECT_DIR} && jarvis speak '${result}' 2>&1"
    fi
}

menu_rag_search() {
    local result=$($YAD --title="RAG Search" \
        --width=400 --height=120 \
        --entry \
        --text="Buscar no código (semântico):" \
        --button="🔍 Search:1" \
        --button="gtk-cancel:0" \
        --theme="$THEME" 2>/dev/null)
    local rc=$?

    if [ $rc -eq 1 ] && [ -n "$result" ]; then
        run_in_terminal "RAG Search" "cd ${PROJECT_DIR} && jarvis rag search '${result}' 2>&1"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: Dev Tools
# ═══════════════════════════════════════════════════════════════════════════

menu_devtools() {
    while true; do
        $YAD --title="Dev Tools" \
            --width=520 --height=420 \
            --text="<b>═══ DEV TOOLS ═══</b>

<b>🔨 Build</b>
  Rebuild     — nixos-rebuild switch (host)
  Build       — nix build (individual package)
  Flake Lock  — Atualizar flake.lock

<b>🧪 Test</b>
  Pytest      — Rodar suite de testes
  Pytest Verbose — Testes detalhados
  Pytest Coverage — Cobertura de código

<b>📊 Quality</b>
  Lint        — Ruff linter
  Type Check  — Pyright/mypy
  Benchmark   — Performance test

<b>📋 Git</b>
  Status      — git status
  Log         — Últimos commits
  Diff        — Mudanças pendentes" \
            --text-align=left \
            --button="🔨 Rebuild:1" \
            --button="🧪 Tests:2" \
            --button="🧪 Tests Verbose:3" \
            --button="📊 Benchmark:4" \
            --button="🔍 Lint:5" \
            --button="📋 Git Status:6" \
            --button="📜 Git Log:7" \
            --button="gtk-go-back:99" \
            --theme="$THEME" 2>/dev/null
        local rc=$?

        case $rc in
            1) run_in_terminal "Rebuild" "cd ${PROJECT_DIR} && bash rebuild-host.sh 2>&1" ;;
            2) run_in_terminal "Pytest" "cd ${PROJECT_DIR} && nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q 2>&1" ;;
            3) run_in_terminal "Pytest Verbose" "cd ${PROJECT_DIR} && nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -v 2>&1" ;;
            4) run_in_terminal "Benchmark" "cd ${PROJECT_DIR} && bash benchmark.sh --warmup --repeat 3 2>&1" ;;
            5) run_in_terminal "Linter" "cd ${PROJECT_DIR} && nix develop --command ruff check modules/ai/jarvis/src/ 2>&1" ;;
            6) run_in_terminal "Git Status" "cd ${PROJECT_DIR} && git status 2>&1" ;;
            7) run_in_terminal "Git Log" "cd ${PROJECT_DIR} && git log --oneline -20 2>&1" ;;
            99|0|*) return ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: Tools (opencode, aider, pi)
# ═══════════════════════════════════════════════════════════════════════════

menu_tools() {
    while true; do
        local opencode_bin=$(which opencode 2>/dev/null || echo "not found")
        local aider_bin=$(which aider 2>/dev/null || echo "not found")
        local pi_bin=$(which pi 2>/dev/null || echo "not found")

        $YAD --title="External Tools" \
            --width=520 --height=380 \
            --text="<b>═══ EXTERNAL TOOLS ═══</b>

<b>💻 Code Editors (CLI)</b>
  opencode   — ${opencode_bin}
  aider      — ${aider_bin}

<b>🤖 AI Agents</b>
  pi         — ${pi_bin}
  roo dev    — VSCode Extension (abrir VSCode)

<b>📝 Quick Launch</b>
  Abra qualquer ferramenta e navegue até o projeto:
  cd ~/projects/nixos-ai" \
            --text-align=left \
            --button="💻 opencode:1" \
            --button="💻 aider:2" \
            --button="🤖 pi:3" \
            --button="📂 Open VSCode:4" \
            --button="📂 Open Terminal:5" \
            --button="gtk-go-back:99" \
            --theme="$THEME" 2>/dev/null
        local rc=$?

        case $rc in
            1) foot --app-id opencode -e bash -c "cd ${PROJECT_DIR} && opencode; exec bash" && return ;;
            2) foot --app-id aider -e bash -c "cd ${PROJECT_DIR} && aider; exec bash" && return ;;
            3) foot --app-id pi-agent -e bash -c "cd ${PROJECT_DIR} && pi; exec bash" && return ;;
            4) code "${PROJECT_DIR}" && return ;;
            5) foot --app-id terminal -e bash -c "cd ${PROJECT_DIR}; exec bash" && return ;;
            99|0|*) return ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: MCPs
# ═══════════════════════════════════════════════════════════════════════════

menu_mcps() {
    while true; do
        local tavily_status="🔴 offline"
        curl -s http://localhost:3000/health >/dev/null 2>&1 && tavily_status="🟢 online"

        local nixos_status="🔴 offline"
        curl -s http://localhost:3001/health >/dev/null 2>&1 && nixos_status="🟢 online"

        $YAD --title="MCP Servers" \
            --width=520 --height=350 \
            --text="<b>═══ MCP SERVERS ═══</b>

<b>🌐 Web Search</b>
  tavily-search  — ${tavily_status}
  Uso: Busca web, extração de URLs, pesquisa técnica

<b>📦 NixOS</b>
  mcp-nixos      — ${nixos_status}
  Uso: Consultar packages, versões, opções do nixpkgs

<b>📂 Config Location</b>
  ~/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json

<b>ℹ️ MCPs são usados pelo Roo Dev (VSCode extension)</b>" \
            --text-align=left \
            --button="🔍 Test Tavily:1" \
            --button="📦 Test NixOS:2" \
            --button="📂 Edit Config:3" \
            --button="gtk-go-back:99" \
            --theme="$THEME" 2>/dev/null
        local rc=$?

        case $rc in
            1) run_in_terminal "Tavily Test" "echo 'Testing tavily-search MCP...' && curl -s http://localhost:3000 2>&1 || echo 'MCP server not running (used by Roo Dev)'" ;;
            2) run_in_terminal "NixOS Test" "echo 'Testing mcp-nixos MCP...' && curl -s http://localhost:3001 2>&1 || echo 'MCP server not running (used by Roo Dev)'" ;;
            3) code ~/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json && return ;;
            99|0|*) return ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: Waybar
# ═══════════════════════════════════════════════════════════════════════════

menu_waybar() {
    while true; do
        $YAD --title="Waybar Configuration" \
            --width=520 --height=350 \
            --text="<b>═══ WAYBAR CONFIG ═══</b>

<b>📊 Módulos Ativos</b>
  custom/jarvis  — Status do Jarvis (click abre Dev CLI)
  custom/cpu     — CPU usage
  custom/memory  — RAM usage
  custom/gpu     — GPU usage (NVIDIA)
  custom/igpu    — iGPU usage (Intel)
  custom/files   — Disk usage

<b>🔗 Click Actions</b>
  Jarvis module → abre jarvis dev (REPL)

<b>📝 Editar</b>
  Config: home-manager/modules/waybar.nix" \
            --text-align=left \
            --button="📂 Edit Waybar Config:1" \
            --button="🔄 Reload Waybar:2" \
            --button="📊 Test Jarvis Module:3" \
            --button="gtk-go-back:99" \
            --theme="$THEME" 2>/dev/null
        local rc=$?

        case $rc in
            1) code "${PROJECT_DIR}/home-manager/modules/waybar.nix" && return ;;
            2) killall waybar 2>/dev/null; waybar &>/dev/null & disown && notify "Waybar" "Reloaded" ;;
            3) run_in_terminal "Waybar Status" "cd ${PROJECT_DIR} && jarvis waybar 2>&1" ;;
            99|0|*) return ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: Maintenance
# ═══════════════════════════════════════════════════════════════════════════

menu_maintenance() {
    while true; do
        local store_size=$(nix-store --query --size /nix/store 2>/dev/null | awk '{printf "%.1f GB", $1/1024/1024/1024}' || echo "N/A")
        local gc_root=$(ls /nix/var/nix/gcroots/ 2>/dev/null | wc -l || echo "0")

        $YAD --title="Maintenance" \
            --width=520 --height=380 \
            --text="<b>═══ MAINTENANCE ═══</b>

<b>🗑️ Nix Store</b>
  Tamanho: ${store_size}
  GC Roots: ${gc_root}

<b>📦 Flake</b>
  Projeto: ${PROJECT_DIR}

<b>📋 Logs</b>
  Ver logs de serviços AI" \
            --text-align=left \
            --button="🗑️ Nix Store GC:1" \
            --button="📦 Update Flake Lock:2" \
            --button="📋 AI Service Logs:3" \
            --button="📋 Gaming Logs:4" \
            --button="🧹 Clean __pycache__:5" \
            --button="gtk-go-back:99" \
            --theme="$THEME" 2>/dev/null
        local rc=$?

        case $rc in
            1) run_in_terminal "Nix GC" "sudo nix-collect-garbage -d 2>&1" ;;
            2) run_in_terminal "Flake Update" "cd ${PROJECT_DIR} && nix flake update 2>&1" ;;
            3) run_in_terminal "AI Logs" "journalctl -u llama-cpp-server -u qdrant --no-pager -n 100 2>&1" ;;
            4) run_in_terminal "Gaming Logs" "journalctl -u jarvis-gaming-watcher --no-pager -n 50 2>&1" ;;
            5) run_in_terminal "Clean" "find ${PROJECT_DIR} -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; echo 'Cleaned'" ;;
            99|0|*) return ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════════════
# Quick Status (notification)
# ═══════════════════════════════════════════════════════════════════════════

quick_status() {
    local llama=$(check_service llama-cpp-server)
    local qdrant=$(check_service qdrant)
    local gaming=$(check_service jarvis-gaming-watcher)
    local gpu=$(gpu_info)
    local ram=$(ram_info)

    local icon="🟢"
    [ "$llama" != "active" ] && icon="🔴"

    notify-send -t 5000 -i "dialog-information" \
        "<b>NixOS-AI Status</b>" \
        "${icon} llama-cpp: ${llama}
🟢 qdrant: ${qdrant}
🟢 gaming: ${gaming}
📊 GPU: ${gpu}
💾 RAM: ${ram}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════════════════

case "${1:-}" in
    --status|-s)  quick_status ;;
    --dev|-d)     foot --app-id jarvis-dev -e bash -c "cd ${PROJECT_DIR} && jarvis dev; exec bash" ;;
    --services)   menu_services ;;
    --hardware)   menu_system ;;
    --tools)      menu_tools ;;
    --help|-h)
        echo "NixOS-AI Launcher v2.0"
        echo ""
        echo "Usage:"
        echo "  (sem args)    Menu principal"
        echo "  --status      Status rápido (notification)"
        echo "  --dev         Abre jarvis dev"
        echo "  --services    Gerenciar serviços"
        echo "  --hardware    Info do hardware"
        echo "  --tools       Ferramentas externas"
        echo ""
        echo "Keybinding: SUPER+A"
        ;;
    *)            main_menu ;;
esac
