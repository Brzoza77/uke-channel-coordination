#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Summarize reconstructed candidate state flow from Access VBA traces.')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    payload = {
        'evidence_blocks': [
            {
                'source': 'strings(LR_Konsultacja_349.mdb)',
                'lines': '596872-596879',
                'raw': [
                    'Set db = DBEngine.Workspaces(0).Databases(0)',
                    'Plan zakresu',
                    'Wybierz plan zakresu',
                    'par1',
                    'par2',
                    'DobryKanal = "0"',
                    'utworzenie fkand',
                ],
                'meaning': 'Before EMC and final status updates, Access appears to initialize a separate candidate goodness flag (DobryKanal) while creating candidate rows.',
            },
            {
                'source': 'strings(LR_Konsultacja_349.mdb)',
                'lines': '598632-598636',
                'raw': [
                    'pom = DLookup("[problem#]", "Problem_kons", "[przeslo#]=" & idp)',
                    'If Not IsNull(pom) Then',
                    ' obliczenia_EMC_POL_ZAGR dbb, fid(i), idp, blad, opis_bledu, status_fkand_zagr',
                    ' If status_fkand_zagr = 2 Then status_fkand = 2',
                    ' If blad > 0 Then Koniec_obliczen dbb, fid(i), status_fkand: Exit Function',
                ],
                'meaning': 'Foreign/problem branch can promote the candidate from default status to status 2 and terminate early on fatal error.',
            },
            {
                'source': 'strings(LR_Konsultacja_349.mdb)',
                'lines': '598641-598654',
                'raw': [
                    'SELECT Problem.[Przeslo#], Problem.[TD p-p], Problem.decyzja_o_koordynacji',
                    'WHERE Problem.[TD p-p] > 1',
                    'UPDATE Problem SET Problem.decyzja_o_koordynacji = IIf([d11] > [dgr],1,2)',
                    'SELECT Problem.[Przeslo#], Problem.decyzja_o_koordynacji',
                    'WHERE Problem.decyzja_o_koordynacji = 1',
                ],
                'meaning': 'Access keeps a separate coordination-decision state inside Problem, distinct from the final candidate status in Czestotliwosc kandydujaca.',
            },
            {
                'source': 'strings(LR_Konsultacja_349.mdb)',
                'lines': '598675-598679',
                'raw': [
                    'statusfk = 1',
                    'otwarcie tabel: Nadajnik,maski,charakterystyka',
                    'Nadajnik',
                    'Nadajnik_kons',
                ],
                'meaning': 'Candidate flow initializes status to 1 before opening radio/mask/antenna resources.',
            },
            {
                'source': 'strings(LR_Konsultacja_349.mdb)',
                'lines': '599237-599246',
                'raw': [
                    'zap_char_LR("identyf_uklad_pol") = 1',
                    'za mała liczba punktów na charakterystyce lub brak charakterystyki',
                    'wyprowadzić jako komunikat błędu do struktury wynikowej',
                    'UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].[status] =',
                    'WHERE ((([Czestotliwosc kandydujaca].[FKandydujaca#])=',
                ],
                'meaning': 'Access performs procedural UPDATE of candidate status near characteristic validation and error-message handling.',
            },
            {
                'source': 'strings(LR_Konsultacja_349.mdb)',
                'lines': '603539-603590',
                'raw': [
                    'td_n = Oblicz_TD(...)',
                    'If td_n > 1 Then',
                    'problem = True',
                    'td_o = Oblicz_TD(...)',
                    'If td_o > 1 Then',
                    'problem = True',
                    'If problem Then filepk.AddNew ... filepk![FKandydujaca#] = fid ... Mid(stat_koor, 2, 1) = "B"',
                    'ExportTx_przeslo',
                    'ExportRx_przeslo',
                    'wpisz_dane_koor',
                    'kwalifikacja_koor',
                    'Kwalifikacja_EMC',
                    'Stan_wniosku_po_weryfikacji',
                ],
                'meaning': 'Domestic/problem branch writes problem records, exports coordination payloads, then runs qualification/verification stages before final state is settled.',
            },
            {
                'source': 'strings(LR_Konsultacja_349.mdb)',
                'lines': '595858-595862',
                'raw': [
                    'wstaw_status',
                    'obliczenia_EMC_POL_ZAGR',
                    'status_kand',
                ],
                'meaning': 'There is likely a dedicated helper routine for writing candidate status, adjacent to the foreign EMC branch.',
            },
        ],
        'confirmed_traces': [
            'statusfk = 1',
            'If status_fkand_zagr = 2 Then status_fkand = 2',
            'If blad > 0 Then Koniec_obliczen dbb, fid(i), status_fkand: Exit Function',
            'If problem Then filepk.AddNew ... filepk![FKandydujaca#] = fid ... Mid(stat_koor, 2, 1) = "B"',
            'ExportTx_przeslo',
            'ExportRx_przeslo',
            'wpisz_dane_koor',
            'kwalifikacja_koor',
            'Kwalifikacja_EMC',
            'Stan_wniosku_po_weryfikacji',
            'UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [status] = ... WHERE [FKandydujaca#] = ...',
        ],
        'reconstructed_flow': [
            {
                'step': 1,
                'description': 'Candidate creation initializes a separate goodness flag (DobryKanal = "0"), then the procedural status pipeline initializes statusfk = 1.',
            },
            {
                'step': 2,
                'description': 'Problem branches are evaluated. For the foreign branch, obliczenia_EMC_POL_ZAGR can raise status_fkand_zagr to 2, which propagates to status_fkand = 2.',
            },
            {
                'step': 3,
                'description': 'When a country/problem conflict is found, Access writes a problem_kons record, marks stat_koor via Mid(stat_koor, 2, 1) = "B", and maintains a separate Problem.decyzja_o_koordynacji state derived from D11 versus Dgr.',
            },
            {
                'step': 4,
                'description': 'Access exports Tx/Rx payloads (ExportTx_przeslo / ExportRx_przeslo) and writes coordination data via wpisz_dane_koor.',
            },
            {
                'step': 5,
                'description': 'Access runs qualification stages: kwalifikacja_koor, Kwalifikacja_EMC, Stan_wniosku_po_weryfikacji.',
            },
            {
                'step': 6,
                'description': 'At the end of the procedural flow, VBA performs UPDATE on Czestotliwosc kandydujaca.status for the selected FKandydujaca#; the nearby identifiers wstaw_status and status_kand strongly suggest a dedicated setter/helper routine.',
            },
            {
                'step': 7,
                'description': 'The print layer later consumes Status = 2 via Wyniki_do_wydruku.',
            },
        ],
        'inference': {
            'strong': [
                'Status = 2 is not computed solely from a saved query; it is the outcome of a procedural VBA pipeline.',
                'The final value depends on at least: problem detection, foreign-branch EMC, coordination payload generation, qualification, and end-of-flow verification.',
                'The procedural flow has two visible status phases: default initialization to 1 and later promotion/update to 2 for report-selected candidates.',
                'Access couples candidate status updates with data-quality checks for antenna characteristics and with coordination/problem bookkeeping.',
                'Access tracks more than one kind of state: a pre-EMC candidate flag (DobryKanal), problem-level coordination decisions, and the final candidate Status written back to Czestotliwosc kandydujaca.',
            ],
            'not_yet_proven': [
                'Exact semantic meaning of each status code beyond the evidence for 1 as initial/default and 2 as promoted/report-selected.',
                'Whether a pure domestic terrestrial branch can also promote statusfk to 2 independently of the foreign branch.',
                'Exact implementation of Koniec_obliczen and Stan_wniosku_po_weryfikacji.',
                'Whether wstaw_status is the sole writer of candidate status or only one helper used by a larger routine.',
                'Whether DobryKanal is later promoted from 0 to 1 and, if so, whether that promotion feeds directly into final Status.',
            ],
        },
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
