from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import analysis as analysis_engine  # noqa: E402
from results.tune_with_uke_docs import discover_pairs, prepare_cases  # noqa: E402


def detect_band(request) -> str:
    freqs = [f for f in (request.freq_ab_ghz, request.freq_ba_ghz) if f is not None]
    if not freqs:
        return "unknown"
    low = min(freqs)
    if 22 <= low < 25:
        return "23GHz"
    if 37 <= low < 40:
        return "38GHz"
    if 70 <= low < 90:
        return "80GHz"
    return f"other:{low:.3f}"


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


def summarize_conflicts(assessment) -> dict:
    conflicts = list(getattr(assessment, "conflicts", []))
    blocking = [c for c in conflicts if analysis_engine.is_blocking_conflict(c)]
    dominant = sorted(blocking or conflicts, key=lambda c: c.score, reverse=True)[:5]
    return {
        "conflicts_total": len(conflicts),
        "blocking_total": len(blocking),
        "same_operator_total": sum(1 for c in conflicts if c.same_operator),
        "same_operator_blocking": sum(1 for c in blocking if c.same_operator),
        "cochannel_blocking": sum(1 for c in blocking if c.conflict_type == "cochannel"),
        "adjacent_blocking": sum(1 for c in blocking if c.conflict_type == "adjacent"),
        "geometry_blocking": sum(1 for c in blocking if c.conflict_type == "geometry"),
        "risk_levels": dict(Counter(c.risk_level for c in blocking)),
        "dominant": [
            {
                "link_id": c.link_id,
                "permit_number": c.permit_number,
                "operator_name": c.operator_name,
                "same_operator": c.same_operator,
                "conflict_type": c.conflict_type,
                "relationship": c.relationship,
                "score": c.score,
                "distance_km": c.distance_km,
                "effective_freq_delta_mhz": c.effective_freq_delta_mhz,
                "estimated_margin_ab_db": c.estimated_margin_ab_db,
                "estimated_margin_ba_db": c.estimated_margin_ba_db,
                "decision_explanation": c.decision_explanation,
            }
            for c in dominant
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze requested-channel blockers on a sample of WLR-DOC pairs by band.")
    parser.add_argument("--tests-dir", default="testy")
    parser.add_argument("--limit-per-band", type=int, default=8)
    parser.add_argument("--max-links", type=int, default=300)
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args()

    tests_dir = Path(args.tests_dir)
    pairs = discover_pairs(tests_dir)
    prepared, stats = prepare_cases(pairs, doc_cache={}, limit=None)

    selected = []
    per_band_counts = defaultdict(int)
    for case in prepared:
        band = detect_band(case.request)
        if band not in {"23GHz", "38GHz", "80GHz"}:
            continue
        if per_band_counts[band] >= args.limit_per_band:
            continue
        per_band_counts[band] += 1
        selected.append((band, case))

    cases_out = []
    aggregate = {
        "by_band": defaultdict(lambda: {
            "cases": 0,
            "current_accepted": 0,
            "current_conditional": 0,
            "current_rejected": 0,
            "expected_accepted": 0,
            "expected_rejected": 0,
            "false_negative_like": 0,
            "same_operator_blocker_cases": 0,
            "external_blocker_cases": 0,
        })
    }

    for band, case in selected:
        bucket = aggregate["by_band"][band]
        bucket["cases"] += 1
        if case.expected_status == "ACCEPTED":
            bucket["expected_accepted"] += 1
        elif case.expected_status == "REJECTED":
            bucket["expected_rejected"] += 1

        try:
            analysis_result = analysis_engine.analyze_wlr_request(case.request, max_links=args.max_links)
        except Exception as exc:  # noqa: BLE001
            cases_out.append({"case": case.key, "band": band, "error": str(exc)})
            continue

        assessment = requested_assessment(case.request, analysis_result)
        if assessment is None:
            cases_out.append({"case": case.key, "band": band, "error": "requested assessment not found"})
            continue

        bucket[f"current_{assessment.status.lower()}"] += 1
        if case.expected_status == "ACCEPTED" and assessment.status != "ACCEPTED":
            bucket["false_negative_like"] += 1

        conflict_summary = summarize_conflicts(assessment)
        if conflict_summary["same_operator_blocking"] > 0:
            bucket["same_operator_blocker_cases"] += 1
        if conflict_summary["blocking_total"] > conflict_summary["same_operator_blocking"]:
            bucket["external_blocker_cases"] += 1

        cases_out.append(
            {
                "case": case.key,
                "band": band,
                "expected_status": case.expected_status,
                "current_status": assessment.status,
                "requested_candidate": f"{assessment.candidate.channel_ab}/{assessment.candidate.channel_ba}/{assessment.candidate.polarization}",
                "best_explanation": assessment.best_explanation,
                "rejection_reasons": list(getattr(assessment, "rejection_reasons", [])),
                "ignored_conflicts_count": len(getattr(assessment, "ignored_conflicts", [])),
                "conflict_summary": conflict_summary,
            }
        )

    summary = {
        "engine_version": analysis_engine.ENGINE_VERSION,
        "prepare_stats": stats,
        "selected_cases": len(selected),
        "limit_per_band": args.limit_per_band,
        "max_links": args.max_links,
        "bands": {band: data for band, data in aggregate["by_band"].items()},
        "cases": cases_out,
    }

    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
