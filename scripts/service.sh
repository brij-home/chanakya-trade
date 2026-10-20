#!/usr/bin/env bash
# ==============================================================================
# ChanakyaTrade — Universal Service Manager (macOS / Linux POSIX Wrapper)
# Delegates to scripts/service.py for cross-platform parity
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Resolve Python in virtual environment or system
PYTHON_EXE="${ROOT_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_EXE}" ]]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_EXE="python3"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_EXE="python"
    else
        echo "[!] Python 3 not found in PATH or .venv" >&2
        exit 1
    fi
fi

exec "${PYTHON_EXE}" "${SCRIPT_DIR}/service.py" "$@"
