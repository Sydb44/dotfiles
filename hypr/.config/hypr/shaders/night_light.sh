#!/usr/bin/env bash
home="$HOME"
shader_path="$home/.config/hypr/shaders/night.glsl"
# theme_script="$home/.config/quickshell/top-bar/bar/theme-mode.sh"   # top-bar variant
theme_script="$home/.config/quickshell/task-bar/utils/theme-mode.sh"
current_theme_file="$home/.cache/quickshell/theme_mode"

current_shader=$(hyprshade current)

if [[ "$current_shader" == *"night"* ]]; then
    if [[ -f "$restore_file" ]]; then
        prev_theme=$(cat "$restore_file" | tr -d '[:space:]')
    fi

    if [[ -z "$prev_theme" ]]; then
        prev_theme="dark"
    fi

    hyprshade off &
    $theme_script "$prev_theme" &
    hyprctl reload

    echo "off" > "$HOME/.cache/quickshell/night_light"
    rm -f "$restore_file"
else
    if [[ -f "$current_theme_file" ]]; then
        current_theme=$(cat "$current_theme_file" | tr -d '[:space:]')
    fi

    if [[ -z "$current_theme" ]]; then
        current_theme="dark"
    fi

    echo "$current_theme" > "$restore_file"

    hyprshade on "$shader_path"
    $theme_script dark
    echo "on" > "$HOME/.cache/quickshell/night_light"
    brightnessctl set 37% &
fi
