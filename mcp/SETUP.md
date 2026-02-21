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
   - `Diagnostics: Backup & Restore` — download configuration backup
   - `Diagnostics: System Activity` — system uptime (used to validate reboot status)
   - `Diagnostics: System Health` — system health metrics
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

Add the MCP server to your Claude Code settings at `~/.claude/settings.json`:

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

The MCP server reads credentials from `mcp/.env` automatically — no keys in `settings.json`.

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

### Connection refused
- Confirm your workstation can reach the OPNsense IP on port 443
- Check that the OPNsense web UI is enabled on the LAN interface
