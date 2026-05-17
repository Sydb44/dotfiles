#!/usr/bin/env python3
# Workspace 3: the ops dashboard. Four apps, launched once and moved onto
# workspace 3 by tracked address (not windowrule title-matching, which
# would be fragile against any other Firefox window sharing a title
# fragment). Placement is a one-shot symmetric 2x2 float layout computed
# from the real monitor geometry at launch time - it reuses
# workspace1_manager.py's own monitor-detection so it can't regress into
# the same hardcoded-2560x1440 bug that hit the main grid. There is no
# persistent daemon for this workspace: it's a glance-and-leave surface,
# not something dragged/resized live, so static placement is enough.
#
# Grafana and Uptime Kuma reuse the existing registry apps
# (workstation_apps.json) rather than hand-rolled Firefox invocations - the
# grafana entry runs scripts/grafana-launch.sh, which opens the actual
# homelab-overview dashboard in kiosk mode with a curl warmup, not just a
# bare URL.
import importlib.util
import subprocess
import sys
from pathlib import Path

HYPR_DIR = Path.home() / ".config/hypr"
spec = importlib.util.spec_from_file_location("workspace1_manager", HYPR_DIR / "workspace1_manager.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

WORKSPACE_ID = 3
FIREFOX_PROFILE_ROOT = Path.home() / ".mozilla/firefox/workstation-profiles"


def ensure_dashboard_profile(name):
    profile_dir = FIREFOX_PROFILE_ROOT / name
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "user.js").write_text(
        '\n'.join([
            'user_pref("browser.startup.page", 1);',
            'user_pref("browser.sessionstore.resume_from_crash", false);',
            'user_pref("browser.tabs.warnOnClose", false);',
            "",
        ])
    )
    return profile_dir


def registry_launch_argv(app_id):
    registry = m.load_registry().get("apps", {})
    entry = registry.get(app_id)
    if not entry:
        raise RuntimeError(f"app '{app_id}' not found in workstation_apps.json registry")
    return m.resolve_app_action(entry, "launch")["argv"]


def quadrant_rects():
    c = m.layout_constants()
    col_w = (c["sw"] - c["outer_left"] - c["outer_right"] - c["col_gap"]) // 2
    row_h = (c["sh"] - c["outer_top"] - c["outer_bottom"] - c["row_gap"]) // 2
    ox, oy = c["sx"] + c["outer_left"], c["sy"] + c["outer_top"]
    return {
        "top_left": {"x": ox, "y": oy, "w": col_w, "h": row_h},
        "top_right": {"x": ox + col_w + c["col_gap"], "y": oy, "w": col_w, "h": row_h},
        "bottom_left": {"x": ox, "y": oy + row_h + c["row_gap"], "w": col_w, "h": row_h},
        "bottom_right": {"x": ox + col_w + c["col_gap"], "y": oy + row_h + c["row_gap"], "w": col_w, "h": row_h},
    }


def spawn(argv):
    env = m.hyprland_env()[0]
    return subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, env=env)


def place(address, rect):
    m.dispatch("movetoworkspacesilent", f"{WORKSPACE_ID},address:{address}")
    m.dispatch("setfloating", f"address:{address}")
    m.dispatch("resizewindowpixel", f"exact {rect['w']} {rect['h']},address:{address}")
    m.dispatch("movewindowpixel", f"exact {rect['x']} {rect['y']},address:{address}")


def find_existing_by_profile(profile_substr):
    # grafana-ui/uptime-kuma-ui are pre-existing dedicated profiles this
    # rice already uses elsewhere (they were live as slot content on the
    # old grid). Firefox profile-locks a directory to one running process,
    # so if one of these is already alive we must move it, not spawn a
    # second instance against the same profile (which would just fail).
    for c in m.clients():
        pid = c.get("pid")
        if not pid or not c.get("mapped"):
            continue
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="ignore")
        except OSError:
            continue
        if profile_substr in cmdline:
            return c.get("address")
    return None


def launch_and_place(slot_name, argv, rects):
    proc = spawn(argv)
    address = m.get_addr_by_pid(proc.pid)
    place(address, rects[slot_name])
    return address


def ensure_and_place(slot_name, profile_substr, argv, rects):
    address = find_existing_by_profile(profile_substr)
    if address is None:
        proc = spawn(argv)
        address = m.get_addr_by_pid(proc.pid)
    place(address, rects[slot_name])
    return address


def main():
    existing = [c for c in m.clients() if c.get("class") == "ws3-cluster"]
    if existing:
        print("workspace 3 already has a live cluster pane - not spawning duplicates. "
              "Close its windows first if you want to relaunch.", file=sys.stderr)
        raise SystemExit(1)

    rects = quadrant_rects()
    gitea_profile = ensure_dashboard_profile("gitea-actions-ui")

    launch_and_place(
        "top_left",
        ["kitty", "--class", "ws3-cluster", "-T", "ws3-cluster",
         "--session", str(Path.home() / ".config/kitty/sessions/ws3-cluster.kitty-session")],
        rects,
    )
    ensure_and_place("top_right", "workstation-profiles/grafana-ui", registry_launch_argv("grafana"), rects)
    ensure_and_place("bottom_left", "workstation-profiles/uptime-kuma-ui", registry_launch_argv("uptime-kuma"), rects)
    ensure_and_place(
        "bottom_right",
        "workstation-profiles/gitea-actions-ui",
        ["firefox", "--new-instance", "--profile", str(gitea_profile),
         "--new-window", "https://git.silion.dev/syd/homelab-ansible/actions"],
        rects,
    )


if __name__ == "__main__":
    main()
