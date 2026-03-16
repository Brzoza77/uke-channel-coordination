#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path


def load_benchmark_residuals(csv_path: Path) -> dict:
    rows = []
    with csv_path.open(encoding='utf-8', newline='') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                uke_value = float(row['uke_link_degradation_db'])
                engine_value = float(row['engine_mapped_aligned_db'])
            except Exception:
                continue
            rows.append(
                {
                    'permit': row['uke_link_permit'],
                    'section': row['section'],
                    'direction': row['direction'],
                    'station': row['uke_link_station'],
                    'uke_db': uke_value,
                    'engine_db': engine_value,
                    'gap_db': abs(uke_value - engine_value),
                    'mapped_case_key': row.get('engine_mapped_case_key', ''),
                }
            )

    per_permit: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        per_permit[row['permit']].append(row['gap_db'])

    top_rows = sorted(rows, key=lambda item: item['gap_db'], reverse=True)[:20]
    top_permits = [
        {
            'permit': permit,
            'mae_db': round(statistics.mean(gaps), 6),
            'row_count': len(gaps),
        }
        for permit, gaps in sorted(per_permit.items(), key=lambda item: statistics.mean(item[1]), reverse=True)[:10]
    ]
    return {
        'row_count': len(rows),
        'top_rows': top_rows,
        'top_permits': top_permits,
    }


def load_tlum_cyrk_summary(sqlite_path: Path) -> dict:
    con = sqlite3.connect(str(sqlite_path))
    cur = con.cursor()
    plan_rows = cur.execute(
        '''
        SELECT plan.symbol_planu, sygnal.szeroko,
               AVG(COALESCE(przeslo.t_umienie_cyrkulator_w_n,0.0)),
               AVG(COALESCE(przeslo.t_umienie_cyrkulator_w_o,0.0)),
               COUNT(*)
        FROM lr_konsultacja_349__przeslo AS przeslo
        LEFT JOIN lr_konsultacja_349__plan AS plan ON przeslo.numer_planu = plan.plan_id
        LEFT JOIN lr_konsultacja_349__sygnal AS sygnal ON przeslo.sygna_id = sygnal.sygna_id
        WHERE plan.symbol_planu IN ('75/85A250','75/85A125','75/85A62.5','23A56','23A28','23A14','23A7','38A56','38A28','38A14','38A7')
        GROUP BY plan.symbol_planu, sygnal.szeroko
        ORDER BY plan.symbol_planu, sygnal.szeroko
        '''
    ).fetchall()
    eband_mode_rows = cur.execute(
        '''
        SELECT plan.symbol_planu, sygnal.szeroko, przeslo.t_umienie_cyrkulator_w_n, przeslo.t_umienie_cyrkulator_w_o, COUNT(*)
        FROM lr_konsultacja_349__przeslo AS przeslo
        LEFT JOIN lr_konsultacja_349__plan AS plan ON przeslo.numer_planu = plan.plan_id
        LEFT JOIN lr_konsultacja_349__sygnal AS sygnal ON przeslo.sygna_id = sygnal.sygna_id
        WHERE plan.symbol_planu LIKE '75/85%'
        GROUP BY plan.symbol_planu, sygnal.szeroko, przeslo.t_umienie_cyrkulator_w_n, przeslo.t_umienie_cyrkulator_w_o
        ORDER BY COUNT(*) DESC
        LIMIT 20
        '''
    ).fetchall()
    all_eband_values = []
    for row in cur.execute(
        '''
        SELECT przeslo.t_umienie_cyrkulator_w_n, przeslo.t_umienie_cyrkulator_w_o
        FROM lr_konsultacja_349__przeslo AS przeslo
        LEFT JOIN lr_konsultacja_349__plan AS plan ON przeslo.numer_planu = plan.plan_id
        WHERE plan.symbol_planu LIKE '75/85%'
        '''
    ):
        for value in row:
            if value is not None:
                all_eband_values.append(float(value))
    all_eband_values.sort()
    con.close()
    return {
        'eband_overall': {
            'row_count': len(all_eband_values),
            'min_db': all_eband_values[0] if all_eband_values else None,
            'p50_db': all_eband_values[len(all_eband_values) // 2] if all_eband_values else None,
            'p90_db': all_eband_values[int(len(all_eband_values) * 0.9)] if all_eband_values else None,
            'max_db': all_eband_values[-1] if all_eband_values else None,
        },
        'selected_plan_averages': [
            {
                'plan_symbol': row[0],
                'channel_width_mhz': row[1],
                'avg_tlum_cyrk_n_db': round(row[2], 6),
                'avg_tlum_cyrk_o_db': round(row[3], 6),
                'row_count': row[4],
            }
            for row in plan_rows
        ],
        'eband_common_modes': [
            {
                'plan_symbol': row[0],
                'channel_width_mhz': row[1],
                'tlum_cyrk_n_db': row[2],
                'tlum_cyrk_o_db': row[3],
                'row_count': row[4],
            }
            for row in eband_mode_rows
        ],
        'inference': 'In the current _349 snapshot, 75/85 GHz circulator losses are usually 0.0 or 0.5 dB, so missing TlumCyrk alone cannot explain the largest residuals still left in the benchmark.',
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Summarize likely semantics of Access wyniki_EMC_fk from string traces and benchmark evidence.')
    parser.add_argument('--benchmark-csv', required=True)
    parser.add_argument('--sqlite', default='data/uke_workflow.sqlite')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    benchmark_csv = Path(args.benchmark_csv).resolve()
    sqlite_path = Path(args.sqlite).resolve()
    out_path = Path(args.out).resolve()

    payload = {
        'procedure': 'wyniki_EMC_fk',
        'signature': 'Sub wyniki_EMC_fk(db, fid As Long, marg As Variant, dz As Double, idprzesla As Long, wsk As Byte, metoda As Byte, blad As Long, opis_bledu As String)',
        'core_evidence': [
            {
                'lines': '599418-599440',
                'raw': [
                    'DELETE DISTINCTROW ... [FKandydujaca_b#] FROM ... WHERE [FKandydujaca_b#]=',
                    'wpisanie 1 rekordu wyniku',
                    'Sub wyniki_EMC_fk(db, fid As Long, marg As Variant, dz As Double, idprzesla As Long, wsk As Byte, metoda As Byte, blad As Long, opis_bledu As String)',
                    '[FKandydujaca_b#]',
                    'Wynik EMC-LR',
                    'and metoda=2',
                    'nie ma zagranicznych stacji zakłócających',
                    'brak maski',
                    'Nfd_Md = 0',
                    'brak nadajnika',
                ],
                'inference': 'The routine deletes/replaces the prior result row for the candidate and writes one pairwise EMC result record into Wynik EMC-LR.',
            },
            {
                'lines': '595809-595860',
                'raw': [
                    'marg',
                    'idprzesla',
                    'metodas',
                    'sprz',
                    'FKandydujaca_b#',
                    'Odleglosc_b-i',
                    'Margines_b-i',
                    'Odleglosc_i-b',
                    'Margines_i-b',
                    'distance',
                    'wstaw_status',
                    'obliczenia_EMC_POL_ZAGR',
                    'status_kand',
                    'TlumCyrk_NO',
                    'dd_n',
                    'dd_o',
                    'wsp_szum_i',
                    'moc_szumow',
                ],
                'inference': 'The variable neighborhood links marg/idprzesla/metoda/sprz directly to the Wynik EMC-LR field set and to per-direction distance/noise/circulator-loss variables.',
            },
            {
                'lines': '598688-598699',
                'raw': [
                    'SELECT DISTINCTROW PRZESLO.[Przęsło#], PRZESLO.Status, ...',
                    'PRZESLO.[Tłumienie cyrkulatorów-n] AS TlumCyrkN',
                    'PRZESLO.[Moc nadajnika] AS Moc',
                    'KONSTRUKCJA.x AS xN, KONSTRUKCJA.y AS yN, KONSTRUKCJA_1.x AS xO, KONSTRUKCJA_1.y AS yO',
                    '[ZASTOSOWANA ANTENA].[Kat wytłumienia ekranu-początkowy] AS KpwNad',
                ],
                'inference': 'Right before the EMC flow Access materializes the same physical inputs we have been reconstructing in EMCInput: transmitter power, circulator loss, geometry, and antenna-screen angles.',
            },
            {
                'lines': '603582-603590',
                'raw': [
                    'ExportTx_przeslo',
                    'ExportRx_przeslo',
                    'wpisz_dane_koor 116878',
                    'kwalifikacja_koor 108355, 0',
                    'Kwalifikacja_EMC 22.3195, 3',
                    'l = Stan_wniosku_po_weryfikacji(29755)',
                ],
                'inference': 'Access runs writer-adjacent qualification after building the EMC payloads, and the second Kwalifikacja_EMC argument looks like a compact class/direction code rather than a raw EMC value.',
            },
        ],
        'parameter_hypotheses': {
            'fid': {
                'most_likely_target': 'Wynik EMC-LR.FKandydujaca_b#',
                'confidence': 'high',
                'why': 'The delete/replace fragment keys directly on FKandydujaca_b# right next to the procedure signature.',
            },
            'idprzesla': {
                'most_likely_target': 'Wynik EMC-LR.Przęsło_i# / prz_s_o_i_id',
                'confidence': 'high',
                'why': 'The field neighborhood places idprzesla immediately next to FKandydujaca_b# and the pairwise result columns.',
            },
            'metoda': {
                'most_likely_target': 'Wynik EMC-LR.metoda',
                'confidence': 'high',
                'why': 'The foreign branch explicitly references metoda=2 right next to the writer; the table contains a metoda column.',
            },
            'blad': {
                'most_likely_target': 'Wynik EMC-LR.blad_obliczen',
                'confidence': 'high',
                'why': 'blad_obliczen appears in the same writer block, and error short-circuiting uses blad/opis_bledu.',
            },
            'opis_bledu': {
                'most_likely_target': 'Wynik EMC-LR.opis_bledu',
                'confidence': 'high',
                'why': 'opis_bledu is threaded through EMC_FS_POL_ZAGR and the writer block and the table stores it verbatim.',
            },
            'dz': {
                'most_likely_target': 'one directional distance column (Odleglosc_b-i or Odleglosc_i-b)',
                'confidence': 'medium',
                'why': 'The writer neighborhood contains distance, dd_n/dd_o, odleglosc_geo_km and the two result distance columns, but no explicit assignment string survived.',
            },
            'marg': {
                'most_likely_target': 'one directional margin column (Margines_b-i or Margines_i-b)',
                'confidence': 'medium',
                'why': 'marg sits directly beside the two margin columns; because the procedure exposes only one marg argument while the table stores two directional margins, one invocation likely writes one side at a time.',
            },
            'wsk': {
                'most_likely_target': 'direction/side selector deciding whether marg/dz land in b-i or i-b',
                'confidence': 'medium',
                'why': 'The signature has no other side-selector input, yet the table distinguishes b-i from i-b. wsk is the cleanest surviving candidate for that choice.',
            },
            'sprz': {
                'most_likely_role': 'auxiliary pairwise relation flag used together with wsk when building the directional writer row',
                'confidence': 'low_to_medium',
                'why': 'sprz is embedded in the same variable cluster as marg/idprzesla/FKandydujaca_b# and the directional columns, but its exact semantics do not survive in strings.',
            },
        },
        'strong_conclusions': [
            'wyniki_EMC_fk is the main terrestrial writer for Wynik EMC-LR, while utworz_wynik_zaklocen belongs to the NSS/satellite branch.',
            'Access appears to write one result row per candidate/interferer pair, replacing any prior row for the same FKandydujaca_b# before inserting/updating the fresh result.',
            'The remaining reverse-engineering gap is not the existence of writer logic, but the exact branch code that maps a computed pairwise case into b-i versus i-b columns.',
            'The nearby SELECT over PRZESLO shows that circulator loss, transmitter power, geometry, and antenna-screen angles are part of the same computational neighborhood as the writer.',
        ],
        'benchmark_context': load_benchmark_residuals(benchmark_csv),
        'tlum_cyrk_distribution': load_tlum_cyrk_summary(sqlite_path),
        'next_best_steps': [
            'Search for call sites of wyniki_EMC_fk with literal wsk values or branch-specific helper names, because that is the shortest path to recovering the b-i versus i-b mapping.',
            'Use the residual permit set (2775, 5092, 3961, 4996, 3840, 1907, 1906, 6071) as the focused benchmark when testing writer-side hypotheses.',
            'Mirror Access domestic input packing more literally around distance/dd_n-dd_o and screen-angle variables before attempting broader EMC changes; TlumCyrk still matters, but its observed values in _349 are usually small.',
        ],
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
