from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from analysis import get_duplex_links


def main() -> None:
    links = get_duplex_links()
    need = Counter()
    for link in links:
        for site in (link.site_a, link.site_b):
            key = ((site.antenna_type or '').strip(), (site.antenna_vendor or '').strip())
            need[key] += 1

    conn = sqlite3.connect('data/uke_antennas_full.sqlite')
    matched = []
    unmatched = []
    for (antenna_type, vendor), count in need.items():
        rows = conn.execute(
            '''
            SELECT COUNT(*) FROM antena a
            LEFT JOIN producent p ON p.producent_id = a.producent_id
            WHERE lower(coalesce(a.typ_anteny,'')) = ?
              AND lower(coalesce(p.nazwa_producenta,'')) = ?
            ''',
            (antenna_type.lower(), vendor.lower()),
        ).fetchone()[0]
        item = {
            'antenna_type': antenna_type,
            'vendor': vendor,
            'endpoint_count': count,
            'catalog_matches': rows,
        }
        if rows:
            matched.append(item)
        else:
            unmatched.append(item)

    matched.sort(key=lambda x: (-x['endpoint_count'], x['antenna_type']))
    unmatched.sort(key=lambda x: (-x['endpoint_count'], x['antenna_type']))
    report = {
        'distinct_total': len(need),
        'distinct_matched': len(matched),
        'distinct_unmatched': len(unmatched),
        'endpoint_total': sum(need.values()),
        'endpoint_matched': sum(x['endpoint_count'] for x in matched),
        'endpoint_unmatched': sum(x['endpoint_count'] for x in unmatched),
        'top_matched': matched[:50],
        'top_unmatched': unmatched[:50],
    }
    out_path = Path('logs') / 'antenna_catalog_coverage.json'
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out_path)


if __name__ == '__main__':
    main()
