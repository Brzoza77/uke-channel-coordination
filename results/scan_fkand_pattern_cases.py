#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path('/home/brzoza/uke')
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import analyze_wlr_request, _pairwise_result_is_problem
from wlr import parse_wlr_file

case_names = [
    '1106.wlr',
    '1234.wlr',
    '1308.wlr',
    '1378.wlr',
    '1905.wlr',
    '3961.wlr',
    'BT10561C-BT10853C-001_0_20260312114554.wlr',
]

results = []
pattern_counter = Counter()
permit_counter = Counter()

for name in case_names:
    path = REPO_ROOT / 'testy' / name
    req = parse_wlr_file(path)
    analysis = analyze_wlr_request(req)
    mismatch_rows = []
    for record in analysis.candidate_frequency_records:
        for row in record.pairwise_results:
            problem = _pairwise_result_is_problem(row)
            blocking = bool(row.is_blocking and row.margin_db is not None)
            red = bool(row.risk_level == 'red' and row.margin_db is not None)
            if problem == blocking == red:
                continue
            mismatch_rows.append({
                'candidate': f"{record.channel_ab}/{record.channel_ba} {record.polarization}",
                'status': record.status,
                'branch': row.direction,
                'permit': row.interfering_permit_number,
                'conflict_type': row.conflict_type,
                'relationship': row.relationship,
                'margin_db': row.margin_db,
                'ci_db': row.ci_db,
                'degradation_db': row.degradation_db,
                'overlap_ratio': row.overlap_ratio,
                'effective_freq_delta_mhz': row.effective_freq_delta_mhz,
                'problem': problem,
                'blocking_counted': blocking,
                'red_counted': red,
            })
            pattern_counter[(row.direction, row.conflict_type, row.relationship, problem, blocking, red, round(row.overlap_ratio or 0.0, 6))] += 1
            permit_counter[row.interfering_permit_number or 'UNKNOWN'] += 1
    results.append({
        'wlr': name,
        'plan_symbol': req.plan_symbol,
        'channel_width_mhz': req.channel_width_mhz,
        'freq_ab_ghz': req.freq_ab_ghz,
        'freq_ba_ghz': req.freq_ba_ghz,
        'candidate_count': len(analysis.candidate_frequency_records),
        'mismatch_row_count': len(mismatch_rows),
        'sample_mismatches': mismatch_rows[:10],
    })

report = {
    'cases': results,
    'totals': {
        'cases_scanned': len(results),
        'cases_with_mismatch': sum(1 for item in results if item['mismatch_row_count'] > 0),
        'total_mismatch_rows': sum(item['mismatch_row_count'] for item in results),
        'pattern_counter': [
            {
                'pattern': {
                    'branch': key[0],
                    'conflict_type': key[1],
                    'relationship': key[2],
                    'problem': key[3],
                    'blocking_counted': key[4],
                    'red_counted': key[5],
                    'overlap_ratio': key[6],
                },
                'rows': count,
            }
            for key, count in pattern_counter.most_common()
        ],
        'permit_counter_top20': permit_counter.most_common(20),
    },
}

out = REPO_ROOT / 'logs' / 'fkand_pattern_multicase_scan_20260316.json'
out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(out)
print(json.dumps(report['totals'], ensure_ascii=False, indent=2))
