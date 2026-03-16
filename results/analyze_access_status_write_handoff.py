#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parent.parent
MDB_PATH = REPO_ROOT / "LR_Konsultacja_349.mdb"
OUTPUT_PATH = REPO_ROOT / "logs" / "access_status_write_handoff_20260316.json"


def collect_strings_with_offsets() -> list[tuple[int, str]]:
    proc = subprocess.run(
        ["strings", "-t", "d", str(MDB_PATH)],
        capture_output=True,
        text=True,
        check=True,
    )
    out: list[tuple[int, str]] = []
    for raw in proc.stdout.splitlines():
        raw = raw.rstrip()
        if not raw:
            continue
        parts = raw.split(" ", 1)
        if len(parts) != 2:
            continue
        try:
            offset = int(parts[0])
        except ValueError:
            continue
        out.append((offset, parts[1].lstrip()))
    return out


def find_first(entries: list[tuple[int, str]], needle: str) -> dict | None:
    for offset, text in entries:
        if needle in text:
            return {"offset": offset, "text": text}
    return None


def main() -> None:
    entries = collect_strings_with_offsets()

    markers = {
        "wstaw_status": find_first(entries, "wstaw_status"),
        "nrsn": find_first(entries, "nrsn"),
        "status_kand": find_first(entries, "status_kand"),
        "statusfk_init": find_first(entries, "statusfk = 1"),
        "status_update_sql": find_first(
            entries,
            "UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].[status] =",
        ),
        "tdane_update_sql": find_first(
            entries,
            'strpyt = "UPDATE [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].T_dane_koor = Null',
        ),
        "db_execute_strpyt": find_first(entries, "db.Execute strpyt"),
    }

    deltas = {}
    if markers["status_kand"] and markers["status_update_sql"]:
        deltas["status_kand_to_status_update_bytes"] = (
            markers["status_update_sql"]["offset"] - markers["status_kand"]["offset"]
        )
    if markers["status_update_sql"] and markers["tdane_update_sql"]:
        deltas["status_update_to_tdane_update_bytes"] = (
            markers["tdane_update_sql"]["offset"] - markers["status_update_sql"]["offset"]
        )
    if markers["tdane_update_sql"] and markers["db_execute_strpyt"]:
        deltas["tdane_update_to_db_execute_bytes"] = (
            markers["db_execute_strpyt"]["offset"] - markers["tdane_update_sql"]["offset"]
        )

    report = {
        "mdb_path": str(MDB_PATH),
        "markers": markers,
        "byte_deltas": deltas,
        "findings": [
            (
                "`wstaw_status`, `nrsn`, and `status_kand` are tightly clustered in one local block, while the "
                "dynamic SQL status update string lives much later in the file."
            ),
            (
                "The recovered distance from `status_kand` to the visible `UPDATE ... SET [status] =` string is "
                "large enough to treat them as separate procedural stages, not one contiguous readable block."
            ),
            (
                "The file also contains a different explicit update path for the same table "
                "(`T_dane_koor/R_dane_koor`) expressed as `strpyt` plus `db.Execute strpyt`, which proves Access uses "
                "dynamic SQL writeback for candidate rows elsewhere in the same workflow."
            ),
            (
                "Taken together, the most likely model is: local helper logic computes `status_kand`, then another "
                "stage composes or dispatches a dynamic SQL update to write the final table status."
            ),
        ],
        "most_likely_handoff_model": [
            "wstaw_status/nrsn/status_kand form a local computation block",
            "status_kand is not itself the visible SQL writer",
            "a later helper stage prepares UPDATE DISTINCTROW ... SET [status] = ...",
            "the actual execution may happen through dynamic SQL similarly to db.Execute strpyt",
        ],
        "open_questions": [
            "Whether the hidden status writer uses strpyt/db.Execute like the T_dane_koor cleanup path.",
            "Whether the same helper that writes status also normalizes status_kand into printable status values.",
        ],
    }

    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
