#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import analyze_wlr_request, _pairwise_result_is_problem
from wlr import parse_wlr_file

MDB_PATH = REPO_ROOT / 'LR_Konsultacja_349.mdb'
OUT_PATH = REPO_ROOT / 'logs' / 'fkand_mismatch_classes_20260316.json'
CASE_NAMES = [
    '1106.wlr',
    '1234.wlr',
    '1308.wlr',
    '1378.wlr',
    '1905.wlr',
    '3961.wlr',
    'BT10561C-BT10853C-001_0_20260312114554.wlr',
]


def collect_strings_with_offsets() -> list[tuple[int, str]]:
    proc = subprocess.run(
        ['strings', '-t', 'd', str(MDB_PATH)],
        capture_output=True,
        text=True,
        check=True,
    )
    rows: list[tuple[int, str]] = []
    for raw in proc.stdout.splitlines():
        parts = raw.split(' ', 1)
        if len(parts) != 2:
            continue
        try:
            offset = int(parts[0])
        except ValueError:
            continue
        rows.append((offset, parts[1].lstrip()))
    return rows


def first_offset(entries: list[tuple[int, str]], needle: str) -> int | None:
    for offset, text in entries:
        if needle in text:
            return offset
    return None


def first_text(entries: list[tuple[int, str]], needle: str) -> str | None:
    for _, text in entries:
        if needle in text:
            return text
    return None



def classify_row(row: dict) -> str:
    if row['problem'] and (not row['blocking_counted']) and (not row['red_counted']):
        return 'problem_only'
    if (not row['problem']) and row['blocking_counted']:
        return 'blocking_only'
    if row['problem'] and row['blocking_counted'] and (not row['red_counted']):
        return 'problem_plus_blocking'
    if row['problem'] and row['blocking_counted'] and row['red_counted']:
        return 'problem_plus_blocking_plus_red'
    return 'other'


def summarize(rows: list[dict]) -> dict:
    return {
        'rows': len(rows),
        'branches': dict(Counter(row['branch'] for row in rows)),
        'conflict_types': dict(Counter(row['conflict_type'] for row in rows)),
        'relationships': dict(Counter(row['relationship'] for row in rows)),
        'permits_top10': Counter(row['permit'] for row in rows).most_common(10),
        'sample': rows[:10],
    }


def main() -> None:
    rows: list[dict] = []
    for name in CASE_NAMES:
        req = parse_wlr_file(REPO_ROOT / 'testy' / name)
        analysis = analyze_wlr_request(req)
        for record in analysis.candidate_frequency_records:
            for row in record.pairwise_results:
                problem = _pairwise_result_is_problem(row)
                blocking = bool(row.is_blocking and row.margin_db is not None)
                red = bool(row.risk_level == 'red' and row.margin_db is not None)
                if problem == blocking == red:
                    continue
                rows.append({
                    'wlr': name,
                    'candidate': f"{record.channel_ab}/{record.channel_ba} {record.polarization}",
                    'status': record.status,
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
                    'problem': problem,
                    'blocking_counted': blocking,
                    'red_counted': red,
                })
    classes: dict[str, list[dict]] = {
        'problem_only': [],
        'blocking_only': [],
        'problem_plus_blocking': [],
        'problem_plus_blocking_plus_red': [],
        'other': [],
    }
    for row in rows:
        classes[classify_row(row)].append(row)

    entries = collect_strings_with_offsets()
    vba_markers = {
        'problem_table_insert': first_offset(entries, 'filepk![TD p-gr] = td_o'),
        'problem_decision_update': first_offset(entries, 'Problem.decyzja_o_koordynacji = IIf([d11]>[dgr],1,2)'),
        'status_incompatible_n': first_offset(entries, 'nadaj czestotliwosci status niekompatybilna'),
        'status_incompatible_o': first_offset(entries, 'wyniki_EMC_prz db, filen![przeslo#], Marg_o, Dzi'),
        'fkand_update': first_offset(entries, 'aktualizacja parametr'),
        'marg_n_comment': first_text(entries, 'Marg_n oznacza degradacj'),
        'marg_o_comment': first_text(entries, 'Marg_o oznacza degradacj'),
    }

    findings = [
        'The mismatch space splits into stable semantic classes instead of one noisy bucket.',
        'Rows with problem=true but blocking/red=false cluster around adjacent/geometry non-overlap cases.',
        'Rows with problem=false but blocking=true cluster around cochannel overlap=1.0 and some adjacent shared-site rows with positive margin.',
        'Recovered VBA strongly suggests two separate procedural paths: Problem table / decyzja_o_koordynacji versus status niekompatybilna / wyniki_EMC_prz / fkand update.',
    ]

    class_interpretation = {
        'problem_only': {
            'most_likely_access_path': 'problem_kons -> Problem.decyzja_o_koordynacji',
            'why': 'These rows look like coordination/problem bookkeeping, not hard incompatible status writes.',
        },
        'blocking_only': {
            'most_likely_access_path': 'status niekompatybilna -> wyniki_EMC_prz -> aktualizacja parametr w fkand',
            'why': 'These rows align better with the recovered incompatible-status writer path than with the Problem table path.',
        },
        'problem_plus_blocking': {
            'most_likely_access_path': 'overlap zone where both bookkeeping and incompatibility writer can fire',
            'why': 'These rows likely sit closest to the actual bridge between problem tracking and final candidate state.',
        },
    }

    report = {
        'cases_scanned': CASE_NAMES,
        'vba_markers': vba_markers,
        'class_summaries': {name: summarize(items) for name, items in classes.items()},
        'class_interpretation': class_interpretation,
        'findings': findings,
    }

    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(OUT_PATH)


if __name__ == '__main__':
    main()
