#!/usr/bin/env bash
# bumps font/page zoom on windows without touching their size - super+numpad
# does every window, super+shift+numpad only the focused one
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
            # kitty defaults to ctrl+shift for these
            case "$direction" in
                in) key="equal" ;;
                out) key="minus" ;;
                reset) key="0" ;;
            esac
            hyprctl dispatch sendshortcut "CTRL_SHIFT,${key},address:${address}" >/dev/null
            ;;
        *)
            # everything else (firefox, discord, most electron/gtk apps) uses plain ctrl
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
