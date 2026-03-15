from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def fnum(value: str) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def pick_engine_value(row: dict[str, str], *keys: str) -> float:
    for key in keys:
        preferred = row.get(key, "")
        if preferred not in {"", None}:
            return fnum(preferred)
    return 0.0


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def mae(values: list[float]) -> float:
    return mean([abs(value) for value in values]) if values else 0.0


def rmse(values: list[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(value * value for value in values) / len(values))


def bias(values: list[float]) -> float:
    return mean(values)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize UKE vs engine degradation gaps for a rerun CSV.")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-csv", required=True)
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve()
    out_json = Path(args.out_json).resolve()
    out_csv = Path(args.out_csv).resolve()

    rows = load_rows(csv_path)

    by_permit: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_variant: dict[tuple[str, str, str, str, str], list[dict[str, str]]] = defaultdict(list)

    victim_gaps: list[float] = []
    aggressor_gaps: list[float] = []
    found_rows = 0

    for row in rows:
        permit = row["uke_link_permit"]
        by_permit[permit].append(row)
        by_variant[
            (
                permit,
                row["direction"],
                row["channel"],
                row["polarization"],
                row["section"],
            )
        ].append(row)

        if row["engine_conflict_found"] == "True":
            found_rows += 1
            uke_value = fnum(row["uke_link_degradation_db"])
            case_aligned_value = pick_engine_value(
                row,
                "engine_mapped_aligned_db",
                "engine_station_aligned_db",
                "engine_case_aligned_db",
                "engine_victim_db",
            )
            victim_gaps.append(uke_value - case_aligned_value)
            aggressor_gaps.append(uke_value - fnum(row["engine_aggressor_db"]))

    permit_rows: list[dict[str, object]] = []
    for permit, items in sorted(by_permit.items()):
        victim_local: list[float] = []
        aggressor_local: list[float] = []
        sections = sorted({item["section"] for item in items})
        directions = sorted({item["direction"] for item in items})
        polarizations = sorted({item["polarization"] for item in items})
        channels = sorted({item["channel"] for item in items})

        for item in items:
            if item["engine_conflict_found"] != "True":
                continue
            uke_value = fnum(item["uke_link_degradation_db"])
            case_aligned_value = pick_engine_value(
                item,
                "engine_mapped_aligned_db",
                "engine_station_aligned_db",
                "engine_case_aligned_db",
                "engine_victim_db",
            )
            victim_local.append(uke_value - case_aligned_value)
            aggressor_local.append(uke_value - fnum(item["engine_aggressor_db"]))

        permit_rows.append(
            {
                "permit": permit,
                "rows": len(items),
                "sections": ",".join(sections),
                "directions": ",".join(directions),
                "polarizations": ",".join(polarizations),
                "channels": ",".join(channels),
                "uke_max_db": round(max(fnum(item["uke_link_degradation_db"]) for item in items), 6),
                "engine_victim_max_db": round(max(pick_engine_value(item, "engine_mapped_aligned_db", "engine_station_aligned_db", "engine_case_aligned_db", "engine_victim_db") for item in items), 6),
                "engine_aggressor_max_db": round(max(fnum(item["engine_aggressor_db"]) for item in items), 6),
                "victim_gap_bias_db": round(bias(victim_local), 6),
                "victim_gap_mae_db": round(mae(victim_local), 6),
                "victim_gap_rmse_db": round(rmse(victim_local), 6),
                "aggressor_gap_bias_db": round(bias(aggressor_local), 6),
                "aggressor_gap_mae_db": round(mae(aggressor_local), 6),
                "aggressor_gap_rmse_db": round(rmse(aggressor_local), 6),
            }
        )

    variant_rows: list[dict[str, object]] = []
    for key, items in sorted(by_variant.items()):
        permit, direction, channel, polarization, section = key
        uke_value = max(fnum(item["uke_link_degradation_db"]) for item in items)
        victim_value = max(pick_engine_value(item, "engine_mapped_aligned_db", "engine_station_aligned_db", "engine_case_aligned_db", "engine_victim_db") for item in items)
        aggressor_value = max(fnum(item["engine_aggressor_db"]) for item in items)
        variant_rows.append(
            {
                "permit": permit,
                "direction": direction,
                "channel": channel,
                "polarization": polarization,
                "section": section,
                "uke_db": round(uke_value, 6),
                "engine_victim_db": round(victim_value, 6),
                "engine_aggressor_db": round(aggressor_value, 6),
                "victim_gap_db": round(uke_value - victim_value, 6),
                "aggressor_gap_db": round(uke_value - aggressor_value, 6),
            }
        )

    permit_rows.sort(key=lambda row: row["victim_gap_mae_db"], reverse=True)

    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = list(permit_rows[0].keys()) if permit_rows else []
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(permit_rows)

    summary = {
        "source_csv": str(csv_path),
        "rows_total": len(rows),
        "rows_with_matched_conflict": found_rows,
        "permit_rows": len(permit_rows),
        "overall": {
            "victim_gap_bias_db": round(bias(victim_gaps), 6),
            "victim_gap_mae_db": round(mae(victim_gaps), 6),
            "victim_gap_rmse_db": round(rmse(victim_gaps), 6),
            "aggressor_gap_bias_db": round(bias(aggressor_gaps), 6),
            "aggressor_gap_mae_db": round(mae(aggressor_gaps), 6),
            "aggressor_gap_rmse_db": round(rmse(aggressor_gaps), 6),
        },
        "worst_permits_by_victim_mae": permit_rows[:10],
        "worst_variants_by_victim_gap": sorted(variant_rows, key=lambda row: row["victim_gap_db"], reverse=True)[:15],
        "worst_variants_by_aggressor_gap": sorted(variant_rows, key=lambda row: row["aggressor_gap_db"], reverse=True)[:15],
        "notes": [
            "gap = UKE degradation minus engine degradation",
            "positive gap means the engine is too mild",
            "negative gap means the engine is more restrictive than UKE",
        ],
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
