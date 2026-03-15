from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
VENDOR_PATH = ROOT_DIR / ".vendor" / "accessparse"
if VENDOR_PATH.exists():
    sys.path.insert(0, str(VENDOR_PATH))

from access_parser import AccessParser  # type: ignore


DEFAULT_WORKFLOW_TABLES = [
    "Czestotliwosc kandydujaca",
    "Dane_EMC",
    "DECYZJA",
    "Przeslo decyzji",
    "Wynik EMC-LR",
    "PROCES_AP28",
    "problem_kons",
    "PRZESLO",
    "Przeslo linii radiowej",
    "Przeslo-zakres-plan",
    "PLAN",
    "KANAL",
    "NADAJNIK",
    "maski",
    "ANTENA",
    "Antena_kons",
    "PASMO ANTENY",
    "CHARAKTERYSTYKA",
    "charakterystyka_kons",
    "PRODUCENT",
    "Producent_kons",
    "Nadajnik_kons",
    "Homologacja_kons",
    "ELEWACJA_HORYZONTU",
    "ZASIEG",
    "STACJA",
    "OBIEKT STACJI",
    "Adresy",
]


def sanitize_identifier(value: str) -> str:
    text = value.strip().lower()
    text = text.replace("#", "_id")
    text = text.replace("\\", "_")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = "col"
    if text[0].isdigit():
        text = f"c_{text}"
    return text


def infer_sqlite_type(values: list[Any]) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return "INTEGER"
        if isinstance(value, int):
            return "INTEGER"
        if isinstance(value, float):
            return "REAL"
        return "TEXT"
    return "TEXT"


def row_count(parsed: dict[str, list[Any]]) -> int:
    return len(next(iter(parsed.values()))) if parsed else 0


def iter_rows(parsed: dict[str, list[Any]]):
    columns = list(parsed.keys())
    total = row_count(parsed)
    for index in range(total):
        yield {column: parsed[column][index] for column in columns}


def ensure_metadata_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_table_metadata (
            source_db TEXT NOT NULL,
            source_table TEXT NOT NULL,
            target_table TEXT NOT NULL,
            source_column TEXT NOT NULL,
            target_column TEXT NOT NULL,
            sqlite_type TEXT NOT NULL,
            PRIMARY KEY (source_db, source_table, source_column)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_table_manifest (
            source_db TEXT NOT NULL,
            source_table TEXT NOT NULL,
            target_table TEXT NOT NULL,
            status TEXT NOT NULL,
            row_count INTEGER,
            primary_keys_json TEXT,
            columns_json TEXT,
            PRIMARY KEY (source_db, source_table)
        )
        """
    )
    conn.commit()


def export_table(
    conn: sqlite3.Connection,
    db_label: str,
    db: AccessParser,
    table_name: str,
) -> dict[str, Any]:
    access_table = db.get_table(table_name)
    target_table = f"{sanitize_identifier(db_label)}__{sanitize_identifier(table_name)}"
    if access_table is None:
        conn.execute(
            """
            INSERT OR REPLACE INTO source_table_manifest
            (source_db, source_table, target_table, status, row_count, primary_keys_json, columns_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (db_label, table_name, target_table, "missing", None, "[]", "[]"),
        )
        conn.commit()
        return {"source_db": db_label, "table": table_name, "target_table": target_table, "status": "missing"}

    parsed = access_table.parse()
    source_columns = list(parsed.keys())
    total_rows = row_count(parsed)

    mapped_columns: list[tuple[str, str, str]] = []
    used_names: set[str] = set()
    for source_column in source_columns:
        target_column = sanitize_identifier(source_column)
        suffix = 2
        while target_column in used_names:
            target_column = f"{target_column}_{suffix}"
            suffix += 1
        used_names.add(target_column)
        sample_values = parsed[source_column][: min(total_rows, 64)]
        mapped_columns.append((source_column, target_column, infer_sqlite_type(sample_values)))

    conn.execute(f'DROP TABLE IF EXISTS "{target_table}"')
    column_defs = ', '.join(f'"{target}" {kind}' for _, target, kind in mapped_columns)
    conn.execute(f'CREATE TABLE "{target_table}" ({column_defs})')

    insert_sql = (
        f'INSERT INTO "{target_table}" ('
        + ", ".join(f'"{target}"' for _, target, _ in mapped_columns)
        + ") VALUES ("
        + ", ".join("?" for _ in mapped_columns)
        + ")"
    )

    batch: list[tuple[Any, ...]] = []
    for row in iter_rows(parsed):
        batch.append(tuple(row[source] for source, _, _ in mapped_columns))
        if len(batch) >= 1000:
            conn.executemany(insert_sql, batch)
            batch.clear()
    if batch:
        conn.executemany(insert_sql, batch)

    conn.executemany(
        """
        INSERT OR REPLACE INTO source_table_metadata
        (source_db, source_table, target_table, source_column, target_column, sqlite_type)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (db_label, table_name, target_table, source, target, kind)
            for source, target, kind in mapped_columns
        ],
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO source_table_manifest
        (source_db, source_table, target_table, status, row_count, primary_keys_json, columns_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            db_label,
            table_name,
            target_table,
            "ok",
            total_rows,
            json.dumps(list(access_table.primary_keys), ensure_ascii=False),
            json.dumps(
                [
                    {"source": source, "target": target, "sqlite_type": kind}
                    for source, target, kind in mapped_columns
                ],
                ensure_ascii=False,
            ),
        ),
    )
    conn.commit()

    return {
        "source_db": db_label,
        "table": table_name,
        "target_table": target_table,
        "rows": total_rows,
        "status": "ok",
        "primary_keys": list(access_table.primary_keys),
        "columns": [
            {"source": source, "target": target, "sqlite_type": kind}
            for source, target, kind in mapped_columns
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Eksport workflow UKE z MDB do lokalnej SQLite z zachowaniem metadanych źródłowych."
    )
    parser.add_argument(
        "--mdb",
        nargs="+",
        default=["LR_Konsultacja_349.mdb", "db1.mdb", "db2.mdb"],
        help="Jedna lub więcej baz MDB do eksportu.",
    )
    parser.add_argument(
        "--sqlite",
        default="data/uke_workflow.sqlite",
        help="Docelowa baza SQLite.",
    )
    parser.add_argument(
        "--tables",
        nargs="*",
        default=DEFAULT_WORKFLOW_TABLES,
        help="Lista tabel do eksportu.",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).resolve()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, Any]] = []
    with sqlite3.connect(sqlite_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        ensure_metadata_tables(conn)

        for mdb_arg in args.mdb:
            db_path = Path(mdb_arg).resolve()
            db_label = db_path.stem
            db = AccessParser(str(db_path))
            db_manifest = {
                "source_db": str(db_path),
                "db_label": db_label,
                "tables": [],
            }
            for table_name in args.tables:
                db_manifest["tables"].append(export_table(conn, db_label, db, table_name))
            manifest.append(db_manifest)

    manifest_path = sqlite_path.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(
            {
                "sqlite_path": str(sqlite_path),
                "sources": manifest,
                "tables_requested": args.tables,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(manifest_path)


if __name__ == "__main__":
    main()
