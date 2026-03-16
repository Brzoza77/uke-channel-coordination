#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Summarize how Access appears to assign candidate Status values.')
    parser.add_argument('--querydefs-json', default='logs/access_querydefs_inventory_20260316.json')
    parser.add_argument('--status-analysis-json', default='logs/access_status_results_analysis_20260316.json')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    querydefs_payload = json.loads(Path(args.querydefs_json).read_text(encoding='utf-8'))
    status_payload = json.loads(Path(args.status_analysis_json).read_text(encoding='utf-8'))

    inventory = querydefs_payload['inventory']
    modules = inventory['objects_by_type'].get('-32761', [])
    macros = inventory['objects_by_type'].get('-32766', [])
    queries = {q['name']: q for q in querydefs_payload['query_inventory']['querydefs']}

    payload = {
        'status_observations': {
            'stored_candidate_statuses': status_payload['status_distribution'],
            'print_queries': {
                'Wyniki_do_wydruku': queries.get('Wyniki_do_wydruku'),
                'Wyniki do wydruku_tab4': queries.get('Wyniki do wydruku_tab4'),
            },
            'result_queries': {
                'Wyniki_b-i': queries.get('Wyniki_b-i'),
                'Wyniki_i-b': queries.get('Wyniki_i-b'),
                'Wyniki_b-iz': queries.get('Wyniki_b-iz'),
                'Wyniki_iz-b': queries.get('Wyniki_iz-b'),
                'Wyniki_b-iss': queries.get('Wyniki_b-iss'),
                'Wyniki_iss-b': queries.get('Wyniki_iss-b'),
            },
        },
        'module_macro_inventory': {
            'modules': modules,
            'macros': macros,
        },
        'inference': {
            'confirmed': [
                'Status = 2 is consumed by Wyniki_do_wydruku at print-selection time.',
                'The wider query Wyniki do wydruku_tab4 reads the same candidate fields without filtering Status = 2.',
                'No saved QueryDef in the current inventory clearly performs UPDATE Czestotliwosc kandydujaca SET Status = 2.',
                'The stored consultation sample contains only Status = 1 rows, so Status = 2 is not reachable from that sample alone.',
            ],
            'likely': [
                'Candidate status assignment is orchestrated by VBA/modules or macros rather than by a visible saved SELECT query.',
                'Modules such as Zadania_LR, Zadania_LR_Tlumienie, Master or start/autoexec are the strongest candidates for the missing status-assignment logic.',
                'Saved queries describe how candidates are selected, paired, exported and printed, but not the complete control flow that flips Status to 2.',
            ],
            'not_proven': [
                'Exact rule that changes a candidate from Status = 1 to Status = 2.',
                'Whether Status = 2 means selected-for-print, accepted-best, conflict-worthy, or another workflow state.',
            ],
        },
        'next_step': 'Inspect VBA/macros or exported source of modules Zadania_LR / Master / start to find status-setting SQL or DAO operations.',
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
