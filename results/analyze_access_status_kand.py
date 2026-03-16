#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parent.parent
MDB_PATH = REPO_ROOT / "LR_Konsultacja_349.mdb"
OUTPUT_PATH = REPO_ROOT / "logs" / "access_status_kand_20260316.json"


def run_strings(*args: str) -> list[str]:
    proc = subprocess.run(
        ["strings", *args, str(MDB_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.splitlines()


def contexts(lines: list[str], pattern: str, radius: int = 12) -> list[dict]:
    out = []
    for i, line in enumerate(lines):
        if pattern in line:
            out.append(
                {
                    "line_number": i + 1,
                    "line": line,
                    "context": lines[max(0, i - radius): min(len(lines), i + radius + 1)],
                }
            )
    return out


def grep_exact_assignment() -> list[str]:
    proc = subprocess.run(
        [
            "bash",
            "-lc",
            r"strings LR_Konsultacja_349.mdb | grep -n -E 'status_kand[[:space:]]*=|wstaw_status\(|wstaw_status[[:space:]]*=|status_kand\)|status_kand,' || true",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def main() -> None:
    ascii_lines = run_strings()
    utf16_lines = run_strings("-el")

    report = {
        "mdb_path": str(MDB_PATH),
        "ascii_status_kand_contexts": contexts(ascii_lines, "status_kand"),
        "ascii_wstaw_status_contexts": contexts(ascii_lines, "wstaw_status"),
        "ascii_update_status_contexts": contexts(
            ascii_lines,
            "UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].[status] =",
        ),
        "utf16_status_kand_contexts": contexts(utf16_lines, "status_kand"),
        "explicit_assignment_hits": grep_exact_assignment(),
        "findings": [
            (
                "`status_kand` appears only once in the recovered ASCII string corpus and sits immediately next to "
                "`wstaw_status`, which makes it a strong candidate for the finalized local status value."
            ),
            (
                "The dynamic SQL update for `Czestotliwosc kandydujaca.status` is visible elsewhere in the corpus, "
                "but not in the same local block as `status_kand`, which suggests an indirect handoff between "
                "status computation and status writeback."
            ),
            (
                "No explicit assignment form such as `status_kand = ...` or a readable call form "
                "`wstaw_status(...)` is visible in the recovered string corpus."
            ),
            (
                "Because `status_kand` is singleton and local, it is more plausible as a procedural local variable "
                "than as a globally reused status code or table field name."
            ),
        ],
        "most_likely_interpretation": [
            "`statusfk` is a working accumulator.",
            "`status_kand` is the later finalized candidate-state value near the end of the procedural flow.",
            "`wstaw_status` likely computes or dispatches `status_kand`.",
            "Another helper or dynamic SQL block likely performs the actual table update after that computation.",
        ],
        "open_questions": [
            "Whether `status_kand` is passed into a helper that builds the dynamic UPDATE string.",
            "Whether `status_kand` is normalized to printable table status values before writeback.",
            "Whether domestic verification can assign `status_kand` directly without touching the foreign-branch accumulator.",
        ],
    }

    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
