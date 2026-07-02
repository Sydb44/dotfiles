#!/bin/bash
THEME_DIR="$HOME/.config/kitty/themes"
TARGET_FILE="$HOME/.local/state/theme/kitty_theme.conf"

DARK_THEME="everforest.conf"
LIGHT_THEME="everforest_light.conf"

if [ ! -f "$TARGET_FILE" ]; then
    mkdir -p "$(dirname "$TARGET_FILE")"
    touch "$TARGET_FILE"
fi

if grep -q "#f3f5d9" "$TARGET_FILE"; then
    CURRENT_MODE="light"
else
    CURRENT_MODE="dark"
fi

if [ "$CURRENT_MODE" == "dark" ]; then
    echo "Switching to Light Mode..."
    ln -sf "$THEME_DIR/$LIGHT_THEME" "$TARGET_FILE"
else
    echo "Switching to Dark Mode..."
    ln -sf "$THEME_DIR/$DARK_THEME" "$TARGET_FILE"
fi

kill -SIGUSR1 $(pidof kitty)
