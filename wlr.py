from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
import re

from uke import get_plan_dataset


@dataclass(frozen=True)
class WlrEndpoint:
    name: Optional[str]
    city: Optional[str]
    street: Optional[str]
    postal_code: Optional[str]
    area_description: Optional[str]
    lon_deg: float
    lat_deg: float
    terrain_m_asl: Optional[float]
    antenna_height_m_agl: Optional[float]
    tx_power_dbm: Optional[float] = None
    antenna_gain_dbi: Optional[float] = None
    antenna_type: Optional[str] = None
    antenna_vendor: Optional[str] = None
    polarization_preferred: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WlrRequest:
    source_filename: str
    source_path: str
    upload_id: Optional[str]
    link_name: Optional[str]
    request_date: Optional[date]
    valid_until: Optional[date]
    site_a: WlrEndpoint
    site_b: WlrEndpoint
    freq_ab_ghz: Optional[float]
    freq_ba_ghz: Optional[float]
    channel_ab: Optional[str]
    channel_ba: Optional[str]
    plan_symbol: Optional[str]
    channel_width_mhz: Optional[float]
    requested_polarization: Optional[str]
    antenna_type: Optional[str]
    antenna_vendor: Optional[str]
    radio_type: Optional[str]
    radio_vendor: Optional[str]
    modulation: Optional[str]
    bitrate_mbps: Optional[float]
    path_length_km: Optional[float]
    duplex_count: Optional[int]
    raw_lines_count: int
    details: dict[str, Any] = field(default_factory=dict)


_DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
_POSTAL_RE = re.compile(r"^\d{2}-\d{3}$")
_LINK_NAME_RE = re.compile(r"[A-Z0-9]+(?:[\-_][A-Z0-9]+)*MW[A-Z0-9\-_]*", re.IGNORECASE)
_UPLOAD_ID_RE = re.compile(r"^([0-9a-f]{32})_(.+\.wlr)$", re.IGNORECASE)


class WlrParseError(ValueError):
    pass


def read_wlr_lines(path: Path) -> list[str]:
    for encoding in ("cp1250", "iso-8859-2", "utf-8", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = path.read_text(encoding="latin-1", errors="ignore")

    return [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]


def parse_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"null", "none", "nan", "-"}:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def parse_int(value: Optional[str]) -> Optional[int]:
    parsed = parse_float(value)
    if parsed is None:
        return None
    return int(parsed)


def parse_date(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def dms_to_decimal(deg: float, minutes: float, seconds: float) -> float:
    return deg + minutes / 60.0 + seconds / 3600.0


def nonempty_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if line]


def detect_upload_id(path: Path) -> Optional[str]:
    match = _UPLOAD_ID_RE.match(path.name)
    if not match:
        return None
    return match.group(1)


def original_filename_from_upload_name(path: Path) -> str:
    match = _UPLOAD_ID_RE.match(path.name)
    if not match:
        return path.name
    return match.group(2)


def normalize_lookup_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    text = value.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def find_antenna_gain_in_catalog(
    lines: list[str],
    antenna_type: Optional[str],
    antenna_vendor: Optional[str],
) -> Optional[float]:
    antenna_type_norm = normalize_lookup_text(antenna_type)
    antenna_vendor_norm = normalize_lookup_text(antenna_vendor)
    if not antenna_type_norm:
        return None

    best_gain: Optional[float] = None
    best_score = -1

    for index, line in enumerate(lines):
        if normalize_lookup_text(line) != antenna_type_norm:
            continue

        score = 1
        if antenna_vendor_norm:
            for probe in range(index + 1, min(index + 4, len(lines))):
                if normalize_lookup_text(lines[probe]) == antenna_vendor_norm:
                    score += 2
                    break

        numeric_values: list[float] = []
        for probe in range(index + 1, min(index + 20, len(lines))):
            try:
                value = parse_float(lines[probe])
            except ValueError:
                continue
            if value is None:
                continue
            numeric_values.append(value)
            if len(numeric_values) >= 8:
                break

        gain_candidate: Optional[float] = None
        if len(numeric_values) >= 6 and 0.0 <= numeric_values[5] <= 60.0:
            gain_candidate = numeric_values[5]
        else:
            for value in reversed(numeric_values[:8]):
                if 0.0 <= value <= 60.0:
                    gain_candidate = value
                    break

        if gain_candidate is None:
            continue

        if score > best_score:
            best_score = score
            best_gain = gain_candidate

    return best_gain


def resolve_uploaded_wlr_path(upload_id: str, uploads_dir: Path | str) -> Path:
    uploads_path = Path(uploads_dir)
    matches = sorted(uploads_path.glob(f"{upload_id}_*.wlr"))
    if not matches:
        raise FileNotFoundError(f"Nie znaleziono pliku WLR dla upload_id={upload_id}")
    if len(matches) > 1:
        raise WlrParseError(f"Znaleziono wiele plików WLR dla upload_id={upload_id}")
    return matches[0]


def find_link_name(lines: list[str], path: Path) -> str:
    for line in lines:
        if line.startswith("EMC_"):
            candidate = line[4:].strip()
            if candidate:
                return candidate

    for line in lines:
        if _LINK_NAME_RE.search(line):
            return line.strip()

    return original_filename_from_upload_name(path).rsplit(".", 1)[0]


def find_request_date(lines: list[str]) -> Optional[date]:
    for line in lines[:10]:
        if _DATE_RE.match(line):
            return parse_date(line)
    return None


def find_valid_until(lines: list[str]) -> Optional[date]:
    dates = [parse_date(line) for line in lines if _DATE_RE.match(line)]
    values = [value for value in dates if value is not None]
    if len(values) >= 2:
        return max(values[:-1]) if len(values) >= 3 else max(values)
    return values[0] if values else None


def find_duplex_anchor(lines: list[str]) -> int:
    for index in range(len(lines) - 8):
        if lines[index] != "1":
            continue
        if not lines[index + 1]:
            continue
        if not lines[index + 2]:
            continue
        if not _POSTAL_RE.match(lines[index + 3]):
            continue
        if parse_int(lines[index + 6]) is None or parse_int(lines[index + 7]) is None:
            continue
        return index
    raise WlrParseError("Nie udało się odnaleźć początku pierwszego przęsła dupleksowego")


def infer_plan_and_channels(
    freq_ab_ghz: Optional[float],
    freq_ba_ghz: Optional[float],
    channel_width_mhz: Optional[float],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if freq_ab_ghz is None and freq_ba_ghz is None:
        return None, None, None

    dataset = get_plan_dataset()
    tolerance_ghz = 0.001

    for symbol, plan in dataset.plans.items():
        if channel_width_mhz is not None and plan.channel_width_mhz is not None:
            if abs(plan.channel_width_mhz - channel_width_mhz) > 0.001:
                continue

        channel_ab = None
        channel_ba = None

        for channel in plan.channels:
            if freq_ab_ghz is not None and abs(channel.center_freq_ghz - freq_ab_ghz) <= tolerance_ghz:
                channel_ab = channel.channel_number
            if freq_ba_ghz is not None and abs(channel.center_freq_ghz - freq_ba_ghz) <= tolerance_ghz:
                channel_ba = channel.channel_number

        if (freq_ab_ghz is None or channel_ab is not None) and (freq_ba_ghz is None or channel_ba is not None):
            return symbol, channel_ab, channel_ba

    return None, None, None


def infer_legacy_radio_params(lines: list[str]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    candidates: list[tuple[int, float, float, float]] = []
    for idx in range(len(lines) - 2):
        freq_ab = parse_float(lines[idx])
        freq_ba = parse_float(lines[idx + 1])
        channel_width = parse_float(lines[idx + 2])

        if freq_ab is None or freq_ba is None or channel_width is None:
            continue
        if not (6.0 <= freq_ab <= 100.0 and 6.0 <= freq_ba <= 100.0):
            continue
        if not (10.0 <= channel_width <= 1000.0):
            continue
        if not (1.0 <= abs(freq_ab - freq_ba) <= 20.0):
            continue

        candidates.append((idx, freq_ab, freq_ba, channel_width))

    if not candidates:
        return None, None, None

    _, freq_ab, freq_ba, channel_width = max(candidates, key=lambda item: item[0])
    return freq_ab, freq_ba, channel_width


def build_endpoint_from_slice(
    values: list[str],
    *,
    antenna_type: Optional[str],
    antenna_vendor: Optional[str],
    polarization: Optional[str],
) -> WlrEndpoint:
    if len(values) < 15:
        raise WlrParseError("Za krótki blok stacji w przęśle WLR")

    city = values[0] or None
    street = values[1] or None
    postal_code = values[2] or None
    area_description = values[4] or None

    lon_deg = parse_float(values[6])
    lon_min = parse_float(values[7])
    lon_sec = parse_float(values[8])
    lat_deg = parse_float(values[9])
    lat_min = parse_float(values[10])
    lat_sec = parse_float(values[11])
    terrain_m_asl = parse_float(values[12])
    antenna_height_m_agl = parse_float(values[14])

    if None in {lon_deg, lon_min, lon_sec, lat_deg, lat_min, lat_sec}:
        raise WlrParseError("Niekompletny blok współrzędnych w stacji WLR")

    tx_power_dbm = parse_float(values[24]) if len(values) > 24 else None

    return WlrEndpoint(
        name=city,
        city=city,
        street=street,
        postal_code=postal_code,
        area_description=area_description,
        lon_deg=dms_to_decimal(lon_deg, lon_min, lon_sec),
        lat_deg=dms_to_decimal(lat_deg, lat_min, lat_sec),
        terrain_m_asl=terrain_m_asl,
        antenna_height_m_agl=antenna_height_m_agl,
        tx_power_dbm=tx_power_dbm,
        antenna_gain_dbi=None,
        antenna_type=antenna_type,
        antenna_vendor=antenna_vendor,
        polarization_preferred=polarization,
        details={
            "station_type": values[13] if len(values) > 13 else None,
            "raw_slice": values,
            "raw_tx_power_dbm": tx_power_dbm,
        },
    )


def parse_first_duplex_link(lines: list[str]) -> dict[str, Any]:
    anchor = find_duplex_anchor(lines)

    duplex_count = parse_int(lines[anchor])
    if duplex_count is None:
        raise WlrParseError("Brak liczby przęseł dupleksowych przy anchorze WLR")

    station_a_values = lines[anchor + 1:anchor + 30]
    station_b_values = lines[anchor + 30:anchor + 59]
    shared_values = lines[anchor + 59:]

    if len(station_a_values) < 29 or len(station_b_values) < 29:
        raise WlrParseError("Niepełny blok stacji A/B w pierwszym przęśle WLR")

    freq_ab_ghz = parse_float(station_a_values[22])
    pol_ab = station_a_values[23] or None
    tx_power_ab_dbm = parse_float(station_a_values[24])
    antenna_type_a = station_a_values[27] or None
    antenna_vendor_a = station_a_values[28] or None

    freq_ba_ghz = parse_float(station_b_values[22])
    pol_ba = station_b_values[23] or None
    tx_power_ba_dbm = parse_float(station_b_values[24])
    antenna_type_b = station_b_values[27] or None
    antenna_vendor_b = station_b_values[28] or None

    requested_polarization = pol_ab or pol_ba
    antenna_type = antenna_type_a or antenna_type_b
    antenna_vendor = antenna_vendor_a or antenna_vendor_b

    antenna_gain_a_dbi = find_antenna_gain_in_catalog(
        lines,
        antenna_type_a or antenna_type,
        antenna_vendor_a or antenna_vendor,
    )
    antenna_gain_b_dbi = find_antenna_gain_in_catalog(
        lines,
        antenna_type_b or antenna_type,
        antenna_vendor_b or antenna_vendor,
    )

    site_a = build_endpoint_from_slice(
        station_a_values,
        antenna_type=antenna_type_a or antenna_type,
        antenna_vendor=antenna_vendor_a or antenna_vendor,
        polarization=requested_polarization,
    )
    site_b = build_endpoint_from_slice(
        station_b_values,
        antenna_type=antenna_type_b or antenna_type,
        antenna_vendor=antenna_vendor_b or antenna_vendor,
        polarization=requested_polarization,
    )

    site_a = WlrEndpoint(
        **{
            **site_a.__dict__,
            "tx_power_dbm": tx_power_ab_dbm,
            "antenna_gain_dbi": antenna_gain_a_dbi,
        }
    )
    site_b = WlrEndpoint(
        **{
            **site_b.__dict__,
            "tx_power_dbm": tx_power_ba_dbm,
            "antenna_gain_dbi": antenna_gain_b_dbi,
        }
    )

    path_length_km = parse_float(shared_values[0]) if len(shared_values) >= 1 else None
    channel_width_mhz = parse_float(shared_values[3]) if len(shared_values) >= 4 else None
    modulation = shared_values[4] or None if len(shared_values) >= 5 else None
    bitrate_mbps = parse_float(shared_values[5]) if len(shared_values) >= 6 else None
    radio_type = shared_values[6] or None if len(shared_values) >= 7 else None
    radio_vendor = shared_values[7] or None if len(shared_values) >= 8 else None

    return {
        "duplex_anchor": anchor,
        "duplex_count": duplex_count,
        "site_a": site_a,
        "site_b": site_b,
        "freq_ab_ghz": freq_ab_ghz,
        "freq_ba_ghz": freq_ba_ghz,
        "requested_polarization": requested_polarization,
        "antenna_type": antenna_type,
        "antenna_vendor": antenna_vendor,
        "antenna_gain_a_dbi": antenna_gain_a_dbi,
        "antenna_gain_b_dbi": antenna_gain_b_dbi,
        "radio_type": radio_type,
        "radio_vendor": radio_vendor,
        "modulation": modulation,
        "bitrate_mbps": bitrate_mbps,
        "channel_width_mhz": channel_width_mhz,
        "path_length_km": path_length_km,
        "station_a_values": station_a_values,
        "station_b_values": station_b_values,
        "shared_values": shared_values[:16],
    }


def parse_wlr_file(path: Path | str) -> WlrRequest:
    source_path = Path(path)
    lines = read_wlr_lines(source_path)

    link_name = find_link_name(lines, source_path)
    request_date = find_request_date(lines)
    valid_until = find_valid_until(lines)
    upload_id = detect_upload_id(source_path)

    duplex = parse_first_duplex_link(lines)
    legacy_freq_ab, legacy_freq_ba, legacy_channel_width = infer_legacy_radio_params(lines)

    freq_ab = duplex["freq_ab_ghz"] if duplex["freq_ab_ghz"] is not None else legacy_freq_ab
    freq_ba = duplex["freq_ba_ghz"] if duplex["freq_ba_ghz"] is not None else legacy_freq_ba
    channel_width = (
        duplex["channel_width_mhz"]
        if duplex["channel_width_mhz"] is not None
        else legacy_channel_width
    )

    plan_symbol, channel_ab, channel_ba = infer_plan_and_channels(
        freq_ab,
        freq_ba,
        channel_width,
    )

    return WlrRequest(
        source_filename=original_filename_from_upload_name(source_path),
        source_path=str(source_path),
        upload_id=upload_id,
        link_name=link_name,
        request_date=request_date,
        valid_until=valid_until,
        site_a=duplex["site_a"],
        site_b=duplex["site_b"],
        freq_ab_ghz=freq_ab,
        freq_ba_ghz=freq_ba,
        channel_ab=channel_ab,
        channel_ba=channel_ba,
        plan_symbol=plan_symbol,
        channel_width_mhz=channel_width,
        requested_polarization=duplex["requested_polarization"],
        antenna_type=duplex["antenna_type"],
        antenna_vendor=duplex["antenna_vendor"],
        radio_type=duplex["radio_type"],
        radio_vendor=duplex["radio_vendor"],
        modulation=duplex["modulation"],
        bitrate_mbps=duplex["bitrate_mbps"],
        path_length_km=duplex["path_length_km"],
        duplex_count=duplex["duplex_count"],
        raw_lines_count=len(lines),
        details={
            "duplex_anchor": duplex["duplex_anchor"],
            "antenna_gain_a_dbi": duplex["antenna_gain_a_dbi"],
            "antenna_gain_b_dbi": duplex["antenna_gain_b_dbi"],
            "station_a_values": duplex["station_a_values"],
            "station_b_values": duplex["station_b_values"],
            "shared_values": duplex["shared_values"],
            "legacy_freq_ab_ghz": legacy_freq_ab,
            "legacy_freq_ba_ghz": legacy_freq_ba,
            "legacy_channel_width_mhz": legacy_channel_width,
        },
    )


def parse_uploaded_wlr(upload_id: str, uploads_dir: Path | str) -> WlrRequest:
    return parse_wlr_file(resolve_uploaded_wlr_path(upload_id, uploads_dir))


def build_wlr_request_summary(request: WlrRequest, upload_id: Optional[str] = None) -> dict[str, Any]:
    effective_upload_id = upload_id or request.upload_id
    return {
        "upload_id": effective_upload_id,
        "link_name": request.link_name,
        "plan_symbol": request.plan_symbol,
        "channel_width_mhz": request.channel_width_mhz,
        "requested_channel": f"{request.channel_ab or '?'} / {request.channel_ba or '?'}",
        "requested_polarization": request.requested_polarization,
        "freq_ab_ghz": request.freq_ab_ghz,
        "freq_ba_ghz": request.freq_ba_ghz,
        "modulation": request.modulation,
        "bitrate_mbps": request.bitrate_mbps,
        "radio_type": request.radio_type,
        "radio_vendor": request.radio_vendor,
        "path_length_km": request.path_length_km,
        "site_a": {
            "name": request.site_a.name,
            "lat_deg": request.site_a.lat_deg,
            "lon_deg": request.site_a.lon_deg,
            "terrain_m_asl": request.site_a.terrain_m_asl,
            "antenna_height_m_agl": request.site_a.antenna_height_m_agl,
            "tx_power_dbm": request.site_a.tx_power_dbm,
            "antenna_gain_dbi": request.site_a.antenna_gain_dbi,
            "antenna_type": request.site_a.antenna_type,
            "polarization_preferred": request.site_a.polarization_preferred,
        },
        "site_b": {
            "name": request.site_b.name,
            "lat_deg": request.site_b.lat_deg,
            "lon_deg": request.site_b.lon_deg,
            "terrain_m_asl": request.site_b.terrain_m_asl,
            "antenna_height_m_agl": request.site_b.antenna_height_m_agl,
            "tx_power_dbm": request.site_b.tx_power_dbm,
            "antenna_gain_dbi": request.site_b.antenna_gain_dbi,
            "antenna_type": request.site_b.antenna_type,
            "polarization_preferred": request.site_b.polarization_preferred,
        },
        "details": {
            "source_filename": request.source_filename,
            "source_path": request.source_path,
            "request_date": request.request_date.isoformat() if request.request_date else None,
            "valid_until": request.valid_until.isoformat() if request.valid_until else None,
            "duplex_count": request.duplex_count,
            "raw_lines_count": request.raw_lines_count,
        },
    }


if __name__ == "__main__":
    sample_path = Path("/home/brzoza/uke/BT11046A-MW17258B-001_20260310101844.wlr")
    parsed = parse_wlr_file(sample_path)
    print(build_wlr_request_summary(parsed))
