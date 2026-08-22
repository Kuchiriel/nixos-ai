#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# NixOS-AI Launcher v3.0 — Cyberpunk GUI
# Usa Yad + GTK3 CSS para estética cyan/preto
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail

YAD="${YAD:-yad}"
PROJECT_DIR="${PROJECT_DIR:-$HOME/projects/nixos-ai}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSS_FILE="${SCRIPT_DIR}/launcher-cyberpunk.css"

# Aplica CSS cyberpunk via GTK3 provider
if [ -f "$CSS_FILE" ]; then
    export GTK_CSS_PROVIDER="$CSS_FILE"
fi

# ── Cores (Pango markup) ────────────────────────────────────────────────
C='\033[0;36m'  # ciano
G='\033[0;32m'  # verde
R='\033[0;31m'  # vermelho
Y='\033[0;33m'  # amarelo
W='\033[1;37m'  # branco bold
D='\033[0;90m'  # cinza escuro
NC='\033[0m'    # reset

# Pango colors
CYAN="#00ffff"
GREEN="#50FA7B"
RED="#FF5555"
ORANGE="#FFB86C"
GRAY="#666666"
WHITE="#ffffff"
DIM="#888888"

# ── Helpers ─────────────────────────────────────────────────────────────

notify() {
    notify-send -t 3000 -i "${3:-dialog-information}" "$1" "$2" 2>/dev/null || true
}

run_in_terminal() {
    local title="${1:-Terminal}"
    local cmd="${2:-bash}"
    foot --app-id "floating_${title}" -e bash -c "
        echo -e '\033[0;36m═══ ${title} ═══\033[0m'
        echo ''
        eval '${cmd}'
        echo ''
        echo -e '\033[0;90m─── Pressione Enter para fechar ───\033[0m'
        read
    " &
}

check_service() {
    systemctl --user is-active "$1" 2>/dev/null || systemctl is-active "$1" 2>/dev/null || echo "inactive"
}

service_dot() {
    local status
    status=$(check_service "$1")
    if [ "$status" = "active" ]; then
        echo "<span color='${GREEN}'>●</span>"
    else
        echo "<span color='${RED}'>●</span>"
    fi
}

service_label() {
    local status
    status=$(check_service "$1")
    if [ "$status" = "active" ]; then
        echo "<span color='${GREEN}'>${1} ●</span>"
    else
        echo "<span color='${GRAY}'>${1} ○</span>"
    fi
}

gpu_info() {
    nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo "N/A"
}

igpu_info() {
    local cur=$(cat /sys/class/drm/card1/gt_cur_freq_mhz 2>/dev/null || echo 0)
    local max=$(cat /sys/class/drm/card1/gt_max_freq_mhz 2>/dev/null || echo 1500)
    local pct=0
    [ "$max" -gt 0 ] 2>/dev/null && pct=$(( cur * 100 / max ))
    echo "${cur}/${max} MHz (${pct}%)"
}

cpu_info() {
    local usage=$(top -bn1 | grep "Cpu(s)" | awk '{print int($2+$4)}')
    local temp=$(cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | head -1 | awk '{print int($1/1000)}' 2>/dev/null || echo "?")
    echo "${usage}% @ ${temp}°C"
}

ram_info() {
    free -h | awk '/^Mem:/ {printf "%s/%s (%.0f%%)", $3, $2, $3/$2*100}'
}

vram_info() {
    nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null | awk -F', ' '{printf "%s/%s", $1, $2}' || echo "N/A"
}

disk_info() {
    df -h / | awk 'NR==2 {printf "%s/%s (%s)", $3, $2, $5}'
}

llm_status() {
    local health
    health=$(curl -s --connect-timeout 2 http://localhost:8080/health 2>/dev/null || echo '{"status":"down"}')
    if echo "$health" | grep -q '"ok"\|"healthy"'; then
        echo "online"
    else
        echo "offline"
    fi
}

llm_slots() {
    curl -s --connect-timeout 2 http://localhost:8080/slots 2>/dev/null | \
        python3 -c "
import sys, json
try:
    slots = json.load(sys.stdin)
    busy = sum(1 for s in slots if s.get('is_processing'))
    total = len(slots)
    ctx = sum(s.get('n_prompt_tokens',0) for s in slots)
    ctx_max = sum(s.get('n_ctx',0) for s in slots)
    pct = int(ctx/ctx_max*100) if ctx_max > 0 else 0
    print(f'{busy}/{total} slots, ctx {pct}%')
except: print('?')
" 2>/dev/null || echo "?"
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu Principal
# ═══════════════════════════════════════════════════════════════════════════

main_menu() {
    while true; do
        local llama_dot=$(service_dot llama-cpp-server)
        local qdrant_dot=$(service_dot qdrant)
        local gpu=$(gpu_info)
        local ram=$(ram_info)
        local vram=$(vram_info)
        local llm=$(llm_status)
        local slots=$(llm_slots)

        local llm_color="${GREEN}"
        [ "$llm" != "online" ] && llm_color="${RED}"

        $YAD --title="NixOS-AI" \
            --width=560 --height=580 \
            --text="<span font='16' color='${CYAN}'>▸ NixOS-AI</span>  <span font='10' color='${DIM}'>v3.0</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span font='11'>${llama_dot}</span> <span font='11' color='${WHITE}'>llama.cpp</span>     <span color='${llm_color}'>${llm}</span>  <span color='${DIM}'>${slots}</span>
  <span font='11'>$(service_dot qdrant)</span> <span font='11' color='${WHITE}'>qdrant</span>        <span color='${GREEN}'>$(check_service qdrant)</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${CYAN}'>󰍛</span> CPU:  <span color='${WHITE}'>$(cpu_info)</span>
  <span color='${CYAN}'>󰘚</span> RAM:  <span color='${WHITE}'>${ram}</span>
  <span color='${CYAN}'>󰢮</span> GPU:  <span color='${WHITE}'>${gpu}</span>
  <span color='${CYAN}'>󰢮</span> VRAM: <span color='${WHITE}'>${vram}</span>
  <span color='${CYAN}'>󰉋</span> Disk: <span color='${WHITE}'>$(disk_info)</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${CYAN}'>󰊠</span> <b>System</b>      <span color='${DIM}'>hardware, monitoramento</span>
  <span color='${CYAN}'>󰒓</span> <b>Services</b>    <span color='${DIM}'>gerenciar serviços AI</span>
  <span color='${CYAN}'>󰋗</span> <b>Jarvis</b>      <span color='${DIM}'>dev CLI, voice, RAG</span>
  <span color='${CYAN}'>󰈙</span> <b>Dev Tools</b>   <span color='${DIM}'>build, test, lint</span>
  <span color='${CYAN}'>󰋖</span> <b>Tools</b>       <span color='${DIM}'>opencode, aider, pi</span>
  <span color='${CYAN}'>󰖟</span> <b>MCPs</b>        <span color='${DIM}'>tavily, nixos</span>
  <span color='${CYAN}'>󰍹</span> <b>Waybar</b>      <span color='${DIM}'>configuração</span>
  <span color='${CYAN}'>�Ẓ</span> <b>Maintenance</b> <span color='${DIM}'>GC, logs, cache</span>" \
            --text-align=left \
            --button="<span color='${CYAN}'>󰊠 System</span>":1 \
            --button="<span color='${CYAN}'>󰒓 Services</span>":2 \
            --button="<span color='${CYAN}'>󰋗 Jarvis</span>":3 \
            --button="<span color='${CYAN}'>󰈙 DevTools</span>":4 \
            --button="<span color='${CYAN}'>󰋖 Tools</span>":5 \
            --button="<span color='${CYAN}'>󰖟 MCPs</span>":6 \
            --button="<span color='${CYAN}'>󰍹 Waybar</span>":7 \
            --button="<span color='${CYAN}'>�Ẓ Maint</span>":8 \
            --button="<span color='${RED}'>gtk-quit</span>":0 \
            2>/dev/null
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
# Menu: System
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
        local uptime_val=$(uptime -p | sed 's/up //')

        local llama_dot=$(service_dot llama-cpp-server)
        local embed_dot=$(service_dot llama-cpp-embeddings)
        local rerank_dot=$(service_dot llama-cpp-rerank)
        local qdrant_dot=$(service_dot qdrant)
        local llm=$(llm_status)
        local slots=$(llm_slots)

        $YAD --title="System" \
            --width=560 --height=520 \
            --text="<span font='14' color='${CYAN}'>󰊠 System Status</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Hardware</b></span>

  <span color='${CYAN}'>󰍛</span> CPU:    <span color='${WHITE}'>${cpu}</span>
  <span color='${CYAN}'>󰢮</span> GPU:    <span color='${WHITE}'>${gpu}</span>
  <span color='${CYAN}'>󰢮</span> iGPU:   <span color='${WHITE}'>${igpu}</span>
  <span color='${CYAN}'>󰘚</span> RAM:    <span color='${WHITE}'>${ram}</span>
  <span color='${CYAN}'>󰢮</span> VRAM:   <span color='${WHITE}'>${vram}</span>
  <span color='${CYAN}'>󰉋</span> Disk:   <span color='${WHITE}'>${disk}</span>
  <span color='${CYAN}'>󰅶</span> Kernel: <span color='${WHITE}'>${kernel}</span>
  <span color='${CYAN}'>󰅒</span> Uptime: <span color='${WHITE}'>${uptime_val}</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Services</b></span>

  ${llama_dot} llama-cpp-server     <span color='${DIM}'>${llm} · ${slots}</span>
  ${embed_dot} llama-cpp-embeddings
  ${rerank_dot} llama-cpp-rerank
  ${qdrant_dot} qdrant

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Endpoints</b></span>

  <span color='${DIM}'>LLM:        http://localhost:8080/v1</span>
  <span color='${DIM}'>Embeddings: http://localhost:8081/v1</span>
  <span color='${DIM}'>Qdrant:     http://localhost:6333</span>" \
            --text-align=left \
            --button="<span color='${CYAN}'>  Refresh</span>":1 \
            --button="<span color='${CYAN}'>󰍛 nvidia-smi</span>":2 \
            --button="<span color='${CYAN}'>󰈙 htop</span>":3 \
            --button="<span color='${GRAY}'>gtk-go-back</span>":99 \
            2>/dev/null
        local rc=$?
        case $rc in
            1) continue ;;
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
        local llama_s=$(check_service llama-cpp-server)
        local embed_s=$(check_service llama-cpp-embeddings)
        local rerank_s=$(check_service llama-cpp-rerank)
        local qdrant_s=$(check_service qdrant)

        $YAD --title="Services" \
            --width=560 --height=450 \
            --text="<span font='14' color='${CYAN}'>󰒓 Service Management</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>AI Core</b></span>

  $(service_label llama-cpp-server)    <span color='${DIM}'>${llama_s}</span>
  $(service_label llama-cpp-embeddings) <span color='${DIM}'>${embed_s}</span>
  $(service_label llama-cpp-rerank)    <span color='${DIM}'>${rerank_s}</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Infrastructure</b></span>

  $(service_label qdrant)              <span color='${DIM}'>${qdrant_s}</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Load</b></span>

  <span color='${CYAN}'>󰊠</span> <span color='${WHITE}'>$(llm_slots)</span>" \
            --text-align=left \
            --button="<span color='${ORANGE}'>󰑓 Restart llama-cpp</span>":1 \
            --button="<span color='${ORANGE}'>󰑓 Restart embeddings</span>":2 \
            --button="<span color='${ORANGE}'>󰑓 Restart rerank</span>":3 \
            --button="<span color='${ORANGE}'>󰑓 Restart qdrant</span>":4 \
            --button="<span color='${RED}'>󰑓 Restart ALL</span>":5 \
            --button="<span color='${CYAN}'>󰈙 Logs</span>":6 \
            --button="<span color='${GRAY}'>gtk-go-back</span>":99 \
            2>/dev/null
        local rc=$?
        case $rc in
            1) sudo systemctl restart llama-cpp-server && notify "Services" "llama-cpp restarted" ;;
            2) sudo systemctl restart llama-cpp-embeddings && notify "Services" "embeddings restarted" ;;
            3) sudo systemctl restart llama-cpp-rerank && notify "Services" "rerank restarted" ;;
            4) sudo systemctl restart qdrant && notify "Services" "qdrant restarted" ;;
            5) sudo systemctl restart llama-cpp-server llama-cpp-embeddings llama-cpp-rerank qdrant && notify "Services" "All AI restarted" ;;
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
            --width=560 --height=480 \
            --text="<span font='14' color='${CYAN}'>󰋗 Jarvis AI</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Development</b></span>

  <span color='${CYAN}'>󰈙</span> Dev CLI      <span color='${DIM}'>REPL interativo de código</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Voice Pipeline</b></span>

  <span color='${CYAN}'>󰍬</span> Voice        <span color='${DIM}'>STT → roteador → TTS</span>
  <span color='${CYAN}'>󰈙</span> STT          <span color='${DIM}'>faster-whisper (transcrição)</span>
  <span color='${CYAN}'>󰕾</span> TTS          <span color='${DIM}'>Kokoro-82M (síntese)</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Intelligence</b></span>

  <span color='${CYAN}'>󰓫</span> RAG Index    <span color='${DIM}'>indexar codebase</span>
  <span color='${CYAN}'>󰓫</span> RAG Search   <span color='${DIM}'>busca semântica</span>
  <span color='${CYAN}'>󰓫</span> Intent       <span color='${DIM}'>classificação de intenção</span>
  <span color='${CYAN}'>󰓫</span> Memory Vault <span color='${DIM}'>resumo episódico</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Diagnostics</b></span>

  <span color='${CYAN}'>󰋗</span> Doctor       <span color='${DIM}'>health check completo</span>
  <span color='${CYAN}'>󰊠</span> HWDetect     <span color='${DIM}'>detectar hardware e tier</span>
  <span color='${CYAN}'>󰍹</span> Waybar       <span color='${DIM}'>status widget</span>" \
            --text-align=left \
            --button="<span color='${CYAN}'>󰈙 Dev CLI</span>":1 \
            --button="<span color='${CYAN}'>󰍬 Voice</span>":2 \
            --button="<span color='${CYAN}'>󰈙 STT Only</span>":3 \
            --button="<span color='${CYAN}'>󰕾 TTS Test</span>":4 \
            --button="<span color='${CYAN}'>󰓫 RAG Search</span>":5 \
            --button="<span color='${CYAN}'>󰓫 Memory</span>":6 \
            --button="<span color='${CYAN}'>󰋗 Doctor</span>":7 \
            --button="<span color='${CYAN}'>󰊠 HW Detect</span>":8 \
            --button="<span color='${GRAY}'>gtk-go-back</span>":99 \
            2>/dev/null
        local rc=$?
        case $rc in
            1) foot --app-id jarvis-dev -e bash -c "cd ${PROJECT_DIR} && jarvis dev; exec bash" && return ;;
            2) run_in_terminal "Voice" "cd ${PROJECT_DIR} && jarvis voice 2>&1" ;;
            3) run_in_terminal "STT" "cd ${PROJECT_DIR} && jarvis stt 2>&1" ;;
            4) menu_tts_test ;;
            5) menu_rag_search ;;
            6) run_in_terminal "Memory Vault" "cd ${PROJECT_DIR} && jarvis vault list 2>&1" ;;
            7) run_in_terminal "Doctor" "cd ${PROJECT_DIR} && jarvis doctor 2>&1" ;;
            8) run_in_terminal "HW Detect" "cd ${PROJECT_DIR} && jarvis hwdetect 2>&1" ;;
            99|0|*) return ;;
        esac
    done
}

menu_tts_test() {
    local result=$($YAD --title="TTS Test" \
        --width=400 --height=120 \
        --entry \
        --text="<span color='${CYAN}'>󰕾 Texto para TTS (Kokoro):</span>" \
        --button="<span color='${CYAN}'>󰐊 Speak</span>":1 \
        --button="<span color='${GRAY}'>gtk-cancel</span>":0 \
        2>/dev/null)
    local rc=$?
    if [ $rc -eq 1 ] && [ -n "$result" ]; then
        run_in_terminal "TTS" "cd ${PROJECT_DIR} && jarvis speak '${result}' 2>&1"
    fi
}

menu_rag_search() {
    local result=$($YAD --title="RAG Search" \
        --width=400 --height=120 \
        --entry \
        --text="<span color='${CYAN}'>󰓫 Buscar no código (semântico):</span>" \
        --button="<span color='${CYAN}'>󰍝 Search</span>":1 \
        --button="<span color='${GRAY}'>gtk-cancel</span>":0 \
        2>/dev/null)
    local rc=$?
    if [ $rc -eq 1 ] && [ -n "$result" ]; then
        run_in_terminal "RAG Search" "cd ${PROJECT_DIR} && jarvis rag '${result}' 2>&1"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: Dev Tools
# ═══════════════════════════════════════════════════════════════════════════

menu_devtools() {
    while true; do
        $YAD --title="Dev Tools" \
            --width=560 --height=450 \
            --text="<span font='14' color='${CYAN}'>󰈙 Dev Tools</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Build</b></span>

  <span color='${CYAN}'>󰑓</span> Rebuild       <span color='${DIM}'>nixos-rebuild switch</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Test</b></span>

  <span color='${CYAN}'>󰗀</span> Pytest        <span color='${DIM}'>suite de testes</span>
  <span color='${CYAN}'>󰗀</span> Pytest Verbose <span color='${DIM}'>detalhado</span>
  <span color='${CYAN}'>󰈙</span> Benchmark     <span color='${DIM}'>performance</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Quality</b></span>

  <span color='${CYAN}'>󰈙</span> Lint          <span color='${DIM}'>ruff check</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Git</b></span>

  <span color='${CYAN}'>󰊢</span> Status        <span color='${DIM}'>git status</span>
  <span color='${CYAN}'>󰊢</span> Log           <span color='${DIM}'>últimos commits</span>
  <span color='${CYAN}'>󰊢</span> Diff          <span color='${DIM}'>mudanças pendentes</span>" \
            --text-align=left \
            --button="<span color='${CYAN}'>󰑓 Rebuild</span>":1 \
            --button="<span color='${CYAN}'>󰗀 Tests</span>":2 \
            --button="<span color='${CYAN}'>󰗀 Tests Verbose</span>":3 \
            --button="<span color='${CYAN}'>󰈙 Benchmark</span>":4 \
            --button="<span color='${CYAN}'>󰈙 Lint</span>":5 \
            --button="<span color='${CYAN}'>󰊢 Git Status</span>":6 \
            --button="<span color='${CYAN}'>󰊢 Git Log</span>":7 \
            --button="<span color='${GRAY}'>gtk-go-back</span>":99 \
            2>/dev/null
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
# Menu: Tools
# ═══════════════════════════════════════════════════════════════════════════

menu_tools() {
    while true; do
        local oc=$(which opencode 2>/dev/null && echo "${GREEN}installed" || echo "${RED}not found")
        local ai=$(which aider 2>/dev/null && echo "${GREEN}installed" || echo "${RED}not found")
        local pi_bin=$(which pi 2>/dev/null && echo "${GREEN}installed" || echo "${RED}not found")

        $YAD --title="Tools" \
            --width=560 --height=380 \
            --text="<span font='14' color='${CYAN}'>󰋖 External Tools</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Code Editors (CLI)</b></span>

  <span color='${CYAN}'>󰈙</span> opencode   <span color='${oc}'>
  <span color='${CYAN}'>󰈙</span> aider      <span color='${ai}'>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>AI Agents</b></span>

  <span color='${CYAN}'>󰋗</span> pi agent   <span color='${pi_bin}'>
  <span color='${CYAN}'>󰨞</span> roo dev    <span color='${DIM}'>VSCode extension</span>" \
            --text-align=left \
            --button="<span color='${CYAN}'>󰈙 opencode</span>":1 \
            --button="<span color='${CYAN}'>󰈙 aider</span>":2 \
            --button="<span color='${CYAN}'>󰋗 pi</span>":3 \
            --button="<span color='${CYAN}'>󰨞 VSCode</span>":4 \
            --button="<span color='${CYAN}'>󰅶 Terminal</span>":5 \
            --button="<span color='${GRAY}'>gtk-go-back</span>":99 \
            2>/dev/null
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
        local tavily_s="offline"
        curl -s --connect-timeout 2 http://localhost:3000/health >/dev/null 2>&1 && tavily_s="online"
        local nixos_s="offline"
        curl -s --connect-timeout 2 http://localhost:3001/health >/dev/null 2>&1 && nixos_s="online"

        $YAD --title="MCPs" \
            --width=560 --height=340 \
            --text="<span font='14' color='${CYAN}'>󰖟 MCP Servers</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Web Search</b></span>

  <span color='${CYAN}'>󰖟</span> tavily-search   <span color='$([ "$tavily_s" = "online" ] && echo $GREEN || echo $RED)'>${tavily_s}</span>
  <span color='${DIM}'>Busca web, extração de URLs, pesquisa técnica</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>NixOS</b></span>

  <span color='${CYAN}'>󰖟</span> mcp-nixos       <span color='$([ "$nixos_s" = "online" ] && echo $GREEN || echo $RED)'>${nixos_s}</span>
  <span color='${DIM}'>Consultar packages, versões, opções do nixpkgs</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${DIM}'>Config: ~/.config/Code/.../roo-cline/settings/mcp_settings.json</span>" \
            --text-align=left \
            --button="<span color='${CYAN}'>󰖟 Test Tavily</span>":1 \
            --button="<span color='${CYAN}'>󰖟 Test NixOS</span>":2 \
            --button="<span color='${CYAN}'>󰉋 Edit Config</span>":3 \
            --button="<span color='${GRAY}'>gtk-go-back</span>":99 \
            2>/dev/null
        local rc=$?
        case $rc in
            1) run_in_terminal "Tavily" "echo 'Testing tavily MCP...' && curl -s http://localhost:3000 2>&1 || echo 'not running'" ;;
            2) run_in_terminal "NixOS" "echo 'Testing mcp-nixos...' && curl -s http://localhost:3001 2>&1 || echo 'not running'" ;;
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
        local waybar_running=$(ps aux | grep -c "[w]aybar" || echo 0)

        $YAD --title="Waybar" \
            --width=560 --height=350 \
            --text="<span font='14' color='${CYAN}'>󰍹 Waybar</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Status</b></span>

  <span color='${CYAN}'>󰍹</span> Process: <span color='$([ "$waybar_running" -gt 0 ] && echo $GREEN || echo $RED)'>$([ "$waybar_running" -gt 0 ] && echo running || echo stopped)</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Módulos Ativos</b></span>

  <span color='${CYAN}'>󰋗</span> custom/jarvis  <span color='${DIM}'>status AI</span>
  <span color='${CYAN}'>󰍛</span> custom/cpu     <span color='${DIM}'>CPU usage</span>
  <span color='${CYAN}'>󰘚</span> custom/memory  <span color='${DIM}'>RAM usage</span>
  <span color='${CYAN}'>󰢮</span> custom/gpu     <span color='${DIM}'>GPU NVIDIA</span>
  <span color='${CYAN}'>󰢮</span> custom/igpu    <span color='${DIM}'>iGPU Intel</span>
  <span color='${CYAN}'>󰉋</span> custom/files   <span color='${DIM}'>disk</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${DIM}'>Config: home-manager/modules/waybar.nix</span>" \
            --text-align=left \
            --button="<span color='${CYAN}'>󰉋 Edit Config</span>":1 \
            --button="<span color='${CYAN}'>󰑓 Reload</span>":2 \
            --button="<span color='${CYAN}'>󰋗 Test Jarvis</span>":3 \
            --button="<span color='${GRAY}'>gtk-go-back</span>":99 \
            2>/dev/null
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
        local store_size=$(nix-store --query --size /nix/store 2>/dev/null | awk '{printf "%.1f GB", $1/1024/1024/1024}' || echo "?")

        $YAD --title="Maintenance" \
            --width=560 --height=380 \
            --text="<span font='14' color='${CYAN}'>�Ẓ Maintenance</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Nix Store</b></span>

  <span color='${CYAN}'>󰊞</span> Size: <span color='${WHITE}'>${store_size}</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Actions</b></span>

  <span color='${CYAN}'>�Ẓ</span> Garbage Collect <span color='${DIM}'>limpar store antigo</span>
  <span color='${CYAN}'>󰊢</span> Flake Update    <span color='${DIM}'>atualizar inputs</span>
  <span color='${CYAN}'>󰈙</span> Clean Cache     <span color='${DIM}'>remover __pycache__</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Logs</b></span>

  <span color='${CYAN}'>󰈙</span> AI Logs         <span color='${DIM}'>llama-cpp + qdrant</span>
  <span color='${CYAN}'>󰈙</span> Gaming Logs     <span color='${DIM}'>gaming watcher</span>" \
            --text-align=left \
            --button="<span color='${RED}'>�Ẓ GC Store</span>":1 \
            --button="<span color='${ORANGE}'>󰊢 Flake Update</span>":2 \
            --button="<span color='${CYAN}'>󰈙 Clean Cache</span>":3 \
            --button="<span color='${CYAN}'>󰈙 AI Logs</span>":4 \
            --button="<span color='${CYAN}'>󰈙 Gaming Logs</span>":5 \
            --button="<span color='${GRAY}'>gtk-go-back</span>":99 \
            2>/dev/null
        local rc=$?
        case $rc in
            1) run_in_terminal "Nix GC" "sudo nix-collect-garbage -d 2>&1" ;;
            2) run_in_terminal "Flake Update" "cd ${PROJECT_DIR} && nix flake update 2>&1" ;;
            3) run_in_terminal "Clean" "find ${PROJECT_DIR} -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; echo 'Done'" ;;
            4) run_in_terminal "AI Logs" "journalctl -u llama-cpp-server -u qdrant --no-pager -n 100 2>&1" ;;
            5) run_in_terminal "Gaming Logs" "journalctl -u jarvis-gaming-watcher --no-pager -n 50 2>&1" ;;
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
    local gpu=$(gpu_info)
    local ram=$(ram_info)
    local llm=$(llm_status)

    local icon="🟢"
    [ "$llama" != "active" ] && icon="🔴"

    notify-send -t 5000 -i "dialog-information" \
        "<b>NixOS-AI Status</b>" \
        "${icon} llama-cpp: ${llama} (${llm})
🟢 qdrant: ${qdrant}
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
        echo "NixOS-AI Launcher v3.0"
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
