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


def requested_status(case_request, analysis_result):
    preferred_pol = case_request.requested_polarization if case_request.requested_polarization in {"H", "V"} else None
    for assessment in analysis_result.channel_assessments:
        if assessment.candidate.channel_ab != case_request.channel_ab:
            continue
        if assessment.candidate.channel_ba != case_request.channel_ba:
            continue
        if preferred_pol and assessment.candidate.polarization != preferred_pol:
            continue
        return assessment.status
    return None


def heuristic_match(expected: str, got: str | None) -> bool:
    if not got:
        return False
    return (
        (expected == "ACCEPTED" and got == "ACCEPTED")
        or (expected == "REJECTED" and got != "ACCEPTED")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline experiment with broader same-operator historical filter.")
    parser.add_argument("--tests-dir", default="testy")
    parser.add_argument("--limit-per-band", type=int, default=6)
    parser.add_argument("--max-links", type=int, default=300)
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args()

    pairs = discover_pairs(Path(args.tests_dir))
    prepared, stats = prepare_cases(pairs, doc_cache={}, limit=None)

    selected = []
    per_band_counts: dict[str, int] = {}
    for case in prepared:
        band = detect_band(case.request)
        if band not in {"23GHz", "38GHz", "80GHz"}:
            continue
        if per_band_counts.get(band, 0) >= args.limit_per_band:
            continue
        per_band_counts[band] = per_band_counts.get(band, 0) + 1
        selected.append((band, case))

    original_filter = analysis_engine.should_ignore_conflict_for_consultation

    def broader_filter(conflict):
        if original_filter(conflict):
            return True
        if conflict.same_operator and conflict.relationship in {"external", "shared_site", "same_span", "same_span_like"}:
            return True
        return False

    current_rows = []
    filtered_rows = []

    for band, case in selected:
        res_current = analysis_engine.analyze_wlr_request(case.request, max_links=args.max_links)
        current = requested_status(case.request, res_current)

        analysis_engine.should_ignore_conflict_for_consultation = broader_filter
        try:
            res_filtered = analysis_engine.analyze_wlr_request(case.request, max_links=args.max_links)
        finally:
            analysis_engine.should_ignore_conflict_for_consultation = original_filter
        filtered = requested_status(case.request, res_filtered)

        row = {
            "case": case.key,
            "band": band,
            "expected": case.expected_status,
            "current": current,
            "filtered": filtered,
            "current_heuristic_ok": heuristic_match(case.expected_status, current),
            "filtered_heuristic_ok": heuristic_match(case.expected_status, filtered),
        }
        current_rows.append(row)
        filtered_rows.append(row)

    summary = {
        "engine_version": analysis_engine.ENGINE_VERSION,
        "prepare_stats": stats,
        "selected_cases": len(selected),
        "limit_per_band": args.limit_per_band,
        "max_links": args.max_links,
        "current_heuristic_accuracy": (
            sum(1 for row in current_rows if row["current_heuristic_ok"]) / len(current_rows) if current_rows else 0.0
        ),
        "filtered_heuristic_accuracy": (
            sum(1 for row in filtered_rows if row["filtered_heuristic_ok"]) / len(filtered_rows) if filtered_rows else 0.0
        ),
        "cases": current_rows,
    }

    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
