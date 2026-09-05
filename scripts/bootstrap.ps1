# ChanakyaTrade — self-healing Python environment bootstrap (Windows)
#
# This script deliberately does not assume that .venv is healthy. Python
# virtual environments embed the absolute path of the interpreter that created
# them; after a Python upgrade/uninstall that path can point at a file that no
# longer exists. Run this script before tests or local development.
#
# Usage:
#   .\scripts\bootstrap.ps1                 # create/repair .venv + install dev deps
#   .\scripts\bootstrap.ps1 -CheckOnly      # diagnose without changing anything
#   .\scripts\bootstrap.ps1 -PythonExe C:\Python312\python.exe

[CmdletBinding()]
param(
    [string]$PythonExe,
    [switch]$CheckOnly,
    [switch]$Force,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$VenvDir = Join-Path $RootDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$MinimumMajor = 3
$MinimumMinor = 11

function Write-Step([string]$Message) {
    Write-Host "[*] $Message" -ForegroundColor Cyan
}

function Test-PythonExecutable([string]$Candidate) {
    if ([string]::IsNullOrWhiteSpace($Candidate) -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
        return $false
    }
    try {
        $raw = & $Candidate -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }
        $parts = ($raw | Select-Object -First 1).Trim().Split('.')
        return ($parts.Count -ge 2 -and [int]$parts[0] -eq $MinimumMajor -and [int]$parts[1] -ge $MinimumMinor)
    } catch {
        return $false
    }
}

function Resolve-Python {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($PythonExe) { $candidates.Add($PythonExe) }
    if ($env:CHANAKYA_PYTHON) { $candidates.Add($env:CHANAKYA_PYTHON) }

    # Never reuse a broken project venv as the source interpreter.
    $commands = @("python.exe", "python3.exe")
    foreach ($name in $commands) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates.Add($cmd.Source) }
    }

    # The Windows launcher is common even when `python` is not on PATH.
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $resolved = & $launcher.Source -3 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved) { $candidates.Add(($resolved | Select-Object -First 1).Trim()) }
        } catch { }
    }

    # Conventional per-user and machine installation locations.
    foreach ($base in @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $base) { continue }
        foreach ($version in @("Python313", "Python312", "Python311")) {
            $candidates.Add((Join-Path $base "Programs\Python\$version\python.exe"))
            $candidates.Add((Join-Path $base "Python\$version\python.exe"))
        }
    }

    # Development hosts such as Codex may expose a managed Python runtime
    # outside PATH. Treat it as a last-resort source only; normal installations
    # should use CHANAKYA_PYTHON or a system Python installation.
    $managedRoot = Join-Path $env:USERPROFILE ".cache\codex-runtimes"
    if (Test-Path -LiteralPath $managedRoot) {
        Get-ChildItem -LiteralPath $managedRoot -Filter "python.exe" -File -Recurse -ErrorAction SilentlyContinue |
            ForEach-Object { $candidates.Add($_.FullName) }
    }

    # De-duplicate while preserving priority and return the first usable one.
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-PythonExecutable $candidate) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    return $null
}

function Invoke-Python([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed ($LASTEXITCODE): $Executable $($Arguments -join ' ')"
    }
}

function Test-Venv([switch]$RequireDevTools) {
    if (-not (Test-PythonExecutable $VenvPython)) { return $false }
    try {
        & $VenvPython -c "import sys; import pip; print(sys.executable)" 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { return $false }
        if ($RequireDevTools) {
            & $VenvPython -c "import pytest, pytest_mock, xdist, ruff; import brokers, engine" 2>$null
            if ($LASTEXITCODE -ne 0) { return $false }
        }
        return $true
    } catch { return $false }
}

Write-Host "ChanakyaTrade Python environment" -ForegroundColor Yellow
Write-Host "Repository: $RootDir"

$sourcePython = Resolve-Python
$venvHealthy = Test-Venv -RequireDevTools:(-not $SkipInstall)

if (-not $Force -and -not $CheckOnly -and $venvHealthy -and -not $SkipInstall) {
    Write-Host "[PASS] Environment already ready: $VenvPython" -ForegroundColor Green
    exit 0
}

if ($CheckOnly) {
    if ($venvHealthy) {
        Write-Host "[PASS] .venv is healthy and development tools are installed." -ForegroundColor Green
        exit 0
    }
    if (-not $sourcePython) {
        Write-Host "[FAIL] No usable Python $MinimumMajor.$MinimumMinor+ interpreter was found." -ForegroundColor Red
        Write-Host "       Install Python from https://www.python.org/downloads/windows/ or set CHANAKYA_PYTHON."
        exit 2
    }
    Write-Host "[WARN] .venv is missing, stale, or incomplete; a bootstrap is required." -ForegroundColor Yellow
    Write-Host "       Usable source interpreter: $sourcePython"
    exit 1
}

if (-not $sourcePython) {
    Write-Host "[FAIL] No usable Python $MinimumMajor.$MinimumMinor+ interpreter was found." -ForegroundColor Red
    Write-Host "       Install Python from https://www.python.org/downloads/windows/ or set CHANAKYA_PYTHON."
    exit 2
}

if ($Force -or -not (Test-Venv)) {
    if (Test-Path -LiteralPath $VenvDir) {
        # Preserve the broken environment for diagnosis instead of deleting it.
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $quarantine = Join-Path $RootDir ".venv.broken-$stamp"
        Write-Step "Quarantining stale .venv as $(Split-Path -Leaf $quarantine)"
        Move-Item -LiteralPath $VenvDir -Destination $quarantine
    }
    Write-Step "Creating a fresh .venv with $sourcePython"
    Invoke-Python $sourcePython @("-m", "venv", $VenvDir)
}

if (-not (Test-Venv)) {
    throw "The newly created .venv could not run. Check the selected Python installation."
}

if (-not $SkipInstall) {
    Write-Step "Installing/updating project and development dependencies"
    # Some modern Python distributions create venvs without setuptools, but
    # pip/ensurepip remains sufficient for an editable install.
    Invoke-Python $VenvPython @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Python $VenvPython @("-m", "pip", "install", "-e", ".[dev]")
}

if (-not $SkipInstall -and -not (Test-Venv -RequireDevTools)) {
    throw "Development dependencies are incomplete. Run this script again or inspect pip output."
}

Write-Host "[PASS] Environment ready: $VenvPython" -ForegroundColor Green
