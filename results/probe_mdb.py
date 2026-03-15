from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path
from typing import Any

VENDOR_PATH = Path(__file__).resolve().parents[1] / '.vendor' / 'accessparse'
if VENDOR_PATH.exists():
    sys.path.insert(0, str(VENDOR_PATH))

from access_parser import AccessParser  # type: ignore


def _timeout_handler(signum: int, frame: Any) -> None:
    raise TimeoutError('Przekroczono limit czasu sondowania MDB')


def probe_catalog(db_path: Path) -> dict[str, Any]:
    db = AccessParser(str(db_path))
    return {
        'db_path': str(db_path),
        'tables': db.catalog,
    }


def probe_table_columns(db_path: Path, table_name: str) -> dict[str, Any]:
    db = AccessParser(str(db_path))
    table = db.get_table(table_name)
    if table is None:
        raise ValueError(f'Nie znaleziono tabeli: {table_name}')
    columns = [col.col_name_str for _, col in sorted(table.columns.items())]
    return {
        'db_path': str(db_path),
        'table': table_name,
        'primary_keys': table.primary_keys,
        'columns': columns,
    }


def probe_table_rows(
    db_path: Path,
    table_name: str,
    limit: int,
    needle: str | None,
    where_column: str | None,
    where_value: str | None,
) -> dict[str, Any]:
    db = AccessParser(str(db_path))
    table = db.get_table(table_name)
    if table is None:
        raise ValueError(f'Nie znaleziono tabeli: {table_name}')
    parsed = table.parse()
    columns = list(parsed.keys())
    row_count = len(next(iter(parsed.values()))) if parsed else 0
    sample: list[dict[str, Any]] = []
    for i in range(row_count):
        row = {col: parsed[col][i] for col in columns}
        if where_column is not None:
            cell = row.get(where_column)
            if where_value is None:
                if cell is not None:
                    continue
            elif str(cell) != where_value:
                continue
        if needle:
            haystack = ' | '.join('' if row[col] is None else str(row[col]) for col in columns)
            if needle.lower() not in haystack.lower():
                continue
        sample.append(row)
        if len(sample) >= limit:
            break
    return {
        'db_path': str(db_path),
        'table': table_name,
        'row_count': row_count,
        'returned_rows': len(sample),
        'sample': sample,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Bezpieczne sondowanie plików MDB po jednej tabeli.')
    parser.add_argument('--db', required=True)
    parser.add_argument('--mode', choices=['catalog', 'columns', 'rows'], default='catalog')
    parser.add_argument('--table')
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--needle')
    parser.add_argument('--where-column')
    parser.add_argument('--where-value')
    parser.add_argument('--timeout-sec', type=int, default=15)
    parser.add_argument('--out')
    args = parser.parse_args()

    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(max(args.timeout_sec, 1))
    try:
        db_path = Path(args.db).resolve()
        if args.mode == 'catalog':
            result = probe_catalog(db_path)
        elif args.mode == 'columns':
            if not args.table:
                raise ValueError('--table jest wymagane dla mode=columns')
            result = probe_table_columns(db_path, args.table)
        else:
            if not args.table:
                raise ValueError('--table jest wymagane dla mode=rows')
            result = probe_table_rows(
                db_path,
                args.table,
                args.limit,
                args.needle,
                args.where_column,
                args.where_value,
            )
    finally:
        signal.alarm(0)

    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding='utf-8')
    else:
        print(text)


if __name__ == '__main__':
    main()
