# Project: OPNsense Enhanced Upgrade Script

## Overview

Multi-tool project for managing OPNsense firewall upgrades. Three components:

- **python/** — Main upgrade script (runs on OPNsense via SSH as root)
- **ps1/** — Windows PowerShell recovery tools (split routing for failed upgrades)
- **mcp/** — Claude MCP server for OPNsense API integration (planned, see MCP-PLAN.md)

## Key Files

- `python/opnsense-upgrade.py` — The main script. Stateful, multi-stage, dry-run by default.
- `ps1/Enable-SplitRouting-WithModule.ps1` — Split routing setup for upgrade recovery.
- `MCP-PLAN.md` — Full implementation plan for the MCP server (not yet built).

## Conventions

- Version: 1.0 (first release)
- Dry-run by default, `-x` to execute
- Keep READMEs in each subdirectory
- No emojis in code or docs
- Python script targets Python 3 on FreeBSD (OPNsense)
- MCP server targets Python 3.10+ on user's workstation

## OPNsense Context

- Version format: YY.M (e.g., 26.1, 26.7, 27.1)
- Minor updates: within same branch (26.1.1 -> 26.1.2)
- Major upgrades: across branches (26.1 -> 26.7), require base/kernel upgrade + reboot
- OPNsense has a REST API at `/api/core/firmware/` for status, updates, upgrades
- `pkg` can break after base/kernel upgrade due to ABI mismatch — the script handles this

## Pending Work

- MCP server implementation (see MCP-PLAN.md for full plan)
- The MCP server should live in `mcp/` subdirectory
- Uses OPNsense REST API (not SSH) for safety and auditability
- Auto-resume via `/etc/rc.local.d/` not yet tested — needs a major upgrade with actual base/kernel reboot to verify. If it fails, user must manually run `./opnsense-upgrade.py -x -r` after reboot.

## Testing Status

- Minor update (26.1.1 -> 26.1.2) tested successfully on OPNsense 26.1
- `pkg rquery '%v' opnsense` confirmed as reliable minor version detection fallback
- Reboot detection (`"please reboot" in output`) logic correct but untested — minor update did not change the FreeBSD kernel so no reboot was triggered
- Auto-resume untested — no mid-upgrade reboot has occurred yet
