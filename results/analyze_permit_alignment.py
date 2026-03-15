from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import analysis as analysis_engine  # noqa: E402
from analysis import ChannelAssessment, ConflictAssessment  # noqa: E402
from wlr import parse_wlr_file  # noqa: E402


def normalize_station_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    return " ".join(text.split())


def station_matches(row_station: str, site_station: str) -> bool:
    row_norm = normalize_station_text(row_station)
    site_norm = normalize_station_text(site_station)
    if not row_norm or not site_norm:
        return False
    return row_norm in site_norm or site_norm in row_norm


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def find_assessment(
    assessments: list[ChannelAssessment],
    direction: str,
    channel: str,
    freq_ghz: float,
    polarization: str,
) -> ChannelAssessment | None:
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
) -> ConflictAssessment | None:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze DOC-to-EMC alignment for selected permit numbers.")
    parser.add_argument("--wlr", required=True)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--permits", nargs="+", required=True)
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args()

    wlr_path = Path(args.wlr).resolve()
    csv_path = Path(args.csv).resolve()
    out_json = Path(args.out_json).resolve()

    request = parse_wlr_file(wlr_path)
    result = analysis_engine.analyze_wlr_request(request)
    rows = load_csv_rows(csv_path)
    permits = set(args.permits)

    per_permit: dict[str, list[dict[str, object]]] = defaultdict(list)
    summary_counter: dict[str, Counter] = defaultdict(Counter)

    for row in rows:
        permit = row["uke_link_permit"]
        if permit not in permits:
            continue
        assessment = find_assessment(
            assessments=result.channel_assessments,
            direction=row["direction"],
            channel=row["channel"],
            freq_ghz=float(row["freq_ghz"]),
            polarization=row["polarization"],
        )
        if assessment is None:
            continue
        conflict = match_engine_conflict(assessment.conflicts, permit)
        if conflict is None:
            continue

        details = conflict.details or {}
        site_a_label = details.get("site_a_station_label", "")
        site_b_label = details.get("site_b_station_label", "")
        row_station = row.get("uke_link_station", "")
        station_side = "unknown"
        if station_matches(row_station, site_a_label):
            station_side = "site_a"
        elif station_matches(row_station, site_b_label):
            station_side = "site_b"

        subcases = {}
        for key in (
            "ab_incoming_direct",
            "ab_incoming_cross",
            "ab_outgoing_direct",
            "ab_outgoing_cross",
            "ba_incoming_direct",
            "ba_incoming_cross",
            "ba_outgoing_direct",
            "ba_outgoing_cross",
        ):
            case_data = details.get(key, {}) or {}
            degradation_db = float(case_data.get("degradation_db", 0.0))
            subcases[key] = {
                "degradation_db": round(degradation_db, 6),
                "delta_to_uke_db": round(float(row["uke_link_degradation_db"]) - degradation_db, 6),
                "ci_db": round(float(case_data.get("ci_db", 0.0)), 6),
                "margin_db": round(float(case_data.get("margin_db", 0.0)), 6),
            }

        best_subcase_key = min(
            subcases,
            key=lambda key: abs(subcases[key]["delta_to_uke_db"]),
        )
        summary_counter[permit][best_subcase_key] += 1
        summary_counter[permit][f"station_side:{station_side}"] += 1
        summary_counter[permit][f"direction:{row['direction']}:{row['section']}"] += 1

        per_permit[permit].append(
            {
                "direction": row["direction"],
                "section": row["section"],
                "channel": row["channel"],
                "polarization": row["polarization"],
                "uke_station": row_station,
                "station_side": station_side,
                "site_a_label": site_a_label,
                "site_b_label": site_b_label,
                "uke_degradation_db": float(row["uke_link_degradation_db"]),
                "best_subcase_key": best_subcase_key,
                "best_subcase_delta_db": subcases[best_subcase_key]["delta_to_uke_db"],
                "subcases": subcases,
            }
        )

    payload = {
        "case": wlr_path.stem,
        "engine_version": analysis_engine.ENGINE_VERSION,
        "permits": {
            permit: {
                "summary_counter": dict(summary_counter[permit]),
                "rows": per_permit[permit],
            }
            for permit in sorted(per_permit)
        },
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
