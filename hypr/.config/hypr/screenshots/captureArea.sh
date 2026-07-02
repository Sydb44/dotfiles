#!/bin/bash
set -euo pipefail

geom=$(slurp || true)
[ -z "$geom" ] && exit 1

dir="$HOME/Pictures/Screenshots"
mkdir -p "$dir"
file="$dir/$(date +'%s_grim.png')"

grim -g "$geom" "$file"

if command -v wl-copy >/dev/null 2>&1; then
  wl-copy --type image/png < "$file"
fi

if command -v play >/dev/null 2>&1; then
  play "$HOME/.config/hypr/assets/sounds/camera-shutter.ogg" >/dev/null 2>&1 &
fi

swappy -f "$file" -o "$file"

# re-copy in case swappy annotated it
if command -v wl-copy >/dev/null 2>&1; then
  wl-copy --type image/png < "$file"
fi
