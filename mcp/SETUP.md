# MCP Server Setup Guide

Step-by-step instructions to prepare your OPNsense firewall and workstation for the Claude MCP server integration.

## Prerequisites

- OPNsense Community Edition with web UI access
- Python 3.10+ on your workstation
- Claude Code CLI installed

---

## Step 1: Create an API User on OPNsense

1. Log in to your OPNsense web UI (e.g., `https://192.168.1.1`)
2. Go to **System > Access > Users**
3. Click **Add**
4. Fill in:
   - **Username:** `claude-mcp` (or any name you prefer)
   - **Password:** set a strong random password (not used for API access, but required by OPNsense)
   - **Full name:** `Claude MCP API User`
   - **Login shell:** `/sbin/nologin`
5. Under **Privileges**, add:
   - `System: Firmware` — check for updates, trigger upgrades
   - `Diagnostics: System Activity` — system uptime (used to validate reboot status)
6. Click **Save**

---

## Step 2: Generate an API Key

1. After saving, click the user to edit it
2. Scroll down to the **API keys** section
3. Click **+ Add API key**
4. OPNsense will display a **Key** and **Secret** — copy both immediately

   **Important:** The secret is shown only once. If you lose it, delete the key and generate a new one.

5. Click **Save**

---

## Step 3: Store Credentials

OPNsense downloads a key file when you generate an API key (e.g., `OPNsense.home.lan_claude-mcp_apikey.txt`).
Copy it into `mcp/` (it is gitignored), then run these commands from inside the `mcp/` directory:

```sh
cd mcp
KEY_FILE="OPNsense.home.lan_claude-mcp_apikey.txt"  # adjust filename if needed

API_KEY=$(grep '^key=' "$KEY_FILE" | cut -d= -f2)
API_SECRET=$(grep '^secret=' "$KEY_FILE" | cut -d= -f2)

cat > .env <<EOF
OPNSENSE_URL=https://192.168.1.1
OPNSENSE_API_KEY=${API_KEY}
OPNSENSE_API_SECRET=${API_SECRET}
OPNSENSE_VERIFY_SSL=false
EOF

echo ".env created."
```

The `.env` file is already listed in `.gitignore` — it will not be pushed to GitHub.

---

## Step 4: Test the API Key

Verify the key works before setting up the MCP server:

```sh
cd mcp
source .env
curl -k -u "${OPNSENSE_API_KEY}:${OPNSENSE_API_SECRET}" \
  "${OPNSENSE_URL}/api/core/firmware/status"
```

Expected: a JSON response with firmware status. If you get a 401, the key or privileges are wrong.

---

## Step 5: Install Python Dependencies

Create a virtual environment and install dependencies:

```sh
cd mcp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Dependencies:
- `mcp` — Anthropic's MCP SDK for Python
- `httpx` — HTTP client for OPNsense API calls
- `pydantic` — configuration validation

---

## Step 6: Register with Claude Code

The recommended way is the `claude mcp add` CLI command, which writes the entry automatically:

```sh
claude mcp add --scope user opnsense -- bash \
  -c "cd ~/projects/opnsense-upgrade/mcp && exec .venv/bin/python -m src.opnsense_mcp.server"
```

This writes to `~/.claude.json` (used by the VSCode extension). If you are using the Claude Code CLI instead of the VSCode extension, the file is `~/.claude/settings.json` — the JSON entry format is the same either way:

```json
{
  "mcpServers": {
    "opnsense": {
      "type": "stdio",
      "command": "bash",
      "args": ["-c", "cd ~/projects/opnsense-upgrade/mcp && exec .venv/bin/python -m src.opnsense_mcp.server"],
      "env": {}
    }
  }
}
```

The MCP server reads credentials from `mcp/.env` automatically — no keys in the registration entry.

**Note:** After registering, restart Claude Code (or reload the VSCode window) to load the server. You must also restart after any code changes to `mcp/src/`.

---

## Available Tools

Once registered, the following tools are available in Claude:

| Tool | Type | Description |
|------|------|-------------|
| `get_version` | read | Current OPNsense version, FreeBSD base, next major version |
| `check_updates` | read | Minor/major update availability and reboot status |
| `pre_upgrade_check` | read | Pre-upgrade health assessment: pending minor updates, reboot status, in-progress detection, go/no-go verdict |
| `upgrade_status` | read | Monitor an in-progress firmware update or upgrade |
| `get_changelog` | read | Changelog for a specific OPNsense version |
| `list_packages` | read | All installed packages with versions |
| `system_info` | read | Uptime, load average, and top processes |
| `run_update` | write | Trigger a minor firmware update |
| `run_upgrade` | write | Trigger a major version upgrade |
| `reboot` | write | Reboot the firewall |

Write tools require explicit user confirmation and are blocked when `OPNSENSE_READ_ONLY=true` in `mcp/.env`.

**Safety guards on write tools:**
- `run_update` — blocked if system is already up to date or an upgrade is already running
- `run_upgrade` — blocked if minor updates are pending (must apply those first) or an upgrade is already running

---

## Security Notes

- **Never commit** your API key or secret to git (`.env` is gitignored)
- The API user has **minimal privileges** — it cannot change firewall rules or access other systems
- To revoke Claude's access instantly: delete the API key in **System > Access > Users**
- OPNsense logs all API calls under **System > Log Files > Audit**
- Use `read_only: true` in the MCP config to disable write tools (update/upgrade/reboot) entirely

---

## Troubleshooting

### 401 Unauthorized
- Check that the API key and secret are correct
- Confirm the user has the required privileges saved

### SSL certificate error
- Set `OPNSENSE_VERIFY_SSL=false` if using a self-signed certificate (default for most OPNsense installs)

### Connection refused / firewall unreachable
- Confirm your workstation can reach the OPNsense IP on port 443
- Check that the OPNsense web UI is enabled on the LAN interface
- The MCP server returns a descriptive error to Claude rather than crashing:
  - Unreachable: `Cannot connect to OPNsense. Check that the firewall is reachable and the URL in mcp/.env is correct.`
  - Timeout: `Request to OPNsense timed out. The firewall may be busy or unreachable.`
  - HTTP error: `OPNsense API error: HTTP 401. Check that the API key has the required privileges.`
