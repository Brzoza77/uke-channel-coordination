#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Document Access/VBA margin-related traces from LR_Konsultacja_349.mdb.")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    payload = {
        "focus": "Margin-related VBA traces around Marg_n, Marg_o, MargNad, MargOdb, N-nad, N-odb.",
        "core_evidence": [
            {
                "lines": "595507-595639",
                "raw": [
                    "jest_wynikN",
                    "jest_wynikO",
                    "statusfk",
                    "Marg_n",
                    "Marg_o",
                    "MargNad",
                    "MargOdb",
                    "N-nad",
                    "N-odb",
                ],
                "inference": "The candidate-level directional margins and counters are present in the same local-variable neighborhood as raw N/O branch margins.",
            },
            {
                "lines": "598767-598806",
                "raw": [
                    "Marg_n oznacza degradację poziomu mocy progowej odbiornika i-tego przęsła",
                    "wyniki_EMC_prz db, filen![przeslo#], Marg_n, dz, file![Przęsło#], 1, 1, blad, \"\", \"POL\"",
                    "Marg_o oznacza degradację poziomu mocy progowej odbiornika i-tego przęsła",
                    "wyniki_EMC_prz db, filen![przeslo#], Marg_o, Dzi, file![Przęsło#], 2, 1, blad, \"\", \"POL\"",
                ],
                "inference": "Access computes explicit N/O branch margins and persists them through the span-level writer wrapper before candidate-level state handling.",
            },
            {
                "lines": "598815-598818",
                "raw": [
                    "aktualizacja parametr",
                    "w fkand",
                    "Czestotliwosc kandydujaca",
                    "[FKandydujaca#] = ...",
                ],
                "inference": "Immediately after the N/O writer calls Access enters a dedicated candidate-update block.",
            },
            {
                "lines": "599245-599246",
                "raw": [
                    "UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].[status] = ...",
                ],
                "inference": "A literal SQL UPDATE is visible for candidate status, but not for MargNad/MargOdb/N-nad/N-odb.",
            },
            {
                "lines": "603528",
                "raw": [
                    "UPDATE [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].T_dane_koor = Null, [Czestotliwosc kandydujaca].R_dane_koor = Null WHERE ...",
                ],
                "inference": "Another literal candidate-table update exists for clearing payloads, which makes the absence of a literal MargNad/MargOdb update even more meaningful.",
            },
        ],
        "negative_evidence": [
            "No direct SQL string was found for UPDATE/SET of [MargNad], [MargOdb], [N-nad], or [N-odb].",
            "No assignment-like string was found in the form MargNad = ... or MargOdb = ...",
            "The only explicit candidate-table SQL updates visible in raw strings target status or T_dane_koor/R_dane_koor.",
        ],
        "strong_conclusions": [
            "Access clearly computes raw branch margins Marg_n and Marg_o.",
            "Access clearly carries candidate-level directional variables MargNad/MargOdb/N-nad/N-odb in the same procedure neighborhood.",
            "The actual write of MargNad/MargOdb/N-nad/N-odb is probably not done through a literal SQL UPDATE embedded as plain text.",
            "The most likely remaining implementation paths are DAO/Recordset field assignments, compiled VBA branches not exposed by strings, or a very short dynamic SQL fragment not recoverable from current raw traces.",
        ],
        "next_best_step": [
            "Search the VBA neighborhood for Recordset/Edit/Update/AddNew traces associated with Czestotliwosc kandydujaca.",
            "Look for shorter dynamic SQL fragments built from concatenated field-name pieces rather than full UPDATE statements.",
            "Keep the current Python fkand-update model, but treat its margin mapping as a structural proxy until a literal write path is recovered.",
        ],
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
