# MCP Server Plan: OPNsense Upgrade Assistant for Claude

> **Status: Implemented.** This document is the original design plan. The MCP server is built and working. See [mcp/SETUP.md](mcp/SETUP.md) for setup instructions.

## Overview

Build an MCP (Model Context Protocol) server that connects Claude to your OPNsense firewall via its REST API. This lets you manage upgrades conversationally — "check for updates", "back up my config", "show upgrade logs" — without giving Claude shell access.

## Why API Instead of SSH

| Aspect | SSH | OPNsense REST API |
|--------|-----|-------------------|
| **Access scope** | Full root shell | Only exposed endpoints |
| **Permissions** | All or nothing | Scoped API key permissions |
| **Audit trail** | Must build your own | Built into OPNsense |
| **Security risk** | High (arbitrary commands) | Low (predefined operations) |
| **Authentication** | SSH key or password | API key + secret (revocable) |

## Architecture

```
Claude Code ←→ MCP Server (Python) ←→ OPNsense REST API (HTTPS)
                    │
                    ├── Tools (what Claude can do)
                    ├── Logging (audit trail)
                    └── Config (API keys, firewall address)
```

## OPNsense API Setup

1. Go to **System > Access > Users** in the OPNsense web UI
2. Create a dedicated API user (e.g., `claude-mcp`)
3. Generate an **API key + secret** pair
4. Assign minimal privileges:
   - `System: Firmware` — read status, trigger updates
   - `Diagnostics: System Activity` — uptime and process info

API docs: `https://<your-opnsense>/api/core/firmware`

## MCP Tools

### Read-Only Tools (no confirmation needed)

| Tool | Description | OPNsense API Endpoint | Status |
|------|-------------|----------------------|--------|
| `check_updates` | Check for available minor and major updates | `GET /api/core/firmware/status` | Implemented |
| `get_version` | Get current OPNsense version and FreeBSD base | `GET /api/core/firmware/status` | Implemented |
| `upgrade_status` | Monitor an in-progress upgrade | `GET /api/core/firmware/upgradestatus` | Implemented |
| `get_changelog` | Show changelog for a specific version | `POST /api/core/firmware/changelog/<version>` | Implemented |
| `list_packages` | List installed packages | `POST /api/core/firmware/info` (with status fallback) | Implemented |
| `system_info` | Uptime, load average, top processes | `POST /api/diagnostics/activity/getActivity` | Implemented |
| `pre_upgrade_check` | Pre-upgrade health assessment with go/no-go verdict | Multiple endpoints | Implemented |
| `get_audit_log` | View recent firmware activity log | `GET /api/core/firmware/audit` | Not implemented |

### Write Tools (require user confirmation)

| Tool | Description | OPNsense API Endpoint | Status |
|------|-------------|----------------------|--------|
| `run_update` | Trigger a minor update (blocked if already up to date or upgrade running) | `POST /api/core/firmware/update` | Implemented |
| `run_upgrade` | Trigger a major upgrade (blocked if minor updates pending or upgrade running) | `POST /api/core/firmware/upgrade` | Implemented |
| `reboot` | Reboot the firewall | `POST /api/core/firmware/reboot` | Implemented |

## Project Structure

```
opnsense-upgrade/
├── ...existing files...
└── mcp/
    ├── README.md                  # MCP server documentation
    ├── pyproject.toml             # Python project config
    ├── requirements.txt           # Dependencies (httpx, mcp-sdk)
    └── src/
        └── opnsense_mcp/
            ├── __init__.py
            ├── server.py          # MCP server entry point
            ├── api.py             # OPNsense API client
            ├── tools.py           # Tool definitions
            └── config.py          # Configuration (API keys, URL)
```

## Configuration

The MCP server reads config from environment variables or a config file:

```json
{
  "opnsense_url": "https://192.168.1.1",
  "api_key": "your-api-key",
  "api_secret": "your-api-secret",
  "verify_ssl": false,
  "read_only": false,
  "log_file": "/var/log/opnsense-mcp.log"
}
```

## Claude Code Integration

Register with the `claude mcp add` CLI (see [mcp/SETUP.md](mcp/SETUP.md) for full instructions):

```sh
claude mcp add --scope user opnsense -- bash \
  -c "cd ~/projects/opnsense-upgrade/mcp && exec .venv/bin/python -m src.opnsense_mcp.server"
```

Credentials are read from `mcp/.env` automatically — no keys in the registration entry.

## Auditing & Safety

### Built-in Safeguards

- **Read-only mode** — Set `read_only: true` to disable all write tools entirely
- **User confirmation** — Write tools (update, upgrade, reboot) require explicit user approval via Claude Code's permission system
- **API key scoping** — OPNsense API keys can be restricted to specific endpoints
- **Revocable access** — Delete the API key in OPNsense to instantly revoke Claude's access
- **Graceful error handling** — Network errors (`ConnectError`, `TimeoutException`), HTTP errors (`HTTPStatusError`), and unexpected exceptions are caught and returned as descriptive messages to Claude rather than crashing the tool call

### Audit Trail

Three layers of logging:

1. **OPNsense audit log** — All API calls logged server-side (System > Log Files > Audit)
2. **MCP server log** — Every tool invocation logged with timestamp, tool name, parameters, and response status
3. **Claude Code hooks** — Optional shell hooks that log every tool call Claude makes

### Example Hook for Logging

In `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "mcp__opnsense__*",
        "hooks": [
          {
            "type": "command",
            "command": "echo \"$(date) MCP call: $CLAUDE_TOOL_NAME $CLAUDE_TOOL_INPUT\" >> ~/.claude/mcp-audit.log"
          }
        ]
      }
    ]
  }
}
```

## Dependencies

- Python 3.10+
- `mcp` — MCP SDK for Python (Anthropic's official SDK)
- `httpx` — HTTP client for OPNsense API calls
- `pydantic` — Configuration validation

## Implementation Steps

1. **Set up OPNsense API access** — Create API user, generate key pair, test with curl
2. **Build API client** — Python wrapper around OPNsense REST API with error handling
3. **Implement read-only tools** — `check_updates`, `get_version`, `list_packages`, etc.
4. **Implement write tools** — `run_update`, `run_upgrade` with confirmation requirements
5. **Add logging** — Audit trail for every tool invocation
6. **Add config** — Environment variables and config file support
7. **Register with Claude Code** — Add to `.claude/settings.json`
8. **Test** — Verify each tool against a live OPNsense instance
9. **Document** — Usage guide with examples

## Example Conversations

Once the MCP server is running, you could interact with Claude like this:

> **You:** Check if my firewall has any updates available
>
> **Claude:** Your OPNsense firewall (192.168.1.1) is running version 26.1.2. There's a minor update available to 26.1.3 with 12 package updates. No major upgrades available. Would you like to see the changelog?

> **You:** Back up my config before I update
>
> **Claude:** Configuration backed up. Downloaded config.xml (42KB) from your firewall. The backup contains your firewall rules, VPN configs, and DHCP settings.

> **You:** Go ahead and run the minor update
>
> **Claude:** [Requests confirmation] This will trigger a minor update from 26.1.2 to 26.1.3 on your firewall. Proceed?
>
> **You:** Yes
>
> **Claude:** Update triggered. Monitoring progress... Package download complete (3/12)... Installation complete. All services running. OPNsense is now on 26.1.3.
