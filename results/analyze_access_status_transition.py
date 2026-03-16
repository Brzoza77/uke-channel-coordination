#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parent.parent
MDB_PATH = REPO_ROOT / "LR_Konsultacja_349.mdb"
OUTPUT_PATH = REPO_ROOT / "logs" / "access_status_transition_20260316.json"


def collect_ascii_strings() -> list[str]:
    proc = subprocess.run(
        ["strings", str(MDB_PATH)],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.splitlines()


def collect_utf16_strings() -> list[str]:
    proc = subprocess.run(
        ["strings", "-el", str(MDB_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.splitlines()


def find_context(lines: list[str], pattern: str, radius: int = 12) -> list[dict]:
    results = []
    for idx, line in enumerate(lines):
        if pattern in line:
            results.append(
                {
                    "line_number": idx + 1,
                    "line": line,
                    "context": lines[max(0, idx - radius): min(len(lines), idx + radius + 1)],
                }
            )
    return results


def main() -> None:
    ascii_lines = collect_ascii_strings()
    utf16_lines = collect_utf16_strings()

    patterns = [
        "statusfk",
        "status_fkand",
        "status_fkand_zagr",
        "Koniec_obliczen",
        "stanp",
        "stan_problem",
        "stanprz",
        "stanprzesla",
        "Stan_wniosku_po_weryfikacji",
        "wstaw_status",
        "nrsn",
        "status_kand",
        "UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].[status] =",
    ]

    ascii_contexts = {pattern: find_context(ascii_lines, pattern) for pattern in patterns}
    utf16_contexts = {pattern: find_context(utf16_lines, pattern) for pattern in patterns}

    report = {
        "mdb_path": str(MDB_PATH),
        "patterns": patterns,
        "ascii_contexts": ascii_contexts,
        "utf16_contexts": {
            key: value for key, value in utf16_contexts.items() if value
        },
        "findings": [
            (
                "The candidate-state relation now looks layered: `statusfk` is the accumulated working state, "
                "while `status_kand` is the later finalized state placed near `wstaw_status`."
            ),
            (
                "The same lexical neighborhood contains additional state-like variables: `stanp`, `stan_problem`, "
                "`stanprz`, and `stanprzesla`, which strongly suggests that Access keeps multiple intermediate "
                "status projections before writing the final candidate status."
            ),
            (
                "`nrsn` appears immediately next to `wstaw_status`; it is a plausible helper argument or local code "
                "used to map verification outcome into `status_kand`."
            ),
            (
                "`Stan_wniosku_po_weryfikacji` still remains the strongest recovered post-EMC checkpoint before "
                "the final status promotion layer."
            ),
            (
                "The UTF-16 search did not reveal any additional transition logic beyond the ASCII string corpus, "
                "so the current reconstruction should continue to focus on ASCII-visible procedural markers."
            ),
        ],
        "most_likely_transition_model": [
            "statusfk initialised to 1",
            "problem / foreign branch may raise statusfk via status_fkand_zagr",
            "Koniec_obliczen may short-circuit with current statusfk",
            "post-EMC verification computes local state projections (stanp / stan_problem / stanprz / stanprzesla)",
            "Stan_wniosku_po_weryfikacji returns verification outcome",
            "wstaw_status consumes verification outcome plus helper code near nrsn",
            "status_kand becomes final candidate-state value",
            "dynamic SQL or helper writes Czestotliwosc kandydujaca.status",
        ],
        "open_questions": [
            "Whether nrsn is a numeric status code, a station number, or another selector used by wstaw_status.",
            "Whether status_kand directly equals the written table status, or is first normalized by another helper.",
            "Whether domestic-only paths can raise statusfk to the final printable state without the foreign branch.",
        ],
    }

    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
