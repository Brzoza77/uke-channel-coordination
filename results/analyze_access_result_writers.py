#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Summarize Access result-writer routines from string traces and benchmark residuals.')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    payload = {
        'evidence': [
            {
                'procedure': 'utworz_wynik_zaklocen',
                'lines': '599165-599177',
                'raw': [
                    'Public Sub utworz_wynik_zaklocen(stacja_NS As Variant, Lokalizacja As Variant, Kanal As Variant, stacja_LR As Variant, Przeslo As Variant, ...)',
                    'zapis do bazy wyników zakłóceń przy obliczeniach kompatybilności pojedynczej NSS i stacji linii radiowych',
                    'stacja linii radiowych jest w bazie danych satelitarnych w tabeli stacja_LR',
                    'zapisz_dane_o_zakloceniu ...',
                ],
                'inference': 'This routine is not the main terrestrial LR pairwise writer for our benchmark; it belongs to the NSS/satellite interference reporting path.',
            },
            {
                'procedure': 'wyniki_EMC_fk',
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
                'inference': 'This looks like the actual writer for pairwise EMC records into Wynik EMC-LR, including method branch, mask/radio lookup failure paths, and one-record-per-candidate/result logic.',
            },
        ],
        'best_benchmark_focus': {
            'source': 'logs/BT10561C-BT10853C-001_0_20260312114554_degradation_gap_summary_internal349_mapped_rowexact_ipasolink.json',
            'overall_victim_mae_db': 2.066108,
            'overall_victim_rmse_db': 2.92936,
            'top_residual_permits': [
                '2775.2024.2',
                '5092.2022.2',
                '3961.2023.2',
                '4996.2016.6',
                '3840.2017.6',
                '1907.2022.2',
                '1906.2022.2',
                '6071.2024.2',
            ],
        },
        'strong_conclusions': [
            'The main remaining reverse-engineering target is wyniki_EMC_fk, not utworz_wynik_zaklocen.',
            'The parameter set of wyniki_EMC_fk strongly suggests that Access writes one computed EMC result per candidate/interferer branch, with explicit method and error handling.',
            'Because mask/radio failure strings appear inside the same routine, some residuals may still come from branch-specific handling of NFD/MD and missing-profile fallback inside the Access writer path.',
        ],
        'next_best_step': [
            'Reconstruct the semantic meaning of wyniki_EMC_fk arguments: marg, dz, wsk, metoda, blad, opis_bledu.',
            'Compare our per-subcase values against benchmark residual permits to infer which subcase likely feeds marg in the Access writer.',
            'Treat utworz_wynik_zaklocen as a secondary branch for NSS/satellite reporting, not as the main terrestrial benchmark target.',
        ],
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
