#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Document the Access layer that updates Czestotliwosc kandydujaca between wyniki_EMC_prz and wyniki_EMC_fk.'
    )
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    payload = {
        'focus': 'Bridge layer between span-level N/O EMC branches and candidate-level fkand state updates.',
        'core_evidence': [
            {
                'lines': '595507-595639',
                'raw': [
                    'jest_wynikN',
                    'jest_wynikO',
                    'p_czy_fk',
                    'przeslo_fk',
                    'pol_fk',
                    'f_fk',
                    'statusfk',
                    'Marg_n',
                    'Marg_o',
                    'TlumCyrk_NO',
                    'dd_n',
                    'dd_o',
                    'moc_szumow',
                    'MargNad',
                    'MargOdb',
                    'N-nad',
                    'N-odb',
                ],
                'inference': 'The local variable block mixes raw N/O EMC branches with candidate-level directional fields, which points to an intermediate update layer rather than a direct write from Marg_n/Marg_o to Wynik EMC-LR columns.',
            },
            {
                'lines': '598658-598661',
                'raw': [
                    'FID - identyfikator fkand lub zero(null) dla przesla',
                    'metoda - zMCT lub bez MCT',
                    'p_czy_fk = 0 dla przęsła',
                    'p_czy_fk = 1 dla fkand',
                ],
                'inference': 'Access reuses one shared routine for both span-level and candidate-level paths. The missing layer is therefore likely procedural and stateful, not just a static query mapping.',
            },
            {
                'lines': '598767-598806',
                'raw': [
                    'wyniki_EMC_prz db, filen![przeslo#], Marg_n, dz, file![Przęsło#], 1, 1, blad, "", "POL"',
                    'wyniki_EMC_prz db, filen![przeslo#], Marg_o, Dzi, file![Przęsło#], 2, 1, blad, "", "POL"',
                ],
                'inference': 'The span-level writer is fed by two directional N/O branches before candidate-level processing happens.',
            },
            {
                'lines': '598815-598820',
                'raw': [
                    'aktualizacja parametr',
                    'w fkand',
                    'Czestotliwosc kandydujaca',
                    '[FKandydujaca#] =',
                ],
                'inference': 'Immediately after the N/O writer calls, Access enters an explicit fkand update block. This is the strongest evidence for the missing bridge layer.',
            },
            {
                'lines': '598827-598871',
                'raw': [
                    'SELECT PRZESLO.[Przęsło#], PRZESLO.T_dane_koor, PRZESLO.R_dane_koor, PRZESLO.[Czestotliwosc przydzielona], SYGNAL.[Szerokość], PRZESLO.[Polaryzacja], PRZESLO.[Status koordynacji], ...',
                    '... INNER JOIN Problem ON PRZESLO.[Przęsło#] = Problem.[Przęsło#] ...',
                    'Dane_do_EMC_BENNER',
                ],
                'inference': 'The bridge layer refreshes domestic span context and problem metadata while updating the candidate record. This suggests MargNad/MargOdb and coordination counters are populated from grouped branch results plus Problem state.',
            },
            {
                'lines': '599424-599430',
                'raw': [
                    'Sub wyniki_EMC_fk(db, fid As Long, marg As Variant, dz As Double, idprzesla As Long, wsk As Byte, metoda As Byte, blad As Long, opis_bledu As String)',
                    'Wynik EMC-LR',
                ],
                'inference': 'The candidate-level writer appears after the fkand update evidence, which supports a staged flow: N/O branch -> fkand update -> candidate writer.',
            },
            {
                'lines': '599458-599462',
                'raw': [
                    'UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].[status] = ...',
                ],
                'inference': 'Status is updated in the same broader procedural neighborhood as the fkand field update logic.',
            },
        ],
        'reconstructed_flow': [
            'Compute raw domestic N/O branch results (Marg_n, dz) and (Marg_o, Dzi).',
            'Persist span-level results through wyniki_EMC_prz with wsk=1/2 and metoda=1.',
            'Enter explicit "aktualizacja parametr w fkand" block for the current FKandydujaca#.',
            'Reload domestic PRZESLO/Problem context and EMC payload-related fields.',
            'Populate or refresh candidate-level directional fields such as MargNad, MargOdb, N-nad, N-odb.',
            'Apply candidate-level status update and then write candidate EMC rows through wyniki_EMC_fk.',
        ],
        'strong_conclusions': [
            'The unresolved layer is not a simple b-i/i-b label flip.',
            'It is a procedural candidate-update stage that aggregates N/O branch results into fkand directional fields before final candidate-row writing.',
            'MargNad/MargOdb and N-nad/N-odb are likely the key state variables produced by this bridge layer.',
            'Any faithful Access-like model should represent this as a separate stage between pairwise branch computation and final result/report projection.',
        ],
        'next_best_step': [
            'Model an explicit fkand update stage in Python using grouped N/O branch results.',
            'Compare inferred Access-like MargNad/MargOdb against current uke_like_margnad_db / uke_like_margodb_db on the benchmark case.',
            'Continue searching VBA context for the exact update statement that writes MargNad, MargOdb, N-nad, and N-odb.',
        ],
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
