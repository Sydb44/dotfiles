#!/usr/bin/env bash
home="$HOME"
shader_path="$home/.config/hypr/shaders/crt_mode.glsl"
wallpaper_crt="$home/Pictures/retro/van.png"
current_theme_file="$home/.cache/quickshell/theme_mode"
wallpaper_light="$home/Pictures/desktop/l2.png"
wallpaper_dark="$home/Pictures/desktop/1.png"

current_shader=$(hyprshade current)

if [[ "$current_shader" == *"crt"* ]]; then
    hyprshade off
    hyprctl reload
    pkill waybar
    qs -c snes-hub &

    saved_theme="dark"
    if [[ -f "$current_theme_file" ]]; then
        saved_theme=$(cat "$current_theme_file" | tr -d '[:space:]')
    fi

    if [[ "$saved_theme" == "light" ]]; then
        awww img "$wallpaper_light" --transition-type none
    else
        awww img "$wallpaper_dark" --transition-type none
    fi

    notify-send 'CRT Mode' 'Deactivated'
else
    hyprshade on "$shader_path"

    awww img "$wallpaper_crt" \
    --transition-type grow \
    --transition-pos 0.5,0.5 \
    --transition-duration 1.5 \
    --transition-fps 60

    pkill qs
    waybar &

    overrides="keyword debug:damage_tracking 0;\
    keyword decoration:rounding 0;\
    keyword general:gaps_in 0;\
    keyword general:gaps_out 0;\
    keyword general:border_size 3;\
    keyword decoration:rounding 0;\
    keyword general:col.active_border rgba(626c73ff);\
    keyword general:col.inactive_border rgba(626c73ff);\
    keyword decoration:blur:enabled 0;\
    keyword decoration:shadow:enabled 0;\
    keyword animations:enabled 0;\
    keyword decoration:dim_around 0"

    hyprctl --batch "$overrides"

    notify-send 'CRT Mode' 'Activated'
fi
