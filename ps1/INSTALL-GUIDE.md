# Installation and Migration Guide

This guide explains how to install the OPNsenseCommon module and migrate your existing scripts to use it.

## Quick Installation

### Step 1: Create the Module Directory

Open PowerShell (no admin needed) and run:

```powershell
New-Item -ItemType Directory -Path "$env:USERPROFILE\Documents\PowerShell-Common-Functions" -Force
```

This creates: `C:\Users\YourUsername\Documents\PowerShell-Common-Functions\`

### Step 2: Copy the Module File

Copy `OPNsenseCommon.psm1` to the folder you just created.

**Final location:**
```
C:\Users\YourUsername\Documents\PowerShell-Common-Functions\
  └─ OPNsenseCommon.psm1
```

### Step 3: Verify Installation

```powershell
# Check if file exists
Test-Path "$env:USERPROFILE\Documents\PowerShell-Common-Functions\OPNsenseCommon.psm1"
```

Should return `True`

### Step 4: Test the Module

```powershell
# Try importing it
$modulePath = Join-Path ([Environment]::GetFolderPath('MyDocuments')) "PowerShell-Common-Functions\OPNsenseCommon.psm1"
Import-Module $modulePath -Force

# Test a function
Write-Success "Module loaded successfully!"
```

If you see a green checkmark, it's working!

## What You Get

### Files Included

1. **OPNsenseCommon.psm1** - The reusable module
2. **MODULE-README.md** - Complete function reference and examples
3. **Enable-SplitRouting-WithModule.ps1** - Example refactored script
4. **INSTALL-GUIDE.md** - This file

### Your Current Scripts

Your existing standalone scripts will continue to work:
- ✅ `Enable-SplitRouting.ps1` - Original standalone version
- ✅ `Restore-NormalRouting.ps1` - Original standalone version

Both already have auto-elevation and logging built in.

## Two Approaches

### Approach 1: Keep Using Standalone Scripts (Easier)

**Pros:**
- ✅ No migration needed
- ✅ Scripts work independently
- ✅ All functionality already there

**Cons:**
- ⚠️ Each script duplicates common code
- ⚠️ Updates require editing multiple scripts

**When to use:** If you only have 1-2 scripts and don't plan to create more.

### Approach 2: Migrate to Module (Recommended for Multiple Scripts)

**Pros:**
- ✅ Much cleaner, shorter scripts
- ✅ Consistent behavior across all scripts
- ✅ Update common functions once, all scripts benefit
- ✅ Easy to create new scripts

**Cons:**
- ⚠️ Requires module installation
- ⚠️ Scripts depend on external module

**When to use:** If you plan to create more troubleshooting scripts.

## Migration Example

### Before (Standalone Script - ~350 lines)

```powershell
# Enable-SplitRouting.ps1 - Full code with elevation, logging, etc.
# ... 350+ lines of code including:
# - Auto-elevation logic
# - Logging setup
# - All logging functions
# - Backup creation
# - Network configuration
# - Error handling
```

### After (Using Module - ~150 lines)

```powershell
# Enable-SplitRouting.ps1
# Import module
Import-Module "$env:USERPROFILE\Documents\PowerShell-Common-Functions\OPNsenseCommon.psm1" -Force

# Auto-elevate
Initialize-ElevatedScript -ScriptPath $PSCommandPath -ScriptArguments $PSBoundParameters

# Initialize logging
Initialize-Logging -ScriptName "Enable-SplitRouting"

# Your actual logic (100 lines instead of 350)
# ... network configuration code ...

Close-Log -Status "Success"
```

**Result:** 
- 55% less code to maintain
- All common functions reusable
- Consistent logging across all scripts

## Creating New Scripts Using the Module

### Template for New Scripts

Save this as a template for any new network script:

```powershell
# MyNewScript.ps1

<#
.SYNOPSIS
    Brief description
.DESCRIPTION
    Detailed description
.PARAMETER SomeParam
    Parameter description
#>

param(
    [string]$SomeParam = "default"
)

# Import common module
$modulePath = Join-Path ([Environment]::GetFolderPath('MyDocuments')) "PowerShell-Common-Functions\OPNsenseCommon.psm1"
if (-not (Test-Path $modulePath)) {
    Write-Host "ERROR: OPNsenseCommon module not found at: $modulePath" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Import-Module $modulePath -Force

# Auto-elevate if needed
if (-not (Initialize-ElevatedScript -ScriptPath $PSCommandPath -ScriptArguments $PSBoundParameters)) {
    exit
}

# Initialize logging
$logFile = Initialize-Logging -ScriptName "MyNewScript"

Write-Host "`n========== My New Script ==========" -ForegroundColor Cyan
Write-Info "Starting..."

try {
    # Your script logic here
    Write-Success "Task completed"
    
    Close-Log -Status "Success"
} catch {
    Write-ErrorMsg "Failed: $_"
    Write-Log "Exception: $($_.Exception.Message)" "ERROR"
    Close-Log -Status "Failed"
    Read-Host "Press Enter to exit"
    exit 1
}

Show-LogLocation
Read-Host "Press Enter to exit"
```

## Comparison: Your Current Options

### Option 1: Original Standalone Scripts

**Files you have:**
- `Enable-SplitRouting.ps1` (350+ lines, all-in-one)
- `Restore-NormalRouting.ps1` (300+ lines, all-in-one)

**Advantages:**
- No dependencies
- Works immediately
- Already has all features you need

**Use when:**
- You only need these two scripts
- You don't plan to create more scripts

### Option 2: Module-Based Scripts

**Files you have:**
- `OPNsenseCommon.psm1` (shared functions)
- `Enable-SplitRouting-WithModule.ps1` (150 lines, uses module)
- Similar for Restore-NormalRouting-WithModule.ps1

**Advantages:**
- Cleaner, more maintainable code
- Easy to create new scripts
- Consistent logging across all scripts
- Update once, benefits everywhere

**Use when:**
- You plan to create more troubleshooting scripts
- You want cleaner, more maintainable code
- You work on multiple network automation tasks

## Recommendation

### For Immediate Use:
**Use the standalone scripts** (`Enable-SplitRouting.ps1` and `Restore-NormalRouting.ps1`)
- They already have everything you need
- No setup required
- Work perfectly as-is

### For Future Development:
**Install the module** and migrate when you need to create a third script
- The module will save you time
- Keeps your scripts clean and consistent
- Makes troubleshooting easier with centralized logging

## Migration Steps (If You Choose Module Approach)

1. **Install the module** (see Quick Installation above)

2. **Test with one script:**
   ```powershell
   # Rename your current script
   Rename-Item "Enable-SplitRouting.ps1" "Enable-SplitRouting-Standalone.ps1"
   
   # Use the module version
   Rename-Item "Enable-SplitRouting-WithModule.ps1" "Enable-SplitRouting.ps1"
   
   # Test it
   .\Enable-SplitRouting.ps1
   ```

3. **If it works, migrate the restore script too**

4. **Keep the standalone versions as backup** until you're confident

## Troubleshooting Installation

### "Module not found" Error

**Problem:** Script can't find `OPNsenseCommon.psm1`

**Solution:**
```powershell
# Verify the path
$expectedPath = "$env:USERPROFILE\Documents\PowerShell-Common-Functions\OPNsenseCommon.psm1"
Test-Path $expectedPath

# If False, check where your Documents folder actually is:
[Environment]::GetFolderPath('MyDocuments')

# Make sure the module is there:
Copy-Item "OPNsenseCommon.psm1" -Destination "$env:USERPROFILE\Documents\PowerShell-Common-Functions\"
```

### Permission Errors

**Problem:** Can't create log files

**Solution:** The module handles this automatically, but if issues persist:
```powershell
# Ensure log directory exists with correct permissions
$logDir = "$env:USERPROFILE\Documents\OPNsense-SplitRouting-Logs"
New-Item -ItemType Directory -Path $logDir -Force

# Set permissions
$acl = Get-Acl $logDir
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule("Users","FullControl","ContainerInherit,ObjectInherit","None","Allow")
$acl.SetAccessRule($rule)
Set-Acl $logDir $acl
```

### Script Execution Policy

**Problem:** "Cannot be loaded because running scripts is disabled"

**Solution:**
```powershell
# Check current policy
Get-ExecutionPolicy

# If Restricted, set to RemoteSigned (run as admin):
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser

# Or bypass for single script:
PowerShell.exe -ExecutionPolicy Bypass -File ".\Enable-SplitRouting.ps1"
```

## File Structure Summary

### After Full Installation:

```
C:\Users\YourUsername\Documents\
├─ PowerShell-Common-Functions\
│  ├─ OPNsenseCommon.psm1           # The reusable module
│  └─ MODULE-README.md              # Function reference
│
├─ OPNsense-SplitRouting-Logs\      # Auto-created by scripts
│  ├─ Enable-SplitRouting-20260207-143015.log
│  ├─ Restore-NormalRouting-20260207-151030.log
│  └─ ...
│
└─ Your Scripts\
   ├─ Enable-SplitRouting.ps1           # Standalone version
   ├─ Restore-NormalRouting.ps1         # Standalone version
   ├─ Enable-SplitRouting-WithModule.ps1   # Module-based version
   └─ Any future scripts...
```

## Next Steps

1. **Install the module** (5 minutes)
2. **Read MODULE-README.md** for function reference
3. **Test with the example script** (`Enable-SplitRouting-WithModule.ps1`)
4. **Create your own scripts** using the template
5. **Enjoy cleaner, more maintainable code!**

## Questions?

- Check **MODULE-README.md** for detailed function documentation
- Check **README.md** for script-specific help
- Check **OPNsense_Upgrade_Troubleshooting_Guide.docx** for the original issue documentation

## Summary

You now have:
- ✅ Working standalone scripts (ready to use immediately)
- ✅ Reusable module for future scripts (install when ready)
- ✅ Complete documentation
- ✅ Example refactored script
- ✅ Template for new scripts

Choose the approach that fits your needs best!
