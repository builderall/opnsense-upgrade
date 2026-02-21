# Enable-SplitRouting.ps1 (Using OPNsenseCommon Module)
# Simplified version using reusable functions

<#
.SYNOPSIS
    Enable split routing for OPNsense troubleshooting
.DESCRIPTION
    Configures wired connection for local OPNsense access only, while using WiFi hotspot for internet.
    Uses OPNsenseCommon module for logging, elevation, and backup.
.PARAMETER WiredAdapter
    Name of the wired network adapter (e.g., "Ethernet")
.PARAMETER WiFiAdapter
    Name of the WiFi network adapter (e.g., "Wi-Fi")
.PARAMETER OPNsenseIP
    IP address of your OPNsense firewall (e.g., "192.168.1.1")
.PARAMETER LocalNetwork
    Your local network in CIDR notation (e.g., "192.168.1.0/24")
.PARAMETER LocalGateway
    Gateway IP for local network (usually your OPNsense LAN IP, e.g., "192.168.1.1")
.EXAMPLE
    .\Enable-SplitRouting.ps1
.EXAMPLE
    .\Enable-SplitRouting.ps1 -WiredAdapter "Ethernet 2" -OPNsenseIP "10.0.0.1"
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$WiredAdapter = "Ethernet",
    
    [Parameter(Mandatory=$false)]
    [string]$WiFiAdapter = "Wi-Fi",
    
    [Parameter(Mandatory=$false)]
    [string]$OPNsenseIP = "192.168.1.1",
    
    [Parameter(Mandatory=$false)]
    [string]$LocalNetwork = "192.168.1.0/24",
    
    [Parameter(Mandatory=$false)]
    [string]$LocalGateway = "192.168.1.1"
)

# Import common module
$modulePath = Join-Path ([Environment]::GetFolderPath('MyDocuments')) "PowerShell-Common-Functions\OPNsenseCommon.psm1"

if (-not (Test-Path $modulePath)) {
    Write-Host "ERROR: OPNsenseCommon module not found!" -ForegroundColor Red
    Write-Host "Expected location: $modulePath" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Please install the module first:" -ForegroundColor Cyan
    Write-Host '  1. Create folder: Documents\PowerShell-Common-Functions\' -ForegroundColor Gray
    Write-Host '  2. Copy OPNsenseCommon.psm1 to that folder' -ForegroundColor Gray
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Import-Module $modulePath -Force

# Auto-elevate if needed
if (-not (Initialize-ElevatedScript -ScriptPath $PSCommandPath -ScriptArguments $PSBoundParameters)) {
    exit
}

# Initialize logging
$logFile = Initialize-Logging -ScriptName "Enable-SplitRouting"

# Display header
Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host "  OPNsense Split Routing Setup" -ForegroundColor Cyan
Write-Host "============================================`n" -ForegroundColor Cyan

Write-Success "Running with administrator privileges"
Write-Info "Log file: $logFile"
Write-Host ""

Write-Info "Configuration:"
Write-Host "  Wired Adapter  : $WiredAdapter"
Write-Host "  WiFi Adapter   : $WiFiAdapter"
Write-Host "  OPNsense IP    : $OPNsenseIP"
Write-Host "  Local Network  : $LocalNetwork"
Write-Host "  Local Gateway  : $LocalGateway"
Write-Host ""

Write-Log "Configuration: WiredAdapter=$WiredAdapter, WiFiAdapter=$WiFiAdapter, OPNsenseIP=$OPNsenseIP, LocalNetwork=$LocalNetwork, LocalGateway=$LocalGateway" "INFO"

try {
    # Step 1: Verify adapters exist
    Write-Info "Step 1: Verifying network adapters..."
    
    $wired = Get-NetAdapter -Name $WiredAdapter -ErrorAction SilentlyContinue
    $wifi = Get-NetAdapter -Name $WiFiAdapter -ErrorAction SilentlyContinue

    if (-not $wired) {
        Write-ErrorMsg "Wired adapter '$WiredAdapter' not found!"
        Write-Info "Available adapters:"
        $adapters = Get-NetAdapter | Format-Table Name, Status, LinkSpeed | Out-String
        Write-Host $adapters
        throw "Wired adapter not found"
    }

    if (-not $wifi) {
        Write-WarningMsg "WiFi adapter '$WiFiAdapter' not found!"
        Write-Info "Available adapters:"
        Get-NetAdapter | Format-Table Name, Status, LinkSpeed
        Write-WarningMsg "You'll need to connect to your phone's WiFi hotspot manually"
    }

    if ($wired.Status -ne "Up") {
        Write-WarningMsg "Wired adapter is not connected!"
        Write-Info "Please connect your ethernet cable and try again"
        throw "Wired adapter not connected"
    }

    Write-Success "Wired adapter found and connected"

    # Step 2: Backup current configuration
    Write-Info "Step 2: Backing up current network configuration..."
    $backupFile = New-ConfigBackup -AdapterName $WiredAdapter
    
    # Step 3: Remove default gateway from wired connection
    Write-Info "Step 3: Removing default gateway from wired connection..."
    
    $defaultRoutes = Get-NetRoute -InterfaceAlias $WiredAdapter -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue
    if ($defaultRoutes) {
        Remove-NetRoute -InterfaceAlias $WiredAdapter -DestinationPrefix "0.0.0.0/0" -Confirm:$false -ErrorAction Stop
        Write-Success "Default gateway removed from $WiredAdapter"
    } else {
        Write-Info "No default gateway found on $WiredAdapter"
    }

    # Step 4: Add persistent routes for local network
    Write-Info "Step 4: Adding persistent routes for local OPNsense access..."
    
    # Remove existing routes to avoid conflicts
    $existingRoute = Get-NetRoute -DestinationPrefix $LocalNetwork -ErrorAction SilentlyContinue | Where-Object {$_.InterfaceAlias -eq $WiredAdapter}
    if ($existingRoute) {
        Remove-NetRoute -DestinationPrefix $LocalNetwork -InterfaceAlias $WiredAdapter -Confirm:$false -ErrorAction SilentlyContinue
        Write-Log "Removed existing route for $LocalNetwork" "INFO"
    }
    
    # Add route for local network
    New-NetRoute -DestinationPrefix $LocalNetwork `
                 -InterfaceAlias $WiredAdapter `
                 -NextHop $LocalGateway `
                 -RouteMetric 1 `
                 -PolicyStore PersistentStore `
                 -ErrorAction Stop | Out-Null
    Write-Success "Route added: $LocalNetwork via $WiredAdapter"
    
    # Add specific route for OPNsense IP
    $existingOPNRoute = Get-NetRoute -DestinationPrefix "$OPNsenseIP/32" -ErrorAction SilentlyContinue | Where-Object {$_.InterfaceAlias -eq $WiredAdapter}
    if ($existingOPNRoute) {
        Remove-NetRoute -DestinationPrefix "$OPNsenseIP/32" -InterfaceAlias $WiredAdapter -Confirm:$false -ErrorAction SilentlyContinue
    }
    
    New-NetRoute -DestinationPrefix "$OPNsenseIP/32" `
                 -InterfaceAlias $WiredAdapter `
                 -NextHop $LocalGateway `
                 -RouteMetric 1 `
                 -PolicyStore PersistentStore `
                 -ErrorAction Stop | Out-Null
    Write-Success "Route added: $OPNsenseIP via $WiredAdapter"

    # Step 5: Enable WiFi adapter if disabled
    if ($wifi) {
        Write-Info "Step 5: Enabling WiFi adapter..."
        
        if ($wifi.Status -ne "Up") {
            Enable-NetAdapter -Name $WiFiAdapter -Confirm:$false -ErrorAction Stop
            Write-Success "WiFi adapter enabled"
            Start-Sleep -Seconds 2
        } else {
            Write-Success "WiFi adapter already enabled"
        }
    }

    # Step 6: Verify configuration
    Write-Info "Step 6: Verifying configuration..."
    Write-Host ""

    # Test local access
    Write-Info "Testing local OPNsense access..."
    $localTest = Test-NetConnection -ComputerName $OPNsenseIP -WarningAction SilentlyContinue -ErrorAction SilentlyContinue
    if ($localTest.PingSucceeded) {
        Write-Success "OPNsense is reachable at $OPNsenseIP"
    } else {
        Write-WarningMsg "Cannot ping OPNsense at $OPNsenseIP (may be normal if ping is disabled)"
    }

    # Test internet access
    Write-Info "Testing internet access..."
    $internetTest = Test-NetConnection -ComputerName 8.8.8.8 -WarningAction SilentlyContinue -ErrorAction SilentlyContinue
    if ($internetTest.PingSucceeded) {
        Write-Success "Internet access working (via WiFi)"
    } else {
        Write-WarningMsg "No internet access detected"
        if (-not $wifi -or $wifi.Status -ne "Up") {
            Write-Info "Please connect to your phone's WiFi hotspot for internet access"
        }
    }

    # Display routing table
    Write-Host "`n============================================" -ForegroundColor Cyan
    Write-Host "  Current Routing Table" -ForegroundColor Cyan
    Write-Host "============================================`n" -ForegroundColor Cyan

    $routeTable = Get-NetRoute | Where-Object {
        $_.DestinationPrefix -eq "0.0.0.0/0" -or 
        $_.DestinationPrefix -eq $LocalNetwork -or 
        $_.DestinationPrefix -eq "$OPNsenseIP/32"
    } | Format-Table DestinationPrefix, NextHop, InterfaceAlias, RouteMetric -AutoSize | Out-String

    Write-Host $routeTable
    Write-Log "Final routing table: $routeTable" "INFO"

    # Success
    Write-Host "`n============================================" -ForegroundColor Green
    Write-Host "  Split Routing Enabled Successfully!" -ForegroundColor Green
    Write-Host "============================================`n" -ForegroundColor Green

    Write-Info "What this means:"
    Write-Host "  • OPNsense ($OPNsenseIP) → Uses $WiredAdapter"
    Write-Host "  • Local network ($LocalNetwork) → Uses $WiredAdapter"
    Write-Host "  • Internet (everything else) → Uses WiFi hotspot"
    Write-Host ""
    Write-Info "You can now troubleshoot OPNsense while maintaining internet access!"
    Write-Host ""
    Write-WarningMsg "To restore normal operation, run: .\Restore-NormalRouting.ps1"
    Write-Host ""
    
    Close-Log -Status "Success"
    
} catch {
    Write-ErrorMsg "Script failed: $_"
    Write-Log "Exception: $($_.Exception.Message)" "ERROR"
    Write-Log "Stack trace: $($_.ScriptStackTrace)" "DEBUG"
    
    Close-Log -Status "Failed"
    Read-Host "Press Enter to exit"
    exit 1
}

Show-LogLocation
Read-Host "Press Enter to exit"
