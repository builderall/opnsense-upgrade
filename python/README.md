# OPNsense Upgrade Script — Python Version

Python 3 OOP implementation of the OPNsense multi-stage upgrade script. Uses only stdlib modules — no pip dependencies.

**Version:** 1.0
**License:** MIT

## Features

- **Automatic version detection** - Queries OPNsense firmware API and pkg mirrors
- **Stateful upgrades** - Survives reboots with automatic resume
- **Dry-run by default** - Safe testing before execution (use `-x` to execute)
- **Multi-stage process** - Pre-checks, Cleanup, Backup, Base/Kernel, Fix pkg, Packages, Verification
- **Automatic recovery** - Handles pkg incompatibility after base upgrades
- **Standalone backup** - Use `-b` to backup config and package list anytime
- **Always backs up during upgrades** - Config and package list saved before every upgrade
- **Version summary** - Use `-l` to see both minor and major versions available
- **Smart auto-detection** - `-t` without version detects major upgrades, `-m` detects minor updates
- **Safety guards** - Blocks major upgrades when minor updates are pending
- **Detailed logging** - All operations logged with mode-prefixed filenames (query/dryrun/upgrade)
- **No arguments = help** - Shows help by default for safety

## Requirements

- Python 3 (included with OPNsense at `/usr/local/bin/python3`)
- OPNsense Community Edition
- Root access

## Installation

```sh
scp opnsense-upgrade.py root@opnsense:/root/
ssh root@opnsense
chmod +x /root/opnsense-upgrade.py
```

## Quick Start

```sh
# Show help
./opnsense-upgrade.py

# Check what's available
./opnsense-upgrade.py -l

# Backup config and package list
./opnsense-upgrade.py -b

# Preview a minor update (dry run)
./opnsense-upgrade.py -m

# Execute minor update
./opnsense-upgrade.py -x -m

# Preview major upgrade (dry run)
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

## Usage Patterns

### 1. Check for Updates

```sh
./opnsense-upgrade.py -l
```

**Output example:**
```
============================================
  Available Versions
============================================

i Current version:  26.1.1
✓ Minor update:     26.1.2  (use -m to update)
i Major upgrade:    none available
```

### 2. Standalone Backup

```sh
./opnsense-upgrade.py -b
```

**Output example:**
```
============================================
  Configuration Backup
============================================

✓ Config backed up: /root/config-backups/config-backup-20260219-221057.xml
✓ Package list saved: /root/config-backups/packages-20260219-221057.txt

i Backup contents:
i   Settings (XML):   /root/config-backups/config-backup-20260219-221057.xml
i   Package list:     /root/config-backups/packages-20260219-221057.txt
i   Original config:  /conf/config.xml

i To restore settings, copy the XML backup back:
i   cp /root/config-backups/config-backup-20260219-221057.xml /conf/config.xml
```

### 3. Minor Update (Patch Release)

**Minor updates** are patch releases within the same major version (e.g., 26.1.1 -> 26.1.2).

```sh
# Dry-run (preview)
./opnsense-upgrade.py -m

# Execute
./opnsense-upgrade.py -x -m
```

**What happens:**
- Auto-detects the latest patch version (e.g., 26.1.2)
- Backs up config and package list
- Runs `opnsense-update -bk` to update base/kernel if changed — reboots automatically if the kernel changed, then resumes from packages
- Runs `opnsense-update -p` to upgrade OPNsense packages
- Fast and low-risk — reboot only happens if the FreeBSD kernel version actually changed

### 4. Major Upgrade (New Release)

**Major upgrades** are version changes to a new branch (e.g., 26.1 -> 26.7 or 27.1).

```sh
# Dry-run (preview)
./opnsense-upgrade.py -t 27.1

# Execute
./opnsense-upgrade.py -x -t 27.1
```

**What happens:**
- Backs up config and package list
- Upgrades base and kernel via `opnsense-update -ubkf`
- **Reboots** the system
- Auto-resumes after reboot to fix pkg compatibility
- Switches pkg repo to new branch
- Upgrades all packages
- Slower and higher risk (test in dry-run first!)

**Safety:** Major upgrades are blocked if minor updates are pending. Apply minor updates first (matching OPNsense web UI behavior).

### 5. Auto-Detect Major Upgrade

```sh
# Auto-detect (tells you if no major is available)
./opnsense-upgrade.py -t
```

If no major version is available, the script tells you and suggests using `-m` instead.

### 6. Resume After Reboot

The script automatically resumes after reboots during major upgrades. You can also manually resume:

```sh
./opnsense-upgrade.py -x -r
```

### 7. Clean State and Start Over

If an upgrade gets stuck or you want to start fresh:

```sh
./opnsense-upgrade.py -c
```

## Examples

| Command | Description |
|---------|-------------|
| `./opnsense-upgrade.py` | Show help |
| `./opnsense-upgrade.py -l` | Show available versions (minor and major) |
| `./opnsense-upgrade.py -b` | Backup config and package list |
| `./opnsense-upgrade.py -m` | **Dry run** minor update |
| `./opnsense-upgrade.py -x -m` | **Execute** minor update |
| `./opnsense-upgrade.py -t 26.7` | **Dry run** major upgrade to 26.7 |
| `./opnsense-upgrade.py -x -t 26.7` | **Execute** major upgrade to 26.7 |
| `./opnsense-upgrade.py -t` | **Auto-detect** major upgrade |
| `./opnsense-upgrade.py -x -r` | **Resume** interrupted upgrade |
| `./opnsense-upgrade.py -c` | Clean saved state |

## Dry Run (Default Behavior)

**All runs are dry runs by default.** The script shows exactly what it would do without making any changes:

```
i Starting dry run: minor update from 26.1.1 to 26.1.2
...
i [DRY RUN] Would run: opnsense-update -bk
i [DRY RUN] Would reboot if base/kernel changed
i [DRY RUN] State checkpoint: Package Upgrade, Version 26.1.2
...
i [DRY RUN] Would run: opnsense-update -p

============================================
  Dry Run Complete
============================================

✓ Dry run finished - no changes were made
i Current version: 26.1.1
i Review the output above, then run with -x to execute
```

Add `-x` to execute for real. When executing, the script asks for confirmation before starting.

## Upgrade Stages

| Stage | Description |
|-------|-------------|
| **Pre-checks** | Disk space (2GB min), pkg database validation, lock file cleanup |
| **Cleanup** | Remove unused packages, clean cache, clear temp files |
| **Backup** | Save config.xml and package list |
| **Base/Kernel** | Runs `opnsense-update -bk` — reboots if kernel changed. For major upgrades uses `opnsense-update -ubkf` and always reboots |
| **Fix pkg** | Reinstall pkg after base upgrade to ensure compatibility *(major upgrades only)* |
| **Packages** | Minor: `opnsense-update -p`. Major: switch repo, refresh catalog, upgrade all packages via `pkg upgrade` |
| **Post-Verification** | Verify pkg database, check services (configd, syslog-ng) |

## Architecture

The script uses 5 classes with single-responsibility design:

| Class | Responsibility |
|-------|---------------|
| `Stage` | Stage constants, names, execution order |
| `Logger` | Colored console output + file logging |
| `Shell` | Subprocess execution with dry-run support |
| `SystemInfo` | Version detection, mirror queries, state detection |
| `StateManager` | JSON state file persistence |
| `OPNsenseUpgrade` | Orchestrator — stages, reboot handling, main flow |

**Stdlib modules used:** `argparse`, `json`, `subprocess`, `urllib`, `os`, `re`, `shutil`, `time`, `datetime`

## Version Detection

The script uses multiple methods to detect available versions, tried in order:

1. **configctl firmware status** - Parses OPNsense firmware API output (JSON and plain text)
2. **Pkg mirror probing** - Checks `pkg.opnsense.org` for next major version repos *(major upgrades only)*
3. **opnsense-update -c** - Native OPNsense update check
4. **pkg rquery** - Queries the locally cached pkg catalog: `pkg rquery '%v' opnsense` — most reliable fallback when the firmware daemon hasn't refreshed yet (e.g., shortly after reboot). Strips the `_N` pkg revision suffix automatically.
5. **pkg search** - Queries the repo directly if catalog is stale
6. **Changelog directory** - Scans `/usr/local/opnsense/changelog/` *(major upgrades only)*

Methods 1-3 rely on the OPNsense firmware daemon cache which may be empty after a fresh reboot. Method 4 (`pkg rquery`) reliably detects minor updates even when the firmware daemon hasn't run yet.

## State File Format

The script uses JSON at `/var/db/opnsense-upgrade.state`:

```json
{
  "stage": 6,
  "version": "26.1.2",
  "timestamp": 1738900000,
  "minor_only": false,
  "force_mode": false,
  "log_file": "/var/log/opnsense-upgrades/opnsense-upgrade-20260219-201934.log"
}
```

## Smart State Detection

When resuming without a state file (`-r` with no saved state), the script dynamically detects the system state:

- **ABI mismatch**: Compares running FreeBSD kernel vs. pkg ABI — if different, base was upgraded but packages weren't -> Resume from Fix pkg
- **Pending updates**: Checks `opnsense-update -c` for updates -> Resume from Base/Kernel
- **Already upgraded**: Current version matches target -> Exit as complete
- **Normal state**: No interrupted upgrade -> Report "Nothing to resume"

## Auto-Resume After Reboot

For upgrades requiring a reboot (base/kernel changed):

1. Saves state to `/var/db/opnsense-upgrade.state`
2. Creates `/etc/rc.local.d/99-opnsense-upgrade-resume` (shell script)
3. After reboot, waits 10 seconds, then auto-runs with `-x -r`
4. Removes auto-resume script when upgrade completes

**Note:** Auto-resume via `/etc/rc.local.d/` has not yet been tested on OPNsense — a major upgrade with an actual base/kernel reboot is required to verify it. If auto-resume does not trigger, SSH back in after reboot and run manually:

```sh
./opnsense-upgrade.py -x -r
```

After reboot, check whether auto-resume ran before resuming manually:
```sh
cat /var/log/opnsense-upgrade-resume.log   # exists if auto-resume ran
cat /var/db/opnsense-upgrade.state         # still present if not yet resumed
grep opnsense-upgrade /var/log/system.log  # logger output from resume script
```

## File Locations

| File | Purpose |
|------|---------|
| `/var/db/opnsense-upgrade.state` | Saved upgrade state (JSON) |
| `/var/log/opnsense-upgrades/opnsense-{mode}-YYYYMMDD-HHMMSS.log` | Timestamped logs (mode: query, dryrun, or upgrade) |
| `/root/config-backups/config-backup-YYYYMMDD-HHMMSS.xml` | Config backups |
| `/root/config-backups/packages-YYYYMMDD-HHMMSS.txt` | Package list backups |
| `/etc/rc.local.d/99-opnsense-upgrade-resume` | Auto-resume script (temporary) |
| `/var/log/opnsense-upgrade-resume.log` | Auto-resume logs |

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

## Troubleshooting

### "Nothing to resume" when using `-r`

Your system is in a normal state with no interrupted upgrade. Run without `-r`:

```sh
./opnsense-upgrade.py -x -m
```

### "Found existing upgrade in progress!"

A previous run left a state file. Clean it and start fresh:

```sh
./opnsense-upgrade.py -c
./opnsense-upgrade.py -x -m
```

### "pkg process is running"

Wait for background pkg process or kill it:

```sh
pkill pkg
rm -f /var/run/pkg.lock
```

### "Insufficient disk space"

Free up space:

```sh
pkg clean -ay
rm -rf /tmp/* /var/tmp/*
find /var/log -name "*.log" -mtime +30 -delete
```

### Upgrade interrupted or failed

Resume from saved state:

```sh
./opnsense-upgrade.py -x -r
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

## Safety Features

- **Dry-run by default** - Must explicitly use `-x` to execute
- **Pre-flight checks** - Validates disk space, pkg database, locks
- **State persistence** - Can resume from any stage after reboot
- **Always backs up** - Config and package list saved before every upgrade
- **Mirror validation** - Ensures target version exists before starting
- **Minor-before-major** - Blocks major upgrades when minor updates are pending
- **Error detection** - Stops on failures, allows manual intervention
- **Confirmation prompts** - Asks before starting (unless `-f` used)
- **Auto-resume safety** - Only resumes if state file exists

## License

MIT

## Support

For issues, check:
- Logs in `/var/log/opnsense-upgrades/`
- State file: `cat /var/db/opnsense-upgrade.state`
- OPNsense forums: https://forum.opnsense.org/
