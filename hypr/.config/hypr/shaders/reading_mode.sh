#!/usr/bin/env bash
home="$HOME"
shader_path="$home/.config/hypr/shaders/reading_mode.glsl"
#theme_script="$home/.config/quickshell/top-bar/bar/theme-mode.sh"     # top-bar variant
theme_script="$home/.config/quickshell/task-bar/utils/theme-mode.sh"
current_theme_file="$home/.cache/quickshell/theme_mode"
restore_file="$home/.cache/quickshell/reading_mode_restore"
wallpaper_reading="$home/Pictures/desktop/WP/6.jpg"
wallpaper_dark="$home/Pictures/desktop/wpdark.jpg"
wallpaper_light="$home/Pictures/desktop/wplight.jpg"

current_shader=$(hyprshade current)

if [[ "$current_shader" == *"reading_mode"* ]]; then
    if [[ -f "$restore_file" ]]; then
        prev_theme=$(cat "$restore_file" | tr -d '[:space:]')
    fi

    if [[ -z "$prev_theme" ]]; then
        prev_theme="dark"
    fi

    hyprshade off &
    $theme_script "$prev_theme" --quiet &
    echo "off" > "$HOME/.cache/quickshell/reading_mode"

    if [[ "$prev_theme" == "light" ]]; then
        awww img "$wallpaper_light" --transition-type none &
    else
        awww img "$wallpaper_dark" --transition-type none &
    fi
    hyprctl reload
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
    $theme_script light --quiet
    echo "on" > "$HOME/.cache/quickshell/reading_mode"

    sleep 1
    awww img "$wallpaper_reading" --transition-type none&
    brightnessctl set 37% &

    overrides="keyword animations:enabled 0;\
    keyword decoration:shadow:enabled 0;\
    keyword decoration:blur:enabled 0;\
    keyword decoration:rounding 0;\
    keyword general:gaps_in 0;\
    keyword general:gaps_out 0;\
    keyword general:border_size 2;\
    keyword general:col.active_border rgba(000000ff);\
    keyword general:col.inactive_border rgba(000000ff);\
    keyword decoration:dim_inactive 0"

    hyprctl --batch "$overrides"
fi
