# ─────────────────────────────────────────────────────────────────────────────
# run_client.ps1  —  Start the Vyuhaa Client UI
# Usage:  .\run_client.ps1
# ─────────────────────────────────────────────────────────────────────────────

$Root   = $PSScriptRoot
$Py     = Join-Path $Root ".venv\Scripts\python.exe"
$Main   = Join-Path $Root "vyuhaa_client\vyuhaa_client\main.py"

if (-not (Test-Path $Py)) {
    Write-Host "Venv not found. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}

Set-Location (Join-Path $Root "vyuhaa_client\vyuhaa_client")
Write-Host "Starting Vyuhaa Client..." -ForegroundColor Cyan
& $Py $Main @args
