#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Summarize experimental Access writer projection columns from a rerun CSV.')
    parser.add_argument('--csv', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve()
    out_path = Path(args.out).resolve()

    rows = []
    with csv_path.open(encoding='utf-8', newline='') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(row)

    side_counter = Counter()
    case_counter = Counter()
    permit_gaps: dict[str, list[float]] = defaultdict(list)
    top_rows = []

    for row in rows:
        side = row.get('engine_writer_projection_side', '')
        case_key = row.get('engine_writer_projection_case_key', '')
        if side:
            side_counter[side] += 1
        if case_key:
            case_counter[case_key] += 1
        try:
            uke_value = float(row['uke_link_degradation_db'])
            writer_value = float(row['engine_writer_projection_degradation_db'])
        except Exception:
            continue
        gap = abs(uke_value - writer_value)
        permit = row.get('uke_link_permit', '')
        permit_gaps[permit].append(gap)
        top_rows.append(
            {
                'permit': permit,
                'section': row.get('section', ''),
                'direction': row.get('direction', ''),
                'station': row.get('uke_link_station', ''),
                'writer_side': side,
                'writer_case_key': case_key,
                'uke_db': uke_value,
                'writer_db': writer_value,
                'gap_db': gap,
            }
        )

    payload = {
        'source_csv': str(csv_path),
        'row_count': len(rows),
        'writer_side_counts': dict(side_counter),
        'writer_case_key_counts_top': case_counter.most_common(20),
        'top_gap_rows': sorted(top_rows, key=lambda item: item['gap_db'], reverse=True)[:20],
        'top_gap_permits': [
            {
                'permit': permit,
                'mae_db': round(statistics.mean(gaps), 6),
                'row_count': len(gaps),
            }
            for permit, gaps in sorted(permit_gaps.items(), key=lambda item: statistics.mean(item[1]), reverse=True)[:15]
        ],
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
