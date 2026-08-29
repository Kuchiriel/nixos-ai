#!/usr/bin/env bash
# Nightwatch Monitor — checks for errors and reports status
# Run periodically to ensure nightwatch is working correctly

set -e

LOG_DIR="$HOME/.local/state/jarvis/nightwatch"
HISTORY="$LOG_DIR/history.jsonl"
CHECK_INTERVAL=300  # 5 minutes

echo "🌙 Nightwatch Monitor — $(date)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check if nightwatch timer is active
echo "1. Checking timer status..."
if systemctl status nightwatch.timer &>/dev/null; then
    echo "   ✅ nightwatch.timer is active"
else
    echo "   ❌ nightwatch.timer is NOT active"
    echo "   Attempting to start..."
    sudo systemctl start nightwatch.timer
fi

# Check if idle worker timer is active
echo "2. Checking idle worker..."
if systemctl --user status jarvis-idle-worker.timer &>/dev/null; then
    echo "   ✅ jarvis-idle-worker.timer is active"
else
    echo "   ❌ jarvis-idle-worker.timer is NOT active"
    echo "   Attempting to start..."
    systemctl --user start jarvis-idle-worker.timer
fi

# Check recent nightwatch runs
echo "3. Checking recent runs..."
if [ -f "$HISTORY" ]; then
    RECENT=$(tail -5 "$HISTORY" | jq -r '.status' 2>/dev/null | sort | uniq -c)
    echo "   Recent statuses:"
    echo "$RECENT" | while read count status; do
        echo "     $count $status"
    done
    
    # Check for errors
    ERRORS=$(tail -20 "$HISTORY" | jq -r 'select(.status == "reverted") | .description' 2>/dev/null)
    if [ -n "$ERRORS" ]; then
        echo "   ⚠️ Recent reverts:"
        echo "$ERRORS" | head -5 | sed 's/^/     /'
    fi
else
    echo "   ℹ️ No history file yet"
fi

# Check systemd journal for errors
echo "4. Checking journal for errors..."
JOURNAL_ERRORS=$(journalctl --user -u jarvis-idle-worker --since "1 hour ago" --no-pager 2>/dev/null | grep -i "error\|fail\|exception" | tail -5)
if [ -n "$JOURNAL_ERRORS" ]; then
    echo "   ⚠️ Recent errors in journal:"
    echo "$JOURNAL_ERRORS" | sed 's/^/     /'
else
    echo "   ✅ No recent errors in journal"
fi

# Check if services are running
echo "5. Checking services..."
for svc in llama-cpp-server jarvis jarvis-telegram qdrant; do
    if systemctl status "$svc" &>/dev/null; then
        echo "   ✅ $svc is running"
    elif systemctl --user status "$svc" &>/dev/null; then
        echo "   ✅ $svc is running (user)"
    else
        echo "   ⚠️ $svc status unknown"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Monitor completed at $(date)"
