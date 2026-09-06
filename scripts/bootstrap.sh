#!/usr/bin/env bash
# ChanakyaTrade — self-healing Python environment bootstrap (macOS/Linux).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
CHECK_ONLY=0
FORCE=0
SKIP_INSTALL=0
SOURCE_OVERRIDE="${CHANAKYA_PYTHON:-}"

usage() {
  cat <<'EOF'
Usage: ./scripts/bootstrap.sh [--check-only] [--force] [--skip-install] [--python PATH]

Creates or repairs .venv and installs the project's development dependencies.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check-only) CHECK_ONLY=1; shift ;;
    --force) FORCE=1; shift ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    --python) SOURCE_OVERRIDE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

is_usable() {
  [[ -x "$1" ]] && "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

SOURCE_PYTHON=""
for candidate in "$SOURCE_OVERRIDE" "$(command -v python3 2>/dev/null || true)" "$(command -v python 2>/dev/null || true)"; do
  if [[ -n "$candidate" ]] && is_usable "$candidate"; then SOURCE_PYTHON="$candidate"; break; fi
done

if [[ -z "$SOURCE_PYTHON" ]]; then
  echo "[FAIL] Python 3.11+ was not found. Install it or set CHANAKYA_PYTHON." >&2
  exit 2
fi

venv_healthy() {
  is_usable "$VENV_PYTHON" || return 1
  "$VENV_PYTHON" -c 'import pip' >/dev/null 2>&1 || return 1
  if [[ "$SKIP_INSTALL" -eq 0 ]]; then
    "$VENV_PYTHON" -c 'import pytest, pytest_mock, xdist, ruff, brokers, engine' >/dev/null 2>&1 || return 1
  fi
}

if [[ "$FORCE" -eq 0 ]] && venv_healthy; then
  echo "[PASS] .venv is healthy: ${VENV_PYTHON}"
  [[ "$CHECK_ONLY" -eq 1 ]] && exit 0
elif [[ "$CHECK_ONLY" -eq 1 ]]; then
  echo "[WARN] .venv is missing, stale, or incomplete; run this script without --check-only."
  exit 1
fi

if [[ -e "$VENV_DIR" ]]; then
  quarantine="${ROOT_DIR}/.venv.broken-$(date +%Y%m%d-%H%M%S)"
  echo "[*] Quarantining stale .venv as $(basename "$quarantine")"
  mv "$VENV_DIR" "$quarantine"
fi

echo "[*] Creating .venv with ${SOURCE_PYTHON}"
"$SOURCE_PYTHON" -m venv "$VENV_DIR"
if [[ "$SKIP_INSTALL" -eq 0 ]]; then
  echo "[*] Installing/updating project and development dependencies"
  "$VENV_PYTHON" -m pip install --upgrade pip
  "$VENV_PYTHON" -m pip install -e '.[dev]'
fi

if ! venv_healthy; then
  echo "[FAIL] Development dependencies are incomplete; inspect pip output and retry." >&2
  exit 1
fi
echo "[PASS] Environment ready: ${VENV_PYTHON}"
