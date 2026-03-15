from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import analysis as analysis_engine  # noqa: E402
from wlr import parse_wlr_file  # noqa: E402

ORIGINAL_FILTER_FN = analysis_engine._empirical_filter_discrimination_db


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def mask_eband_250_discrimination_db(freq_delta_mhz: float, bw_mhz: float, overlap_ratio: float) -> float:
    if overlap_ratio >= 0.95 or freq_delta_mhz <= 1e-6:
        return 0.0
    if abs(bw_mhz - 250.0) > 1e-6:
        return ORIGINAL_FILTER_FN(freq_delta_mhz, bw_mhz, overlap_ratio)

    # Raw interpretation of MDB table `maski`, row ID 81 for 60-100 GHz, width 0..250 MHz:
    # 250 MHz -> 0 dB, 300 MHz -> 40 dB, then hold 40 dB.
    points = [(250.0, 0.0), (300.0, 40.0)]
    if freq_delta_mhz <= points[0][0]:
        return points[0][1]
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if freq_delta_mhz <= x2:
            ratio = (freq_delta_mhz - x1) / max(x2 - x1, 1e-9)
            return y1 + ratio * (y2 - y1)
    return points[-1][1]


def run_rerun(base_csv: Path, wlr_path: Path, out_csv: Path, out_json: Path) -> dict:
    from results.rerun_case_from_csv import update_rows  # type: ignore

    rows = load_rows(base_csv)
    request = parse_wlr_file(wlr_path)
    result = analysis_engine.analyze_wlr_request(request)
    updated_rows = update_rows(rows, result.channel_assessments)

    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(updated_rows[0].keys()))
        writer.writeheader()
        writer.writerows(updated_rows)

    summary = {
        "case": wlr_path.stem,
        "engine_version": getattr(analysis_engine, "ENGINE_VERSION", "unknown"),
        "mode": "experiment_eband_250_masks",
        "rows_total": len(updated_rows),
        "accepted_count": len(result.accepted_assessments),
        "conditional_count": len(result.conditional_assessments),
        "rejected_count": len(result.rejected_assessments),
        "out_csv": str(out_csv),
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Experiment with raw MDB maski for E-band 250 MHz.")
    parser.add_argument("--wlr", required=True)
    parser.add_argument("--base-csv", required=True)
    parser.add_argument("--out-csv", required=True)
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args()

    base_csv = Path(args.base_csv).resolve()
    wlr_path = Path(args.wlr).resolve()
    out_csv = Path(args.out_csv).resolve()
    out_json = Path(args.out_json).resolve()

    analysis_engine._empirical_filter_discrimination_db = mask_eband_250_discrimination_db
    try:
        summary = run_rerun(base_csv, wlr_path, out_csv, out_json)
    finally:
        analysis_engine._empirical_filter_discrimination_db = ORIGINAL_FILTER_FN

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
