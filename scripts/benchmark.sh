#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/common.sh"

echo "=== Local batch resource snapshot ==="
df -h "$ROOT"
free -h
printf '\nProcess snapshot:\n'
ps -eo pid,ppid,%cpu,%mem,rss,etime,cmd --sort=-%mem | head -20
printf '\nCurrent batch status:\n'
"$SCRIPT_DIR/status.sh"

cat <<MSG

This benchmark does not fabricate NAS results. For real validation, record the same snapshot during:
  1. batch download
  2. annotation of a batch
  3. batch upload
  4. NAS outage/recovery

Use on Linux when available:
  pidstat -r -u -d 1
  iostat -xz 1
  nload or ifstat
  journalctl --user -u batch-manager.service -f
MSG
