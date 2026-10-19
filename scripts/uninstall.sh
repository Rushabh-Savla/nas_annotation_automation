#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONF="$PROJECT_DIR/config.env"
UNIT_DIR="$HOME/.config/systemd/user"

# Intentionally do NOT source common.sh here: it used to mkdir the workspace,
# which made uninstall itself recreate the directory the user wanted to remove.
if [ ! -f "$CONF" ]; then
    echo "[ERROR] Missing configuration: $CONF" >&2
    exit 1
fi
ROOT="$(python3 - "$CONF" <<'PYCFG'
import os, sys
from pathlib import Path
values = {}
for line in Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1); v=v.strip()
    if len(v)>=2 and v[0]==v[-1] and v[0] in ('\"', "'"): v=v[1:-1]
    values[k.strip()] = os.path.expandvars(os.path.expanduser(v))
print(values.get('ROOT',''))
PYCFG
)"

# Stop timers and any currently running oneshot services before removing units.
for UNIT in batch-manager.timer batch-cleanup.timer batch-manager.service batch-cleanup.service; do
    systemctl --user disable --now "$UNIT" 2>/dev/null || true
done
systemctl --user daemon-reload 2>/dev/null || true
rm -f "$UNIT_DIR/batch-manager.timer" "$UNIT_DIR/batch-cleanup.timer" \
      "$UNIT_DIR/batch-manager.service" "$UNIT_DIR/batch-cleanup.service"
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user reset-failed 2>/dev/null || true

echo "Background annotation timers/services removed."
echo "Workspace was NOT deleted: ${ROOT:-<ROOT not configured>}"
echo "Configuration was NOT deleted: $CONF"
echo "You can now remove the workspace manually, or run scripts/remove_workspace.sh."
