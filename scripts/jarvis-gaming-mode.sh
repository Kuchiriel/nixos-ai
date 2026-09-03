#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# JARVIS GAMING MODE
#
# Stop/start all Jarvis services for gaming.
# Usage:
#   jarvis-gaming-mode.sh stop    # Stop all services (for gaming)
#   jarvis-gaming-mode.sh start   # Start all services (after gaming)
#   jarvis-gaming-mode.sh status  # Show current status
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

# Services to stop for gaming (heavy, compete for GPU/CPU)
GAMING_SERVICES=(
    "llama-cpp-server"
    "llama-cpp-embeddings"
    "llama-cpp-rerank"
    "llama-fan-control"
    "nightwatch"
)

# User services to stop
USER_SERVICES=(
    "jarvis-telegram"
    "jarvis-wakeword"
)

stop_all() {
    echo "=== Stopping Jarvis services for gaming ==="
    
    # Stop system services
    for svc in "${GAMING_SERVICES[@]}"; do
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            echo "Stopping $svc..."
            sudo systemctl stop "$svc"
        fi
    done
    
    # Stop user services
    for svc in "${USER_SERVICES[@]}"; do
        if systemctl --user is-active --quiet "$svc" 2>/dev/null; then
            echo "Stopping $svc (user)..."
            systemctl --user stop "$svc"
        fi
    done
    
    echo "=== All services stopped ==="
    echo "GPU VRAM freed:"
    nvidia-smi --query-gpu=memory.used,memory.total --format=csv 2>/dev/null
}

start_all() {
    echo "=== Starting Jarvis services ==="
    
    # Start system services
    for svc in "${GAMING_SERVICES[@]}"; do
        if ! systemctl is-active --quiet "$svc" 2>/dev/null; then
            echo "Starting $svc..."
            sudo systemctl start "$svc"
        fi
    done
    
    # Start user services
    for svc in "${USER_SERVICES[@]}"; do
        if ! systemctl --user is-active --quiet "$svc" 2>/dev/null; then
            echo "Starting $svc (user)..."
            systemctl --user start "$svc"
        fi
    done
    
    echo "=== All services started ==="
}

show_status() {
    echo "=== Jarvis Services Status ==="
    echo ""
    echo "System services:"
    for svc in "${GAMING_SERVICES[@]}"; do
        status=$(systemctl is-active "$svc" 2>/dev/null || echo "inactive")
        printf "  %-25s %s\n" "$svc" "$status"
    done
    echo ""
    echo "User services:"
    for svc in "${USER_SERVICES[@]}"; do
        status=$(systemctl --user is-active "$svc" 2>/dev/null || echo "inactive")
        printf "  %-25s %s\n" "$svc" "$status"
    done
    echo ""
    echo "GPU:"
    nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv 2>/dev/null
}

case "${1:-status}" in
    stop)
        stop_all
        ;;
    start)
        start_all
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: $0 {stop|start|status}"
        exit 1
        ;;
esac
