#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import analysis as analysis_engine  # noqa: E402
from wlr import parse_wlr_file  # noqa: E402


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _serialize_record(record) -> dict[str, object]:
    return {
        "channel_ab": record.channel_ab,
        "channel_ba": record.channel_ba,
        "polarization": record.polarization,
        "status": record.status,
        "score": record.score,
        "worst_duplex_margin_db": record.worst_duplex_margin_db,
        "uke_like_margnad_db": record.uke_like_margnad_db,
        "uke_like_margodb_db": record.uke_like_margodb_db,
        "access_fkand_jest_wynik_n": record.access_fkand_jest_wynik_n,
        "access_fkand_jest_wynik_o": record.access_fkand_jest_wynik_o,
        "access_fkand_margnad_db": record.access_fkand_margnad_db,
        "access_fkand_margodb_db": record.access_fkand_margodb_db,
        "access_fkand_n_nad": record.access_fkand_n_nad,
        "access_fkand_n_odb": record.access_fkand_n_odb,
        "access_fkand_update_notes": record.access_fkand_update_notes,
        "margnad_delta_vs_uke_like_db": _delta(record.access_fkand_margnad_db, record.uke_like_margnad_db),
        "margodb_delta_vs_uke_like_db": _delta(record.access_fkand_margodb_db, record.uke_like_margodb_db),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze experimental Access fkand-update model on a WLR case.")
    parser.add_argument("--wlr", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    wlr_path = Path(args.wlr).resolve()
    out_path = Path(args.out).resolve()

    request = parse_wlr_file(wlr_path)
    result = analysis_engine.analyze_wlr_request(request)

    requested = next(
        (
            record
            for record in result.candidate_frequency_records
            if record.channel_ab == request.channel_ab
            and record.channel_ba == request.channel_ba
            and record.polarization == request.requested_polarization
        ),
        None,
    )

    margnad_deltas = [
        delta
        for delta in (_delta(record.access_fkand_margnad_db, record.uke_like_margnad_db) for record in result.candidate_frequency_records)
        if delta is not None
    ]
    margodb_deltas = [
        delta
        for delta in (_delta(record.access_fkand_margodb_db, record.uke_like_margodb_db) for record in result.candidate_frequency_records)
        if delta is not None
    ]

    payload = {
        "wlr": str(wlr_path),
        "engine_version": analysis_engine.ENGINE_VERSION,
        "candidate_frequency_records_count": len(result.candidate_frequency_records),
        "requested_record": _serialize_record(requested) if requested else None,
        "top_candidates": [
            _serialize_record(record)
            for record in result.candidate_frequency_records[:10]
        ],
        "fkand_update_model_summary": {
            "records_with_jest_wynik_n": sum(1 for record in result.candidate_frequency_records if record.access_fkand_jest_wynik_n),
            "records_with_jest_wynik_o": sum(1 for record in result.candidate_frequency_records if record.access_fkand_jest_wynik_o),
            "records_with_n_nad_problems": sum(1 for record in result.candidate_frequency_records if record.access_fkand_n_nad > 0),
            "records_with_n_odb_problems": sum(1 for record in result.candidate_frequency_records if record.access_fkand_n_odb > 0),
            "margnad_delta_vs_uke_like_mean_db": round(statistics.mean(margnad_deltas), 6) if margnad_deltas else None,
            "margodb_delta_vs_uke_like_mean_db": round(statistics.mean(margodb_deltas), 6) if margodb_deltas else None,
            "margnad_delta_vs_uke_like_max_abs_db": round(max(abs(value) for value in margnad_deltas), 6) if margnad_deltas else None,
            "margodb_delta_vs_uke_like_max_abs_db": round(max(abs(value) for value in margodb_deltas), 6) if margodb_deltas else None,
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
