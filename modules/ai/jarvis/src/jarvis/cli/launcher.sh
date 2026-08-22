#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# NixOS-AI Launcher v3.1 — Cyberpunk GUI
# Yad + Nerd Font icons, sem markup Pango nos botões
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail

YAD="${YAD:-yad}"
PROJECT_DIR="${PROJECT_DIR:-$HOME/projects/nixos-ai}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSS_FILE="${SCRIPT_DIR}/launcher-cyberpunk.css"

# GTK3 CSS cyberpunk
if [ -f "$CSS_FILE" ]; then
    export GTK_CSS_PROVIDER="$CSS_FILE"
fi

# Cores Pango (só no --text, NUNCA nos botões)
CYAN="#00ffff"
GREEN="#50FA7B"
RED="#FF5555"
GRAY="#888888"
WHITE="#ffffff"
DIM="#666666"
ORANGE="#FFB86C"

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

notify() { notify-send -t 3000 "${1}" "${2}" 2>/dev/null || true; }

run_in_terminal() {
    local title="${1:-Terminal}"
    local cmd="${2:-bash}"
    foot --app-id "floating_${title}" -e bash -c "
        echo -e '\033[0;36m═══ ${title} ═══\033[0m'
        eval '${cmd}'
        echo ''
        echo -e '\033[0;90m─── Enter p/ fechar ───\033[0m'
        read
    " &
}

svc() { systemctl --user is-active "$1" 2>/dev/null || systemctl is-active "$1" 2>/dev/null || echo "inactive"; }
dot() {
    local s; s=$(svc "$1")
    [ "$s" = "active" ] && echo "<span color='${GREEN}'>●</span>" || echo "<span color='${RED}'>●</span>"
}
dot_plain() {
    local s; s=$(svc "$1")
    [ "$s" = "active" ] && echo "●" || echo "○"
}

gpu_info()  { nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo "N/A"; }
igpu_info() {
    local cur=$(cat /sys/class/drm/card1/gt_cur_freq_mhz 2>/dev/null || echo 0)
    local max=$(cat /sys/class/drm/card1/gt_max_freq_mhz 2>/dev/null || echo 1500)
    local pct=0; [ "$max" -gt 0 ] 2>/dev/null && pct=$(( cur * 100 / max ))
    echo "${cur}/${max}MHz (${pct}%)"
}
cpu_info() {
    local u=$(top -bn1 | grep "Cpu(s)" | awk '{print int($2+$4)}')
    local t=$(cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | head -1 | awk '{print int($1/1000)}' 2>/dev/null || echo "?")
    echo "${u}% @ ${t}°C"
}
ram_info()  { free -h | awk '/^Mem:/ {printf "%s/%s (%.0f%%)", $3, $2, $3/$2*100}'; }
vram_info() { nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null | awk -F', ' '{printf "%s/%s", $1, $2}' || echo "N/A"; }
disk_info() { df -h / | awk 'NR==2 {printf "%s/%s (%s)", $3, $2, $5}'; }

llm_slots() {
    curl -s --connect-timeout 2 http://localhost:8080/slots 2>/dev/null | \
        python3 -c "
import sys,json
try:
    s=json.load(sys.stdin)
    b=sum(1 for x in s if x.get('is_processing'))
    c=sum(x.get('n_prompt_tokens',0) for s in s for x in [s])
    m=sum(x.get('n_ctx',0) for s in s for x in [s])
    p=int(c/m*100) if m>0 else 0
    print(f'{b}/{len(s)} slots, ctx {p}%')
except: print('?')
" 2>/dev/null || echo "?"
}

llm_health() {
    curl -s --connect-timeout 2 http://localhost:8080/health 2>/dev/null | grep -q '"ok"\|"healthy"' && echo "online" || echo "offline"
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu helpers — rods menu_yad com --text-info + scroll
# ═══════════════════════════════════════════════════════════════════════════

# menu_run: abre janela Yad com texto + botões
# SEM --text-info (que fecha com EOF do pipe)
# Usa --text direto — maior janela se precisar
MENU_RC=0
MENU_CLICKED=""

menu_run() {
    local title="$1"; shift
    local text="$1"; shift
    local buttons=()
    for arg in "$@"; do
        buttons+=(--button="$arg")
    done

    MENU_CLICKED=$($YAD \
        --title="$title" \
        --text="$text" \
        --text-align=left \
        --width=580 --height=640 \
        --font="JetBrainsMono Nerd Font 12" \
        "${buttons[@]}" \
        2>/dev/null) || true
    MENU_RC=$?
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu Principal
# ═══════════════════════════════════════════════════════════════════════════

main_menu() {
    while true; do
        local txt="<span font='16' color='${CYAN}'>▸ NixOS-AI</span>  <span font='10' color='${DIM}'>v3.1</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  $(dot llama-cpp-server) <span font='11' color='${WHITE}'>llama.cpp</span>   <span color='$([ "$(llm_health)" = "online" ] && echo $GREEN || echo $RED)'>$(llm_health)</span>  <span color='${DIM}'>$(llm_slots)</span>
  $(dot qdrant) <span font='11' color='${WHITE}'>qdrant</span>      <span color='${GREEN}'>$(svc qdrant)</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${CYAN}'>󰍛</span> CPU:  <span color='${WHITE}'>$(cpu_info)</span>
  <span color='${CYAN}'>󰘚</span> RAM:  <span color='${WHITE}'>$(ram_info)</span>
  <span color='${CYAN}'>󰢮</span> GPU:  <span color='${WHITE}'>$(gpu_info)</span>
  <span color='${CYAN}'>󰢮</span> VRAM: <span color='${WHITE}'>$(vram_info)</span>
  <span color='${CYAN}'>󰉋</span> Disk: <span color='${WHITE}'>$(disk_info)</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${CYAN}'>󰊠</span> <b>System</b>      <span color='${DIM}'>hardware, monitoramento</span>
  <span color='${CYAN}'>󰒓</span> <b>Services</b>    <span color='${DIM}'>gerenciar serviços AI</span>
  <span color='${CYAN}'>󰋗</span> <b>Jarvis</b>      <span color='${DIM}'>dev CLI, voice, RAG</span>
  <span color='${CYAN}'>󰈙</span> <b>Dev Tools</b>   <span color='${DIM}'>build, test, lint</span>
  <span color='${CYAN}'>󰋖</span> <b>Tools</b>       <span color='${DIM}'>opencode, aider, pi</span>
  <span color='${CYAN}'>󰖟</span> <b>MCPs</b>        <span color='${DIM}'>tavily, nixos</span>
  <span color='${CYAN}'>󰍹</span> <b>Waybar</b>      <span color='${DIM}'>configuração</span>
  <span color='${CYAN}'>󰝰</span> <b>Maintenance</b> <span color='${DIM}'>GC, logs, cache</span>"

        menu_run "NixOS-AI" "$txt" \
            "󰊠 System:1" \
            "󰒓 Services:2" \
            "󰋗 Jarvis:3" \
            "󰈙 DevTools:4" \
            "󰋖 Tools:5" \
            "󰖟 MCPs:6" \
            "󰍹 Waybar:7" \
            "󰝰 Maintenance:8" \
            "gtk-quit:0"

        case $MENU_RC in
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
        local txt="<span font='14' color='${CYAN}'>󰊠 System Status</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Hardware</b></span>

  <span color='${CYAN}'>󰍛</span> CPU:    <span color='${WHITE}'>$(cpu_info)</span>
  <span color='${CYAN}'>󰢮</span> GPU:    <span color='${WHITE}'>$(gpu_info)</span>
  <span color='${CYAN}'>󰢮</span> iGPU:   <span color='${WHITE}'>$(igpu_info)</span>
  <span color='${CYAN}'>󰘚</span> RAM:    <span color='${WHITE}'>$(ram_info)</span>
  <span color='${CYAN}'>󰢮</span> VRAM:   <span color='${WHITE}'>$(vram_info)</span>
  <span color='${CYAN}'>󰉋</span> Disk:   <span color='${WHITE}'>$(disk_info)</span>
  <span color='${CYAN}'>󰅶</span> Kernel: <span color='${WHITE}'>$(uname -r)</span>
  <span color='${CYAN}'>󰅒</span> Uptime: <span color='${WHITE}'>$(uptime -p | sed 's/up //')</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Services</b></span>

  $(dot llama-cpp-server) llama-cpp-server     <span color='${DIM}'>$(llm_health) · $(llm_slots)</span>
  $(dot llama-cpp-embeddings) llama-cpp-embeddings
  $(dot llama-cpp-rerank) llama-cpp-rerank
  $(dot qdrant) qdrant

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Endpoints</b></span>

  <span color='${DIM}'>LLM:        http://localhost:8080/v1</span>
  <span color='${DIM}'>Embeddings: http://localhost:8081/v1</span>
  <span color='${DIM}'>Qdrant:     http://localhost:6333</span>"

        menu_run "System" "$txt" \
            "  Refresh:1" \
            "󰍛 nvidia-smi:2" \
            "󰈙 htop:3" \
            "gtk-go-back:99"

        case $MENU_RC in
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
        local txt="<span font='14' color='${CYAN}'>󰒓 Service Management</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>AI Core</b></span>

  $(dot llama-cpp-server) llama-cpp-server     <span color='${DIM}'>$(svc llama-cpp-server)</span>
  $(dot llama-cpp-embeddings) llama-cpp-embeddings <span color='${DIM}'>$(svc llama-cpp-embeddings)</span>
  $(dot llama-cpp-rerank) llama-cpp-rerank     <span color='${DIM}'>$(svc llama-cpp-rerank)</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Infrastructure</b></span>

  $(dot qdrant) qdrant              <span color='${DIM}'>$(svc qdrant)</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Load</b></span>

  <span color='${CYAN}'>󰊠</span> <span color='${WHITE}'>$(llm_slots)</span>"

        menu_run "Services" "$txt" \
            "󰑓 Restart llama-cpp:1" \
            "󰑓 Restart embeddings:2" \
            "󰑓 Restart rerank:3" \
            "󰑓 Restart qdrant:4" \
            "󰑓 Restart ALL:5" \
            "󰈙 Logs:6" \
            "gtk-go-back:99"

        case $MENU_RC in
            1) sudo systemctl restart llama-cpp-server && notify "OK" "llama-cpp restarted" ;;
            2) sudo systemctl restart llama-cpp-embeddings && notify "OK" "embeddings restarted" ;;
            3) sudo systemctl restart llama-cpp-rerank && notify "OK" "rerank restarted" ;;
            4) sudo systemctl restart qdrant && notify "OK" "qdrant restarted" ;;
            5) sudo systemctl restart llama-cpp-server llama-cpp-embeddings llama-cpp-rerank qdrant && notify "OK" "All restarted" ;;
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
        local txt="<span font='14' color='${CYAN}'>󰋗 Jarvis AI</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Development</b></span>

  <span color='${CYAN}'>󰈙</span> Dev CLI      <span color='${DIM}'>REPL interativo de código</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Voice Pipeline</b></span>

  <span color='${CYAN}'>󰍬</span> Voice        <span color='${DIM}'>STT → roteador → TTS</span>
  <span color='${CYAN}'>󰈙</span> STT          <span color='${DIM}'>faster-whisper</span>
  <span color='${CYAN}'>󰕾</span> TTS          <span color='${DIM}'>Kokoro-82M</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Intelligence</b></span>

  <span color='${CYAN}'>󰓫</span> RAG Index    <span color='${DIM}'>indexar codebase</span>
  <span color='${CYAN}'>󰓫</span> RAG Search   <span color='${DIM}'>busca semântica</span>
  <span color='${CYAN}'>󰓫</span> Intent       <span color='${DIM}'>classificação</span>
  <span color='${CYAN}'>󰓫</span> Memory Vault <span color='${DIM}'>resumo episódico</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Diagnostics</b></span>

  <span color='${CYAN}'>󰋗</span> Doctor       <span color='${DIM}'>health check</span>
  <span color='${CYAN}'>󰊠</span> HWDetect     <span color='${DIM}'>detectar hardware</span>
  <span color='${CYAN}'>󰍹</span> Waybar       <span color='${DIM}'>status widget</span>"

        menu_run "Jarvis" "$txt" \
            "󰈙 Dev CLI:1" \
            "󰍬 Voice:2" \
            "󰈙 STT Only:3" \
            "󰕾 TTS Test:4" \
            "󰓫 RAG Search:5" \
            "󰓫 Memory:6" \
            "󰋗 Doctor:7" \
            "󰊠 HW Detect:8" \
            "gtk-go-back:99"

        case $MENU_RC in
            1) foot --app-id jarvis-dev -e bash -c "cd ${PROJECT_DIR} && jarvis dev; exec bash" && return ;;
            2) run_in_terminal "Voice" "cd ${PROJECT_DIR} && jarvis voice 2>&1" ;;
            3) run_in_terminal "STT" "cd ${PROJECT_DIR} && jarvis stt 2>&1" ;;
            4) menu_tts_test ;;
            5) menu_rag_search ;;
            6) run_in_terminal "Memory" "cd ${PROJECT_DIR} && jarvis vault list 2>&1" ;;
            7) run_in_terminal "Doctor" "cd ${PROJECT_DIR} && jarvis doctor 2>&1" ;;
            8) run_in_terminal "HW Detect" "cd ${PROJECT_DIR} && jarvis hwdetect 2>&1" ;;
            99|0|*) return ;;
        esac
    done
}

menu_tts_test() {
    local result
    result=$($YAD --title="TTS Test" --width=400 --height=120 \
        --entry --text="Texto para TTS:" \
        --button="Speak:1" --button="gtk-cancel:0" 2>/dev/null)
    [ $? -eq 1 ] && [ -n "$result" ] && run_in_terminal "TTS" "cd ${PROJECT_DIR} && jarvis speak '${result}' 2>&1"
}

menu_rag_search() {
    local result
    result=$($YAD --title="RAG Search" --width=400 --height=120 \
        --entry --text="Buscar no código:" \
        --button="Search:1" --button="gtk-cancel:0" 2>/dev/null)
    [ $? -eq 1 ] && [ -n "$result" ] && run_in_terminal "RAG" "cd ${PROJECT_DIR} && jarvis rag '${result}' 2>&1"
}

# ═══════════════════════════════════════════════════════════════════════════
# Menu: Dev Tools
# ═══════════════════════════════════════════════════════════════════════════

menu_devtools() {
    while true; do
        local txt="<span font='14' color='${CYAN}'>󰈙 Dev Tools</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Build</b></span>

  <span color='${CYAN}'>󰑓</span> Rebuild       <span color='${DIM}'>nixos-rebuild switch</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Test</b></span>

  <span color='${CYAN}'>󰗀</span> Pytest        <span color='${DIM}'>suite de testes</span>
  <span color='${CYAN}'>󰗀</span> Pytest Verbose <span color='${DIM}'>detalhado</span>
  <span color='${CYAN}'>󰈙</span> Benchmark     <span color='${DIM}'>performance</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Quality</b></span>

  <span color='${CYAN}'>󰈙</span> Lint          <span color='${DIM}'>ruff check</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Git</b></span>

  <span color='${CYAN}'>󰊢</span> Status        <span color='${DIM}'>git status</span>
  <span color='${CYAN}'>󰊢</span> Log           <span color='${DIM}'>últimos commits</span>
  <span color='${CYAN}'>󰊢</span> Diff          <span color='${DIM}'>mudanças pendentes</span>"

        menu_run "DevTools" "$txt" \
            "󰑓 Rebuild:1" \
            "󰗀 Tests:2" \
            "󰗀 Tests Verbose:3" \
            "󰈙 Benchmark:4" \
            "󰈙 Lint:5" \
            "󰊢 Git Status:6" \
            "󰊢 Git Log:7" \
            "gtk-go-back:99"

        case $MENU_RC in
            1) run_in_terminal "Rebuild" "cd ${PROJECT_DIR} && bash rebuild-host.sh 2>&1" ;;
            2) run_in_terminal "Pytest" "cd ${PROJECT_DIR} && nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q 2>&1" ;;
            3) run_in_terminal "Pytest" "cd ${PROJECT_DIR} && nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -v 2>&1" ;;
            4) run_in_terminal "Benchmark" "cd ${PROJECT_DIR} && bash benchmark.sh --warmup --repeat 3 2>&1" ;;
            5) run_in_terminal "Lint" "cd ${PROJECT_DIR} && nix develop --command ruff check modules/ai/jarvis/src/ 2>&1" ;;
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
        local oc="not found"; which opencode &>/dev/null && oc="installed"
        local ai="not found"; which aider &>/dev/null && ai="installed"
        local pi_b="not found"; which pi &>/dev/null && pi_b="installed"

        local txt="<span font='14' color='${CYAN}'>󰋖 External Tools</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Code Editors (CLI)</b></span>

  <span color='${CYAN}'>󰈙</span> opencode   <span color='$([ "$oc" = "installed" ] && echo $GREEN || echo $RED)'>${oc}</span>
  <span color='${CYAN}'>󰈙</span> aider      <span color='$([ "$ai" = "installed" ] && echo $GREEN || echo $RED)'>${ai}</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>AI Agents</b></span>

  <span color='${CYAN}'>󰋗</span> pi agent   <span color='$([ "$pi_b" = "installed" ] && echo $GREEN || echo $RED)'>${pi_b}</span>
  <span color='${CYAN}'>󰨞</span> roo dev    <span color='${DIM}'>VSCode extension</span>"

        menu_run "Tools" "$txt" \
            "󰈙 opencode:1" \
            "󰈙 aider:2" \
            "󰋗 pi:3" \
            "󰨞 VSCode:4" \
            "󰅶 Terminal:5" \
            "gtk-go-back:99"

        case $MENU_RC in
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
        local tav="offline"; curl -s --connect-timeout 2 http://localhost:3000/health >/dev/null 2>&1 && tav="online"
        local nix="offline"; curl -s --connect-timeout 2 http://localhost:3001/health >/dev/null 2>&1 && nix="online"

        local txt="<span font='14' color='${CYAN}'>󰖟 MCP Servers</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Web Search</b></span>

  <span color='${CYAN}'>󰖟</span> tavily-search   <span color='$([ "$tav" = "online" ] && echo $GREEN || echo $RED)'>${tav}</span>
  <span color='${DIM}'>Busca web, extração de URLs</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>NixOS</b></span>

  <span color='${CYAN}'>󰖟</span> mcp-nixos       <span color='$([ "$nix" = "online" ] && echo $GREEN || echo $RED)'>${nix}</span>
  <span color='${DIM}'>Packages, versões, opções do nixpkgs</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${DIM}'>Config: ~/.config/Code/.../roo-cline/settings/mcp_settings.json</span>"

        menu_run "MCPs" "$txt" \
            "󰖟 Test Tavily:1" \
            "󰖟 Test NixOS:2" \
            "󰉋 Edit Config:3" \
            "gtk-go-back:99"

        case $MENU_RC in
            1) run_in_terminal "Tavily" "curl -s http://localhost:3000 2>&1 || echo 'not running'" ;;
            2) run_in_terminal "NixOS" "curl -s http://localhost:3001 2>&1 || echo 'not running'" ;;
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
        local wb="stopped"; pgrep -x waybar &>/dev/null && wb="running"

        local txt="<span font='14' color='${CYAN}'>󰍹 Waybar</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Status</b></span>

  <span color='${CYAN}'>󰍹</span> Process: <span color='$([ "$wb" = "running" ] && echo $GREEN || echo $RED)'>${wb}</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Módulos Ativos</b></span>

  <span color='${CYAN}'>󰋗</span> custom/jarvis  <span color='${DIM}'>status AI</span>
  <span color='${CYAN}'>󰍛</span> custom/cpu     <span color='${DIM}'>CPU usage</span>
  <span color='${CYAN}'>󰘚</span> custom/memory  <span color='${DIM}'>RAM usage</span>
  <span color='${CYAN}'>󰢮</span> custom/gpu     <span color='${DIM}'>GPU NVIDIA</span>
  <span color='${CYAN}'>󰢮</span> custom/igpu    <span color='${DIM}'>iGPU Intel</span>
  <span color='${CYAN}'>󰉋</span> custom/files   <span color='${DIM}'>disk</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${DIM}'>Config: home-manager/modules/waybar.nix</span>"

        menu_run "Waybar" "$txt" \
            "󰉋 Edit Config:1" \
            "󰑓 Reload:2" \
            "󰋗 Test Jarvis:3" \
            "gtk-go-back:99"

        case $MENU_RC in
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
        local sz=$(nix-store --query --size /nix/store 2>/dev/null | awk '{printf "%.1f GB", $1/1024/1024/1024}' || echo "?")

        local txt="<span font='14' color='${CYAN}'>󰝰 Maintenance</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Nix Store</b></span>

  <span color='${CYAN}'>󰊞</span> Size: <span color='${WHITE}'>${sz}</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Actions</b></span>

  <span color='${CYAN}'>󰝰</span> Garbage Collect <span color='${DIM}'>limpar store antigo</span>
  <span color='${CYAN}'>󰊢</span> Flake Update    <span color='${DIM}'>atualizar inputs</span>
  <span color='${CYAN}'>󰈙</span> Clean Cache     <span color='${DIM}'>remover __pycache__</span>

<span color='${GRAY}'>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</span>

  <span color='${WHITE}'><b>Logs</b></span>

  <span color='${CYAN}'>󰈙</span> AI Logs         <span color='${DIM}'>llama-cpp + qdrant</span>
  <span color='${CYAN}'>󰈙</span> Gaming Logs     <span color='${DIM}'>gaming watcher</span>"

        menu_run "Maintenance" "$txt" \
            "󰝰 GC Store:1" \
            "󰊢 Flake Update:2" \
            "󰈙 Clean Cache:3" \
            "󰈙 AI Logs:4" \
            "󰈙 Gaming Logs:5" \
            "gtk-go-back:99"

        case $MENU_RC in
            1) run_in_terminal "Nix GC" "sudo nix-collect-garbage -d 2>&1" ;;
            2) run_in_terminal "Flake" "cd ${PROJECT_DIR} && nix flake update 2>&1" ;;
            3) run_in_terminal "Clean" "find ${PROJECT_DIR} -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; echo Done" ;;
            4) run_in_terminal "AI Logs" "journalctl -u llama-cpp-server -u qdrant --no-pager -n 100 2>&1" ;;
            5) run_in_terminal "Gaming" "journalctl -u jarvis-gaming-watcher --no-pager -n 50 2>&1" ;;
            99|0|*) return ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════════════
# Quick Status
# ═══════════════════════════════════════════════════════════════════════════

quick_status() {
    local llama=$(svc llama-cpp-server)
    local llm=$(llm_health)
    local gpu=$(gpu_info)
    local ram=$(ram_info)
    local icon="●"; [ "$llama" != "active" ] && icon="○"
    notify-send -t 5000 "NixOS-AI Status" \
"${icon} llama-cpp: ${llama} (${llm})
● qdrant: $(svc qdrant)
 GPU: ${gpu}
 RAM: ${ram}" 2>/dev/null || true
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
        echo "NixOS-AI Launcher v3.1"
        echo "Usage: launcher.sh [--status|--dev|--services|--hardware|--tools]"
        echo "Keybinding: SUPER+A"
        ;;
    *)            main_menu ;;
esac
