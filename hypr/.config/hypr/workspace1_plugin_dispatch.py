#!/usr/bin/env python3

import json
import os
import subprocess
import sys


USER_RUNTIME_DIR = f"/run/user/{os.getuid()}"


def hyprland_env():
    env = os.environ.copy()
    existing_instance = env.get("HYPRLAND_INSTANCE_SIGNATURE")
    existing_socket = env.get("WAYLAND_DISPLAY")
    if existing_instance and existing_socket:
        env["XDG_RUNTIME_DIR"] = env.get("XDG_RUNTIME_DIR", USER_RUNTIME_DIR)
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env['XDG_RUNTIME_DIR']}/bus")
        return env, existing_instance

    instances = subprocess.run(
        ["hyprctl", "instances", "-j"],
        text=True,
        capture_output=True,
        check=True,
    )
    raw = instances.stdout.strip()
    start = raw.find("[")
    if start == -1:
        start = raw.find("{")
    if start == -1:
        raise RuntimeError(f"Unexpected hyprctl instances output: {raw[:200]}")
    payload = json.loads(raw[start:])
    if not payload:
        raise RuntimeError("No Hyprland instance found")

    instance = max(payload, key=lambda item: item.get("time", 0))
    env["HYPRLAND_INSTANCE_SIGNATURE"] = instance["instance"]
    env["WAYLAND_DISPLAY"] = instance["wl_socket"]
    env["XDG_RUNTIME_DIR"] = USER_RUNTIME_DIR
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={USER_RUNTIME_DIR}/bus")
    return env, instance["instance"]


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: workspace1_plugin_dispatch.py <left_width> <top_height>")

    left = str(int(float(sys.argv[1])))
    top = str(int(float(sys.argv[2])))
    env, instance = hyprland_env()
    subprocess.run(
        ["hyprctl", "-i", instance, "dispatch", "ws1-set-grid", f"{left} {top}"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


if __name__ == "__main__":
    main()
