#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import _pairwise_result_is_problem, analyze_wlr_request
from wlr import parse_wlr_file


def branch_counts(rows):
    return {
        "valid": sum(1 for row in rows if row.margin_db is not None),
        "problem": sum(1 for row in rows if _pairwise_result_is_problem(row)),
        "negative": sum(1 for row in rows if row.margin_db is not None and row.margin_db < 0.0),
        "blocking": sum(1 for row in rows if row.is_blocking and row.margin_db is not None),
        "red": sum(1 for row in rows if row.risk_level == "red" and row.margin_db is not None),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Find the fkand aggregation edge case where problem != blocking/red.")
    parser.add_argument("--wlr", required=True)
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args()

    request = parse_wlr_file(Path(args.wlr).resolve())
    result = analyze_wlr_request(request)

    cases = []
    for record in result.candidate_frequency_records:
        results_o = [row for row in record.pairwise_results if row.direction == "B->A"]
        counts_o = branch_counts(results_o)
        if counts_o["problem"] == counts_o["blocking"] == counts_o["red"]:
            continue
        detail_rows = []
        for row in results_o:
            problem = _pairwise_result_is_problem(row)
            blocking = bool(row.is_blocking and row.margin_db is not None)
            red = bool(row.risk_level == "red" and row.margin_db is not None)
            if len({problem, blocking, red}) <= 1:
                continue
            detail_rows.append(
                {
                    "permit": row.interfering_permit_number,
                    "operator": row.interfering_operator_name,
                    "conflict_type": row.conflict_type,
                    "relationship": row.relationship,
                    "margin_db": row.margin_db,
                    "ci_db": row.ci_db,
                    "degradation_db": row.degradation_db,
                    "overlap_ratio": row.overlap_ratio,
                    "effective_freq_delta_mhz": row.effective_freq_delta_mhz,
                    "risk_level": row.risk_level,
                    "is_blocking": row.is_blocking,
                    "problem": problem,
                    "blocking_counted": blocking,
                    "red_counted": red,
                    "explanation": row.explanation,
                }
            )
        cases.append(
            {
                "candidate": f"{record.channel_ab}/{record.channel_ba} {record.polarization}",
                "status": record.status,
                "current_n_nad": record.access_fkand_n_nad,
                "o_branch_counts": counts_o,
                "margnad_db": record.access_fkand_margnad_db,
                "detail_rows": detail_rows,
            }
        )

    out_path = Path(args.out_json).resolve()
    out_path.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=2) + "\n")
    print(out_path)


if __name__ == "__main__":
    main()
