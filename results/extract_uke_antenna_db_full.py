from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
VENDOR_PATH = ROOT_DIR / '.vendor' / 'accessparse'
if VENDOR_PATH.exists():
    sys.path.insert(0, str(VENDOR_PATH))

from access_parser import AccessParser  # type: ignore

TABLES = [
    'PRODUCENT',
    'ANTENA',
    'PASMO ANTENY',
    'CHARAKTERYSTYKA',
    'ELEMENT_CHARAKTERYSTYKI',
    'ZASTOSOWANA ANTENA',
    'ANTENA_SAT',
    'HOMOLOGACJA',
    'STACJA',
    'OBIEKT STACJI',
    'NADAJNIK',
    'PRZESLO',
    'Adresy',
]


def sanitize_identifier(value: str) -> str:
    text = value.strip().lower()
    text = text.replace('#', '_id')
    text = re.sub(r'[^a-z0-9]+', '_', text)
    text = re.sub(r'_+', '_', text).strip('_')
    if not text:
        text = 'col'
    if text[0].isdigit():
        text = f'c_{text}'
    return text


def infer_sqlite_type(values: list[Any]) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return 'INTEGER'
        if isinstance(value, int):
            return 'INTEGER'
        if isinstance(value, float):
            return 'REAL'
        return 'TEXT'
    return 'TEXT'


def row_count(parsed: dict[str, list[Any]]) -> int:
    return len(next(iter(parsed.values()))) if parsed else 0


def iter_rows(parsed: dict[str, list[Any]]):
    columns = list(parsed.keys())
    total = row_count(parsed)
    for index in range(total):
        yield {column: parsed[column][index] for column in columns}


def export_table(conn: sqlite3.Connection, db: AccessParser, table_name: str) -> dict[str, Any]:
    access_table = db.get_table(table_name)
    if access_table is None:
        return {'table': table_name, 'status': 'missing'}

    parsed = access_table.parse()
    source_columns = list(parsed.keys())
    total_rows = row_count(parsed)
    target_table = sanitize_identifier(table_name)

    mapped_columns: list[tuple[str, str, str]] = []
    used_names: set[str] = set()
    for source_column in source_columns:
        target_column = sanitize_identifier(source_column)
        suffix = 2
        while target_column in used_names:
            target_column = f'{target_column}_{suffix}'
            suffix += 1
        used_names.add(target_column)
        sample_values = parsed[source_column][: min(total_rows, 64)]
        mapped_columns.append((source_column, target_column, infer_sqlite_type(sample_values)))

    conn.execute(f'DROP TABLE IF EXISTS "{target_table}"')
    column_defs = ', '.join(f'"{target}" {kind}' for _, target, kind in mapped_columns)
    conn.execute(f'CREATE TABLE "{target_table}" ({column_defs})')

    insert_sql = (
        f'INSERT INTO "{target_table}" ('
        + ', '.join(f'"{target}"' for _, target, _ in mapped_columns)
        + ') VALUES ('
        + ', '.join('?' for _ in mapped_columns)
        + ')'
    )

    batch: list[tuple[Any, ...]] = []
    for row in iter_rows(parsed):
        batch.append(tuple(row[source] for source, _, _ in mapped_columns))
        if len(batch) >= 1000:
            conn.executemany(insert_sql, batch)
            batch.clear()
    if batch:
        conn.executemany(insert_sql, batch)

    metadata_table = 'source_table_metadata'
    conn.execute(
        f'''
        CREATE TABLE IF NOT EXISTS {metadata_table} (
            source_table TEXT NOT NULL,
            target_table TEXT NOT NULL,
            source_column TEXT NOT NULL,
            target_column TEXT NOT NULL,
            sqlite_type TEXT NOT NULL,
            PRIMARY KEY (source_table, source_column)
        )
        '''
    )
    conn.executemany(
        f'''
        INSERT OR REPLACE INTO {metadata_table}
        (source_table, target_table, source_column, target_column, sqlite_type)
        VALUES (?, ?, ?, ?, ?)
        ''',
        [
            (table_name, target_table, source, target, kind)
            for source, target, kind in mapped_columns
        ],
    )
    conn.commit()

    return {
        'table': table_name,
        'target_table': target_table,
        'rows': total_rows,
        'columns': [
            {
                'source': source,
                'target': target,
                'sqlite_type': kind,
            }
            for source, target, kind in mapped_columns
        ],
        'primary_keys': list(access_table.primary_keys),
        'status': 'ok',
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Mirror full UKE antenna-related MDB tables into local SQLite.')
    parser.add_argument('--mdb', default='LR_Konsultacja_349.mdb')
    parser.add_argument('--sqlite', default='data/uke_antennas_full.sqlite')
    parser.add_argument('--tables', nargs='*', default=TABLES)
    args = parser.parse_args()

    db_path = Path(args.mdb).resolve()
    sqlite_path = Path(args.sqlite).resolve()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    db = AccessParser(str(db_path))
    with sqlite3.connect(sqlite_path) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        manifest = []
        for table_name in args.tables:
            manifest.append(export_table(conn, db, table_name))
        manifest_path = sqlite_path.with_suffix('.manifest.json')
        manifest_path.write_text(json.dumps({
            'source_mdb': str(db_path),
            'sqlite_path': str(sqlite_path),
            'tables': manifest,
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        print(manifest_path)


if __name__ == '__main__':
    main()
