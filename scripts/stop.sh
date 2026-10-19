#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONF="$PROJECT_DIR/config.env"
UNIT_DIR="$HOME/.config/systemd/user"

if [ ! -f "$CONF" ]; then
    echo "[ERROR] Missing configuration: $CONF" >&2
    exit 1
fi

# Read ROOT without sourcing common.sh, which must not create any directories.
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

# Disable timers so they cannot wake up again after this command exits.
for UNIT in batch-manager.timer batch-cleanup.timer; do
    systemctl --user disable --now "$UNIT" 2>/dev/null || true
done
# Stop any currently running oneshot jobs too.
for UNIT in batch-manager.service batch-cleanup.service; do
    systemctl --user stop "$UNIT" 2>/dev/null || true
done

# If XAnyLabeling was launched by this project and its PID file exists, stop it.
PID_FILE="$ROOT/state/app.pid"
if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ "$PID" =~ ^[0-9]+$ ]] && kill -0 "$PID" 2>/dev/null; then
        kill -TERM "$PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE" 2>/dev/null || true
fi

echo "Annotation background timers and services have been stopped and disabled."
echo "Workspace has been preserved: ${ROOT:-<ROOT not configured>}"
echo "Delete it only after confirming any unsynchronized annotations are backed up."
echo "To remove timers/unit files too, run: bash \"$SCRIPT_DIR/uninstall.sh\""
