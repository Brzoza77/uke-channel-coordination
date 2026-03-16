#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def _load_querydefs(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    return {q['name']: q for q in payload.get('query_inventory', {}).get('querydefs', [])}


def _status_distribution(con: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = con.cursor()
    cur.execute("select name from sqlite_master where type='table' and lower(name) like '%czestotliwosc_kandydujaca%'")
    tables = [r[0] for r in cur.fetchall()]
    out = []
    for table in tables:
        cur.execute(
            f"""
            select status, count(*), min(margnad), max(margnad), min(margodb), max(margodb),
                   min(n_nad), max(n_nad), min(n_odb), max(n_odb)
            from '{table}'
            group by status
            order by status
            """
        )
        rows = cur.fetchall()
        out.append(
            {
                'table': table,
                'statuses': [
                    {
                        'status': row[0],
                        'count': row[1],
                        'margnad_min': row[2],
                        'margnad_max': row[3],
                        'margodb_min': row[4],
                        'margodb_max': row[5],
                        'n_nad_min': row[6],
                        'n_nad_max': row[7],
                        'n_odb_min': row[8],
                        'n_odb_max': row[9],
                    }
                    for row in rows
                ],
            }
        )
    return out


def _sample_candidates(con: sqlite3.Connection) -> list[dict[str, Any]]:
    con.row_factory = sqlite3.Row
    rows = con.execute(
        '''
        select fkandydujaca_id, prz_s_o_id, numer_przesla, numer_pary_f, plan, numer_czestotliwosci,
               kod_nadawczej, polaryzacja, status, margnad, margodb, n_nad, n_odb,
               zachowanie_procesu_obslugi
        from lr_konsultacja_349__czestotliwosc_kandydujaca
        order by fkandydujaca_id
        '''
    ).fetchall()
    return [dict(r) for r in rows]


def _sample_results(con: sqlite3.Connection) -> list[dict[str, Any]]:
    con.row_factory = sqlite3.Row
    rows = con.execute(
        '''
        select fkandydujaca_b_id, prz_s_o_i_id, metoda, margines_b_i, margines_i_b,
               blad_obliczen, opis_bledu
        from lr_konsultacja_349__wynik_emc_lr
        order by fkandydujaca_b_id, prz_s_o_i_id
        '''
    ).fetchall()
    return [dict(r) for r in rows]


def _query_summary(querydefs: dict[str, Any], name: str) -> dict[str, Any]:
    q = querydefs.get(name, {})
    return {
        'name': name,
        'sources': q.get('sources', []),
        'filters': q.get('filters', []),
        'selected_fields': q.get('selected_fields', [])[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Analyze Access candidate Status semantics and result queries.')
    parser.add_argument('--sqlite', default='data/uke_workflow.sqlite')
    parser.add_argument('--querydefs-json', default='logs/access_querydefs_inventory_20260316.json')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).resolve()
    querydefs_path = Path(args.querydefs_json).resolve()
    con = sqlite3.connect(sqlite_path)
    try:
        payload = {
            'sqlite': str(sqlite_path),
            'querydefs_json': str(querydefs_path),
            'status_distribution': _status_distribution(con),
            'sample_candidates': _sample_candidates(con),
            'sample_results': _sample_results(con),
        }
    finally:
        con.close()

    querydefs = _load_querydefs(querydefs_path)
    payload['query_evidence'] = {
        'Wyniki_do_wydruku': _query_summary(querydefs, 'Wyniki_do_wydruku'),
        'Wyniki do wydruku_tab4': _query_summary(querydefs, 'Wyniki do wydruku_tab4'),
        'Wyniki_b-i': _query_summary(querydefs, 'Wyniki_b-i'),
        'Wyniki_i-b': _query_summary(querydefs, 'Wyniki_i-b'),
        'Wyniki_b-iz': _query_summary(querydefs, 'Wyniki_b-iz'),
        'Wyniki_iz-b': _query_summary(querydefs, 'Wyniki_iz-b'),
        'Wyniki_b-iss': _query_summary(querydefs, 'Wyniki_b-iss'),
        'Wyniki_iss-b': _query_summary(querydefs, 'Wyniki_iss-b'),
    }
    payload['inference'] = {
        'confirmed': [
            'Wyniki_b-i / Wyniki_i-b build DOC-visible terrestrial conflict rows from Wynik EMC-LR where margin > 1 and metoda < 2.',
            'Wyniki_b-iz / Wyniki_iz-b are the foreign-coordination branch using Wynik EMC-LR where metoda = 2.',
            'Wyniki_b-iss / Wyniki_iss-b are a separate SS branch based on Wynik EMC-SS.',
            'Wyniki_do_wydruku filters candidate rows by Numer_przesla and Status = 2.',
            'Wyniki do wydruku_tab4 uses the same candidate fields without the Status = 2 filter, so Access has at least one wider result view independent of the final print filter.',
            'The stored sample has only Status = 1 candidates and no positive EMC rows; Wynik EMC-LR stores self rows with blad_obliczen = -1 and message about no interfering LR stations.',
        ],
        'likely': [
            'Status is a candidate/workflow flag used by the print/report layer, not the raw pairwise EMC result itself.',
            'Status = 1 likely represents a non-problematic/default candidate state in the stored sample.',
            'Status = 2 likely marks candidates selected for the final print path or a report-worthy state, but the stored sample is too small to map it cleanly to ACCEPTED/CONDITIONAL/REJECTED.',
        ],
        'not_yet_proven': [
            'Exact semantic mapping of Status codes to user-facing acceptance labels.',
            'Whether Status = 2 means accepted candidate, selected candidate, conflict-bearing candidate, or simply candidate included in a specific report section.',
        ],
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
