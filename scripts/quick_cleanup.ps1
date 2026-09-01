# quick_cleanup.ps1 - Automated Cleanup & Recovery for Antigravity IDE & AI Agents
# Safely purges orphaned background processes, stale socket locks, and temp caches.

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "   Antigravity IDE & AI Agent Quick Environment Cleanup" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan

# 1. Terminate orphaned headless Python/pytest/uvicorn worker processes
$currentPid = $PID
$killedCount = 0

try {
    $zombieProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | 
        Where-Object { 
            $_.ProcessId -ne $currentPid -and 
            ($_.Name -match "python|pytest|uvicorn") -and
            ($_.CommandLine -match "chanakya-trade" -or $_.CommandLine -match "pytest" -or $_.CommandLine -match "uvicorn" -or $_.CommandLine -match "validate_all" -or $_.CommandLine -match "exec\(eval")
        }

    foreach ($proc in $zombieProcs) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host " [+] Terminated orphaned background process: $($proc.Name) (PID $($proc.ProcessId))" -ForegroundColor Yellow
            $killedCount++
        } catch {
            # Silently ignore protected processes
        }
    }
} catch {
    # Fallback to Get-Process if CIM unavailable
}

if ($killedCount -eq 0) {
    Write-Host " [v] No orphaned Python/pytest/uvicorn processes found." -ForegroundColor Green
} else {
    Write-Host " [v] Successfully purged $killedCount orphaned worker process(es)." -ForegroundColor Green
}

# 2. Release stale local socket bindings & locks on port 8765 if stuck
try {
    $portProcs = Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($p in $portProcs) {
        if ($p -and $p -ne 0) {
            Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
            Write-Host " [+] Released stuck port 8765 listener (PID $p)" -ForegroundColor Yellow
        }
    }
} catch {
    # Non-admin or no active listener
}

# 3. Clean temporary pytest and analysis caches
$cachePaths = @(
    "$PSScriptRoot\..\.pytest_cache",
    "$PSScriptRoot\..\.pytest_trading_platform"
)

foreach ($path in $cachePaths) {
    if (Test-Path $path) {
        try {
            Remove-Item -Path $path -Recurse -Force -ErrorAction SilentlyContinue
            Write-Host " [+] Cleaned cache directory: $(Split-Path $path -Leaf)" -ForegroundColor DarkGray
        } catch {
            # In-use files will skip gracefully
        }
    }
}

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host " [v] Environment cleanup complete!" -ForegroundColor Green
Write-Host " Tip: Press [Ctrl+Alt+R] (or Ctrl+Shift+P -> 'Developer: Restart Extension Host') to reset AI chat connection." -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
