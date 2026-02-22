# OPNsense MCP Server

A Claude MCP server that connects Claude Code directly to your OPNsense firewall via its REST API. Manage your firewall conversationally — no SSH required.

**See [SETUP.md](SETUP.md) for installation and configuration instructions.**

---

## Tools

| Tool | Type | Description |
|------|------|-------------|
| `get_version` | read | Current OPNsense version, FreeBSD base, next major version |
| `check_updates` | read | Minor/major update availability and reboot status |
| `pre_upgrade_check` | read | Pre-upgrade health assessment with go/no-go verdict |
| `upgrade_status` | read | Monitor an in-progress upgrade |
| `get_changelog` | read | Changelog for a specific version |
| `list_packages` | read | Installed packages with versions |
| `system_info` | read | Uptime, load average, top processes |
| `run_update` | write | Trigger minor update (requires confirmation) |
| `run_upgrade` | write | Trigger major upgrade (requires confirmation) |
| `reboot` | write | Reboot the firewall (requires confirmation) |

Write tools require explicit confirmation and are blocked when `OPNSENSE_READ_ONLY=true`.

---

## Structure

```
mcp/
├── SETUP.md                  # Step-by-step setup guide
├── requirements.txt          # Python dependencies (mcp, httpx, pydantic)
└── src/opnsense_mcp/
    ├── server.py             # Asyncio entry point
    ├── config.py             # Loads mcp/.env, pydantic Config model
    ├── api.py                # OPNsenseAPI — all HTTP calls and reboot staleness logic
    └── tools.py              # MCP tool definitions and handlers
```

## Requirements

- Python 3.10+ on your workstation
- OPNsense with a dedicated API user (`System: Firmware` + `Diagnostics: System Activity` privileges)
- Claude Code CLI or VSCode extension
