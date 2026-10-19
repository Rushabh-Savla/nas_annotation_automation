#!/usr/bin/env bash
set -euo pipefail
if [ $# -ne 2 ]; then
    echo "Usage: $0 <relative-json-path> <local|remote>" >&2
    exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/common.sh"
exec "$SCRIPT_DIR/manager.sh" resolve "$1" "$2"
