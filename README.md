# dotfiles

Arch/Hyprland dotfiles, managed with [stow](https://www.gnu.org/software/stow/). Each top-level folder is a stow package.

```bash
cd ~/dotfiles
stow zsh hypr kitty nvim starship waybar dunst
```

## What's in here

- `zsh` — shell config
- `hypr` — Hyprland, hypridle, hyprlock, hyprpaper, plus the workspace1 window manager (below)
- `kitty` — terminal config and themes
- `nvim` — LazyVim-based Neovim config
- `starship` — prompt
- `waybar` — status bar
- `dunst` — notifications

## workspace1: a second window manager on top of Hyprland

The desktop isn't run as a normal tiling setup. Workspace 2 (the main work
area) is driven by `workspace1_manager.py`, a Python daemon that manages a
fixed 4-slot grid (plus a 2-panel "half" mode) of floating windows, each
slot swappable between different apps via directional gestures instead of
manual window placement.

Rough shape of it:

- `workspace1_manager.py` — the daemon and CLI. Tracks which app is active
  in each slot, handles switching/parking windows (closed apps get moved to
  a hidden named workspace instead of killed, so switching back is instant),
  drift correction (snaps a window back if it gets moved/resized outside
  the manager), and a small app registry so new apps can be added without
  touching the grid logic.
- `workspace1_live_resize.py` — a 60fps watcher that handles live drag-resize
  of the grid split, separate from the daemon so dragging stays smooth.
- `workspace1_plugin_dispatch.py` — bridges into a small native Hyprland
  plugin (kept for future work, not currently driving placement).
- The actual gesture UI (the radial pie menus, drag handles, app picker)
  lives in a Quickshell/QML layer that talks to this daemon over its CLI.

The grid geometry is computed from whatever monitor is actually active
(`hyprctl monitors`), scaled from a 2560x1440 reference, so it holds up on
different resolutions instead of being hardcoded to one screen.

## Third workspace

Workspace 1 is dedicated to gaming (Steam/Discord), workspace 3 is a static
ops dashboard (cluster status, Grafana, Uptime Kuma, CI status) launched by
`launch-workspace3.py`.
