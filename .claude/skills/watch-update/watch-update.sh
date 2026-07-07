#!/usr/bin/env bash
# watch-update.sh -- thin launcher for watch_update.py.
#
# The watcher logic lives in watch_update.py, which runs from mcp/.venv and
# imports the MCP package so repo-error detection, config loading, and API
# access have a single source of truth. This wrapper exists so the Monitor
# command, SKILL.md, and the PostToolUse hook keep a stable entry point.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VENV_PY="$ROOT/mcp/.venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
    echo "ERROR: mcp venv python not found: $VENV_PY (see mcp/SETUP.md)"
    exit 1
fi

exec "$VENV_PY" "$SCRIPT_DIR/watch_update.py" "$@"
