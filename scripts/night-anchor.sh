#!/usr/bin/env bash
# ═══ night-anchor.sh ═══
# Keeps a CLI session alive during overnight work.
# Saves state, logs progress, and can resume from where it left off.
#
# Usage:
#   ./scripts/night-anchor.sh start    # Start anchor (background heartbeat)
#   ./scripts/night-anchor.sh status   # Check if anchor is alive
#   ./scripts/night-anchor.sh log "msg" # Log a progress message
#   ./scripts/night-anchor.sh stop     # Stop anchor
#   ./scripts/night-anchor.sh resume   # Show last session state
#
# The anchor writes a heartbeat every 60s to prevent session timeout.
# It also saves the current working directory and a state file.

set -euo pipefail

ANCHOR_DIR="$HOME/.local/state/jarvis"
ANCHOR_PID="$ANCHOR_DIR/anchor.pid"
ANCHOR_LOG="$ANCHOR_DIR/anchor.log"
ANCHOR_STATE="$ANCHOR_DIR/anchor-state.json"
HEARTBEAT_INTERVAL=60

mkdir -p "$ANCHOR_DIR"

case "${1:-help}" in
    start)
        if [[ -f "$ANCHOR_PID" ]] && kill -0 "$(cat "$ANCHOR_PID")" 2>/dev/null; then
            echo "⚠️  Anchor already running (PID $(cat "$ANCHBEAT_PID"))"
            exit 1
        fi

        echo "🚀 Starting night anchor..."

        # Save initial state
        cat > "$ANCHOR_STATE" <<EOF
{
  "started_at": "$(date -Iseconds)",
  "cwd": "$(pwd)",
  "git_branch": "$(git branch --show-current 2>/dev/null || echo 'unknown')",
  "git_hash": "$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')",
  "tasks_completed": 0,
  "last_activity": "$(date -Iseconds)"
}
EOF

        # Start heartbeat in background
        (
            while true; do
                echo "$(date -Iseconds) heartbeat" >> "$ANCHOR_LOG"
                sleep "$HEARTBEAT_INTERVAL"
            done
        ) &
        HEARTBEAT_PID=$!
        echo "$HEARTBEAT_PID" > "$ANCHOR_PID"

        echo "✅ Anchor started (PID $HEARTBEAT_PID)"
        echo "   Heartbeat every ${HEARTBEAT_INTERVAL}s"
        echo "   Log: $ANCHOR_LOG"
        echo "   State: $ANCHOR_STATE"
        ;;

    status)
        if [[ -f "$ANCHOR_PID" ]] && kill -0 "$(cat "$ANCHOR_PID")" 2>/dev/null; then
            PID=$(cat "$ANCHOR_PID")
            echo "✅ Anchor alive (PID $PID)"
            echo "   Started: $(jq -r '.started_at' "$ANCHOR_STATE" 2>/dev/null || echo 'unknown')"
            echo "   CWD: $(jq -r '.cwd' "$ANCHOR_STATE" 2>/dev/null || echo 'unknown')"
            echo "   Tasks: $(jq -r '.tasks_completed' "$ANCHOR_STATE" 2>/dev/null || echo 0)"
            echo "   Last activity: $(jq -r '.last_activity' "$ANCHOR_STATE" 2>/dev/null || echo 'unknown')"
            echo "   Heartbeats: $(wc -l < "$ANCHOR_LOG" 2>/dev/null || echo 0)"
        else
            echo "❌ Anchor not running"
            [[ -f "$ANCHOR_STATE" ]] && echo "   Last state:" && cat "$ANCHOR_STATE"
        fi
        ;;

    log)
        shift
        MSG="${*:-no message}"
        echo "$(date -Iseconds) $MSG" >> "$ANCHOR_LOG"

        # Update state
        if [[ -f "$ANCHOR_STATE" ]]; then
            tmp=$(mktemp)
            jq ".last_activity = \"$(date -Iseconds)\" | .tasks_completed += 1" "$ANCHOR_STATE" > "$tmp" && mv "$tmp" "$ANCHOR_STATE"
        fi

        echo "📝 Logged: $MSG"
        ;;

    stop)
        if [[ -f "$ANCHOR_PID" ]]; then
            PID=$(cat "$ANCHOR_PID")
            if kill -0 "$PID" 2>/dev/null; then
                kill "$PID" 2>/dev/null
                echo "🛑 Anchor stopped (PID $PID)"
            else
                echo "⚠️  Anchor was not running (stale PID)"
            fi
            rm -f "$ANCHOR_PID"
        else
            echo "⚠️  No anchor PID found"
        fi
        ;;

    resume)
        if [[ -f "$ANCHOR_STATE" ]]; then
            echo "📋 Last session state:"
            cat "$ANCHOR_STATE"
            echo ""
            echo "📂 Was in: $(jq -r '.cwd' "$ANCHOR_STATE" 2>/dev/null)"
            echo "🌿 Branch: $(jq -r '.git_branch' "$ANCHOR_STATE" 2>/dev/null)"
            echo "📝 Tasks completed: $(jq -r '.tasks_completed' "$ANCHOR_STATE" 2>/dev/null)"
            echo ""
            echo "To resume:"
            echo "  cd $(jq -r '.cwd' "$ANCHOR_STATE" 2>/dev/null)"
            echo "  git checkout $(jq -r '.git_branch' "$ANCHOR_STATE" 2>/dev/null)"
        else
            echo "❌ No previous session found"
        fi
        ;;

    help|*)
        echo "night-anchor.sh — Keep CLI sessions alive overnight"
        echo ""
        echo "Usage:"
        echo "  $0 start    # Start anchor (background heartbeat)"
        echo "  $0 status   # Check if anchor is alive"
        echo "  $0 log MSG  # Log a progress message"
        echo "  $0 stop     # Stop anchor"
        echo "  $0 resume   # Show last session state"
        echo ""
        echo "State files:"
        echo "  $ANCHOR_PID   — PID of heartbeat process"
        echo "  $ANCHOR_LOG   — Activity log"
        echo "  $ANCHOR_STATE — Session state JSON"
        ;;
esac
