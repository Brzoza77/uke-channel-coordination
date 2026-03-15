from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import analysis as analysis_engine  # noqa: E402
from analysis import ChannelAssessment, ConflictAssessment  # noqa: E402
from wlr import parse_wlr_file  # noqa: E402


def sum_degradation_db(values: list[float]) -> float:
    ratios_sum = 0.0
    for value in values:
        ratios_sum += max(0.0, 10.0 ** (value / 10.0) - 1.0)
    return 10.0 * math.log10(1.0 + ratios_sum) if ratios_sum > 0.0 else 0.0


def find_assessment(
    assessments: list[ChannelAssessment],
    direction: str,
    channel: str,
    freq_ghz: float,
    polarization: str,
) -> Optional[ChannelAssessment]:
    candidates: list[tuple[float, ChannelAssessment]] = []
    for assessment in assessments:
        candidate = assessment.candidate
        if candidate.polarization != polarization:
            continue
        if direction == "A -> B":
            if candidate.channel_ab != channel:
                continue
            delta = abs(candidate.freq_ab_ghz - freq_ghz)
        else:
            if candidate.channel_ba != channel:
                continue
            delta = abs(candidate.freq_ba_ghz - freq_ghz)
        candidates.append((delta, assessment))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def match_engine_conflict(
    conflicts: list[ConflictAssessment],
    permit_number: str,
) -> Optional[ConflictAssessment]:
    matches = [conflict for conflict in conflicts if conflict.permit_number == permit_number]
    if not matches:
        return None
    matches.sort(
        key=lambda conflict: max(
            conflict.estimated_degradation_victim_db or 0.0,
            conflict.estimated_degradation_aggressor_db or 0.0,
        ),
        reverse=True,
    )
    return matches[0]


def update_rows(rows: list[dict[str, str]], assessments: list[ChannelAssessment]) -> list[dict[str, str]]:
    grouped_conflicts: dict[tuple[str, str, str, str, str], list[ConflictAssessment]] = {}
    for row in rows:
        key = (
            row["direction"],
            row["channel"],
            row["freq_ghz"],
            row["polarization"],
            row["plan_symbol"],
        )
        assessment = find_assessment(
            assessments=assessments,
            direction=row["direction"],
            channel=row["channel"],
            freq_ghz=float(row["freq_ghz"]),
            polarization=row["polarization"],
        )
        conflicts = assessment.conflicts if assessment else []
        grouped_conflicts[key] = conflicts

        row["engine_assessment_status"] = assessment.status if assessment else ""
        row["engine_status_ab"] = assessment.status_ab if assessment else ""
        row["engine_status_ba"] = assessment.status_ba if assessment else ""
        row["engine_candidate_channel_ab"] = assessment.candidate.channel_ab if assessment else ""
        row["engine_candidate_channel_ba"] = assessment.candidate.channel_ba if assessment else ""

        engine_conflict = match_engine_conflict(conflicts, row["uke_link_permit"]) if assessment else None
        row["engine_conflict_found"] = str(engine_conflict is not None)
        row["engine_conflict_link_id"] = engine_conflict.link_id if engine_conflict else ""
        row["engine_conflict_operator"] = engine_conflict.operator_name if engine_conflict else ""
        row["engine_conflict_permit"] = engine_conflict.permit_number if engine_conflict else ""
        row["engine_victim_db"] = (
            f"{(engine_conflict.estimated_degradation_victim_db or 0.0):.6f}" if engine_conflict else ""
        )
        row["engine_aggressor_db"] = (
            f"{(engine_conflict.estimated_degradation_aggressor_db or 0.0):.6f}" if engine_conflict else ""
        )
        row["engine_ci_victim_db"] = f"{(engine_conflict.estimated_ci_victim_db or 0.0):.6f}" if engine_conflict else ""
        row["engine_ci_aggressor_db"] = (
            f"{(engine_conflict.estimated_ci_aggressor_db or 0.0):.6f}" if engine_conflict else ""
        )
        row["engine_margin_ab_db"] = f"{(engine_conflict.estimated_margin_ab_db or 0.0):.6f}" if engine_conflict else ""
        row["engine_margin_ba_db"] = f"{(engine_conflict.estimated_margin_ba_db or 0.0):.6f}" if engine_conflict else ""
        row["engine_effective_freq_delta_mhz"] = (
            f"{(engine_conflict.effective_freq_delta_mhz or 0.0):.6f}" if engine_conflict else ""
        )
        row["engine_overlap_ab_ratio"] = f"{(engine_conflict.overlap_ab_ratio or 0.0):.6f}" if engine_conflict else ""
        row["engine_overlap_ba_ratio"] = f"{(engine_conflict.overlap_ba_ratio or 0.0):.6f}" if engine_conflict else ""

    for row in rows:
        key = (
            row["direction"],
            row["channel"],
            row["freq_ghz"],
            row["polarization"],
            row["plan_symbol"],
        )
        conflicts = grouped_conflicts.get(key, [])
        total_victim = sum_degradation_db([conflict.estimated_degradation_victim_db or 0.0 for conflict in conflicts])
        total_aggressor = sum_degradation_db(
            [conflict.estimated_degradation_aggressor_db or 0.0 for conflict in conflicts]
        )
        row["engine_total_victim_db"] = f"{total_victim:.6f}"
        row["engine_total_aggressor_db"] = f"{total_aggressor:.6f}"

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute engine columns for a case using an existing UKE CSV.")
    parser.add_argument("--wlr", required=True)
    parser.add_argument("--base-csv", required=True)
    parser.add_argument("--out-csv", required=True)
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args()

    wlr_path = Path(args.wlr).resolve()
    base_csv = Path(args.base_csv).resolve()
    out_csv = Path(args.out_csv).resolve()
    out_json = Path(args.out_json).resolve()

    with base_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fieldnames = reader.fieldnames or []
    extra_fieldnames = [
        "engine_margin_ab_db",
        "engine_margin_ba_db",
    ]
    for name in extra_fieldnames:
        if name not in fieldnames:
            fieldnames.append(name)

    request = parse_wlr_file(wlr_path)
    analysis_result = analysis_engine.analyze_wlr_request(request)
    updated_rows = update_rows(rows, analysis_result.channel_assessments)
    requested_assessment = find_assessment(
        assessments=analysis_result.channel_assessments,
        direction="A -> B",
        channel=request.channel_ba,
        freq_ghz=request.freq_ba_ghz,
        polarization=request.requested_polarization,
    )

    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated_rows)

    summary = {
        "case": wlr_path.stem,
        "engine_version": getattr(analysis_engine, "ENGINE_VERSION", "unknown"),
        "rows_total": len(updated_rows),
        "accepted_count": len(analysis_result.accepted_assessments),
        "conditional_count": len(analysis_result.conditional_assessments),
        "rejected_count": len(analysis_result.rejected_assessments),
        "requested_status": requested_assessment.status if requested_assessment else None,
        "requested_status_ab": requested_assessment.status_ab if requested_assessment else None,
        "requested_status_ba": requested_assessment.status_ba if requested_assessment else None,
        "requested_margin_ab_db": min(
            (
                conflict.estimated_margin_ab_db
                for conflict in (requested_assessment.conflicts if requested_assessment else [])
                if conflict.estimated_margin_ab_db is not None
            ),
            default=None,
        ),
        "requested_margin_ba_db": min(
            (
                conflict.estimated_margin_ba_db
                for conflict in (requested_assessment.conflicts if requested_assessment else [])
                if conflict.estimated_margin_ba_db is not None
            ),
            default=None,
        ),
        "out_csv": str(out_csv),
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
