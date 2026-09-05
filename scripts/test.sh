#!/usr/bin/env bash
# Self-healing test entrypoint for macOS/Linux.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
bash "${SCRIPT_DIR}/bootstrap.sh"
cd "$ROOT_DIR"

args=( -m pytest tests -v --tb=short --basetemp "${ROOT_DIR}/.pytest_trading_platform/pytest-tmp" -p no:cacheprovider )
case "${1:-}" in
  --all) shift ;;
  --network) args+=( -m network ); shift ;;
  --slow) args+=( -m 'slow and not network' ); shift ;;
  *) args+=( -m 'not network and not slow' ) ;;
esac
exec "${ROOT_DIR}/.venv/bin/python" "${args[@]}" "$@"
