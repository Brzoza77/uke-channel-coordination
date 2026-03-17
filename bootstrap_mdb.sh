#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "${ROOT_DIR}/requirements.txt"
python -m pip install -r "${ROOT_DIR}/requirements-mdb.txt"

if ! command -v unar >/dev/null 2>&1 && \
   ! command -v 7z >/dev/null 2>&1 && \
   ! command -v unrar >/dev/null 2>&1 && \
   ! command -v bsdtar >/dev/null 2>&1; then
  echo
  echo "Uwaga: nie znaleziono ekstraktora RAR."
  echo "Do ./refresh_uke_sqlite.sh potrzebne jest jedno z narzędzi: unar, 7z, unrar albo bsdtar."
  echo "Ubuntu/Debian: sudo apt install unar"
  echo "Alternatywnie: sudo apt install p7zip-full"
fi

echo "Application + MDB environment is ready."
echo "Activate with: source ${VENV_DIR}/bin/activate"
