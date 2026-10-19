#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONF="$PROJECT_DIR/config.env"

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
print(Path(values.get('ROOT','')).expanduser().resolve() if values.get('ROOT') else '')
PYCFG
)"

if [ -z "$ROOT" ] || [ "$ROOT" = "/" ] || [ "$ROOT" = "$HOME" ] || [ "$ROOT" = "$PROJECT_DIR" ]; then
    echo "[ERROR] Unsafe or empty ROOT path; refusing to delete: ${ROOT:-<empty>}" >&2
    exit 1
fi

echo "This will permanently delete the local workspace and any unsynchronized annotations:"
echo "  $ROOT"
read -r -p 'Type DELETE WORKSPACE to continue: ' CONFIRM
if [ "$CONFIRM" != "DELETE WORKSPACE" ]; then
    echo "Cancelled. Nothing was deleted."
    exit 0
fi

# Remove/disable services first; uninstall.sh deliberately does not create ROOT.
bash "$SCRIPT_DIR/uninstall.sh"
# Refuse to follow a symlink as the configured root.
if [ -L "$ROOT" ]; then
    echo "[ERROR] ROOT is a symlink; refusing recursive deletion: $ROOT" >&2
    exit 1
fi
if [ -e "$ROOT" ]; then
    rm -rf -- "$ROOT"
fi
echo "Workspace removed: $ROOT"
echo "The workspace will be recreated only when you explicitly run an operational command or reinstall/start the workflow."
