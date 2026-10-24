<#
.SYNOPSIS
    HPE iLO Firmware Upgrade Automation Suite PowerShell Launcher.
.DESCRIPTION
    Automates environment verification, dependency installation, and launches the Redfish iLO upgrade workflow.
.PARAMETER Excel
    Path to the Excel inventory file (default: sample_inventory.xlsx)
.PARAMETER FirmwareDir
    Path to local firmware directory (default: firmware)
.PARAMETER Mock
    Runs in Mock simulation mode for safe dry-run testing
.EXAMPLE
    .\run_ilo_updater.ps1
.EXAMPLE
    .\run_ilo_updater.ps1 -Excel ".\my_datacenter.xlsx" -FirmwareDir "C:\iLO_Firmware"
.EXAMPLE
    .\run_ilo_updater.ps1 -Mock
#>

param (
    [string]$Excel = "sample_inventory.xlsx",
    [string]$FirmwareDir = "firmware",
    [switch]$Mock,
    [switch]$Template
)

$Host.UI.RawUI.WindowTitle = "HPE iLO Firmware Upgrade Automation Suite"

Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host "           HPE iLO FIRMWARE UPGRADE AUTOMATION SUITE                           " -ForegroundColor White
Write-Host "           Redfish RESTful API - PowerShell Launcher                           " -ForegroundColor Cyan
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "[ERROR] Python was not found in your PATH." -ForegroundColor Red
    Write-Host "Please download and install Python 3.8+ from https://www.python.org/" -ForegroundColor Yellow
    Write-Host "Ensure 'Add Python to PATH' is checked during setup." -ForegroundColor Yellow
    Read-Host "Press Enter to exit..."
    exit 1
}

$pyVersion = & python --version
Write-Host "[INFO] Detected Python: $pyVersion" -ForegroundColor Green

# 2. Virtual Environment Setup
$venvPython = ".\venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[INFO] Creating virtual environment (venv)..." -ForegroundColor Yellow
    & python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
        exit 1
    }
    Write-Host "[INFO] Installing dependencies (requests, openpyxl, rich)..." -ForegroundColor Yellow
    & .\venv\Scripts\pip install -r requirements.txt
}

# 3. Build Arguments
$argsList = @("main.py", "--excel", $Excel, "--firmware-dir", $FirmwareDir)
if ($Mock) { $argsList += "--mock" }
if ($Template) { $argsList += "--template" }

# 4. Launch Application
Write-Host "[INFO] Launching Redfish Firmware Updater..." -ForegroundColor Cyan
& $venvPython $argsList

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[WARNING] Process exited with exit code $LASTEXITCODE." -ForegroundColor Yellow
}

Write-Host "`n===============================================================================" -ForegroundColor Cyan
Write-Host "Completed. Press Enter to exit..." -ForegroundColor Gray
Read-Host
