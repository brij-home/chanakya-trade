# ==============================================================================
# ChanakyaTrade — Seamless Background Service Manager (Windows PowerShell)
# ==============================================================================
# Usage:
#   .\scripts\service.ps1 -Action start
#   .\scripts\service.ps1 -Action stop
#   .\scripts\service.ps1 -Action restart
#   .\scripts\service.ps1 -Action status
#   .\scripts\service.ps1 -Action restart -NoFrontend
# ==============================================================================

[CmdletBinding()]
param (
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "restart",
    [switch]$NoFrontend,
    [switch]$SkipBuildWeb,
    [string]$ApiHost = "127.0.0.1",
    [int]$ApiPort = 8765,
    [int]$VitePort = 5173,
    [int]$TimeoutSeconds = 12
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $RootDir ".logs"
$PythonExe = Join-Path $RootDir ".venv\Scripts\python.exe"
$FrontendDir = Join-Path $RootDir "macos-app"
$PidFile = Join-Path $LogDir "services.json"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

function Stop-ChanakyaServices {
    Write-Host "[*] Stopping existing ChanakyaTrade background services..." -ForegroundColor Cyan
    & (Join-Path $ScriptDir "quick_cleanup.ps1")
    if (Test-Path $PidFile) {
        Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-ServiceStatus {
    Write-Host "`n=== ChanakyaTrade Service Status ===" -ForegroundColor Cyan
    $backendLive = $false
    $frontendLive = $false

    try {
        $bPort = Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($bPort) {
            $backendLive = $true
            Write-Host " [+] Backend (FastAPI):  RUNNING on http://${ApiHost}:${ApiPort} (PID: $($bPort.OwningProcess))" -ForegroundColor Green
        } else {
            Write-Host " [-] Backend (FastAPI):  STOPPED (port $ApiPort not listening)" -ForegroundColor DarkGray
        }
    } catch {
        Write-Host " [-] Backend (FastAPI):  UNKNOWN" -ForegroundColor DarkGray
    }

    try {
        $fPort = Get-NetTCPConnection -LocalPort $VitePort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($fPort) {
            $frontendLive = $true
            Write-Host " [+] Frontend (Vite/UI): RUNNING on http://localhost:$VitePort (PID: $($fPort.OwningProcess))" -ForegroundColor Green
        } else {
            Write-Host " [-] Frontend (Vite/UI): STOPPED (port $VitePort not listening)" -ForegroundColor DarkGray
        }
    } catch {
        Write-Host " [-] Frontend (Vite/UI): UNKNOWN" -ForegroundColor DarkGray
    }

    Write-Host "====================================`n" -ForegroundColor Cyan
    return ($backendLive -and ($NoFrontend -or $frontendLive))
}

if ($Action -eq "stop") {
    Stop-ChanakyaServices
    Write-Host "[+] All services cleanly stopped." -ForegroundColor Green
    exit 0
}

if ($Action -eq "status") {
    Get-ServiceStatus | Out-Null
    exit 0
}

# --- Action: start or restart ---

Stop-ChanakyaServices

# 1. Optionally rebuild web bundle to ensure web/static is synced
if (-not $SkipBuildWeb -and (Test-Path "$FrontendDir\package.json")) {
    Write-Host "[*] Synchronizing web static bundle (npm run build:web)..." -ForegroundColor Cyan
    Push-Location $FrontendDir
    try {
        & cmd.exe /c "npm.cmd run build:web" | Out-Null
        Write-Host " [+] Web bundle synchronized to web/static/" -ForegroundColor Green
    } catch {
        Write-Warning "Web build reported warning. Continuing..."
    } finally {
        Pop-Location
    }
}

# 2. Launch FastAPI backend completely detached from parent Job Object via WMI
$backendOut = Join-Path $LogDir "backend.log"
$backendErr = Join-Path $LogDir "backend_err.log"

Write-Host "[*] Launching detached FastAPI Sidecar on http://${ApiHost}:${ApiPort} ..." -ForegroundColor Cyan
$backendCmd = "cmd.exe /c `"`"$PythonExe`" -m uvicorn web.api:app --host $ApiHost --port $ApiPort > `"$backendOut`" 2> `"$backendErr`"`""
$bRes = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $backendCmd
    CurrentDirectory = $RootDir
}
$backendPid = $bRes.ProcessId

# 3. Launch Frontend (if requested)
$frontendPid = $null
if (-not $NoFrontend -and (Test-Path $FrontendDir)) {
    $frontendOut = Join-Path $LogDir "frontend.log"
    $frontendErr = Join-Path $LogDir "frontend_err.log"

    Write-Host "[*] Launching detached Electron & Vite Desktop App on http://localhost:$VitePort ..." -ForegroundColor Cyan
    $frontendCmd = "cmd.exe /c `"npm.cmd run dev > `"$frontendOut`" 2> `"$frontendErr`"`""
    $fRes = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $frontendCmd
        CurrentDirectory = $FrontendDir
    }
    $frontendPid = $fRes.ProcessId
}

# Save PID info
$pids = @{
    backend_pid = $backendPid
    frontend_pid = $frontendPid
    started_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
}
$pids | ConvertTo-Json | Set-Content -Path $PidFile -Force

# 4. Wait for healthy socket binding
Write-Host "[*] Waiting for services to initialize..." -ForegroundColor Gray
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$backendReady = $false

while ($sw.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
    Start-Sleep -Milliseconds 800
    try {
        $conn = Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            $backendReady = $true
            break
        }
    } catch {}
}

if ($backendReady) {
    Write-Host " [+] FastAPI Sidecar is healthy and listening on http://${ApiHost}:${ApiPort}" -ForegroundColor Green
    if (-not $NoFrontend) {
        # Check Vite port
        Start-Sleep -Seconds 1
        $fConn = Get-NetTCPConnection -LocalPort $VitePort -State Listen -ErrorAction SilentlyContinue
        if ($fConn) {
            Write-Host " [+] Frontend Desktop & Vite are listening on http://localhost:$VitePort" -ForegroundColor Green
        } else {
            Write-Host " [*] Frontend is initializing in background (check $LogDir\frontend.log)" -ForegroundColor Yellow
        }
    }
    Write-Host "`n[SUCCESS] ChanakyaTrade background services are running seamlessly!" -ForegroundColor Green
    Write-Host "  • Logs: $LogDir\backend.log, $LogDir\frontend.log" -ForegroundColor DarkGray
    Write-Host "  • Management: .\scripts\service.ps1 [status | stop | restart]" -ForegroundColor DarkGray
} else {
    Write-Warning "Backend did not respond within $TimeoutSeconds seconds. Check $backendErr"
}

exit 0
