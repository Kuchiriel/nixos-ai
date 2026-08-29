#!/usr/bin/env bash
# Gaming mode toggle — for rofi and keybinding
# Usage: gaming-toggle.sh [on|off|toggle|status]

set -euo pipefail

ACTION="${1:-toggle}"

case "$ACTION" in
    on)
        python3 -c "
from jarvis.core.gaming import transition_to_gaming, get_current_profile
if get_current_profile() == 'gaming':
    print('Gaming mode already active')
else:
    result = transition_to_gaming(manual=True)
    print(f'Gaming mode activated — stopped {len(result)} services')
"
        ;;
    off)
        python3 -c "
from jarvis.core.gaming import transition_to_normal, get_current_profile
if get_current_profile() == 'normal':
    print('Already in normal mode')
else:
    result = transition_to_normal(manual=True)
    print(f'Normal mode restored — started {len(result)} services')
"
        ;;
    toggle)
        python3 -c "
from jarvis.core.gaming import toggle_gaming
import json
result = toggle_gaming()
print(json.dumps(result, indent=2))
"
        ;;
    status)
        python3 -c "
from jarvis.core.gaming import get_current_profile, get_gpu_state
profile = get_current_profile()
gpu = get_gpu_state()
print(f'Profile: {profile}')
if gpu:
    print(f'GPU: {gpu.get(\"gpu_utilization\", 0)}% util, {gpu.get(\"vram_used_mb\", 0)}MB VRAM')
"
        ;;
    *)
        echo "Usage: gaming-toggle.sh [on|off|toggle|status]"
        exit 1
        ;;
esac
