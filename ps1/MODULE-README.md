# OPNsense Common PowerShell Module

Reusable PowerShell functions for network troubleshooting scripts with auto-elevation, logging, backup, and restore capabilities.

## Installation

### Quick Install

1. **Copy the module to your Documents folder:**
   ```powershell
   # Create the directory
   New-Item -ItemType Directory -Path "$env:USERPROFILE\Documents\PowerShell-Common-Functions" -Force
   
   # Copy the module file
   Copy-Item "OPNsenseCommon.psm1" -Destination "$env:USERPROFILE\Documents\PowerShell-Common-Functions\"
   ```

2. **Done!** The module is ready to use.

### Installation Location

```
C:\Users\YourUsername\Documents\PowerShell-Common-Functions\
  └─ OPNsenseCommon.psm1
```

## Usage in Your Scripts

### Basic Template

```powershell
# Import the common module
$modulePath = Join-Path ([Environment]::GetFolderPath('MyDocuments')) "PowerShell-Common-Functions\OPNsenseCommon.psm1"
Import-Module $modulePath -Force

# Your script parameters
param(
    [string]$SomeParameter = "default"
)

# Auto-elevate if needed
if (-not (Initialize-ElevatedScript -ScriptPath $PSCommandPath -ScriptArguments $PSBoundParameters)) {
    exit
}

# Initialize logging
$logFile = Initialize-Logging -ScriptName "MyScript"
Write-Info "Script started"

# Your script logic here
try {
    Write-Success "Task completed successfully"
    Close-Log -Status "Success"
} catch {
    Write-ErrorMsg "Script failed: $_"
    Close-Log -Status "Failed"
    Read-Host "Press Enter to exit"
    exit 1
}

Show-LogLocation
Read-Host "Press Enter to exit"
```

## Available Functions

### Auto-Elevation

#### Initialize-ElevatedScript
Automatically elevates script to admin if needed, preserving all parameters.

```powershell
Initialize-ElevatedScript -ScriptPath $PSCommandPath -ScriptArguments $PSBoundParameters
```

**Returns:** `$true` if already elevated, otherwise relaunches and exits

### Logging

#### Initialize-Logging
Sets up logging system with timestamped log file.

```powershell
$logFile = Initialize-Logging -ScriptName "MyScript"
$logFile = Initialize-Logging -ScriptName "MyScript" -SubFolder "Custom-Log-Folder"
```

**Returns:** Full path to the log file

#### Write-Log
Writes a timestamped log entry.

```powershell
Write-Log "Configuration saved" "SUCCESS"
Write-Log "Processing item" "INFO"
Write-Log "Potential issue detected" "WARNING"
Write-Log "Operation failed" "ERROR"
Write-Log "Debugging information" "DEBUG"
```

**Levels:** INFO, SUCCESS, WARNING, ERROR, DEBUG

#### Write-Success, Write-Info, Write-ErrorMsg, Write-WarningMsg, Write-DebugMsg
Color-coded console output with automatic logging.

```powershell
Write-Success "Operation completed successfully"
Write-Info "Processing configuration..."
Write-ErrorMsg "Failed to connect to server"
Write-WarningMsg "Configuration may be incomplete"
Write-DebugMsg "Current value: $variable"
```

#### Close-Log
Closes the log file with a status summary.

```powershell
Close-Log -Status "Success"
Close-Log -Status "Failed"
Close-Log -Status "Cancelled"
```

#### Show-LogLocation
Displays the log file location to the user.

```powershell
Show-LogLocation
```

### Backup and Restore

#### New-ConfigBackup
Creates a JSON backup of network adapter configuration.

```powershell
$backupFile = New-ConfigBackup -AdapterName "Ethernet"
$backupFile = New-ConfigBackup -AdapterName "Ethernet" -BackupLocation "C:\Backups"
```

**Backs up:**
- IP addresses
- Routes
- DNS settings
- Adapter information

**Returns:** Path to the backup file

#### Restore-ConfigBackup
Restores configuration from a backup file.

```powershell
Restore-ConfigBackup -BackupFile "C:\Temp\network-backup-20260207-143015.json"
Restore-ConfigBackup -BackupFile $backupFile -WhatIf  # Preview without changing
```

**Returns:** `$true` if successful, `$false` otherwise

#### Get-ConfigBackups
Lists available backup files.

```powershell
Get-ConfigBackups
Get-ConfigBackups -BackupLocation "C:\Backups" -Count 5
```

**Returns:** Array of backup file objects

### Path Management

#### Get-OriginalUserPath
Gets the original user's Documents folder, even when elevated.

```powershell
$userDocs = Get-OriginalUserPath
```

**Returns:** Path to original user's Documents folder

#### Set-OriginalUserPath
Sets the original user's path for elevated processes (internal use).

```powershell
Set-OriginalUserPath -Path "C:\Users\Username\Documents"
```

## Complete Example Script

```powershell
# MyNetworkScript.ps1
# Import common functions
$modulePath = Join-Path ([Environment]::GetFolderPath('MyDocuments')) "PowerShell-Common-Functions\OPNsenseCommon.psm1"
Import-Module $modulePath -Force

# Script parameters
param(
    [Parameter(Mandatory=$false)]
    [string]$AdapterName = "Ethernet",
    
    [Parameter(Mandatory=$false)]
    [switch]$CreateBackup
)

# Auto-elevate if needed
if (-not (Initialize-ElevatedScript -ScriptPath $PSCommandPath -ScriptArguments $PSBoundParameters)) {
    exit
}

# Initialize logging
$logFile = Initialize-Logging -ScriptName "MyNetworkScript"

Write-Info "Starting network configuration changes..."
Write-Log "Adapter: $AdapterName, CreateBackup: $CreateBackup" "INFO"

try {
    # Create backup if requested
    if ($CreateBackup) {
        $backupFile = New-ConfigBackup -AdapterName $AdapterName
        if (-not $backupFile) {
            throw "Failed to create backup"
        }
    }
    
    # Your network configuration logic here
    Write-Info "Modifying network settings..."
    
    # Example: Get adapter
    $adapter = Get-NetAdapter -Name $AdapterName -ErrorAction Stop
    Write-Success "Found adapter: $($adapter.Name)"
    
    # More logic here...
    
    Write-Success "Configuration completed successfully"
    Close-Log -Status "Success"
    
} catch {
    Write-ErrorMsg "Script failed: $_"
    Write-Log "Exception: $($_.Exception.Message)" "ERROR"
    Write-Log "Stack trace: $($_.ScriptStackTrace)" "DEBUG"
    
    # Optionally restore from backup
    if ($backupFile -and (Test-Path $backupFile)) {
        Write-WarningMsg "Backup available at: $backupFile"
        $restore = Read-Host "Would you like to restore from backup? (Y/N)"
        if ($restore -eq "Y" -or $restore -eq "y") {
            Restore-ConfigBackup -BackupFile $backupFile
        }
    }
    
    Close-Log -Status "Failed"
    Read-Host "Press Enter to exit"
    exit 1
}

# Show log location and available backups
Show-LogLocation
Get-ConfigBackups -Count 3

Read-Host "Press Enter to exit"
```

## Log File Format

Logs are saved to: `Documents\OPNsense-SplitRouting-Logs\` (or custom subfolder)

Example log content:
```
==========================================
Script: MyNetworkScript
Started: 2026-02-07 14:30:15
User: Manjunath
Computer: DESKTOP-ABC123
==========================================

[2026-02-07 14:30:15] [INFO] Starting network configuration changes...
[2026-02-07 14:30:15] [INFO] Adapter: Ethernet, CreateBackup: True
[2026-02-07 14:30:16] [INFO] Creating backup for adapter: Ethernet
[2026-02-07 14:30:16] [SUCCESS] Backup file created: C:\Temp\network-backup-20260207-143016.json
[2026-02-07 14:30:17] [SUCCESS] Found adapter: Ethernet
[2026-02-07 14:30:20] [SUCCESS] Configuration completed successfully

==========================================
Completed: 2026-02-07 14:30:20
Status: Success
==========================================
```

## Backup File Format

Backups are saved as JSON files with this structure:

```json
{
  "Timestamp": "2026-02-07 14:30:16",
  "AdapterName": "Ethernet",
  "IPAddress": {
    "IPAddress": "192.168.1.100",
    "PrefixLength": 24,
    "PrefixOrigin": "Dhcp"
  },
  "Routes": [
    {
      "DestinationPrefix": "0.0.0.0/0",
      "NextHop": "192.168.1.1",
      "RouteMetric": 10,
      "InterfaceAlias": "Ethernet"
    }
  ],
  "DNS": {
    "ServerAddresses": ["192.168.1.1", "8.8.8.8"]
  },
  "AdapterInfo": {
    "Name": "Ethernet",
    "Status": "Up",
    "LinkSpeed": "1 Gbps",
    "MacAddress": "00-11-22-33-44-55"
  }
}
```

## Benefits of Using This Module

✅ **Consistent Logging** - All scripts use the same log format and location  
✅ **Auto-Elevation** - No need to manually run as Administrator  
✅ **User-Friendly** - Logs always go to the regular user's Documents folder  
✅ **Color-Coded Output** - Easy to read success/error/warning messages  
✅ **Backup Safety** - Easy to create and restore configuration backups  
✅ **Reusable** - Write once, use in all your scripts  
✅ **Auditable** - Complete audit trail of all operations  

## Module Function Reference

| Function | Purpose |
|----------|---------|
| `Initialize-ElevatedScript` | Auto-elevate with parameter preservation |
| `Initialize-Logging` | Setup logging system |
| `Write-Log` | Write timestamped log entry |
| `Write-Success` | Green success message + log |
| `Write-Info` | Cyan info message + log |
| `Write-ErrorMsg` | Red error message + log |
| `Write-WarningMsg` | Yellow warning message + log |
| `Write-DebugMsg` | Gray debug message + log |
| `New-ConfigBackup` | Create network config backup |
| `Restore-ConfigBackup` | Restore from backup |
| `Get-ConfigBackups` | List available backups |
| `Get-OriginalUserPath` | Get user's Documents path |
| `Set-OriginalUserPath` | Set user's Documents path |
| `Close-Log` | Close log with status |
| `Show-LogLocation` | Display log file path |

## Troubleshooting

### Module Not Found
If you get "Module not found" error:
```powershell
# Check if file exists
Test-Path "$env:USERPROFILE\Documents\PowerShell-Common-Functions\OPNsenseCommon.psm1"

# If false, re-copy the module to the correct location
```

### Permissions Error
If logs can't be written:
```powershell
# Check log directory permissions
Get-Acl "$env:USERPROFILE\Documents\OPNsense-SplitRouting-Logs"

# The module automatically sets permissions, but you can manually fix:
$logDir = "$env:USERPROFILE\Documents\OPNsense-SplitRouting-Logs"
$acl = Get-Acl $logDir
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule("Users","FullControl","ContainerInherit,ObjectInherit","None","Allow")
$acl.SetAccessRule($rule)
Set-Acl $logDir $acl
```

## Version History

- **v1.0** (2026-02-07) - Initial release
  - Auto-elevation with parameter preservation
  - Comprehensive logging system
  - Network configuration backup/restore
  - Color-coded console output
  - User path management across elevation

## License

Free to use and modify for your own scripts.

## Contributing

To add new common functions:
1. Add the function to `OPNsenseCommon.psm1`
2. Document it in this README
3. Add it to the `Export-ModuleMember` list
4. Update the version history
