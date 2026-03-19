from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional, Callable
import re
import pickle
import sqlite3

import subprocess

from antenna_catalog import DEFAULT_CATALOG_PATH, catalog_exists


BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / ".cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_FILE = CACHE_DIR / "permissions_cache.pkl"
INTERNAL_SQLITE_PATH = BASE_DIR / "data" / "uke_workflow.sqlite"
INTERNAL_REQUIRED_TABLES = (
    "lr_konsultacja_349__decyzja",
    "lr_konsultacja_349__przeslo_decyzji",
    "lr_konsultacja_349__przeslo",
    "lr_konsultacja_349__zastosowana_antena",
    "lr_konsultacja_349__stacja",
    "lr_konsultacja_349__konstrukcja",
    "lr_konsultacja_349__obiekt_stacji",
    "lr_konsultacja_349__plan",
    "lr_konsultacja_349__nadajnik",
    "lr_konsultacja_349__pasmo_anteny",
    "lr_konsultacja_349__antena",
    "lr_konsultacja_349__producent",
)

PLAN_DIR = BASE_DIR / "plany"
PLANS_CACHE_FILE = CACHE_DIR / "plans_cache.pkl"


HEADER_ALIASES = {
    "L.p.": "lp",
    "Dl_geo_Tx": "dl_geo_tx",
    "Sz_geo_Tx": "sz_geo_tx",
    "H_t_Tx [m npm]": "terrain_tx_m_asl",
    "Miejscowość Tx": "city_tx",
    "Województwo Tx": "province_tx",
    "Ulica Tx": "street_tx",
    "Opis położenia Tx": "location_desc_tx",
    "Dl_geo_Rx": "dl_geo_rx",
    "Sz_geo_Rx": "sz_geo_rx",
    "H_t_Rx [m npm]": "terrain_rx_m_asl",
    "Miejscowość Rx": "city_rx",
    "Województwo Rx": "province_rx",
    "Ulica Rx": "street_rx",
    "Opis położenia Rx": "location_desc_rx",
    "f [GHz]": "freq_ghz",
    "Nr_kan": "channel_number",
    "Symbol_planu": "plan_symbol",
    "Szer_kan [MHz]": "channel_width_mhz",
    "Polaryzacja": "polarization",
    "Rodz_modu-lacji": "modulation",
    "Przepływność [Mb/s]": "bitrate_mbps",
    "EIRP [dBm]": "eirp_dbm",
    "Tłum_ant_odb_Rx [dB]": "rx_antenna_attenuation_db",
    "Typ_nad": "radio_type",
    "Prod_nad": "radio_vendor",
    "Liczba_szum_Rx [dB]": "rx_noise_figure_db",
    "Tłum_ATPC [dB]": "atpc_attenuation_db",
    "Typ_ant_Tx": "antenna_type_tx",
    "Prod_ant_Tx": "antenna_vendor_tx",
    "Zysk_ant_Tx [dBi]": "antenna_gain_tx_dbi",
    "H_ant_Tx [m npt]": "antenna_height_tx_m_agl",
    "Typ_ant_Rx": "antenna_type_rx",
    "Prod_ant_Rx": "antenna_vendor_rx",
    "Zysk_ant_Rx [dBi]": "antenna_gain_rx_dbi",
    "H_ant_Rx [m npt]": "antenna_height_rx_m_agl",
    "Operator": "operator_name",
    "Nr_pozw/dec": "permit_number",
    "Rodz_dec": "decision_type",
    "Data_wydania": "issue_date",
    "Data_ważn_pozw/dec": "valid_until",
}


@dataclass(frozen=True)
class GeoPoint:
    lon_deg: float
    lat_deg: float


@dataclass(frozen=True)
class Site:
    role: str
    point: GeoPoint
    terrain_m_asl: Optional[float]
    antenna_height_m_agl: Optional[float]
    city: Optional[str]
    province: Optional[str]
    street: Optional[str]
    location_description: Optional[str]
    antenna_type: Optional[str]
    antenna_vendor: Optional[str]
    antenna_gain_dbi: Optional[float]

    @property
    def antenna_center_m_asl(self) -> Optional[float]:
        if self.terrain_m_asl is None or self.antenna_height_m_agl is None:
            return None
        return self.terrain_m_asl + self.antenna_height_m_agl


@dataclass(frozen=True)
class RadioEmission:
    center_freq_ghz: float
    center_freq_mhz: float
    channel_number: str
    plan_symbol: Optional[str]
    channel_width_mhz: Optional[float]
    polarization: Optional[str]
    modulation: Optional[str]
    bitrate_mbps: Optional[float]
    eirp_dbm: Optional[float]
    rx_antenna_attenuation_db: Optional[float]
    radio_type: Optional[str]
    radio_vendor: Optional[str]
    rx_noise_figure_db: Optional[float]
    atpc_attenuation_db: Optional[float]

    @property
    def lower_edge_mhz(self) -> Optional[float]:
        if self.channel_width_mhz is None:
            return None
        return self.center_freq_mhz - self.channel_width_mhz / 2.0

    @property
    def upper_edge_mhz(self) -> Optional[float]:
        if self.channel_width_mhz is None:
            return None
        return self.center_freq_mhz + self.channel_width_mhz / 2.0



@dataclass(frozen=True)
class PermitRecord:
    row_number: int
    operator_name: Optional[str]
    permit_number: Optional[str]
    decision_type: Optional[str]
    issue_date: Optional[date]
    valid_until: Optional[date]
    tx_site: Site
    rx_site: Site
    emission: RadioEmission
    source_filename: str
    source_sheet: str

    @property
    def stable_id(self) -> str:
        permit = self.permit_number or "no-permit"
        chan = self.emission.channel_number or "no-chan"
        freq = f"{self.emission.center_freq_mhz:.3f}"
        return f"{permit}:{chan}:{freq}:{self.row_number}"


@dataclass(frozen=True)
class DuplexLink:
    link_id: str
    operator_name: Optional[str]
    permit_number: Optional[str]
    decision_type: Optional[str]
    issue_date: Optional[date]
    valid_until: Optional[date]
    site_a: Site
    site_b: Site
    emission_ab: RadioEmission
    emission_ba: RadioEmission
    source_filename: str
    source_sheet: str

    @property
    def band_name(self) -> str:
        return f"{self.emission_ab.center_freq_ghz:.6f}/{self.emission_ba.center_freq_ghz:.6f} GHz"

    @property
    def plan_symbol(self) -> Optional[str]:
        return self.emission_ab.plan_symbol or self.emission_ba.plan_symbol

    @property
    def polarization(self) -> Optional[str]:
        return self.emission_ab.polarization or self.emission_ba.polarization


@dataclass(frozen=True)
class RadioProfile:
    radio_id: int
    radio_type: Optional[str]
    radio_vendor: Optional[str]
    rx_noise_figure_db: Optional[float]
    atpc_attenuation_db: Optional[float]
    receiver_bandwidth_mhz: Optional[float]
    is_verified: bool


@dataclass(frozen=True)
class PlanChannel:
    channel_number: str
    channel_index: int
    is_prime: bool
    subband: str
    center_freq_ghz: float


@dataclass(frozen=True)
class FrequencyPlan:
    symbol: str
    source_filename: str
    source_format: str
    range_from_ghz: Optional[float]
    range_to_ghz: Optional[float]
    channel_width_mhz: Optional[float]
    channel_spacing_mhz: Optional[float]
    band_center_mhz: Optional[float]
    origin: Optional[str]
    recommendation: Optional[str]
    recommendation_value: Optional[str]
    annex_variant: Optional[str]
    plan_type: Optional[str]
    message_type: Optional[str]
    duplex_spacing_mhz: Optional[float]
    min_duplex_spacing_mhz: Optional[float]
    guard_band_lower_mhz: Optional[float]
    guard_band_upper_mhz: Optional[float]
    lower_subband_factor_mhz: Optional[float]
    upper_subband_factor_mhz: Optional[float]
    first_channel: Optional[int]
    last_channel: Optional[int]
    step: Optional[int]
    channels: list[PlanChannel]

    @property
    def is_tdd(self) -> bool:
        return self.duplex_spacing_mhz in (None, 0)

    @property
    def has_prime_channels(self) -> bool:
        return any(channel.is_prime for channel in self.channels)


@dataclass(frozen=True)
class PlanDataset:
    source_dir: str
    loaded_files: list[str]
    loaded_at: datetime
    plans: dict[str, FrequencyPlan]


@dataclass(frozen=True)
class PlanCacheEnvelope:
    source_signature: tuple[tuple[str, int, int], ...]
    dataset: PlanDataset


@dataclass(frozen=True)
class SourceFileInfo:
    filename: str
    full_path: str
    file_size_bytes: int
    modified_at: datetime
    sheet_name: str
    rows_count: int



@dataclass(frozen=True)
class PermissionDataset:
    source: SourceFileInfo
    records: list[PermitRecord]


@dataclass(frozen=True)
class PairingReport:
    total_records: int
    duplex_links: list[DuplexLink]
    orphan_records: list[PermitRecord]

    @property
    def paired_records_count(self) -> int:
        return len(self.duplex_links) * 2

    @property
    def orphan_records_count(self) -> int:
        return len(self.orphan_records)


@dataclass(frozen=True)
class CacheEnvelope:
    source_path: str
    source_mtime_ns: int
    source_size: int
    dataset: PermissionDataset


_COORD_RE = re.compile(
    r"^\s*(\d+)([NSEW])([0-9]{1,2})'(\d{1,2}(?:[\.,]\d+)?)''\s*$"
)


def parse_uke_coord(value: Any) -> float:
    if value is None:
        raise ValueError("Pusta współrzędna")

    text = str(value).strip()
    match = _COORD_RE.match(text)
    if not match:
        raise ValueError(f"Nieznany format współrzędnej UKE: {text!r}")

    deg, hemi, minutes, seconds = match.groups()
    deg_f = float(deg)
    minutes_f = float(minutes)
    seconds_f = float(seconds.replace(",", "."))

    decimal = deg_f + minutes_f / 60.0 + seconds_f / 3600.0
    if hemi in {"W", "S"}:
        decimal *= -1.0
    return decimal


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = "".join(ch for ch in str(value).strip() if ord(ch) >= 32 or ch in "\t\n\r")
    return text or None


def normalize_lookup_text(value: Any) -> str:
    text = clean_text(value)
    if text is None:
        return ""
    normalized = re.sub(r"[^0-9a-z]+", " ", text.lower())
    return " ".join(normalized.split())


def internal_catalog_available(sqlite_path: Path = INTERNAL_SQLITE_PATH) -> bool:
    if not sqlite_path.exists():
        return False
    try:
        with sqlite3.connect(sqlite_path) as con:
            cur = con.cursor()
            existing = {row[0] for row in cur.execute("select name from sqlite_master where type='table'")}
        return all(table in existing for table in INTERNAL_REQUIRED_TABLES)
    except sqlite3.Error:
        return False


def compute_internal_eirp_dbm(
    tx_power_dbm: Optional[float],
    tx_antenna_gain_dbi: Optional[float],
    tx_circulator_loss_db: Optional[float],
) -> Optional[float]:
    if tx_power_dbm is None and tx_antenna_gain_dbi is None:
        return None
    return (tx_power_dbm or 0.0) + (tx_antenna_gain_dbi or 0.0) - (tx_circulator_loss_db or 0.0)


@lru_cache(maxsize=1)
def _load_internal_radio_profiles(sqlite_path_str: str = str(INTERNAL_SQLITE_PATH)) -> tuple[RadioProfile, ...]:
    sqlite_path = Path(sqlite_path_str)
    if not sqlite_path.exists():
        return ()
    query = """
    SELECT
        n.nadajnik_id,
        n.typ_nadajnika,
        prod.nazwa_producenta AS radio_vendor,
        n.wsp_szum_w AS rx_noise_figure_db,
        n.atpc AS atpc_attenuation_db,
        n.szer_pasma_odb AS receiver_bandwidth_mhz,
        COALESCE(n.poprawna, 0) AS is_verified
    FROM lr_konsultacja_349__nadajnik n
    LEFT JOIN lr_konsultacja_349__producent prod
      ON prod.producent_id = n.producent_id
    ORDER BY
        COALESCE(prod.nazwa_producenta, ''),
        COALESCE(n.typ_nadajnika, ''),
        n.nadajnik_id
    """
    with sqlite3.connect(sqlite_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(query).fetchall()
    return tuple(
        RadioProfile(
            radio_id=int(row["nadajnik_id"]),
            radio_type=clean_text(row["typ_nadajnika"]),
            radio_vendor=clean_text(row["radio_vendor"]),
            rx_noise_figure_db=row["rx_noise_figure_db"],
            atpc_attenuation_db=row["atpc_attenuation_db"],
            receiver_bandwidth_mhz=row["receiver_bandwidth_mhz"],
            is_verified=bool(row["is_verified"]),
        )
        for row in rows
    )


def _band_hints_from_freqs(freqs_ghz: tuple[float, ...]) -> set[str]:
    valid = [freq for freq in freqs_ghz if freq is not None]
    if not valid:
        return set()
    min_freq = min(valid)
    max_freq = max(valid)
    if min_freq >= 70.0:
        return {"80", "70 80"}
    if 37.0 <= max_freq <= 39.5:
        return {"38"}
    if 22.0 <= max_freq <= 24.5:
        return {"23"}
    if 17.0 <= max_freq <= 19.5:
        return {"18"}
    if 12.0 <= max_freq <= 14.5:
        return {"13"}
    if 10.0 <= max_freq <= 12.5:
        return {"11"}
    if 6.0 <= max_freq <= 8.5:
        return {"7"}
    return set()


def lookup_internal_radio_profile(
    radio_type: Optional[str],
    radio_vendor: Optional[str],
    freqs_ghz: tuple[Optional[float], ...] = (),
    channel_width_mhz: Optional[float] = None,
    sqlite_path: Path = INTERNAL_SQLITE_PATH,
) -> Optional[RadioProfile]:
    radio_type_norm = normalize_lookup_text(radio_type)
    if not radio_type_norm:
        return None
    request_tokens = set(radio_type_norm.split())
    radio_vendor_norm = normalize_lookup_text(radio_vendor)
    band_hints = _band_hints_from_freqs(tuple(freq for freq in freqs_ghz if freq is not None))

    best_profile: Optional[RadioProfile] = None
    best_score = float("-inf")

    for profile in _load_internal_radio_profiles(str(sqlite_path)):
        profile_type_norm = normalize_lookup_text(profile.radio_type)
        if not profile_type_norm:
            continue
        profile_tokens = set(profile_type_norm.split())
        common_tokens = request_tokens & profile_tokens
        if not common_tokens:
            continue

        score = float(len(common_tokens) * 3)
        if profile.is_verified:
            score += 0.5
        if radio_type_norm == profile_type_norm:
            score += 8.0
        elif radio_type_norm in profile_type_norm or profile_type_norm in radio_type_norm:
            score += 5.0

        profile_vendor_norm = normalize_lookup_text(profile.radio_vendor)
        if radio_vendor_norm and profile_vendor_norm:
            if radio_vendor_norm == profile_vendor_norm:
                score += 4.0
            elif radio_vendor_norm in profile_vendor_norm or profile_vendor_norm in radio_vendor_norm:
                score += 2.5
            else:
                score -= 1.0

        if band_hints and any(hint in profile_type_norm for hint in band_hints):
            score += 3.0
        elif band_hints:
            digit_tokens = {token for token in profile_tokens if any(ch.isdigit() for ch in token)}
            if digit_tokens:
                score -= 1.0

        if channel_width_mhz is not None and profile.receiver_bandwidth_mhz is not None:
            delta_bw = abs(profile.receiver_bandwidth_mhz - channel_width_mhz)
            if delta_bw <= 0.5:
                score += 1.5
            elif delta_bw <= max(channel_width_mhz, 1.0):
                score += 0.5

        if (
            score > best_score
            or (
                best_profile is not None
                and score == best_score
                and profile.radio_id < best_profile.radio_id
            )
        ):
            best_score = score
            best_profile = profile

    if best_profile is None or best_score < 5.0:
        return None
    return best_profile


def parse_optional_float_strict(value: Any) -> Optional[float]:
    text = clean_text(value)
    if text is None:
        return None
    text = text.replace(" ", "").replace(",", ".")
    return float(text)


def parse_float(value: Any) -> Optional[float]:
    return parse_optional_float_strict(value)


def parse_int(value: Any) -> int:
    text = clean_text(value)
    if text is None:
        raise ValueError("Brak wartości całkowitej")
    return int(float(text.replace(",", ".")))


def parse_bitrate_mbps(value: Any) -> Optional[float]:
    text = clean_text(value)
    if text is None:
        return None

    normalized = text.replace(" ", "").replace(",", ".").lower()
    normalized = normalized.replace("mb/s", "").replace("mbit/s", "").replace("mbps", "")
    normalized = normalized.replace("max", "")

    match = re.search(r"([0-9]+(?:\.[0-9]+)?)x([0-9]+(?:\.[0-9]+)?)", normalized)
    if match:
        left = float(match.group(1))
        right = float(match.group(2))
        return left * right

    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", normalized)
    if match:
        return float(match.group(1))

    raise ValueError(f"Nieznany format przepływności: {text!r}")


def parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = clean_text(value)
    if text is None:
        return None

    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    raise ValueError(f"Nieznany format daty: {text!r}")



def normalize_row(headers: list[Any], row: tuple[Any, ...]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for header, value in zip(headers, row):
        if header is None:
            continue
        alias = HEADER_ALIASES.get(header)
        if alias is None:
            continue
        normalized[alias] = value
    return normalized


def normalize_channel_number(value: Optional[str]) -> str:
    if value is None:
        return ""
    return value.replace(" ", "").replace("’", "'").strip()


def approx_equal(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def site_pair_key(site_left: Site, site_right: Site) -> tuple[float, float, float, float]:
    coords = sorted(
        [
            (round(site_left.point.lon_deg, 7), round(site_left.point.lat_deg, 7)),
            (round(site_right.point.lon_deg, 7), round(site_right.point.lat_deg, 7)),
        ]
    )
    return coords[0][0], coords[0][1], coords[1][0], coords[1][1]


def build_pairing_key(record: PermitRecord) -> tuple[Any, ...]:
    return (
        record.permit_number or "",
        record.operator_name or "",
        site_pair_key(record.tx_site, record.rx_site),
        round(record.emission.channel_width_mhz or 0.0, 6),
        record.emission.plan_symbol or "",
        record.emission.polarization or "",
        record.emission.radio_type or "",
        record.emission.radio_vendor or "",
    )


def records_are_reverse_match(left: PermitRecord, right: PermitRecord) -> bool:
    return (
        approx_equal(left.tx_site.point.lon_deg, right.rx_site.point.lon_deg)
        and approx_equal(left.tx_site.point.lat_deg, right.rx_site.point.lat_deg)
        and approx_equal(left.rx_site.point.lon_deg, right.tx_site.point.lon_deg)
        and approx_equal(left.rx_site.point.lat_deg, right.tx_site.point.lat_deg)
    )


def choose_best_reverse_match(base: PermitRecord, candidates: list[PermitRecord]) -> Optional[PermitRecord]:
    best: Optional[PermitRecord] = None
    best_score: Optional[tuple[int, int, int, int, float]] = None

    for candidate in candidates:
        if candidate.row_number == base.row_number:
            continue
        if not records_are_reverse_match(base, candidate):
            continue

        same_channel = int(
            normalize_channel_number(base.emission.channel_number).rstrip("'")
            == normalize_channel_number(candidate.emission.channel_number).rstrip("'")
        )
        apostrophe_pair = int(
            normalize_channel_number(base.emission.channel_number)
            != normalize_channel_number(candidate.emission.channel_number)
            and normalize_channel_number(base.emission.channel_number).rstrip("'")
            == normalize_channel_number(candidate.emission.channel_number).rstrip("'")
        )
        same_modulation = int((base.emission.modulation or "") == (candidate.emission.modulation or ""))
        same_bitrate = int(approx_equal(base.emission.bitrate_mbps, candidate.emission.bitrate_mbps, tol=1e-3))
        freq_delta = abs(base.emission.center_freq_mhz - candidate.emission.center_freq_mhz)

        score = (same_channel, apostrophe_pair, same_modulation, same_bitrate, -freq_delta)
        if best_score is None or score > best_score:
            best = candidate
            best_score = score

    return best


def make_duplex_link(left: PermitRecord, right: PermitRecord) -> DuplexLink:
    left_key = (left.tx_site.point.lon_deg, left.tx_site.point.lat_deg, left.rx_site.point.lon_deg, left.rx_site.point.lat_deg)
    right_key = (right.tx_site.point.lon_deg, right.tx_site.point.lat_deg, right.rx_site.point.lon_deg, right.rx_site.point.lat_deg)

    if left_key <= right_key:
        record_ab = left
        record_ba = right
    else:
        record_ab = right
        record_ba = left

    link_id = (
        f"{record_ab.permit_number or 'no-permit'}:"
        f"{record_ab.row_number}-"
        f"{record_ba.row_number}"
    )

    return DuplexLink(
        link_id=link_id,
        operator_name=record_ab.operator_name or record_ba.operator_name,
        permit_number=record_ab.permit_number or record_ba.permit_number,
        decision_type=record_ab.decision_type or record_ba.decision_type,
        issue_date=record_ab.issue_date or record_ba.issue_date,
        valid_until=record_ab.valid_until or record_ba.valid_until,
        site_a=record_ab.tx_site,
        site_b=record_ab.rx_site,
        emission_ab=record_ab.emission,
        emission_ba=record_ba.emission,
        source_filename=record_ab.source_filename,
        source_sheet=record_ab.source_sheet,
    )


def pair_duplex_links(records: list[PermitRecord]) -> PairingReport:
    buckets: dict[tuple[Any, ...], list[PermitRecord]] = {}
    for record in records:
        buckets.setdefault(build_pairing_key(record), []).append(record)

    used_row_numbers: set[int] = set()
    duplex_links: list[DuplexLink] = []
    orphan_records: list[PermitRecord] = []

    for bucket_records in buckets.values():
        bucket_records_sorted = sorted(bucket_records, key=lambda rec: rec.row_number)
        for record in bucket_records_sorted:
            if record.row_number in used_row_numbers:
                continue

            candidates = [c for c in bucket_records_sorted if c.row_number not in used_row_numbers]
            match = choose_best_reverse_match(record, candidates)
            if match is None:
                orphan_records.append(record)
                used_row_numbers.add(record.row_number)
                continue

            duplex_links.append(make_duplex_link(record, match))
            used_row_numbers.add(record.row_number)
            used_row_numbers.add(match.row_number)

    duplex_links.sort(key=lambda link: (link.permit_number or "", link.link_id))
    orphan_records.sort(key=lambda record: record.row_number)

    return PairingReport(
        total_records=len(records),
        duplex_links=duplex_links,
        orphan_records=orphan_records,
    )


# === Frequency Plan Handling ===


def discover_plan_files(plan_dir: Path = PLAN_DIR) -> list[Path]:
    if not plan_dir.exists():
        return []
    return sorted(
        [path for path in plan_dir.glob("*.rtf") if path.is_file()],
        key=lambda path: path.name.lower(),
    )


def build_plan_source_signature(plan_files: list[Path]) -> tuple[tuple[str, int, int], ...]:
    return tuple(
        (path.name, path.stat().st_mtime_ns, path.stat().st_size)
        for path in plan_files
    )


def _load_plans_cache_from_disk() -> Optional[PlanCacheEnvelope]:
    if not PLANS_CACHE_FILE.exists():
        return None
    with PLANS_CACHE_FILE.open("rb") as fh:
        return pickle.load(fh)


def _save_plans_cache_to_disk(envelope: PlanCacheEnvelope) -> None:
    with PLANS_CACHE_FILE.open("wb") as fh:
        pickle.dump(envelope, fh)


def parse_decimal_token(value: str) -> float:
    return float(value.replace(" ", "").replace(",", "."))


def normalize_plan_label(value: str) -> str:
    text = value.lower().strip()
    text = text.replace("/", " ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def derive_plan_symbol_from_filename(path: Path) -> str:
    symbol = path.stem.strip()
    if not symbol:
        raise ValueError(f"Pusta nazwa pliku planu: {path.name}")
    return symbol


def convert_rtf_to_text(path: Path) -> str:
    try:
        result = subprocess.run(
            ["unrtf", "--text", str(path)],
            capture_output=True,
            check=True,
        )
        return result.stdout.decode("utf-8", errors="ignore")
    except FileNotFoundError:
        return fallback_rtf_to_text(path)


def cleanup_plan_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        if line.startswith("###"):
            continue
        if line.startswith("AUTHOR:"):
            continue
        if line.startswith("-----------------"):
            continue
        if re.match(r"^Strona\s+\d+\s+z\s+\d+$", line):
            continue
        if re.match(r"^\d{1,2}\s+[A-Za-zżźćńółęąśŻŹĆĄŚĘŁÓŃ]+\s+\d{4}$", line):
            continue
        lines.append(line)
    return lines


def find_plan_symbol_in_lines(lines: list[str], path: Path) -> str:
    for index, line in enumerate(lines):
        if normalize_plan_label(line) == "plan" and index + 1 < len(lines):
            candidate = lines[index + 1].strip()
            if candidate:
                return candidate

    filename_symbol = derive_plan_symbol_from_filename(path)
    normalized_filename_symbol = normalize_plan_label(filename_symbol)

    for line in lines:
        normalized_line = normalize_plan_label(line)
        if normalized_line == normalized_filename_symbol:
            return filename_symbol
        if normalized_filename_symbol and normalized_filename_symbol in normalized_line:
            return filename_symbol

    return filename_symbol


def fallback_rtf_to_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    text = raw
    text = text.replace("\\par", "\n")
    text = text.replace("\\line", "\n")
    text = text.replace("\r", "")
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()
def extract_inline_channel_pairs(lines: list[str]) -> list[PlanChannel]:
    channels: list[PlanChannel] = []
    seen: set[tuple[str, float]] = set()

    for line in lines:
        matches = re.findall(r"(\d+'?)\s+(\d+(?:[\.,]\d+)?)", line)
        for channel_token, freq_token in matches:
            center_freq_ghz = parse_decimal_token(freq_token)
            key = (channel_token, center_freq_ghz)
            if key in seen:
                continue
            seen.add(key)

            is_prime = channel_token.endswith("'")
            channel_index = int(channel_token.rstrip("'"))
            subband = "upper" if is_prime else "lower"
            channels.append(
                PlanChannel(
                    channel_number=channel_token,
                    channel_index=channel_index,
                    is_prime=is_prime,
                    subband=subband,
                    center_freq_ghz=center_freq_ghz,
                )
            )

    if channels and not any(channel.is_prime for channel in channels):
        channels = [
            PlanChannel(
                channel_number=channel.channel_number,
                channel_index=channel.channel_index,
                is_prime=False,
                subband="single",
                center_freq_ghz=channel.center_freq_ghz,
            )
            for channel in channels
        ]

    return channels


def get_value_after_label(lines: list[str], label_prefixes: list[str]) -> Optional[str]:
    normalized_prefixes = [normalize_plan_label(prefix) for prefix in label_prefixes]
    units = {"ghz", "mhz"}

    for index, line in enumerate(lines):
        normalized_line = normalize_plan_label(line)
        if any(normalized_line.startswith(prefix) for prefix in normalized_prefixes):
            for candidate in lines[index + 1:]:
                normalized_candidate = normalize_plan_label(candidate)
                if not normalized_candidate:
                    continue
                if normalized_candidate in units:
                    continue
                if normalized_candidate.startswith("numer kan"):
                    return None
                return candidate
    return None


def get_all_values_after_label(lines: list[str], label_prefixes: list[str]) -> list[str]:
    normalized_prefixes = [normalize_plan_label(prefix) for prefix in label_prefixes]
    units = {"ghz", "mhz"}
    values: list[str] = []

    for index, line in enumerate(lines):
        normalized_line = normalize_plan_label(line)
        if any(normalized_line.startswith(prefix) for prefix in normalized_prefixes):
            for candidate in lines[index + 1:]:
                normalized_candidate = normalize_plan_label(candidate)
                if not normalized_candidate:
                    continue
                if normalized_candidate in units:
                    continue
                if normalized_candidate.startswith("numer kan"):
                    break
                values.append(candidate)
                break

    return values


def parse_optional_int_token(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    return int(parse_decimal_token(value))


def parse_optional_float_token(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    return parse_decimal_token(value)


def first_matching_value(
    lines: list[str],
    prefixes: list[str],
    parser: Callable[[str], Any],
) -> Any:
    for value in get_all_values_after_label(lines, prefixes):
        try:
            return parser(value)
        except Exception:
            continue
    return None


def parse_plan_channels(lines: list[str]) -> list[PlanChannel]:
    table_start_index: Optional[int] = None
    for index, line in enumerate(lines):
        normalized_line = normalize_plan_label(line)
        if normalized_line.startswith("numer kan") and "cz" in normalized_line:
            table_start_index = index + 1
            break

    channels: list[PlanChannel] = []

    if table_start_index is not None:
        tokens = lines[table_start_index:]
        i = 0
        while i < len(tokens) - 1:
            channel_token = tokens[i].strip()
            freq_token = tokens[i + 1].strip()

            if re.fullmatch(r"\d+'?", channel_token) and re.fullmatch(r"\d+(?:[\.,]\d+)?", freq_token):
                is_prime = channel_token.endswith("'")
                channel_index = int(channel_token.rstrip("'"))
                subband = "upper" if is_prime else "lower"
                channels.append(
                    PlanChannel(
                        channel_number=channel_token,
                        channel_index=channel_index,
                        is_prime=is_prime,
                        subband=subband,
                        center_freq_ghz=parse_decimal_token(freq_token),
                    )
                )
                i += 2
                continue

            inline_matches = re.findall(r"(\d+'?)\s+(\d+(?:[\.,]\d+)?)", tokens[i])
            if inline_matches:
                for inline_channel_token, inline_freq_token in inline_matches:
                    is_prime = inline_channel_token.endswith("'")
                    channel_index = int(inline_channel_token.rstrip("'"))
                    subband = "upper" if is_prime else "lower"
                    channels.append(
                        PlanChannel(
                            channel_number=inline_channel_token,
                            channel_index=channel_index,
                            is_prime=is_prime,
                            subband=subband,
                            center_freq_ghz=parse_decimal_token(inline_freq_token),
                        )
                    )
            i += 1

    if not channels:
        channels = extract_inline_channel_pairs(lines)

    if not channels:
        raise ValueError("Nie znaleziono tabeli kanałów w planie")

    deduped: list[PlanChannel] = []
    seen: set[tuple[str, float]] = set()
    for channel in channels:
        key = (channel.channel_number, channel.center_freq_ghz)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(channel)

    if not any(channel.is_prime for channel in deduped):
        deduped = [
            PlanChannel(
                channel_number=channel.channel_number,
                channel_index=channel.channel_index,
                is_prime=False,
                subband="single",
                center_freq_ghz=channel.center_freq_ghz,
            )
            for channel in deduped
        ]

    return deduped


def parse_frequency_plan_from_rtf(path: Path) -> FrequencyPlan:
    text = convert_rtf_to_text(path)
    lines = cleanup_plan_lines(text)

    symbol = find_plan_symbol_in_lines(lines, path)

    channels = parse_plan_channels(lines)

    subband_factor_values = [
        parse_decimal_token(value)
        for value in get_all_values_after_label(lines, ["wspczynnik podzakresu"])
        if re.fullmatch(r"-?\d+(?:[\.,]\d+)?", value)
    ]

    lower_subband_factor_mhz = subband_factor_values[0] if len(subband_factor_values) >= 1 else None
    upper_subband_factor_mhz = subband_factor_values[1] if len(subband_factor_values) >= 2 else None

    return FrequencyPlan(
        symbol=symbol,
        source_filename=path.name,
        source_format="rtf",
        range_from_ghz=first_matching_value(lines, ["dla zakresu od", "dla zakresu"], parse_decimal_token),
        range_to_ghz=first_matching_value(lines, ["do"], parse_decimal_token),
        channel_width_mhz=first_matching_value(lines, ["szeroko", "szerokosc"], parse_decimal_token),
        channel_spacing_mhz=first_matching_value(lines, ["odstep miedzykana", "odstep"], parse_decimal_token),
        band_center_mhz=first_matching_value(lines, ["czstotliwosc zakresu", "czestotliwosc zakresu"], parse_decimal_token),
        origin=get_value_after_label(lines, ["pochodzenie"]),
        recommendation=get_value_after_label(lines, ["zalecenie"]),
        recommendation_value=get_value_after_label(lines, ["rekomendacja"]),
        annex_variant=get_value_after_label(lines, ["zalacznik", "wariant"]),
        plan_type=get_value_after_label(lines, ["rodzaj planu"]),
        message_type=get_value_after_label(lines, ["rodzaj wiadomosci"]),
        duplex_spacing_mhz=first_matching_value(lines, ["odstp nadawania i odbioru", "odstep nadawania i odbioru"], parse_decimal_token),
        min_duplex_spacing_mhz=first_matching_value(lines, ["min odstp nadawania i odbioru", "min odstep nadawania i odbioru"], parse_decimal_token),
        guard_band_lower_mhz=first_matching_value(lines, ["pasmo ochronne dolne", "pasmo ochronne"], parse_decimal_token),
        guard_band_upper_mhz=first_matching_value(lines, ["grne", "gorne"], parse_decimal_token),
        lower_subband_factor_mhz=lower_subband_factor_mhz,
        upper_subband_factor_mhz=upper_subband_factor_mhz,
        first_channel=first_matching_value(lines, ["numer pierwszego kanalu", "numer pierwszego"], lambda value: int(parse_decimal_token(value))),
        last_channel=first_matching_value(lines, ["numer ostatniego"], lambda value: int(parse_decimal_token(value))),
        step=first_matching_value(lines, ["krok"], lambda value: int(parse_decimal_token(value))),
        channels=channels,
    )


def load_plan_dataset_from_rtf(plan_dir: Path = PLAN_DIR) -> PlanDataset:
    plan_files = discover_plan_files(plan_dir)
    plans: dict[str, FrequencyPlan] = {}
    for path in plan_files:
        try:
            plan = parse_frequency_plan_from_rtf(path)
        except Exception as exc:
            raise ValueError(f"Błąd parsowania planu {path.name}: {exc}. Ścieżka: {path}") from exc

        if plan.symbol in plans:
            raise ValueError(
                f"Duplikat symbolu planu {plan.symbol!r} dla plików {plans[plan.symbol].source_filename!r} i {path.name!r}"
            )

        plans[plan.symbol] = plan

    return PlanDataset(
        source_dir=str(plan_dir),
        loaded_files=[path.name for path in plan_files],
        loaded_at=datetime.now(),
        plans=plans,
    )


def normalize_plan_symbol_key(symbol: str) -> str:
    text = clean_text(symbol) or ""
    text = text.replace("/", "_")
    text = re.sub(r"\s+", "", text)
    return text


def load_plan_dataset_from_internal_sqlite(sqlite_path: Path = INTERNAL_SQLITE_PATH) -> PlanDataset:
    with sqlite3.connect(sqlite_path) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        plan_rows = cur.execute(
            """
            SELECT
                p.plan_id,
                p.symbol_planu,
                p.odstep_kanalowy,
                p.min_odstep_nadawania_i_odbioru,
                p.odstep_nadawania_i_odbioru,
                p.wspolczynnik_podzakresu_dolnego,
                p.wspolczynnik_podzakresu_gornego,
                p.numer_pierwszego_kanalu,
                p.numer_ostatniego_kanalu,
                p.krok,
                p.odstep_z1s,
                p.odstep_z2s,
                p.skok,
                p.pochodzenie,
                p.zalecenie,
                p.rekomendacja,
                p.zalacznik_wariant,
                p.rodzaj_wiadomosci,
                p.rodzaj_planu,
                p.zalecany_wybor_kanalow,
                p.uwagi
            FROM lr_konsultacja_349__plan p
            ORDER BY p.plan_id
            """
        ).fetchall()

        plans: dict[str, FrequencyPlan] = {}
        for row in plan_rows:
            raw_symbol = clean_text(row["symbol_planu"])
            if not raw_symbol:
                continue

            channel_rows = cur.execute(
                """
                SELECT
                    numer_kana_u AS channel_number,
                    MIN(czestotliwosc_przydzielona) AS freq_ghz
                FROM lr_konsultacja_349__przeslo
                WHERE numer_planu = ?
                  AND numer_kana_u IS NOT NULL
                  AND czestotliwosc_przydzielona IS NOT NULL
                GROUP BY numer_kana_u
                ORDER BY freq_ghz
                """,
                (row["plan_id"],),
            ).fetchall()

            channels: list[PlanChannel] = []
            for channel_row in channel_rows:
                channel_number = normalize_channel_number(channel_row["channel_number"])
                if not channel_number:
                    continue
                digits = "".join(ch for ch in channel_number if ch.isdigit())
                if not digits:
                    continue
                channel_index = int(digits)
                is_prime = channel_number.endswith("'")
                subband = "upper" if is_prime else "lower"
                channels.append(
                    PlanChannel(
                        channel_number=channel_number,
                        channel_index=channel_index,
                        is_prime=is_prime,
                        subband=subband,
                        center_freq_ghz=float(channel_row["freq_ghz"]),
                    )
                )

            if not channels:
                continue

            symbol = normalize_plan_symbol_key(raw_symbol)
            if symbol in plans:
                continue

            plans[symbol] = FrequencyPlan(
                symbol=symbol,
                source_filename=sqlite_path.name,
                source_format="sqlite",
                range_from_ghz=min(channel.center_freq_ghz for channel in channels),
                range_to_ghz=max(channel.center_freq_ghz for channel in channels),
                channel_width_mhz=row["odstep_kanalowy"],
                channel_spacing_mhz=row["odstep_kanalowy"],
                band_center_mhz=None,
                origin=clean_text(row["pochodzenie"]),
                recommendation=clean_text(row["zalecenie"]),
                recommendation_value=clean_text(row["rekomendacja"]),
                annex_variant=clean_text(row["zalacznik_wariant"]),
                plan_type=clean_text(row["rodzaj_planu"]),
                message_type=clean_text(row["rodzaj_wiadomosci"]),
                duplex_spacing_mhz=row["odstep_nadawania_i_odbioru"],
                min_duplex_spacing_mhz=row["min_odstep_nadawania_i_odbioru"],
                guard_band_lower_mhz=row["odstep_z1s"],
                guard_band_upper_mhz=row["odstep_z2s"],
                lower_subband_factor_mhz=row["wspolczynnik_podzakresu_dolnego"],
                upper_subband_factor_mhz=row["wspolczynnik_podzakresu_gornego"],
                first_channel=row["numer_pierwszego_kanalu"],
                last_channel=row["numer_ostatniego_kanalu"],
                step=row["krok"],
                channels=channels,
            )

    return PlanDataset(
        source_dir=str(sqlite_path),
        loaded_files=[sqlite_path.name],
        loaded_at=datetime.now(),
        plans=plans,
    )


def get_plan_dataset(force_reload: bool = False) -> PlanDataset:
    if internal_catalog_available():
        signature = ((INTERNAL_SQLITE_PATH.name, INTERNAL_SQLITE_PATH.stat().st_mtime_ns, INTERNAL_SQLITE_PATH.stat().st_size),)
        if not force_reload:
            cached = _load_plans_cache_from_disk()
            if cached is not None and cached.source_signature == signature:
                return cached.dataset
        dataset = load_plan_dataset_from_internal_sqlite(INTERNAL_SQLITE_PATH)
        envelope = PlanCacheEnvelope(source_signature=signature, dataset=dataset)
        _save_plans_cache_to_disk(envelope)
        return dataset

    plan_files = discover_plan_files()
    signature = build_plan_source_signature(plan_files)

    if not force_reload:
        cached = _load_plans_cache_from_disk()
        if cached is not None and cached.source_signature == signature:
            return cached.dataset

    dataset = load_plan_dataset_from_rtf()
    envelope = PlanCacheEnvelope(source_signature=signature, dataset=dataset)
    _save_plans_cache_to_disk(envelope)
    return dataset


def get_plan_summary() -> dict[str, Any]:
    dataset = get_plan_dataset()
    source_formats = sorted({plan.source_format for plan in dataset.plans.values() if plan.source_format})
    return {
        "plans_count": len(dataset.plans),
        "loaded_files_count": len(dataset.loaded_files),
        "loaded_files": dataset.loaded_files,
        "loaded_at": dataset.loaded_at.isoformat(timespec="seconds"),
        "symbols": sorted(dataset.plans.keys()),
        "source_formats": source_formats,
        "primary_source_format": source_formats[0] if len(source_formats) == 1 else ",".join(source_formats),
    }


def row_to_record(
    row_data: dict[str, Any],
    source_filename: str,
    source_sheet: str,
) -> PermitRecord:
    tx_site = Site(
        role="TX",
        point=GeoPoint(
            lon_deg=parse_uke_coord(row_data["dl_geo_tx"]),
            lat_deg=parse_uke_coord(row_data["sz_geo_tx"]),
        ),
        terrain_m_asl=parse_float(row_data.get("terrain_tx_m_asl")),
        antenna_height_m_agl=parse_float(row_data.get("antenna_height_tx_m_agl")),
        city=clean_text(row_data.get("city_tx")),
        province=clean_text(row_data.get("province_tx")),
        street=clean_text(row_data.get("street_tx")),
        location_description=clean_text(row_data.get("location_desc_tx")),
        antenna_type=clean_text(row_data.get("antenna_type_tx")),
        antenna_vendor=clean_text(row_data.get("antenna_vendor_tx")),
        antenna_gain_dbi=parse_float(row_data.get("antenna_gain_tx_dbi")),
    )

    rx_site = Site(
        role="RX",
        point=GeoPoint(
            lon_deg=parse_uke_coord(row_data["dl_geo_rx"]),
            lat_deg=parse_uke_coord(row_data["sz_geo_rx"]),
        ),
        terrain_m_asl=parse_float(row_data.get("terrain_rx_m_asl")),
        antenna_height_m_agl=parse_float(row_data.get("antenna_height_rx_m_agl")),
        city=clean_text(row_data.get("city_rx")),
        province=clean_text(row_data.get("province_rx")),
        street=clean_text(row_data.get("street_rx")),
        location_description=clean_text(row_data.get("location_desc_rx")),
        antenna_type=clean_text(row_data.get("antenna_type_rx")),
        antenna_vendor=clean_text(row_data.get("antenna_vendor_rx")),
        antenna_gain_dbi=parse_float(row_data.get("antenna_gain_rx_dbi")),
    )

    center_freq_ghz = parse_float(row_data["freq_ghz"])
    if center_freq_ghz is None:
        raise ValueError("Brak częstotliwości środkowej")

    emission = RadioEmission(
        center_freq_ghz=center_freq_ghz,
        center_freq_mhz=center_freq_ghz * 1000.0,
        channel_number=clean_text(row_data.get("channel_number")) or "",
        plan_symbol=clean_text(row_data.get("plan_symbol")),
        channel_width_mhz=parse_float(row_data.get("channel_width_mhz")),
        polarization=clean_text(row_data.get("polarization")),
        modulation=clean_text(row_data.get("modulation")),
        bitrate_mbps=parse_bitrate_mbps(row_data.get("bitrate_mbps")),
        eirp_dbm=parse_float(row_data.get("eirp_dbm")),
        rx_antenna_attenuation_db=parse_float(row_data.get("rx_antenna_attenuation_db")),
        radio_type=clean_text(row_data.get("radio_type")),
        radio_vendor=clean_text(row_data.get("radio_vendor")),
        rx_noise_figure_db=parse_float(row_data.get("rx_noise_figure_db")),
        atpc_attenuation_db=parse_float(row_data.get("atpc_attenuation_db")),
    )

    return PermitRecord(
        row_number=parse_int(row_data["lp"]),
        operator_name=clean_text(row_data.get("operator_name")),
        permit_number=clean_text(row_data.get("permit_number")),
        decision_type=clean_text(row_data.get("decision_type")),
        issue_date=parse_date(row_data.get("issue_date")),
        valid_until=parse_date(row_data.get("valid_until")),
        tx_site=tx_site,
        rx_site=rx_site,
        emission=emission,
        source_filename=source_filename,
        source_sheet=source_sheet,
    )


def _internal_catalog_query() -> str:
    return """
    SELECT
        d.nrdecyzji AS permit_number,
        d.data_wydania,
        d.data_waznosci,
        p.prz_s_o_id AS span_id,
        p.numer_kana_u AS channel_label,
        p.polaryzacja,
        p.czestotliwosc_przydzielona AS assigned_frequency_ghz,
        pl.symbol_planu AS plan_symbol,
        pl.odstep_kanalowy AS channel_width_mhz,
        p.moc_nadajnika AS tx_power_dbm,
        p.t_umienie_cyrkulator_w_n AS circ_loss_n_db,
        p.t_umienie_cyrkulator_w_o AS circ_loss_o_db,
        n.typ_nadajnika,
        n.wsp_szum_w AS rx_noise_figure_db,
        n.atpc AS atpc_attenuation_db,
        prod_radio.nazwa_producenta AS radio_vendor,
        st_n.u_ytkownik_id AS tx_user_id,
        st_o.u_ytkownik_id AS rx_user_id,
        st_n.operator AS tx_operator,
        st_o.operator AS rx_operator,
        os_n.nazwa1 AS tx_user_name,
        os_o.nazwa1 AS rx_user_name,
        pa_n.zysk_energetyczny AS tx_antenna_gain_dbi,
        a_n.typ_anteny AS tx_antenna_type,
        prod_n.nazwa_producenta AS tx_antenna_vendor,
        za_n.h_anteny AS tx_antenna_height_m_agl,
        k_n.h_terenu AS tx_terrain_m_asl,
        ob_n.miejscowo AS tx_city,
        ob_n.ulica_i_numer AS tx_street,
        ob_n.opis_po_o_enia AS tx_location_description,
        ob_n.powiat AS tx_province,
        k_n.szer_geo AS tx_lat,
        k_n.dlug_geo AS tx_lon,
        pa_o.zysk_energetyczny AS rx_antenna_gain_dbi,
        a_o.typ_anteny AS rx_antenna_type,
        prod_o.nazwa_producenta AS rx_antenna_vendor,
        za_o.h_anteny AS rx_antenna_height_m_agl,
        k_o.h_terenu AS rx_terrain_m_asl,
        ob_o.miejscowo AS rx_city,
        ob_o.ulica_i_numer AS rx_street,
        ob_o.opis_po_o_enia AS rx_location_description,
        ob_o.powiat AS rx_province,
        k_o.szer_geo AS rx_lat,
        k_o.dlug_geo AS rx_lon
    FROM lr_konsultacja_349__decyzja d
    JOIN lr_konsultacja_349__przeslo_decyzji pd
      ON pd.decyzja_id = d.decyzja_id
    JOIN lr_konsultacja_349__przeslo p
      ON p.prz_s_o_id = pd.prz_s_o_id
    LEFT JOIN lr_konsultacja_349__plan pl
      ON pl.plan_id = p.numer_planu
    LEFT JOIN lr_konsultacja_349__nadajnik n
      ON n.nadajnik_id = p.nadajnik_id
    LEFT JOIN lr_konsultacja_349__producent prod_radio
      ON prod_radio.producent_id = n.producent_id
    LEFT JOIN lr_konsultacja_349__zastosowana_antena za_n
      ON za_n.zastosowana_antena_id = p.antena_stacji_n_id
    LEFT JOIN lr_konsultacja_349__stacja st_n
      ON st_n.stacja_id = za_n.stacja_id
    LEFT JOIN lr_konsultacja_349__osoba os_n
      ON os_n.wnioskodawca_id = st_n.u_ytkownik_id
    LEFT JOIN lr_konsultacja_349__konstrukcja k_n
      ON k_n.konstrukcja_id = st_n.konstrukcja_id
    LEFT JOIN lr_konsultacja_349__obiekt_stacji ob_n
      ON ob_n.obiekt_stacji_id = k_n.obiekt_stacji_id
    LEFT JOIN lr_konsultacja_349__pasmo_anteny pa_n
      ON pa_n.pasmo_anteny_id = p.pasmo_anteny_n_id
    LEFT JOIN lr_konsultacja_349__antena a_n
      ON a_n.antena_id = pa_n.antena_id
    LEFT JOIN lr_konsultacja_349__producent prod_n
      ON prod_n.producent_id = a_n.producent_id
    LEFT JOIN lr_konsultacja_349__zastosowana_antena za_o
      ON za_o.zastosowana_antena_id = p.antena_stacji_o_id
    LEFT JOIN lr_konsultacja_349__stacja st_o
      ON st_o.stacja_id = za_o.stacja_id
    LEFT JOIN lr_konsultacja_349__osoba os_o
      ON os_o.wnioskodawca_id = st_o.u_ytkownik_id
    LEFT JOIN lr_konsultacja_349__konstrukcja k_o
      ON k_o.konstrukcja_id = st_o.konstrukcja_id
    LEFT JOIN lr_konsultacja_349__obiekt_stacji ob_o
      ON ob_o.obiekt_stacji_id = k_o.obiekt_stacji_id
    LEFT JOIN lr_konsultacja_349__pasmo_anteny pa_o
      ON pa_o.pasmo_anteny_id = p.pasmo_anteny_o_id
    LEFT JOIN lr_konsultacja_349__antena a_o
      ON a_o.antena_id = pa_o.antena_id
    LEFT JOIN lr_konsultacja_349__producent prod_o
      ON prod_o.producent_id = a_o.producent_id
    LEFT JOIN lr_konsultacja_349__przesla_do_modyfikacji pm
      ON pm.prz_s_o_modyfikowane_id = p.prz_s_o_id
    """


def _row_to_internal_record(row: sqlite3.Row, source_filename: str, source_sheet: str) -> Optional[PermitRecord]:
    if row["tx_lat"] is None or row["tx_lon"] is None or row["rx_lat"] is None or row["rx_lon"] is None:
        return None
    if row["assigned_frequency_ghz"] is None:
        return None

    tx_site = Site(
        role="TX",
        point=GeoPoint(
            lon_deg=parse_uke_coord(row["tx_lon"]),
            lat_deg=parse_uke_coord(row["tx_lat"]),
        ),
        terrain_m_asl=row["tx_terrain_m_asl"],
        antenna_height_m_agl=row["tx_antenna_height_m_agl"],
        city=clean_text(row["tx_city"]),
        province=clean_text(row["tx_province"]),
        street=clean_text(row["tx_street"]),
        location_description=clean_text(row["tx_location_description"]),
        antenna_type=clean_text(row["tx_antenna_type"]),
        antenna_vendor=clean_text(row["tx_antenna_vendor"]),
        antenna_gain_dbi=row["tx_antenna_gain_dbi"],
    )
    rx_site = Site(
        role="RX",
        point=GeoPoint(
            lon_deg=parse_uke_coord(row["rx_lon"]),
            lat_deg=parse_uke_coord(row["rx_lat"]),
        ),
        terrain_m_asl=row["rx_terrain_m_asl"],
        antenna_height_m_agl=row["rx_antenna_height_m_agl"],
        city=clean_text(row["rx_city"]),
        province=clean_text(row["rx_province"]),
        street=clean_text(row["rx_street"]),
        location_description=clean_text(row["rx_location_description"]),
        antenna_type=clean_text(row["rx_antenna_type"]),
        antenna_vendor=clean_text(row["rx_antenna_vendor"]),
        antenna_gain_dbi=row["rx_antenna_gain_dbi"],
    )

    operator_name = (
        clean_text(row["tx_operator"])
        or clean_text(row["tx_user_name"])
        or clean_text(row["rx_operator"])
        or clean_text(row["rx_user_name"])
    )
    if operator_name is None and row["tx_user_id"] is not None and row["tx_user_id"] == row["rx_user_id"]:
        operator_name = f"UKE_USER_{row['tx_user_id']}"

    emission = RadioEmission(
        center_freq_ghz=row["assigned_frequency_ghz"],
        center_freq_mhz=row["assigned_frequency_ghz"] * 1000.0,
        channel_number=clean_text(row["channel_label"]) or "",
        plan_symbol=clean_text(row["plan_symbol"]),
        channel_width_mhz=row["channel_width_mhz"],
        polarization=clean_text(row["polaryzacja"]),
        modulation=None,
        bitrate_mbps=None,
        eirp_dbm=compute_internal_eirp_dbm(
            row["tx_power_dbm"],
            row["tx_antenna_gain_dbi"],
            row["circ_loss_n_db"],
        ),
        rx_antenna_attenuation_db=row["circ_loss_o_db"],
        radio_type=clean_text(row["typ_nadajnika"]),
        radio_vendor=clean_text(row["radio_vendor"]),
        rx_noise_figure_db=row["rx_noise_figure_db"],
        atpc_attenuation_db=row["atpc_attenuation_db"],
    )

    return PermitRecord(
        row_number=int(row["span_id"]),
        operator_name=operator_name,
        permit_number=clean_text(row["permit_number"]),
        decision_type=None,
        issue_date=parse_date(row["data_wydania"]),
        valid_until=parse_date(row["data_waznosci"]),
        tx_site=tx_site,
        rx_site=rx_site,
        emission=emission,
        source_filename=source_filename,
        source_sheet=source_sheet,
    )


def load_dataset_from_internal_sqlite(sqlite_path: Path = INTERNAL_SQLITE_PATH) -> PermissionDataset:
    with sqlite3.connect(sqlite_path) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        rows = cur.execute(_internal_catalog_query() + "\nORDER BY d.nrdecyzji, p.prz_s_o_id").fetchall()

    records: list[PermitRecord] = []
    for row in rows:
        record = _row_to_internal_record(row, sqlite_path.name, "LR_Konsultacja_349")
        if record is not None:
            records.append(record)

    stat = sqlite_path.stat()
    source = SourceFileInfo(
        filename=sqlite_path.name,
        full_path=str(sqlite_path),
        file_size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime),
        sheet_name="LR_Konsultacja_349",
        rows_count=len(records),
    )
    return PermissionDataset(source=source, records=records)


def infer_plan_channel_width_mhz(plan: FrequencyPlan) -> Optional[float]:
    if plan.channel_width_mhz is not None:
        return plan.channel_width_mhz
    subbands: dict[tuple[str, bool], list[float]] = {}
    for channel in plan.channels:
        subbands.setdefault((channel.subband, channel.is_prime), []).append(channel.center_freq_ghz)
    deltas_mhz: list[float] = []
    for freqs in subbands.values():
        freqs = sorted(freqs)
        for left, right in zip(freqs, freqs[1:]):
            delta_mhz = round((right - left) * 1000.0, 6)
            if delta_mhz > 0:
                deltas_mhz.append(delta_mhz)
    return min(deltas_mhz) if deltas_mhz else None


@lru_cache(maxsize=64)
def _get_internal_duplex_links_window_cached(
    channel_width_mhz: Optional[float],
    min_freq_ghz: float,
    max_freq_ghz: float,
) -> tuple[DuplexLink, ...]:
    query = _internal_catalog_query() + """
    WHERE p.czestotliwosc_przydzielona BETWEEN ? AND ?
      AND p.status NOT IN (10, 13, 14)
      AND p.stan > 3
      AND k_n.szer_geo IS NOT NULL
      AND k_n.dlug_geo IS NOT NULL
      AND k_o.szer_geo IS NOT NULL
      AND k_o.dlug_geo IS NOT NULL
      AND pm.prz_s_o_modyfikowane_id IS NULL
    """
    params: list[Any] = [
        min_freq_ghz - 0.25,
        max_freq_ghz + 0.25,
    ]
    if channel_width_mhz is not None:
        query += "\n  AND pl.odstep_kanalowy BETWEEN ? AND ?"
        params.extend([channel_width_mhz - 0.001, channel_width_mhz + 0.001])
    query += "\nORDER BY d.nrdecyzji, p.prz_s_o_id"
    with sqlite3.connect(INTERNAL_SQLITE_PATH) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        rows = cur.execute(query, params).fetchall()

    records: list[PermitRecord] = []
    for row in rows:
        record = _row_to_internal_record(row, INTERNAL_SQLITE_PATH.name, "LR_Konsultacja_349")
        if record is not None:
            records.append(record)
    report = pair_duplex_links(records)
    return tuple(report.duplex_links)


def get_internal_duplex_links_for_plan(plan: FrequencyPlan) -> list[DuplexLink]:
    freqs = [channel.center_freq_ghz for channel in plan.channels]
    if not freqs:
        return []
    return list(
        _get_internal_duplex_links_window_cached(
            None,
            min(freqs),
            max(freqs),
        )
    )


def _load_cache_from_disk() -> Optional[CacheEnvelope]:
    if not CACHE_FILE.exists():
        return None
    with CACHE_FILE.open("rb") as fh:
        return pickle.load(fh)


def _save_cache_to_disk(envelope: CacheEnvelope) -> None:
    with CACHE_FILE.open("wb") as fh:
        pickle.dump(envelope, fh)


def get_permissions_dataset(force_reload: bool = False) -> PermissionDataset:
    if not internal_catalog_available():
        raise FileNotFoundError(
            f"Brak gotowej bazy SQLite UKE w {INTERNAL_SQLITE_PATH}. "
            "Najpierw uruchom ./refresh_uke_sqlite.sh"
        )

    source_path = INTERNAL_SQLITE_PATH
    stat = source_path.stat()

    if not force_reload:
        cached = _load_cache_from_disk()
        if cached is not None:
            if (
                cached.source_path == str(source_path)
                and cached.source_mtime_ns == stat.st_mtime_ns
                and cached.source_size == stat.st_size
            ):
                return cached.dataset

    dataset = load_dataset_from_internal_sqlite(source_path)
    envelope = CacheEnvelope(
        source_path=str(source_path),
        source_mtime_ns=stat.st_mtime_ns,
        source_size=stat.st_size,
        dataset=dataset,
    )
    _save_cache_to_disk(envelope)
    return dataset



def get_source_summary() -> dict[str, Any]:
    if not internal_catalog_available():
        raise FileNotFoundError(
            f"Brak gotowej bazy SQLite UKE w {INTERNAL_SQLITE_PATH}. "
            "Najpierw uruchom ./refresh_uke_sqlite.sh"
        )

    stat = INTERNAL_SQLITE_PATH.stat()
    with sqlite3.connect(INTERNAL_SQLITE_PATH) as con:
        cur = con.cursor()
        rows_count = cur.execute("select count(*) from lr_konsultacja_349__przeslo").fetchone()[0]
    return {
        "source_kind": "sqlite",
        "antenna_catalog_present": catalog_exists(DEFAULT_CATALOG_PATH),
        "antenna_catalog_path": str(DEFAULT_CATALOG_PATH),
        "filename": INTERNAL_SQLITE_PATH.name,
        "full_path": str(INTERNAL_SQLITE_PATH),
        "rows_count": rows_count,
        "sheet_name": "LR_Konsultacja_349",
        "file_size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def get_pairing_summary() -> dict[str, Any]:
    if internal_catalog_available():
        with sqlite3.connect(INTERNAL_SQLITE_PATH) as con:
            cur = con.cursor()
            total_records = cur.execute("select count(*) from lr_konsultacja_349__przeslo").fetchone()[0]
            duplex_links = cur.execute(
                """
                select count(*) from (
                    select
                        d.nrdecyzji,
                        coalesce(p.polaryzacja, ''),
                        coalesce(pl.symbol_planu, ''),
                        replace(coalesce(p.numer_kana_u, ''), '''', '') as channel_base,
                        min(p.antena_stacji_n_id, p.antena_stacji_o_id) as endpoint_a,
                        max(p.antena_stacji_n_id, p.antena_stacji_o_id) as endpoint_b
                    from lr_konsultacja_349__decyzja d
                    join lr_konsultacja_349__przeslo_decyzji pd on pd.decyzja_id = d.decyzja_id
                    join lr_konsultacja_349__przeslo p on p.prz_s_o_id = pd.prz_s_o_id
                    left join lr_konsultacja_349__plan pl on pl.plan_id = p.numer_planu
                    group by 1,2,3,4,5,6
                )
                """
            ).fetchone()[0]
        paired_records_count = min(total_records, duplex_links * 2)
        orphan_records_count = max(0, total_records - paired_records_count)
        return {
            "total_records": total_records,
            "duplex_links": duplex_links,
            "paired_records_count": paired_records_count,
            "orphan_records_count": orphan_records_count,
        }
    dataset = get_permissions_dataset()
    report = pair_duplex_links(dataset.records)
    return {
        "total_records": report.total_records,
        "duplex_links": len(report.duplex_links),
        "paired_records_count": report.paired_records_count,
        "orphan_records_count": report.orphan_records_count,
    }


if __name__ == "__main__":
    summary = get_source_summary()
    pairing = get_pairing_summary()
    plans = get_plan_summary()
    print(f"Źródło: {summary['filename']}")
    print(f"Wiersze: {summary['rows_count']}")
    print(f"Arkusz: {summary['sheet_name']}")
    print(f"Modyfikacja: {summary['modified_at']}")
    print(f"Łącza duplex: {pairing['duplex_links']}")
    print(f"Sparowane rekordy: {pairing['paired_records_count']}")
    print(f"Sieroty: {pairing['orphan_records_count']}")
    print(f"Plany częstotliwości: {plans['plans_count']}")
    print(f"Pliki planów: {plans['loaded_files_count']}")
