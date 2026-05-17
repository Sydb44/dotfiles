#!/usr/bin/env bash
# SUPER + numpad +/-        : bump content size (font/page zoom) on every window
# SUPER + SHIFT + numpad +/-: bump content size on only the focused window
# Never touches window geometry - routes to each app's own native zoom
# shortcut so it stays smooth/incremental.
set -euo pipefail

direction="${1:-}"
scope="${2:-all}"

if [ "$direction" != "in" ] && [ "$direction" != "out" ] && [ "$direction" != "reset" ]; then
    echo "usage: content_zoom.sh <in|out|reset> [focused|all]" >&2
    exit 1
fi
if [ "$scope" != "focused" ] && [ "$scope" != "all" ]; then
    echo "usage: content_zoom.sh <in|out|reset> [focused|all]" >&2
    exit 1
fi

zoom_one() {
    local address="$1" class="$2"
    local key
    case "$class" in
        kitty|ws1-*)
            # kitty's built-in default binds (kitty_mod = ctrl+shift)
            case "$direction" in
                in) key="equal" ;;
                out) key="minus" ;;
                reset) key="0" ;;
            esac
            hyprctl dispatch sendshortcut "CTRL_SHIFT,${key},address:${address}" >/dev/null
            ;;
        *)
            # Common ctrl+=/ctrl+-/ctrl+0 zoom convention: Firefox, Chromium,
            # most Electron apps (Discord, VSCode, Spotify web UI), many
            # GTK/Qt apps.
            case "$direction" in
                in) key="equal" ;;
                out) key="minus" ;;
                reset) key="0" ;;
            esac
            hyprctl dispatch sendshortcut "CTRL,${key},address:${address}" >/dev/null
            ;;
    esac
}

if [ "$scope" = "focused" ]; then
    active_json="$(hyprctl activewindow -j)"
    address="$(jq -r '.address // empty' <<<"$active_json")"
    class="$(jq -r '.class // empty' <<<"$active_json")"
    [ -n "$address" ] && zoom_one "$address" "$class"
    exit 0
fi

hyprctl clients -j | jq -r '.[] | [.address, .class] | @tsv' | while IFS=$'\t' read -r address class; do
    zoom_one "$address" "$class"
done
