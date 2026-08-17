#!/usr/bin/env python3
"""check_updates.py -- one-shot OPNsense firmware status report.

Fallback for when the opnsense MCP server is not connected. Read-only: reads
firmware status via the REST API and never triggers or mutates anything.

Runs from mcp/.venv and imports the MCP package so config loading, version
state, batch classification, and repo-error detection have a single source of
truth. The report is deliberately assembled from the same helpers the
check_updates MCP tool uses (_version_state, batch_summary, _update_lines,
_repo_error) rather than re-deriving any of it here.
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# The skill lives at <repo>/.claude/skills/opnsense-check-updates/
# Project root is three levels up: skill -> skills -> .claude -> repo
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
MCP_DIR = os.path.join(PROJECT_ROOT, "mcp")
sys.path.insert(0, MCP_DIR)

import httpx  # noqa: E402  (from the mcp venv)
from src.opnsense_mcp.api import OPNsenseAPI  # noqa: E402
from src.opnsense_mcp.config import Config  # noqa: E402
from src.opnsense_mcp.tools import (  # noqa: E402
    _repo_error,
    _update_lines,
    _version_state,
    batch_summary,
)


def report(api):
    """Build the status report lines from one firmware_status() call."""
    status = api.firmware_status()
    vs = _version_state(status)
    batch = batch_summary(status)

    lines = [f"Current version: {vs['current'] or 'unknown'}"]
    lines.extend(_update_lines(vs, batch))

    if vs["fw_status"] == "upgrade":
        lines.append(f"Major upgrade available: {vs['next_major']}")
    elif vs["next_major"]:
        lines.append(f"Next major version: {vs['next_major']} (planned)")
    else:
        lines.append("Major upgrade: none available")

    lines.append(f"Status: {status.get('status_msg', '') or 'no updates'}")
    if _repo_error(status):
        lines.append("WARNING: repo unreachable")

    lines.append(f"Reboot: {api.check_needs_reboot()['explanation']}")
    return lines


def main():
    try:
        config = Config.from_env()
    except ValueError as exc:
        print(f"ERROR: {exc} (see mcp/SETUP.md)", file=sys.stderr)
        return 2

    api = OPNsenseAPI(config)
    try:
        print("\n".join(report(api)))
    except httpx.ConnectError:
        print(f"ERROR: cannot reach the firewall at {config.url}", file=sys.stderr)
        return 1
    except httpx.TimeoutException:
        print("ERROR: timed out talking to the firewall", file=sys.stderr)
        return 1
    except httpx.HTTPStatusError as exc:
        print(f"ERROR: HTTP {exc.response.status_code} from the firewall", file=sys.stderr)
        return 1
    finally:
        api.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
