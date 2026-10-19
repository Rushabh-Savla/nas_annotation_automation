#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

for file in "$SCRIPT_DIR"/*.sh; do
    bash -n "$file"
done
python3 -m py_compile "$SCRIPT_DIR/manager.py"
PYTHONPATH="$PROJECT_DIR" python3 -m unittest discover -s "$PROJECT_DIR/tests" -v

echo "All local tests passed."
