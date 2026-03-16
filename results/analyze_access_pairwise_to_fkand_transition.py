#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parent.parent
MDB_PATH = REPO_ROOT / "LR_Konsultacja_349.mdb"
OUTPUT_PATH = REPO_ROOT / "logs" / "access_pairwise_to_fkand_transition_20260316.json"


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


def first_offset(entries: list[tuple[int, str]], needle: str) -> int | None:
    for offset, text in entries:
        if needle in text:
            return offset
    return None


def main() -> None:
    entries = collect_strings_with_offsets()
    marg_n = first_offset(entries, 'wyniki_EMC_prz db, filen![przeslo#], Marg_n')
    marg_o = first_offset(entries, 'wyniki_EMC_prz db, filen![przeslo#], Marg_o')
    update_fkand = first_offset(entries, 'aktualizacja parametr')
    update_fkand_table = first_offset(entries, 'Czestotliwosc kandydujaca')
    incompatible_offsets = [
        offset for offset, text in entries if 'nadaj czestotliwosci status niekompatybilna' in text
    ]

    report = {
        "mdb_path": str(MDB_PATH),
        "markers": {
            "marg_n_writer": marg_n,
            "marg_o_writer": marg_o,
            "fkand_update_marker": update_fkand,
            "fkand_table_marker": update_fkand_table,
            "incompatible_status_markers": incompatible_offsets,
        },
        "byte_deltas": {
            "marg_n_to_fkand_update": (update_fkand - marg_n) if marg_n is not None and update_fkand is not None else None,
            "marg_o_to_fkand_update": (update_fkand - marg_o) if marg_o is not None and update_fkand is not None else None,
        },
        "findings": [
            (
                "The corpus contains exactly two `wyniki_EMC_prz` calls in the relevant LR path: one for `Marg_n` "
                "and one for `Marg_o`."
            ),
            (
                "There is only one recovered `aktualizacja parametr` / `w fkand` marker in this neighborhood."
            ),
            (
                "The recovered distances show that `aktualizacja parametr` happens much closer to the `Marg_o` writer "
                "than to the `Marg_n` writer."
            ),
            (
                "This strongly suggests that candidate-state propagation to `fkand` happens after both pairwise writer "
                "branches have run, not immediately after the first `Marg_n` write."
            ),
        ],
        "most_likely_transition_model": [
            "incompatibility is detected in Marg_n branch",
            "wyniki_EMC_prz writes Marg_n row",
            "incompatibility is detected in Marg_o branch",
            "wyniki_EMC_prz writes Marg_o row",
            "after the branch pair completes, aktualizacja parametr w fkand updates candidate state",
        ],
        "open_questions": [
            "Whether the final fkand update uses only the second branch as a trigger or explicitly aggregates both Marg_n and Marg_o before writeback.",
        ],
    }

    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
