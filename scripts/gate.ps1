<#
.SYNOPSIS
    Institutional Shift-Left Quality & Safety Gate runner for Windows.
.DESCRIPTION
    Runs scripts/shift_left_check.py using the verified Python environment (.venv or py -3.12).
#>
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir

$PyExe = if (Test-Path "$RootDir\.venv\Scripts\python.exe") {
    "$RootDir\.venv\Scripts\python.exe"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    "py"
} else {
    "python"
}

if ($PyExe -eq "py") {
    & py -3.12 "$ScriptDir\shift_left_check.py" @args
} else {
    & $PyExe "$ScriptDir\shift_left_check.py" @args
}
exit $LASTEXITCODE
