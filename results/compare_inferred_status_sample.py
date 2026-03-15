from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import analysis as analysis_engine  # noqa: E402
from results.tune_with_uke_docs import discover_pairs, prepare_cases  # noqa: E402


def requested_assessment(case_request, analysis_result):
    preferred_pol = case_request.requested_polarization if case_request.requested_polarization in {"H", "V"} else None
    for assessment in analysis_result.channel_assessments:
        if assessment.candidate.channel_ab != case_request.channel_ab:
            continue
        if assessment.candidate.channel_ba != case_request.channel_ba:
            continue
        if preferred_pol and assessment.candidate.polarization != preferred_pol:
            continue
        return assessment
    return None


def requested_record(case_request, analysis_result):
    preferred_pol = case_request.requested_polarization if case_request.requested_polarization in {"H", "V"} else None
    for record in analysis_result.candidate_frequency_records:
        if record.channel_ab != case_request.channel_ab:
            continue
        if record.channel_ba != case_request.channel_ba:
            continue
        if preferred_pol and record.polarization != preferred_pol:
            continue
        return record
    return None


def heuristic_match(expected: str, got: str) -> bool:
    return (
        (expected == "ACCEPTED" and got == "ACCEPTED")
        or (expected == "REJECTED" and got != "ACCEPTED")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare current requested status vs inferred UKE-like status on a sample of WLR-DOC pairs.")
    parser.add_argument("--tests-dir", default="testy")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--max-links", type=int, default=300)
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args()

    tests_dir = Path(args.tests_dir)
    pairs = discover_pairs(tests_dir)
    prepared, stats = prepare_cases(pairs, doc_cache={}, limit=args.limit)

    current_compared = 0
    current_matched_heur = 0
    current_matched_strict = 0
    inferred_compared = 0
    inferred_matched_heur = 0
    inferred_matched_strict = 0
    cases_out = []

    for case in prepared:
        try:
            analysis_result = analysis_engine.analyze_wlr_request(case.request, max_links=args.max_links)
        except Exception as exc:  # noqa: BLE001
            cases_out.append(
                {
                    "case": case.key,
                    "expected": case.expected_status,
                    "error": str(exc),
                }
            )
            continue

        assessment = requested_assessment(case.request, analysis_result)
        record = requested_record(case.request, analysis_result)
        current_status = assessment.status if assessment else None
        inferred_status = record.inferred_uke_like_status if record else None

        row = {
            "case": case.key,
            "expected": case.expected_status,
            "current_status": current_status,
            "inferred_status": inferred_status,
            "current_heuristic_ok": heuristic_match(case.expected_status, current_status) if current_status else None,
            "inferred_heuristic_ok": heuristic_match(case.expected_status, inferred_status) if inferred_status else None,
            "current_strict_ok": current_status == case.expected_status if current_status else None,
            "inferred_strict_ok": inferred_status == case.expected_status if inferred_status else None,
            "requested_candidate": (
                f"{record.channel_ab}/{record.channel_ba}/{record.polarization}" if record else None
            ),
            "worst_duplex_margin_db": record.worst_duplex_margin_db if record else None,
            "uke_like_problem_flags": record.uke_like_problem_flags if record else [],
        }
        cases_out.append(row)

        if current_status:
            current_compared += 1
            if row["current_heuristic_ok"]:
                current_matched_heur += 1
            if row["current_strict_ok"]:
                current_matched_strict += 1
        if inferred_status:
            inferred_compared += 1
            if row["inferred_heuristic_ok"]:
                inferred_matched_heur += 1
            if row["inferred_strict_ok"]:
                inferred_matched_strict += 1

    summary = {
        "engine_version": analysis_engine.ENGINE_VERSION,
        "limit": args.limit,
        "max_links": args.max_links,
        "prepare_stats": stats,
        "prepared_cases": len(prepared),
        "current": {
            "compared": current_compared,
            "matched_heuristic": current_matched_heur,
            "matched_strict": current_matched_strict,
            "heuristic_accuracy": (current_matched_heur / current_compared) if current_compared else 0.0,
            "strict_accuracy": (current_matched_strict / current_compared) if current_compared else 0.0,
        },
        "inferred": {
            "compared": inferred_compared,
            "matched_heuristic": inferred_matched_heur,
            "matched_strict": inferred_matched_strict,
            "heuristic_accuracy": (inferred_matched_heur / inferred_compared) if inferred_compared else 0.0,
            "strict_accuracy": (inferred_matched_strict / inferred_compared) if inferred_compared else 0.0,
        },
        "cases": cases_out,
    }

    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
