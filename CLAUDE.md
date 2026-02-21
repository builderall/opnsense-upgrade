# Project: OPNsense Enhanced Upgrade Script

## Overview

Multi-tool project for managing OPNsense firewall upgrades. Three components:

- **python/** — Main upgrade script (runs on OPNsense via SSH as root)
- **ps1/** — Windows PowerShell recovery tools (split routing for failed upgrades)
- **mcp/** — Claude MCP server for OPNsense API integration (built and working)

## Key Files

- `python/opnsense-upgrade.py` — The main upgrade script. Stateful, multi-stage, dry-run by default.
- `ps1/Enable-SplitRouting-WithModule.ps1` — Split routing setup for upgrade recovery.
- `MCP-PLAN.md` — Original MCP server design plan (implemented).
- `mcp/SETUP.md` — Step-by-step setup guide for new users.
- `mcp/src/opnsense_mcp/` — MCP server Python package (see MCP Server section below).
- `push.sh` — Push to GitHub using gh CLI token (auto-creates repo on first run).

## Conventions

- Version: 1.0 (first release, tagged v1.0 on GitHub)
- Dry-run by default, `-x` to execute
- Keep READMEs in each subdirectory
- No emojis in code or docs
- Python script targets Python 3 on FreeBSD (OPNsense)
- MCP server targets Python 3.10+ on user's workstation (Linux/WSL)

## OPNsense Context

- Firewall hostname: `OPNsense.home.lan` (user's local DNS)
- Current version: 26.1.2 (upgraded from 26.1.1 during development)
- Next major version: 26.7 (confirmed via API `CORE_NEXT` field)
- Version format: YY.M.P (e.g., 26.1.2) with pkg revision suffix `_N` (e.g., 26.1.2_5) — always strip suffix for comparisons
- Minor updates: within same branch (26.1.1 -> 26.1.2)
- Major upgrades: across branches (26.1 -> 26.7), require base/kernel upgrade + reboot
- OPNsense REST API at `/api/core/firmware/` — confirmed working
- `pkg` can break after base/kernel upgrade due to ABI mismatch — the python script handles this

## GitHub

- Repo: https://github.com/builderall/opnsense-upgrade
- Branch: master
- Tag: v1.0 (initial release)
- Git user: builderall / 25215839+builderall@users.noreply.github.com (set locally, not globally)
- Push with: `./push.sh` (uses gh CLI token, auto-creates repo if missing)

## MCP Server

**Status: Built and smoke-tested against live OPNsense. Not yet tested via Claude Code session.**

### Structure

```
mcp/
├── .env                          # credentials (gitignored) — loaded automatically by config.py
├── .venv/                        # Python 3.12 venv (gitignored) — mcp 1.26.0, httpx 0.28.1, pydantic 2.12.5
├── requirements.txt              # mcp, httpx, pydantic
├── pyproject.toml
├── SETUP.md                      # user setup guide
└── src/opnsense_mcp/
    ├── config.py                 # loads mcp/.env, pydantic Config model
    ├── api.py                    # OPNsenseAPI class — all HTTP calls + reboot staleness logic
    ├── tools.py                  # 10 MCP tools registered via list_tools/call_tool decorators
    └── server.py                 # asyncio entry point, started by Claude Code via settings.json
```

### Registered in Claude Code

`~/.claude/settings.json`:
```json
{
  "mcpServers": {
    "opnsense": {
      "command": "~/projects/opnsense-upgrade/mcp/.venv/bin/python",
      "args": ["-m", "src.opnsense_mcp.server"],
      "cwd": "~/projects/opnsense-upgrade/mcp"
    }
  }
}
```

### Available Tools

| Tool | Type | Description |
|------|------|-------------|
| `get_version` | read | Current OPNsense version, FreeBSD base, next major |
| `check_updates` | read | Minor/major update availability + reboot status |
| `upgrade_status` | read | Monitor in-progress upgrade |
| `get_changelog` | read | Changelog for a specific version |
| `list_packages` | read | Installed packages with versions |
| `get_config_backup` | read | Download config XML, return summary |
| `system_info` | read | Uptime, load average, top processes |
| `run_update` | write | Trigger minor update (requires user confirmation) |
| `run_upgrade` | write | Trigger major upgrade (requires user confirmation) |
| `reboot` | write | Reboot firewall (requires user confirmation) |

Write tools are blocked when `OPNSENSE_READ_ONLY=true` in `.env`.

### OPNsense API User (claude-mcp)

Privileges required:
- `System: Firmware` — firmware status, update, upgrade
- `Diagnostics: Backup & Restore` — config XML download
- `Diagnostics: System Activity` — uptime via `POST /api/diagnostics/activity/getActivity`
- `Diagnostics: System Health` — health metrics

### Pending MCP Work

- First live test via Claude Code session (start new session, MCP server auto-loads)
- Verify `~/` path expansion works in `settings.json` command/cwd fields (untested)
- Test write tools (`run_update`, `run_upgrade`, `reboot`) — need careful testing with real upgrade
- Add mcp/README.md once live testing is done

## Testing Status (python script)

- Minor update (26.1.1 -> 26.1.2) tested successfully on OPNsense 26.1
- `pkg rquery '%v' opnsense` confirmed as reliable minor version detection fallback
- Reboot detection (`"please reboot" in output`) logic correct but untested — minor update did not change the FreeBSD kernel so no reboot was triggered
- Auto-resume via `/etc/rc.local.d/` not yet tested — needs a major upgrade with actual base/kernel reboot to verify. If it fails, user must manually run `./opnsense-upgrade.py -x -r` after reboot.

## MCP API Notes

- `needs_reboot: 1` in firmware status after 26.1.2 upgrade: genuine (not stale) — firmware daemon ran post-reboot and still reports it. Router requires a second reboot to clear this flag. Safe to use, just needs reboot.
- Reboot staleness logic in `api.py`: compare uptime vs last_check_age. If `uptime > last_check_age`, boot happened before last check => flag is genuine. If `uptime < last_check_age`, check predates this boot => flag is stale.
- `GET` requests to diagnostics endpoints return 401; use `POST` for `getActivity` and similar.
- `CORE_NEXT: 26.7` confirmed in firmware status API — next major version detection works.
