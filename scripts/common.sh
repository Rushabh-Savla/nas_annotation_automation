#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="$PROJECT_DIR/config.env"

if [ ! -f "$CONF" ]; then
    echo "[ERROR] Missing configuration: $CONF" >&2
    exit 1
fi
# shellcheck disable=SC1090
source "$CONF"

: "${ROOT:?ROOT is required in config.env}"
: "${REMOTE:?REMOTE is required in config.env}"
: "${DATASET:?DATASET is required in config.env}"

RCLONE_BIN="${RCLONE_BIN:-rclone}"
ROOT="${ROOT/#\~/$HOME}"
ROOT="$(printf "%s" "$ROOT")"
STATE="$ROOT/state"
DB="$STATE/state.db"
BATCHES="$ROOT/batches"
BACKUPS="$ROOT/backups"
CURRENT="$ROOT/current"
LOGS="$ROOT/logs"
TMP="$ROOT/tmp"
APP_PID="$STATE/app.pid"
LOCK="$STATE/manager.lock"

# Do not create the workspace while merely loading shared configuration.
# The Python manager creates it only when an operational command is explicitly run.

say() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
    say "ERROR: $*" >&2
    exit 1
}

checklocal() {
    local fs
    fs="$(findmnt -T "$1" -o FSTYPE -n 2>/dev/null || true)"
    case "$fs" in
        cifs|nfs|nfs4|fuse.rclone|fuse.sshfs|sshfs)
            fail "ROOT is on a network filesystem ($fs). Use local SSD/HDD storage: $1" ;;
    esac
}

notify() {
    local title="$1" text="$2"
    if [ "${NOTIFY:-1}" = "1" ] && command -v notify-send >/dev/null 2>&1; then
        notify-send "$title" "$text" >/dev/null 2>&1 || true
    fi
}
