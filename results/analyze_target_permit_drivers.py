from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def family_of(case_key: str) -> str:
    if case_key.endswith('cross'):
        return 'cross'
    if case_key.endswith('direct'):
        return 'direct'
    return 'other'


def summarize_permit(rows: list[dict[str, object]]) -> dict[str, object]:
    family_counter = Counter()
    overlap_zero = 0
    overlap_nonzero = 0
    deltas = []
    direct_values = []
    cross_values = []
    best_deltas = []
    sample_rows = []

    for row in rows:
        best = str(row.get('best_subcase_key') or '')
        family_counter[family_of(best)] += 1
        subcases = row.get('subcases') or {}
        direct_max = max((float(v.get('degradation_db', 0.0)) for k, v in subcases.items() if str(k).endswith('direct')), default=0.0)
        cross_max = max((float(v.get('degradation_db', 0.0)) for k, v in subcases.items() if str(k).endswith('cross')), default=0.0)
        direct_values.append(direct_max)
        cross_values.append(cross_max)
        deltas.append(min(abs(float(v.get('delta_to_uke_db', 0.0))) for v in subcases.values()) if subcases else 0.0)
        best_deltas.append(abs(float(row.get('best_subcase_delta_db', 0.0))))

        top_overlap = None
        best_case_data = subcases.get(best) or {}
        if 'overlap_ratio' in best_case_data:
            top_overlap = best_case_data.get('overlap_ratio')
        overlap_hint = 'unknown'
        if top_overlap is None:
            # infer coarsely from direct/cross values present in the row description outside the JSON
            overlap_hint = 'unknown'
        sample_rows.append(
            {
                'direction': row.get('direction'),
                'section': row.get('section'),
                'channel': row.get('channel'),
                'polarization': row.get('polarization'),
                'uke_station': row.get('uke_station'),
                'best_subcase_key': best,
                'best_subcase_delta_db': row.get('best_subcase_delta_db'),
                'direct_max_db': round(direct_max, 6),
                'cross_max_db': round(cross_max, 6),
                'dominant_family': 'direct' if direct_max >= cross_max else 'cross',
            }
        )

    avg_direct = sum(direct_values) / len(direct_values) if direct_values else 0.0
    avg_cross = sum(cross_values) / len(cross_values) if cross_values else 0.0
    avg_best_delta = sum(best_deltas) / len(best_deltas) if best_deltas else 0.0

    diagnosis = []
    dominant_family = family_counter.most_common(1)[0][0] if family_counter else 'other'
    if dominant_family == 'cross' and avg_cross > avg_direct + 5.0:
        diagnosis.append('cross family dominates; this looks like adjacent/shared-site coupling, not classic cochannel direct coupling')
    if dominant_family == 'direct' and avg_direct > avg_cross + 10.0:
        diagnosis.append('direct family dominates strongly; DOC-row mapping is likely a larger problem than EMC math for this permit')
    if avg_best_delta > 8.0:
        diagnosis.append('even best-matching subcases still differ materially from UKE; remaining gap is mathematical, not just semantic')
    if not diagnosis:
        diagnosis.append('permit sits near the boundary between mapping ambiguity and EMC math; needs manual inspection')

    return {
        'row_count': len(rows),
        'best_family_counter': dict(family_counter),
        'avg_direct_max_db': round(avg_direct, 6),
        'avg_cross_max_db': round(avg_cross, 6),
        'avg_best_delta_db': round(avg_best_delta, 6),
        'diagnosis': diagnosis,
        'sample_rows': sample_rows[:8],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Analyze mathematical drivers for selected permits.')
    parser.add_argument('--alignment-json', required=True)
    parser.add_argument('--permits', nargs='+', required=True)
    parser.add_argument('--out-json', required=True)
    args = parser.parse_args()

    payload = json.loads(Path(args.alignment_json).read_text(encoding='utf-8'))
    result = {
        'case': payload.get('case'),
        'engine_version': payload.get('engine_version'),
        'permits': {},
    }
    for permit in args.permits:
        permit_payload = payload.get('permits', {}).get(permit)
        if not permit_payload:
            continue
        result['permits'][permit] = summarize_permit(permit_payload.get('rows', []))

    Path(args.out_json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
