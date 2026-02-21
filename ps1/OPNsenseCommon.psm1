# OPNsenseCommon.psm1
# Common functions for OPNsense troubleshooting scripts
# Version: 1.0
# Location: Documents\PowerShell-Common-Functions\OPNsenseCommon.psm1

<#
.SYNOPSIS
    Common PowerShell functions for OPNsense troubleshooting scripts
.DESCRIPTION
    Provides reusable functions for:
    - Auto-elevation with parameter preservation
    - Comprehensive logging with timestamps
    - Configuration backup and restore
    - Color-coded console output
    - User path management across elevation
#>

#region Global Variables
$script:LogFile = $null
$script:BackupFile = $null
$script:OriginalUserDocuments = $null
#endregion

#region Path Management

<#
.SYNOPSIS
    Gets the original user's Documents folder path, even when elevated
.DESCRIPTION
    Captures the user's Documents path before elevation and stores it for use by elevated processes
.OUTPUTS
    String - Path to the original user's Documents folder
#>
function Get-OriginalUserPath {
    [CmdletBinding()]
    param()
    
    # Try to get from environment variable first (if elevated)
    if ($env:ORIGINAL_USER_DOCS) {
        return $env:ORIGINAL_USER_DOCS
    }
    
    # Otherwise get current user's documents
    return [Environment]::GetFolderPath('MyDocuments')
}

<#
.SYNOPSIS
    Sets the original user's Documents path for use by elevated processes
.PARAMETER Path
    Path to the original user's Documents folder
#>
function Set-OriginalUserPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$Path
    )
    
    $script:OriginalUserDocuments = $Path
    $env:ORIGINAL_USER_DOCS = $Path
}

#endregion

#region Auto-Elevation

<#
.SYNOPSIS
    Ensures script is running with administrator privileges
.DESCRIPTION
    Checks if running as admin, if not, relaunches script with elevation
    Preserves all parameters passed to the original script
.PARAMETER ScriptPath
    Full path to the script file
.PARAMETER ScriptArguments
    Hashtable of script parameters and their values
.EXAMPLE
    Initialize-ElevatedScript -ScriptPath $PSCommandPath -ScriptArguments $PSBoundParameters
#>
function Initialize-ElevatedScript {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$ScriptPath,
        
        [Parameter(Mandatory=$false)]
        [hashtable]$ScriptArguments = @{}
    )
    
    # Check if already running as administrator
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if ($currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        return $true  # Already elevated
    }
    
    Write-Host "Requesting administrator privileges..." -ForegroundColor Yellow
    
    # Capture original user's Documents path before elevation
    $originalDocs = [Environment]::GetFolderPath('MyDocuments')
    Set-OriginalUserPath -Path $originalDocs
    
    # Build argument string from hashtable
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
    
    foreach ($key in $ScriptArguments.Keys) {
        $value = $ScriptArguments[$key]
        if ($value -is [switch] -or $value -is [bool]) {
            if ($value) {
                $arguments += " -$key"
            }
        } else {
            $arguments += " -$key `"$value`""
        }
    }
    
    # Start elevated process
    Start-Process PowerShell.exe -ArgumentList $arguments -Verb RunAs
    exit
}

#endregion

#region Logging Functions

<#
.SYNOPSIS
    Initializes logging system
.DESCRIPTION
    Creates log directory and file, sets permissions for regular user access
.PARAMETER ScriptName
    Name of the script (used in log filename)
.PARAMETER SubFolder
    Optional subfolder within Documents for logs (default: "OPNsense-SplitRouting-Logs")
.OUTPUTS
    String - Full path to the log file
.EXAMPLE
    Initialize-Logging -ScriptName "Enable-SplitRouting"
#>
function Initialize-Logging {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$ScriptName,
        
        [Parameter(Mandatory=$false)]
        [string]$SubFolder = "OPNsense-SplitRouting-Logs"
    )
    
    # Get original user's documents path
    $userDocs = Get-OriginalUserPath
    $logDir = Join-Path $userDocs $SubFolder
    
    # Create log directory with proper permissions
    if (-not (Test-Path $logDir)) {
        $newDir = New-Item -ItemType Directory -Path $logDir -Force
        
        # Set permissions for all users
        try {
            $acl = Get-Acl $logDir
            $accessRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                "Users", 
                "FullControl", 
                "ContainerInherit,ObjectInherit", 
                "None", 
                "Allow"
            )
            $acl.SetAccessRule($accessRule)
            Set-Acl -Path $logDir -AclObject $acl
        } catch {
            Write-Warning "Could not set permissions on log directory: $_"
        }
    }
    
    # Create log file
    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $script:LogFile = Join-Path $logDir "$ScriptName-$timestamp.log"
    
    # Write header
    Add-Content -Path $script:LogFile -Value "=========================================="
    Add-Content -Path $script:LogFile -Value "Script: $ScriptName"
    Add-Content -Path $script:LogFile -Value "Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Add-Content -Path $script:LogFile -Value "User: $env:USERNAME"
    Add-Content -Path $script:LogFile -Value "Computer: $env:COMPUTERNAME"
    Add-Content -Path $script:LogFile -Value "=========================================="
    Add-Content -Path $script:LogFile -Value ""
    
    return $script:LogFile
}

<#
.SYNOPSIS
    Writes a log entry with timestamp and level
.PARAMETER Message
    The message to log
.PARAMETER Level
    Log level (INFO, SUCCESS, WARNING, ERROR, DEBUG)
.EXAMPLE
    Write-Log "Configuration backup created" "SUCCESS"
#>
function Write-Log {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$Message,
        
        [Parameter(Mandatory=$false)]
        [ValidateSet("INFO", "SUCCESS", "WARNING", "ERROR", "DEBUG")]
        [string]$Level = "INFO"
    )
    
    if (-not $script:LogFile) {
        Write-Warning "Logging not initialized. Call Initialize-Logging first."
        return
    }
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] [$Level] $Message"
    
    try {
        Add-Content -Path $script:LogFile -Value $logMessage
    } catch {
        Write-Warning "Failed to write to log: $_"
    }
}

<#
.SYNOPSIS
    Writes a success message to console and log
#>
function Write-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
    Write-Log $Message "SUCCESS"
}

<#
.SYNOPSIS
    Writes an info message to console and log
#>
function Write-Info {
    param([string]$Message)
    Write-Host "ℹ $Message" -ForegroundColor Cyan
    Write-Log $Message "INFO"
}

<#
.SYNOPSIS
    Writes an error message to console and log
#>
function Write-ErrorMsg {
    param([string]$Message)
    Write-Host "✗ $Message" -ForegroundColor Red
    Write-Log $Message "ERROR"
}

<#
.SYNOPSIS
    Writes a warning message to console and log
#>
function Write-WarningMsg {
    param([string]$Message)
    Write-Host "⚠ $Message" -ForegroundColor Yellow
    Write-Log $Message "WARNING"
}

<#
.SYNOPSIS
    Writes a debug message to console and log
#>
function Write-DebugMsg {
    param([string]$Message)
    Write-Host "🔍 $Message" -ForegroundColor Gray
    Write-Log $Message "DEBUG"
}

#endregion

#region Backup and Restore Functions

<#
.SYNOPSIS
    Creates a backup of network configuration
.DESCRIPTION
    Backs up IP configuration, routes, and DNS settings for specified adapter
.PARAMETER AdapterName
    Name of the network adapter to backup
.PARAMETER BackupLocation
    Optional custom backup location (default: %TEMP%)
.OUTPUTS
    String - Path to the backup file
.EXAMPLE
    New-ConfigBackup -AdapterName "Ethernet"
#>
function New-ConfigBackup {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$AdapterName,
        
        [Parameter(Mandatory=$false)]
        [string]$BackupLocation = $env:TEMP
    )
    
    Write-Info "Creating configuration backup for $AdapterName..."
    Write-Log "Creating backup for adapter: $AdapterName" "INFO"
    
    try {
        $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $script:BackupFile = Join-Path $BackupLocation "network-backup-$timestamp.json"
        
        # Gather configuration
        $config = @{
            Timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
            AdapterName = $AdapterName
            IPAddress = Get-NetIPAddress -InterfaceAlias $AdapterName -AddressFamily IPv4 -ErrorAction SilentlyContinue
            Routes = Get-NetRoute -InterfaceAlias $AdapterName -ErrorAction SilentlyContinue | 
                Select-Object DestinationPrefix, NextHop, RouteMetric, InterfaceAlias
            DNS = Get-DnsClientServerAddress -InterfaceAlias $AdapterName -AddressFamily IPv4 -ErrorAction SilentlyContinue
            AdapterInfo = Get-NetAdapter -Name $AdapterName -ErrorAction SilentlyContinue | 
                Select-Object Name, Status, LinkSpeed, MacAddress
        }
        
        # Save to JSON
        $config | ConvertTo-Json -Depth 5 | Out-File $script:BackupFile -Encoding UTF8
        
        Write-Success "Backup created: $script:BackupFile"
        Write-Log "Backup file created: $script:BackupFile" "SUCCESS"
        
        return $script:BackupFile
        
    } catch {
        Write-ErrorMsg "Failed to create backup: $_"
        Write-Log "Backup failed: $_" "ERROR"
        return $null
    }
}

<#
.SYNOPSIS
    Restores network configuration from backup
.PARAMETER BackupFile
    Path to the backup JSON file
.PARAMETER WhatIf
    Shows what would be restored without making changes
.OUTPUTS
    Boolean - True if restore successful, False otherwise
.EXAMPLE
    Restore-ConfigBackup -BackupFile "C:\Temp\network-backup-20260207-143015.json"
#>
function Restore-ConfigBackup {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory=$true)]
        [string]$BackupFile,
        
        [Parameter(Mandatory=$false)]
        [switch]$WhatIf
    )
    
    if (-not (Test-Path $BackupFile)) {
        Write-ErrorMsg "Backup file not found: $BackupFile"
        Write-Log "Backup file not found: $BackupFile" "ERROR"
        return $false
    }
    
    Write-Info "Restoring configuration from: $BackupFile"
    Write-Log "Starting restore from: $BackupFile" "INFO"
    
    try {
        # Load backup
        $backup = Get-Content $BackupFile -Raw | ConvertFrom-Json
        $adapterName = $backup.AdapterName
        
        Write-Info "Backup from: $($backup.Timestamp)"
        Write-Info "Adapter: $adapterName"
        
        if ($WhatIf) {
            Write-Host "`nWould restore:" -ForegroundColor Yellow
            Write-Host "  IP Address: $($backup.IPAddress.IPAddress)"
            Write-Host "  Routes: $($backup.Routes.Count) route(s)"
            Write-Host "  DNS Servers: $($backup.DNS.ServerAddresses -join ', ')"
            return $true
        }
        
        # Verify adapter exists
        $adapter = Get-NetAdapter -Name $adapterName -ErrorAction SilentlyContinue
        if (-not $adapter) {
            Write-ErrorMsg "Adapter '$adapterName' not found on this system"
            Write-Log "Adapter not found: $adapterName" "ERROR"
            return $false
        }
        
        # Ask for confirmation
        $response = Read-Host "Restore configuration to $adapterName? This will override current settings (Y/N)"
        Write-Log "User response to restore: $response" "INFO"
        
        if ($response -ne "Y" -and $response -ne "y") {
            Write-WarningMsg "Restore cancelled by user"
            Write-Log "Restore cancelled by user" "WARNING"
            return $false
        }
        
        # Restore would go here - this is a template
        # Actual restoration depends on specific needs
        Write-WarningMsg "Note: Full restore functionality should be implemented based on specific requirements"
        Write-Log "Restore template executed - implement specific restore logic as needed" "WARNING"
        
        return $true
        
    } catch {
        Write-ErrorMsg "Restore failed: $_"
        Write-Log "Restore failed: $_" "ERROR"
        return $false
    }
}

<#
.SYNOPSIS
    Lists available backup files
.PARAMETER BackupLocation
    Location to search for backups (default: %TEMP%)
.PARAMETER Count
    Maximum number of recent backups to list (default: 10)
.OUTPUTS
    Array of backup file objects
.EXAMPLE
    Get-ConfigBackups
#>
function Get-ConfigBackups {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$false)]
        [string]$BackupLocation = $env:TEMP,
        
        [Parameter(Mandatory=$false)]
        [int]$Count = 10
    )
    
    Write-Info "Searching for backups in: $BackupLocation"
    
    $backups = Get-ChildItem -Path $BackupLocation -Filter "network-backup-*.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First $Count
    
    if ($backups) {
        Write-Host "`nFound $($backups.Count) backup(s):" -ForegroundColor Cyan
        foreach ($backup in $backups) {
            $age = (Get-Date) - $backup.LastWriteTime
            $ageStr = if ($age.TotalHours -lt 1) { "$([int]$age.TotalMinutes) min ago" }
                     elseif ($age.TotalDays -lt 1) { "$([int]$age.TotalHours) hours ago" }
                     else { "$([int]$age.TotalDays) days ago" }
            
            Write-Host "  $($backup.Name) - $ageStr" -ForegroundColor Gray
        }
        Write-Log "Found $($backups.Count) backup files" "INFO"
    } else {
        Write-WarningMsg "No backups found in $BackupLocation"
        Write-Log "No backups found" "WARNING"
    }
    
    return $backups
}

#endregion

#region Utility Functions

<#
.SYNOPSIS
    Closes the log file with summary
.PARAMETER Status
    Final status (Success, Failed, Cancelled)
#>
function Close-Log {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$false)]
        [ValidateSet("Success", "Failed", "Cancelled")]
        [string]$Status = "Success"
    )
    
    if ($script:LogFile) {
        Add-Content -Path $script:LogFile -Value ""
        Add-Content -Path $script:LogFile -Value "=========================================="
        Add-Content -Path $script:LogFile -Value "Completed: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        Add-Content -Path $script:LogFile -Value "Status: $Status"
        Add-Content -Path $script:LogFile -Value "=========================================="
    }
}

<#
.SYNOPSIS
    Displays the log file location to the user
#>
function Show-LogLocation {
    [CmdletBinding()]
    param()
    
    if ($script:LogFile) {
        Write-Host ""
        Write-Info "Log file saved to: $script:LogFile"
        Write-Host ""
    }
}

#endregion

# Export module members
Export-ModuleMember -Function @(
    'Get-OriginalUserPath',
    'Set-OriginalUserPath',
    'Initialize-ElevatedScript',
    'Initialize-Logging',
    'Write-Log',
    'Write-Success',
    'Write-Info',
    'Write-ErrorMsg',
    'Write-WarningMsg',
    'Write-DebugMsg',
    'New-ConfigBackup',
    'Restore-ConfigBackup',
    'Get-ConfigBackups',
    'Close-Log',
    'Show-LogLocation'
)
