# Self-healing test entrypoint for Windows.
# Examples:
#   .\scripts\test.ps1
#   .\scripts\test.ps1 -TestPath tests/test_broker_shoonya.py
#   .\scripts\test.ps1 -All -PytestArgs @('-n', '4')
[CmdletBinding()]
param(
    [switch]$All,
    [switch]$Network,
    [switch]$Slow,
    [string[]]$TestPath = @("tests"),
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir

& (Join-Path $ScriptDir "bootstrap.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$args = @(
    "-m", "pytest"
)
$args += $TestPath
$args += @(
    "-v", "--tb=short",
    "--basetemp", (Join-Path $RootDir ".pytest_trading_platform\pytest-tmp"),
    "-p", "no:cacheprovider"
)
if (-not $All -and -not $Network) { $args += @("-m", "not network and not slow") }
elseif (-not $Network) { $args += @("-m", "not network") }
if ($Slow) { $args += @("-m", "slow and not network") }
if ($PytestArgs) { $args += $PytestArgs }

Push-Location $RootDir
try {
    & (Join-Path $RootDir ".venv\Scripts\python.exe") @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
