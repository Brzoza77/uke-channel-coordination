from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import analysis as analysis_engine  # noqa: E402
from analysis import ChannelAssessment, ConflictAssessment  # noqa: E402
from wlr import parse_wlr_file  # noqa: E402


def sum_degradation_db(values: list[float]) -> float:
    ratios_sum = 0.0
    for value in values:
        ratios_sum += max(0.0, 10.0 ** (value / 10.0) - 1.0)
    return 10.0 * math.log10(1.0 + ratios_sum) if ratios_sum > 0.0 else 0.0


def find_assessment(
    assessments: list[ChannelAssessment],
    direction: str,
    channel: str,
    freq_ghz: float,
    polarization: str,
) -> Optional[ChannelAssessment]:
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
) -> Optional[ConflictAssessment]:
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


def _normalize_station_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = text.replace("pawba", "pawla")
    text = text.replace("zajczka", "zajaczka")
    text = text.replace("powzkowska", "powazkowska")
    text = text.replace("zwitoja", "swietoja")
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    return " ".join(text.split())


def _station_matches(row_station: str, site_station: str) -> bool:
    row_norm = _normalize_station_text(row_station)
    site_norm = _normalize_station_text(site_station)
    if not row_norm or not site_norm:
        return False
    return row_norm in site_norm or site_norm in row_norm


_STOP_TOKENS = {
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


def _meaningful_tokens(value: str) -> list[str]:
    return [token for token in _normalize_station_text(value).split() if token not in _STOP_TOKENS]


def _address_matches(left: str, right: str) -> bool:
    left_tokens = set(_meaningful_tokens(left))
    right_tokens = set(_meaningful_tokens(right))
    if not left_tokens or not right_tokens:
        return False
    left_numbers = {token for token in left_tokens if any(ch.isdigit() for ch in token)}
    right_numbers = {token for token in right_tokens if any(ch.isdigit() for ch in token)}
    left_words = {token for token in left_tokens if not any(ch.isdigit() for ch in token)}
    right_words = {token for token in right_tokens if not any(ch.isdigit() for ch in token)}
    number_ok = not left_numbers or not right_numbers or bool(left_numbers & right_numbers)
    return number_ok and len(left_words & right_words) >= 1


def _classify_request_side(label: str, request_a_label: str, request_b_label: str) -> str:
    if _address_matches(label, request_a_label):
        return "req_a"
    if _address_matches(label, request_b_label):
        return "req_b"
    return "other"


def _row_case_key(direction: str, section: str) -> str:
    if direction == "A -> B":
        return "ab_incoming_case" if section == "incoming" else "ab_outgoing_case"
    return "ba_incoming_case" if section == "incoming" else "ba_outgoing_case"


def _station_aware_case_key(row: dict[str, str], conflict: ConflictAssessment) -> str:
    direction = row["direction"]
    section = row["section"]
    row_station = row.get("uke_link_station", "")
    details = conflict.details or {}
    site_a_label = details.get("site_a_station_label", "")
    site_b_label = details.get("site_b_station_label", "")
    station_is_a = _station_matches(row_station, site_a_label)
    station_is_b = _station_matches(row_station, site_b_label)

    if direction == "A -> B":
        if section == "incoming":
            if station_is_a:
                return "ab_incoming_direct"
            if station_is_b:
                return "ab_incoming_cross"
        else:
            if station_is_b:
                return "ab_outgoing_direct"
            if station_is_a:
                return "ab_outgoing_cross"
    else:
        if section == "incoming":
            if station_is_b:
                return "ba_incoming_direct"
            if station_is_a:
                return "ba_incoming_cross"
        else:
            if station_is_a:
                return "ba_outgoing_direct"
            if station_is_b:
                return "ba_outgoing_cross"

    return _row_case_key(direction, section)


def _load_mapping_rules(path: Optional[Path]) -> dict[str, list[dict[str, object]]]:
    if not path or not path.exists():
        return {"exact": [], "family": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    exact_rules = list(payload.get("stable_rules", []))
    family_rules: list[dict[str, object]] = []
    for rule in payload.get("ambiguous_rules", []):
        counter = Counter()
        for subcase, count in (rule.get("best_subcase_counter") or {}).items():
            family = "cross" if str(subcase).endswith("cross") else "direct" if str(subcase).endswith("direct") else ""
            if family:
                counter[family] += int(count)
        if not counter:
            continue
        family, family_count = counter.most_common(1)[0]
        row_count = int(rule.get("row_count") or 0)
        share = (family_count / row_count) if row_count else 0.0
        if row_count >= 4 and share >= 0.75:
            family_rules.append(
                {
                    "pattern": rule.get("pattern", {}),
                    "majority_family": family,
                    "family_share": share,
                    "row_count": row_count,
                }
            )
    return {"exact": exact_rules, "family": family_rules}


def _mapped_case_key(
    row: dict[str, str],
    conflict: ConflictAssessment,
    request_a_label: str,
    request_b_label: str,
    mapping_rules: dict[str, list[dict[str, object]]],
) -> str:
    if not conflict:
        return ""

    details = conflict.details or {}
    pattern = {
        "direction": row.get("direction", ""),
        "section": row.get("section", ""),
        "station_side": "unknown",
        "row_request_side": _classify_request_side(row.get("uke_link_station", ""), request_a_label, request_b_label),
        "permit_site_a_request_side": _classify_request_side(
            details.get("site_a_station_label", ""), request_a_label, request_b_label
        ),
        "permit_site_b_request_side": _classify_request_side(
            details.get("site_b_station_label", ""), request_a_label, request_b_label
        ),
    }

    row_station = row.get("uke_link_station", "")
    if _station_matches(row_station, details.get("site_a_station_label", "")):
        pattern["station_side"] = "site_a"
    elif _station_matches(row_station, details.get("site_b_station_label", "")):
        pattern["station_side"] = "site_b"

    for rule in mapping_rules.get("exact", []):
        if rule.get("pattern") == pattern:
            return str(rule.get("majority_subcase") or "")

    for rule in mapping_rules.get("family", []):
        if rule.get("pattern") != pattern:
            continue
        family = str(rule.get("majority_family") or "")
        family_candidates = []
        for key, case_data in details.items():
            if not isinstance(case_data, dict):
                continue
            if family == "cross" and not str(key).endswith("cross"):
                continue
            if family == "direct" and not str(key).endswith("direct"):
                continue
            family_candidates.append((float(case_data.get("degradation_db", 0.0)), str(key)))
        if family_candidates:
            family_candidates.sort(reverse=True)
            return family_candidates[0][1]

    return _station_aware_case_key(row, conflict)


def update_rows(
    rows: list[dict[str, str]],
    assessments: list[ChannelAssessment],
    request_a_label: str,
    request_b_label: str,
    mapping_rules: dict[str, list[dict[str, object]]],
) -> list[dict[str, str]]:
    grouped_conflicts: dict[tuple[str, str, str, str, str], list[ConflictAssessment]] = {}
    for row in rows:
        key = (
            row["direction"],
            row["channel"],
            row["freq_ghz"],
            row["polarization"],
            row["plan_symbol"],
        )
        assessment = find_assessment(
            assessments=assessments,
            direction=row["direction"],
            channel=row["channel"],
            freq_ghz=float(row["freq_ghz"]),
            polarization=row["polarization"],
        )
        conflicts = assessment.conflicts if assessment else []
        grouped_conflicts[key] = conflicts

        row["engine_assessment_status"] = assessment.status if assessment else ""
        row["engine_status_ab"] = assessment.status_ab if assessment else ""
        row["engine_status_ba"] = assessment.status_ba if assessment else ""
        row["engine_candidate_channel_ab"] = assessment.candidate.channel_ab if assessment else ""
        row["engine_candidate_channel_ba"] = assessment.candidate.channel_ba if assessment else ""

        engine_conflict = match_engine_conflict(conflicts, row["uke_link_permit"]) if assessment else None
        row["engine_conflict_found"] = str(engine_conflict is not None)
        row["engine_conflict_link_id"] = engine_conflict.link_id if engine_conflict else ""
        row["engine_conflict_operator"] = engine_conflict.operator_name if engine_conflict else ""
        row["engine_conflict_permit"] = engine_conflict.permit_number if engine_conflict else ""
        case_key = _row_case_key(row["direction"], row["section"])
        station_case_key = _station_aware_case_key(row, engine_conflict) if engine_conflict else ""
        mapped_case_key = (
            _mapped_case_key(row, engine_conflict, request_a_label, request_b_label, mapping_rules)
            if engine_conflict
            else ""
        )
        row["engine_case_key"] = case_key if engine_conflict else ""
        row["engine_station_case_key"] = station_case_key if engine_conflict else ""
        row["engine_mapped_case_key"] = mapped_case_key if engine_conflict else ""
        row["engine_victim_db"] = (
            f"{(engine_conflict.estimated_degradation_victim_db or 0.0):.6f}" if engine_conflict else ""
        )
        row["engine_aggressor_db"] = (
            f"{(engine_conflict.estimated_degradation_aggressor_db or 0.0):.6f}" if engine_conflict else ""
        )
        row["engine_ci_victim_db"] = f"{(engine_conflict.estimated_ci_victim_db or 0.0):.6f}" if engine_conflict else ""
        row["engine_ci_aggressor_db"] = (
            f"{(engine_conflict.estimated_ci_aggressor_db or 0.0):.6f}" if engine_conflict else ""
        )
        row["engine_margin_ab_db"] = f"{(engine_conflict.estimated_margin_ab_db or 0.0):.6f}" if engine_conflict else ""
        row["engine_margin_ba_db"] = f"{(engine_conflict.estimated_margin_ba_db or 0.0):.6f}" if engine_conflict else ""
        row["engine_effective_freq_delta_mhz"] = (
            f"{(engine_conflict.effective_freq_delta_mhz or 0.0):.6f}" if engine_conflict else ""
        )
        row["engine_overlap_ab_ratio"] = f"{(engine_conflict.overlap_ab_ratio or 0.0):.6f}" if engine_conflict else ""
        row["engine_overlap_ba_ratio"] = f"{(engine_conflict.overlap_ba_ratio or 0.0):.6f}" if engine_conflict else ""
        case_data = engine_conflict.details.get(case_key, {}) if engine_conflict else {}
        station_case_data = engine_conflict.details.get(station_case_key, {}) if engine_conflict else {}
        mapped_case_data = engine_conflict.details.get(mapped_case_key, {}) if engine_conflict else {}
        row["engine_case_aligned_db"] = f"{float(case_data.get('degradation_db', 0.0)):.6f}" if engine_conflict else ""
        row["engine_case_aligned_ci_db"] = f"{float(case_data.get('ci_db', 0.0)):.6f}" if engine_conflict else ""
        row["engine_case_aligned_margin_db"] = f"{float(case_data.get('margin_db', 0.0)):.6f}" if engine_conflict else ""
        row["engine_station_aligned_db"] = f"{float(station_case_data.get('degradation_db', 0.0)):.6f}" if engine_conflict else ""
        row["engine_station_aligned_ci_db"] = f"{float(station_case_data.get('ci_db', 0.0)):.6f}" if engine_conflict else ""
        row["engine_station_aligned_margin_db"] = f"{float(station_case_data.get('margin_db', 0.0)):.6f}" if engine_conflict else ""
        row["engine_mapped_aligned_db"] = f"{float(mapped_case_data.get('degradation_db', 0.0)):.6f}" if engine_conflict else ""
        row["engine_mapped_aligned_ci_db"] = f"{float(mapped_case_data.get('ci_db', 0.0)):.6f}" if engine_conflict else ""
        row["engine_mapped_aligned_margin_db"] = f"{float(mapped_case_data.get('margin_db', 0.0)):.6f}" if engine_conflict else ""

    for row in rows:
        key = (
            row["direction"],
            row["channel"],
            row["freq_ghz"],
            row["polarization"],
            row["plan_symbol"],
        )
        conflicts = grouped_conflicts.get(key, [])
        total_victim = sum_degradation_db([conflict.estimated_degradation_victim_db or 0.0 for conflict in conflicts])
        total_aggressor = sum_degradation_db(
            [conflict.estimated_degradation_aggressor_db or 0.0 for conflict in conflicts]
        )
        row["engine_total_victim_db"] = f"{total_victim:.6f}"
        row["engine_total_aggressor_db"] = f"{total_aggressor:.6f}"

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute engine columns for a case using an existing UKE CSV.")
    parser.add_argument("--wlr", required=True)
    parser.add_argument("--base-csv", required=True)
    parser.add_argument("--out-csv", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--mapping-rules-json")
    args = parser.parse_args()

    wlr_path = Path(args.wlr).resolve()
    base_csv = Path(args.base_csv).resolve()
    out_csv = Path(args.out_csv).resolve()
    out_json = Path(args.out_json).resolve()

    with base_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fieldnames = reader.fieldnames or []
    extra_fieldnames = [
        "engine_margin_ab_db",
        "engine_margin_ba_db",
        "engine_case_key",
        "engine_case_aligned_db",
        "engine_case_aligned_ci_db",
        "engine_case_aligned_margin_db",
        "engine_station_case_key",
        "engine_station_aligned_db",
        "engine_station_aligned_ci_db",
        "engine_station_aligned_margin_db",
        "engine_mapped_case_key",
        "engine_mapped_aligned_db",
        "engine_mapped_aligned_ci_db",
        "engine_mapped_aligned_margin_db",
    ]
    for name in extra_fieldnames:
        if name not in fieldnames:
            fieldnames.append(name)

    request = parse_wlr_file(wlr_path)
    analysis_result = analysis_engine.analyze_wlr_request(request)
    mapping_rules = _load_mapping_rules(Path(args.mapping_rules_json).resolve()) if args.mapping_rules_json else []
    request_a_label = f"{request.site_a.city} {request.site_a.street}".strip()
    request_b_label = f"{request.site_b.city} {request.site_b.street}".strip()
    updated_rows = update_rows(
        rows,
        analysis_result.channel_assessments,
        request_a_label,
        request_b_label,
        mapping_rules,
    )
    requested_assessment = find_assessment(
        assessments=analysis_result.channel_assessments,
        direction="A -> B",
        channel=request.channel_ba,
        freq_ghz=request.freq_ba_ghz,
        polarization=request.requested_polarization,
    )

    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated_rows)

    summary = {
        "case": wlr_path.stem,
        "engine_version": getattr(analysis_engine, "ENGINE_VERSION", "unknown"),
        "rows_total": len(updated_rows),
        "accepted_count": len(analysis_result.accepted_assessments),
        "conditional_count": len(analysis_result.conditional_assessments),
        "rejected_count": len(analysis_result.rejected_assessments),
        "requested_status": requested_assessment.status if requested_assessment else None,
        "requested_status_ab": requested_assessment.status_ab if requested_assessment else None,
        "requested_status_ba": requested_assessment.status_ba if requested_assessment else None,
        "requested_margin_ab_db": min(
            (
                conflict.estimated_margin_ab_db
                for conflict in (requested_assessment.conflicts if requested_assessment else [])
                if conflict.estimated_margin_ab_db is not None
            ),
            default=None,
        ),
        "requested_margin_ba_db": min(
            (
                conflict.estimated_margin_ba_db
                for conflict in (requested_assessment.conflicts if requested_assessment else [])
                if conflict.estimated_margin_ba_db is not None
            ),
            default=None,
        ),
        "out_csv": str(out_csv),
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
