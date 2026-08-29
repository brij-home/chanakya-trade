#!/usr/bin/env bash
# ==============================================================================
# ChanakyaTrade — Local Greenfield Development Bootstrap (macOS / Linux POSIX)
# ==============================================================================
# Usage:
#   ./scripts/dev.sh
#   ./scripts/dev.sh --no-frontend
#   ./scripts/dev.sh --port 8765
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

NO_FRONTEND=0
API_PORT=8765
VITE_PORT=5173
SKIP_PREFLIGHT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-frontend)
      NO_FRONTEND=1
      shift
      ;;
    --port)
      API_PORT="$2"
      shift 2
      ;;
    --skip-preflight)
      SKIP_PREFLIGHT=1
      shift
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo ""
echo -e "\033[1;36m==================================================================\033[0m"
echo -e "\033[1;33m   ChanakyaTrade — AI-Powered Institutional Quant Terminal\033[0m"
echo -e "\033[1;36m   Local-First Greenfield Bootstrap (POSIX Environment)\033[0m"
echo -e "\033[1;36m==================================================================\033[0m"
echo ""

# 1. Resolve Python
PYTHON_EXE=""
if [[ -f "${ROOT_DIR}/.venv/bin/python" ]]; then
    PYTHON_EXE="${ROOT_DIR}/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON_EXE="$(command -v python3)"
elif command -v python &>/dev/null; then
    PYTHON_EXE="$(command -v python)"
else
    echo -e "\033[1;31m[-] Python 3.11+ is required but not found.\033[0m"
    exit 1
fi

echo -e "\033[1;32m[+] Python Executable: ${PYTHON_EXE}\033[0m"

# 2. Preflight Check
if [[ ${SKIP_PREFLIGHT} -eq 0 ]]; then
    echo -e "\033[0;37m[*] Running system preflight checks...\033[0m"
    "${PYTHON_EXE}" -m scripts.preflight || true
fi

# 3. Ensure Frontend Dependencies
FRONTEND_DIR="${ROOT_DIR}/macos-app"
if [[ ${NO_FRONTEND} -eq 0 && -d "${FRONTEND_DIR}" ]]; then
    if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
        echo -e "\033[1;33m[*] Installing frontend dependencies in macos-app...\033[0m"
        (cd "${FRONTEND_DIR}" && npm install)
    fi
fi

# 4. Graceful Cleanup Trap
cleanup() {
    echo ""
    echo -e "\033[1;33m[*] Stopping development services...\033[0m"
    if [[ -n "${BACKEND_PID}" ]]; then
        kill "${BACKEND_PID}" 2>/dev/null || true
    fi
    if [[ -n "${FRONTEND_PID}" ]]; then
        kill "${FRONTEND_PID}" 2>/dev/null || true
    fi
    echo -e "\033[1;32m[+] All services cleanly stopped.\033[0m"
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# 5. Start Services
echo ""
echo -e "\033[1;36m[*] Launching FastAPI Sidecar on http://127.0.0.1:${API_PORT} ...\033[0m"
(cd "${ROOT_DIR}" && "${PYTHON_EXE}" -m uvicorn web.api:app --host 127.0.0.1 --port "${API_PORT}" --reload) &
BACKEND_PID=$!

if [[ ${NO_FRONTEND} -eq 0 && -d "${FRONTEND_DIR}" ]]; then
    echo -e "\033[1;36m[*] Launching Vite Frontend on http://127.0.0.1:${VITE_PORT} ...\033[0m"
    sleep 1
    (cd "${FRONTEND_DIR}" && npm run dev) &
    FRONTEND_PID=$!
fi

echo ""
echo -e "\033[1;35mPress Ctrl+C to terminate all services.\033[0m"
echo ""

wait "${BACKEND_PID}"
