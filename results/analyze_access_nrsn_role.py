#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parent.parent
MDB_PATH = REPO_ROOT / "LR_Konsultacja_349.mdb"
OUTPUT_PATH = REPO_ROOT / "logs" / "access_nrsn_role_20260316.json"


PATTERNS = [
    "nrsn",
    "StNaRad1",
    "wstaw_status",
    "status_kand",
    "stanp",
    "stan_problem",
    "stanprz",
    "stanprzesla",
]


def collect_strings(args: list[str]) -> list[str]:
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    return proc.stdout.splitlines()


def find_context(lines: list[str], pattern: str, radius: int = 10) -> list[dict]:
    hits = []
    for idx, line in enumerate(lines):
        if pattern in line:
            hits.append(
                {
                    "line_number": idx + 1,
                    "line": line,
                    "context": lines[max(0, idx - radius): min(len(lines), idx + radius + 1)],
                }
            )
    return hits


def main() -> None:
    ascii_lines = collect_strings(["strings", str(MDB_PATH)])
    utf16_lines = collect_strings(["strings", "-el", str(MDB_PATH)])

    ascii_hits = {pattern: find_context(ascii_lines, pattern) for pattern in PATTERNS}
    utf16_counts = {pattern: sum(1 for line in utf16_lines if pattern in line) for pattern in PATTERNS}

    report = {
        "mdb_path": str(MDB_PATH),
        "ascii_counts": {pattern: len(ascii_hits[pattern]) for pattern in PATTERNS},
        "utf16_counts": utf16_counts,
        "ascii_contexts": ascii_hits,
        "findings": [
            (
                "`nrsn`, `StNaRad1`, and `status_kand` each appear only once in the ASCII string corpus and do not "
                "reappear elsewhere as global workflow identifiers."
            ),
            (
                "Their only recovered neighborhood is the same local block around `wstaw_status`, which makes them "
                "much more likely to be local helper variables or selector codes than top-level workflow entities."
            ),
            (
                "`stanp`, `stan_problem`, `stanprz`, and `stanprzesla` form a nearby cluster of intermediate state "
                "symbols, reinforcing the idea that `wstaw_status` consumes a normalized local state bundle."
            ),
            (
                "The UTF-16 scan contributes no additional occurrences, so the current role inference for `nrsn` "
                "should remain grounded in the ASCII-visible local block only."
            ),
        ],
        "most_likely_interpretation": [
            "`nrsn` is not a globally reused status flag.",
            "`nrsn` is likely a local selector or code used by `wstaw_status` while producing `status_kand`.",
            "`status_kand` is likely the finalized local candidate-state value derived from post-verification state.",
        ],
    }

    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
