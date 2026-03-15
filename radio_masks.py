from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional


MASKS_PATH = Path(__file__).resolve().parent / "data" / "uke_masks.json"


@lru_cache(maxsize=1)
def _load_rows() -> list[dict]:
    if not MASKS_PATH.exists():
        return []
    return json.loads(MASKS_PATH.read_text(encoding="utf-8"))


def _to_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def find_mask_row(freq_ghz: float, bw_mhz: float) -> Optional[dict]:
    rows = _load_rows()
    best: Optional[tuple[float, dict]] = None
    for row in rows:
        fd = _to_float(row.get("fd"))
        fg = _to_float(row.get("fg"))
        szer1 = _to_float(row.get("szer1"))
        szer2 = _to_float(row.get("szer2"))
        if fd is None or fg is None or szer1 is None or szer2 is None:
            continue
        if not (fd <= freq_ghz <= fg):
            continue
        if not (szer1 <= bw_mhz <= szer2):
            continue
        span_score = (fg - fd) + (szer2 - szer1)
        if best is None or span_score < best[0]:
            best = (span_score, row)
    return best[1] if best else None


def lookup_mask_discrimination_db(freq_ghz: float, bw_mhz: float, freq_delta_mhz: float) -> Optional[float]:
    row = find_mask_row(freq_ghz, bw_mhz)
    if not row:
        return None

    points: list[tuple[float, float]] = []
    for idx in range(1, 7):
        freq = _to_float(row.get(f"f{idx}"))
        att = _to_float(row.get(f"att{idx}"))
        if freq is None or att is None:
            continue
        points.append((freq, att))
    if not points:
        return None

    points.sort(key=lambda item: item[0])
    if freq_delta_mhz <= points[0][0]:
        return points[0][1]
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if freq_delta_mhz <= x2:
            ratio = (freq_delta_mhz - x1) / max(x2 - x1, 1e-9)
            return y1 + ratio * (y2 - y1)
    return points[-1][1]
