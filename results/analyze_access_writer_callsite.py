#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Document Access writer call-site evidence around wyniki_EMC_prz and wyniki_EMC_fk.')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    payload = {
        'core_evidence': [
            {
                'lines': '598767-598776',
                'raw': [
                    'Marg_n oznacza degradację poziomu mocy progowej odbiornika i-tego przęsła',
                    'Marg_n = TlumNaPrzeszk ...',
                    'wyniki_EMC_prz db, filen![przeslo#], Marg_n, dz, file![Przęsło#], 1, 1, blad, "", "POL"',
                ],
                'inference': 'The writer wrapper uses literal wsk=1 and metoda=1 for the Marg_n / dz branch.',
            },
            {
                'lines': '598798-598806',
                'raw': [
                    'Marg_o oznacza degradację poziomu mocy progowej odbiornika i-tego przęsła',
                    'Marg_o = TlumNaPrzeszk ...',
                    'wyniki_EMC_prz db, filen![przeslo#], Marg_o, Dzi, file![Przęsło#], 2, 1, blad, "", "POL"',
                ],
                'inference': 'The writer wrapper uses literal wsk=2 and metoda=1 for the Marg_o / Dzi branch.',
            },
            {
                'lines': '599423-599430',
                'raw': [
                    'Sub wyniki_EMC_fk(db, fid As Long, marg As Variant, dz As Double, idprzesla As Long, wsk As Byte, metoda As Byte, blad As Long, opis_bledu As String)',
                    'FKandydujaca_b#',
                    'Wynik EMC-LR',
                    'and metoda=2',
                ],
                'inference': 'wyniki_EMC_fk is the candidate-level writer, and wyniki_EMC_prz is very likely a closely related wrapper for span-level writes with the same wsk/metoda convention.',
            },
            {
                'lines': '595528-595559',
                'raw': [
                    'p_czy_fk',
                    'przeslo_fk',
                    'pol_fk',
                    'f_fk',
                    'statusfk',
                    'wspspecjalny',
                    'Marg_n',
                    'Marg_o',
                    'TlumCyrk_NO',
                    'dd_n',
                    'dd_o',
                    'wsp_szum_i',
                    'moc_szumow',
                ],
                'inference': 'The local variable neighborhood strongly suggests a shared writer-adjacent routine that handles both span-level and candidate-level results, with explicit direction-specific margin and distance branches.',
            },
        ],
        'strong_conclusions': [
            'wsk is no longer just a hypothesis: the wrapper call site shows literal values 1 and 2.',
            'metoda=1 is the domestic path at the writer wrapper level; metoda=2 remains the foreign branch seen near wyniki_EMC_fk.',
            'The remaining gap is specifically mapping Marg_n/Marg_o (and dz/Dzi) onto Wynik EMC-LR columns b-i vs i-b.',
            'Because the call site still writes through wyniki_EMC_prz rather than directly through wyniki_EMC_fk, there is probably one more thin wrapper layer between branch computation and final candidate-row persistence.',
        ],
        'next_best_step': [
            'Search for call-site or wrapper evidence tying Marg_n/Marg_o to Odleglosc_b-i/Margines_b-i vs Odleglosc_i-b/Margines_i-b.',
            'Check whether the N/O branch names align with site labels or request directions in the residual permit set.',
            'Once that mapping is stable, extend the writer projection layer with explicit wsk=1/2 and writer-column targeting.',
        ],
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
