#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


PREFIX_SCHEMA = [
    "role",
    "freq_ghz",
    "service_code",
    "coordination_mode",
    "path_type",
    "duplex_mode",
    "band_code",
    "date_compact",
    "station_label",
    "country_code",
    "coord_compact",
    "terrain_m_asl",
    "bandwidth_label",
    "radio_vendor",
    "radio_type",
    "fixed_zero_1",
]


POST_MASK_SCHEMA = [
    "reserved_mask_gap_1",
    "reserved_mask_gap_2",
    "channel_width_mhz",
    "tx_power_dbw",
    "atpc_db",
    "main_azimuth_deg",
    "main_elevation_deg",
    "polarization",
    "noise_floor_dbw",
    "circulator_loss_db",
    "antenna_height_m_agl",
    "reserved_1",
    "family_code",
    "reserved_2",
    "reserved_3",
    "antenna_id",
    "antenna_vendor",
    "antenna_type",
    "antenna_fd_ghz",
    "antenna_fg_ghz",
    "antenna_gain_dbi",
    "copol_code",
    "copol_count",
]


def _as_float(value: str) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _parse_pattern(values: list[str], start_index: int) -> tuple[dict[str, Any], int]:
    code = values[start_index - 1] if start_index - 1 < len(values) else ""
    count_value = values[start_index] if start_index < len(values) else ""
    count = int(_as_float(count_value) or 0)
    pairs: list[dict[str, Any]] = []
    cursor = start_index + 1
    for _ in range(count):
        if cursor + 1 >= len(values):
            break
        pairs.append(
            {
                "angle_deg": _as_float(values[cursor]),
                "attenuation_db": _as_float(values[cursor + 1]),
            }
        )
        cursor += 2
    return {"code": code, "count": count, "pairs": pairs}, cursor


def parse_payload(payload: str, kind: str) -> dict[str, Any]:
    values = (payload or "").split(";")
    result: dict[str, Any] = {"raw_count": len(values), "kind": kind}

    for index, key in enumerate(PREFIX_SCHEMA, start=1):
        result[key] = values[index - 1] if index - 1 < len(values) else ""

    mask_pairs = []
    cursor = len(PREFIX_SCHEMA) + 1
    for idx in range(6):
        freq_key = f"{kind}_mask_f{idx + 1}_mhz"
        att_key = f"{kind}_mask_a{idx + 1}_db"
        result[freq_key] = values[cursor - 1] if cursor - 1 < len(values) else ""
        result[att_key] = values[cursor] if cursor < len(values) else ""
        mask_pairs.append(
            {
                "index": idx + 1,
                "freq_mhz": _as_float(result[freq_key]),
                "attenuation_db": _as_float(result[att_key]),
            }
        )
        cursor += 2
    result["radio_mask_pairs"] = mask_pairs

    for offset, key in enumerate(POST_MASK_SCHEMA):
        position = cursor + offset
        result[key] = values[position - 1] if position - 1 < len(values) else ""

    copol_start = cursor + len(POST_MASK_SCHEMA) - 2
    copol, next_index = _parse_pattern(values, copol_start)
    crosspol, final_index = _parse_pattern(values, next_index + 1)
    result["copol_pattern"] = copol
    result["crosspol_pattern"] = crosspol
    result["pattern_parse_end_index"] = final_index

    numeric_keys = [
        "freq_ghz",
        "mask_bw_mhz",
        "channel_width_mhz",
        "tx_power_dbw",
        "atpc_db",
        "main_azimuth_deg",
        "main_elevation_deg",
        "noise_floor_dbw",
        "circulator_loss_db",
        "antenna_height_m_agl",
        "antenna_fd_ghz",
        "antenna_fg_ghz",
        "antenna_gain_dbi",
    ]
    for key in numeric_keys:
        result[f"{key}_num"] = _as_float(result.get(key, ""))

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Decode Access EMC coordinate payloads from Czestotliwosc kandydujaca.")
    parser.add_argument("--sqlite", default="data/uke_workflow.sqlite")
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=4)
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).resolve()
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT
            fkandydujaca_id,
            prz_s_o_id,
            numer_przesla,
            numer_pary_f,
            plan,
            numer_czestotliwosci,
            kod_nadawczej,
            polaryzacja,
            wartosc_czestotliwosci,
            t_dane_koor,
            r_dane_koor
        FROM lr_konsultacja_349__czestotliwosc_kandydujaca
        ORDER BY fkandydujaca_id
        LIMIT ?
        """,
        (args.limit,),
    ).fetchall()
    con.close()

    decoded_rows = []
    for row in rows:
        decoded_rows.append(
            {
                "fkandydujaca_id": row["fkandydujaca_id"],
                "przeslo_id": row["prz_s_o_id"],
                "numer_przesla": row["numer_przesla"],
                "numer_pary_f": row["numer_pary_f"],
                "plan": row["plan"],
                "numer_czestotliwosci": row["numer_czestotliwosci"],
                "kod_nadawczej": row["kod_nadawczej"],
                "polaryzacja": row["polaryzacja"],
                "wartosc_czestotliwosci": row["wartosc_czestotliwosci"],
                "tx_payload": parse_payload(row["t_dane_koor"], "tx"),
                "rx_payload": parse_payload(row["r_dane_koor"], "rx"),
            }
        )

    payload = {
        "sqlite": str(sqlite_path),
        "limit": args.limit,
        "schema": {
            "prefix": PREFIX_SCHEMA,
            "post_mask": POST_MASK_SCHEMA,
            "mask_pair_count": 6,
            "patterns_start_at_index_1_based": len(PREFIX_SCHEMA) + 12 + len(POST_MASK_SCHEMA) - 1,
        },
        "notes": [
            "Payloads are semicolon-delimited strings exported by Access QueryDefs ExportTx_przeslo / ExportRx_przeslo.",
            "tx_power_dbw and noise_floor_dbw are in dBW-like units, matching Access formulas such as [Moc_nadajnika]-30 and 10*log10(BW_MHz)-144+NF.",
            "copol_pattern and crosspol_pattern are decoded from the antenna characteristic tail of the payload.",
        ],
        "rows": decoded_rows,
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
