#!/usr/bin/env bash
# ==============================================================================
# Central Platform Pytest Suite Runner
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Running Central Platform Pytest Suite ==="
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python3"
if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

PYTEST_BIN="$PROJECT_ROOT/.venv/bin/pytest"
if [ ! -f "$PYTEST_BIN" ]; then
    PYTEST_BIN="pytest"
fi

PYTHONPATH="$PROJECT_ROOT" "$PYTEST_BIN" "$PROJECT_ROOT/tests_central" -v

echo "[SUCCESS] All central platform tests passed."

