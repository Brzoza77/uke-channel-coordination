from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
DMS_RE = re.compile(r"^\s*(\d{1,3})([NSEW])(\d{1,2})'(\d{1,2}(?:\.\d+)?)''\s*$")


def clean_text(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = CONTROL_RE.sub("", value).strip()
    return text or None


def parse_dms(value: str | None) -> float | None:
    if not value:
        return None
    match = DMS_RE.match(value)
    if not match:
        return None
    degrees = float(match.group(1))
    hemisphere = match.group(2)
    minutes = float(match.group(3))
    seconds = float(match.group(4))
    decimal = degrees + minutes / 60.0 + seconds / 3600.0
    if hemisphere in {"S", "W"}:
        decimal *= -1.0
    return decimal


def to_pair_key(row: sqlite3.Row) -> tuple[Any, ...]:
    left = (
        row["end_n_city"],
        row["end_n_address"],
        row["end_n_lat"],
        row["end_n_lon"],
    )
    right = (
        row["end_o_city"],
        row["end_o_address"],
        row["end_o_lat"],
        row["end_o_lon"],
    )
    return tuple(sorted((left, right)))


def build_query() -> str:
    return """
    SELECT
        d.nrdecyzji AS permit_number,
        d.decyzja_id,
        d.id_pozwolenia,
        d.data_wydania,
        d.data_waznosci,
        p.prz_s_o_id AS span_id,
        p.wniosek_id,
        p.numer_prz_s_a AS span_number_in_request,
        p.numer_kana_u AS channel_label,
        p.polaryzacja,
        p.czestotliwosc_przydzielona AS assigned_frequency_ghz,
        p.numer_planu AS plan_id,
        pl.symbol_planu AS plan_symbol,
        pl.odstep_kanalowy AS channel_spacing_mhz,
        pl.odstep_nadawania_i_odbioru AS duplex_spacing_mhz,
        p.status_koordynacji,
        p.moc_nadajnika AS tx_power_dbm,
        p.t_umienie_cyrkulator_w_n AS circ_loss_n_db,
        p.t_umienie_cyrkulator_w_o AS circ_loss_o_db,
        p.nadajnik_id,
        za_n.zastosowana_antena_id AS applied_antenna_n_id,
        za_n.antena_id AS antenna_catalog_n_id,
        za_n.stacja_id AS station_n_id,
        za_n.h_anteny AS antenna_height_n_m,
        za_n.kierunek_maksymalnego_promieniowania AS antenna_bearing_n_deg,
        za_n.kat_elewacji AS antenna_tilt_n_deg,
        st_n.konstrukcja_id AS structure_n_id,
        ob_n.obiekt_stacji_id AS site_n_id,
        ob_n.miejscowo AS end_n_city,
        ob_n.ulica_i_numer AS end_n_address,
        ob_n.gmina AS end_n_gmina,
        ob_n.gmina_kod_gus AS end_n_gmina_code,
        ob_n.symbol_obiektu AS end_n_symbol,
        k_n.h_terenu AS terrain_height_n_m,
        k_n.szer_geo AS end_n_lat,
        k_n.dlug_geo AS end_n_lon,
        za_o.zastosowana_antena_id AS applied_antenna_o_id,
        za_o.antena_id AS antenna_catalog_o_id,
        za_o.stacja_id AS station_o_id,
        za_o.h_anteny AS antenna_height_o_m,
        za_o.kierunek_maksymalnego_promieniowania AS antenna_bearing_o_deg,
        za_o.kat_elewacji AS antenna_tilt_o_deg,
        st_o.konstrukcja_id AS structure_o_id,
        ob_o.obiekt_stacji_id AS site_o_id,
        ob_o.miejscowo AS end_o_city,
        ob_o.ulica_i_numer AS end_o_address,
        ob_o.gmina AS end_o_gmina,
        ob_o.gmina_kod_gus AS end_o_gmina_code,
        ob_o.symbol_obiektu AS end_o_symbol,
        k_o.h_terenu AS terrain_height_o_m,
        k_o.szer_geo AS end_o_lat,
        k_o.dlug_geo AS end_o_lon,
        p.t_dane_koor,
        p.r_dane_koor
    FROM lr_konsultacja_349__decyzja d
    JOIN lr_konsultacja_349__przeslo_decyzji pd
      ON pd.decyzja_id = d.decyzja_id
    JOIN lr_konsultacja_349__przeslo p
      ON p.prz_s_o_id = pd.prz_s_o_id
    LEFT JOIN lr_konsultacja_349__plan pl
      ON pl.plan_id = p.numer_planu
    LEFT JOIN lr_konsultacja_349__zastosowana_antena za_n
      ON za_n.zastosowana_antena_id = p.antena_stacji_n_id
    LEFT JOIN lr_konsultacja_349__stacja st_n
      ON st_n.stacja_id = za_n.stacja_id
    LEFT JOIN lr_konsultacja_349__konstrukcja k_n
      ON k_n.konstrukcja_id = st_n.konstrukcja_id
    LEFT JOIN lr_konsultacja_349__obiekt_stacji ob_n
      ON ob_n.obiekt_stacji_id = k_n.obiekt_stacji_id
    LEFT JOIN lr_konsultacja_349__zastosowana_antena za_o
      ON za_o.zastosowana_antena_id = p.antena_stacji_o_id
    LEFT JOIN lr_konsultacja_349__stacja st_o
      ON st_o.stacja_id = za_o.stacja_id
    LEFT JOIN lr_konsultacja_349__konstrukcja k_o
      ON k_o.konstrukcja_id = st_o.konstrukcja_id
    LEFT JOIN lr_konsultacja_349__obiekt_stacji ob_o
      ON ob_o.obiekt_stacji_id = k_o.obiekt_stacji_id
    """


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Buduje lekki katalog linków UKE bezpośrednio z rdzenia `_349` w SQLite."
    )
    parser.add_argument("--sqlite", default="data/uke_workflow.sqlite")
    parser.add_argument("--permit", nargs="*", default=[])
    parser.add_argument("--plan-symbol")
    parser.add_argument("--min-frequency", type=float)
    parser.add_argument("--max-frequency", type=float)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--out-json")
    parser.add_argument("--out-csv")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).resolve()
    out_json = Path(args.out_json).resolve() if args.out_json else None
    out_csv = Path(args.out_csv).resolve() if args.out_csv else None

    with sqlite3.connect(sqlite_path) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        query = build_query()
        clauses: list[str] = []
        params: list[Any] = []
        if args.permit:
            placeholders = ",".join("?" for _ in args.permit)
            clauses.append(f"d.nrdecyzji IN ({placeholders})")
            params.extend(args.permit)
        if args.plan_symbol:
            clauses.append("pl.symbol_planu = ?")
            params.append(args.plan_symbol)
        if args.min_frequency is not None:
            clauses.append("p.czestotliwosc_przydzielona >= ?")
            params.append(args.min_frequency)
        if args.max_frequency is not None:
            clauses.append("p.czestotliwosc_przydzielona <= ?")
            params.append(args.max_frequency)
        if clauses:
            query += "\nWHERE " + " AND ".join(clauses)
        query += "\nORDER BY d.nrdecyzji, p.prz_s_o_id"
        if args.limit:
            query += f"\nLIMIT {int(args.limit)}"

        rows = cur.execute(query, params).fetchall()

    records: list[dict[str, Any]] = []
    for row in rows:
        record = {key: clean_text(row[key]) for key in row.keys()}
        record["end_n_lat_decimal"] = parse_dms(record["end_n_lat"])
        record["end_n_lon_decimal"] = parse_dms(record["end_n_lon"])
        record["end_o_lat_decimal"] = parse_dms(record["end_o_lat"])
        record["end_o_lon_decimal"] = parse_dms(record["end_o_lon"])
        record["duplex_pair_key"] = list(to_pair_key(row))
        records.append(record)

    summary = {
        "sqlite": str(sqlite_path),
        "row_count": len(records),
        "distinct_permits": len({r["permit_number"] for r in records}),
        "distinct_spans": len({r["span_id"] for r in records}),
        "distinct_pairs": len({tuple(tuple(x) for x in r["duplex_pair_key"]) for r in records}),
        "filters": {
            "permit": args.permit,
            "plan_symbol": args.plan_symbol,
            "min_frequency": args.min_frequency,
            "max_frequency": args.max_frequency,
            "limit": args.limit,
        },
    }
    payload = {"summary": summary, "records": records}

    if out_json:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if out_csv:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        if records:
            with out_csv.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(records[0].keys()))
                writer.writeheader()
                writer.writerows(records)
        else:
            out_csv.write_text("", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
