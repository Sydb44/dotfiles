#!/bin/bash
set -euo pipefail

"$HOME/.config/hypr/workspace1_manager.py" stop >/dev/null 2>&1 || true
rm -f "$HOME/.cache/hypr/workspace1_manager.pid"
hyprctl dispatch workspace 2 >/dev/null 2>&1 || true
"$HOME/.config/hypr/workspace1_manager.py" launch
hyprctl dispatch workspace 2 >/dev/null 2>&1 || true
nohup "$HOME/.config/hypr/workspace1_manager.py" daemon >/tmp/workspace1-manager.log 2>&1 &
