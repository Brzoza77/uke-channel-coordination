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

# Szuka lokalnie wgranego archiwum RAR lub pliku MDB w katalogu głównym.
# Zwraca przez stdout ścieżki do trzech plików MDB (lr_konsultacja db1 db2),
# po jednym na linię, lub nic jeśli nie znaleziono.
_find_local_mdb_args() {
  # Szukaj pliku RAR z lr_konsultacja w nazwie (case-insensitive)
  local newest_rar=""
  while IFS= read -r f; do
    [[ -z "$newest_rar" ]] && newest_rar="$f"
    # sort -V zapewnia porządek wersji; bierzemy ostatni (najnowszy)
    newest_rar="$f"
  done < <(find "$ROOT_DIR" -maxdepth 1 -iname "lr_konsultacja*.rar" -o -maxdepth 1 -iname "lr_konsultacja*.RAR" 2>/dev/null | sort -V)

  if [[ -n "$newest_rar" ]]; then
    local stem
    stem="$(basename "${newest_rar%.*}")"
    local extract_dir="$SOURCE_ROOT/extracted/$stem"
    echo "Znaleziono lokalne archiwum RAR: $newest_rar" >&2
    echo "Rozpakowuję do: $extract_dir" >&2
    mkdir -p "$extract_dir"
    # Wybór narzędzia do rozpakowania RAR
    if command -v unar &>/dev/null; then
      unar -force-overwrite -output-directory "$extract_dir" "$newest_rar" >&2
    elif command -v 7z &>/dev/null; then
      7z x -y "-o$extract_dir" "$newest_rar" >&2
    elif command -v unrar &>/dev/null; then
      unrar x -o+ "$newest_rar" "$extract_dir" >&2
    elif command -v bsdtar &>/dev/null; then
      bsdtar -xf "$newest_rar" -C "$extract_dir" >&2
    else
      echo "Błąd: brak narzędzia do rozpakowania RAR (zainstaluj unar, 7z, unrar lub bsdtar)." >&2
      return 1
    fi
    # Szukaj plików MDB wewnątrz rozpakowanego archiwum
    python3 - <<'PY' "$extract_dir"
import sys
from pathlib import Path

d = Path(sys.argv[1])
files = sorted(d.rglob("*.mdb"))
result = {}
for p in files:
    n = p.name.lower()
    if n.startswith("lr_konsultacja") and "lr_konsultacja" not in result:
        result["lr_konsultacja"] = str(p.resolve())
    elif n == "db1.mdb" and "db1" not in result:
        result["db1"] = str(p.resolve())
    elif n == "db2.mdb" and "db2" not in result:
        result["db2"] = str(p.resolve())
for key in ("lr_konsultacja", "db1", "db2"):
    if key in result:
        print(result[key])
PY
    return
  fi

  # Brak RAR — szukaj pliku LR_Konsultacja_*.mdb bezpośrednio w katalogu głównym
  local newest_mdb=""
  while IFS= read -r f; do
    newest_mdb="$f"
  done < <(find "$ROOT_DIR" -maxdepth 1 -iname "lr_konsultacja_*.mdb" 2>/dev/null | sort -V)

  if [[ -n "$newest_mdb" ]]; then
    local db1="$ROOT_DIR/db1.mdb"
    local db2="$ROOT_DIR/db2.mdb"
    if [[ -f "$db1" && -f "$db2" ]]; then
      echo "Znaleziono lokalny plik MDB: $newest_mdb" >&2
      echo "$newest_mdb"
      echo "$db1"
      echo "$db2"
    else
      echo "Znaleziono $newest_mdb, ale brakuje db1.mdb lub db2.mdb w katalogu głównym." >&2
    fi
  fi
}

if [[ "$AUTO_UPDATE" == "1" ]]; then
  UPDATE_ARGS=()
  if [[ "$DOWNLOAD_PLANY" != "1" ]]; then
    UPDATE_ARGS+=("--skip-plany")
  fi

  set +e
  python3 results/update_uke_publication.py \
    --state-file "$STATE_FILE" \
    --download-dir "$SOURCE_ROOT/downloads" \
    --extract-dir "$SOURCE_ROOT/extracted" \
    "${UPDATE_ARGS[@]}" \
    --out "$UPDATE_LOG"
  _update_exit=$?
  set -e

  if [[ "$_update_exit" -ne 0 ]]; then
    echo "Ostrzeżenie: pobieranie ze strony UKE nie powiodło się (kod: $_update_exit)." >&2
    echo "Sprawdzam czy użytkownik wgrał nową wersję do katalogu głównego..." >&2
    mapfile -t LOCAL_MDB_ARGS < <(_find_local_mdb_args)
    if [[ "${#LOCAL_MDB_ARGS[@]}" -eq 3 ]]; then
      MDB_ARGS=("${LOCAL_MDB_ARGS[@]}")
      echo "Używam lokalnie wgranych plików MDB." >&2
    else
      echo "Nie znaleziono lokalnie wgranych plików. Używam domyślnych plików MDB." >&2
    fi
  else
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
