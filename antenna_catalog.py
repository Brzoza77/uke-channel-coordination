from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
import sqlite3
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CATALOG_PATH = BASE_DIR / "data" / "antenna_catalog.sqlite"


def _normalize_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return " ".join(value.strip().lower().split())


def _normalize_vendor_key(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "", _normalize_text(value))


def _normalize_antenna_type_tokens(value: Optional[str]) -> tuple[str, ...]:
    tokens = re.findall(r"[a-z0-9.]+", _normalize_text(value))
    normalized: list[str] = []
    for token in tokens:
        if token in {"c"}:
            continue
        if token in {"hpx", "hpy"}:
            token = "hp"
        if token == "wr":
            continue
        if not normalized or normalized[-1] != token:
            normalized.append(token)
    return tuple(normalized)


def _normalize_antenna_type_key(value: Optional[str]) -> str:
    return "".join(_normalize_antenna_type_tokens(value))


def _vendor_match_score(query_vendor: str, candidate_vendor: str) -> int:
    if not query_vendor or not candidate_vendor:
        return 0
    if query_vendor == candidate_vendor:
        return 1000
    if query_vendor in candidate_vendor or candidate_vendor in query_vendor:
        return 100
    return 0


def _antenna_type_match_score(
    query_tokens: tuple[str, ...],
    query_key: str,
    candidate_tokens: tuple[str, ...],
    candidate_key: str,
) -> int:
    if not query_tokens or not candidate_tokens:
        return 0
    if query_key == candidate_key:
        return 2000

    score = 0
    if query_tokens[0] == candidate_tokens[0]:
        score += 300

    shared = set(query_tokens) & set(candidate_tokens)
    score += len(shared) * 40

    if query_tokens[-1] == candidate_tokens[-1]:
        score += 40

    score -= abs(len(query_tokens) - len(candidate_tokens)) * 5
    return max(score, 0)


def catalog_exists(path: Path | str = DEFAULT_CATALOG_PATH) -> bool:
    return Path(path).exists()


@lru_cache(maxsize=256)
def _load_pattern_points(
    antenna_type: str,
    vendor: str,
    rounded_freq_mhz: int,
    catalog_path: str,
) -> tuple[tuple[float, float], ...]:
    db_path = Path(catalog_path)
    if not db_path.exists():
        return ()

    query_type_key = _normalize_antenna_type_key(antenna_type)
    query_type_tokens = _normalize_antenna_type_tokens(antenna_type)
    query_vendor_key = _normalize_vendor_key(vendor)

    with sqlite3.connect(db_path) as conn:
        candidate_rows = conn.execute(
            """
            SELECT
              ab.band_id,
              a.antenna_type,
              p.producer_name,
              ABS(((ab.freq_low_ghz + ab.freq_high_ghz) / 2.0) - ?) AS freq_distance,
              COALESCE(ab.gain_dbi, 0.0) AS gain_dbi
            FROM antenna_bands ab
            JOIN antennas a ON a.antenna_id = ab.antenna_id
            JOIN producers p ON p.producer_id = a.producer_id
            WHERE ab.freq_low_ghz <= ?
              AND ab.freq_high_ghz >= ?
            """,
            (
                rounded_freq_mhz / 1000.0,
                rounded_freq_mhz / 1000.0,
                rounded_freq_mhz / 1000.0,
            ),
        ).fetchall()

        scored_rows: list[tuple[int, int, float, float, int]] = []
        for band_id, candidate_type, candidate_vendor, freq_distance, gain_dbi in candidate_rows:
            vendor_score = _vendor_match_score(query_vendor_key, _normalize_vendor_key(candidate_vendor))
            if vendor_score <= 0:
                continue
            type_tokens = _normalize_antenna_type_tokens(candidate_type)
            type_key = _normalize_antenna_type_key(candidate_type)
            type_score = _antenna_type_match_score(query_type_tokens, query_type_key, type_tokens, type_key)
            if type_score <= 0:
                continue
            scored_rows.append((vendor_score, type_score, -float(freq_distance), float(gain_dbi), int(band_id)))

        if not scored_rows:
            return ()

        best_band_id = sorted(
            scored_rows,
            key=lambda item: (-item[0], -item[1], -item[2], -item[3], item[4]),
        )[0][4]

        rows = conn.execute(
            """
            SELECT azimuth_deg, MIN(attenuation_db) AS attenuation_db
            FROM pattern_points
            WHERE band_id = ?
            GROUP BY azimuth_deg
            ORDER BY azimuth_deg
            """,
            (best_band_id,),
        ).fetchall()

    if not rows:
        return ()
    return tuple((float(angle), float(value)) for angle, value in rows)


def lookup_pattern_points(
    antenna_type: Optional[str],
    vendor: Optional[str],
    freq_ghz: Optional[float],
    catalog_path: Path | str = DEFAULT_CATALOG_PATH,
) -> tuple[tuple[float, float], ...]:
    norm_type = _normalize_text(antenna_type)
    norm_vendor = _normalize_text(vendor)
    if not norm_type or not norm_vendor or freq_ghz is None:
        return ()
    return _load_pattern_points(
        norm_type,
        norm_vendor,
        int(round(freq_ghz * 1000.0)),
        str(Path(catalog_path)),
    )


def interpolate_attenuation_db(
    antenna_type: Optional[str],
    vendor: Optional[str],
    freq_ghz: Optional[float],
    off_axis_deg: float,
    catalog_path: Path | str = DEFAULT_CATALOG_PATH,
) -> Optional[float]:
    points = lookup_pattern_points(antenna_type, vendor, freq_ghz, catalog_path=catalog_path)
    if not points:
        return None

    angle = abs(off_axis_deg) % 360.0
    if angle > 180.0:
        angle = 360.0 - angle

    if angle <= points[0][0]:
        return points[0][1]
    if angle >= points[-1][0]:
        return points[-1][1]

    for index in range(1, len(points)):
        left_angle, left_value = points[index - 1]
        right_angle, right_value = points[index]
        if angle > right_angle:
            continue
        span = max(right_angle - left_angle, 1e-9)
        ratio = (angle - left_angle) / span
        return left_value + (right_value - left_value) * ratio

    return points[-1][1]
