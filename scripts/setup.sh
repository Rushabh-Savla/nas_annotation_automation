#!/usr/bin/env bash
# ==============================================================================
# Central Annotation Platform - Setup & Bootstrap Script (Linux / Ubuntu)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"
SECRETS_DIR="$PROJECT_ROOT/secrets"

echo "=== [1/6] Checking Prerequisites ==="
if ! command -v docker >/dev/null 2>&1; then
    echo "[ERROR] Docker is not installed or not in PATH."
    echo "To install Docker on Ubuntu, visit: https://docs.docker.com/engine/install/ubuntu/"
    echo "Example commands: sudo apt update && sudo apt install -y docker.io docker-compose-v2"
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "[ERROR] Docker Compose plugin is missing."
    echo "Please install docker-compose-plugin: sudo apt install -y docker-compose-plugin"
    exit 1
fi

echo "Docker: $(docker --version)"
echo "Docker Compose: $(docker compose version)"

echo "=== [2/6] Initializing Secrets & Configuration ==="
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

if [ -f "$ENV_FILE" ]; then
    echo ".env already exists. Preserving existing configuration."
    chmod 600 "$ENV_FILE"
else
    echo "Generating secure .env configuration..."
    (
        umask 077
        APP_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)
        DB_PASS=$(python3 -c "import secrets; print(secrets.token_hex(24))" 2>/dev/null || openssl rand -hex 24)
        BOOTSTRAP_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -hex 24)

        cat > "$ENV_FILE" <<EOF
APP_ENV=production
APP_SECRET_KEY=${APP_SECRET}
PUBLIC_BASE_URL=http://localhost:8000
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000

POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=annotation_db
POSTGRES_USER=annotation_user
POSTGRES_PASSWORD=${DB_PASS}
DATABASE_URL=postgresql://annotation_user:${DB_PASS}@postgres:5432/annotation_db

BOOTSTRAP_ADMIN_TOKEN=${BOOTSTRAP_TOKEN}

DEFAULT_BATCH_SIZE=100
MAX_ASSIGNMENT_COUNT=10000
HEARTBEAT_INTERVAL_SECONDS=30
LEASE_DURATION_SECONDS=120
LEASE_GRACE_SECONDS=60

SUPPORTED_IMAGE_EXTENSIONS=jpg,jpeg,png,bmp,webp,tif,tiff
EXCLUDED_PATTERNS=.Trash/**,**/.Trash/**,**/.DS_Store,**/.thumbnails/**,**/tmp/**

DEFAULT_REMOTE_NAME=annotation_nas
DATASET_ROOT=ai_data_collection
ANNOTATION_WORKSPACE_ROOT=annotation_workspaces
ANNOTATION_OUTPUT_POLICY=WORKSPACE

RCLONE_CONFIG_PATH=/secrets/rclone.conf
RCLONE_BIN=rclone
RCLONE_TRANSFERS=2
RCLONE_CHECKERS=2
RCLONE_SFTP_CONCURRENCY=2
RCLONE_BANDWIDTH=25M
RCLONE_TIMEOUT=30s
RCLONE_CONNECT_TIMEOUT=10s
TRANSFER_TIMEOUT_SECONDS=1800

MAX_UPLOAD_SIZE_BYTES=10485760
STAGING_MAX_DISK_PERCENT=90
EOF
    )
    chmod 600 "$ENV_FILE"
    echo ".env created with secure permissions (chmod 600)."
fi

echo "=== [3/6] Validating Docker Compose Configuration ==="
(cd "$PROJECT_ROOT" && docker compose config >/dev/null)
echo "Docker Compose configuration is valid."

echo "=== [4/6] Checking NAS Credentials ==="
if [ ! -f "$SECRETS_DIR/rclone.conf" ]; then
    echo "[NOTICE] secrets/rclone.conf not found."
    echo "If real NAS access is required, place your rclone.conf in: $SECRETS_DIR/rclone.conf"
    echo "The platform will start and can operate in mock/local mode until credentials are provided."
    touch "$SECRETS_DIR/rclone.conf"
    chmod 600 "$SECRETS_DIR/rclone.conf"
fi

echo "=== [5/6] Building & Starting PostgreSQL Database ==="
(cd "$PROJECT_ROOT" && docker compose up -d postgres)

echo "Waiting for PostgreSQL healthcheck..."
until (cd "$PROJECT_ROOT" && docker compose ps postgres | grep -q "healthy"); do
    sleep 2
done
echo "PostgreSQL is ready and healthy."

echo "=== [6/6] Running Database Migrations & Starting Services ==="
(cd "$PROJECT_ROOT" && docker compose run --rm migrate)
(cd "$PROJECT_ROOT" && docker compose up -d controller sync_worker)

echo ""
echo "=============================================================================="
echo "Central Annotation Platform is running successfully!"
echo "Master Web Dashboard: http://localhost:8000"
echo "API Documentation:    http://localhost:8000/docs"
echo ""
echo "Next Steps:"
echo "1. Create initial administrator (hidden password entry):"
echo "   docker compose exec controller python -m controller.app.cli create-admin"
echo ""
echo "2. Check service status:"
echo "   docker compose ps"
echo ""
echo "3. Run system diagnostic health check:"
echo "   docker compose exec controller python -m controller.app.cli doctor"
echo "=============================================================================="

