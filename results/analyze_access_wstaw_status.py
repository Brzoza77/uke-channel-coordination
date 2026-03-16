#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MDB_PATH = REPO_ROOT / "LR_Konsultacja_349.mdb"
OUTPUT_PATH = REPO_ROOT / "logs" / "access_wstaw_status_20260316.json"


def collect_strings() -> list[str]:
    import subprocess

    proc = subprocess.run(
        ["strings", str(MDB_PATH)],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.splitlines()


def find_context(lines: list[str], pattern: str, radius: int = 10) -> list[dict]:
    matches = []
    for index, line in enumerate(lines):
        if pattern in line:
            matches.append(
                {
                    "pattern": pattern,
                    "line_number": index + 1,
                    "line": line,
                    "context": lines[max(0, index - radius): min(len(lines), index + radius + 1)],
                }
            )
    return matches


def main() -> None:
    lines = collect_strings()

    patterns = [
        "wstaw_status",
        "status_kand",
        "statusfk",
        "status_fkand",
        "status_fkand_zagr",
        "Stan_wniosku_po_weryfikacji",
        "Koniec_obliczen",
        "UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].[status] =",
    ]

    contexts = {pattern: find_context(lines, pattern) for pattern in patterns}

    report = {
        "mdb_path": str(MDB_PATH),
        "patterns": patterns,
        "contexts": contexts,
        "findings": [
            (
                "`statusfk = 1` remains the clearest initialization point for the procedural candidate-state "
                "accumulator before EMC verification."
            ),
            (
                "`status_fkand_zagr` is the only recovered branch variable that demonstrably promotes the accumulator: "
                "`If status_fkand_zagr = 2 Then status_fkand = 2`."
            ),
            (
                "`Koniec_obliczen dbb, fid(i), status_fkand` shows that Access can terminate a candidate path early "
                "while still carrying the accumulated state value."
            ),
            (
                "`Stan_wniosku_po_weryfikacji(...)` appears after `ExportTx_przeslo`, `ExportRx_przeslo`, "
                "`wpisz_dane_koor`, `kwalifikacja_koor`, and `Kwalifikacja_EMC`, so it belongs to the post-EMC "
                "verification layer rather than raw pairwise result writing."
            ),
            (
                "`wstaw_status` and `status_kand` appear in the same lexical block as post-verification symbols, "
                "which supports the interpretation that final candidate promotion happens after verification."
            ),
            (
                "The literal SQL update for `Czestotliwosc kandydujaca.status` is visible elsewhere in the corpus, "
                "so `wstaw_status` is most plausibly a helper that computes or dispatches the final status value, "
                "while the actual write may happen through dynamic SQL or a nearby helper call."
            ),
        ],
        "most_likely_flow": [
            "statusfk = 1",
            "problem / foreign branch may raise status_fkand",
            "Koniec_obliczen can short-circuit with status_fkand",
            "ExportTx_przeslo",
            "ExportRx_przeslo",
            "wpisz_dane_koor",
            "kwalifikacja_koor",
            "Kwalifikacja_EMC",
            "Stan_wniosku_po_weryfikacji",
            "wstaw_status",
            "status_kand",
            "UPDATE Czestotliwosc kandydujaca.status",
        ],
        "open_questions": [
            "Whether status_kand is a local numeric variable or a helper return value consumed by wstaw_status.",
            "Whether domestic terrestrial verification can promote statusfk to 2 without going through status_fkand_zagr.",
            "Whether wstaw_status performs the write itself or only chooses the value later written by dynamic SQL.",
        ],
    }

    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
