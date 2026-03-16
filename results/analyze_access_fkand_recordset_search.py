#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Document narrow Recordset/Edit/Update search around Access fkand margin updates.")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    payload = {
        "focus": "Narrow search for DAO Recordset/Edit/Update traces that could write MargNad/MargOdb/N-nad/N-odb.",
        "positive_hits": [
            {
                "lines": "603570-603578",
                "raw": [
                    "filepk.AddNew",
                    "filepk![przeslo#] = filep![przeslo#]",
                    "filepk![FKandydujaca#] = fid",
                    "filepk!Kraj = filek!Kraj",
                    "filepk![Tx\\Rx] = \"Rx\"",
                    "filepk![D11] = D11_Rx",
                    "filepk![Dgr] = D_rx_gr",
                    "filepk![TD p-gr] = td_o",
                    "filepk.Update",
                ],
                "inference": "Confirmed Recordset write path for problem_kons-like coordination problem records, not for candidate margin fields.",
            },
            {
                "lines": "604388-604406",
                "raw": [
                    "If Not IsNull(maska(i, 1)) Then",
                    "wpis_maski file, maska, ilk, i",
                    "file.Update",
                    "Else",
                    "file.Update",
                    "wpisz_blad blad, 0, \"Brak maski nadajnika ...\"",
                ],
                "inference": "Confirmed Recordset update path while preparing transmitter mask / Dane_EMC-side data, again not the fkand directional margins.",
            },
            {
                "lines": "598815-598818",
                "raw": [
                    "aktualizacja parametr",
                    "w fkand",
                    "Czestotliwosc kandydujaca",
                    "[FKandydujaca#] = ...",
                ],
                "inference": "Strong procedural marker for the missing fkand update layer, but no direct Recordset field assignment is visible in current raw traces.",
            },
        ],
        "negative_hits": [
            "No narrow Recordset/Edit/Update context was recovered that explicitly assigns file![MargNad], file![MargOdb], file![N-nad], or file![N-odb].",
            "No FindFirst/NoMatch context around Czestotliwosc kandydujaca exposed a visible subsequent field assignment for margin fields.",
            "The strongest narrow procedural traces still separate into three groups: fkand marker block, problem_kons writes, and Dane_EMC/mask writes.",
        ],
        "strong_conclusions": [
            "The search confirms that Access does use DAO Recordset persistence in the same general workflow area.",
            "However, the recovered Recordset writes currently belong to adjacent tables, not to a visible candidate-margin write for Czestotliwosc kandydujaca.",
            "The fkand margin setter is therefore still hidden behind either an unrecovered Recordset branch, a shorter dynamic SQL fragment, or compiled VBA content not surfaced by the current string extraction.",
        ],
        "next_best_step": [
            "Keep searching specifically for file!/filen! assignments in the immediate neighborhood after the 'aktualizacja parametr w fkand' marker.",
            "Search for DAO object names besides file/filepk that may point to a fkand-specific Recordset variable.",
            "Treat the current Python fkand-update stage as a structural proxy until the literal setter is recovered.",
        ],
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
