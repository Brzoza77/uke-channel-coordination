#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Summarize VBA/string traces related to candidate status assignment in MDB.')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    findings = {
        'confirmed_traces': [
            'UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].[status] = ... WHERE ((([Czestotliwosc kandydujaca].[FKandydujaca#])= ...',
            'strpyt = "UPDATE [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].T_dane_koor = Null, [Czestotliwosc kandydujaca].R_dane_koor = Null WHERE ((([Czestotliwosc kandydujaca].[FKandydujaca#])=" & fid & "));"',
            'Sub wyniki_EMC_fk(db, fid As Long, marg As Variant, dz As Double, idprzesla As Long, wsk As Byte, metoda As Byte, blad As Long, opis_bledu As String)',
            'Set dbb = CurrentDb',
            'QueryDef / OpenRecordset / CurrentProject.Path / Zadania_LR traces are present in the MDB strings',
        ],
        'contextual_traces': [
            'The status update trace appears next to code handling antenna characteristic lookup and validation.',
            'Nearby strings mention: brak charakterystyki, za mała liczba punktów na charakterystyce, kod_polaryzacji = 5.',
            'Nearby strings also include dynamic SELECTs over CHARAKTERYSTYKA_kons for both Antena_nad and Antena_odb.',
            'This strongly suggests candidate status can be modified from VBA after validating whether required antenna characteristics exist for the EMC run.',
        ],
        'strong_inference': [
            'Candidate Status is not just a passive field consumed by print queries; it is actively updated from VBA.',
            'The final selection/print path likely depends on a procedural pass that prepares EMC payloads, validates supporting characteristics, runs EMC, then updates candidate status.',
            'Modules such as Zadania_LR / Master remain the most likely container of the complete orchestration logic.',
        ],
        'what_this_changes': [
            'We no longer need to assume Status = 2 is assigned by a hidden saved query.',
            'To fully mirror Access final candidate selection, we need either the VBA source itself or a reliable reconstruction of the procedural logic around wyniki_EMC_fk and related routines.',
        ],
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
