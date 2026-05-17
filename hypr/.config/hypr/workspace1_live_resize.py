#!/usr/bin/env python3

import json
import os
import subprocess
import time
from pathlib import Path
import fcntl


LIVE_FILE = Path.home() / ".cache/hypr/hyprworkstation_live_resize.json"
PID_FILE = Path.home() / ".cache/hypr/workspace1_live_resize.pid"
SLOTS_FILE = Path.home() / ".cache/hypr/workspace1_slots.json"
META_FILE = Path.home() / ".cache/hypr/workspace1_meta.json"
USER_RUNTIME_DIR = f"/run/user/{os.getuid()}"
DEBUG_LOG = Path("/tmp/workspace1-live-resize-debug.log")
TRACE_LOG = Path("/tmp/workspace1-live-resize-trace.jsonl")
# Reference canvas this layout was tuned against (2560x1440); everything is
# scaled proportionally to whatever monitor is actually hosting workspace 1,
# mirroring workspace1_manager.py's layout_constants() so drag-time geometry
# matches settle-time geometry on any resolution.
_REF_W = 2560
_REF_H = 1440
_REF_OUTER_LEFT = 48
_REF_OUTER_RIGHT = 48
_REF_OUTER_TOP = 56
_REF_OUTER_BOTTOM = 80
_REF_GRID_COLUMN_GAP = 48
_REF_GRID_ROW_GAP = 64
BOTTOM_WIDTH_RATIO = 937 / 1208
GRID_DELTA_THRESHOLD = 6
WINDOW_DELTA_THRESHOLD = 4

_screen_cache = {"ts": 0.0, "x": 0, "y": 0, "w": _REF_W, "h": _REF_H}
_SCREEN_CACHE_TTL = 2.0


def _detect_screen_geometry(env, instance):
    try:
        out = subprocess.run(
            ["hyprctl", "-i", instance, "monitors", "-j"],
            check=False, capture_output=True, text=True, env=env, timeout=1.0,
        )
        monitors = json.loads(out.stdout or "[]")
        if not monitors:
            return None
    except Exception:
        return None

    m = None
    for cand in monitors:
        if cand.get("activeWorkspace", {}).get("id") == 2:
            m = cand
            break
    if m is None:
        for cand in monitors:
            if cand.get("focused"):
                m = cand
                break
    if m is None:
        m = monitors[0]

    scale = m.get("scale") or 1.0
    return {
        "x": int(m.get("x", 0)),
        "y": int(m.get("y", 0)),
        "w": int(round(m.get("width", _REF_W) / scale)),
        "h": int(round(m.get("height", _REF_H) / scale)),
    }


def screen_geometry(env, instance):
    now = time.monotonic()
    if (now - _screen_cache["ts"]) < _SCREEN_CACHE_TTL:
        return _screen_cache
    geom = _detect_screen_geometry(env, instance)
    if geom is not None:
        _screen_cache.update(geom)
    _screen_cache["ts"] = now
    return _screen_cache


def layout_constants(env, instance):
    s = screen_geometry(env, instance)
    wr = s["w"] / _REF_W
    hr = s["h"] / _REF_H
    return {
        "sx": s["x"], "sy": s["y"], "sw": s["w"], "sh": s["h"],
        "outer_left": int(round(_REF_OUTER_LEFT * wr)),
        "outer_right": int(round(_REF_OUTER_RIGHT * wr)),
        "outer_top": int(round(_REF_OUTER_TOP * hr)),
        "outer_bottom": int(round(_REF_OUTER_BOTTOM * hr)),
        "col_gap": int(round(_REF_GRID_COLUMN_GAP * wr)),
        "row_gap": int(round(_REF_GRID_ROW_GAP * hr)),
    }


def log_line(message):
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.time():.3f} pid={os.getpid()} {message}\n")
    except Exception:
        pass


def log_trace(payload):
    try:
        TRACE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with TRACE_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
    except Exception:
        pass


def read_state():
    try:
        return json.loads(LIVE_FILE.read_text())
    except Exception:
        return None


def read_slots():
    try:
        return json.loads(SLOTS_FILE.read_text())
    except Exception:
        return {}


def read_meta():
    try:
        return json.loads(META_FILE.read_text())
    except Exception:
        return {}


def current_clients(env, instance):
    result = subprocess.run(
        ["hyprctl", "-i", instance, "clients", "-j"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    try:
        return json.loads(result.stdout or "[]")
    except Exception:
        return []


def hyprctl_keyword(env, instance, key, value):
    subprocess.run(
        ["hyprctl", "-i", instance, "keyword", key, str(value)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def significantly_different(a, b, threshold):
    return abs(int(a) - int(b)) >= threshold


def grid_rects(env, instance, left_width, top_height):
    c = layout_constants(env, instance)
    right_top_width = c["sw"] - c["outer_left"] - c["outer_right"] - c["col_gap"] - left_width
    bottom_height = c["sh"] - c["outer_top"] - c["outer_bottom"] - c["row_gap"] - top_height
    left_bottom_width = int(round(left_width * BOTTOM_WIDTH_RATIO))
    right_bottom_width = int(round(right_top_width * BOTTOM_WIDTH_RATIO))
    ox, oy = c["sx"] + c["outer_left"], c["sy"] + c["outer_top"]
    return {
        "top_left": (ox, oy, left_width, top_height),
        "top_right": (ox + left_width + c["col_gap"], oy, right_top_width, top_height),
        "bottom_left": (ox, oy + top_height + c["row_gap"], left_bottom_width, bottom_height),
        "bottom_right": (c["sx"] + c["sw"] - c["outer_right"] - right_bottom_width, oy + top_height + c["row_gap"], right_bottom_width, bottom_height),
    }


def half_rects(env, instance, left_width, top_height):
    rects = grid_rects(env, instance, left_width, top_height)
    c = layout_constants(env, instance)
    right_top_width = c["sw"] - c["outer_left"] - c["outer_right"] - c["col_gap"] - left_width
    full_height = c["sh"] - c["outer_top"] - c["outer_bottom"]
    ox, oy = c["sx"] + c["outer_left"], c["sy"] + c["outer_top"]
    rects["half_left"] = (ox, oy, left_width, full_height)
    rects["half_right"] = (ox + left_width + c["col_gap"], oy, right_top_width, full_height)
    return rects


def apply_grid(env, instance, left, top, previous_actual=None):
    slots = read_slots()
    rects = grid_rects(env, instance, left, top)
    applied = []
    slot_order = ("top_left", "top_right", "bottom_left", "bottom_right")
    previous_actual = previous_actual or {}

    for slot_name in slot_order:
        rect = rects[slot_name]
        slot = slots.get(slot_name) or {}
        active = slot.get("active_profile")
        if not active:
            continue
        profile = (slot.get("profiles") or {}).get(active) or {}
        address = profile.get("address")
        if not address:
            continue
        x, y, w, h = rect
        prior = previous_actual.get(address) or {}
        prior_at = prior.get("at") or [None, None]
        prior_size = prior.get("size") or [None, None]

        if (
            prior_at[0] is not None and
            prior_at[1] is not None and
            prior_size[0] is not None and
            prior_size[1] is not None and
            not significantly_different(prior_at[0], x, WINDOW_DELTA_THRESHOLD) and
            not significantly_different(prior_at[1], y, WINDOW_DELTA_THRESHOLD) and
            not significantly_different(prior_size[0], w, WINDOW_DELTA_THRESHOLD) and
            not significantly_different(prior_size[1], h, WINDOW_DELTA_THRESHOLD)
        ):
            continue
        subprocess.run(
            ["hyprctl", "-i", instance, "dispatch", "resizewindowpixel", f"exact {w} {h},address:{address}"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        subprocess.run(
            ["hyprctl", "-i", instance, "dispatch", "movewindowpixel", f"exact {x} {y},address:{address}"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        applied.append({
            "slot": slot_name,
            "address": address,
            "target": {"x": x, "y": y, "w": w, "h": h},
        })
    return applied


def apply_layout(env, instance, left, top, previous_actual=None):
    slots = read_slots()
    meta = read_meta()
    mode = meta.get("mode", "grid")
    rects = half_rects(env, instance, left, top)
    previous_actual = previous_actual or {}
    applied = []

    if mode == "half_left":
        slot_order = ("half_left", "top_right", "bottom_right")
    elif mode == "half_right":
        slot_order = ("top_left", "bottom_left", "half_right")
    else:
        slot_order = ("top_left", "top_right", "bottom_left", "bottom_right")

    for slot_name in slot_order:
        rect = rects[slot_name]
        slot = slots.get(slot_name) or {}
        active = slot.get("active_profile")
        if not active:
            continue
        profile = (slot.get("profiles") or {}).get(active) or {}
        address = profile.get("address")
        if not address:
            continue
        x, y, w, h = rect
        prior = previous_actual.get(address) or {}
        prior_at = prior.get("at") or [None, None]
        prior_size = prior.get("size") or [None, None]

        if (
            prior_at[0] is not None and
            prior_at[1] is not None and
            prior_size[0] is not None and
            prior_size[1] is not None and
            not significantly_different(prior_at[0], x, WINDOW_DELTA_THRESHOLD) and
            not significantly_different(prior_at[1], y, WINDOW_DELTA_THRESHOLD) and
            not significantly_different(prior_size[0], w, WINDOW_DELTA_THRESHOLD) and
            not significantly_different(prior_size[1], h, WINDOW_DELTA_THRESHOLD)
        ):
            continue

        subprocess.run(
            ["hyprctl", "-i", instance, "dispatch", "resizewindowpixel", f"exact {w} {h},address:{address}"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        subprocess.run(
            ["hyprctl", "-i", instance, "dispatch", "movewindowpixel", f"exact {x} {y},address:{address}"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        applied.append({
            "slot": slot_name,
            "address": address,
            "target": {"x": x, "y": y, "w": w, "h": h},
        })

    return applied

def main():
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    pid_handle = PID_FILE.open("w", encoding="utf-8")
    try:
        fcntl.flock(pid_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log_line("another watcher already holds the lock; exiting")
        raise SystemExit(0)
    pid_handle.write(str(os.getpid()))
    pid_handle.flush()
    try:
        DEBUG_LOG.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        TRACE_LOG.unlink(missing_ok=True)
    except Exception:
        pass
    last = None
    dispatch_count = 0
    animations_suppressed = False
    blur_suppressed = False
    shadow_suppressed = False
    previous_actual = {}
    env = os.environ.copy()
    instance = env.get("HYPRLAND_INSTANCE_SIGNATURE")
    socket = env.get("WAYLAND_DISPLAY")
    if not instance or not socket:
        raise SystemExit("workspace1_live_resize.py requires HYPRLAND_INSTANCE_SIGNATURE and WAYLAND_DISPLAY")
    env["XDG_RUNTIME_DIR"] = env.get("XDG_RUNTIME_DIR", USER_RUNTIME_DIR)
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env['XDG_RUNTIME_DIR']}/bus")

    try:
        log_line(f"start instance={instance} socket={socket}")
        while True:
            state = read_state()
            if not state:
                time.sleep(0.05)
                continue

            active = bool(state.get("active"))
            left = int(state.get("grid_left_width", 1208))
            top = int(state.get("grid_top_height", 680))
            current = (left, top)

            if active:
                if not animations_suppressed:
                    hyprctl_keyword(env, instance, "animations:enabled", 0)
                    animations_suppressed = True
                if not blur_suppressed:
                    hyprctl_keyword(env, instance, "decoration:blur:enabled", 0)
                    blur_suppressed = True
                if not shadow_suppressed:
                    hyprctl_keyword(env, instance, "decoration:shadow:enabled", 0)
                    shadow_suppressed = True
                should_apply = (
                    last is None or
                    significantly_different(current[0], last[0], GRID_DELTA_THRESHOLD) or
                    significantly_different(current[1], last[1], GRID_DELTA_THRESHOLD)
                )
                if should_apply:
                    log_line(f"dispatch left={left} top={top}")
                    dispatch_count += 1
                    applied = apply_layout(env, instance, left, top, previous_actual)
                    clients = current_clients(env, instance)
                    by_address = {c.get("address"): c for c in clients}
                    previous_actual = by_address
                    if dispatch_count % 4 == 0:
                        log_trace({
                            "ts": round(time.time(), 4),
                            "grid": {"left": left, "top": top},
                            "applied": applied,
                            "actual": [
                                {
                                    "slot": item["slot"],
                                    "address": item["address"],
                                    "at": (by_address.get(item["address"]) or {}).get("at"),
                                    "size": (by_address.get(item["address"]) or {}).get("size"),
                                }
                                for item in applied
                            ],
                        })
                    last = current
                time.sleep(0.016)
                continue

            if animations_suppressed:
                hyprctl_keyword(env, instance, "animations:enabled", 1)
                animations_suppressed = False
            if blur_suppressed:
                hyprctl_keyword(env, instance, "decoration:blur:enabled", 1)
                blur_suppressed = False
            if shadow_suppressed:
                hyprctl_keyword(env, instance, "decoration:shadow:enabled", 1)
                shadow_suppressed = False
            last = None
            previous_actual = {}
            time.sleep(0.03)
    finally:
        if 'animations_suppressed' in locals() and animations_suppressed:
            try:
                hyprctl_keyword(env, instance, "animations:enabled", 1)
            except Exception:
                pass
        if 'blur_suppressed' in locals() and blur_suppressed:
            try:
                hyprctl_keyword(env, instance, "decoration:blur:enabled", 1)
            except Exception:
                pass
        if 'shadow_suppressed' in locals() and shadow_suppressed:
            try:
                hyprctl_keyword(env, instance, "decoration:shadow:enabled", 1)
            except Exception:
                pass
        log_line("stop")
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            pid_handle.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
