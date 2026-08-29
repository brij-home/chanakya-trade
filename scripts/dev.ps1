# ==============================================================================
# ChanakyaTrade — Local Greenfield Development Bootstrap (Windows PowerShell)
# ==============================================================================
# Usage:
#   .\scripts\dev.ps1
#   .\scripts\dev.ps1 -NoFrontend
#   .\scripts\dev.ps1 -Port 8765
# ==============================================================================

[CmdletBinding()]
param (
    [switch]$NoFrontend,
    [int]$ApiPort = 8765,
    [int]$VitePort = 5173,
    [switch]$SkipPreflight
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "   ChanakyaTrade — AI-Powered Institutional Quant Terminal" -ForegroundColor Yellow
Write-Host "   Local-First Greenfield Bootstrap (Windows Environment)" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Resolve Python Executable
$PythonExe = $null
if (Test-Path "$RootDir\.venv\Scripts\python.exe") {
    $PythonExe = "$RootDir\.venv\Scripts\python.exe"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonExe = (Get-Command python).Source
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonExe = "py"
} else {
    Write-Error "Python 3.11+ is required but was not found in PATH or .venv."
    exit 1
}

Write-Host "[+] Python Executable: $PythonExe" -ForegroundColor Green

# 2. Run Preflight Diagnostics
if (-not $SkipPreflight) {
    Write-Host "[*] Running system preflight checks..." -ForegroundColor Gray
    try {
        & $PythonExe -m scripts.preflight
    } catch {
        Write-Warning "Preflight checks reported warnings. Proceeding with caution..."
    }
}

# 3. Ensure Frontend Dependencies
$FrontendDir = Join-Path $RootDir "macos-app"
if (-not $NoFrontend -and (Test-Path $FrontendDir)) {
    if (-not (Test-Path "$FrontendDir\node_modules")) {
        Write-Host "[*] Installing frontend dependencies in macos-app..." -ForegroundColor Yellow
        Push-Location $FrontendDir
        try {
            & cmd.exe /c "npm.cmd install"
        } finally {
            Pop-Location
        }
    }
}

# 4. Start FastAPI Backend & Vite Frontend with Graceful Shutdown
Write-Host ""
Write-Host "[*] Launching FastAPI Sidecar on http://127.0.0.1:$ApiPort ..." -ForegroundColor Cyan
if (-not $NoFrontend) {
    Write-Host "[*] Launching Vite Frontend on http://127.0.0.1:$VitePort ..." -ForegroundColor Cyan
}
Write-Host ""
Write-Host "Press Ctrl+C to terminate all services." -ForegroundColor Magenta
Write-Host ""

$BackendProcess = $null
$FrontendProcess = $null

try {
    # Start Backend
    $BackendStartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $BackendStartInfo.FileName = $PythonExe
    $BackendStartInfo.Arguments = "-m uvicorn web.api:app --host 127.0.0.1 --port $ApiPort --reload"
    $BackendStartInfo.WorkingDirectory = $RootDir
    $BackendStartInfo.UseShellExecute = $false
    $BackendProcess = [System.Diagnostics.Process]::Start($BackendStartInfo)

    # Start Frontend (if requested)
    if (-not $NoFrontend -and (Test-Path $FrontendDir)) {
        Start-Sleep -Seconds 1
        $FrontendStartInfo = New-Object System.Diagnostics.ProcessStartInfo
        $FrontendStartInfo.FileName = "cmd.exe"
        $FrontendStartInfo.Arguments = "/c npm.cmd run dev"
        $FrontendStartInfo.WorkingDirectory = $FrontendDir
        $FrontendStartInfo.UseShellExecute = $false
        $FrontendProcess = [System.Diagnostics.Process]::Start($FrontendStartInfo)
    }

    # Wait for child processes
    if ($BackendProcess) {
        $BackendProcess.WaitForExit()
    }
} finally {
    Write-Host "`n[*] Stopping development services..." -ForegroundColor Yellow
    if ($FrontendProcess -and -not $FrontendProcess.HasExited) {
        Stop-Process -Id $FrontendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($BackendProcess -and -not $BackendProcess.HasExited) {
        Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[+] All services cleanly stopped." -ForegroundColor Green
}
