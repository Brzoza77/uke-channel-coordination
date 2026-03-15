#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

SQLITE_PATH="${1:-data/uke_workflow.sqlite}"

python3 results/extract_uke_workflow_sqlite.py \
  --mdb LR_Konsultacja_349.mdb db1.mdb db2.mdb \
  --sqlite "$SQLITE_PATH"

python3 results/analyze_uke_workflow_sqlite.py \
  --sqlite "$SQLITE_PATH" \
  --source-db LR_Konsultacja_349 \
  --out logs/uke_workflow_sqlite_summary.json

python3 results/build_uke_workflow_graph.py \
  --sqlite "$SQLITE_PATH" \
  --source-db LR_Konsultacja_349 \
  --out-json logs/uke_workflow_graph.json \
  --out-dot logs/uke_workflow_graph.dot

echo "Odświeżono SQLite i artefakty workflow: $SQLITE_PATH"
