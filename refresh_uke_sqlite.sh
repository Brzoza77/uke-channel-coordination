#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

SQLITE_PATH="${1:-data/uke_workflow.sqlite}"
ANTENNA_SQLITE_PATH="${UKE_ANTENNA_SQLITE_PATH:-data/antenna_catalog.sqlite}"
AUTO_UPDATE="${UKE_AUTO_UPDATE:-1}"
SOURCE_ROOT="${UKE_SOURCE_ROOT:-data/uke_source}"
STATE_FILE="${UKE_STATE_FILE:-$SOURCE_ROOT/state.json}"
UPDATE_LOG="${UKE_UPDATE_LOG:-logs/uke_publication_update.json}"
DOWNLOAD_PLANY="${UKE_DOWNLOAD_PLANY:-0}"

MDB_ARGS=("LR_Konsultacja_349.mdb" "db1.mdb" "db2.mdb")

if [[ "$AUTO_UPDATE" == "1" ]]; then
  UPDATE_ARGS=()
  if [[ "$DOWNLOAD_PLANY" != "1" ]]; then
    UPDATE_ARGS+=("--skip-plany")
  fi
  python3 results/update_uke_publication.py \
    --state-file "$STATE_FILE" \
    --download-dir "$SOURCE_ROOT/downloads" \
    --extract-dir "$SOURCE_ROOT/extracted" \
    "${UPDATE_ARGS[@]}" \
    --out "$UPDATE_LOG"

  mapfile -t INTERNAL_MDB_ARGS < <(
    python3 - <<'PY' "$UPDATE_LOG"
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    raise SystemExit(0)
payload = json.loads(path.read_text(encoding="utf-8"))
mdb = payload.get("mdb_files") or {}
for key in ("lr_konsultacja", "db1", "db2"):
    value = mdb.get(key)
    if value:
        print(value)
PY
  )
  if [[ "${#INTERNAL_MDB_ARGS[@]}" -eq 3 ]]; then
    MDB_ARGS=("${INTERNAL_MDB_ARGS[@]}")
  fi
fi

python3 results/extract_uke_workflow_sqlite.py \
  --mdb "${MDB_ARGS[@]}" \
  --sqlite "$SQLITE_PATH"

rm -f "${ANTENNA_SQLITE_PATH}" "${ANTENNA_SQLITE_PATH}-wal" "${ANTENNA_SQLITE_PATH}-shm"
python3 results/extract_uke_antennas_sqlite.py \
  --mdb "${MDB_ARGS[0]}" \
  --sqlite "$ANTENNA_SQLITE_PATH"

python3 results/analyze_uke_workflow_sqlite.py \
  --sqlite "$SQLITE_PATH" \
  --source-db LR_Konsultacja_349 \
  --out logs/uke_workflow_sqlite_summary.json

python3 results/build_uke_workflow_graph.py \
  --sqlite "$SQLITE_PATH" \
  --source-db LR_Konsultacja_349 \
  --out-json logs/uke_workflow_graph.json \
  --out-dot logs/uke_workflow_graph.dot

echo "Odświeżono SQLite i artefakty workflow:"
echo " - katalog UKE: $SQLITE_PATH"
echo " - katalog anten: $ANTENNA_SQLITE_PATH"
printf 'MDB source files:\n'
printf ' - %s\n' "${MDB_ARGS[@]}"
