#!/usr/bin/env python3

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


MANAGER = str(Path.home() / ".config" / "hypr" / "workspace1_manager.py")


def normalize_input(value):
    raw = str(value or "").strip()
    if raw.startswith("file://"):
        parsed = urlparse(raw)
        raw = unquote(parsed.path)
    return str(Path(raw).expanduser())


def notify(title, message, urgency="normal"):
    subprocess.run(
        ["notify-send", "-u", urgency, title, message],
        check=False,
        capture_output=True,
        text=True,
    )


def launch_one(exe_path):
    cmd = [MANAGER, "launch-exe", exe_path, "auto"]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.stdout.strip():
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = None
    else:
        payload = None

    if result.returncode == 0 and payload and payload.get("status") == "ok":
        chosen = payload.get("selected_runtime", "unknown")
        notify("Workstation EXE", f"Launched with {chosen}: {Path(exe_path).name}")
        return 0

    reason = "failed to launch"
    if payload and payload.get("attempts"):
        last_attempt = payload["attempts"][-1]
        reason = f"{last_attempt.get('runtime', 'runtime')}: {last_attempt.get('reason', 'unknown error')}"
    elif result.stderr.strip():
        reason = result.stderr.strip().splitlines()[-1]
    notify("Workstation EXE", f"{Path(exe_path).name}: {reason}", "critical")
    return 1


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: workstation_exe_open.py <path-or-uri> [more...]")
    exit_code = 0
    for arg in sys.argv[1:]:
        path = normalize_input(arg)
        exit_code = max(exit_code, launch_one(path))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
