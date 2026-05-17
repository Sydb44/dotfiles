#!/usr/bin/env bash
# Launches Grafana kiosk panel in a dedicated Firefox profile
set -euo pipefail

PROFILE_DIR="$HOME/.mozilla/firefox/workstation-profiles/grafana-ui"
DASHBOARD_URL="https://grafana.silion.dev/d/homelab-overview/homelab-overview?kiosk&refresh=30s"

# Warm up Grafana (helps with cold-start loading time)
curl -sf -o /dev/null --max-time 3 "$DASHBOARD_URL" 2>/dev/null || true

exec firefox \
  --new-instance \
  --profile "$PROFILE_DIR" \
  --new-window "$DASHBOARD_URL" 2>/dev/null
