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
   - `System: Firmware` — check for updates, trigger upgrades, reboot
   - `Diagnostics: System Activity` — system uptime (used to validate reboot status)

   These two are all the server needs. (Backup download and service-status endpoints
   are not used — OPNsense restricts them to admin-level access, not grantable to a
   scoped API key.)
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
OPNSENSE_URL=https://192.168.1.1        # change to your firewall's IP or hostname
OPNSENSE_API_KEY=${API_KEY}
OPNSENSE_API_SECRET=${API_SECRET}
OPNSENSE_VERIFY_SSL=false               # set to true only if you have a valid SSL cert
OPNSENSE_READ_ONLY=false                # set to true to disable update/upgrade/reboot tools
EOF

echo ".env created."
```

The `.env` file is already listed in `.gitignore` — it will not be pushed to GitHub.

Connecting by IP address is fine — the MCP server does not need a DNS name. With
`OPNSENSE_VERIFY_SSL=false` (the default for OPNsense's self-signed certificate) no
certificate name check happens, so `https://<ip>` behaves identically to a hostname,
and the IP keeps the MCP server working even when local DNS is unavailable. A hostname
is only required if you set `OPNSENSE_VERIFY_SSL=true` with a real certificate — then
the URL must match a name in the certificate.

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

**Adjust the path** (`~/projects/opnsense-upgrade/mcp`) to wherever you cloned this repo.

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

## Step 7: Verify

After restarting, confirm the server loaded correctly by asking Claude:

> "What version is my OPNsense?"

Claude should call `get_version` and return the current version, FreeBSD base, and next major version. If you see an error, check the Troubleshooting section below.

---

## Available Tools

Once registered, the following tools are available in Claude:

| Tool | Type | Description |
|------|------|-------------|
| `get_version` | read | Current OPNsense version, FreeBSD base, next major version |
| `check_updates` | read | Minor/major update availability and reboot status |
| `pre_upgrade_check` | read | Pre-upgrade health assessment: pending minor updates, reboot status, unreachable repos, in-progress detection, obsolete py37 packages, go/no-go verdict |
| `upgrade_status` | read | Monitor an in-progress firmware update or upgrade |
| `get_changelog` | read | Changelog for a specific OPNsense version |
| `list_packages` | read | All installed packages with versions |
| `system_info` | read | Uptime, load average, and top processes |
| `run_update` | write | Trigger a minor firmware update — may reboot if kernel/base packages are updated |
| `run_upgrade` | write | Trigger a major version upgrade |
| `reboot` | write | Reboot the firewall |

Write tools require explicit user confirmation and are blocked when `OPNSENSE_READ_ONLY=true` in `mcp/.env`.

**Safety guards on write tools:**
- `run_update` — blocked if system is already up to date or an upgrade is already running
- `run_upgrade` — blocked if minor updates are pending (must apply those first) or an upgrade is already running
- `run_update` / `run_upgrade` — blocked if a configured pkg repository is unreachable (it would otherwise hang on the catalog fetch); the message names the fix
- `upgrade_status` — warns when a "running" status coincides with an unreachable repo, the classic stalled-update signature
- `check_updates` — appends the same unreachable-repo warning so the problem is visible before any write tool is attempted

**Note on reboots:** When a pending update includes kernel or base packages, `check_updates` and `pre_upgrade_check` report that the update will reboot the system when applied — this is informational, not a blocker, and never requires rebooting beforehand. OPNsense reboots automatically mid-update: expect a connection loss of 2-5 minutes and confirm with `get_version` once the firewall is back. A "Reboot status: not required" means no reboot is outstanding from a previous operation.

---

## Security Notes

- **Never commit** your API key or secret to git (`.env` is gitignored)
- The API user has **minimal privileges** — it cannot change firewall rules or access other systems
- To revoke Claude's access instantly: delete the API key in **System > Access > Users**
- OPNsense logs all API calls under **System > Log Files > Audit**
- Set `OPNSENSE_READ_ONLY=true` in `mcp/.env` to disable write tools (update/upgrade/reboot) entirely

---

## Usage Examples

Just talk to Claude naturally — no special syntax required:

| What you say | What Claude does |
|--------------|-----------------|
| "What version is my firewall?" | Calls `get_version` |
| "Check for updates" | Calls `check_updates` |
| "Is my firewall ready to upgrade to 26.7?" | Calls `pre_upgrade_check` |
| "Show me what's installed" | Calls `list_packages` |
| "What changed in 26.1.2?" | Calls `get_changelog` with version 26.1.2 |
| "How is my firewall doing?" | Calls `system_info` |
| "What's happening with the upgrade?" | Calls `upgrade_status` |
| "Apply the latest update" | Calls `run_update` (asks confirmation first) |
| "Reboot the firewall" | Calls `reboot` (asks confirmation first) |

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
