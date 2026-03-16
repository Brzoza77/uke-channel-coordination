#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path('/home/brzoza/uke')
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import analyze_wlr_request, _pairwise_result_is_problem
from wlr import parse_wlr_file

wlr_path = REPO_ROOT / 'testy' / 'BT10561C-BT10853C-001_0_20260312114554.wlr'
request = parse_wlr_file(wlr_path)
result = analyze_wlr_request(request)

mismatch_rows = []
branch_counter = Counter()
permit_counter = Counter()
conflict_counter = Counter()
relationship_counter = Counter()

for record in result.candidate_frequency_records:
    for row in record.pairwise_results:
        problem = _pairwise_result_is_problem(row)
        blocking = bool(row.is_blocking and row.margin_db is not None)
        red = bool(row.risk_level == 'red' and row.margin_db is not None)
        if problem == blocking == red:
            continue
        signature = {
            'candidate': f"{record.channel_ab}/{record.channel_ba} {record.polarization}",
            'candidate_status': record.status,
            'branch': row.direction,
            'permit': row.interfering_permit_number,
            'operator': row.interfering_operator_name,
            'conflict_type': row.conflict_type,
            'relationship': row.relationship,
            'margin_db': row.margin_db,
            'ci_db': row.ci_db,
            'degradation_db': row.degradation_db,
            'overlap_ratio': row.overlap_ratio,
            'effective_freq_delta_mhz': row.effective_freq_delta_mhz,
            'risk_level': row.risk_level,
            'is_blocking': row.is_blocking,
            'problem': problem,
            'blocking_counted': blocking,
            'red_counted': red,
            'explanation': row.explanation,
        }
        mismatch_rows.append(signature)
        branch_counter[row.direction] += 1
        permit_counter[row.interfering_permit_number or 'UNKNOWN'] += 1
        conflict_counter[row.conflict_type] += 1
        relationship_counter[row.relationship] += 1

pattern_groups = defaultdict(list)
for row in mismatch_rows:
    key = (
        row['branch'],
        row['conflict_type'],
        row['relationship'],
        row['problem'],
        row['blocking_counted'],
        row['red_counted'],
        round(row['overlap_ratio'] or 0.0, 6),
    )
    pattern_groups[key].append(row)

pattern_summary = []
for key, rows in sorted(pattern_groups.items(), key=lambda item: len(item[1]), reverse=True):
    margins = [row['margin_db'] for row in rows if row['margin_db'] is not None]
    cis = [row['ci_db'] for row in rows if row['ci_db'] is not None]
    degs = [row['degradation_db'] for row in rows if row['degradation_db'] is not None]
    deltas = [row['effective_freq_delta_mhz'] for row in rows if row['effective_freq_delta_mhz'] is not None]
    pattern_summary.append({
        'pattern': {
            'branch': key[0],
            'conflict_type': key[1],
            'relationship': key[2],
            'problem': key[3],
            'blocking_counted': key[4],
            'red_counted': key[5],
            'overlap_ratio': key[6],
        },
        'rows': len(rows),
        'permits': Counter(row['permit'] for row in rows),
        'candidates': [row['candidate'] for row in rows[:10]],
        'margin_range_db': [min(margins), max(margins)] if margins else None,
        'ci_range_db': [min(cis), max(cis)] if cis else None,
        'degradation_range_db': [min(degs), max(degs)] if degs else None,
        'freq_delta_range_mhz': [min(deltas), max(deltas)] if deltas else None,
    })

report = {
    'benchmark': wlr_path.name,
    'candidate_count': len(result.candidate_frequency_records),
    'mismatch_row_count': len(mismatch_rows),
    'branch_counter': dict(branch_counter),
    'permit_counter_top10': permit_counter.most_common(10),
    'conflict_counter': dict(conflict_counter),
    'relationship_counter': dict(relationship_counter),
    'pattern_summary': pattern_summary,
    'sample_rows': mismatch_rows[:25],
    'findings': [],
}

if mismatch_rows:
    top = pattern_summary[0]
    report['findings'].append(
        'There is a recurring mismatch class where rows are counted as blocking/red but not as problem rows.'
    )
    report['findings'].append(
        f"Dominant pattern: {top['pattern']} across {top['rows']} rows."
    )
else:
    report['findings'].append('No mismatch rows found between problem and blocking/red semantics.')

out_path = REPO_ROOT / 'logs' / 'fkand_pattern_scan_20260316.json'
out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(out_path)
print(json.dumps({
    'mismatch_row_count': report['mismatch_row_count'],
    'branch_counter': report['branch_counter'],
    'conflict_counter': report['conflict_counter'],
    'relationship_counter': report['relationship_counter'],
    'top_pattern': report['pattern_summary'][0] if report['pattern_summary'] else None,
}, ensure_ascii=False, indent=2))
