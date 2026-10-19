#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONF="$PROJECT_DIR/config.env"
UNIT_DIR="$HOME/.config/systemd/user"

if [ ! -f "$CONF" ]; then
    echo "[ERROR] Missing $CONF" >&2
    exit 1
fi
# shellcheck disable=SC1090
source "$CONF"
ROOT="${ROOT/#\~/$HOME}"
REMOTE="${REMOTE:?REMOTE is required}"
DATASET="${DATASET:?DATASET is required}"
RCLONE_BIN="${RCLONE_BIN:-rclone}"

mkdir -p "$UNIT_DIR" "$ROOT/state" "$ROOT/batches" "$ROOT/backups" "$ROOT/logs" "$ROOT/tmp"

FS="$(findmnt -T "$ROOT" -o FSTYPE -n 2>/dev/null || true)"
case "$FS" in
    cifs|nfs|nfs4|fuse.rclone|fuse.sshfs|sshfs)
        echo "[ERROR] ROOT is on network filesystem $FS: $ROOT" >&2
        exit 1 ;;
esac

for CMD in python3 "$RCLONE_BIN" systemctl findmnt flock; do
    command -v "$CMD" >/dev/null 2>&1 || { echo "[ERROR] Missing command: $CMD" >&2; exit 1; }
done

"$RCLONE_BIN" version >/dev/null 2>&1 || { echo "[ERROR] Rclone is not working." >&2; exit 1; }

echo "[1/3] Testing NAS access..."
timeout 20 "$RCLONE_BIN" lsf "$REMOTE:$DATASET" --max-depth 1 --files-only >/dev/null || {
    echo "[ERROR] Cannot access $REMOTE:$DATASET" >&2
    exit 1
}

chmod +x "$SCRIPT_DIR"/*.sh "$SCRIPT_DIR"/*.py

cat > "$UNIT_DIR/batch-manager.service" <<EOF
[Unit]
Description=Controlled XAnyLabeling Batch Manager

[Service]
Type=oneshot
ExecStart=$PROJECT_DIR/scripts/manager.sh step
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
CPUWeight=20
IOWeight=20
TasksMax=16
NoNewPrivileges=yes
PrivateTmp=yes
UMask=0077
TimeoutStartSec=45min
EOF

cat > "$UNIT_DIR/batch-manager.timer" <<EOF
[Unit]
Description=Run XAnyLabeling batch manager

[Timer]
OnBootSec=30s
OnUnitActiveSec=1min
RandomizedDelaySec=5s
Persistent=true

[Install]
WantedBy=timers.target
EOF

cat > "$UNIT_DIR/batch-cleanup.service" <<EOF
[Unit]
Description=Clean synchronized annotation backups

[Service]
Type=oneshot
ExecStart=$PROJECT_DIR/scripts/cleanup.sh
Nice=15
IOSchedulingClass=best-effort
IOSchedulingPriority=7
CPUWeight=10
IOWeight=10
TasksMax=8
NoNewPrivileges=yes
PrivateTmp=yes
UMask=0077
TimeoutStartSec=10min
EOF

cat > "$UNIT_DIR/batch-cleanup.timer" <<EOF
[Unit]
Description=Run annotation backup cleanup

[Timer]
OnBootSec=15min
OnUnitActiveSec=15min
RandomizedDelaySec=30s
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now batch-manager.timer batch-cleanup.timer

echo
echo "=========================================="
echo "Installation complete"
echo "=========================================="
echo "Config:          $CONF"
echo "Local workspace: $ROOT"
echo "Remote:          $REMOTE:$DATASET"
echo
echo "Edit ONLY this file to change settings:"
echo "  $CONF"
echo
echo "Then the next manager run automatically reads the new values."
echo
echo "Start annotation:"
echo "  $SCRIPT_DIR/start_annotation.sh"
