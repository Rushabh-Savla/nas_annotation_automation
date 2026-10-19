#!/usr/bin/env bash
# ==============================================================================
# Central Annotation Platform - Database Restore Script
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <path_to_backup.sql or path_to_backup.sql.gz>"
    exit 1
fi

BACKUP_FILE="$1"
if [ ! -f "$BACKUP_FILE" ]; then
    echo "[ERROR] Backup file does not exist: $BACKUP_FILE"
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "[ERROR] .env file not found."
    exit 1
fi

source "$ENV_FILE"

echo "WARNING: Restoring will overwrite existing data in ${POSTGRES_DB:-annotation_db}."
read -r -p "Are you sure you want to proceed? [y/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Restore cancelled."
    exit 0
fi

echo "Stopping controller and worker services during restore..."
(cd "$PROJECT_ROOT" && docker compose stop controller sync_worker)

echo "Restoring database from: $BACKUP_FILE"
if [[ "$BACKUP_FILE" == *.gz ]]; then
    gunzip -c "$BACKUP_FILE" | (cd "$PROJECT_ROOT" && docker compose exec -T postgres psql -U "${POSTGRES_USER:-annotation_user}" -d "${POSTGRES_DB:-annotation_db}")
else
    (cd "$PROJECT_ROOT" && docker compose exec -T postgres psql -U "${POSTGRES_USER:-annotation_user}" -d "${POSTGRES_DB:-annotation_db}") < "$BACKUP_FILE"
fi

echo "Restarting services..."
(cd "$PROJECT_ROOT" && docker compose start controller sync_worker)

echo "[SUCCESS] Database restored successfully."

