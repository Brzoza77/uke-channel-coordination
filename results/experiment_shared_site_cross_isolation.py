from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import analysis as analysis_engine  # noqa: E402
from results.tune_with_uke_docs import discover_pairs, prepare_cases  # noqa: E402
from wlr import parse_wlr_file  # noqa: E402


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


def _recompute_case(case_data: dict[str, Any], extra_isolation_db: float) -> dict[str, Any]:
    updated = dict(case_data)
    updated["interference_dbm"] = case_data["interference_dbm"] - extra_isolation_db
    updated["ci_db"] = case_data["wanted_signal_dbm"] - updated["interference_dbm"]
    updated["degradation_db"] = analysis_engine.threshold_degradation_db(
        updated["interference_dbm"],
        case_data["noise_dbm"],
    )
    updated["margin_db"] = analysis_engine._emc_margin_db(updated["ci_db"], updated["degradation_db"])
    return updated


def _adjust_metrics(metrics: dict[str, Any], extra_isolation_db: float, cross_delta_min_mhz: float) -> dict[str, Any]:
    if extra_isolation_db <= 0.0:
        return metrics
    if metrics.get("relationship") != "shared_site":
        return metrics

    updated = dict(metrics)
    changed = False

    for label in ("ab_incoming_case", "ab_outgoing_case", "ba_incoming_case", "ba_outgoing_case"):
        case_data = updated[label]
        emc_input = case_data.get("emc_input")
        if emc_input is None:
            continue
        if not emc_input.direction.endswith("_cross"):
            continue
        if emc_input.overlap_ratio > 0.0:
            continue
        if emc_input.freq_delta_mhz < cross_delta_min_mhz:
            continue
        updated[label] = _recompute_case(case_data, extra_isolation_db)
        changed = True

    if not changed:
        return metrics

    ab_incoming_case = updated["ab_incoming_case"]
    ab_outgoing_case = updated["ab_outgoing_case"]
    ba_incoming_case = updated["ba_incoming_case"]
    ba_outgoing_case = updated["ba_outgoing_case"]

    md_db = min(
        ab_incoming_case["md_db"],
        ab_outgoing_case["md_db"],
        ba_incoming_case["md_db"],
        ba_outgoing_case["md_db"],
    )
    nfd_db = min(
        ab_incoming_case["nfd_db"],
        ab_outgoing_case["nfd_db"],
        ba_incoming_case["nfd_db"],
        ba_outgoing_case["nfd_db"],
    )
    interference_victim_dbm = max(ab_incoming_case["interference_dbm"], ba_incoming_case["interference_dbm"])
    interference_aggressor_dbm = max(ab_outgoing_case["interference_dbm"], ba_outgoing_case["interference_dbm"])
    noise_request_dbm = analysis_engine.thermal_noise_dbm(updated["ab_incoming_case"]["emc_input"].victim_bw_mhz)
    noise_existing_dbm = min(
        ab_outgoing_case["noise_dbm"],
        ba_outgoing_case["noise_dbm"],
    )
    ci_victim_db = min(ab_incoming_case["ci_db"], ba_incoming_case["ci_db"])
    ci_aggressor_db = min(ab_outgoing_case["ci_db"], ba_outgoing_case["ci_db"])
    degradation_victim_db = max(ab_incoming_case["degradation_db"], ba_incoming_case["degradation_db"])
    degradation_aggressor_db = max(ab_outgoing_case["degradation_db"], ba_outgoing_case["degradation_db"])
    degradation_ab_db = max(ab_incoming_case["degradation_db"], ab_outgoing_case["degradation_db"])
    degradation_ba_db = max(ba_incoming_case["degradation_db"], ba_outgoing_case["degradation_db"])
    ci_ab_db = min(ab_incoming_case["ci_db"], ab_outgoing_case["ci_db"])
    ci_ba_db = min(ba_incoming_case["ci_db"], ba_outgoing_case["ci_db"])
    margin_ab_db = min(ab_incoming_case["margin_db"], ab_outgoing_case["margin_db"])
    margin_ba_db = min(ba_incoming_case["margin_db"], ba_outgoing_case["margin_db"])

    updated["md_db"] = md_db
    updated["nfd_db"] = nfd_db
    updated["spectral_coupling_db"] = -md_db
    updated["noise_request_dbm"] = noise_request_dbm
    updated["noise_existing_dbm"] = noise_existing_dbm
    updated["estimated_interference_victim_dbm"] = interference_victim_dbm
    updated["estimated_interference_aggressor_dbm"] = interference_aggressor_dbm
    updated["estimated_ci_victim_db"] = ci_victim_db
    updated["estimated_ci_aggressor_db"] = ci_aggressor_db
    updated["estimated_degradation_victim_db"] = degradation_victim_db
    updated["estimated_degradation_aggressor_db"] = degradation_aggressor_db
    updated["estimated_ci_ab_db"] = ci_ab_db
    updated["estimated_ci_ba_db"] = ci_ba_db
    updated["estimated_degradation_ab_db"] = degradation_ab_db
    updated["estimated_degradation_ba_db"] = degradation_ba_db
    updated["estimated_margin_ab_db"] = margin_ab_db
    updated["estimated_margin_ba_db"] = margin_ba_db
    updated["shared_site_cross_extra_isolation_db"] = extra_isolation_db
    return updated


@contextmanager
def patched_cross_isolation(extra_isolation_db: float, cross_delta_min_mhz: float):
    original = analysis_engine.estimate_interference_metrics

    def wrapped(request, candidate, link):
        metrics = original(request, candidate, link)
        return _adjust_metrics(metrics, extra_isolation_db, cross_delta_min_mhz)

    analysis_engine.estimate_interference_metrics = wrapped
    try:
        yield
    finally:
        analysis_engine.estimate_interference_metrics = original


def run_case(case_path: Path, extra_isolation_db: float, max_links: int, cross_delta_min_mhz: float) -> dict[str, Any]:
    request = parse_wlr_file(case_path)
    with patched_cross_isolation(extra_isolation_db, cross_delta_min_mhz):
        result = analysis_engine.analyze_wlr_request(request, max_links=max_links)
    assessment = requested_assessment(request, result)
    if assessment is None:
        return {"case": case_path.stem, "error": "requested assessment not found"}
    return {
        "case": case_path.stem,
        "status": assessment.status,
        "status_ab": assessment.status_ab,
        "status_ba": assessment.status_ba,
        "accepted_count": len(result.accepted_assessments),
        "conditional_count": len(result.conditional_assessments),
        "rejected_count": len(result.rejected_assessments),
        "rejection_reasons": list(getattr(assessment, "rejection_reasons", [])),
    }


def run_sample(limit_per_band: int, max_links: int, extra_isolation_db: float, cross_delta_min_mhz: float) -> dict[str, Any]:
    pairs = discover_pairs(Path("testy"))
    prepared, stats = prepare_cases(pairs, doc_cache={}, limit=None)
    selected = []
    per_band = defaultdict(int)
    for case in prepared:
        band = detect_band(case.request)
        if band not in {"23GHz", "38GHz", "80GHz"}:
            continue
        if per_band[band] >= limit_per_band:
            continue
        per_band[band] += 1
        selected.append((band, case))

    aggregate = defaultdict(lambda: {"cases": 0, "accepted": 0, "conditional": 0, "rejected": 0})
    rows = []
    with patched_cross_isolation(extra_isolation_db, cross_delta_min_mhz):
        for band, case in selected:
            result = analysis_engine.analyze_wlr_request(case.request, max_links=max_links)
            assessment = requested_assessment(case.request, result)
            if assessment is None:
                rows.append({"case": case.key, "band": band, "error": "requested assessment not found"})
                continue
            aggregate[band]["cases"] += 1
            aggregate[band][assessment.status.lower()] += 1
            rows.append(
                {
                    "case": case.key,
                    "band": band,
                    "expected_status": case.expected_status,
                    "current_status": assessment.status,
                }
            )
    return {
        "prepare_stats": stats,
        "selected_cases": len(selected),
        "bands": dict(aggregate),
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Experiment with extra shared-site cross-case isolation.")
    parser.add_argument("--case", action="append", default=[], help="Specific WLR path(s) to test.")
    parser.add_argument("--limit-per-band", type=int, default=6)
    parser.add_argument("--max-links", type=int, default=150)
    parser.add_argument("--cross-delta-min-mhz", type=float, default=5000.0)
    parser.add_argument("--levels", type=float, nargs="+", default=[0.0, 10.0, 20.0, 30.0, 40.0, 50.0])
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args()

    case_paths = [Path(p) for p in args.case]
    experiments = []
    for level in args.levels:
        row = {
            "extra_isolation_db": level,
            "cross_delta_min_mhz": args.cross_delta_min_mhz,
            "cases": [run_case(path, level, args.max_links, args.cross_delta_min_mhz) for path in case_paths],
            "sample": run_sample(args.limit_per_band, args.max_links, level, args.cross_delta_min_mhz),
        }
        experiments.append(row)

    output = {
        "base_engine_version": analysis_engine.ENGINE_VERSION,
        "experiments": experiments,
    }
    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
