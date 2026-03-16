#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import analyze_wlr_request
from wlr import parse_wlr_file


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


def record_payload(record) -> dict:
    return {
        'candidate': f"{record.channel_ab}/{record.channel_ba} {record.polarization}",
        'status': record.status,
        'status_ab': record.status_ab,
        'status_ba': record.status_ba,
        'worst_duplex_margin_db': record.worst_duplex_margin_db,
        'current_fkand': {
            'margnad_db': record.access_fkand_margnad_db,
            'margodb_db': record.access_fkand_margodb_db,
            'n_nad': record.access_fkand_n_nad,
            'n_odb': record.access_fkand_n_odb,
        },
        'dual_path_fkand': {
            'problem_path_margnad_db': record.access_fkand_problem_path_margnad_db,
            'problem_path_margodb_db': record.access_fkand_problem_path_margodb_db,
            'problem_path_n_nad': record.access_fkand_problem_path_n_nad,
            'problem_path_n_odb': record.access_fkand_problem_path_n_odb,
            'incompatible_path_margnad_db': record.access_fkand_incompatible_path_margnad_db,
            'incompatible_path_margodb_db': record.access_fkand_incompatible_path_margodb_db,
            'incompatible_path_n_nad': record.access_fkand_incompatible_path_n_nad,
            'incompatible_path_n_odb': record.access_fkand_incompatible_path_n_odb,
            'problem_only_count': record.access_fkand_problem_only_count,
            'blocking_only_count': record.access_fkand_blocking_only_count,
            'overlap_count': record.access_fkand_overlap_count,
            'notes': record.access_fkand_dual_path_notes,
        },
        'path_combo': path_combo(record),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Analyze experimental dual-path Access fkand model for a WLR case.')
    parser.add_argument('--wlr', required=True)
    parser.add_argument('--out-json', required=True)
    args = parser.parse_args()

    request = parse_wlr_file(Path(args.wlr).resolve())
    analysis = analyze_wlr_request(request)
    records = list(analysis.candidate_frequency_records)
    combo_counter = Counter(path_combo(record) for record in records)

    requested = next(
        (
            record for record in records
            if record.channel_ab == request.channel_ab
            and record.channel_ba == request.channel_ba
            and record.polarization == request.requested_polarization
        ),
        None,
    )

    top_by_overlap = sorted(records, key=lambda record: record.access_fkand_overlap_count, reverse=True)[:10]
    top_by_incompatible = sorted(
        records,
        key=lambda record: record.access_fkand_incompatible_path_n_odb + record.access_fkand_incompatible_path_n_nad,
        reverse=True,
    )[:10]
    top_by_problem = sorted(
        records,
        key=lambda record: record.access_fkand_problem_path_n_odb + record.access_fkand_problem_path_n_nad,
        reverse=True,
    )[:10]

    report = {
        'wlr': str(Path(args.wlr).resolve()),
        'engine_version': analysis.__class__.__name__,
        'channel_count': len(records),
        'combo_counter': dict(combo_counter),
        'requested_candidate': record_payload(requested) if requested else None,
        'top_by_overlap_count': [record_payload(record) for record in top_by_overlap],
        'top_by_incompatible_path_count': [record_payload(record) for record in top_by_incompatible],
        'top_by_problem_path_count': [record_payload(record) for record in top_by_problem],
        'findings': [
            'The experimental model keeps separate problem-path and incompatible-path candidate tallies instead of collapsing everything into one fkand count.',
            'Problem-path is intended to mirror problem_kons / decyzja_o_koordynacji style bookkeeping.',
            'Incompatible-path is intended to mirror status niekompatybilna -> wyniki_EMC_prz -> aktualizacja parametr w fkand.',
        ],
    }

    out_path = Path(args.out_json).resolve()
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(out_path)


if __name__ == '__main__':
    main()
