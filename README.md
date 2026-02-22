# OPNsense Upgrade Tools

Tools for managing OPNsense firewall upgrades.

**Version:** 1.1
**License:** MIT

---

## Components

| # | Component | Location | Use when |
|---|-----------|----------|----------|
| 1 | [Claude MCP Server](#1-claude-mcp-server) | `mcp/` | Day-to-day monitoring and triggering updates conversationally from Claude Code |
| 2 | [SSH Upgrade Script](#2-ssh-upgrade-script) | `python/` | Major upgrades where the web UI falls short, or as a fallback after an MCP-triggered upgrade |
| 3 | [Split Routing Recovery Tools](#3-split-routing-recovery-tools) | `ps1/` | Major upgrade breaks OPNsense networking — restore SSH access from a Windows machine |

---

## 1. Claude MCP Server

Connects Claude directly to your OPNsense firewall via its REST API. Once registered, manage your firewall conversationally from within Claude Code — no SSH required.

**Example usage:**
- "Check my firewall for updates"
- "Run a pre-upgrade health check"
- "Show me the 26.7 changelog"
- "How is my firewall doing?"

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

Write tools are blocked when `OPNSENSE_READ_ONLY=true`. See [mcp/SETUP.md](mcp/SETUP.md) for setup instructions.

---

## 2. SSH Upgrade Script

A stateful, multi-stage upgrade script that runs directly on OPNsense via SSH. Handles the failure modes that the OPNsense web UI cannot recover from during major upgrades:

- `pkg` breaking after a base/kernel upgrade due to ABI mismatch
- Segfaults mid-upgrade leaving packages half-installed
- No automatic resume after the reboot that follows a base/kernel upgrade

Runs dry by default (`-x` to execute). See [python/README.md](python/README.md) for full documentation.

```sh
scp python/opnsense-upgrade.py root@opnsense:/root/
ssh root@opnsense
./opnsense-upgrade.py -l        # check available versions
./opnsense-upgrade.py -x -m    # execute minor update
./opnsense-upgrade.py -x -t 26.7  # execute major upgrade
```

---

## 3. Split Routing Recovery Tools

PowerShell scripts for Windows that restore connectivity when a major OPNsense upgrade breaks networking. Sets up split routing so you can SSH into OPNsense to fix the upgrade while still having internet access via WiFi.

```powershell
.\ps1\Enable-SplitRouting-WithModule.ps1
```

Then SSH into OPNsense and resume: `./opnsense-upgrade.py -x -r`

See [ps1/README.md](ps1/README.md) for details.

---

## Project Structure

```
opnsense-upgrade/
├── README.md
├── python/
│   ├── README.md                     # Full upgrade script documentation
│   └── opnsense-upgrade.py          # Main upgrade script (runs on OPNsense)
├── mcp/
│   ├── SETUP.md                      # MCP server setup guide
│   ├── requirements.txt
│   └── src/opnsense_mcp/             # MCP server package (api, tools, config, server)
└── ps1/
    ├── README.md                     # Recovery tools documentation
    ├── Enable-SplitRouting-WithModule.ps1
    ├── OPNsenseCommon.psm1
    ├── MODULE-README.md
    └── INSTALL-GUIDE.md
```

## License

MIT
