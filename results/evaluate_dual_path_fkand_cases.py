#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import analyze_wlr_request
from wlr import parse_wlr_file

CASE_NAMES = [
    '1106.wlr',
    '1234.wlr',
    '1308.wlr',
    '1378.wlr',
    '1905.wlr',
    '3961.wlr',
    'BT10561C-BT10853C-001_0_20260312114554.wlr',
]


def path_combo(record) -> str:
    has_problem = (record.access_fkand_problem_path_n_odb + record.access_fkand_problem_path_n_nad) > 0
    has_incompatible = (record.access_fkand_incompatible_path_n_odb + record.access_fkand_incompatible_path_n_nad) > 0
    if has_problem and has_incompatible:
        return 'both_paths'
    if has_problem:
        return 'problem_path_only'
    if has_incompatible:
        return 'incompatible_path_only'
    return 'no_path'


def avg(values):
    return mean(values) if values else 0.0


def main() -> None:
    case_reports = []
    combo_counter = Counter()
    status_by_combo = defaultdict(Counter)
    status_by_problem_presence = defaultdict(Counter)
    status_by_incompatible_presence = defaultdict(Counter)
    metrics_by_status = defaultdict(list)

    for case_name in CASE_NAMES:
        req = parse_wlr_file(REPO_ROOT / 'testy' / case_name)
        analysis = analyze_wlr_request(req)
        combo_local = Counter()
        requested_payload = None

        for record in analysis.candidate_frequency_records:
            combo = path_combo(record)
            combo_counter[combo] += 1
            combo_local[combo] += 1
            status_by_combo[combo][record.status] += 1
            status_by_problem_presence[str((record.access_fkand_problem_path_n_odb + record.access_fkand_problem_path_n_nad) > 0)][record.status] += 1
            status_by_incompatible_presence[str((record.access_fkand_incompatible_path_n_odb + record.access_fkand_incompatible_path_n_nad) > 0)][record.status] += 1
            metrics_by_status[record.status].append({
                'problem_count': record.access_fkand_problem_path_n_odb + record.access_fkand_problem_path_n_nad,
                'incompatible_count': record.access_fkand_incompatible_path_n_odb + record.access_fkand_incompatible_path_n_nad,
                'overlap_count': record.access_fkand_overlap_count,
                'problem_only_count': record.access_fkand_problem_only_count,
                'blocking_only_count': record.access_fkand_blocking_only_count,
            })
            if record.channel_ab == req.channel_ab and record.channel_ba == req.channel_ba and record.polarization == req.requested_polarization:
                requested_payload = {
                    'candidate': f"{record.channel_ab}/{record.channel_ba} {record.polarization}",
                    'status': record.status,
                    'combo': combo,
                    'problem_count': record.access_fkand_problem_path_n_odb + record.access_fkand_problem_path_n_nad,
                    'incompatible_count': record.access_fkand_incompatible_path_n_odb + record.access_fkand_incompatible_path_n_nad,
                    'overlap_count': record.access_fkand_overlap_count,
                    'problem_only_count': record.access_fkand_problem_only_count,
                    'blocking_only_count': record.access_fkand_blocking_only_count,
                }

        case_reports.append({
            'wlr': case_name,
            'combo_counter': dict(combo_local),
            'requested_candidate': requested_payload,
        })

    metric_summary = {}
    for status, rows in metrics_by_status.items():
        metric_summary[status] = {
            'avg_problem_count': avg([row['problem_count'] for row in rows]),
            'avg_incompatible_count': avg([row['incompatible_count'] for row in rows]),
            'avg_overlap_count': avg([row['overlap_count'] for row in rows]),
            'avg_problem_only_count': avg([row['problem_only_count'] for row in rows]),
            'avg_blocking_only_count': avg([row['blocking_only_count'] for row in rows]),
            'rows': len(rows),
        }

    report = {
        'cases': case_reports,
        'totals': {
            'combo_counter': dict(combo_counter),
            'status_by_combo': {key: dict(value) for key, value in status_by_combo.items()},
            'status_by_problem_presence': {key: dict(value) for key, value in status_by_problem_presence.items()},
            'status_by_incompatible_presence': {key: dict(value) for key, value in status_by_incompatible_presence.items()},
            'metric_summary_by_status': metric_summary,
        },
        'findings': [
            'This report checks whether the dual-path fkand model separates accepted/conditional/rejected candidates better than the single collapsed proxy.',
            'The most informative outputs are status_by_combo and per-status averages of problem_only_count versus blocking_only_count.',
        ],
    }

    out = REPO_ROOT / 'logs' / 'fkand_dual_path_case_evaluation_20260316.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(out)
    print(json.dumps(report['totals'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
