#!/usr/bin/env bash
# ==============================================================================
# Central Annotation Platform - Database Backup Script
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "[ERROR] .env file not found."
    exit 1
fi

source "$ENV_FILE"

BACKUP_DIR="${1:-$HOME/annotation_backups}"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DUMP_FILE="$BACKUP_DIR/annotation_db_${TIMESTAMP}.sql"

echo "Creating PostgreSQL backup to: $DUMP_FILE"
(cd "$PROJECT_ROOT" && docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-annotation_user}" -d "${POSTGRES_DB:-annotation_db}") > "$DUMP_FILE"

gzip "$DUMP_FILE"
echo "[SUCCESS] Backup created: ${DUMP_FILE}.gz ($(du -h "${DUMP_FILE}.gz" | cut -f1))"

