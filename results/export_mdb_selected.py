from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

VENDOR_PATH = Path(__file__).resolve().parents[1] / '.vendor' / 'accessparse'
if VENDOR_PATH.exists():
    sys.path.insert(0, str(VENDOR_PATH))

from access_parser import AccessParser  # type: ignore

DEFAULT_TABLES = [
    'ANTENA',
    'PASMO ANTENY',
    'CHARAKTERYSTYKA',
    'ELEMENT_CHARAKTERYSTYKI',
    'PRODUCENT',
    'NADAJNIK',
    'maski',
    'HOMOLOGACJA',
    'ZASTOSOWANA ANTENA',
    'PRZESLO',
    'Dane_EMC',
    'Wynik EMC-LR',
]


def export_table(db: AccessParser, table_name: str, out_dir: Path) -> dict[str, Any]:
    table = db.get_table(table_name)
    if table is None:
        return {'table': table_name, 'status': 'missing'}
    parsed = table.parse()
    columns = list(parsed.keys())
    row_count = len(next(iter(parsed.values()))) if parsed else 0
    out_path = out_dir / f"{table_name.replace('/', '_')}.jsonl"
    with out_path.open('w', encoding='utf-8') as fh:
        for i in range(row_count):
            row = {col: parsed[col][i] for col in columns}
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
    return {
        'table': table_name,
        'status': 'ok',
        'rows': row_count,
        'columns': columns,
        'out': str(out_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Eksport wybranych tabel MDB do JSONL.')
    parser.add_argument('--db', required=True)
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--tables', nargs='*', default=DEFAULT_TABLES)
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    db = AccessParser(str(db_path))
    manifest = []
    for table_name in args.tables:
        manifest.append(export_table(db, table_name, out_dir))
    manifest_path = out_dir / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(manifest_path)


if __name__ == '__main__':
    main()
