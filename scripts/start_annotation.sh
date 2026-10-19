#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

checklocal "$ROOT"

show_review() {
    echo
    echo "=========================================================="
    echo "Batch annotation review"
    echo "=========================================================="
    "$SCRIPT_DIR/manager.py" review || true
}

ask_unannotated() {
    show_review
    echo
    echo "WARNING: Some images in this batch do not have annotations."
    echo "These images can be intentional background/negative images."
    echo "If you proceed, they will be accepted without JSON files."
    echo
    read -r -p "Proceed with upload and move to the next batch? [y/N]: " ANSWER
    case "${ANSWER,,}" in
        y|yes)
            "$SCRIPT_DIR/manager.py" approve yes
            return 0
            ;;
        *)
            "$SCRIPT_DIR/manager.py" approve no >/dev/null 2>&1 || true
            echo
            echo "Upload paused. The current batch remains safely on local storage."
            echo "Run this script again when you want to continue annotating the remaining images."
            return 1
            ;;
    esac
}

while true; do
    "$SCRIPT_DIR/sync_now.sh" >/dev/null 2>&1 || true

    if [ ! -L "$CURRENT" ]; then
        echo "No current batch. Annotation workflow is complete or waiting for setup."
        exit 0
    fi

    STATE_NOW="$(python3 "$SCRIPT_DIR/manager.py" status 2>/dev/null | sed -n 's/^Current batch: [0-9][0-9]* (\([^)]*\)).*/\1/p' | tail -n1 || true)"

    if [ "$STATE_NOW" = "AWAITING_APPROVAL" ]; then
        # User previously chose to wait. Reopen the same batch for more annotation.
        "$SCRIPT_DIR/manager.py" reopen >/dev/null
        STATE_NOW="ANNOTATING"
    elif [ "$STATE_NOW" = "REVIEW_REQUIRED" ]; then
        echo
        echo "Some annotation JSON files are invalid. They must be fixed before upload."
        "$SCRIPT_DIR/manager.py" review || true
        "$SCRIPT_DIR/manager.py" reopen >/dev/null
        STATE_NOW="ANNOTATING"
    fi

    BATCH="$(readlink -f "$CURRENT")"
    echo "Opening XAnyLabeling on local batch: $BATCH"
    echo "Annotate normally. Background images may intentionally remain unannotated."

    printf '%s\n' "$(basename "$BATCH")" > "$STATE/app_open_batch"
    "$XANYLABELING" "$CURRENT" &
    PID=$!
    printf '%s\n' "$PID" > "$APP_PID"

    cleanup() { rm -f "$APP_PID"; }
    trap cleanup EXIT INT TERM
    wait "$PID" || true
    cleanup
    trap - EXIT INT TERM

    "$SCRIPT_DIR/close_batch.sh" >/dev/null 2>&1 || true
    "$SCRIPT_DIR/sync_now.sh" >/dev/null 2>&1 || true

    STATE_NOW="$(python3 "$SCRIPT_DIR/manager.py" status 2>/dev/null | sed -n 's/^Current batch: [0-9][0-9]* (\([^)]*\)).*/\1/p' | tail -n1 || true)"

    case "$STATE_NOW" in
        AWAITING_APPROVAL)
            if ! ask_unannotated; then
                exit 0
            fi
            ;;
        REVIEW_REQUIRED)
            echo
            echo "The batch contains invalid annotation JSON files."
            echo "They must be corrected before the batch can be uploaded."
            "$SCRIPT_DIR/manager.py" review || true
            "$SCRIPT_DIR/manager.py" reopen >/dev/null
            continue
            ;;
    esac

    "$SCRIPT_DIR/sync_now.sh" >/dev/null 2>&1 || true

    while [ -L "$CURRENT" ]; do
        STATE_NOW="$(python3 "$SCRIPT_DIR/manager.py" status 2>/dev/null | sed -n 's/^Current batch: [0-9][0-9]* (\([^)]*\)).*/\1/p' | tail -n1 || true)"
        case "$STATE_NOW" in
            SYNCED|CLEANED)
                break
                ;;
            CONFLICT)
                echo "Batch has a conflict. Resolve it, then synchronization will continue." >&2
                sleep 10
                ;;
            AWAITING_APPROVAL)
                if ! ask_unannotated; then
                    exit 0
                fi
                ;;
            REVIEW_REQUIRED)
                echo "Batch has invalid annotation JSON files. Reopening XAnyLabeling." >&2
                "$SCRIPT_DIR/manager.py" reopen >/dev/null
                break
                ;;
            ANNOTATING|UPLOAD_PENDING|DOWNLOADING)
                "$SCRIPT_DIR/sync_now.sh" >/dev/null 2>&1 || true
                sleep 10
                ;;
            *)
                break
                ;;
        esac
    done

done
