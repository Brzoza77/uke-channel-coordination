from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from wlr import parse_wlr_file  # noqa: E402

STOP_TOKENS = {
    "warszawa",
    "ul",
    "al",
    "aleja",
    "gen",
    "jozefa",
    "plac",
    "pl",
    "powiat",
    "im",
    "sw",
}

CORRECTIONS = {
    "pawba": "pawla",
    "zajczka": "zajaczka",
    "powzkowska": "powazkowska",
    "zwitojanska": "swietojanska",
    "zwitojad": "swietojan",
}


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    for src, dst in CORRECTIONS.items():
        text = text.replace(src, dst)
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    return " ".join(text.split())


def meaningful_tokens(value: str) -> list[str]:
    return [token for token in normalize_text(value).split() if token not in STOP_TOKENS]


def address_matches(left: str, right: str) -> bool:
    left_tokens = set(meaningful_tokens(left))
    right_tokens = set(meaningful_tokens(right))
    if not left_tokens or not right_tokens:
        return False
    left_numbers = {token for token in left_tokens if any(ch.isdigit() for ch in token)}
    right_numbers = {token for token in right_tokens if any(ch.isdigit() for ch in token)}
    left_words = {token for token in left_tokens if not any(ch.isdigit() for ch in token)}
    right_words = {token for token in right_tokens if not any(ch.isdigit() for ch in token)}
    number_ok = not left_numbers or not right_numbers or bool(left_numbers & right_numbers)
    word_overlap = len(left_words & right_words)
    return number_ok and word_overlap >= 1


def classify_request_side(label: str, request_a: str, request_b: str) -> str:
    if address_matches(label, request_a):
        return "req_a"
    if address_matches(label, request_b):
        return "req_b"
    return "other"


def main() -> None:
    parser = argparse.ArgumentParser(description="Infer DOC row to EMC subcase mapping patterns.")
    parser.add_argument("--wlr", required=True)
    parser.add_argument("--alignment-json", required=True)
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args()

    request = parse_wlr_file(Path(args.wlr).resolve())
    request_a = f"{request.site_a.city} {request.site_a.street}".strip()
    request_b = f"{request.site_b.city} {request.site_b.street}".strip()

    with Path(args.alignment_json).resolve().open("r", encoding="utf-8") as fh:
        alignment = json.load(fh)

    grouped: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
    permit_grouped: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)

    for permit, payload in alignment["permits"].items():
        for row in payload["rows"]:
            row_request_side = classify_request_side(row.get("uke_station", ""), request_a, request_b)
            site_a_request_side = classify_request_side(row.get("site_a_label", ""), request_a, request_b)
            site_b_request_side = classify_request_side(row.get("site_b_label", ""), request_a, request_b)
            key = (
                row.get("direction", ""),
                row.get("section", ""),
                row.get("station_side", ""),
                row_request_side,
                site_a_request_side,
                site_b_request_side,
            )
            grouped[key].append(
                {
                    "permit": permit,
                    "channel": row.get("channel"),
                    "polarization": row.get("polarization"),
                    "uke_station": row.get("uke_station"),
                    "best_subcase_key": row.get("best_subcase_key"),
                    "best_subcase_delta_db": row.get("best_subcase_delta_db"),
                }
            )
            permit_grouped[(permit, *key)].append(
                {
                    "permit": permit,
                    "channel": row.get("channel"),
                    "polarization": row.get("polarization"),
                    "uke_station": row.get("uke_station"),
                    "best_subcase_key": row.get("best_subcase_key"),
                    "best_subcase_delta_db": row.get("best_subcase_delta_db"),
                }
            )

    patterns: list[dict[str, object]] = []
    stable_rules: list[dict[str, object]] = []
    ambiguous_rules: list[dict[str, object]] = []
    permit_stable_rules: list[dict[str, object]] = []

    for key, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        counter = Counter(row["best_subcase_key"] for row in rows)
        best_subcase, best_count = counter.most_common(1)[0]
        total = len(rows)
        confidence = best_count / total
        avg_abs_delta = sum(abs(float(row["best_subcase_delta_db"] or 0.0)) for row in rows) / total
        pattern_payload = {
            "pattern": {
                "direction": key[0],
                "section": key[1],
                "station_side": key[2],
                "row_request_side": key[3],
                "permit_site_a_request_side": key[4],
                "permit_site_b_request_side": key[5],
            },
            "row_count": total,
            "best_subcase_counter": dict(counter),
            "majority_subcase": best_subcase,
            "majority_count": best_count,
            "majority_share": round(confidence, 6),
            "avg_abs_best_delta_db": round(avg_abs_delta, 6),
            "permits": sorted({str(row['permit']) for row in rows}),
            "sample_rows": rows[:5],
        }
        patterns.append(pattern_payload)
        if total >= 3 and confidence >= 0.7:
            stable_rules.append(pattern_payload)
        elif total >= 3:
            ambiguous_rules.append(pattern_payload)

    for key, rows in sorted(permit_grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        permit = key[0]
        pattern_key = key[1:]
        counter = Counter(row["best_subcase_key"] for row in rows)
        best_subcase, best_count = counter.most_common(1)[0]
        total = len(rows)
        confidence = best_count / total
        avg_abs_delta = sum(abs(float(row["best_subcase_delta_db"] or 0.0)) for row in rows) / total
        if total < 2 or confidence < 1.0:
            continue
        permit_stable_rules.append(
            {
                "permit": permit,
                "pattern": {
                    "direction": pattern_key[0],
                    "section": pattern_key[1],
                    "station_side": pattern_key[2],
                    "row_request_side": pattern_key[3],
                    "permit_site_a_request_side": pattern_key[4],
                    "permit_site_b_request_side": pattern_key[5],
                },
                "row_count": total,
                "best_subcase_counter": dict(counter),
                "majority_subcase": best_subcase,
                "majority_count": best_count,
                "majority_share": round(confidence, 6),
                "avg_abs_best_delta_db": round(avg_abs_delta, 6),
                "sample_rows": rows[:5],
            }
        )

    payload = {
        "case": alignment.get("case"),
        "engine_version": alignment.get("engine_version"),
        "request": {
            "site_a": request_a,
            "site_b": request_b,
        },
        "pattern_count": len(patterns),
        "stable_rule_count": len(stable_rules),
        "ambiguous_rule_count": len(ambiguous_rules),
        "permit_stable_rule_count": len(permit_stable_rules),
        "stable_rules": stable_rules,
        "ambiguous_rules": ambiguous_rules,
        "permit_stable_rules": permit_stable_rules,
        "patterns": patterns,
    }

    out_path = Path(args.out_json).resolve()
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
