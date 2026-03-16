#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

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


def main() -> None:
    total = 0
    matched = 0
    confusion = defaultdict(Counter)
    case_summaries = []
    mismatches = []

    for case_name in CASE_NAMES:
        req = parse_wlr_file(REPO_ROOT / 'testy' / case_name)
        analysis = analyze_wlr_request(req)
        case_total = 0
        case_matched = 0
        requested = None

        for record in analysis.candidate_frequency_records:
            total += 1
            case_total += 1
            confusion[record.status][record.access_fkand_gate_status] += 1
            if record.status == record.access_fkand_gate_status:
                matched += 1
                case_matched += 1
            else:
                if len(mismatches) < 60:
                    mismatches.append({
                        'wlr': case_name,
                        'candidate': f"{record.channel_ab}/{record.channel_ba} {record.polarization}",
                        'engine_status': record.status,
                        'gate_status': record.access_fkand_gate_status,
                        'problem_count': record.access_fkand_problem_path_n_odb + record.access_fkand_problem_path_n_nad,
                        'incompatible_count': record.access_fkand_incompatible_path_n_odb + record.access_fkand_incompatible_path_n_nad,
                        'overlap_count': record.access_fkand_overlap_count,
                        'worst_duplex_margin_db': record.worst_duplex_margin_db,
                        'gate_notes': record.access_fkand_gate_notes,
                    })
            if record.channel_ab == req.channel_ab and record.channel_ba == req.channel_ba and record.polarization == req.requested_polarization:
                requested = {
                    'candidate': f"{record.channel_ab}/{record.channel_ba} {record.polarization}",
                    'engine_status': record.status,
                    'gate_status': record.access_fkand_gate_status,
                    'problem_count': record.access_fkand_problem_path_n_odb + record.access_fkand_problem_path_n_nad,
                    'incompatible_count': record.access_fkand_incompatible_path_n_odb + record.access_fkand_incompatible_path_n_nad,
                    'overlap_count': record.access_fkand_overlap_count,
                    'worst_duplex_margin_db': record.worst_duplex_margin_db,
                }

        case_summaries.append({
            'wlr': case_name,
            'accuracy': (case_matched / case_total) if case_total else 0.0,
            'requested_candidate': requested,
        })

    report = {
        'cases': case_summaries,
        'totals': {
            'rows': total,
            'matched': matched,
            'accuracy': (matched / total) if total else 0.0,
            'confusion': {key: dict(value) for key, value in confusion.items()},
        },
        'sample_mismatches': mismatches,
        'findings': [
            'This evaluates the experimental dual-path status gate against the current engine status labels on the representative case pack.',
            'The most important signal is whether the gate cleanly recovers ACCEPTED versus non-ACCEPTED before tuning CONDITIONAL versus REJECTED.',
        ],
    }

    out = REPO_ROOT / 'logs' / 'fkand_status_gate_evaluation_20260316.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(out)
    print(json.dumps(report['totals'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
