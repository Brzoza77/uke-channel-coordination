#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from analyze_emc_coord_payload import parse_payload


def _load_querydefs(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    return {q['name']: q for q in payload.get('query_inventory', {}).get('querydefs', [])}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _noise_floor_dbw_from_nf(channel_width_mhz: float | None, noise_figure_db: float | None) -> float | None:
    if channel_width_mhz is None or noise_figure_db is None or channel_width_mhz <= 0:
        return None
    noise_dbm = -174.0 + 10.0 * math.log10(channel_width_mhz * 1_000_000.0) + noise_figure_db
    return noise_dbm - 30.0


def _sample_candidate_rows(con: sqlite3.Connection) -> list[dict[str, Any]]:
    con.row_factory = sqlite3.Row
    rows = con.execute(
        '''
        SELECT
            c.fkandydujaca_id,
            c.prz_s_o_id,
            c.numer_przesla,
            c.numer_pary_f,
            c.plan,
            c.numer_czestotliwosci,
            c.kod_nadawczej,
            c.polaryzacja,
            c.wartosc_czestotliwosci,
            c.status,
            c.margnad,
            c.margodb,
            c.t_dane_koor,
            c.r_dane_koor,
            d.kierpromn,
            d.kierpromo,
            d.katelewn,
            d.katelewo,
            d.szerokosc_kanalu,
            d.liczba_szumowa,
            d.moc_nadajnika,
            d.tlum_cyrk_n,
            d.tlum_cyrk_o,
            d.zysk_ant_n,
            d.zysk_ant_o,
            d.nadajnik,
            d.antena_nad,
            d.antena_odb
        FROM lr_konsultacja_349__czestotliwosc_kandydujaca c
        JOIN lr_konsultacja_349__dane_emc d ON d.przeslo_id = c.prz_s_o_id
        ORDER BY c.fkandydujaca_id
        '''
    ).fetchall()
    decoded: list[dict[str, Any]] = []
    for row in rows:
        tx = parse_payload(row['t_dane_koor'], 'tx')
        rx = parse_payload(row['r_dane_koor'], 'rx')
        expected_noise_floor = _noise_floor_dbw_from_nf(_to_float(row['szerokosc_kanalu']), _to_float(row['liczba_szumowa']))
        decoded.append(
            {
                'fkandydujaca_id': row['fkandydujaca_id'],
                'przeslo_id': row['prz_s_o_id'],
                'numer_przesla': row['numer_przesla'],
                'numer_pary_f': row['numer_pary_f'],
                'plan': row['plan'],
                'channel': row['numer_czestotliwosci'],
                'kod_nadawczej': row['kod_nadawczej'],
                'polaryzacja': row['polaryzacja'],
                'status': row['status'],
                'margnad': row['margnad'],
                'margodb': row['margodb'],
                'payload_matches': {
                    'tx_main_azimuth_payload_deg': tx['main_azimuth_deg_num'],
                    'tx_main_azimuth_dane_emc_deg': _to_float(row['kierpromn']),
                    'rx_main_azimuth_payload_deg': rx['main_azimuth_deg_num'],
                    'rx_main_azimuth_dane_emc_deg': _to_float(row['kierpromo']),
                    'tx_main_elevation_payload_deg': tx['main_elevation_deg_num'],
                    'tx_main_elevation_dane_emc_deg': _to_float(row['katelewn']),
                    'rx_main_elevation_payload_deg': rx['main_elevation_deg_num'],
                    'rx_main_elevation_dane_emc_deg': _to_float(row['katelewo']),
                    'tx_power_dbw_payload': tx['tx_power_dbw_num'],
                    'tx_power_dbw_expected_from_dane_emc': (_to_float(row['moc_nadajnika']) - 30.0) if _to_float(row['moc_nadajnika']) is not None else None,
                    'noise_floor_dbw_payload': rx['noise_floor_dbw_num'],
                    'noise_floor_dbw_expected_from_nf': expected_noise_floor,
                    'tx_circulator_payload_db': tx['circulator_loss_db_num'],
                    'tx_circulator_dane_emc_db': _to_float(row['tlum_cyrk_n']),
                    'rx_circulator_payload_db': rx['circulator_loss_db_num'],
                    'rx_circulator_dane_emc_db': _to_float(row['tlum_cyrk_o']),
                    'mask_pairs_payload': tx['radio_mask_pairs'],
                },
                'payload_summary': {
                    'tx_station_label': tx['station_label'],
                    'rx_station_label': rx['station_label'],
                    'radio_vendor': tx['radio_vendor'],
                    'radio_type': tx['radio_type'],
                    'antenna_vendor': tx['antenna_vendor'],
                    'antenna_type': tx['antenna_type'],
                    'antenna_gain_dbi': tx['antenna_gain_dbi_num'],
                    'tx_copol_count': tx['copol_pattern']['count'],
                    'tx_crosspol_count': tx['crosspol_pattern']['count'],
                },
            }
        )
    return decoded


def _sample_result_rows(con: sqlite3.Connection) -> list[dict[str, Any]]:
    con.row_factory = sqlite3.Row
    rows = con.execute(
        '''
        SELECT
            w.fkandydujaca_b_id,
            w.prz_s_o_i_id,
            w.metoda,
            w.odleglosc_b_i,
            w.odleglosc_i_b,
            w.margines_b_i,
            w.margines_i_b,
            w.blad_obliczen,
            w.opis_bledu,
            c.prz_s_o_id AS candidate_przeslo_id,
            c.numer_czestotliwosci,
            c.plan,
            c.kod_nadawczej,
            c.status,
            c.margnad,
            c.margodb
        FROM lr_konsultacja_349__wynik_emc_lr w
        JOIN lr_konsultacja_349__czestotliwosc_kandydujaca c ON c.fkandydujaca_id = w.fkandydujaca_b_id
        ORDER BY w.fkandydujaca_b_id, w.prz_s_o_i_id
        '''
    ).fetchall()
    return [dict(r) for r in rows]


def _query_summary(querydefs: dict[str, Any], name: str) -> dict[str, Any]:
    q = querydefs.get(name, {})
    return {
        'name': name,
        'sources': q.get('sources', []),
        'joins': q.get('joins', []),
        'filters': q.get('filters', []),
        'selected_fields': q.get('selected_fields', [])[:30],
        'other_rows': q.get('other_rows', [])[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Reconstruct end-to-end Access EMC query flow from inventory + sqlite.')
    parser.add_argument('--sqlite', default='data/uke_workflow.sqlite')
    parser.add_argument('--querydefs-json', default='logs/access_querydefs_inventory_20260316.json')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).resolve()
    querydefs_path = Path(args.querydefs_json).resolve()
    querydefs = _load_querydefs(querydefs_path)

    con = sqlite3.connect(sqlite_path)
    try:
        candidate_rows = _sample_candidate_rows(con)
        result_rows = _sample_result_rows(con)
    finally:
        con.close()

    flow = [
        {
            'step': 1,
            'query': 'jest_nadajnik_w_bazie',
            'purpose': 'Access matches request-side radio by type, producer, frequency range and channel-width range.',
            'evidence': _query_summary(querydefs, 'jest_nadajnik_w_bazie'),
        },
        {
            'step': 2,
            'query': 'Dane_EMC_druk',
            'purpose': 'Access enriches Dane_EMC with consultation snapshots of radio, antenna and producer.',
            'evidence': _query_summary(querydefs, 'Dane_EMC_druk'),
        },
        {
            'step': 3,
            'query': 'ExportTx_przeslo / ExportRx_przeslo',
            'purpose': 'Access serializes Tx/Rx EMC payloads; these payloads include azimuth, elevation, mask pairs, radio and antenna metadata.',
            'evidence': {
                'ExportTx_przeslo': _query_summary(querydefs, 'ExportTx_przeslo'),
                'ExportRx_przeslo': _query_summary(querydefs, 'ExportRx_przeslo'),
            },
        },
        {
            'step': 4,
            'query': 'Czestotliwosc kandydujaca',
            'purpose': 'Candidate records carry T_dane_koor and R_dane_koor plus candidate-side status and directional margins (MargNad / MargOdb).',
            'evidence': {
                'table': 'lr_konsultacja_349__czestotliwosc_kandydujaca',
                'sample_rows': candidate_rows,
            },
        },
        {
            'step': 5,
            'query': 'Dane_do_EMC_BENNER',
            'purpose': 'Access joins candidate records with Dane_EMC on Przeslo# to prepare EMC execution for a selected FKandydujaca#.',
            'evidence': _query_summary(querydefs, 'Dane_do_EMC_BENNER'),
        },
        {
            'step': 6,
            'query': 'Wynik EMC-LR',
            'purpose': 'EMC engine stores pairwise margins per candidate and interfering span.',
            'evidence': {
                'table': 'lr_konsultacja_349__wynik_emc_lr',
                'sample_rows': result_rows,
            },
        },
        {
            'step': 7,
            'query': 'Wyniki_b-i / Wyniki_i-b',
            'purpose': 'Access builds DOC-visible conflict rows by filtering Wynik EMC-LR to positive margins and metoda < 2, then joins permit/station/operator metadata.',
            'evidence': {
                'Wyniki_b-i': _query_summary(querydefs, 'Wyniki_b-i'),
                'Wyniki_i-b': _query_summary(querydefs, 'Wyniki_i-b'),
            },
        },
        {
            'step': 8,
            'query': 'Wyniki_do_wydruku',
            'purpose': 'Access selects candidate rows for printing from Czestotliwosc kandydujaca using Numer_przesla and Status=2.',
            'evidence': _query_summary(querydefs, 'Wyniki_do_wydruku'),
        },
        {
            'step': 9,
            'query': 'Pary_fk_ABprim / Pary_fk_AprimB',
            'purpose': 'Access pairs A/B directional candidates into duplex channels by apostrophe convention and shared polarization/span.',
            'evidence': {
                'Pary_fk_ABprim': _query_summary(querydefs, 'Pary_fk_ABprim'),
                'Pary_fk_AprimB': _query_summary(querydefs, 'Pary_fk_AprimB'),
            },
        },
    ]

    payload_findings = {
        'confirmed_equalities': [
            'payload main azimuth ~= Dane_EMC.KierPromN/O',
            'payload main elevation ~= Dane_EMC.KatElewN/O',
            'payload tx_power_dbw = Dane_EMC.Moc_nadajnika - 30',
            'payload noise_floor_dbw = -174 dBm/Hz + 10log10(BW_Hz) + NF, then converted to dBW',
            'payload circulator loss mirrors Dane_EMC.Tlum_cyrk_N/O',
        ],
        'current_implication_for_engine': [
            'Our EMCInput should keep azimuth and elevation explicitly.',
            'Using azimuth/elevation as observability is already correct.',
            'We do not yet have evidence that Access applies an extra 3D-only discrimination on top of antenna pattern lookup.',
        ],
    }

    open_questions = [
        'What exact semantics does Access assign to candidate Status values (not just printed Status=2)?',
        'How does the external EMC executable populate Wynik EMC-LR for dense terrestrial cases beyond the small stored sample?',
        'Which rule maps Wyniki_b-i / Wyniki_i-b rows to the exact DOC row orientation for mixed direct/cross cases?',
    ]

    payload = {
        'sqlite': str(sqlite_path),
        'querydefs_json': str(querydefs_path),
        'flow': flow,
        'payload_findings': payload_findings,
        'open_questions': open_questions,
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
