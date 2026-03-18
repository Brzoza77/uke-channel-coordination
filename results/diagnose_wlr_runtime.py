from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis import analyze_wlr_request
from uke import INTERNAL_SQLITE_PATH, _internal_catalog_query, get_source_summary, lookup_internal_radio_profile
from wlr import build_wlr_request_summary, parse_wlr_file


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return None


def _sqlite_signature(path: Path) -> dict[str, object]:
    stat = path.stat()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with sqlite3.connect(path) as con:
        table_count = con.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
        sample = con.execute(
            "select name from sqlite_master where type='table' order by name limit 8"
        ).fetchall()
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha,
        "table_count": table_count,
        "sample_tables": [row[0] for row in sample],
    }


def _record_digest(record) -> str:
    payload = {
        "channel_ab": record.channel_ab,
        "channel_ba": record.channel_ba,
        "polarization": record.polarization,
        "status": record.status,
        "status_ab": record.status_ab,
        "status_ba": record.status_ba,
        "score": round(record.score, 6),
        "red": record.pairwise_red_count,
        "blocking": record.pairwise_blocking_count,
        "worst_margin_ab_db": record.worst_margin_ab_db,
        "worst_margin_ba_db": record.worst_margin_ba_db,
        "gate_status": record.access_fkand_gate_status,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _catalog_digest(path: Path, limit: int = 5000) -> dict[str, object]:
    query = (
        _internal_catalog_query()
        + """
ORDER BY
    d.nrdecyzji,
    p.prz_s_o_id,
    p.czestotliwosc_przydzielona,
    COALESCE(st_n.operator, ''),
    COALESCE(st_o.operator, '')
LIMIT ?
"""
    )
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(query, (limit,)).fetchall()

    sample_rows = []
    h = hashlib.sha256()
    for row in rows:
        payload = {
            "permit_number": row["permit_number"],
            "span_id": row["span_id"],
            "assigned_frequency_ghz": row["assigned_frequency_ghz"],
            "plan_symbol": row["plan_symbol"],
            "tx_power_dbm": row["tx_power_dbm"],
            "tx_lat": row["tx_lat"],
            "tx_lon": row["tx_lon"],
            "rx_lat": row["rx_lat"],
            "rx_lon": row["rx_lon"],
            "tx_operator": row["tx_operator"],
            "rx_operator": row["rx_operator"],
            "typ_nadajnika": row["typ_nadajnika"],
            "radio_vendor": row["radio_vendor"],
            "tx_antenna_gain_dbi": row["tx_antenna_gain_dbi"],
            "rx_antenna_gain_dbi": row["rx_antenna_gain_dbi"],
        }
        h.update(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        if len(sample_rows) < 8:
            sample_rows.append(payload)
    return {
        "rows_hashed": len(rows),
        "sha256": h.hexdigest(),
        "sample_rows": sample_rows,
    }


def _candidate_links_snapshot(analysis, limit: int = 12) -> dict[str, object]:
    ordered = sorted(
        analysis.candidate_links,
        key=lambda link: (
            link.link_id,
            link.permit_number or "",
            link.site_a.point.lat_deg,
            link.site_a.point.lon_deg,
        ),
    )
    sample = []
    h = hashlib.sha256()
    for link in ordered:
        payload = {
            "link_id": link.link_id,
            "permit_number": link.permit_number,
            "operator_name": link.operator_name,
            "channel_ab": link.emission_ab.channel_number,
            "channel_ba": link.emission_ba.channel_number,
            "polarization": link.polarization,
            "site_a_lat": link.site_a.point.lat_deg,
            "site_a_lon": link.site_a.point.lon_deg,
            "site_b_lat": link.site_b.point.lat_deg,
            "site_b_lon": link.site_b.point.lon_deg,
        }
        h.update(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        if len(sample) < limit:
            sample.append(payload)
    return {
        "count": len(ordered),
        "sha256": h.hexdigest(),
        "sample": sample,
    }


def _pairwise_rows(record, limit: int = 20) -> list[dict[str, object]]:
    rows = []
    ordered = sorted(
        record.pairwise_results,
        key=lambda r: (
            r.direction,
            r.interfering_link_id or "",
            r.interfering_permit_number or "",
            r.conflict_type or "",
            r.relationship or "",
            -(r.degradation_db or 0.0),
        ),
    )
    for result in ordered[:limit]:
        rows.append(
            {
                "direction": result.direction,
                "link_id": result.interfering_link_id,
                "permit": result.interfering_permit_number,
                "operator": result.interfering_operator_name,
                "conflict_type": result.conflict_type,
                "relationship": result.relationship,
                "risk_level": result.risk_level,
                "distance_km": result.distance_km,
                "margin_db": result.margin_db,
                "ci_db": result.ci_db,
                "degradation_db": result.degradation_db,
                "overlap_ratio": result.overlap_ratio,
                "effective_freq_delta_mhz": result.effective_freq_delta_mhz,
                "is_blocking": result.is_blocking,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare deterministic runtime fingerprints for one WLR.")
    parser.add_argument("wlr", help="Path to .wlr file")
    parser.add_argument("--top", type=int, default=5, help="How many candidate rows to include")
    args = parser.parse_args()

    wlr_path = Path(args.wlr).resolve()
    request = parse_wlr_file(wlr_path)
    analysis = analyze_wlr_request(request)
    source = get_source_summary()
    radio_profile = lookup_internal_radio_profile(
        request.radio_type,
        request.radio_vendor,
        freqs_ghz=(request.freq_ab_ghz, request.freq_ba_ghz),
        channel_width_mhz=request.channel_width_mhz,
    )

    records = analysis.candidate_frequency_records[: args.top]
    top_candidates = []
    for record in records:
        top_candidates.append(
            {
                "channel": f"{record.channel_ab}/{record.channel_ba} {record.polarization}",
                "status": record.status,
                "status_ab": record.status_ab,
                "status_ba": record.status_ba,
                "score": round(record.score, 6),
                "pairwise_red_count": record.pairwise_red_count,
                "pairwise_blocking_count": record.pairwise_blocking_count,
                "worst_margin_ab_db": record.worst_margin_ab_db,
                "worst_margin_ba_db": record.worst_margin_ba_db,
                "gate_status": record.access_fkand_gate_status,
                "digest": _record_digest(record),
            }
        )

    best = analysis.candidate_frequency_records[0] if analysis.candidate_frequency_records else None
    payload = {
        "env": {
            "python": sys.version,
            "platform": platform.platform(),
            "sqlite_runtime": sqlite3.sqlite_version,
            "git_commit": _git_commit(),
        },
        "sqlite": _sqlite_signature(INTERNAL_SQLITE_PATH),
        "catalog_digest": _catalog_digest(INTERNAL_SQLITE_PATH),
        "source_summary": source,
        "request": build_wlr_request_summary(request),
        "request_radio_profile": (
            {
                "radio_id": radio_profile.radio_id,
                "radio_type": radio_profile.radio_type,
                "radio_vendor": radio_profile.radio_vendor,
                "rx_noise_figure_db": radio_profile.rx_noise_figure_db,
                "atpc_attenuation_db": radio_profile.atpc_attenuation_db,
                "receiver_bandwidth_mhz": radio_profile.receiver_bandwidth_mhz,
                "is_verified": radio_profile.is_verified,
            }
            if radio_profile is not None
            else None
        ),
        "analysis_summary": {
            "candidate_links_count": len(analysis.candidate_links),
            "candidate_frequency_records_count": len(analysis.candidate_frequency_records),
            "accepted_count": len(analysis.accepted_assessments),
            "conditional_count": len(analysis.conditional_assessments),
            "rejected_count": len(analysis.rejected_assessments),
        },
        "candidate_links_snapshot": _candidate_links_snapshot(analysis),
        "top_candidates": top_candidates,
        "best_candidate_pairwise": _pairwise_rows(best) if best is not None else [],
    }

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
