#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parent.parent
MDB_PATH = REPO_ROOT / "LR_Konsultacja_349.mdb"
OUTPUT_PATH = REPO_ROOT / "logs" / "access_fkand_aggregation_20260316.json"


def collect_strings_with_offsets() -> list[tuple[int, str]]:
    proc = subprocess.run(
        ["strings", "-t", "d", str(MDB_PATH)],
        capture_output=True,
        text=True,
        check=True,
    )
    rows = []
    for raw in proc.stdout.splitlines():
        parts = raw.split(" ", 1)
        if len(parts) != 2:
            continue
        try:
            offset = int(parts[0])
        except ValueError:
            continue
        rows.append((offset, parts[1].lstrip()))
    return rows


def first(entries: list[tuple[int, str]], needle: str) -> dict | None:
    for offset, text in entries:
        if needle in text:
            return {"offset": offset, "text": text}
    return None


def window(entries: list[tuple[int, str]], start: int, end: int) -> list[dict]:
    return [{"offset": offset, "text": text} for offset, text in entries if start <= offset <= end]


def main() -> None:
    entries = collect_strings_with_offsets()

    markers = {
        "jest_wynikN": first(entries, "jest_wynikN"),
        "jest_wynikO": first(entries, "jest_wynikO"),
        "Marg_n": first(entries, "Marg_n"),
        "Marg_o": first(entries, "Marg_o"),
        "MargNad": first(entries, "MargNad"),
        "MargOdb": first(entries, "MargOdb"),
        "N-nad": first(entries, "N-nad"),
        "N-odb": first(entries, "N-odb"),
        "wyniki_EMC_prz_Marg_n": first(entries, 'wyniki_EMC_prz db, filen![przeslo#], Marg_n'),
        "wyniki_EMC_prz_Marg_o": first(entries, 'wyniki_EMC_prz db, filen![przeslo#], Marg_o'),
        "aktualizacja_parametr": first(entries, 'aktualizacja parametr'),
    }

    aggregation_block = window(entries, 49550200, 49552320)
    update_block = window(entries, 49767800, 49768680)

    report = {
        "mdb_path": str(MDB_PATH),
        "markers": markers,
        "aggregation_block": aggregation_block,
        "update_block": update_block,
        "findings": [
            (
                "The variables `jest_wynikN`, `jest_wynikO`, `Marg_n`, `Marg_o`, `MargNad`, `MargOdb`, "
                "`N-nad`, and `N-odb` all appear inside one compact recovered block of VBA symbols."
            ),
            (
                "This block also contains `stanp`, `stan_problem`, `stanprz`, `stanprzesla`, and `statusfk`, "
                "which places aggregation and candidate-state bookkeeping in the same procedural neighborhood."
            ),
            (
                "`MargNad/MargOdb` and `N-nad/N-odb` appear after the local pairwise variables `Marg_n/Marg_o`, "
                "which supports the interpretation that they are aggregated candidate-level summaries rather than "
                "raw per-pair metrics."
            ),
            (
                "The later transition block shows `wyniki_EMC_prz` for `Marg_n`, then `wyniki_EMC_prz` for `Marg_o`, "
                "and only afterwards `aktualizacja parametr w fkand`."
            ),
            (
                "Taken together, the strongest current model is that Access first computes per-branch pairwise results "
                "(`Marg_n/Marg_o`), then folds them into candidate-level aggregates (`MargNad/MargOdb`, `N-nad/N-odb`, "
                "`jest_wynikN/O`), and only then updates `fkand` state."
            ),
        ],
        "most_likely_aggregation_model": [
            "Marg_n and Marg_o are raw pairwise branch metrics",
            "jest_wynikN/O indicate whether a valid branch result exists",
            "MargNad/MargOdb are candidate-level branch summaries",
            "N-nad/N-odb are candidate-level counts or conflict tallies",
            "statusfk / later status logic consumes the aggregated candidate-level state, not raw single pair rows",
        ],
        "open_questions": [
            "Whether MargNad maps specifically to the O branch or the N branch in the original VBA logic.",
            "Whether N-nad/N-odb count only incompatible rows or all valid rows with jest_wynikN/O true.",
        ],
    }

    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
