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
cd <project-root>/mcp && .venv/bin/python3 -c "
import sys; sys.path.insert(0, 'src')
from opnsense_mcp.config import Config
from opnsense_mcp.api import OPNsenseAPI
from opnsense_mcp.tools import _version_state, batch_summary, _update_lines, _repo_error

config = Config.from_env()
api = OPNsenseAPI(config)
status = api.firmware_status()

vs = _version_state(status)
batch = batch_summary(status)

lines = [f'Current version: {vs[\"current\"] or \"unknown\"}']
lines.extend(_update_lines(vs, batch))
if vs['fw_status'] == 'upgrade':
    lines.append(f'Major upgrade available: {vs[\"next_major\"]}')
elif vs['next_major']:
    lines.append(f'Next major version: {vs[\"next_major\"]} (planned)')
else:
    lines.append('Major upgrade: none available')
lines.append(f'Status: {status.get(\"status_msg\", \"\") or \"no updates\"}')

if _repo_error(status):
    lines.append('WARNING: repo unreachable')

reboot = api.check_needs_reboot()
lines.append(f'Reboot: {reboot[\"explanation\"]}')
print('\\n'.join(lines))
"
```

Replace `<project-root>` with the repo root (e.g. `~/projects/opnsense-upgrade`). Must run
via `mcp/.venv/bin/python3`, not the system `python3` -- the venv is the only place
`httpx`/`pydantic`/`mcp` are guaranteed to be installed at the versions this package expects.
If `.venv/bin/python3` is missing, see `mcp/SETUP.md`.

## Output Format

- Current version (with pkg revision stripped for comparison)
- Minor update status (up to date or pending with package list)
- Major upgrade availability
- Repository status warning if unreachable
- Reboot status with explanation (stale vs genuine)

## Common Pitfalls

- Running with system `python3` instead of `mcp/.venv/bin/python3` -- will fail with
  `ModuleNotFoundError` unless the same packages happen to be installed globally.
- `Config.from_env()` raises `ValueError` if `mcp/.env` is missing or incomplete; check
  `mcp/SETUP.md` if the command errors out instead of printing a report.

## Verification Checklist

- [ ] Command runs without errors
- [ ] Output includes all four sections (version, minor update, major upgrade, reboot)
- [ ] Repository warning appears if `status_msg` contains "repositor" + error word
