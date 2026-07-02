#!/usr/bin/env python3
import configparser
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from urllib.parse import unquote, urlparse
from pathlib import Path


HOME = str(Path.home())
CACHE_DIR = Path(HOME) / ".cache" / "hypr"
STATE_FILE = CACHE_DIR / "workspace1_slots.json"
PID_FILE = CACHE_DIR / "workspace1_manager.pid"
META_FILE = CACHE_DIR / "workspace1_meta.json"
REGISTRY_FILE = CACHE_DIR / "workstation_registry.json"
RUNTIME_FILE = CACHE_DIR / "workstation_runtime.json"
VAULT_FILE = CACHE_DIR / "workstation_vault.json"
APPS_CACHE_FILE = CACHE_DIR / "workstation_apps.json"
PICKER_PREFS_FILE = CACHE_DIR / "workstation_picker_prefs.json"
LIVE_RESIZE_FILE = CACHE_DIR / "hyprworkstation_live_resize.json"
RUN_EVENTS_FILE = CACHE_DIR / "workstation_run_events.jsonl"
EXE_MAPPINGS_FILE = CACHE_DIR / "workstation_exe_mappings.json"
PREFIX_ROOT = Path(HOME) / ".local" / "share" / "workstation-prefixes"
BINDINGS_FILE = Path(HOME) / ".config" / "hypr" / "workstation_bindings.json"
USER_RUNTIME_DIR = f"/run/user/{os.getuid()}"
FIREFOX_PROFILE_ROOT = Path(HOME) / ".mozilla" / "firefox" / "workstation-profiles"
HALF_APP_REGISTRY_FILE = Path(HOME) / ".config" / "hypr" / "workstation_apps.json"
PLUGIN_SO = str(Path(HOME) / "projects" / "hyprworkstation-plugin" / "build" / "libhyprworkstation.so")

WORKSPACE_ID = 2
POLL_INTERVAL = 0.20
RESTORE_DELAY = 0.35
POSITION_TOLERANCE = 10
BOTTOM_WIDTH_RATIO = 937 / 1208

# everything below scales off this 2560x1440 reference so it still looks
# right on whatever monitor workspace 1 actually ends up on
_REF_W = 2560
_REF_H = 1440
_REF_OUTER_LEFT = 48
_REF_OUTER_RIGHT = 48
_REF_OUTER_TOP = 56
_REF_OUTER_BOTTOM = 80
_REF_GRID_COLUMN_GAP = 48
_REF_GRID_ROW_GAP = 64
_REF_DEFAULT_LEFT_W = 1208
_REF_DEFAULT_TOP_H = 680
_REF_MIN_LEFT_W = 980
_REF_MAX_LEFT_W = 1436
_REF_MIN_TOP_H = 620
_REF_MAX_TOP_H = 800

_screen_cache = {"ts": 0.0, "x": 0, "y": 0, "w": _REF_W, "h": _REF_H}
_SCREEN_CACHE_TTL = 1.0


def _detect_screen_geometry():
    """Find the monitor currently hosting workspace 1 and return its logical
    (scale-adjusted) position/size. Falls back to the focused monitor, then
    the first monitor, then the last known-good cached value."""
    try:
        out = subprocess.run(
            ["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=1.0
        )
        monitors = json.loads(out.stdout)
        if not monitors:
            raise ValueError("no monitors reported")
    except Exception:
        return None

    def pick():
        for m in monitors:
            if m.get("activeWorkspace", {}).get("id") == WORKSPACE_ID:
                return m
        for m in monitors:
            if m.get("focused"):
                return m
        return monitors[0]

    m = pick()
    scale = m.get("scale") or 1.0
    width = int(round(m.get("width", _REF_W) / scale))
    height = int(round(m.get("height", _REF_H) / scale))
    return {"x": int(m.get("x", 0)), "y": int(m.get("y", 0)), "w": width, "h": height}


def get_screen_geometry(force=False):
    now = time.monotonic()
    if not force and (now - _screen_cache["ts"]) < _SCREEN_CACHE_TTL:
        return _screen_cache
    geom = _detect_screen_geometry()
    if geom is None:
        _screen_cache["ts"] = now
        return _screen_cache
    _screen_cache.update(geom)
    _screen_cache["ts"] = now
    return _screen_cache


def layout_constants(meta=None):
    """All layout numbers scaled proportionally to the active monitor."""
    screen = get_screen_geometry()
    sx, sy, sw, sh = screen["x"], screen["y"], screen["w"], screen["h"]
    wr = sw / _REF_W
    hr = sh / _REF_H
    return {
        "sx": sx,
        "sy": sy,
        "sw": sw,
        "sh": sh,
        "outer_left": int(round(_REF_OUTER_LEFT * wr)),
        "outer_right": int(round(_REF_OUTER_RIGHT * wr)),
        "outer_top": int(round(_REF_OUTER_TOP * hr)),
        "outer_bottom": int(round(_REF_OUTER_BOTTOM * hr)),
        "col_gap": int(round(_REF_GRID_COLUMN_GAP * wr)),
        "row_gap": int(round(_REF_GRID_ROW_GAP * hr)),
        "default_left_w": int(round(_REF_DEFAULT_LEFT_W * wr)),
        "default_top_h": int(round(_REF_DEFAULT_TOP_H * hr)),
        "min_left_w": int(round(_REF_MIN_LEFT_W * wr)),
        "max_left_w": int(round(_REF_MAX_LEFT_W * wr)),
        "min_top_h": int(round(_REF_MIN_TOP_H * hr)),
        "max_top_h": int(round(_REF_MAX_TOP_H * hr)),
    }


def expanded_geometry():
    c = layout_constants()
    return {
        "x": c["sx"] + c["outer_left"],
        "y": c["sy"] + c["outer_top"],
        "w": c["sw"] - c["outer_left"] - c["outer_right"],
        "h": c["sh"] - c["outer_top"] - c["outer_bottom"],
    }


def half_geometry_defaults():
    c = layout_constants()
    full_h = c["sh"] - c["outer_top"] - c["outer_bottom"]
    return {
        "left": {"x": c["sx"] + c["outer_left"], "y": c["sy"] + c["outer_top"], "w": c["default_left_w"], "h": full_h},
        "right": {
            "x": c["sx"] + c["outer_left"] + c["default_left_w"] + c["col_gap"],
            "y": c["sy"] + c["outer_top"],
            "w": c["sw"] - c["outer_left"] - c["outer_right"] - c["col_gap"] - c["default_left_w"],
            "h": full_h,
        },
    }


HALF_GEOMETRY = half_geometry_defaults()


SLOTS = {
    "top_left": {
        "profile": "term",
        "directions": {
            "up": "term",
            "left": "lazygit",
            "down": "nvim",
            "right": "firefox",
        },
        "class": "ws1-slot-tl",
        "title": "ws1-slot-tl",
        "geometry": {"x": 48, "y": 56, "w": 1208, "h": 680},
    },
    "top_right": {
        "profile": "firefox",
        "directions": {
            "up": "firefox",
            "left": "k9s",
            "down": "btop",
            "right": "term",
        },
        "class": "ws1-slot-tr",
        "title": "ws1-slot-tr",
        "geometry": {"x": 1304, "y": 56, "w": 1208, "h": 680},
    },
    "bottom_left": {
        "profile": "yazi",
        "directions": {
            "up": "yazi",
            "left": "lazygit",
            "down": "term",
            "right": "dolphin",
        },
        "class": "ws1-slot-bl",
        "title": "ws1-slot-bl",
        "geometry": {"x": 48, "y": 800, "w": 937, "h": 560},
    },
    "bottom_right": {
        "profile": "bottom",
        "directions": {
            "up": "k9s",
            "left": "grafana",
            "down": "bottom",
            "right": "htop",
        },
        "class": "ws1-slot-br",
        "title": "ws1-slot-br",
        "geometry": {"x": 1575, "y": 800, "w": 937, "h": 560},
    },
}

HALF_SLOTS = {
    "half_left": {
        "profile": "term",
        "directions": {
            "left": "term",
            "right": "firefox",
            "up": "term",
            "down": "firefox",
        },
        "class": "ws1-half-left",
        "title": "ws1-half-left",
        "geometry": HALF_GEOMETRY["left"],
    },
    "half_right": {
        "profile": "firefox",
        "directions": {
            "left": "term",
            "right": "firefox",
            "up": "term",
            "down": "firefox",
        },
        "class": "ws1-half-right",
        "title": "ws1-half-right",
        "geometry": HALF_GEOMETRY["right"],
    },
}

ALL_SLOTS = {**SLOTS, **HALF_SLOTS}
GRID_SLOT_NAMES = list(SLOTS.keys())

PROFILE_COMMANDS = {
    "nvim": ["kitty", "-e", "nvim"],
    "term": ["kitty"],
    "dolphin": ["dolphin", "--new-window", HOME],
    "htop": ["kitty", "-e", "htop"],
    "yazi": ["kitty", "-e", "yazi"],
    "btop": ["kitty", "-e", "btop"],
    "bottom": ["kitty", "-e", "/usr/bin/btm"],
    "lazygit": ["kitty", "-e", "lazygit"],
    "journal": ["kitty", "-e", "bash", "-lc", "journalctl -f -n 80"],
    "k9s": ["kitty", "-e", "k9s"],
    "firefox": ["firefox"],
}

PROFILE_CLASSES = {
    "dolphin": {"dolphin", "org.kde.dolphin"},
    "firefox": {"firefox"},
}

DEFAULT_HALF_APPS = {
    "term": {
        "label": "Terminal",
        "command": ["kitty"],
        "classes": [],
    },
    "firefox": {
        "label": "Firefox",
        "command": ["firefox"],
        "classes": ["firefox"],
    },
    "cursor": {
        "label": "Cursor",
        "command": ["cursor"],
        "classes": ["cursor", "Cursor"],
    },
    "dolphin": {
        "label": "Dolphin",
        "command": ["dolphin", "--new-window", HOME],
        "classes": ["dolphin", "org.kde.dolphin"],
    },
    "btop": {
        "label": "btop",
        "command": ["kitty", "-e", "btop"],
        "classes": [],
    },
    "bottom": {
        "label": "Bottom",
        "command": ["kitty", "-e", "/usr/bin/btm"],
        "classes": [],
    },
}

DEFAULT_BINDINGS = {
    "grid": {
        "top_left": dict(SLOTS["top_left"]["directions"]),
        "top_right": dict(SLOTS["top_right"]["directions"]),
        "bottom_left": dict(SLOTS["bottom_left"]["directions"]),
        "bottom_right": dict(SLOTS["bottom_right"]["directions"]),
    },
    "half": {
        "left": {
            "left": "term",
            "right": "firefox",
        },
        "right": {
            "left": "term",
            "right": "firefox",
        },
    },
}


def is_firefox_profile(profile):
    return profile == "firefox"


def ensure_firefox_profile(slot_name):
    profile_dir = FIREFOX_PROFILE_ROOT / slot_name
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "user.js").write_text(
        '\n'.join([
            'user_pref("browser.startup.page", 3);',
            'user_pref("browser.sessionstore.resume_from_crash", true);',
            'user_pref("browser.tabs.warnOnClose", false);',
            "",
        ])
    )
    return profile_dir


def ensure_half_app_registry_file():
    HALF_APP_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if HALF_APP_REGISTRY_FILE.exists():
        return
    HALF_APP_REGISTRY_FILE.write_text(
        json.dumps({"schema_version": 2, "apps": DEFAULT_HALF_APPS}, indent=2) + "\n"
    )


def load_half_apps():
    ensure_half_app_registry_file()
    try:
        raw = json.loads(HALF_APP_REGISTRY_FILE.read_text())
    except json.JSONDecodeError:
        raw = {}
    _, raw_apps = normalize_custom_apps_payload(raw)

    apps = {}
    for app_id, item in DEFAULT_HALF_APPS.items():
        merged = dict(item)
        if isinstance(raw_apps.get(app_id), dict):
            merged.update(raw_apps[app_id])
        apps[app_id] = merged

    for app_id, item in raw_apps.items():
        if app_id in apps or not isinstance(item, dict):
            continue
        entrypoint = item.get("entrypoint") if isinstance(item.get("entrypoint"), dict) else {}
        has_argv = isinstance(entrypoint.get("argv"), list) and entrypoint.get("argv")
        if not has_argv and (not isinstance(item.get("command"), list) or not item.get("command")):
            continue
        apps[app_id] = item

    return apps


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def append_jsonl(path, payload):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
    except OSError:
        # Logging should never break control flow for runtime actions.
        return


def log_run_event(event_type, app_id, runtime_type, status, **extra):
    payload = {
        "ts": int(time.time()),
        "event": event_type,
        "app_id": app_id,
        "runtime": runtime_type,
        "status": status,
    }
    payload.update(extra)
    append_jsonl(RUN_EVENTS_FILE, payload)


def normalize_custom_apps_payload(raw):
    if isinstance(raw, dict) and isinstance(raw.get("apps"), dict):
        return int(raw.get("schema_version", 2)), raw["apps"]
    if isinstance(raw, dict):
        return 1, raw
    return 1, {}


def normalize_custom_app_entry(app_id, item):
    if not isinstance(item, dict):
        return None
    label = item.get("label") or app_id
    classes = item.get("classes") or []
    runtime = item.get("runtime") if isinstance(item.get("runtime"), dict) else {}
    runtime_type = str(runtime.get("type") or "native")
    entrypoint = item.get("entrypoint") if isinstance(item.get("entrypoint"), dict) else {}

    # Backward compatibility with legacy command-based entries.
    if not entrypoint.get("argv") and isinstance(item.get("command"), list):
        entrypoint["argv"] = item["command"]
    if not runtime.get("type"):
        runtime["type"] = "native"

    normalized = {
        "id": app_id,
        "label": label,
        "icon": item.get("icon") or app_id,
        "classes": classes if isinstance(classes, list) else [],
        "runtime": runtime,
        "runtime_type": runtime_type,
        "entrypoint": entrypoint,
        "working_dir": item.get("workingDir"),
        "env": item.get("env") if isinstance(item.get("env"), dict) else {},
        "args": item.get("args") if isinstance(item.get("args"), list) else [],
        "preflight": item.get("preflight") if isinstance(item.get("preflight"), dict) else {},
        "post_launch": item.get("postLaunch") if isinstance(item.get("postLaunch"), dict) else {},
        "provision": item.get("provision") if isinstance(item.get("provision"), dict) else {},
        "known_incompatible": item.get("known_incompatible"),
    }
    return normalized


def normalize_registry_app_entry(app_id):
    app = load_registry().get("apps", {}).get(app_id)
    if not isinstance(app, dict):
        return None
    if app.get("source") == "custom":
        return normalize_custom_app_entry(app_id, app)
    launch = app.get("launch") if isinstance(app.get("launch"), list) else []
    runtime = app.get("runtime") if isinstance(app.get("runtime"), dict) else {"type": "native"}
    runtime_type = str(runtime.get("type") or "native")
    return {
        "id": app_id,
        "label": app.get("label") or app_id,
        "icon": app.get("icon") or app_id,
        "classes": app.get("classes") if isinstance(app.get("classes"), list) else [],
        "runtime": runtime,
        "runtime_type": runtime_type,
        "entrypoint": app.get("entrypoint") if isinstance(app.get("entrypoint"), dict) else {"argv": launch},
        "working_dir": app.get("workingDir"),
        "env": app.get("env") if isinstance(app.get("env"), dict) else {},
        "args": app.get("args") if isinstance(app.get("args"), list) else [],
        "preflight": app.get("preflight") if isinstance(app.get("preflight"), dict) else {},
        "post_launch": app.get("postLaunch") if isinstance(app.get("postLaunch"), dict) else {},
        "provision": app.get("provision") if isinstance(app.get("provision"), dict) else {},
        "known_incompatible": app.get("known_incompatible"),
    }


def resolve_app_action(app_entry, action):
    runtime_type = app_entry.get("runtime_type", "native")
    runtime = app_entry.get("runtime", {})
    entrypoint = app_entry.get("entrypoint", {})
    env = dict(app_entry.get("env", {}))
    argv = []
    cwd = app_entry.get("working_dir")

    if action != "launch":
        action_value = app_entry.get("provision", {}).get(action)
        if isinstance(action_value, list) and action_value:
            argv = [str(v) for v in action_value]
        elif isinstance(action_value, dict):
            action_argv = action_value.get("argv")
            if isinstance(action_argv, list) and action_argv:
                argv = [str(v) for v in action_argv]
            cwd = action_value.get("workingDir") or cwd
            if isinstance(action_value.get("env"), dict):
                env.update({str(k): str(v) for k, v in action_value["env"].items()})
        elif action in {"install", "repair", "remove"}:
            raise RuntimeError(f"no '{action}' action configured for {app_entry['id']}")

    if not argv:
        if runtime_type in {"native", "steam"}:
            argv = list(entrypoint.get("argv") or [])
            if runtime_type == "steam" and runtime.get("steamAppId"):
                argv = ["/usr/bin/steam", "-applaunch", str(runtime["steamAppId"])]
        elif runtime_type == "bottles":
            bottle = runtime.get("profileId") or app_entry["id"]
            exe = entrypoint.get("exe")
            if exe:
                argv = ["bottles-cli", "run", "-b", bottle, "-e", str(exe)]
            else:
                argv = list(entrypoint.get("argv") or [])
        elif runtime_type == "wine":
            prefix = runtime.get("profilePath") or str(PREFIX_ROOT / (runtime.get("profileId") or app_entry["id"]))
            exe = entrypoint.get("exe")
            env["WINEPREFIX"] = prefix
            if exe:
                argv = ["wine", str(exe)]
            else:
                argv = list(entrypoint.get("argv") or [])
        elif runtime_type == "proton":
            proton_cmd = runtime.get("protonBin") or "/usr/bin/proton"
            prefix = runtime.get("profilePath") or str(PREFIX_ROOT / (runtime.get("profileId") or app_entry["id"]))
            env["STEAM_COMPAT_DATA_PATH"] = prefix
            exe = entrypoint.get("exe")
            if exe:
                argv = [proton_cmd, "run", str(exe)]
            else:
                argv = list(entrypoint.get("argv") or [])
        else:
            argv = list(entrypoint.get("argv") or [])

    argv.extend([str(v) for v in app_entry.get("args", [])])
    if not argv:
        raise RuntimeError(f"no entrypoint defined for {app_entry['id']}")
    return {"argv": argv, "env": env, "cwd": cwd, "runtime_type": runtime_type}


def execute_hook_block(app_entry, block_name, runtime_type):
    block = app_entry.get(block_name) or {}
    hook_argv = None
    hook_env = {}
    hook_cwd = None
    if isinstance(block, list):
        hook_argv = [str(v) for v in block]
    elif isinstance(block, dict):
        if isinstance(block.get("argv"), list):
            hook_argv = [str(v) for v in block["argv"]]
        hook_cwd = block.get("workingDir")
        if isinstance(block.get("env"), dict):
            hook_env = {str(k): str(v) for k, v in block["env"].items()}
    if not hook_argv:
        return
    env = os.environ.copy()
    env.update(hook_env)
    log_run_event(block_name, app_entry["id"], runtime_type, "start", argv=hook_argv)
    result = subprocess.run(
        hook_argv,
        text=True,
        capture_output=True,
        check=False,
        env=env,
        cwd=hook_cwd or None,
    )
    status = "ok" if result.returncode == 0 else "error"
    log_run_event(
        block_name,
        app_entry["id"],
        runtime_type,
        status,
        exit_code=result.returncode,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{block_name} hook failed for {app_entry['id']} with {result.returncode}")


def live_resize_active():
    try:
        raw = json.loads(LIVE_RESIZE_FILE.read_text())
    except Exception:
        return False
    return bool(raw.get("active"))


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def load_exe_mappings():
    raw = read_json(EXE_MAPPINGS_FILE, {"items": {}})
    items = raw.get("items")
    if not isinstance(items, dict):
        items = {}
    return {"items": items}


def save_exe_mappings(payload):
    write_json(EXE_MAPPINGS_FILE, payload)


def normalize_exe_path(raw_path):
    value = str(raw_path or "").strip()
    if value.startswith("file://"):
        parsed = urlparse(value)
        value = unquote(parsed.path)
    return str(Path(value).expanduser().resolve())


def exe_file_metadata(exe_path):
    path = Path(exe_path)
    if not path.exists():
        raise RuntimeError(f"exe not found: {exe_path}")
    if not path.is_file():
        raise RuntimeError(f"not a file: {exe_path}")
    if path.suffix.lower() != ".exe":
        raise RuntimeError(f"not an .exe file: {exe_path}")
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": str(path),
        "name": path.name,
        "size": int(stat.st_size),
        "mtime": int(stat.st_mtime),
        "sha256": digest,
    }


def exe_mapping_key(exe_meta):
    return f"{exe_meta['sha256']}::{exe_meta['path']}"


def default_exe_runtime_order():
    return ["bottles", "proton", "wine"]


def resolve_exe_runtime_order(exe_meta, requested_runtime="auto"):
    requested = (requested_runtime or "auto").strip().lower()
    allowed = {"auto", "bottles", "proton", "wine"}
    if requested not in allowed:
        raise RuntimeError(f"unsupported runtime mode: {requested_runtime}")
    if requested != "auto":
        return [requested]
    mappings = load_exe_mappings().get("items", {})
    entry = mappings.get(exe_mapping_key(exe_meta), {})
    preferred = str(entry.get("preferred_runtime") or "").lower()
    order = default_exe_runtime_order()
    if preferred in {"bottles", "proton", "wine"}:
        order = [preferred] + [item for item in order if item != preferred]
    return order


def ensure_bindings_file():
    if not BINDINGS_FILE.exists():
        write_json(BINDINGS_FILE, DEFAULT_BINDINGS)


def load_bindings():
    ensure_bindings_file()
    raw = read_json(BINDINGS_FILE, {})
    merged = {
        "grid": {},
        "half": {},
    }
    for panel, defaults in DEFAULT_BINDINGS["grid"].items():
        candidate = raw.get("grid", {}).get(panel, {})
        merged["grid"][panel] = {
            direction: str(candidate.get(direction) or app_id)
            for direction, app_id in defaults.items()
        }
    for side, defaults in DEFAULT_BINDINGS["half"].items():
        candidate = raw.get("half", {}).get(side, {})
        merged["half"][side] = {
            direction: str(candidate.get(direction) or app_id)
            for direction, app_id in defaults.items()
        }
    return merged


def save_bindings(bindings):
    write_json(BINDINGS_FILE, bindings)


def normalize_exec(exec_value):
    if not exec_value:
        return []
    tokens = shlex.split(exec_value)
    stripped = []
    for token in tokens:
        if token.startswith("%"):
            continue
        stripped.append(token)
    return stripped


def desktop_entry_candidates():
    candidates = []
    for root in (
        Path("/usr/share/applications"),
        Path(HOME) / ".local" / "share" / "applications",
    ):
        if not root.exists():
            continue
        candidates.extend(sorted(root.glob("*.desktop")))
    return candidates


def app_id_from_desktop(path, parser):
    desktop = parser["Desktop Entry"]
    wmclass = (desktop.get("StartupWMClass") or "").strip()
    if wmclass:
        return wmclass.lower()
    stem = path.stem.lower()
    if "." in stem:
        stem = stem.split(".")[-1]
    return stem


def build_registry():
    custom_apps = load_half_apps()
    apps = {}

    for app_id, command in PROFILE_COMMANDS.items():
        apps[app_id] = {
            "id": app_id,
            "label": app_id,
            "kind": "builtin",
            "icon": app_id,
            "launch": command[:],
            "classes": list(PROFILE_CLASSES.get(app_id, [])),
            "source": "builtin",
        }

    for app_id, item in custom_apps.items():
        normalized = normalize_custom_app_entry(app_id, item)
        if not normalized:
            continue
        launch_spec = resolve_app_action(normalized, "launch")
        apps[app_id] = {
            "id": app_id,
            "label": normalized.get("label") or app_id,
            "kind": "custom",
            "icon": normalized.get("icon") or app_id,
            "launch": launch_spec.get("argv") or [],
            "classes": normalized.get("classes") or [],
            "runtime": normalized.get("runtime") or {"type": "native"},
            "entrypoint": normalized.get("entrypoint") or {},
            "env": normalized.get("env") or {},
            "workingDir": normalized.get("working_dir"),
            "args": normalized.get("args") or [],
            "preflight": normalized.get("preflight") or {},
            "postLaunch": normalized.get("post_launch") or {},
            "provision": normalized.get("provision") or {},
            "known_incompatible": normalized.get("known_incompatible"),
            "source": "custom",
        }

    for path in desktop_entry_candidates():
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read(path, encoding="utf-8")
        except (configparser.Error, UnicodeDecodeError):
            continue
        if "Desktop Entry" not in parser:
            continue
        desktop = parser["Desktop Entry"]
        if desktop.get("Type", "Application") != "Application":
            continue
        if desktop.get("NoDisplay", "").lower() == "true":
            continue
        exec_cmd = normalize_exec(desktop.get("Exec") or "")
        if not exec_cmd:
            continue
        app_id = app_id_from_desktop(path, parser)
        if app_id in apps:
            continue
        apps[app_id] = {
            "id": app_id,
            "label": desktop.get("Name") or app_id,
            "kind": "gui",
            "icon": desktop.get("Icon") or app_id,
            "launch": exec_cmd,
            "classes": [desktop.get("StartupWMClass")] if desktop.get("StartupWMClass") else [],
            "source": "desktop",
        }

    payload = {
        "generated_at": int(time.time()),
        "apps": dict(sorted(apps.items())),
    }
    write_json(REGISTRY_FILE, payload)
    write_json(APPS_CACHE_FILE, payload["apps"])
    return payload


def load_registry():
    payload = read_json(REGISTRY_FILE, {})
    if not payload or "apps" not in payload:
        payload = build_registry()
    return payload


def load_vault():
    raw = read_json(VAULT_FILE, {"items": []})
    items = raw.get("items")
    if not isinstance(items, list):
        items = []
    return {"items": items}


def save_vault(vault):
    write_json(VAULT_FILE, vault)


def load_picker_prefs():
    raw = read_json(PICKER_PREFS_FILE, {"favorites": [], "recent": []})
    favorites = raw.get("favorites")
    recent = raw.get("recent")
    if not isinstance(favorites, list):
        favorites = []
    if not isinstance(recent, list):
        recent = []
    return {
        "favorites": [str(item) for item in favorites][:32],
        "recent": [str(item) for item in recent][:32],
    }


def save_picker_prefs(prefs):
    write_json(PICKER_PREFS_FILE, prefs)


def mark_recent_app(app_id):
    prefs = load_picker_prefs()
    recent = [item for item in prefs["recent"] if item != app_id]
    recent.insert(0, app_id)
    prefs["recent"] = recent[:24]
    save_picker_prefs(prefs)


def set_favorite_app(app_id, favorite):
    prefs = load_picker_prefs()
    favorites = [item for item in prefs["favorites"] if item != app_id]
    if favorite:
        favorites.append(app_id)
    prefs["favorites"] = favorites[:24]
    save_picker_prefs(prefs)


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


def run(cmd, *, check=True):
    env = None
    actual_cmd = cmd
    if cmd and cmd[0] == "hyprctl":
        env, instance = hyprland_env()
        if "-i" not in cmd:
            actual_cmd = ["hyprctl", "-i", instance, *cmd[1:]]
    return subprocess.run(actual_cmd, text=True, capture_output=True, check=check, env=env)


def hyprctl_json(*args):
    return json.loads(run(["hyprctl", *args]).stdout)


def dispatch(*args):
    run(["hyprctl", "dispatch", *args])


def plugin_list_output():
    return run(["hyprctl", "plugin", "list"], check=False).stdout or ""


def workstation_plugin_loaded():
    output = plugin_list_output()
    return "Plugin hyprworkstation by syd:" in output


def sync_plugin_grid(state):
    # native plugin still has the old monitor size hardcoded, feeding it
    # live updates just makes windows flash to the wrong spot
    return
    if not workstation_plugin_loaded():
        return
    meta = load_meta()
    dispatch("ws1-set-grid", f"{meta['grid_left_width']} {meta['grid_top_height']}")
    current_clients = clients()
    for slot_name in GRID_SLOT_NAMES:
        slot_state = state.get(slot_name) or {}
        address = active_address(slot_state)
        if not address or not client_by_address(address, current_clients):
            continue
        dispatch("ws1-set-slot-window", f"{slot_name} {address}")
    dispatch("ws1-apply")


def ensure_cache_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def clamp(value, low, high):
    return max(low, min(high, int(round(value))))


def normalized_meta(raw=None):
    raw = raw or {}
    c = layout_constants()
    # if the monitor changed, re-center instead of clamping the old pixel
    # values (clamping alone leaves it lopsided against the new bounds)
    screen_changed = (
        raw.get("screen_w") != c["sw"] or raw.get("screen_h") != c["sh"]
    )
    if screen_changed or "grid_left_width" not in raw:
        left_width = c["default_left_w"]
    else:
        left_width = clamp(raw.get("grid_left_width"), c["min_left_w"], c["max_left_w"])
    if screen_changed or "grid_top_height" not in raw:
        top_height = c["default_top_h"]
    else:
        top_height = clamp(raw.get("grid_top_height"), c["min_top_h"], c["max_top_h"])
    return {
        "mode": raw.get("mode", "grid"),
        "expanded_slot": raw.get("expanded_slot"),
        "true_fullscreen_slot": raw.get("true_fullscreen_slot"),
        "grid_left_width": left_width,
        "grid_top_height": top_height,
        "screen_w": c["sw"],
        "screen_h": c["sh"],
    }


def grid_layout(meta=None):
    meta = normalized_meta(meta or load_meta())
    c = layout_constants()
    left_top_width = meta["grid_left_width"]
    right_top_width = c["sw"] - c["outer_left"] - c["outer_right"] - c["col_gap"] - left_top_width
    top_height = meta["grid_top_height"]
    bottom_height = c["sh"] - c["outer_top"] - c["outer_bottom"] - c["row_gap"] - top_height
    left_bottom_width = int(round(left_top_width * BOTTOM_WIDTH_RATIO))
    right_bottom_width = int(round(right_top_width * BOTTOM_WIDTH_RATIO))
    return {
        "top_left": {"x": c["sx"] + c["outer_left"], "y": c["sy"] + c["outer_top"], "w": left_top_width, "h": top_height},
        "top_right": {
            "x": c["sx"] + c["outer_left"] + left_top_width + c["col_gap"],
            "y": c["sy"] + c["outer_top"],
            "w": right_top_width,
            "h": top_height,
        },
        "bottom_left": {
            "x": c["sx"] + c["outer_left"],
            "y": c["sy"] + c["outer_top"] + top_height + c["row_gap"],
            "w": left_bottom_width,
            "h": bottom_height,
        },
        "bottom_right": {
            "x": c["sx"] + c["sw"] - c["outer_right"] - right_bottom_width,
            "y": c["sy"] + c["outer_top"] + top_height + c["row_gap"],
            "w": right_bottom_width,
            "h": bottom_height,
        },
    }


def half_layout(meta=None):
    meta = normalized_meta(meta or load_meta())
    c = layout_constants()
    left_width = meta["grid_left_width"]
    right_width = c["sw"] - c["outer_left"] - c["outer_right"] - c["col_gap"] - left_width
    full_height = c["sh"] - c["outer_top"] - c["outer_bottom"]
    return {
        "half_left":  {"x": c["sx"] + c["outer_left"], "y": c["sy"] + c["outer_top"], "w": left_width,  "h": full_height},
        "half_right": {"x": c["sx"] + c["outer_left"] + left_width + c["col_gap"], "y": c["sy"] + c["outer_top"], "w": right_width, "h": full_height},
    }


def slot_geometry(slot_name, meta=None):
    if slot_name in SLOTS:
        return grid_layout(meta)[slot_name]
    if slot_name in HALF_SLOTS:
        return half_layout(meta)[slot_name]
    return ALL_SLOTS[slot_name]["geometry"]


def save_state(state):
    ensure_cache_dir()
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def load_meta():
    if not META_FILE.exists():
        return normalized_meta()
    try:
        raw = json.loads(META_FILE.read_text())
    except json.JSONDecodeError:
        return normalized_meta()
    return normalized_meta(raw)


def save_meta(meta):
    ensure_cache_dir()
    META_FILE.write_text(json.dumps(normalized_meta(meta), indent=2) + "\n")


def runtime_payload_from_legacy_state(state):
    meta = load_meta()
    runtime_panels = {}
    next_profile_seq = {}
    for slot_name, slot_state in state.items():
        panel_profiles = {}
        for app_id, profile_data in slot_state.get("profiles", {}).items():
            profile_id = profile_data.get("profile_id") or f"profile-{app_id}-{slot_name}-1"
            panel_profiles[profile_id] = {
                "profile_id": profile_id,
                "app_id": app_id,
                "address": profile_data.get("address"),
                "vaulted": bool(profile_data.get("vaulted", False)),
                "created_at": int(profile_data.get("created_at") or time.time()),
            }
            next_profile_seq[slot_name] = max(next_profile_seq.get(slot_name, 1), 2)
        active_profile = slot_state.get("active_profile", ALL_SLOTS[slot_name]["profile"])
        active_profile_id = None
        for profile_id, profile_data in panel_profiles.items():
            if profile_data["app_id"] == active_profile:
                active_profile_id = profile_id
                break
        runtime_panels[slot_name] = {
            "active_profile": active_profile,
            "active_profile_id": active_profile_id,
            "profiles": panel_profiles,
        }
    return {
        "mode": meta.get("mode", "grid"),
        "expanded_slot": meta.get("expanded_slot"),
        "true_fullscreen_slot": meta.get("true_fullscreen_slot"),
        "grid_left_width": meta.get("grid_left_width", layout_constants()["default_left_w"]),
        "grid_top_height": meta.get("grid_top_height", layout_constants()["default_top_h"]),
        "panels": runtime_panels,
        "next_profile_seq": next_profile_seq,
    }


def state_from_runtime(runtime):
    state = {}
    for slot_name in ALL_SLOTS:
        panel = runtime.get("panels", {}).get(slot_name, {})
        profiles = {}
        active_profile = panel.get("active_profile") or ALL_SLOTS[slot_name]["profile"]
        active_profile_id = panel.get("active_profile_id")
        for profile_id, profile_data in panel.get("profiles", {}).items():
            app_id = profile_data.get("app_id")
            if not app_id:
                continue
            profiles[app_id] = {
                "address": profile_data.get("address"),
                "profile_id": profile_id,
                "vaulted": bool(profile_data.get("vaulted", False)),
                "created_at": int(profile_data.get("created_at") or time.time()),
            }
        state[slot_name] = {
            "active_profile": active_profile,
            "active_profile_id": active_profile_id,
            "profiles": profiles,
        }
    return state


def save_runtime(runtime):
    ensure_cache_dir()
    write_json(RUNTIME_FILE, runtime)
    current_meta = load_meta()
    save_meta({
        "mode": runtime.get("mode", "grid"),
        "expanded_slot": runtime.get("expanded_slot"),
        "true_fullscreen_slot": runtime.get("true_fullscreen_slot"),
        "grid_left_width": runtime.get("grid_left_width", current_meta.get("grid_left_width", layout_constants()["default_left_w"])),
        "grid_top_height": runtime.get("grid_top_height", current_meta.get("grid_top_height", layout_constants()["default_top_h"])),
        # without these normalized_meta thinks the monitor changed and
        # resets the grid split back to default on every save
        "screen_w": current_meta.get("screen_w"),
        "screen_h": current_meta.get("screen_h"),
    })
    save_state(state_from_runtime(runtime))


def load_runtime():
    raw = read_json(RUNTIME_FILE, {})
    if not raw or "panels" not in raw:
        runtime = runtime_payload_from_legacy_state(load_state())
        save_runtime(runtime)
        return runtime
    runtime = {
        "mode": raw.get("mode", "grid"),
        "expanded_slot": raw.get("expanded_slot"),
        "true_fullscreen_slot": raw.get("true_fullscreen_slot"),
        "grid_left_width": raw.get("grid_left_width", layout_constants()["default_left_w"]),
        "grid_top_height": raw.get("grid_top_height", layout_constants()["default_top_h"]),
        "panels": {},
        "next_profile_seq": raw.get("next_profile_seq") or {},
    }
    for slot_name in ALL_SLOTS:
        panel = raw.get("panels", {}).get(slot_name, {})
        profiles = {}
        for profile_id, profile_data in panel.get("profiles", {}).items():
            app_id = profile_data.get("app_id")
            if not app_id:
                continue
            profiles[profile_id] = {
                "profile_id": profile_id,
                "app_id": app_id,
                "address": profile_data.get("address"),
                "vaulted": bool(profile_data.get("vaulted", False)),
                "created_at": int(profile_data.get("created_at") or time.time()),
            }
        runtime["panels"][slot_name] = {
            "active_profile": panel.get("active_profile") or ALL_SLOTS[slot_name]["profile"],
            "active_profile_id": panel.get("active_profile_id"),
            "profiles": profiles,
        }
    return runtime


def sync_runtime_from_state(state):
    runtime = runtime_payload_from_legacy_state(state)
    save_runtime(runtime)


def slots_for_mode(mode):
    if mode == "half_left":
        return ["half_left", "top_right", "bottom_right"]
    if mode == "half_right":
        return ["top_left", "bottom_left", "half_right"]
    if mode == "half_both":
        return ["half_left", "half_right"]
    return GRID_SLOT_NAMES


def inactive_slots_for_mode(mode):
    if mode == "half_left":
        return ["top_left", "bottom_left", "half_right"]
    if mode == "half_right":
        return ["top_right", "bottom_right", "half_left"]
    if mode == "half_both":
        return ["top_left", "top_right", "bottom_left", "bottom_right"]
    if mode == "grid":
        return ["half_left", "half_right"]
    return []


def direction_bindings(slot_name):
    bindings = load_bindings()
    if slot_name in SLOTS:
        return bindings["grid"][slot_name]
    if slot_name == "half_left":
        return bindings["half"]["left"]
    if slot_name == "half_right":
        return bindings["half"]["right"]
    return {}


def slot_profiles(slot_name):
    directions = direction_bindings(slot_name)
    profiles = list(dict.fromkeys(directions.values()))
    if slot_name in HALF_SLOTS:
        for app_id in load_half_apps().keys():
            if app_id not in profiles:
                profiles.append(app_id)
    return profiles


def hidden_workspace(slot_name, profile):
    return f"name:__ws1_{slot_name}_{profile}"


def normalize_slot_state(slot_name, raw_entry):
    default_profile = ALL_SLOTS[slot_name]["profile"]
    if not raw_entry:
        return {"active_profile": default_profile, "profiles": {}}

    if "active_profile" in raw_entry and "profiles" in raw_entry:
        return raw_entry

    # Backward compatibility with the earlier one-window-per-slot state format.
    profile = raw_entry.get("profile", default_profile)
    address = raw_entry.get("address")
    profiles = {}
    if profile and address:
        profiles[profile] = {"address": address}
    return {"active_profile": profile, "profiles": profiles}


def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        raw = json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError:
        return {}
    state = {}
    for slot_name in ALL_SLOTS:
        state[slot_name] = normalize_slot_state(slot_name, raw.get(slot_name, {}))
    return state


def clients():
    return hyprctl_json("clients", "-j")


def client_by_address(address, current_clients=None, expected_classes=None):
    # addresses get reused after a window closes, so a stale cached one can
    # match a totally different window - pass expected_classes to catch that
    current_clients = current_clients if current_clients is not None else clients()
    for client in current_clients:
        if client.get("address") == address and client.get("mapped"):
            if expected_classes and client.get("class") not in expected_classes:
                continue
            return client
    return None


def profile_address(slot_state, profile):
    return slot_state.get("profiles", {}).get(profile, {}).get("address")


def profile_id(slot_state, profile):
    return slot_state.get("profiles", {}).get(profile, {}).get("profile_id")


def new_profile_id(runtime, slot_name, profile):
    seq = int(runtime.get("next_profile_seq", {}).get(slot_name, 1))
    runtime.setdefault("next_profile_seq", {})
    runtime["next_profile_seq"][slot_name] = seq + 1
    return f"profile-{profile}-{slot_name}-{seq}"


def set_profile_address(slot_name, slot_state, profile, address, runtime=None):
    slot_state.setdefault("profiles", {})
    slot_state["profiles"].setdefault(profile, {})
    slot_state["profiles"][profile]["address"] = address
    if not slot_state["profiles"][profile].get("profile_id"):
        if runtime is None:
            runtime = load_runtime()
        slot_state["profiles"][profile]["profile_id"] = new_profile_id(runtime, slot_name=slot_name, profile=profile)
    slot_state["profiles"][profile]["created_at"] = int(slot_state["profiles"][profile].get("created_at") or time.time())


def active_address(slot_state):
    return profile_address(slot_state, slot_state.get("active_profile"))


def slot_name_for_address(state, address):
    for slot_name, slot_state in state.items():
        for profile_data in slot_state.get("profiles", {}).values():
            if profile_data.get("address") == address:
                return slot_name
    return None


def get_addr_by_pid(pid):
    for _ in range(120):
        for client in clients():
            if client.get("pid") == pid and client.get("mapped"):
                return client["address"]
        time.sleep(0.1)
    raise RuntimeError(f"Could not resolve window address for pid {pid}")


def expected_classes(slot_name, profile):
    slot = ALL_SLOTS[slot_name]
    registry_app = load_registry().get("apps", {}).get(profile, {})
    classes = registry_app.get("classes") or []
    if classes:
        return set(classes)
    if slot_name in HALF_SLOTS:
        half_apps = load_half_apps()
        app = half_apps.get(profile)
        if app:
            classes = app.get("classes") or []
            if classes:
                return set(classes)
    if profile in PROFILE_CLASSES:
        return PROFILE_CLASSES[profile]
    return {slot["class"]}


def get_new_window_addr(before_addrs, expected_classes_set=None, timeout=15.0):
    return get_new_window_addr_stable(before_addrs, expected_classes_set=expected_classes_set, timeout=timeout)


def _window_score(client):
    size = client.get("size") or [0, 0]
    area = int(size[0] or 0) * int(size[1] or 0)
    mapped_bonus = 1 if client.get("mapped") else 0
    floating_bonus = 1 if client.get("floating") else 0
    return (mapped_bonus, area, floating_bonus)


def get_new_window_addr_stable(before_addrs, expected_classes_set=None, timeout=18.0, settle_seconds=0.15):
    expected_lower = {name.lower() for name in (expected_classes_set or set())}
    deadline = time.monotonic() + timeout
    settle_deadline = None
    last_best = None
    while time.monotonic() < deadline:
        candidate_clients = []
        for client in clients():
            addr = client.get("address")
            client_class = str(client.get("class") or "").lower()
            if (
                addr
                and addr not in before_addrs
                and client.get("mapped")
                and (
                    not expected_lower
                    or client_class in expected_lower
                )
            ):
                candidate_clients.append(client)
        if candidate_clients:
            best = max(candidate_clients, key=_window_score)
            last_best = best.get("address")
            if settle_deadline is None:
                settle_deadline = time.monotonic() + settle_seconds
            elif time.monotonic() >= settle_deadline and last_best:
                return last_best
        time.sleep(0.1)
    if last_best:
        return last_best
    raise RuntimeError("No new window appeared within timeout")


def tracked_addresses(state):
    tracked = set()
    for slot_state in state.values():
        for profile_data in slot_state.get("profiles", {}).values():
            address = profile_data.get("address")
            if address:
                tracked.add(address)
    return tracked


def enforce_workspace_popup_policy(state, current_clients):
    managed_addrs = tracked_addresses(state)
    workspace_clients = [c for c in current_clients if int((c.get("workspace") or {}).get("id") or 0) == WORKSPACE_ID]
    for client in workspace_clients:
        address = client.get("address")
        if not address or address in managed_addrs:
            continue
        if not client.get("mapped"):
            continue
        if client.get("floating"):
            continue
        size = client.get("size") or [0, 0]
        w = int(size[0] or 0)
        h = int(size[1] or 0)
        if w <= 0 or h <= 0:
            continue
        # Broad popup guard: keep unmanaged smaller windows floating so they don't tile behind nodes.
        _c = layout_constants()
        if (w * h) < int(0.72 * _c["sw"] * _c["sh"]):
            dispatch("setfloating", f"address:{address}")


def build_command(slot_name, profile):
    slot = ALL_SLOTS[slot_name]
    registry_app = load_registry().get("apps", {}).get(profile, {})
    normalized = normalize_custom_app_entry(profile, registry_app) if registry_app.get("source") == "custom" else None
    if normalized:
        launch_spec = resolve_app_action(normalized, "launch")
        command = launch_spec["argv"][:]
        command_env = launch_spec["env"]
        command_cwd = launch_spec["cwd"]
        runtime_type = launch_spec["runtime_type"]
    else:
        command_env = {}
        command_cwd = None
        runtime_type = "builtin"
        if registry_app and isinstance(registry_app.get("launch"), list) and registry_app["launch"]:
            command = registry_app["launch"][:]
        elif slot_name in HALF_SLOTS:
            half_apps = load_half_apps()
            app = half_apps.get(profile)
            normalized_half = normalize_custom_app_entry(profile, app) if app else None
            if normalized_half:
                launch_spec = resolve_app_action(normalized_half, "launch")
                command = launch_spec["argv"][:]
                command_env = launch_spec["env"]
                command_cwd = launch_spec["cwd"]
                runtime_type = launch_spec["runtime_type"]
            else:
                command = PROFILE_COMMANDS[profile][:]
        else:
            command = PROFILE_COMMANDS[profile][:]
    if is_firefox_profile(profile):
        profile_dir = ensure_firefox_profile(slot_name)
        command = ["firefox", "--new-instance", "--profile", str(profile_dir), "--new-window"]
    if command[0] == "kitty":
        command = [
            "kitty",
            "--class",
            slot["class"],
            "-T",
            slot["title"],
            "--override",
            "window_padding_width=8",
            *command[1:],
        ]
    return {
        "app_id": profile,
        "argv": command,
        "env": command_env,
        "cwd": command_cwd,
        "runtime_type": runtime_type,
        "app_entry": normalized,
    }


def spawn_launch_plan(app_id, launch_plan):
    env = hyprland_env()[0]
    env.update({str(k): str(v) for k, v in launch_plan.get("env", {}).items()})
    runtime_type = launch_plan.get("runtime_type", "unknown")
    argv = launch_plan.get("argv") or []
    app_entry = launch_plan.get("app_entry")
    if not argv:
        raise RuntimeError(f"empty launch argv for {app_id}")
    if app_entry:
        incompatible = app_entry.get("known_incompatible")
        if incompatible:
            raise RuntimeError(f"{app_id} is marked incompatible: {incompatible}")
        execute_hook_block(app_entry, "preflight", runtime_type)
    log_run_event("launch", app_id, runtime_type, "start", argv=argv)
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
        cwd=launch_plan.get("cwd") or None,
    )
    log_run_event("launch", app_id, runtime_type, "spawned", pid=proc.pid)
    if app_entry:
        execute_hook_block(app_entry, "post_launch", runtime_type)
    return proc


def run_app_action(app_id, action):
    normalized = normalize_registry_app_entry(app_id)
    if not normalized:
        raise RuntimeError(f"unknown app: {app_id}")
    incompatible = normalized.get("known_incompatible")
    if incompatible:
        raise RuntimeError(f"{app_id} is marked incompatible: {incompatible}")
    execute_hook_block(normalized, "preflight", normalized.get("runtime_type", "unknown"))
    launch_plan = resolve_app_action(normalized, action)
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in launch_plan.get("env", {}).items()})
    argv = launch_plan["argv"]
    log_run_event(action, app_id, launch_plan["runtime_type"], "start", argv=argv)
    result = subprocess.run(
        argv,
        text=True,
        capture_output=True,
        env=env,
        cwd=launch_plan.get("cwd") or None,
        check=False,
    )
    status = "ok" if result.returncode == 0 else "error"
    log_run_event(
        action,
        app_id,
        launch_plan["runtime_type"],
        status,
        exit_code=result.returncode,
    )
    print(
        json.dumps(
            {
                "app_id": app_id,
                "action": action,
                "runtime": launch_plan["runtime_type"],
                "command": argv,
                "cwd": launch_plan.get("cwd"),
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            indent=2,
        )
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    execute_hook_block(normalized, "post_launch", launch_plan["runtime_type"])


def build_exe_runtime_entry(exe_meta, runtime_type):
    exe_path = exe_meta["path"]
    exe_name = Path(exe_path).stem
    if runtime_type == "bottles":
        return {
            "id": f"exe::{exe_name}",
            "runtime_type": "bottles",
            "runtime": {"type": "bottles", "profileId": f"exe-{exe_name}"},
            "entrypoint": {"exe": exe_path},
            "args": [],
            "env": {},
            "preflight": {},
            "post_launch": {},
            "working_dir": str(Path(exe_path).parent),
            "known_incompatible": None,
        }
    if runtime_type == "proton":
        return {
            "id": f"exe::{exe_name}",
            "runtime_type": "proton",
            "runtime": {"type": "proton", "profileId": f"exe-{exe_name}"},
            "entrypoint": {"exe": exe_path},
            "args": [],
            "env": {},
            "preflight": {},
            "post_launch": {},
            "working_dir": str(Path(exe_path).parent),
            "known_incompatible": None,
        }
    if runtime_type == "wine":
        return {
            "id": f"exe::{exe_name}",
            "runtime_type": "wine",
            "runtime": {"type": "wine", "profileId": f"exe-{exe_name}"},
            "entrypoint": {"exe": exe_path},
            "args": [],
            "env": {},
            "preflight": {},
            "post_launch": {},
            "working_dir": str(Path(exe_path).parent),
            "known_incompatible": None,
        }
    raise RuntimeError(f"unsupported exe runtime: {runtime_type}")


def persist_exe_runtime_success(exe_meta, runtime_type):
    payload = load_exe_mappings()
    items = payload.setdefault("items", {})
    key = exe_mapping_key(exe_meta)
    items[key] = {
        "path": exe_meta["path"],
        "sha256": exe_meta["sha256"],
        "name": exe_meta["name"],
        "preferred_runtime": runtime_type,
        "last_success_at": int(time.time()),
    }
    save_exe_mappings(payload)


def launch_exe_attempt(exe_meta, runtime_type, attempt_index):
    app_entry = build_exe_runtime_entry(exe_meta, runtime_type)
    launch_plan = resolve_app_action(app_entry, "launch")
    try:
        before_addrs = {c.get("address") for c in clients() if c.get("address")}
    except Exception as exc:
        log_run_event(
            "launch_exe_attempt",
            exe_meta["name"],
            runtime_type,
            "error",
            attempt=attempt_index,
            exe_path=exe_meta["path"],
            reason="hypr_unavailable",
            message=str(exc),
        )
        return {
            "runtime": runtime_type,
            "status": "error",
            "reason": "hypr_unavailable",
            "message": str(exc),
        }
    argv = launch_plan.get("argv") or []
    log_run_event(
        "launch_exe_attempt",
        exe_meta["name"],
        runtime_type,
        "start",
        attempt=attempt_index,
        exe_path=exe_meta["path"],
        argv=argv,
    )
    try:
        proc = spawn_launch_plan(exe_meta["name"], launch_plan)
    except Exception as exc:
        log_run_event(
            "launch_exe_attempt",
            exe_meta["name"],
            runtime_type,
            "error",
            attempt=attempt_index,
            exe_path=exe_meta["path"],
            reason="spawn_error",
            message=str(exc),
        )
        return {
            "runtime": runtime_type,
            "status": "error",
            "reason": "spawn_error",
            "message": str(exc),
        }
    try:
        new_address = get_new_window_addr(before_addrs, timeout=18.0)
        log_run_event(
            "launch_exe_attempt",
            exe_meta["name"],
            runtime_type,
            "ok",
            attempt=attempt_index,
            exe_path=exe_meta["path"],
            pid=proc.pid,
            address=new_address,
        )
        return {
            "runtime": runtime_type,
            "status": "ok",
            "pid": proc.pid,
            "address": new_address,
        }
    except Exception:
        exited = proc.poll() is not None
        reason = "process_exited_early" if exited else "window_not_detected"
        log_run_event(
            "launch_exe_attempt",
            exe_meta["name"],
            runtime_type,
            "error",
            attempt=attempt_index,
            exe_path=exe_meta["path"],
            pid=proc.pid,
            reason=reason,
        )
        return {
            "runtime": runtime_type,
            "status": "error",
            "pid": proc.pid,
            "reason": reason,
        }


def launch_exe_fallback(exe_path, runtime_mode="auto"):
    normalized = normalize_exe_path(exe_path)
    exe_meta = exe_file_metadata(normalized)
    runtime_order = resolve_exe_runtime_order(exe_meta, runtime_mode)
    attempts = []
    for index, runtime_type in enumerate(runtime_order, start=1):
        result = launch_exe_attempt(exe_meta, runtime_type, index)
        attempts.append(result)
        if result.get("status") == "ok":
            persist_exe_runtime_success(exe_meta, runtime_type)
            payload = {
                "status": "ok",
                "exe": exe_meta,
                "runtime_mode": runtime_mode,
                "selected_runtime": runtime_type,
                "attempts": attempts,
            }
            print(json.dumps(payload, indent=2))
            return
    payload = {
        "status": "error",
        "exe": exe_meta,
        "runtime_mode": runtime_mode,
        "attempts": attempts,
    }
    print(json.dumps(payload, indent=2))
    raise SystemExit(1)


def probe_exe(exe_path):
    normalized = normalize_exe_path(exe_path)
    exe_meta = exe_file_metadata(normalized)
    mappings = load_exe_mappings().get("items", {})
    mapping = mappings.get(exe_mapping_key(exe_meta), {})
    print(
        json.dumps(
            {
                "status": "ok",
                "exe": exe_meta,
                "mapping": mapping,
                "runtime_order_auto": resolve_exe_runtime_order(exe_meta, "auto"),
            },
            indent=2,
        )
    )


def app_prefix_path(app_entry):
    runtime_type = app_entry.get("runtime_type", "native")
    runtime = app_entry.get("runtime", {})
    if runtime_type == "bottles":
        return runtime.get("profilePath") or str(PREFIX_ROOT / "bottles" / (runtime.get("profileId") or app_entry["id"]))
    if runtime_type in {"wine", "proton"}:
        return runtime.get("profilePath") or str(PREFIX_ROOT / (runtime.get("profileId") or app_entry["id"]))
    if runtime_type == "steam":
        steam_app_id = runtime.get("steamAppId")
        if steam_app_id:
            return str(Path(HOME) / ".steam" / "steam" / "steamapps" / "compatdata" / str(steam_app_id) / "pfx")
        return str(PREFIX_ROOT / "steam" / app_entry["id"])
    return None


def open_app_prefix(app_id):
    app_entry = normalize_registry_app_entry(app_id)
    if not app_entry:
        raise RuntimeError(f"unknown app: {app_id}")
    prefix = app_prefix_path(app_entry)
    if not prefix:
        raise RuntimeError(f"{app_id} runtime has no prefix path")
    path = Path(prefix)
    path.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"app_id": app_id, "prefix_path": str(path)}, indent=2))


def open_run_logs():
    if RUN_EVENTS_FILE.exists():
        print(RUN_EVENTS_FILE.read_text())
    else:
        print("")


def place_window(address, geometry):
    dispatch("movetoworkspacesilent", f"{WORKSPACE_ID},address:{address}")
    dispatch("setfloating", f"address:{address}")
    dispatch("resizewindowpixel", f"exact {geometry['w']} {geometry['h']},address:{address}")
    dispatch("movewindowpixel", f"exact {geometry['x']} {geometry['y']},address:{address}")


def place_in_slot(address, slot_name):
    geom = slot_geometry(slot_name)
    place_window(address, geom)


def place_expanded(address):
    place_window(address, expanded_geometry())


def place_window_for_profile(address, slot_name, profile, *, expanded=False):
    if expanded:
        place_expanded(address)
    else:
        place_in_slot(address, slot_name)
    if is_firefox_profile(profile):
        # Firefox often sends a later configure request after first map.
        time.sleep(0.45)
        if expanded:
            place_expanded(address)
        else:
            place_in_slot(address, slot_name)


def park_window(address, slot_name, profile):
    dispatch("movetoworkspacesilent", f"{hidden_workspace(slot_name, profile)},address:{address}")


def close_window(address):
    dispatch("closewindow", f"address:{address}")


def launch():
    state = {}
    runtime = {
        "mode": "grid",
        "expanded_slot": None,
        "true_fullscreen_slot": None,
        "panels": {},
        "next_profile_seq": {},
    }
    for slot_name, slot in SLOTS.items():
        profile = slot["profile"]
        launch_plan = build_command(slot_name, profile)
        proc = spawn_launch_plan(profile, launch_plan)
        addr = get_addr_by_pid(proc.pid)
        place_window_for_profile(addr, slot_name, profile)
        slot_state = {"active_profile": profile, "profiles": {}}
        set_profile_address(slot_name, slot_state, profile, addr, runtime=runtime)
        state[slot_name] = slot_state
    for slot_name, slot in HALF_SLOTS.items():
        state[slot_name] = {"active_profile": slot["profile"], "profiles": {}}

    save_state(state)
    sync_runtime_from_state(state)
    save_meta({"mode": "grid", "expanded_slot": None, "true_fullscreen_slot": None})
    save_runtime(runtime_payload_from_legacy_state(state))
    sync_plugin_grid(state)


def ensure_profile_window(slot_name, profile, slot_state):
    address = profile_address(slot_state, profile)
    if address and client_by_address(address, expected_classes=expected_classes(slot_name, profile)):
        return address

    before_addrs = {c["address"] for c in clients()}
    launch_plan = build_command(slot_name, profile)
    spawn_launch_plan(profile, launch_plan)
    new_address = get_new_window_addr(
        before_addrs,
        expected_classes_set=expected_classes(slot_name, profile),
    )
    set_profile_address(slot_name, slot_state, profile, new_address)
    return new_address


def switch_profile(slot_name, direction_name, state):
    meta = load_meta()
    slot_state = state[slot_name]
    slot = ALL_SLOTS[slot_name]
    target_profile = direction_bindings(slot_name)[direction_name]
    current_profile = slot_state.get("active_profile", slot["profile"])

    if target_profile == current_profile:
        existing_address = active_address(slot_state)
        if existing_address and client_by_address(existing_address, expected_classes=expected_classes(slot_name, target_profile)):
            return
        new_address = ensure_profile_window(slot_name, target_profile, slot_state)
        place_window_for_profile(
            new_address,
            slot_name,
            target_profile,
            expanded=(meta.get("mode") == "expanded" and meta.get("expanded_slot") == slot_name),
        )
        save_state(state)
        sync_runtime_from_state(state)
        return

    old_address = active_address(slot_state)
    if old_address and client_by_address(old_address, expected_classes=expected_classes(slot_name, current_profile)):
        park_window(old_address, slot_name, current_profile)

    new_address = ensure_profile_window(slot_name, target_profile, slot_state)
    place_window_for_profile(
        new_address,
        slot_name,
        target_profile,
        expanded=(meta.get("mode") == "expanded" and meta.get("expanded_slot") == slot_name),
    )
    slot_state["active_profile"] = target_profile
    save_state(state)
    sync_runtime_from_state(state)
    if slot_name in SLOTS and load_meta().get("mode") == "grid":
        sync_plugin_grid(state)


def activate_profile(slot_name, profile, state):
    if slot_name not in ALL_SLOTS:
        raise RuntimeError(f"unknown slot: {slot_name}")

    if profile not in slot_profiles(slot_name):
        raise RuntimeError(f"profile {profile} not valid for {slot_name}")

    meta = load_meta()
    slot_state = state[slot_name]
    current_profile = slot_state.get("active_profile", ALL_SLOTS[slot_name]["profile"])

    if current_profile == profile:
        existing_address = active_address(slot_state)
        if existing_address and client_by_address(existing_address, expected_classes=expected_classes(slot_name, profile)):
            return
        new_address = ensure_profile_window(slot_name, profile, slot_state)
        expanded = meta.get("mode") == "expanded" and meta.get("expanded_slot") == slot_name
        place_window_for_profile(new_address, slot_name, profile, expanded=expanded)
        save_state(state)
        sync_runtime_from_state(state)
        return

    old_address = active_address(slot_state)
    if old_address and client_by_address(old_address, expected_classes=expected_classes(slot_name, current_profile)):
        park_window(old_address, slot_name, current_profile)

    new_address = ensure_profile_window(slot_name, profile, slot_state)
    if meta.get("mode") == "expanded" and meta.get("expanded_slot") == slot_name:
        expanded = True
    else:
        expanded = False
    place_window_for_profile(new_address, slot_name, profile, expanded=expanded)
    slot_state["active_profile"] = profile
    save_state(state)
    sync_runtime_from_state(state)
    if slot_name in SLOTS and load_meta().get("mode") == "grid":
        sync_plugin_grid(state)


def activewindow():
    try:
        return hyprctl_json("activewindow", "-j")
    except subprocess.CalledProcessError:
        return {}


def apply_slot_window_policy(address):
    previous = str(activewindow().get("address") or "")
    target = str(address or "")
    if not target:
        return

    if previous != target:
        dispatch("focuswindow", f"address:{target}")
        time.sleep(0.05)

    dispatch("fullscreenstate", "0 2 set")

    if previous and previous != target and client_by_address(previous):
        dispatch("focuswindow", f"address:{previous}")


def focus_slot(slot_name, state):
    if slot_name not in ALL_SLOTS:
        raise SystemExit(f"unknown slot: {slot_name}")

    slot_state = state.get(slot_name) or normalize_slot_state(slot_name, {})
    state[slot_name] = slot_state
    profile = slot_state.get("active_profile", ALL_SLOTS[slot_name]["profile"])
    address = ensure_profile_window(slot_name, profile, slot_state)
    if not address:
        return

    if slot_name in HALF_SLOTS:
        side = "left" if slot_name == "half_left" else "right"
        ensure_half_layout(side, state)
    else:
        meta = load_meta()
        if meta.get("mode") != "grid":
            restore_grid(state)

    apply_slot_window_policy(address)


def restore_grid(state):
    meta = load_meta()
    meta["mode"] = "grid"
    meta["expanded_slot"] = None
    save_meta(meta)

    for slot_name in GRID_SLOT_NAMES:
        slot_state = state[slot_name]
        profile = slot_state.get("active_profile", ALL_SLOTS[slot_name]["profile"])
        address = ensure_profile_window(slot_name, profile, slot_state)
        place_window_for_profile(address, slot_name, profile, expanded=False)
    for slot_name in HALF_SLOTS:
        slot_state = state[slot_name]
        address = active_address(slot_state)
        if address and client_by_address(address):
            park_window(address, slot_name, slot_state["active_profile"])
    save_state(state)
    sync_runtime_from_state(state)
    sync_plugin_grid(state)


def enter_mode(mode, state, profile_overrides=None):
    if mode not in {"grid", "half_left", "half_right", "half_both"}:
        raise RuntimeError(f"unknown mode: {mode}")
    profile_overrides = profile_overrides or {}

    meta = load_meta()
    meta["mode"] = mode
    meta["expanded_slot"] = None
    save_meta(meta)

    active_slots = slots_for_mode(mode)
    parked_slots = inactive_slots_for_mode(mode)

    for slot_name in active_slots:
        slot_state = state[slot_name]
        if slot_name in profile_overrides:
            profile = profile_overrides[slot_name]
            for other_profile, profile_data in slot_state.get("profiles", {}).items():
                other_address = profile_data.get("address")
                if other_profile != profile and other_address and client_by_address(other_address):
                    park_window(other_address, slot_name, other_profile)
            slot_state["active_profile"] = profile
        else:
            profile = slot_state.get("active_profile", ALL_SLOTS[slot_name]["profile"])
        address = ensure_profile_window(slot_name, profile, slot_state)

        if slot_name == "half_left":
            geom = half_layout(meta)["half_left"]
            place_window(address, geom)
            if is_firefox_profile(profile):
                time.sleep(0.45)
                place_window(address, geom)
        elif slot_name == "half_right":
            geom = half_layout(meta)["half_right"]
            place_window(address, geom)
            if is_firefox_profile(profile):
                time.sleep(0.45)
                place_window(address, geom)
        else:
            place_window_for_profile(address, slot_name, profile, expanded=False)

    for slot_name in parked_slots:
        slot_state = state[slot_name]
        address = active_address(slot_state)
        if address and client_by_address(address):
            park_window(address, slot_name, slot_state["active_profile"])

    save_state(state)
    sync_runtime_from_state(state)


def enter_half(side, state, target_profile=None):
    if side not in {"left", "right"}:
        raise RuntimeError(f"unknown side: {side}")
    overrides = {}
    if target_profile:
        overrides[f"half_{side}"] = target_profile
    enter_mode(f"half_{side}", state, overrides)


def expand_slot(slot_name, state):
    active_slots = slots_for_mode(load_meta().get("mode", "grid"))
    inactive_slots = inactive_slots_for_mode(load_meta().get("mode", "grid"))

    for other_slot in active_slots:
        slot_state = state[other_slot]
        address = active_address(slot_state)
        if not address or not client_by_address(address):
            continue
        if other_slot == slot_name:
            place_window_for_profile(
                address,
                other_slot,
                slot_state["active_profile"],
                expanded=True,
            )
        else:
            park_window(address, other_slot, slot_state["active_profile"])
    for other_slot in inactive_slots:
        slot_state = state[other_slot]
        address = active_address(slot_state)
        if address and client_by_address(address):
            park_window(address, other_slot, slot_state["active_profile"])
    meta = load_meta()
    meta["mode"] = "expanded"
    meta["expanded_slot"] = slot_name
    save_meta(meta)


def toggle_expand_current(state):
    meta = load_meta()
    if meta.get("mode") == "expanded":
        restore_grid(state)
        return

    active = activewindow()
    slot_name = slot_name_for_address(state, str(active.get("address") or ""))
    if not slot_name:
        return
    expand_slot(slot_name, state)


def toggle_true_fullscreen_current(state):
    meta = load_meta()
    active = activewindow()
    slot_name = slot_name_for_address(state, str(active.get("address") or ""))
    if not slot_name:
        return

    current_fullscreen = int(active.get("fullscreen", 0) or 0)
    if meta.get("true_fullscreen_slot") == slot_name and current_fullscreen != 0:
        dispatch("fullscreen", "0")
        meta["true_fullscreen_slot"] = None
    else:
        meta["true_fullscreen_slot"] = slot_name
        save_meta(meta)
        dispatch("fullscreen", "0")
        return

    save_meta(meta)


def toggle_split_layout(state):
    meta = load_meta()
    if meta.get("mode") in {"half_left", "half_right"}:
        restore_grid(state)
    else:
        enter_half("left", state)


def ensure_half_layout(side, state):
    if load_meta().get("mode") != f"half_{side}":
        enter_half(side, state)


def activate_half(side, profile, state):
    if side not in {"left", "right"}:
        raise RuntimeError(f"unknown side: {side}")
    if profile not in load_half_apps():
        raise RuntimeError(f"unsupported half profile: {profile}")

    slot_name = "half_left" if side == "left" else "half_right"
    current_mode = load_meta().get("mode", "grid")
    desired_mode = f"half_{side}"
    if current_mode == "half_left" and side == "right":
        desired_mode = "half_both"
    elif current_mode == "half_right" and side == "left":
        desired_mode = "half_both"
    elif current_mode == "half_both":
        desired_mode = "half_both"

    if current_mode != desired_mode:
        enter_mode(desired_mode, state, {slot_name: profile})
        return
    activate_profile(slot_name, profile, state)


def activate_half_app(side, app_id, state):
    if side not in {"left", "right"}:
        raise RuntimeError(f"unknown side: {side}")
    half_apps = load_half_apps()
    if app_id not in half_apps:
        raise RuntimeError(f"unknown half app: {app_id}")
    activate_half(side, app_id, state)


def apply_grid_layout(state):
    meta = load_meta()
    if meta.get("mode") != "grid":
        return
    for slot_name in GRID_SLOT_NAMES:
        slot_state = state.get(slot_name) or normalize_slot_state(slot_name, {})
        address = active_address(slot_state)
        if address and client_by_address(address):
            place_window(address, slot_geometry(slot_name, meta))
    save_state(state)
    sync_runtime_from_state(state)
    sync_plugin_grid(state)


def apply_current_layout(state):
    meta = load_meta()
    mode = meta.get("mode", "grid")
    if mode == "grid":
        apply_grid_layout(state)
        return

    active_slots = slots_for_mode(mode)
    inactive_slots = inactive_slots_for_mode(mode)

    for slot_name in active_slots:
        slot_state = state.get(slot_name) or normalize_slot_state(slot_name, {})
        address = active_address(slot_state)
        if address and client_by_address(address):
            place_window(address, slot_geometry(slot_name, meta))

    for slot_name in inactive_slots:
        slot_state = state.get(slot_name) or normalize_slot_state(slot_name, {})
        address = active_address(slot_state)
        if address and client_by_address(address):
            park_window(address, slot_name, slot_state.get("active_profile", ALL_SLOTS[slot_name]["profile"]))

    save_state(state)
    sync_runtime_from_state(state)
    sync_plugin_grid(state)


def resize_grid(left_width, top_height, state):
    meta = load_meta()
    c = layout_constants()
    meta["grid_left_width"] = clamp(left_width, c["min_left_w"], c["max_left_w"])
    meta["grid_top_height"] = clamp(top_height, c["min_top_h"], c["max_top_h"])
    save_meta(meta)
    apply_current_layout(state)


def reset_layout(state):
    meta = load_meta()
    c = layout_constants()
    meta["grid_left_width"] = c["default_left_w"]
    meta["grid_top_height"] = c["default_top_h"]
    meta["mode"] = "grid"
    meta["expanded_slot"] = None
    meta["true_fullscreen_slot"] = None
    save_meta(meta)
    restore_grid(state)


def restore_side(side, state):
    current_mode = load_meta().get("mode", "grid")
    if current_mode == "half_both":
        if side == "left":
            enter_mode("half_right", state)
        else:
            enter_mode("half_left", state)
        return
    restore_grid(state)


def vault_profile(slot_name, app_id, slot_state, *, origin_layout=None, origin_direction=None):
    profile_data = slot_state.get("profiles", {}).get(app_id)
    if not profile_data:
        return
    address = profile_data.get("address")
    try:
        if address and client_by_address(address):
            park_window(address, slot_name, app_id)
    except Exception:
        pass
    vault = load_vault()
    vault["items"] = [
        item for item in vault["items"]
        if item.get("profile_id") != profile_data.get("profile_id")
    ]
    vault["items"].append(
        {
            "profile_id": profile_data.get("profile_id"),
            "app_id": app_id,
            "address": address,
            "origin_layout": origin_layout,
            "origin_panel": slot_name,
            "origin_direction": origin_direction,
            "created_at": int(time.time()),
        }
    )
    save_vault(vault)
    slot_state["profiles"].pop(app_id, None)
    if slot_state.get("active_profile") == app_id:
        slot_state["active_profile"] = ALL_SLOTS[slot_name]["profile"]
        slot_state["active_profile_id"] = None


def rebind_direction(layout_name, panel_name, direction_name, app_id):
    bindings = load_bindings()
    registry = load_registry().get("apps", {})
    if app_id not in registry:
        raise RuntimeError(f"unknown app: {app_id}")
    if layout_name == "grid":
        if panel_name not in bindings["grid"]:
            raise RuntimeError(f"unknown grid panel: {panel_name}")
        if direction_name not in bindings["grid"][panel_name]:
            raise RuntimeError(f"unknown direction: {direction_name}")
    elif layout_name == "half":
        if panel_name not in bindings["half"]:
            raise RuntimeError(f"unknown half panel: {panel_name}")
        if direction_name not in bindings["half"][panel_name]:
            raise RuntimeError(f"unknown direction: {direction_name}")
    else:
        raise RuntimeError(f"unknown layout: {layout_name}")

    current_app = bindings[layout_name][panel_name][direction_name]
    if current_app == app_id:
        return

    state = load_state()
    if layout_name == "grid":
        slot_name = panel_name
    else:
        slot_name = "half_left" if panel_name == "left" else "half_right"
    slot_state = state.setdefault(slot_name, normalize_slot_state(slot_name, {}))
    if current_app in slot_state.get("profiles", {}) and slot_state.get("active_profile") != current_app:
        vault_profile(
            slot_name,
            current_app,
            slot_state,
            origin_layout=layout_name,
            origin_direction=direction_name,
        )

    bindings[layout_name][panel_name][direction_name] = app_id
    save_bindings(bindings)
    save_state(state)
    sync_runtime_from_state(state)


def bindings_payload():
    return load_bindings()


def restore_vault_item(profile_id, layout_name, panel_name, direction_name):
    vault = load_vault()
    item = None
    remaining = []
    for entry in vault["items"]:
        if entry.get("profile_id") == profile_id:
            item = entry
        else:
            remaining.append(entry)
    if item is None:
        raise RuntimeError(f"vault profile not found: {profile_id}")

    app_id = item.get("app_id")
    bindings = load_bindings()
    if layout_name == "grid":
        if panel_name not in bindings["grid"]:
            raise RuntimeError(f"unknown grid panel: {panel_name}")
        bindings["grid"][panel_name][direction_name] = app_id
        slot_name = panel_name
    elif layout_name == "half":
        if panel_name not in bindings["half"]:
            raise RuntimeError(f"unknown half panel: {panel_name}")
        bindings["half"][panel_name][direction_name] = app_id
        slot_name = "half_left" if panel_name == "left" else "half_right"
    else:
        raise RuntimeError(f"unknown layout: {layout_name}")

    state = load_state()
    slot_state = state.setdefault(slot_name, normalize_slot_state(slot_name, {}))
    slot_state.setdefault("profiles", {})
    slot_state["profiles"][app_id] = {
        "address": item.get("address"),
        "profile_id": profile_id,
        "created_at": int(item.get("created_at") or time.time()),
    }

    save_bindings(bindings)
    save_state(state)
    sync_runtime_from_state(state)
    vault["items"] = remaining
    save_vault(vault)


def delete_vault_item(profile_id):
    vault = load_vault()
    remaining = [item for item in vault["items"] if item.get("profile_id") != profile_id]
    vault["items"] = remaining
    save_vault(vault)


def swap_slots(from_slot, to_slot, state):
    """Swap active windows between two grid slots."""
    if from_slot not in SLOTS:
        raise RuntimeError(f"unknown grid slot: {from_slot}")
    if to_slot not in SLOTS:
        raise RuntimeError(f"unknown grid slot: {to_slot}")
    if from_slot == to_slot:
        return

    from_state = state.get(from_slot) or normalize_slot_state(from_slot, {})
    to_state = state.get(to_slot) or normalize_slot_state(to_slot, {})

    from_addr = active_address(from_state)
    to_addr = active_address(to_state)
    from_profile = from_state.get("active_profile") or SLOTS[from_slot]["profile"]
    to_profile = to_state.get("active_profile") or SLOTS[to_slot]["profile"]

    if from_addr and client_by_address(from_addr):
        place_in_slot(from_addr, to_slot)
        if is_firefox_profile(from_profile):
            time.sleep(0.45)
            place_in_slot(from_addr, to_slot)

    if to_addr and client_by_address(to_addr):
        place_in_slot(to_addr, from_slot)
        if is_firefox_profile(to_profile):
            time.sleep(0.45)
            place_in_slot(to_addr, from_slot)

    from_profile_data = dict(from_state.get("profiles", {}).get(from_profile, {}))
    to_profile_data = dict(to_state.get("profiles", {}).get(to_profile, {}))

    from_state.setdefault("profiles", {})
    to_state.setdefault("profiles", {})

    from_state["profiles"].pop(from_profile, None)
    if to_profile_data:
        from_state["profiles"][to_profile] = to_profile_data
    from_state["active_profile"] = to_profile
    from_state["active_profile_id"] = to_profile_data.get("profile_id")

    to_state["profiles"].pop(to_profile, None)
    if from_profile_data:
        to_state["profiles"][from_profile] = from_profile_data
    to_state["active_profile"] = from_profile
    to_state["active_profile_id"] = from_profile_data.get("profile_id")

    state[from_slot] = from_state
    state[to_slot] = to_state
    save_state(state)
    sync_runtime_from_state(state)
    if load_meta().get("mode") == "grid":
        sync_plugin_grid(state)


def daemon():
    ensure_cache_dir()
    PID_FILE.write_text(f"{os.getpid()}\n")

    runtime = {}

    while True:
        if live_resize_active():
            time.sleep(POLL_INTERVAL)
            continue

        state = load_state()
        meta = load_meta()
        if not state:
            time.sleep(POLL_INTERVAL)
            continue

        for slot_name in state:
            runtime.setdefault(slot_name, {"drift_since": None, "fullscreen_state": (0, 0)})

        current_clients = clients()
        enforce_workspace_popup_policy(state, current_clients)
        now = time.monotonic()
        base_mode = meta.get("mode", "grid")
        if base_mode not in {"grid", "half_left", "half_right", "half_both"}:
            base_mode = "grid"
        active_slots = slots_for_mode(base_mode)
        parked_slots = inactive_slots_for_mode(base_mode)

        for slot_name, entry in state.items():
            address = active_address(entry)
            active_profile_name = entry.get("active_profile", ALL_SLOTS.get(slot_name, {}).get("profile"))
            client = client_by_address(address, current_clients, expected_classes=expected_classes(slot_name, active_profile_name))
            if client is None:
                # Hard safety rail: never respawn from the daemon.
                continue

            if meta.get("true_fullscreen_slot") == slot_name:
                if int(client.get("fullscreen", 0) or 0) != 0:
                    runtime[slot_name]["drift_since"] = None
                    continue
                meta["true_fullscreen_slot"] = None
                save_meta(meta)

            if meta.get("mode") == "expanded":
                if slot_name != meta.get("expanded_slot"):
                    if client.get("workspace", {}).get("id") == WORKSPACE_ID:
                        park_window(address, slot_name, entry["active_profile"])
                    runtime[slot_name]["drift_since"] = None
                    continue
                geom = expanded_geometry()
            else:
                if slot_name in parked_slots:
                    if client.get("workspace", {}).get("id") == WORKSPACE_ID:
                        park_window(address, slot_name, entry["active_profile"])
                    runtime[slot_name]["drift_since"] = None
                    continue
                if slot_name not in active_slots:
                    runtime[slot_name]["drift_since"] = None
                    continue
                else:
                    geom = slot_geometry(slot_name, meta)

            x, y = client["at"]
            w, h = client["size"]
            dx = x - geom["x"]
            dy = y - geom["y"]
            displaced = (
                abs(dx) > POSITION_TOLERANCE
                or abs(dy) > POSITION_TOLERANCE
                or abs(w - geom["w"]) > POSITION_TOLERANCE
                or abs(h - geom["h"]) > POSITION_TOLERANCE
            )
            current_fs = (
                int(client.get("fullscreen", 0) or 0),
                int(client.get("fullscreenClient", 0) or 0),
            )
            if displaced:
                if runtime[slot_name]["drift_since"] is None:
                    runtime[slot_name]["drift_since"] = now

                if now - runtime[slot_name]["drift_since"] >= RESTORE_DELAY:
                    place_window(address, geom)
                    runtime[slot_name]["drift_since"] = None
            else:
                runtime[slot_name]["drift_since"] = None

            if current_fs != runtime[slot_name]["fullscreen_state"]:
                runtime[slot_name]["fullscreen_state"] = current_fs
                if current_fs not in {(0, 0), (0, 2)}:
                    apply_slot_window_policy(address)
                    place_window(address, geom)

        time.sleep(POLL_INTERVAL)


def stop():
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, signal.SIGTERM)
        except (ValueError, OSError):
            pass
        PID_FILE.unlink(missing_ok=True)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: workspace1_manager.py [launch|daemon|stop|switch SLOT DIR|focus-slot SLOT|activate SLOT PROFILE|activate-half SIDE PROFILE|activate-half-app SIDE APP_ID|get-half-apps|list-apps|refresh-registry|get-bindings|rebind LAYOUT PANEL DIRECTION APP_ID|list-vault|restore-vault PROFILE_ID LAYOUT PANEL DIRECTION|delete-vault PROFILE_ID|swap-slots FROM_SLOT TO_SLOT|restore-side SIDE|toggle-expand-current|toggle-true-fullscreen-current|toggle-split-layout|ensure-half-layout SIDE|resize-grid LEFT_WIDTH TOP_HEIGHT|reset-layout|restore-grid|app-action ACTION APP_ID|install-app APP_ID|repair-app APP_ID|remove-app APP_ID|open-prefix APP_ID|open-logs|run-events|probe-exe EXE_PATH|launch-exe EXE_PATH [auto|bottles|proton|wine]|launch-exe-fallback EXE_PATH [auto|bottles|proton|wine]]")

    cmd = sys.argv[1]
    if cmd == "launch":
        launch()
    elif cmd == "daemon":
        daemon()
    elif cmd == "stop":
        stop()
    elif cmd == "switch":
        if len(sys.argv) != 4:
            raise SystemExit("usage: workspace1_manager.py switch SLOT DIRECTION")
        slot_name = sys.argv[2]
        direction_name = sys.argv[3]
        if slot_name not in ALL_SLOTS:
            raise SystemExit(f"unknown slot: {slot_name}")
        if direction_name not in {"left", "right", "up", "down"}:
            raise SystemExit(f"unknown direction: {direction_name}")
        state = load_state()
        if slot_name not in state:
            state[slot_name] = normalize_slot_state(slot_name, {})
        switch_profile(slot_name, direction_name, state)
    elif cmd == "focus-slot":
        if len(sys.argv) != 3:
            raise SystemExit("usage: workspace1_manager.py focus-slot SLOT")
        slot_name = sys.argv[2]
        state = load_state()
        focus_slot(slot_name, state)
    elif cmd == "toggle-expand-current":
        state = load_state()
        toggle_expand_current(state)
    elif cmd == "toggle-true-fullscreen-current":
        state = load_state()
        toggle_true_fullscreen_current(state)
    elif cmd == "activate":
        if len(sys.argv) != 4:
            raise SystemExit("usage: workspace1_manager.py activate SLOT PROFILE")
        slot_name = sys.argv[2]
        profile = sys.argv[3]
        if slot_name not in ALL_SLOTS:
            raise SystemExit(f"unknown slot: {slot_name}")
        state = load_state()
        if slot_name not in state:
            state[slot_name] = normalize_slot_state(slot_name, {})
        activate_profile(slot_name, profile, state)
    elif cmd == "toggle-split-layout":
        state = load_state()
        toggle_split_layout(state)
    elif cmd == "ensure-half-layout":
        if len(sys.argv) != 3:
            raise SystemExit("usage: workspace1_manager.py ensure-half-layout SIDE")
        side = sys.argv[2]
        if side not in {"left", "right"}:
            raise SystemExit(f"unknown side: {side}")
        state = load_state()
        ensure_half_layout(side, state)
    elif cmd == "activate-half":
        if len(sys.argv) != 4:
            raise SystemExit("usage: workspace1_manager.py activate-half SIDE PROFILE")
        side = sys.argv[2]
        profile = sys.argv[3]
        if side not in {"left", "right"}:
            raise SystemExit(f"unknown side: {side}")
        state = load_state()
        activate_half(side, profile, state)
    elif cmd == "activate-half-app":
        if len(sys.argv) != 4:
            raise SystemExit("usage: workspace1_manager.py activate-half-app SIDE APP_ID")
        side = sys.argv[2]
        app_id = sys.argv[3]
        state = load_state()
        activate_half_app(side, app_id, state)
    elif cmd == "get-half-apps":
        print(json.dumps(load_half_apps(), indent=2))
    elif cmd == "list-apps":
        print(json.dumps(build_registry().get("apps", {}), indent=2))
    elif cmd == "refresh-registry":
        print(json.dumps(build_registry(), indent=2))
    elif cmd == "get-bindings":
        print(json.dumps(bindings_payload(), indent=2))
    elif cmd == "get-layout-constants":
        c = layout_constants()
        print(json.dumps({
            "outer_left": c["outer_left"],
            "outer_right": c["outer_right"],
            "outer_top": c["outer_top"],
            "outer_bottom": c["outer_bottom"],
            "grid_column_gap": c["col_gap"],
            "grid_row_gap": c["row_gap"],
            "min_grid_left_width": c["min_left_w"],
            "max_grid_left_width": c["max_left_w"],
            "min_grid_top_height": c["min_top_h"],
            "max_grid_top_height": c["max_top_h"],
            "default_grid_left_width": c["default_left_w"],
            "default_grid_top_height": c["default_top_h"],
        }, indent=2))
    elif cmd == "rebind":
        if len(sys.argv) != 6:
            raise SystemExit("usage: workspace1_manager.py rebind LAYOUT PANEL DIRECTION APP_ID")
        layout_name = sys.argv[2]
        panel_name = sys.argv[3]
        direction_name = sys.argv[4]
        app_id = sys.argv[5]
        rebind_direction(layout_name, panel_name, direction_name, app_id)
    elif cmd == "list-vault":
        print(json.dumps(load_vault(), indent=2))
    elif cmd == "picker-prefs":
        print(json.dumps(load_picker_prefs(), indent=2))
    elif cmd == "favorite-app":
        if len(sys.argv) != 4:
            raise SystemExit("usage: workspace1_manager.py favorite-app APP_ID on|off")
        set_favorite_app(sys.argv[2], sys.argv[3] == "on")
    elif cmd == "mark-recent":
        if len(sys.argv) != 3:
            raise SystemExit("usage: workspace1_manager.py mark-recent APP_ID")
        mark_recent_app(sys.argv[2])
    elif cmd == "restore-vault":
        if len(sys.argv) != 6:
            raise SystemExit("usage: workspace1_manager.py restore-vault PROFILE_ID LAYOUT PANEL DIRECTION")
        restore_vault_item(
            sys.argv[2],
            sys.argv[3],
            sys.argv[4],
            sys.argv[5],
        )
    elif cmd == "delete-vault":
        if len(sys.argv) != 3:
            raise SystemExit("usage: workspace1_manager.py delete-vault PROFILE_ID")
        delete_vault_item(sys.argv[2])
    elif cmd == "swap-slots":
        if len(sys.argv) != 4:
            raise SystemExit("usage: workspace1_manager.py swap-slots FROM_SLOT TO_SLOT")
        from_slot = sys.argv[2]
        to_slot = sys.argv[3]
        if from_slot not in SLOTS:
            raise SystemExit(f"unknown grid slot: {from_slot}")
        if to_slot not in SLOTS:
            raise SystemExit(f"unknown grid slot: {to_slot}")
        state = load_state()
        swap_slots(from_slot, to_slot, state)
    elif cmd == "restore-side":
        if len(sys.argv) != 3:
            raise SystemExit("usage: workspace1_manager.py restore-side SIDE")
        side = sys.argv[2]
        if side not in {"left", "right"}:
            raise SystemExit(f"unknown side: {side}")
        state = load_state()
        restore_side(side, state)
    elif cmd == "resize-grid":
        if len(sys.argv) != 4:
            raise SystemExit("usage: workspace1_manager.py resize-grid LEFT_WIDTH TOP_HEIGHT")
        state = load_state()
        resize_grid(int(sys.argv[2]), int(sys.argv[3]), state)
    elif cmd == "reset-layout":
        state = load_state()
        reset_layout(state)
    elif cmd == "restore-grid":
        state = load_state()
        restore_grid(state)
    elif cmd == "app-action":
        if len(sys.argv) != 4:
            raise SystemExit("usage: workspace1_manager.py app-action launch|install|repair|remove APP_ID")
        action = sys.argv[2]
        if action not in {"launch", "install", "repair", "remove"}:
            raise SystemExit(f"unsupported action: {action}")
        run_app_action(sys.argv[3], action)
    elif cmd == "install-app":
        if len(sys.argv) != 3:
            raise SystemExit("usage: workspace1_manager.py install-app APP_ID")
        run_app_action(sys.argv[2], "install")
    elif cmd == "repair-app":
        if len(sys.argv) != 3:
            raise SystemExit("usage: workspace1_manager.py repair-app APP_ID")
        run_app_action(sys.argv[2], "repair")
    elif cmd == "remove-app":
        if len(sys.argv) != 3:
            raise SystemExit("usage: workspace1_manager.py remove-app APP_ID")
        run_app_action(sys.argv[2], "remove")
    elif cmd == "open-prefix":
        if len(sys.argv) != 3:
            raise SystemExit("usage: workspace1_manager.py open-prefix APP_ID")
        open_app_prefix(sys.argv[2])
    elif cmd == "open-logs":
        open_run_logs()
    elif cmd == "run-events":
        open_run_logs()
    elif cmd == "probe-exe":
        if len(sys.argv) != 3:
            raise SystemExit("usage: workspace1_manager.py probe-exe EXE_PATH")
        try:
            probe_exe(sys.argv[2])
        except Exception as exc:
            print(json.dumps({"status": "error", "message": str(exc)}, indent=2))
            raise SystemExit(1)
    elif cmd == "launch-exe":
        if len(sys.argv) not in {3, 4}:
            raise SystemExit("usage: workspace1_manager.py launch-exe EXE_PATH [auto|bottles|proton|wine]")
        runtime_mode = sys.argv[3] if len(sys.argv) == 4 else "auto"
        try:
            launch_exe_fallback(sys.argv[2], runtime_mode)
        except SystemExit:
            raise
        except Exception as exc:
            print(json.dumps({"status": "error", "message": str(exc)}, indent=2))
            raise SystemExit(1)
    elif cmd == "launch-exe-fallback":
        if len(sys.argv) not in {3, 4}:
            raise SystemExit("usage: workspace1_manager.py launch-exe-fallback EXE_PATH [auto|bottles|proton|wine]")
        runtime_mode = sys.argv[3] if len(sys.argv) == 4 else "auto"
        try:
            launch_exe_fallback(sys.argv[2], runtime_mode)
        except SystemExit:
            raise
        except Exception as exc:
            print(json.dumps({"status": "error", "message": str(exc)}, indent=2))
            raise SystemExit(1)
    else:
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
