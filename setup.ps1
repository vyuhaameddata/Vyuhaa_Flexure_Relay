# setup.ps1 - Run once on any machine to create the venv and install deps
# Usage:  .\setup.ps1

$Root  = $PSScriptRoot
$Venv  = Join-Path $Root ".venv"
$Py    = Join-Path $Venv "Scripts\python.exe"

Write-Host ""
Write-Host "=== Vyuhaa Setup ===" -ForegroundColor Cyan
Write-Host "Root : $Root"
Write-Host "Venv : $Venv"
Write-Host ""

# 1. Create venv (delete and recreate if broken from another machine)
$needCreate = $true
if (Test-Path $Py) {
    & $Py -c "import sys" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[1/3] Venv already exists and is valid, skipping creation." -ForegroundColor Green
        $needCreate = $false
    } else {
        Write-Host "[1/3] Venv exists but is broken (wrong machine) - recreating..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force $Venv
    }
}
if ($needCreate) {
    Write-Host "[1/3] Creating virtual environment..." -ForegroundColor Yellow
    python -m venv $Venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: 'python' not found. Install Python 3.10+ and add it to PATH." -ForegroundColor Red
        exit 1
    }
}

# 2. Upgrade pip
Write-Host "[2/3] Upgrading pip..." -ForegroundColor Yellow
& $Py -m pip install --upgrade pip --quiet

# 3. Install dependencies
Write-Host "[3/3] Installing dependencies..." -ForegroundColor Yellow

$ServerReqs = Join-Path $Root "vyuhaa_jetson\vyuhaa_jetson\requirements.txt"
$ClientReqs = Join-Path $Root "vyuhaa_client\vyuhaa_client\requirements.txt"

if (Test-Path $ServerReqs) {
    Write-Host "  -> server requirements" -ForegroundColor Gray
    & $Py -m pip install -r $ServerReqs --quiet
}
if (Test-Path $ClientReqs) {
    Write-Host "  -> client requirements" -ForegroundColor Gray
    & $Py -m pip install -r $ClientReqs --quiet
}

Write-Host ""
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host "Now run:  .\run_server.ps1   and   .\run_client.ps1"
Write-Host ""
