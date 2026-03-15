#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8012}"

if [[ "${PORT}" =~ ^[0-9]+$ ]] && (( PORT < 1024 )); then
  echo "Port ${PORT} jest uprzywilejowany. Ustaw PORT>=1024, np. PORT=8012."
  exit 1
fi

PYTHON_CANDIDATES=()
if [[ -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
  PYTHON_CANDIDATES+=("${PROJECT_DIR}/.venv/bin/python")
fi
PYTHON_CANDIDATES+=("python3")

PYTHON_BIN=""
for candidate in "${PYTHON_CANDIDATES[@]}"; do
  if "${candidate}" -c "import uvicorn" >/dev/null 2>&1; then
    PYTHON_BIN="${candidate}"
    break
  fi
done

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "Nie znaleziono interpretera Python z zainstalowanym modułem uvicorn."
  exit 1
fi

if lsof -tiTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  PID="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN | head -n 1)"
  CMD="$(ps -p "${PID}" -o args= 2>/dev/null || true)"
  echo "Port ${PORT} jest już zajęty przez PID ${PID}."
  if [[ -n "${CMD}" ]]; then
    echo "Proces: ${CMD}"
  fi
  echo "Zatrzymaj istniejący proces albo uruchom skrypt z innym portem, np. PORT=8013 ./run.sh"
  exit 1
fi

cd "${PROJECT_DIR}"

echo "Uruchamianie FastAPI na http://${HOST}:${PORT} z --reload"
exec "${PYTHON_BIN}" -m uvicorn app:app --host "${HOST}" --port "${PORT}" --reload
