# Windows Recovery Tools for OPNsense

PowerShell scripts for recovering from failed OPNsense upgrades when you lose network connectivity.

## When to Use

During a major OPNsense upgrade, if networking breaks (e.g., after base/kernel upgrade but before packages are updated), you may lose both internet and access to OPNsense. These scripts set up **split routing** on your Windows machine:

- **Wired connection** -> OPNsense (for SSH/console access to fix the upgrade)
- **WiFi connection** -> Internet (for downloading packages, documentation, etc.)

## Files

| File | Purpose |
|------|---------|
| `Enable-SplitRouting-WithModule.ps1` | Enable split routing for OPNsense troubleshooting |
| `OPNsenseCommon.psm1` | Reusable PowerShell module (logging, auto-elevation, config backup) |
| `MODULE-README.md` | Complete reference for the PowerShell module |
| `INSTALL-GUIDE.md` | Installation and setup guide |

## Quick Start

### 1. Install the Module

```powershell
New-Item -ItemType Directory -Path "$env:USERPROFILE\Documents\PowerShell-Common-Functions" -Force
Copy-Item "OPNsenseCommon.psm1" -Destination "$env:USERPROFILE\Documents\PowerShell-Common-Functions\"
```

### 2. Enable Split Routing

```powershell
.\Enable-SplitRouting-WithModule.ps1
```

This configures your Windows machine so wired traffic goes to OPNsense (local network) and WiFi handles internet access.

### 3. Fix the Upgrade

With split routing active, SSH into OPNsense and resume the upgrade:

```sh
ssh root@opnsense
./opnsense-upgrade.py -x -r
```

## Requirements

- Windows 10/11 with PowerShell 5.1+
- Wired Ethernet connection to OPNsense
- WiFi connection for internet access
- Administrator privileges (scripts auto-elevate)

## Documentation

- See [MODULE-README.md](MODULE-README.md) for module function reference
- See [INSTALL-GUIDE.md](INSTALL-GUIDE.md) for detailed installation instructions
