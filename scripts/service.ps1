# ==============================================================================
# ChanakyaTrade — Ultra-Fast Background Service Manager (Windows PowerShell)
# ==============================================================================
# Usage:
#   .\scripts\service.ps1 -Action start
#   .\scripts\service.ps1 -Action stop
#   .\scripts\service.ps1 -Action restart
#   .\scripts\service.ps1 -Action status
#   .\scripts\service.ps1 -Action restart -NoFrontend
#   .\scripts\service.ps1 -Action restart -ForceBuildWeb
# ==============================================================================

[CmdletBinding()]
param (
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "restart",
    [switch]$NoFrontend,
    [switch]$SkipBuildWeb,
    [switch]$ForceBuildWeb,
    [string]$ApiHost = "127.0.0.1",
    [int]$ApiPort = 8765,
    [int]$VitePort = 5173,
    [int]$TimeoutSeconds = 90,
    [switch]$Reload,
    [switch]$Calibrate
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
    
    # 1. Fast PID termination from services.json (< 10ms)
    if (Test-Path $PidFile) {
        try {
            $pData = Get-Content -Path $PidFile -Raw | ConvertFrom-Json
            if ($pData.backend_pid) {
                Stop-Process -Id $pData.backend_pid -Force -ErrorAction SilentlyContinue
            }
            if ($pData.frontend_pid) {
                Stop-Process -Id $pData.frontend_pid -Force -ErrorAction SilentlyContinue
            }
        } catch {}
        Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
    }

    # 2. Fast port listener termination (< 20ms)
    foreach ($port in @($ApiPort, $VitePort)) {
        try {
            $pids = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($p in $pids) {
                if ($p -and $p -ne 0 -and $p -ne $PID) {
                    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
                }
            }
        } catch {}
    }

    # 3. Always run quick_cleanup to safely purge orphaned Electron/node/uvicorn processes
    try {
        & (Join-Path $ScriptDir "quick_cleanup.ps1") | Out-Null
    } catch {}
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
            try {
                $prov = Invoke-RestMethod -Uri "http://${ApiHost}:${ApiPort}/api/system/code-provenance" -TimeoutSec 2 -ErrorAction SilentlyContinue
                if ($prov -and $prov.is_stale_in_memory) {
                    Write-Host " [!] STALE BYTECODE:     In-memory code lags disk! $($prov.stale_files_count) file(s) modified after boot." -ForegroundColor Yellow
                    Write-Host "     Action Needed:      Run .\scripts\service.ps1 -Action restart to reload fresh bytecode." -ForegroundColor Yellow
                } elseif ($prov) {
                    Write-Host "     Code Provenance:    FRESH (Commit: $($prov.git_commit), Uptime: $($prov.uptime_seconds)s)" -ForegroundColor DarkGray
                }
            } catch {}
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

# 0. Optional 90-day Fyers Historical Model Calibration
if ($Calibrate) {
    Write-Host "[*] Executing 90-day institutional Fyers model calibration..." -ForegroundColor Cyan
    & $PythonExe (Join-Path $ScriptDir "calibrate_fyers_historical_models.py")
    Write-Host " [+] Model calibration complete." -ForegroundColor Green
}

# 1. Smart Web static bundle sync: guarantees any UI source changes reflect
if (-not $NoFrontend -and -not $SkipBuildWeb -and (Test-Path "$FrontendDir\package.json")) {
    $staticIndex = Join-Path $RootDir "web\static\index.html"
    $needsBuild = $false
    $buildReason = ""

    if ($ForceBuildWeb) {
        $needsBuild = $true
        $buildReason = "Forced rebuild requested (-ForceBuildWeb)"
    } elseif (-not (Test-Path $staticIndex)) {
        $needsBuild = $true
        $buildReason = "web/static/index.html not found"
    } else {
        # Check if any UI source file is newer than the built static bundle
        $staticTime = (Get-Item $staticIndex).LastWriteTime
        $latestSrc = Get-ChildItem -Path "$FrontendDir\src" -Recurse -File -ErrorAction SilentlyContinue | 
            Sort-Object LastWriteTime -Descending | Select-Object -First 1

        if ($latestSrc -and $latestSrc.LastWriteTime -gt $staticTime) {
            $needsBuild = $true
            $buildReason = "UI source changed ($($latestSrc.Name) updated at $($latestSrc.LastWriteTime.ToString('HH:mm:ss')))"
        }
    }

    if ($needsBuild) {
        Write-Host "[*] UI change detected: $buildReason. Synchronizing web static bundle..." -ForegroundColor Cyan
        Push-Location $FrontendDir
        try {
            & cmd.exe /c "npm.cmd run build:web:fast" | Out-Null
            Write-Host " [+] Web bundle synchronized to web/static/" -ForegroundColor Green
        } catch {
            Write-Warning "Fast web build encountered warning. Continuing..."
        } finally {
            Pop-Location
        }
    } else {
        Write-Host " [+] Web static bundle is up-to-date (no UI source changes). Skipping rebuild." -ForegroundColor DarkGray
    }
}

# 2. Launch FastAPI backend completely detached from parent Job Object via WMI (ShowWindow = 0: no black terminal)
$backendOut = Join-Path $LogDir "backend.log"
$backendErr = Join-Path $LogDir "backend_err.log"

Write-Host "[*] Launching hidden background FastAPI Sidecar on http://${ApiHost}:${ApiPort} ..." -ForegroundColor Cyan
$startupClass = [wmiclass]"Win32_ProcessStartup"
$startupInfo = $startupClass.CreateInstance()
$startupInfo.ShowWindow = 0  # SW_HIDE (0): guarantees zero black console window

$processClass = [wmiclass]"Win32_Process"
$reloadFlag = if ($Reload) { "--reload" } else { "" }
$backendCmd = "cmd.exe /c `"`"$PythonExe`" -m uvicorn web.api:app --host $ApiHost --port $ApiPort $reloadFlag > `"$backendOut`" 2> `"$backendErr`"`""
$bRes = $processClass.Create($backendCmd, $RootDir, $startupInfo)
$backendPid = $bRes.ProcessId

# 3. Wait for FastAPI sidecar to bind port with fast 100ms polling BEFORE launching frontend
Write-Host "[*] Waiting for FastAPI Sidecar to initialize on http://${ApiHost}:${ApiPort} ..." -ForegroundColor Gray
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$backendReady = $false

while ($sw.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
    Start-Sleep -Milliseconds 100
    try {
        $conn = Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            $backendReady = $true
            $backendPid = $conn.OwningProcess
            break
        }
    } catch {}
}

if (-not $backendReady) {
    Write-Warning "Backend did not bind to port $ApiPort within $TimeoutSeconds seconds. Check $backendErr"
    exit 1
}

Write-Host " [+] FastAPI Sidecar is healthy and listening on http://${ApiHost}:${ApiPort} (PID: $backendPid)" -ForegroundColor Green

# Foreground user protection: set process priority to BelowNormal so Office/Browser/Calls stay 100% fluid
try {
    (Get-Process -Id $backendPid).PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal
    Write-Host " [+] Process priority calibrated to BelowNormal (Foreground office & browser protected)" -ForegroundColor DarkGray
} catch {}

# 4. Launch Frontend (if requested)
$frontendPid = $null
if (-not $NoFrontend -and (Test-Path $FrontendDir)) {
    $frontendOut = Join-Path $LogDir "frontend.log"
    $frontendErr = Join-Path $LogDir "frontend_err.log"

    Write-Host "[*] Launching hidden background Vite Dev Server on http://localhost:$VitePort ..." -ForegroundColor Cyan
    $frontendCmd = "cmd.exe /c `"npm.cmd run dev:renderer > `"$frontendOut`" 2> `"$frontendErr`"`""
    $fRes = $processClass.Create($frontendCmd, $FrontendDir, $startupInfo)
    $frontendPid = $fRes.ProcessId

    $frontendReady = $false
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        try {
            $fConn = Get-NetTCPConnection -LocalPort $VitePort -State Listen -ErrorAction SilentlyContinue
            if ($fConn) {
                $frontendReady = $true
                $frontendPid = $fConn.OwningProcess
                break
            }
        } catch {}
        Start-Sleep -Milliseconds 100
    }
    if ($frontendReady) {
        Write-Host " [+] Frontend Desktop & Vite are listening on http://localhost:$VitePort (PID: $frontendPid)" -ForegroundColor Green
    } else {
        Write-Host " [*] Frontend is initializing in background (check $LogDir\frontend.log)" -ForegroundColor Yellow
    }
}

# Save PID info
$pids = @{
    backend_pid = $backendPid
    frontend_pid = $frontendPid
    started_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
}
$pids | ConvertTo-Json | Set-Content -Path $PidFile -Force

Write-Host "`n[SUCCESS] ChanakyaTrade background services restarted in $([math]::Round($sw.Elapsed.TotalSeconds, 2))s!" -ForegroundColor Green
Write-Host "  • Logs: $LogDir\backend.log, $LogDir\frontend.log" -ForegroundColor DarkGray
Write-Host "  • Management: .\scripts\service.ps1 [status | stop | restart]" -ForegroundColor DarkGray

exit 0
