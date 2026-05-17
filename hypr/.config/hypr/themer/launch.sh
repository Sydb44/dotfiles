#!/usr/bin/env bash
# Kill any existing instance
hyprctl dispatch closewindow class:com.snes.hyprthemer 2>/dev/null
sleep 0.1

# Launch in background
python3 ~/.config/hypr/themer/themer.py &

# Wait for window to appear then move it
for i in $(seq 1 20); do
    sleep 0.2
    addr=$(hyprctl clients -j | python3 -c "
import sys, json
for c in json.load(sys.stdin):
    if c.get('class') == 'com.snes.hyprthemer':
        print(c['address'])
        break
" 2>/dev/null)
    if [ -n "$addr" ]; then
        hyprctl dispatch movewindowpixel exact 1099 824,address:$addr
        hyprctl dispatch pin address:$addr
        break
    fi
done
