#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Evaluate writer-side hypotheses for Access wyniki_EMC_prz / wyniki_EMC_fk flow.')
    parser.add_argument('--writer-csv', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    writer_csv = Path(args.writer_csv).resolve()
    out_path = Path(args.out).resolve()

    rows = []
    with writer_csv.open(encoding='utf-8', newline='') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(row)

    current_side_counts = Counter(row.get('engine_writer_projection_side', '') for row in rows if row.get('engine_writer_projection_side'))
    current_case_counts = Counter(row.get('engine_writer_projection_case_key', '') for row in rows if row.get('engine_writer_projection_case_key'))

    payload = {
        'source_csv': str(writer_csv),
        'rows_total': len(rows),
        'current_projection_side_counts': dict(current_side_counts),
        'current_projection_case_key_counts_top': current_case_counts.most_common(12),
        'tested_hypotheses': [
            {
                'id': 'H1',
                'description': 'wsk=1 writes b-i, wsk=2 writes i-b',
                'status': 'not_supported',
                'why': [
                    'The call-site text says both Marg_n and Marg_o are degradations of the receiver of the i-th span (przęsło i), not two different writer-table families.',
                    'At the current stage, flipping only the side label does not change the benchmark numerically; the unresolved issue is earlier, in mapping N/O subbranches onto writer columns.',
                ],
            },
            {
                'id': 'H2',
                'description': 'wsk=1 writes i-b, wsk=2 writes b-i',
                'status': 'not_supported',
                'why': [
                    'This reverse mapping has the same weakness as H1: it treats wsk as a direct final-column selector, while the surviving strings describe N/O degradation of the i-th span receiver.',
                    'With the current projection layer, H1 and H2 are numerically indistinguishable because the writer value stays the same and only the side label flips.',
                ],
            },
            {
                'id': 'H3',
                'description': 'wsk=1 and wsk=2 select N/O subbranches inside the writer flow; final b-i vs i-b mapping happens one layer later or through aggregation',
                'status': 'best_supported',
                'why': [
                    'The wrapper call sites are explicit: Marg_n with wsk=1, Marg_o with wsk=2.',
                    'Both Marg_n and Marg_o are described as degradation of the receiver of the i-th span, which fits subbranch selection better than direct final-column selection.',
                    'wyniki_EMC_prz looks like a thin wrapper, while wyniki_EMC_fk is the candidate-level writer to Wynik EMC-LR; this suggests one more translation layer between N/O branches and final b-i/i-b columns.',
                ],
            },
        ],
        'key_evidence': [
            'wyniki_EMC_prz db, filen![przeslo#], Marg_n, dz, file![Przęsło#], 1, 1, blad, "", "POL"',
            'wyniki_EMC_prz db, filen![przeslo#], Marg_o, Dzi, file![Przęsło#], 2, 1, blad, "", "POL"',
            'Marg_n oznacza degradację poziomu mocy progowej odbiornika i-tego przęsła',
            'Marg_o oznacza degradację poziomu mocy progowej odbiornika i-tego przęsła',
            'Sub wyniki_EMC_fk(db, fid As Long, marg As Variant, dz As Double, idprzesla As Long, wsk As Byte, metoda As Byte, blad As Long, opis_bledu As String)',
        ],
        'practical_conclusion': 'The next useful test is not another pure side-label swap. We need to map Marg_n/Marg_o (and dz/Dzi) onto final writer columns by finding the wrapper/aggregation layer between wyniki_EMC_prz and wyniki_EMC_fk.',
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
