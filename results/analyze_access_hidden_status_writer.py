#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parent.parent
MDB_PATH = REPO_ROOT / "LR_Konsultacja_349.mdb"
OUTPUT_PATH = REPO_ROOT / "logs" / "access_hidden_status_writer_20260316.json"


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


def around(entries: list[tuple[int, str]], center: int, window: int) -> list[dict]:
    return [{"offset": offset, "text": text} for offset, text in entries if center - window <= offset <= center + window]


def nearest(entries: list[tuple[int, str]], center: int, needles: list[str]) -> dict:
    result = {}
    for needle in needles:
        hits = [(abs(offset - center), offset, text) for offset, text in entries if needle in text]
        if hits:
            distance, offset, text = min(hits, key=lambda item: item[0])
            result[needle] = {"offset": offset, "distance": distance, "text": text}
    return result


def main() -> None:
    entries = collect_strings_with_offsets()
    status_update = next(
        (offset for offset, text in entries if "UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].[status] =" in text),
        None,
    )
    if status_update is None:
        raise SystemExit("status update marker not found")

    report = {
        "mdb_path": str(MDB_PATH),
        "status_update_offset": status_update,
        "status_update_neighbourhood": around(entries, status_update, 1800),
        "nearest_execution_markers": nearest(
            entries,
            status_update,
            ["db.Execute", "dbb.Execute", "RunSQL", "QueryDefs", "CurrentDb", "strpyt ="],
        ),
        "nearest_status_markers": nearest(
            entries,
            status_update,
            ["wstaw_status", "status_kand", "nrsn", "statusfk = 1"],
        ),
        "findings": [
            (
                "The visible `UPDATE DISTINCTROW ... SET [status] =` string sits in the same lexical neighborhood as "
                "antenna-characteristic validation (`zap_char_LR`, `Set set_char_LR = ...`, and repeated "
                "`za mała liczba punktów / brak charakterystyki`)."
            ),
            (
                "No local `db.Execute`, `dbb.Execute`, or `RunSQL` marker appears close to the status update string, "
                "which means the write statement is likely prepared here but executed elsewhere."
            ),
            (
                "The nearest visible explicit SQL execution path is the separate `strpyt` / `db.Execute strpyt` block "
                "used for `T_dane_koor/R_dane_koor`, far away from the status update string."
            ),
            (
                "The nearest `wstaw_status/status_kand/nrsn` block is also far away, so the hidden writer most likely "
                "bridges two distinct phases: local status computation and later SQL writeback."
            ),
        ],
        "most_likely_writer_model": [
            "characteristic-validation branch decides or influences final status eligibility",
            "a later helper composes UPDATE DISTINCTROW ... SET [status] = ...",
            "execution happens through a separate SQL-dispatch path not visible in the local string window",
        ],
        "open_questions": [
            "Whether the hidden writer is a helper that returns a full SQL string to a common Execute routine.",
            "Whether characteristic-validation failures directly choose the written status value before execution.",
        ],
    }

    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
