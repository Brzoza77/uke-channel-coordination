#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any, Optional
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import analyze_wlr_request, _pairwise_result_is_problem
from wlr import parse_wlr_file


def _min_optional(values: list[Optional[float]]) -> Optional[float]:
    concrete = [value for value in values if value is not None]
    return min(concrete) if concrete else None


def _branch_hypotheses(results: list[Any]) -> dict[str, Any]:
    valid_rows = [result for result in results if result.margin_db is not None]
    problem_rows = [result for result in results if _pairwise_result_is_problem(result)]
    negative_rows = [result for result in results if result.margin_db is not None and result.margin_db < 0.0]
    blocking_rows = [result for result in results if result.is_blocking and result.margin_db is not None]
    red_rows = [result for result in results if result.risk_level == 'red' and result.margin_db is not None]
    return {
        'margin_min_valid_db': _min_optional([result.margin_db for result in valid_rows]),
        'margin_min_problem_db': _min_optional([result.margin_db for result in problem_rows]),
        'margin_min_negative_db': _min_optional([result.margin_db for result in negative_rows]),
        'margin_min_blocking_db': _min_optional([result.margin_db for result in blocking_rows]),
        'margin_min_red_db': _min_optional([result.margin_db for result in red_rows]),
        'count_valid': len(valid_rows),
        'count_problem': len(problem_rows),
        'count_negative': len(negative_rows),
        'count_blocking': len(blocking_rows),
        'count_red': len(red_rows),
    }


def _candidate_key(record: Any) -> str:
    return f"{record.channel_ab}/{record.channel_ba} {record.polarization}"


def _compare_scalar(current: Any, other: Any) -> bool:
    return current == other


def _mean(values: list[float]) -> float:
    return mean(values) if values else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description='Compare Access-like fkand aggregation hypotheses.')
    parser.add_argument('--wlr', required=True)
    parser.add_argument('--out-json', required=True)
    args = parser.parse_args()

    wlr_path = Path(args.wlr).resolve()
    out_json = Path(args.out_json).resolve()

    request = parse_wlr_file(wlr_path)
    result = analyze_wlr_request(request)

    requested_key = (request.channel_ab, request.channel_ba, request.requested_polarization)

    records_report: list[dict[str, Any]] = []
    margin_match_stats = {
        'margodb': Counter(),
        'margnad': Counter(),
    }
    count_match_stats = {
        'n_odb': Counter(),
        'n_nad': Counter(),
    }
    valid_minus_problem_deltas: list[int] = []
    blocking_minus_problem_deltas: list[int] = []

    for record in result.candidate_frequency_records:
        results_n = [item for item in record.pairwise_results if item.direction == 'A->B']
        results_o = [item for item in record.pairwise_results if item.direction == 'B->A']
        hyp_n = _branch_hypotheses(results_n)
        hyp_o = _branch_hypotheses(results_o)

        hypothesis_block = {
            'n_branch': hyp_n,
            'o_branch': hyp_o,
        }

        margin_variants = {
            'min_valid': (hyp_n['margin_min_valid_db'], hyp_o['margin_min_valid_db']),
            'min_problem': (hyp_n['margin_min_problem_db'], hyp_o['margin_min_problem_db']),
            'min_negative': (hyp_n['margin_min_negative_db'], hyp_o['margin_min_negative_db']),
            'min_blocking': (hyp_n['margin_min_blocking_db'], hyp_o['margin_min_blocking_db']),
            'min_red': (hyp_n['margin_min_red_db'], hyp_o['margin_min_red_db']),
        }
        count_variants = {
            'valid': (hyp_n['count_valid'], hyp_o['count_valid']),
            'problem': (hyp_n['count_problem'], hyp_o['count_problem']),
            'negative': (hyp_n['count_negative'], hyp_o['count_negative']),
            'blocking': (hyp_n['count_blocking'], hyp_o['count_blocking']),
            'red': (hyp_n['count_red'], hyp_o['count_red']),
        }

        for name, (cand_odb, cand_nad) in margin_variants.items():
            if _compare_scalar(record.access_fkand_margodb_db, cand_odb):
                margin_match_stats['margodb'][name] += 1
            if _compare_scalar(record.access_fkand_margnad_db, cand_nad):
                margin_match_stats['margnad'][name] += 1
        for name, (cand_odb, cand_nad) in count_variants.items():
            if _compare_scalar(record.access_fkand_n_odb, cand_odb):
                count_match_stats['n_odb'][name] += 1
            if _compare_scalar(record.access_fkand_n_nad, cand_nad):
                count_match_stats['n_nad'][name] += 1

        valid_minus_problem_deltas.append(hyp_n['count_valid'] - hyp_n['count_problem'])
        valid_minus_problem_deltas.append(hyp_o['count_valid'] - hyp_o['count_problem'])
        blocking_minus_problem_deltas.append(hyp_n['count_blocking'] - hyp_n['count_problem'])
        blocking_minus_problem_deltas.append(hyp_o['count_blocking'] - hyp_o['count_problem'])

        records_report.append({
            'candidate': _candidate_key(record),
            'status': record.status,
            'requested': (record.channel_ab, record.channel_ba, record.polarization) == requested_key,
            'current_fkand': {
                'margodb_db': record.access_fkand_margodb_db,
                'margnad_db': record.access_fkand_margnad_db,
                'n_odb': record.access_fkand_n_odb,
                'n_nad': record.access_fkand_n_nad,
            },
            'uke_like': {
                'margodb_db': record.uke_like_margodb_db,
                'margnad_db': record.uke_like_margnad_db,
            },
            'hypotheses': hypothesis_block,
            'variant_match_flags': {
                'margodb': {name: _compare_scalar(record.access_fkand_margodb_db, pair[0]) for name, pair in margin_variants.items()},
                'margnad': {name: _compare_scalar(record.access_fkand_margnad_db, pair[1]) for name, pair in margin_variants.items()},
                'n_odb': {name: _compare_scalar(record.access_fkand_n_odb, pair[0]) for name, pair in count_variants.items()},
                'n_nad': {name: _compare_scalar(record.access_fkand_n_nad, pair[1]) for name, pair in count_variants.items()},
            },
        })

    requested_record = next((item for item in records_report if item['requested']), None)
    top_by_valid_problem_gap = sorted(
        records_report,
        key=lambda item: max(
            item['hypotheses']['n_branch']['count_valid'] - item['hypotheses']['n_branch']['count_problem'],
            item['hypotheses']['o_branch']['count_valid'] - item['hypotheses']['o_branch']['count_problem'],
        ),
        reverse=True,
    )[:10]

    report = {
        'wlr': str(wlr_path),
        'engine_version': result.__dict__.get('engine_version', None),
        'candidate_count': len(result.candidate_frequency_records),
        'status_counts': dict(Counter(record.status for record in result.candidate_frequency_records)),
        'summary': {
            'margin_match_counts_vs_current_fkand': margin_match_stats,
            'count_match_counts_vs_current_fkand': count_match_stats,
            'avg_valid_minus_problem_delta': _mean(valid_minus_problem_deltas),
            'avg_blocking_minus_problem_delta': _mean(blocking_minus_problem_deltas),
            'uke_like_equals_current_fkand': {
                'margodb_all_candidates': all(item['current_fkand']['margodb_db'] == item['uke_like']['margodb_db'] for item in records_report),
                'margnad_all_candidates': all(item['current_fkand']['margnad_db'] == item['uke_like']['margnad_db'] for item in records_report),
            },
        },
        'requested_candidate': requested_record,
        'top_valid_minus_problem_gap_candidates': top_by_valid_problem_gap,
        'findings': [
            'Current fkand margins can be compared against worst-valid, worst-problem, worst-negative, worst-blocking, and worst-red branch aggregations.',
            'Current fkand counts can be compared against valid-row, problem-row, negative-margin-row, blocking-row, and red-row tallies.',
            'The strongest discriminator for Access semantics is whether clean/conditional candidates keep worst-valid margins or drop to null until a problem row exists.',
            'For counts, the strongest discriminator is whether N-nad/N-odb track all valid branch rows or only problem/incompatible rows.',
        ],
    }

    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(out_json)


if __name__ == '__main__':
    main()
