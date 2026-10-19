#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/common.sh"

echo "Checking $REMOTE:$DATASET"
if timeout 20 "$RCLONE_BIN" lsf "$REMOTE:$DATASET" --max-depth 1 --files-only >/dev/null; then
    echo "NAS: CONNECTED"
    exit 0
fi
echo "NAS: UNAVAILABLE" >&2
exit 1
