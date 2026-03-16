#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import analyze_wlr_request
from wlr import parse_wlr_file

CASE_NAMES = [
    "1106.wlr",
    "1234.wlr",
    "1308.wlr",
    "1378.wlr",
    "1905.wlr",
    "3961.wlr",
    "BT10561C-BT10853C-001_0_20260312114554.wlr",
]


def main() -> None:
    evaluation = json.loads((REPO_ROOT / "logs" / "fkand_status_gate_evaluation_20260316.json").read_text())
    mismatches = evaluation["sample_mismatches"]
    targets = {(row["wlr"], row["candidate"]) for row in mismatches}

    all_by_signature: dict[tuple[int, int, int], list[dict[str, object]]] = defaultdict(list)
    target_reports: list[dict[str, object]] = []

    for case_name in CASE_NAMES:
        request = parse_wlr_file(REPO_ROOT / "testy" / case_name)
        analysis = analyze_wlr_request(request)
        assessments = {
            f"{item.candidate.channel_ab}/{item.candidate.channel_ba} {item.candidate.polarization}": item
            for item in analysis.channel_assessments
        }

        for record in analysis.candidate_frequency_records:
            candidate_label = f"{record.channel_ab}/{record.channel_ba} {record.polarization}"
            problem_count = record.access_fkand_problem_path_n_odb + record.access_fkand_problem_path_n_nad
            incompatible_count = (
                record.access_fkand_incompatible_path_n_odb + record.access_fkand_incompatible_path_n_nad
            )
            signature = (problem_count, incompatible_count, record.access_fkand_overlap_count)
            assessment = assessments[candidate_label]
            row = {
                "wlr": case_name,
                "candidate": candidate_label,
                "status": record.status,
                "gate_status": record.access_fkand_gate_status,
                "signature": signature,
                "worst_duplex_margin_db": record.worst_duplex_margin_db,
                "pairwise_red_count": record.pairwise_red_count,
                "pairwise_blocking_count": record.pairwise_blocking_count,
                "pairwise_cochannel_count": record.pairwise_cochannel_count,
                "status_ab": record.status_ab,
                "status_ba": record.status_ba,
                "risk_counts": dict(Counter(conflict.risk_level for conflict in assessment.conflicts)),
                "type_counts": dict(Counter(conflict.conflict_type for conflict in assessment.conflicts)),
                "relationship_counts": dict(Counter(conflict.relationship for conflict in assessment.conflicts)),
                "reasons_ab": assessment.reasons_ab,
                "reasons_ba": assessment.reasons_ba,
            }
            all_by_signature[signature].append(row)
            if (case_name, candidate_label) in targets:
                target_reports.append(row)

    report = {
        "totals": evaluation["totals"],
        "mismatch_count": len(mismatches),
        "mismatches": target_reports,
        "signature_context": {
            str(signature): rows
            for signature, rows in sorted(
                all_by_signature.items(),
                key=lambda item: (len(item[1]), item[0]),
                reverse=True,
            )
            if any((row["wlr"], row["candidate"]) in targets for row in rows)
        },
        "findings": [
            "The last 5 status-gate mismatches split into two classes: ambiguous signatures reused by both CONDITIONAL and REJECTED rows, and one fallback-driven mismatch that likely needs one more discriminator.",
            "The strongest extra discriminator in the current residuals is pairwise RED presence: the only REJECTED->CONDITIONAL mismatch has red_count=4, while the symmetric CONDITIONAL mismatches around the same counts have red_count=0 or 2.",
        ],
    }

    out = REPO_ROOT / "logs" / "status_gate_mismatch_analysis_20260316.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(out)
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
