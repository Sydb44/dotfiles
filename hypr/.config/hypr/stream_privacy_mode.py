#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import time
from pathlib import Path
import shutil


CACHE_DIR = Path.home() / ".cache" / "sunshine"
STATE_FILE = CACHE_DIR / "stream_privacy_state.json"
USER_RUNTIME_DIR = f"/run/user/{os.getuid()}"

NULL_SINK_NAME = "moonlight_null"
NULL_SINK_DESC = "Moonlight Null Output"


def run(cmd, *, check=False):
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def run_timed(cmd, timeout_s, *, check=False):
    try:
        return subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=check,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        class _TimedOutResult:
            returncode = 124
            stdout = ""
            stderr = "timeout"
        return _TimedOutResult()


def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(payload, indent=2) + "\n")


def hyprland_env_and_instance():
    env = os.environ.copy()
    existing_instance = env.get("HYPRLAND_INSTANCE_SIGNATURE")
    existing_socket = env.get("WAYLAND_DISPLAY")
    if existing_instance and existing_socket:
        env["XDG_RUNTIME_DIR"] = env.get("XDG_RUNTIME_DIR", USER_RUNTIME_DIR)
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env['XDG_RUNTIME_DIR']}/bus")
        return env, existing_instance

    instances = run(["hyprctl", "instances", "-j"], check=True)
    raw = instances.stdout.strip()
    start = raw.find("[")
    if start == -1:
        start = raw.find("{")
    payload = json.loads(raw[start:]) if start != -1 else []
    if not payload:
        raise RuntimeError("No Hyprland instance found")

    instance = max(payload, key=lambda item: item.get("time", 0))
    env["HYPRLAND_INSTANCE_SIGNATURE"] = instance["instance"]
    env["WAYLAND_DISPLAY"] = instance["wl_socket"]
    env["XDG_RUNTIME_DIR"] = USER_RUNTIME_DIR
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={USER_RUNTIME_DIR}/bus")
    return env, instance["instance"]


def hyprctl_dispatch(*args):
    env, instance = hyprland_env_and_instance()
    run(["hyprctl", "-i", instance, "dispatch", *args], check=False)


def have_ddcutil():
    return shutil.which("ddcutil") is not None


def _ddcutil_get_brightness():
    res = run_timed(["ddcutil", "getvcp", "10", "--brief"], 1.2, check=False)
    if res.returncode != 0:
        return None
    # Example: "VCP code 0x10 (Brightness): current value = 50, max value = 100"
    text = (res.stdout or "").strip()
    marker = "current value ="
    idx = text.find(marker)
    if idx == -1:
        return None
    tail = text[idx + len(marker) :].strip()
    num = ""
    for ch in tail:
        if ch.isdigit():
            num += ch
        else:
            break
    return int(num) if num.isdigit() else None


def _ddcutil_set_brightness(value: int):
    v = max(0, min(100, int(value)))
    res = run_timed(["ddcutil", "setvcp", "10", str(v), "--noverify"], 1.2, check=False)
    return res.returncode == 0


def blank_monitor_hardware(enable_blank: bool, state: dict):
    """
    Best-effort hardware "blanking" using DDC/CI brightness (VCP 0x10).
    This should NOT affect KMS capture.
    Requires DDC/CI access (ddcutil + i2c-dev + permissions).

    If unavailable, do nothing.
    """
    if not have_ddcutil():
        return False

    if enable_blank:
        prev = _ddcutil_get_brightness()
        if not isinstance(prev, int):
            return False
        state["previous_monitor_brightness"] = prev
        return _ddcutil_set_brightness(0)

    prev = state.get("previous_monitor_brightness")
    if isinstance(prev, int):
        return _ddcutil_set_brightness(prev)
    return False


def pactl_info():
    result = run(["pactl", "info"], check=False)
    out = result.stdout.splitlines()
    info = {}
    for line in out:
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        info[k.strip()] = v.strip()
    return info


def list_sinks():
    result = run(["pactl", "list", "short", "sinks"], check=False)
    sinks = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            sinks.append({"id": parts[0], "name": parts[1]})
    return sinks


def list_sink_inputs():
    result = run(["pactl", "list", "short", "sink-inputs"], check=False)
    items = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if parts and parts[0].isdigit():
            items.append(parts[0])
    return items


def ensure_null_sink_loaded(state):
    sinks = list_sinks()
    if any(s["name"] == NULL_SINK_NAME for s in sinks):
        return state

    # Load a null sink via pipewire-pulse
    res = run(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            f"sink_name={NULL_SINK_NAME}",
            f"sink_properties=device.description={NULL_SINK_DESC}",
        ],
        check=False,
    )
    module_id = (res.stdout or "").strip()
    if module_id.isdigit():
        state["null_module_id"] = int(module_id)
    # Give PipeWire a moment to register it
    time.sleep(0.1)
    return state


def set_default_sink(sink_name):
    run(["pactl", "set-default-sink", sink_name], check=False)


def move_all_inputs_to(sink_name):
    for input_id in list_sink_inputs():
        run(["pactl", "move-sink-input", input_id, sink_name], check=False)


def unload_null_sink_if_loaded(state):
    module_id = state.get("null_module_id")
    if isinstance(module_id, int) and module_id > 0:
        run(["pactl", "unload-module", str(module_id)], check=False)
    state.pop("null_module_id", None)
    return state


def choose_restore_sink(state):
    # Prefer the previously remembered sink if it still exists.
    previous = state.get("previous_default_sink")
    sink_names = [s["name"] for s in list_sinks()]
    if isinstance(previous, str) and previous in sink_names and previous != NULL_SINK_NAME:
        return previous

    # Fallback: pick the first real sink (non-null).
    for name in sink_names:
        if name != NULL_SINK_NAME:
            return name
    return None


def enable():
    state = load_state()
    info = pactl_info()
    default_sink = info.get("Default Sink", "")
    # Only capture "previous" sink if it's a real output.
    if default_sink and default_sink != NULL_SINK_NAME:
        state["previous_default_sink"] = default_sink

    state = ensure_null_sink_loaded(state)
    set_default_sink(NULL_SINK_NAME)
    move_all_inputs_to(NULL_SINK_NAME)

    # Blank physical monitor without breaking KMS capture (best-effort).
    state["monitor_blanked"] = bool(blank_monitor_hardware(True, state))

    state["enabled_at"] = int(time.time())
    state["enabled"] = True
    save_state(state)


def disable():
    state = load_state()
    restore_sink = choose_restore_sink(state)

    # Restore physical monitor (best-effort)
    blank_monitor_hardware(False, state)

    if isinstance(restore_sink, str) and restore_sink:
        set_default_sink(restore_sink)
        move_all_inputs_to(restore_sink)

    state = unload_null_sink_if_loaded(state)
    state["enabled"] = False
    save_state(state)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"on", "off"}:
        raise SystemExit("usage: stream_privacy_mode.py on|off")
    if sys.argv[1] == "on":
        enable()
    else:
        disable()


if __name__ == "__main__":
    main()

