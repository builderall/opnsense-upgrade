---
name: opnsense-check-updates
description: >
  Quick firmware-status check for OPNsense via a direct script against the mcp package,
  bypassing the MCP tool-call layer. Use when the opnsense MCP server fails to connect or
  load, or as a fast one-shot check without an MCP round trip.
---

# Check OPNsense Firmware Updates (MCP server unavailable)

Use when the `opnsense` MCP server isn't connected (e.g. it failed to load this session)
and the user wants a firmware/update check anyway. If the MCP server is connected, prefer
its `check_updates` / `get_version` tools directly instead of this script -- it exists as a
fallback that talks to the same `mcp/` package without going through the MCP protocol.

## Quick Command

```bash
<project-root>/.claude/skills/opnsense-check-updates/check_updates.sh
```

Replace `<project-root>` with the repo root (e.g. `~/projects/opnsense-upgrade`). The
launcher resolves its own paths, so it runs from any working directory.

`check_updates.sh` is a thin launcher; the report logic is `check_updates.py`, run from
`mcp/.venv`. It imports the MCP package (`Config`, `OPNsenseAPI`, `_version_state`,
`batch_summary`, `_update_lines`, `_repo_error`), so the output matches the `check_updates`
MCP tool instead of re-deriving version state or repo-error detection separately.

## Output Format

- Current version (with pkg revision stripped for comparison)
- Minor update status (up to date or pending with package list)
- Major upgrade availability
- Repository status warning if unreachable
- Reboot status with explanation (stale vs genuine)

## Common Pitfalls

- Running `check_updates.py` with system `python3` instead of through the launcher -- will
  fail with `ModuleNotFoundError` unless the same packages happen to be installed globally.
  The launcher exists to prevent this; invoke it rather than the `.py` directly.
- A missing `mcp/.venv` makes the launcher exit 1 with the venv path it looked for; see
  `mcp/SETUP.md`.
- Missing or incomplete `mcp/.env` exits 2 with the `Config.from_env()` message rather than
  a traceback. An unreachable firewall exits 1.

## Verification Checklist

- [ ] Command runs without errors
- [ ] Output includes all four sections (version, minor update, major upgrade, reboot)
- [ ] Repository warning appears if `status_msg` contains "repositor" + error word
