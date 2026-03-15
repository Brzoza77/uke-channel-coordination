from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sqlite3
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CATALOG_PATH = BASE_DIR / "data" / "antenna_catalog.sqlite"


def _normalize_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return " ".join(value.strip().lower().split())


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

    with sqlite3.connect(db_path) as conn:
        best_band = conn.execute(
            """
            SELECT ab.band_id
            FROM antenna_bands ab
            JOIN antennas a ON a.antenna_id = ab.antenna_id
            JOIN producers p ON p.producer_id = a.producer_id
            WHERE lower(a.antenna_type) = ?
              AND lower(p.producer_name) = ?
              AND ab.freq_low_ghz <= ?
              AND ab.freq_high_ghz >= ?
            ORDER BY
              ABS(((ab.freq_low_ghz + ab.freq_high_ghz) / 2.0) - ?),
              COALESCE(ab.gain_dbi, 0.0) DESC,
              ab.band_id
            LIMIT 1
            """,
            (
                antenna_type,
                vendor,
                rounded_freq_mhz / 1000.0,
                rounded_freq_mhz / 1000.0,
                rounded_freq_mhz / 1000.0,
            ),
        ).fetchone()

        if best_band is None:
            return ()

        rows = conn.execute(
            """
            SELECT azimuth_deg, MIN(attenuation_db) AS attenuation_db
            FROM pattern_points
            WHERE band_id = ?
            GROUP BY azimuth_deg
            ORDER BY azimuth_deg
            """,
            (int(best_band[0]),),
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
