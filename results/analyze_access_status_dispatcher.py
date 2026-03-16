#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parent.parent
MDB_PATH = REPO_ROOT / "LR_Konsultacja_349.mdb"
OUTPUT_PATH = REPO_ROOT / "logs" / "access_status_dispatcher_20260316.json"


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


def windows_around(entries: list[tuple[int, str]], needle: str, radius: int = 2500) -> list[dict]:
    hits = []
    for offset, text in entries:
        if needle in text:
            hits.append(
                {
                    "center_offset": offset,
                    "center_text": text,
                    "window": [
                        {"offset": o, "text": t}
                        for o, t in entries
                        if offset - radius <= o <= offset + radius
                    ],
                }
            )
    return hits


def main() -> None:
    entries = collect_strings_with_offsets()
    windows = windows_around(entries, "nadaj czestotliwosci status niekompatybilna")

    report = {
        "mdb_path": str(MDB_PATH),
        "status_dispatcher_windows": windows,
        "findings": [
            (
                "The phrase `nadaj czestotliwosci status niekompatybilna` appears twice, once in the `Marg_n` branch "
                "and once in the `Marg_o` branch."
            ),
            (
                "Each occurrence is immediately followed by a `wyniki_EMC_prz` call, which ties the phrase directly "
                "to pairwise EMC result writing rather than only to the final report stage."
            ),
            (
                "The second occurrence is followed shortly by `aktualizacja parametr`, `w fkand`, and "
                "`Czestotliwosc kandydujaca`, making it the strongest currently recovered bridge between "
                "pairwise incompatibility detection and candidate-state update."
            ),
            (
                "This suggests the hidden dispatcher is likely split across two layers: an early branch that decides "
                "`status niekompatybilna` during `Marg_n/Marg_o` handling, and a later writer that turns that state "
                "into the visible `UPDATE DISTINCTROW ... SET [status] = ...`."
            ),
        ],
        "most_likely_dispatcher_model": [
            "Marg_n / Marg_o branch detects incompatibility",
            "code path marks 'status niekompatybilna'",
            "wyniki_EMC_prz writes pairwise result row",
            "aktualizacja parametr w fkand propagates the incompatible state to candidate-local state",
            "later SQL writer persists final candidate status to Czestotliwosc kandydujaca",
        ],
        "open_questions": [
            "Whether the same branch directly sets statusfk/status_kand or only flips another local incompatibility flag.",
            "Whether both Marg_n and Marg_o can independently trigger the same final incompatible candidate status.",
        ],
    }

    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
