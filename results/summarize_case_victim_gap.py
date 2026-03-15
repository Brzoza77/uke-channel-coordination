from __future__ import annotations

import argparse
import csv
import json
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize UKE vs engine victim-side gap for a rerun CSV.")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-csv", required=True)
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve()
    out_json = Path(args.out_json).resolve()
    out_csv = Path(args.out_csv).resolve()

    rows = load_rows(csv_path)

    by_variant_permit: dict[tuple[str, str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    by_permit: dict[str, list[dict[str, str]]] = defaultdict(list)

    for row in rows:
        key = (
            row["uke_link_permit"],
            row["direction"],
            row["channel"],
            row["polarization"],
            row["section"],
        )
        by_variant_permit[key].append(row)
        by_permit[row["uke_link_permit"]].append(row)

    variant_rows: list[dict[str, object]] = []
    for key, items in sorted(by_variant_permit.items()):
        permit, direction, channel, polarization, section = key
        uke_max = max(fnum(item["uke_link_degradation_db"]) for item in items)
        victim_max = max(fnum(item["engine_victim_db"]) for item in items)
        aggressor_max = max(fnum(item["engine_aggressor_db"]) for item in items)
        variant_rows.append(
            {
                "permit": permit,
                "direction": direction,
                "channel": channel,
                "polarization": polarization,
                "section": section,
                "rows": len(items),
                "uke_max_db": round(uke_max, 6),
                "engine_victim_max_db": round(victim_max, 6),
                "engine_aggressor_max_db": round(aggressor_max, 6),
                "victim_gap_db": round(uke_max - victim_max, 6),
                "aggressor_gap_db": round(uke_max - aggressor_max, 6),
            }
        )

    permit_rows: list[dict[str, object]] = []
    for permit, items in sorted(by_permit.items()):
        uke_max = max(fnum(item["uke_link_degradation_db"]) for item in items)
        uke_avg = sum(fnum(item["uke_link_degradation_db"]) for item in items) / len(items)
        victim_max = max(fnum(item["engine_victim_db"]) for item in items)
        aggressor_max = max(fnum(item["engine_aggressor_db"]) for item in items)
        permit_rows.append(
            {
                "permit": permit,
                "rows": len(items),
                "uke_max_db": round(uke_max, 6),
                "uke_avg_db": round(uke_avg, 6),
                "engine_victim_max_db": round(victim_max, 6),
                "engine_aggressor_max_db": round(aggressor_max, 6),
                "victim_gap_db": round(uke_max - victim_max, 6),
                "aggressor_gap_db": round(uke_max - aggressor_max, 6),
            }
        )

    worst_victim_variant = sorted(variant_rows, key=lambda row: row["victim_gap_db"], reverse=True)[:20]
    strongest_uke_variants = sorted(variant_rows, key=lambda row: row["uke_max_db"], reverse=True)[:20]
    worst_victim_permits = sorted(permit_rows, key=lambda row: row["victim_gap_db"], reverse=True)

    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = list(variant_rows[0].keys()) if variant_rows else []
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(variant_rows)

    summary = {
        "source_csv": str(csv_path),
        "variant_rows": len(variant_rows),
        "permit_rows": len(permit_rows),
        "worst_victim_permits": worst_victim_permits[:10],
        "worst_victim_variants": worst_victim_variant,
        "strongest_uke_variants": strongest_uke_variants,
        "notes": [
            "victim_gap_db = UKE degradation minus engine_victim_db",
            "positive victim_gap_db means engine underestimates victim-side degradation",
        ],
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
