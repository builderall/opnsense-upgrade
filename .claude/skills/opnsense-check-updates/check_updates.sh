#!/usr/bin/env bash
# check_updates.sh -- thin launcher for check_updates.py.
#
# The report logic lives in check_updates.py, which runs from mcp/.venv and
# imports the MCP package so config loading, version state, and repo-error
# detection have a single source of truth. This wrapper exists so the skill
# and docs keep a stable entry point.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VENV_PY="$ROOT/mcp/.venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
    echo "ERROR: mcp venv python not found: $VENV_PY (see mcp/SETUP.md)"
    exit 1
fi

exec "$VENV_PY" "$SCRIPT_DIR/check_updates.py" "$@"
