# OPNsense MCP Server

A Claude MCP server that connects Claude Code directly to your OPNsense firewall via its REST API. Manage your firewall conversationally — no SSH required.

**See [SETUP.md](SETUP.md) for installation and configuration instructions.**

---

## Tools

| Tool | Type | Description |
|------|------|-------------|
| `get_version` | read | Current OPNsense version, FreeBSD base, next major version |
| `check_updates` | read | Minor/major update availability, pending package list (name, versions, repo), and reboot status; distinguishes plugin-only batches from OPNsense version bumps |
| `pre_upgrade_check` | read | Pre-upgrade health assessment with go/no-go verdict (flags pending minor updates, genuine reboots, unreachable repos, in-progress upgrades, obsolete py37 packages) |
| `upgrade_status` | read | Monitor an in-progress upgrade |
| `get_changelog` | read | Changelog for a specific version |
| `list_packages` | read | Installed packages with versions |
| `system_info` | read | Uptime, load average, top processes |
| `run_update` | write | Trigger minor update (requires confirmation) — lists the package batch being applied; may reboot if kernel/base packages are updated |
| `run_upgrade` | write | Trigger major upgrade (requires confirmation) |
| `reboot` | write | Reboot the firewall (requires confirmation) |

Write tools require explicit confirmation and are blocked when `OPNSENSE_READ_ONLY=true`.

---

## Structure

```
mcp/
├── SETUP.md                  # Step-by-step setup guide
├── requirements.txt          # Python dependencies (mcp, httpx, pydantic)
├── tests/
│   └── test_batch_summary.py # Pending-batch reporting tests (offline, fixture-driven)
└── src/opnsense_mcp/
    ├── server.py             # Asyncio entry point
    ├── config.py             # Loads mcp/.env, pydantic Config model
    ├── api.py                # OPNsenseAPI — HTTP calls, reboot staleness, batch classification
    └── tools.py              # MCP tool definitions and handlers
```

## Tests

Offline regression tests (no firewall needed):

```bash
mcp/.venv/bin/python mcp/tests/test_batch_summary.py
```

## Requirements

- Python 3.10+ on your workstation
- OPNsense with a dedicated API user — privileges: `System: Firmware`, `Diagnostics: System Activity`
- Claude Code CLI or VSCode extension
