# OPNsense Enhanced Upgrade Script

A stateful, multi-stage upgrade script for OPNsense firewalls with automatic recovery, reboot handling, and dry-run safety.

**Version:** 1.0
**License:** MIT

## Why Not Just Use the Web UI?

The OPNsense web UI handles minor updates well, but major upgrades (e.g., 25.7 to 26.1) are a multi-step process that the web UI does not fully manage. Common problems include:

- **Base/kernel upgraded, packages not** - The web UI upgrades the FreeBSD base and kernel, reboots, but the package upgrade can fail silently or segfault, leaving you with a FreeBSD 14 base running OPNsense 25.7 packages
- **`pkg` breaks after base upgrade** - The new FreeBSD base ships a newer `pkg` ABI, making the old `pkg` binary unable to install or upgrade anything — the web UI has no recovery for this
- **Segfaults during package install** - `opnsense-update` and `pkg` can segfault mid-upgrade due to ABI mismatches, leaving packages half-installed
- **No automatic resume after reboot** - The web UI reboots after base/kernel but does not automatically continue with package upgrades — you must manually log back in and trigger the next step
- **No rollback or state tracking** - If the upgrade fails partway through, the web UI provides no record of what stage failed or how to resume

This script solves these problems by treating the upgrade as a **stateful, multi-stage pipeline**:

- Breaking the upgrade into **resumable stages** with saved state between reboots
- **Automatically resuming** after reboot to continue from where it left off
- Detecting and **fixing `pkg` incompatibility** after base/kernel changes (using `pkg-static` or `opnsense-bootstrap`)
- Running in **dry-run mode by default** so you can preview every step before committing
- **Always backing up** configuration and package list before upgrades
- Blocking major upgrades when minor updates are pending (matching OPNsense web UI behavior)

## Features

- **Automatic version detection** - Multiple methods: firmware API, `pkg rquery`, mirror probing
- **Stateful upgrades** - Survives reboots with automatic resume
- **Dry-run by default** - Safe testing before execution (use `-x` to execute)
- **Multi-stage process** - Pre-checks, Cleanup, Backup, Base/Kernel, Fix pkg, Packages, Verification
- **Minor & Major upgrades** - Supports both patch updates (26.1.1 -> 26.1.2) and major versions (26.1 -> 27.1)
- **Smart detection** - Handles plain text and JSON firmware output
- **Standalone backup** - Use `-b` to backup config and package list anytime
- **Version summary** - Use `-l` to see both minor and major versions available
- **Safety guards** - Blocks major upgrades when minor updates are pending
- **Help by default** - Shows usage when run without arguments for safety

## Project Structure

```
opnsense-upgrade/
├── README.md                          # This file
├── python/
│   ├── README.md                     # Detailed documentation
│   └── opnsense-upgrade.py          # Main upgrade script (runs on OPNsense)
├── mcp/
│   ├── SETUP.md                      # MCP server setup guide
│   ├── requirements.txt              # Python dependencies
│   └── src/opnsense_mcp/             # MCP server package (api, tools, config, server)
└── ps1/
    ├── README.md                     # Recovery tools documentation
    ├── Enable-SplitRouting-WithModule.ps1  # Split routing for upgrade recovery
    ├── OPNsenseCommon.psm1           # PowerShell module (logging, elevation)
    ├── MODULE-README.md              # Module reference
    └── INSTALL-GUIDE.md              # Module installation guide
```

## Claude MCP Server

The `mcp/` directory contains a Claude MCP server that connects Claude directly to your OPNsense firewall via its REST API. Once registered, you can manage your firewall conversationally from within Claude Code.

**Example usage:**
- "Check my firewall for updates"
- "Run a pre-upgrade health check"
- "Show me the 26.7 changelog"
- "Back up my config before upgrading"

**Available tools:**

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

Write tools are blocked when `OPNSENSE_READ_ONLY=true`. See [mcp/SETUP.md](mcp/SETUP.md) for full setup instructions.

## Installation

```sh
# Copy to your OPNsense firewall
scp python/opnsense-upgrade.py root@opnsense:/root/
ssh root@opnsense
chmod +x /root/opnsense-upgrade.py

# Show help
./opnsense-upgrade.py

# Check for updates
./opnsense-upgrade.py -l

# Execute minor update
./opnsense-upgrade.py -x -m
```

## Requirements

- **OPNsense Community Edition** (tested on OPNsense Community only; not tested with OPNsense Business Edition)
- Python 3 (included with OPNsense)
- Root access
- Network connectivity to OPNsense pkg mirrors

## Quick Start

```sh
# Check what's available
./opnsense-upgrade.py -l

# Backup configuration and package list
./opnsense-upgrade.py -b

# Preview a minor update (dry run - safe, changes nothing)
./opnsense-upgrade.py -m

# Execute minor update
./opnsense-upgrade.py -x -m

# Preview a major upgrade to specific version (dry run)
./opnsense-upgrade.py -t 27.1

# Execute major upgrade
./opnsense-upgrade.py -x -t 27.1
```

## Command-Line Options

```
Options:
    -h, --help              Show help message and exit
    -l, --latest            Query and display available versions (minor and major)
    -t, --target [VERSION]  Target major version (e.g., 26.7, 27.1)
                            Auto-detects if version omitted
    -m, --minor             Minor update only (within current branch)
    -x, --execute           Execute for real (default is dry run)
    -b, --backup            Standalone: backup config and package list, then exit
    -f, --force             Force mode (no confirmations)
    -r, --resume            Resume from saved state (after reboot or interruption)
    -c, --clean             Clean state and start fresh
```

## Upgrade Stages

| Stage | Description |
|-------|-------------|
| **Pre-checks** | Disk space (2GB minimum), package database health, obsolete package removal, lock file cleanup |
| **Cleanup** | Remove unused packages, clean package cache, clear temp files |
| **Backup** | Back up `/conf/config.xml` and installed package list |
| **Base/Kernel Upgrade** | Runs `opnsense-update -bk` — reboots automatically if kernel changed. Major upgrades always reboot |
| **Fix pkg Compatibility** | After reboot, detect and fix `pkg` binary incompatibility with new base using `pkg-static` or `opnsense-bootstrap` *(major upgrades only)* |
| **Package Upgrade** | Minor: `opnsense-update -p`. Major: switch pkg repo, refresh catalog, upgrade all packages |
| **Post-Verification** | Verify package database health, check critical services (configd, syslog-ng), optional final reboot |

If the user cancels at any stage, the state file is cleaned up so the next run starts fresh.

## Version Detection

The script uses multiple methods to detect available versions, tried in order:

1. **configctl firmware status** - Parses OPNsense firmware API output (JSON and plain text)
2. **Pkg mirror probing** - Checks `pkg.opnsense.org` for next major version repos *(major only)*
3. **opnsense-update -c** - Native OPNsense update check
4. **pkg rquery** - Queries locally cached pkg catalog (`pkg rquery '%v' opnsense`) — most reliable fallback when the firmware daemon cache is empty (e.g., shortly after reboot). Strips `_N` pkg revision suffix automatically.
5. **pkg search** - Queries repo directly if catalog is stale
6. **Changelog directory** - Scans `/usr/local/opnsense/changelog/` *(major only)*

## Auto-Resume After Reboot

When the script triggers a reboot (base/kernel changed), it:

1. Saves the current stage and target version to `/var/db/opnsense-upgrade.state`
2. Creates `/etc/rc.local.d/99-opnsense-upgrade-resume` to auto-resume on boot
3. After reboot, the resume script runs the upgrade script with `-x -r` to continue

The auto-resume script is automatically cleaned up after the upgrade completes.

**Note:** Auto-resume has not yet been tested on OPNsense — it requires a major upgrade where the FreeBSD kernel changes to trigger a reboot mid-upgrade. If it does not trigger, SSH back in after reboot and run manually:

```sh
./opnsense-upgrade.py -x -r
```

**Check auto-resume status after reboot:**
```sh
cat /var/log/opnsense-upgrade-resume.log   # exists if auto-resume ran
cat /var/db/opnsense-upgrade.state         # still present if packages not yet done
grep opnsense-upgrade /var/log/system.log  # logger output from resume script
opnsense-version                           # confirm current version
```

## File Locations

| File | Purpose |
|------|---------|
| `/var/db/opnsense-upgrade.state` | Saved upgrade state (JSON format) |
| `/var/log/opnsense-upgrades/opnsense-{mode}-YYYYMMDD-HHMMSS.log` | Timestamped logs (mode: query, dryrun, or upgrade) |
| `/root/config-backups/config-backup-YYYYMMDD-HHMMSS.xml` | Configuration backups |
| `/root/config-backups/packages-YYYYMMDD-HHMMSS.txt` | Installed package list backups |
| `/etc/rc.local.d/99-opnsense-upgrade-resume` | Auto-resume script (temporary, removed after completion) |
| `/var/log/opnsense-upgrade-resume.log` | Log from auto-resumed upgrades |

## Minor vs Major Upgrades

| Aspect | Minor Update (`-m`) | Major Upgrade (`-t`) |
|--------|-------------------|---------------|
| **Example** | 26.1.1 -> 26.1.2 | 26.1 -> 26.7 or 27.1 |
| **Base/kernel upgrade** | Only if FreeBSD version changed | Yes |
| **Reboot required** | Only if kernel changed | Yes (automatic) |
| **Pkg repo switch** | No | Yes |
| **Risk level** | Low | Medium |
| **Duration** | 5-10 minutes | 15-30 minutes |
| **Command** | `./opnsense-upgrade.py -x -m` | `./opnsense-upgrade.py -x -t 27.1` |

## Recovery Tools (Windows)

If a major upgrade breaks networking on OPNsense, use the PowerShell scripts in [ps1/](ps1/) to set up split routing on your Windows machine:

- **Wired** -> OPNsense (SSH access to fix the upgrade)
- **WiFi** -> Internet (download packages, docs)

```powershell
.\ps1\Enable-SplitRouting-WithModule.ps1
```

Then SSH into OPNsense and resume: `./opnsense-upgrade.py -x -r`

See [ps1/README.md](ps1/README.md) for details.

## Troubleshooting

### pkg not working after base upgrade

The script handles this automatically in the Fix pkg stage. If running manually:

```sh
pkg-static install -fy pkg
```

### Slow downloads

OPNsense's default mirror can be slow. Switch to a regional mirror before upgrading:

```sh
opnsense-update -M "https://mirror.wdc1.us.leaseweb.net/opnsense"
```

### Segmentation faults during upgrade

Segfaults during major upgrades are common and often non-fatal. The script checks the actual installed version after errors to determine if the upgrade succeeded despite the segfaults.

### "Nothing to resume" when using `-r`

Your system is in a normal state with no interrupted upgrade. Run without `-r`:

```sh
./opnsense-upgrade.py -x -m
```

### Want to see logs

```sh
ls -lh /var/log/opnsense-upgrades/
tail -f /var/log/opnsense-upgrades/opnsense-*.log
```

## Best Practices

1. **Always test with dry-run first** - Run without `-x` to preview
2. **Use `-b` for standalone backups** - Backup config anytime
3. **Check logs after completion** - Verify no errors occurred
4. **Test services** - After upgrade, verify firewall rules, VPN, etc.
5. **Schedule maintenance windows** - Especially for major upgrades
6. **Keep console access** - IPMI/serial console for major upgrades
7. **Read the dry-run output** - Understand what will happen

## Documentation

- [python/README.md](python/README.md) - Detailed upgrade script documentation
- [mcp/SETUP.md](mcp/SETUP.md) - MCP server setup guide for Claude Code integration
- [ps1/README.md](ps1/README.md) - Windows recovery tools for failed upgrades

## License

MIT

## Support

For issues, check:
- Python README: [python/README.md](python/README.md)
- Logs: `/var/log/opnsense-upgrades/`
- State file: `cat /var/db/opnsense-upgrade.state`
- OPNsense forums: https://forum.opnsense.org/
