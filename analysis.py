

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from math import acos, asin, atan2, cos, degrees, log10, radians, sin, sqrt
from typing import Any, Optional

from antenna_catalog import interpolate_attenuation_db
from radio_masks import lookup_mask_discrimination_db
from uke import (
    DuplexLink,
    FrequencyPlan,
    PlanChannel,
    get_permissions_dataset,
    pair_duplex_links,
    get_plan_dataset,
    get_internal_duplex_links_for_plan,
    internal_catalog_available,
    lookup_internal_radio_profile,
    normalize_plan_symbol_key,
)
from wlr import WlrRequest

ENGINE_VERSION = "hcm-access-like-candidate-state-2026-03-16"


DEFAULT_REQUEST_OPERATOR = "Towerlink Poland Sp. z o.o."
EARTH_RADIUS_KM = 6371.0088
DEFAULT_RADIUS_KM = 30.0
DEFAULT_MAX_LINKS = 500
DEFAULT_INTERNAL_EBAND_MAX_LINKS = 0
DEFAULT_CORRIDOR_KM = 2.0
DEFAULT_CROSS_POL_DISCRIMINATION_DB = 6.0
APPLY_ATPC_TO_COORDINATION_AGGRESSOR = False
ENABLE_MASK_LOOKUP = True
ENABLE_CONSULTATION_FILTER = True

DEFAULT_MISC_LOSS_DB = 3.0
DEFAULT_RECEIVER_NOISE_FIGURE_DB = 7.0
SITE_MATCH_THRESHOLD_KM = 0.35
PLAN_FREQ_TOLERANCE_GHZ = 0.25

MAX_ACCEPTED_DEGRADATION_DB = 1.0
MAX_CONDITIONAL_DEGRADATION_DB = 2.0
MIN_ACCEPTED_CI_DB = 12.0
MIN_CONDITIONAL_CI_DB = 8.0
MIN_HARD_BLOCKING_CI_DB = 6.0
EBAND_FULL_WINDOW_GHZ = 70.0
EBAND_DENSE_NEAR_KM = 3.0
EBAND_DENSE_VERY_NEAR_KM = 1.5
EBAND_DENSE_DELTA_FACTOR = 0.5
EBAND_DENSE_REJECT_COUNT = 6
EBAND_DENSE_CONDITIONAL_COUNT = 3
SHARED_SITE_CROSS_EXTRA_ISOLATION_DB = 20.0
SHARED_SITE_CROSS_MIN_DELTA_MHZ = 5000.0
IPASOLINK_SHARED_SITE_CROSS_EXTRA_COUPLING_DB = 8.0
ANNEX11_LOW_HEIGHT_LIMIT_M_ASL = 300.0
ENABLE_ANNEX11_SEARCH_EXPANSION = False


@dataclass(frozen=True)
class ChannelCandidate:
    plan_symbol: str
    channel_ab: str
    channel_ba: str
    freq_ab_ghz: float
    freq_ba_ghz: float
    polarization: str


@dataclass(frozen=True)
class SearchBBox:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


@dataclass(frozen=True)
class EMCInput:
    direction: str
    aggressor_eirp_dbm: float
    aggressor_atpc_db: float
    aggressor_freq_ghz: float
    victim_wanted_eirp_dbm: float
    victim_wanted_freq_ghz: float
    victim_bw_mhz: float
    victim_noise_figure_db: float
    victim_rx_antenna_gain_dbi: float
    victim_rx_attenuation_db: float
    overlap_ratio: float
    freq_delta_mhz: float
    cross_pol_bonus_db: float
    enable_mask_lookup: bool
    aggressor_main_azimuth_deg: Optional[float] = None
    aggressor_main_elevation_deg: Optional[float] = None
    aggressor_interference_azimuth_deg: Optional[float] = None
    aggressor_interference_elevation_deg: Optional[float] = None
    victim_main_azimuth_deg: Optional[float] = None
    victim_main_elevation_deg: Optional[float] = None
    victim_interference_azimuth_deg: Optional[float] = None
    victim_interference_elevation_deg: Optional[float] = None
    aggressor_off_axis_deg: Optional[float] = None
    victim_off_axis_deg: Optional[float] = None


@dataclass(frozen=True)
class PairwiseEmcResult:
    direction: str
    interfering_link_id: str
    interfering_permit_number: Optional[str]
    interfering_operator_name: Optional[str]
    conflict_type: str
    relationship: str
    distance_km: float
    margin_db: Optional[float]
    ci_db: Optional[float]
    degradation_db: Optional[float]
    overlap_ratio: float
    effective_freq_delta_mhz: Optional[float]
    risk_level: str
    explanation: str
    is_blocking: bool = False


@dataclass(frozen=True)
class CandidateFrequencyRecord:
    plan_symbol: str
    channel_ab: str
    channel_ba: str
    polarization: str
    freq_ab_ghz: float
    freq_ba_ghz: float
    status: str
    status_ab: str
    status_ba: str
    requested_distance: int
    score: float
    status_rank_value: int
    uke_like_margnad_db: Optional[float]
    uke_like_margodb_db: Optional[float]
    worst_margin_ab_db: Optional[float]
    worst_margin_ba_db: Optional[float]
    worst_duplex_margin_db: Optional[float]
    uke_like_problem_flags: list[str] = field(default_factory=list)
    inferred_uke_like_status: str = "REJECTED"
    pairwise_red_count: int = 0
    pairwise_cochannel_count: int = 0
    pairwise_blocking_count: int = 0
    access_like_dobry_kanal_seed: str = "0"
    access_like_dobry_kanal_value: str = "0"
    access_like_problem_pair_count: int = 0
    access_like_problem_decision: Optional[int] = None
    access_like_problem_decision_1_count: int = 0
    access_like_problem_decision_2_count: int = 0
    access_like_qualification_state: str = "FAILED"
    access_like_qualification_rank: int = 2
    access_like_status_seed: int = 1
    access_like_status_code: int = 1
    access_like_status_label: str = "PENDING"
    access_like_state_notes: list[str] = field(default_factory=list)
    pairwise_results: list[PairwiseEmcResult] = field(default_factory=list)


@dataclass(frozen=True)
class ConflictAssessment:
    link_id: str
    operator_name: Optional[str]
    permit_number: Optional[str]
    same_operator: bool
    conflict_type: str
    role: str
    score: float
    risk_level: str
    distance_km: float
    freq_delta_ab_mhz: Optional[float]
    freq_delta_ba_mhz: Optional[float]
    freq_delta_cross_ab_mhz: Optional[float]
    freq_delta_cross_ba_mhz: Optional[float]
    effective_freq_delta_mhz: Optional[float]
    overlap_ab_ratio: float
    overlap_ba_ratio: float
    estimated_interference_victim_dbm: Optional[float]
    estimated_interference_aggressor_dbm: Optional[float]
    estimated_ci_victim_db: Optional[float]
    estimated_ci_aggressor_db: Optional[float]
    estimated_degradation_victim_db: Optional[float]
    estimated_degradation_aggressor_db: Optional[float]
    estimated_margin_ab_db: Optional[float]
    estimated_margin_ba_db: Optional[float]
    decision_explanation: str
    relationship: str
    shared_site_count: int
    same_span: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelAssessment:
    candidate: ChannelCandidate
    status: str
    score: float
    red_conflicts: int
    amber_conflicts: int
    green_conflicts: int
    candidate_links_count: int
    best_explanation: str
    rejection_reasons: list[str] = field(default_factory=list)
    conflicts: list[ConflictAssessment] = field(default_factory=list)
    status_ab: str = "REJECTED"
    status_ba: str = "REJECTED"
    reasons_ab: list[str] = field(default_factory=list)
    reasons_ba: list[str] = field(default_factory=list)
    ignored_conflicts: list[ConflictAssessment] = field(default_factory=list)


@dataclass(frozen=True)
class AnalysisResult:
    request_operator_name: str
    bbox: SearchBBox
    candidate_links: list[DuplexLink]
    channel_candidates: list[ChannelCandidate]
    candidate_frequency_records: list[CandidateFrequencyRecord]
    accepted_assessments: list[ChannelAssessment]
    conditional_assessments: list[ChannelAssessment]
    rejected_assessments: list[ChannelAssessment]
    channel_assessments: list[ChannelAssessment]


def _min_optional(values: list[Optional[float]]) -> Optional[float]:
    concrete = [value for value in values if value is not None]
    return min(concrete) if concrete else None


def build_pairwise_emc_results(assessment: ChannelAssessment) -> list[PairwiseEmcResult]:
    results: list[PairwiseEmcResult] = []
    for conflict in assessment.conflicts:
        is_blocking = is_blocking_conflict(conflict)
        results.append(
            PairwiseEmcResult(
                direction="A->B",
                interfering_link_id=conflict.link_id,
                interfering_permit_number=conflict.permit_number,
                interfering_operator_name=conflict.operator_name,
                conflict_type=conflict.conflict_type,
                relationship=conflict.relationship,
                distance_km=conflict.distance_km,
                margin_db=conflict.estimated_margin_ab_db,
                ci_db=conflict.details.get("estimated_ci_ab_db"),
                degradation_db=conflict.details.get("estimated_degradation_ab_db"),
                overlap_ratio=conflict.overlap_ab_ratio,
                effective_freq_delta_mhz=conflict.effective_freq_delta_mhz,
                risk_level=conflict.risk_level,
                explanation=conflict.decision_explanation,
                is_blocking=is_blocking,
            )
        )
        results.append(
            PairwiseEmcResult(
                direction="B->A",
                interfering_link_id=conflict.link_id,
                interfering_permit_number=conflict.permit_number,
                interfering_operator_name=conflict.operator_name,
                conflict_type=conflict.conflict_type,
                relationship=conflict.relationship,
                distance_km=conflict.distance_km,
                margin_db=conflict.estimated_margin_ba_db,
                ci_db=conflict.details.get("estimated_ci_ba_db"),
                degradation_db=conflict.details.get("estimated_degradation_ba_db"),
                overlap_ratio=conflict.overlap_ba_ratio,
                effective_freq_delta_mhz=conflict.effective_freq_delta_mhz,
                risk_level=conflict.risk_level,
                explanation=conflict.decision_explanation,
                is_blocking=is_blocking,
            )
        )
    return results


def _pairwise_result_is_problem(result: PairwiseEmcResult) -> bool:
    if result.margin_db is not None and result.margin_db < 0.0:
        return True
    if result.degradation_db is not None and result.degradation_db > MAX_ACCEPTED_DEGRADATION_DB:
        return True
    if result.ci_db is not None and result.overlap_ratio > 0.0 and result.ci_db < MIN_ACCEPTED_CI_DB:
        return True
    return False


def _pairwise_problem_coordination_decision(result: PairwiseEmcResult) -> int:
    ci_db = result.ci_db if result.ci_db is not None else 999.0
    degradation_db = result.degradation_db if result.degradation_db is not None else 0.0
    conditional_margin_db = _emc_margin_at_thresholds(
        ci_db,
        degradation_db,
        MIN_CONDITIONAL_CI_DB,
        MAX_CONDITIONAL_DEGRADATION_DB,
    )
    return 1 if conditional_margin_db >= 0.0 else 2


def infer_access_like_candidate_state(
    pairwise_results: list[PairwiseEmcResult],
    worst_duplex_margin_db: Optional[float],
    red_count: int,
) -> dict[str, Any]:
    problem_results = [result for result in pairwise_results if _pairwise_result_is_problem(result)]
    decision_1_count = 0
    decision_2_count = 0
    notes: list[str] = ['DobryKanal initialised to "0"', "statusfk initialised to 1"]

    for result in problem_results:
        decision = _pairwise_problem_coordination_decision(result)
        if decision == 1:
            decision_1_count += 1
        else:
            decision_2_count += 1

    problem_decision: Optional[int]
    if decision_2_count:
        problem_decision = 2
        notes.append("At least one problem pair exceeds conditional coordination thresholds")
    elif decision_1_count:
        problem_decision = 1
        notes.append("Problem pairs exist, but all stay within conditional coordination thresholds")
    else:
        problem_decision = None
        notes.append("No problem pairs detected under Access-like strict thresholds")

    if problem_decision is None:
        dobry_kanal_value = "1"
        notes.append("DobryKanal promoted to 1 in experimental model")
    elif problem_decision == 1:
        dobry_kanal_value = "1"
        notes.append("DobryKanal stays viable despite coordination-required pairs")
    else:
        dobry_kanal_value = "0"
        notes.append("DobryKanal remains 0 because a pair requires hard rejection")

    accepted_margin_ok = worst_duplex_margin_db is None or worst_duplex_margin_db >= 0.0
    conditional_margin_ok = worst_duplex_margin_db is None or worst_duplex_margin_db >= -3.0
    if problem_decision == 2 or red_count > 0:
        qualification_state = "FAILED"
        qualification_rank = 2
        notes.append("Qualification failed due to hard problem decision or RED pair")
    elif problem_decision == 1 or not accepted_margin_ok:
        qualification_state = "COORDINATION_REQUIRED"
        qualification_rank = 1
        notes.append("Qualification requires coordination / conditional acceptance path")
    else:
        qualification_state = "QUALIFIED"
        qualification_rank = 0
        notes.append("Qualification passed without conditional problem state")

    selected_for_report = (
        qualification_state != "FAILED"
        and dobry_kanal_value == "1"
        and conditional_margin_ok
    )
    status_code = 2 if selected_for_report else 1
    status_label = "SELECTED" if status_code == 2 else "PENDING"
    notes.append(f"Experimental final Status={status_code}")

    return {
        "dobry_kanal_seed": "0",
        "dobry_kanal_value": dobry_kanal_value,
        "problem_pair_count": len(problem_results),
        "problem_decision": problem_decision,
        "problem_decision_1_count": decision_1_count,
        "problem_decision_2_count": decision_2_count,
        "qualification_state": qualification_state,
        "qualification_rank": qualification_rank,
        "status_seed": 1,
        "status_code": status_code,
        "status_label": status_label,
        "state_notes": notes,
    }


def build_candidate_frequency_record(
    request: WlrRequest,
    assessment: ChannelAssessment,
) -> CandidateFrequencyRecord:
    pairwise_results = build_pairwise_emc_results(assessment)
    worst_margin_ab_db = _min_optional([result.margin_db for result in pairwise_results if result.direction == "A->B"])
    worst_margin_ba_db = _min_optional([result.margin_db for result in pairwise_results if result.direction == "B->A"])
    worst_duplex_margin_db = _min_optional([worst_margin_ab_db, worst_margin_ba_db])
    # UKE candidate rows appear directional; in the observed snapshot the row with kod_nadawczej=A
    # carries receiver-side margin (MargOdb), while kod_nadawczej=B carries transmitter-side margin (MargNad).
    uke_like_margnad_db = worst_margin_ba_db
    uke_like_margodb_db = worst_margin_ab_db
    uke_like_problem_flags: list[str] = []
    if worst_margin_ab_db is not None and worst_margin_ab_db < 0.0:
        uke_like_problem_flags.append("negative_margin_ab")
    if worst_margin_ba_db is not None and worst_margin_ba_db < 0.0:
        uke_like_problem_flags.append("negative_margin_ba")
    blocking_count = sum(1 for result in pairwise_results if result.is_blocking)
    cochannel_count = sum(1 for result in pairwise_results if result.conflict_type == "cochannel")
    red_count = sum(1 for result in pairwise_results if result.risk_level == "red")
    if blocking_count:
        uke_like_problem_flags.append("blocking_pairs_present")
    if cochannel_count:
        uke_like_problem_flags.append("cochannel_pairs_present")
    if red_count:
        uke_like_problem_flags.append("red_pairs_present")
    if not uke_like_problem_flags:
        uke_like_problem_flags.append("clean_candidate")

    if worst_duplex_margin_db is None or (worst_duplex_margin_db >= 0.0 and blocking_count == 0):
        inferred_uke_like_status = "ACCEPTED"
    elif worst_duplex_margin_db >= -3.0 and red_count == 0:
        inferred_uke_like_status = "CONDITIONAL"
    else:
        inferred_uke_like_status = "REJECTED"
    access_like_state = infer_access_like_candidate_state(pairwise_results, worst_duplex_margin_db, red_count)
    return CandidateFrequencyRecord(
        plan_symbol=assessment.candidate.plan_symbol,
        channel_ab=assessment.candidate.channel_ab,
        channel_ba=assessment.candidate.channel_ba,
        polarization=assessment.candidate.polarization,
        freq_ab_ghz=assessment.candidate.freq_ab_ghz,
        freq_ba_ghz=assessment.candidate.freq_ba_ghz,
        status=assessment.status,
        status_ab=assessment.status_ab,
        status_ba=assessment.status_ba,
        requested_distance=requested_channel_distance(request, assessment.candidate),
        score=assessment.score,
        status_rank_value=status_rank(assessment.status),
        uke_like_margnad_db=uke_like_margnad_db,
        uke_like_margodb_db=uke_like_margodb_db,
        uke_like_problem_flags=uke_like_problem_flags,
        inferred_uke_like_status=inferred_uke_like_status,
        worst_margin_ab_db=worst_margin_ab_db,
        worst_margin_ba_db=worst_margin_ba_db,
        worst_duplex_margin_db=worst_duplex_margin_db,
        pairwise_red_count=red_count,
        pairwise_cochannel_count=cochannel_count,
        pairwise_blocking_count=blocking_count,
        access_like_dobry_kanal_seed=access_like_state["dobry_kanal_seed"],
        access_like_dobry_kanal_value=access_like_state["dobry_kanal_value"],
        access_like_problem_pair_count=access_like_state["problem_pair_count"],
        access_like_problem_decision=access_like_state["problem_decision"],
        access_like_problem_decision_1_count=access_like_state["problem_decision_1_count"],
        access_like_problem_decision_2_count=access_like_state["problem_decision_2_count"],
        access_like_qualification_state=access_like_state["qualification_state"],
        access_like_qualification_rank=access_like_state["qualification_rank"],
        access_like_status_seed=access_like_state["status_seed"],
        access_like_status_code=access_like_state["status_code"],
        access_like_status_label=access_like_state["status_label"],
        access_like_state_notes=access_like_state["state_notes"],
        pairwise_results=pairwise_results,
    )


def build_uke_like_directional_candidate_rows(record: CandidateFrequencyRecord) -> list[dict[str, Any]]:
    return [
        {
            "kod_nadawczej": "A",
            "channel_number": record.channel_ba,
            "frequency_ghz": record.freq_ba_ghz,
            "polarization": record.polarization,
            "status": record.status,
            "margnad_db": None,
            "margodb_db": record.uke_like_margodb_db,
        },
        {
            "kod_nadawczej": "B",
            "channel_number": record.channel_ab,
            "frequency_ghz": record.freq_ab_ghz,
            "polarization": record.polarization,
            "status": record.status,
            "margnad_db": record.uke_like_margnad_db,
            "margodb_db": None,
        },
    ]


def build_candidate_frequency_records(
    request: WlrRequest,
    assessments: list[ChannelAssessment],
) -> list[CandidateFrequencyRecord]:
    return [build_candidate_frequency_record(request, assessment) for assessment in assessments]


def _record_worst_margin(record: CandidateFrequencyRecord) -> float:
    return record.worst_duplex_margin_db if record.worst_duplex_margin_db is not None else 999.0


def _record_pairwise_red_count(record: CandidateFrequencyRecord) -> int:
    return record.pairwise_red_count


def _record_pairwise_cochannel_count(record: CandidateFrequencyRecord) -> int:
    return record.pairwise_cochannel_count


def _record_status_priority(record: CandidateFrequencyRecord) -> tuple[int, int]:
    both_ok = 0 if record.status_ab == "ACCEPTED" and record.status_ba == "ACCEPTED" else 1
    one_ok = 0 if record.status_ab == "ACCEPTED" or record.status_ba == "ACCEPTED" else 1
    return both_ok, one_ok


def _candidate_record_sort_key(
    request: WlrRequest,
    record: CandidateFrequencyRecord,
    prioritize_orientation: bool,
) -> tuple[Any, ...]:
    candidate = ChannelCandidate(
        plan_symbol=record.plan_symbol,
        channel_ab=record.channel_ab,
        channel_ba=record.channel_ba,
        freq_ab_ghz=record.freq_ab_ghz,
        freq_ba_ghz=record.freq_ba_ghz,
        polarization=record.polarization,
    )
    orientation = orientation_preference_penalty(request, candidate) if prioritize_orientation else 0
    both_ok, one_ok = _record_status_priority(record)
    return (
        record.status_rank_value,
        both_ok,
        one_ok,
        orientation,
        -_record_worst_margin(record),
        record.pairwise_blocking_count,
        _record_pairwise_cochannel_count(record),
        _record_pairwise_red_count(record),
        record.requested_distance,
        polarization_preference_penalty(request, candidate),
        record.score,
        record.channel_ab,
        record.channel_ba,
        record.polarization,
    )


def _candidate_record_access_like_sort_key(
    request: WlrRequest,
    record: CandidateFrequencyRecord,
    prioritize_orientation: bool,
) -> tuple[Any, ...]:
    candidate = ChannelCandidate(
        plan_symbol=record.plan_symbol,
        channel_ab=record.channel_ab,
        channel_ba=record.channel_ba,
        freq_ab_ghz=record.freq_ab_ghz,
        freq_ba_ghz=record.freq_ba_ghz,
        polarization=record.polarization,
    )
    orientation = orientation_preference_penalty(request, candidate) if prioritize_orientation else 0
    problem_decision_rank = 0 if record.access_like_problem_decision in (None, 1) else 1
    return (
        0 if record.access_like_status_code == 2 else 1,
        record.access_like_qualification_rank,
        problem_decision_rank,
        orientation,
        record.access_like_problem_decision_2_count,
        record.access_like_problem_pair_count,
        -_record_worst_margin(record),
        record.pairwise_blocking_count,
        _record_pairwise_cochannel_count(record),
        _record_pairwise_red_count(record),
        record.requested_distance,
        polarization_preference_penalty(request, candidate),
        record.score,
        record.channel_ab,
        record.channel_ba,
        record.polarization,
    )
    orientation = orientation_preference_penalty(request, candidate) if prioritize_orientation else 0
    both_ok, one_ok = _record_status_priority(record)
    return (
        record.status_rank_value,
        both_ok,
        one_ok,
        orientation,
        -_record_worst_margin(record),
        record.pairwise_blocking_count,
        _record_pairwise_cochannel_count(record),
        _record_pairwise_red_count(record),
        record.requested_distance,
        polarization_preference_penalty(request, candidate),
        record.score,
        record.channel_ab,
        record.channel_ba,
        record.polarization,
    )


def status_rank(status: str) -> int:
    return {"ACCEPTED": 0, "CONDITIONAL": 1, "REJECTED": 2}.get(status, 9)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r, lon1_r = radians(lat1), radians(lon1)
    lat2_r, lon2_r = radians(lat2), radians(lon2)
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = sin(dlat / 2.0) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlon / 2.0) ** 2
    c = 2.0 * asin(min(1.0, sqrt(a)))
    return EARTH_RADIUS_KM * c


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r, lat2_r = radians(lat1), radians(lat2)
    dlon_r = radians(lon2 - lon1)
    x = sin(dlon_r) * cos(lat2_r)
    y = cos(lat1_r) * sin(lat2_r) - sin(lat1_r) * cos(lat2_r) * cos(dlon_r)
    bearing = degrees(atan2(x, y))
    return (bearing + 360.0) % 360.0


def angular_difference_deg(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return diff if diff <= 180.0 else 360.0 - diff


def fspl_db(distance_km: float, freq_ghz: float) -> float:
    distance_km = max(distance_km, 0.001)
    freq_ghz = max(freq_ghz, 0.001)
    return 92.45 + 20.0 * __import__("math").log10(distance_km) + 20.0 * __import__("math").log10(freq_ghz)


def spectral_overlap_ratio(f1_ghz: float, bw1_mhz: float, f2_ghz: float, bw2_mhz: float) -> float:
    f1_mhz = f1_ghz * 1000.0
    f2_mhz = f2_ghz * 1000.0
    a1, b1 = f1_mhz - bw1_mhz / 2.0, f1_mhz + bw1_mhz / 2.0
    a2, b2 = f2_mhz - bw2_mhz / 2.0, f2_mhz + bw2_mhz / 2.0
    overlap = max(0.0, min(b1, b2) - max(a1, a2))
    return overlap / min(bw1_mhz, bw2_mhz)


def thermal_noise_dbm(bw_mhz: float, noise_figure_db: float = DEFAULT_RECEIVER_NOISE_FIGURE_DB) -> float:
    bw_hz = max(bw_mhz, 0.001) * 1_000_000.0
    return -174.0 + 10.0 * log10(bw_hz) + noise_figure_db


def threshold_degradation_db(interference_dbm: float, noise_dbm: float) -> float:
    ratio_linear = 10.0 ** ((interference_dbm - noise_dbm) / 10.0)
    return 10.0 * log10(1.0 + ratio_linear)


def build_search_bbox(request: WlrRequest, radius_km: float = DEFAULT_RADIUS_KM) -> SearchBBox:
    lat_margin = radius_km / 111.0
    lon_scale_a = max(cos(radians(request.site_a.lat_deg)), 0.1)
    lon_scale_b = max(cos(radians(request.site_b.lat_deg)), 0.1)
    lon_margin = max(radius_km / (111.0 * lon_scale_a), radius_km / (111.0 * lon_scale_b))

    min_lon = min(request.site_a.lon_deg, request.site_b.lon_deg) - lon_margin
    max_lon = max(request.site_a.lon_deg, request.site_b.lon_deg) + lon_margin
    min_lat = min(request.site_a.lat_deg, request.site_b.lat_deg) - lat_margin
    max_lat = max(request.site_a.lat_deg, request.site_b.lat_deg) + lat_margin
    return SearchBBox(min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat)


def bbox_contains_point(bbox: SearchBBox, lon: float, lat: float) -> bool:
    return bbox.min_lon <= lon <= bbox.max_lon and bbox.min_lat <= lat <= bbox.max_lat


def request_midpoint(request: WlrRequest) -> tuple[float, float]:
    return (
        (request.site_a.lat_deg + request.site_b.lat_deg) / 2.0,
        (request.site_a.lon_deg + request.site_b.lon_deg) / 2.0,
    )


def link_midpoint(link: DuplexLink) -> tuple[float, float]:
    return (
        (link.site_a.point.lat_deg + link.site_b.point.lat_deg) / 2.0,
        (link.site_a.point.lon_deg + link.site_b.point.lon_deg) / 2.0,
    )


def _endpoint_height_asl_m(endpoint: Any) -> Optional[float]:
    terrain = getattr(endpoint, "terrain_m_asl", None)
    antenna = getattr(endpoint, "antenna_height_m_agl", None)
    if terrain is None and antenna is None:
        return None
    return (terrain or 0.0) + (antenna or 0.0)


def hcm_fixed_service_coordination_distance_km(request: WlrRequest) -> Optional[float]:
    freq_candidates = [freq for freq in (request.freq_ab_ghz, request.freq_ba_ghz) if freq is not None]
    if not freq_candidates:
        return None
    freq_ghz = min(freq_candidates)

    if 1.0 <= freq_ghz <= 5.0:
        distance_km = 200.0
    elif 5.0 < freq_ghz <= 10.0:
        distance_km = 150.0
    elif 10.0 < freq_ghz <= 12.0:
        distance_km = 100.0
    elif 12.0 < freq_ghz <= 20.0:
        distance_km = 80.0
    elif 20.0 < freq_ghz <= 24.5:
        distance_km = 60.0
    elif 24.5 < freq_ghz <= 30.0:
        distance_km = 40.0
    elif 30.0 < freq_ghz <= 39.5:
        distance_km = 30.0
    elif 39.5 < freq_ghz <= 43.5:
        distance_km = 20.0
    else:
        return None

    if freq_ghz < 10.0:
        height_a = _endpoint_height_asl_m(request.site_a)
        height_b = _endpoint_height_asl_m(request.site_b)
        if height_a is not None and height_b is not None and height_a < ANNEX11_LOW_HEIGHT_LIMIT_M_ASL and height_b < ANNEX11_LOW_HEIGHT_LIMIT_M_ASL:
            distance_km = min(distance_km, 100.0)

    return distance_km


def _local_xy_km(lat: float, lon: float, origin_lat: float, origin_lon: float) -> tuple[float, float]:
    mean_lat = radians((lat + origin_lat) / 2.0)
    x = (lon - origin_lon) * 111.320 * cos(mean_lat)
    y = (lat - origin_lat) * 110.574
    return x, y


def point_to_segment_distance_km(
    point_lat: float,
    point_lon: float,
    a_lat: float,
    a_lon: float,
    b_lat: float,
    b_lon: float,
) -> float:
    origin_lat = a_lat
    origin_lon = a_lon
    px, py = _local_xy_km(point_lat, point_lon, origin_lat, origin_lon)
    ax, ay = 0.0, 0.0
    bx, by = _local_xy_km(b_lat, b_lon, origin_lat, origin_lon)

    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    ab_len_sq = abx * abx + aby * aby
    if ab_len_sq <= 1e-9:
        return sqrt((px - ax) ** 2 + (py - ay) ** 2)

    t = max(0.0, min(1.0, (apx * abx + apy * aby) / ab_len_sq))
    cx = ax + t * abx
    cy = ay + t * aby
    return sqrt((px - cx) ** 2 + (py - cy) ** 2)


def link_distance_to_request_corridor_km(request: WlrRequest, link: DuplexLink) -> float:
    samples = [
        (link.site_a.point.lat_deg, link.site_a.point.lon_deg),
        (link.site_b.point.lat_deg, link.site_b.point.lon_deg),
        link_midpoint(link),
    ]
    return min(
        point_to_segment_distance_km(
            sample_lat,
            sample_lon,
            request.site_a.lat_deg,
            request.site_a.lon_deg,
            request.site_b.lat_deg,
            request.site_b.lon_deg,
        )
        for sample_lat, sample_lon in samples
    )


def _endpoint_distances_km(request: WlrRequest, link: DuplexLink) -> dict[str, float]:
    return {
        "a_to_a": haversine_km(request.site_a.lat_deg, request.site_a.lon_deg, link.site_a.point.lat_deg, link.site_a.point.lon_deg),
        "a_to_b": haversine_km(request.site_a.lat_deg, request.site_a.lon_deg, link.site_b.point.lat_deg, link.site_b.point.lon_deg),
        "b_to_a": haversine_km(request.site_b.lat_deg, request.site_b.lon_deg, link.site_a.point.lat_deg, link.site_a.point.lon_deg),
        "b_to_b": haversine_km(request.site_b.lat_deg, request.site_b.lon_deg, link.site_b.point.lat_deg, link.site_b.point.lon_deg),
    }



def shared_site_count(request: WlrRequest, link: DuplexLink, threshold_km: float = SITE_MATCH_THRESHOLD_KM) -> int:
    distances = _endpoint_distances_km(request, link)
    count = 0
    if min(distances["a_to_a"], distances["a_to_b"]) <= threshold_km:
        count += 1
    if min(distances["b_to_a"], distances["b_to_b"]) <= threshold_km:
        count += 1
    return count



def is_same_span(request: WlrRequest, link: DuplexLink, threshold_km: float = SITE_MATCH_THRESHOLD_KM) -> bool:
    distances = _endpoint_distances_km(request, link)
    direct = distances["a_to_a"] <= threshold_km and distances["b_to_b"] <= threshold_km
    reverse = distances["a_to_b"] <= threshold_km and distances["b_to_a"] <= threshold_km
    return direct or reverse



def classify_relationship(request: WlrRequest, link: DuplexLink) -> str:
    if is_same_span(request, link):
        return "same_span"
    matches = shared_site_count(request, link)
    if matches == 2:
        return "same_span_like"
    if matches == 1:
        return "shared_site"
    return "external"


def effective_interference_distance_km(request: WlrRequest, link: DuplexLink, relationship: str) -> float:
    endpoint_distances = _endpoint_distances_km(request, link)
    midpoint_lat_req, midpoint_lon_req = request_midpoint(request)
    midpoint_lat_link, midpoint_lon_link = link_midpoint(link)
    midpoint_distance = haversine_km(midpoint_lat_req, midpoint_lon_req, midpoint_lat_link, midpoint_lon_link)

    if relationship == "same_span":
        return max(0.5, midpoint_distance)

    if relationship == "shared_site":
        req_bearing_ab = initial_bearing_deg(
            request.site_a.lat_deg,
            request.site_a.lon_deg,
            request.site_b.lat_deg,
            request.site_b.lon_deg,
        )
        req_bearing_ba = initial_bearing_deg(
            request.site_b.lat_deg,
            request.site_b.lon_deg,
            request.site_a.lat_deg,
            request.site_a.lon_deg,
        )
        link_bearing_ab = initial_bearing_deg(
            link.site_a.point.lat_deg,
            link.site_a.point.lon_deg,
            link.site_b.point.lat_deg,
            link.site_b.point.lon_deg,
        )
        link_bearing_ba = initial_bearing_deg(
            link.site_b.point.lat_deg,
            link.site_b.point.lon_deg,
            link.site_a.point.lat_deg,
            link.site_a.point.lon_deg,
        )
        azimuth_delta = min(
            angular_difference_deg(req_bearing_ab, link_bearing_ab),
            angular_difference_deg(req_bearing_ab, link_bearing_ba),
            angular_difference_deg(req_bearing_ba, link_bearing_ab),
            angular_difference_deg(req_bearing_ba, link_bearing_ba),
        )
        geometric_floor = max(0.3, midpoint_distance, 0.05 * azimuth_delta)
        return geometric_floor

    if relationship == "same_span_like":
        return max(0.5, midpoint_distance)

    return max(0.05, min(endpoint_distances.values()))


@lru_cache(maxsize=1)
def _get_duplex_links_cached() -> tuple[DuplexLink, ...]:
    dataset = get_permissions_dataset()
    report = pair_duplex_links(dataset.records)
    return tuple(report.duplex_links)


def get_duplex_links() -> list[DuplexLink]:
    return list(_get_duplex_links_cached())


def select_candidate_links(
    request: WlrRequest,
    plan: FrequencyPlan,
    request_operator_name: str = DEFAULT_REQUEST_OPERATOR,
    radius_km: float = DEFAULT_RADIUS_KM,
    max_links: int = DEFAULT_MAX_LINKS,
    apply_corridor_filter: bool = True,
) -> tuple[SearchBBox, list[DuplexLink]]:
    bbox = build_search_bbox(request, radius_km)
    mid_lat, mid_lon = request_midpoint(request)
    selected: list[tuple[float, DuplexLink]] = []

    links_pool = get_internal_duplex_links_for_plan(plan) if internal_catalog_available() else get_duplex_links()
    for link in links_pool:
        points = [
            (link.site_a.point.lon_deg, link.site_a.point.lat_deg),
            (link.site_b.point.lon_deg, link.site_b.point.lat_deg),
        ]
        if not any(bbox_contains_point(bbox, lon, lat) for lon, lat in points):
            link_lat, link_lon = link_midpoint(link)
            if haversine_km(mid_lat, mid_lon, link_lat, link_lon) > radius_km:
                continue

        if apply_corridor_filter:
            corridor_distance = link_distance_to_request_corridor_km(request, link)
            if corridor_distance > DEFAULT_CORRIDOR_KM and shared_site_count(request, link) == 0 and not is_same_span(request, link):
                continue

        link_lat, link_lon = link_midpoint(link)
        distance = haversine_km(mid_lat, mid_lon, link_lat, link_lon)
        selected.append((distance, link))

    selected.sort(key=lambda item: item[0])
    if max_links <= 0:
        return bbox, [link for _, link in selected]
    return bbox, [link for _, link in selected[:max_links]]


def find_matching_plan(request: WlrRequest) -> Optional[FrequencyPlan]:
    plans = get_plan_dataset().plans
    if request.plan_symbol and request.plan_symbol in plans:
        return plans[request.plan_symbol]
    if request.plan_symbol:
        normalized = normalize_plan_symbol_key(request.plan_symbol)
        if normalized in plans:
            return plans[normalized]

    if request.channel_width_mhz is None:
        return None

    matches = [
        plan for plan in plans.values()
        if plan.channel_width_mhz is not None and abs(plan.channel_width_mhz - request.channel_width_mhz) <= 0.001
    ]
    if not matches:
        return None
    if request.freq_ab_ghz is not None:
        for plan in matches:
            if any(abs(ch.center_freq_ghz - request.freq_ab_ghz) <= 0.001 for ch in plan.channels):
                return plan
    return matches[0]


def link_matches_plan(plan: FrequencyPlan, link: DuplexLink) -> bool:
    if plan.channel_width_mhz is not None and link.emission_ab.channel_width_mhz is not None:
        if abs(plan.channel_width_mhz - link.emission_ab.channel_width_mhz) > 0.001:
            return False

    channel_freqs = [channel.center_freq_ghz for channel in plan.channels]
    if not channel_freqs:
        return False

    min_plan_freq = min(channel_freqs)
    max_plan_freq = max(channel_freqs)
    lower_bound = min_plan_freq - PLAN_FREQ_TOLERANCE_GHZ
    upper_bound = max_plan_freq + PLAN_FREQ_TOLERANCE_GHZ

    return (
        lower_bound <= link.emission_ab.center_freq_ghz <= upper_bound and
        lower_bound <= link.emission_ba.center_freq_ghz <= upper_bound
    )


def candidate_matches_frequency_window(
    request: WlrRequest,
    candidate: ChannelCandidate,
    link: DuplexLink,
) -> bool:
    request_bw_mhz = request.channel_width_mhz or 1.0
    overlap_pairs = [
        (
            candidate.freq_ab_ghz * 1000.0,
            link.emission_ab.center_freq_mhz,
            link.emission_ab.channel_width_mhz or request_bw_mhz,
        ),
        (
            candidate.freq_ba_ghz * 1000.0,
            link.emission_ba.center_freq_mhz,
            link.emission_ba.channel_width_mhz or request_bw_mhz,
        ),
        (
            candidate.freq_ab_ghz * 1000.0,
            link.emission_ba.center_freq_mhz,
            link.emission_ba.channel_width_mhz or request_bw_mhz,
        ),
        (
            candidate.freq_ba_ghz * 1000.0,
            link.emission_ab.center_freq_mhz,
            link.emission_ab.channel_width_mhz or request_bw_mhz,
        ),
    ]
    if not any(
        (abs(link_freq_mhz - candidate_freq_mhz) - 1e-8) <= ((link_bw_mhz + request_bw_mhz) * 0.5)
        for candidate_freq_mhz, link_freq_mhz, link_bw_mhz in overlap_pairs
    ):
        return False

    return True


def generate_channel_candidates(request: WlrRequest, plan: FrequencyPlan) -> list[ChannelCandidate]:
    candidates: list[ChannelCandidate] = []

    if plan.has_prime_channels:
        lower_by_number = {
            ch.channel_number: ch
            for ch in plan.channels
            if ch.subband in {"lower", "single"}
        }
        upper_by_number = {
            ch.channel_number: ch
            for ch in plan.channels
            if ch.subband in {"upper", "single"} or ch.is_prime
        }

        def _append_if_pair_exists(channel_ab: str, channel_ba: str, polarization: str) -> None:
            ch_ab = lower_by_number.get(channel_ab) or upper_by_number.get(channel_ab)
            ch_ba = lower_by_number.get(channel_ba) or upper_by_number.get(channel_ba)
            if ch_ab is None or ch_ba is None:
                return
            candidates.append(
                ChannelCandidate(
                    plan_symbol=plan.symbol,
                    channel_ab=ch_ab.channel_number,
                    channel_ba=ch_ba.channel_number,
                    freq_ab_ghz=ch_ab.center_freq_ghz,
                    freq_ba_ghz=ch_ba.center_freq_ghz,
                    polarization=polarization,
                )
            )

        base_channels = sorted(
            {
                ch.channel_number.rstrip("'")
                for ch in plan.channels
                if ch.channel_number
            },
            key=lambda value: (int(value) if value.isdigit() else value),
        )
        for base_channel in base_channels:
            prime_channel = f"{base_channel}'"
            for polarization in ("V", "H"):
                _append_if_pair_exists(base_channel, prime_channel, polarization)
                _append_if_pair_exists(prime_channel, base_channel, polarization)
    else:
        singles = sorted(plan.channels, key=lambda ch: (ch.channel_index, ch.center_freq_ghz))
        for ch in singles:
            for polarization in ("V", "H"):
                candidates.append(
                    ChannelCandidate(
                        plan_symbol=plan.symbol,
                        channel_ab=ch.channel_number,
                        channel_ba=ch.channel_number,
                        freq_ab_ghz=ch.center_freq_ghz,
                        freq_ba_ghz=ch.center_freq_ghz,
                        polarization=polarization,
                    )
                )

    deduped: list[ChannelCandidate] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        key = (candidate.channel_ab, candidate.channel_ba, candidate.polarization)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def estimate_off_axis_penalty_db(request: WlrRequest, link: DuplexLink) -> float:
    req_bearing_ab = initial_bearing_deg(request.site_a.lat_deg, request.site_a.lon_deg, request.site_b.lat_deg, request.site_b.lon_deg)
    req_bearing_ba = initial_bearing_deg(request.site_b.lat_deg, request.site_b.lon_deg, request.site_a.lat_deg, request.site_a.lon_deg)
    link_bearing_ab = initial_bearing_deg(link.site_a.point.lat_deg, link.site_a.point.lon_deg, link.site_b.point.lat_deg, link.site_b.point.lon_deg)
    link_bearing_ba = initial_bearing_deg(link.site_b.point.lat_deg, link.site_b.point.lon_deg, link.site_a.point.lat_deg, link.site_a.point.lon_deg)

    diff = min(
        angular_difference_deg(req_bearing_ab, link_bearing_ab),
        angular_difference_deg(req_bearing_ab, link_bearing_ba),
        angular_difference_deg(req_bearing_ba, link_bearing_ab),
        angular_difference_deg(req_bearing_ba, link_bearing_ba),
    )

    if diff <= 3.0:
        return 0.0
    if diff <= 10.0:
        return 6.0
    if diff <= 20.0:
        return 14.0
    if diff <= 30.0:
        return 22.0
    if diff <= 45.0:
        return 30.0
    if diff <= 60.0:
        return 38.0
    if diff <= 90.0:
        return 46.0
    return 55.0


def _angle_penalty_from_diff(diff_deg: float) -> float:
    if diff_deg <= 3.0:
        return 0.0
    if diff_deg <= 10.0:
        return 6.0
    if diff_deg <= 20.0:
        return 14.0
    if diff_deg <= 30.0:
        return 22.0
    if diff_deg <= 45.0:
        return 30.0
    if diff_deg <= 60.0:
        return 38.0
    if diff_deg <= 90.0:
        return 46.0
    return 55.0


def _site_distance_km(site_left: Any, site_right: Any) -> float:
    left_point = site_left.point if hasattr(site_left, "point") else site_left
    right_point = site_right.point if hasattr(site_right, "point") else site_right
    return haversine_km(left_point.lat_deg, left_point.lon_deg, right_point.lat_deg, right_point.lon_deg)


def _bearing_between_sites(site_from: Any, site_to: Any) -> Optional[float]:
    if _site_distance_km(site_from, site_to) <= 0.001:
        return None
    point_from = site_from.point if hasattr(site_from, "point") else site_from
    point_to = site_to.point if hasattr(site_to, "point") else site_to
    return initial_bearing_deg(point_from.lat_deg, point_from.lon_deg, point_to.lat_deg, point_to.lon_deg)


def _elevation_between_sites(site_from: Any, site_to: Any) -> Optional[float]:
    distance_km = _site_distance_km(site_from, site_to)
    if distance_km <= 0.001:
        return None
    height_from = _endpoint_height_asl_m(site_from)
    height_to = _endpoint_height_asl_m(site_to)
    if height_from is None or height_to is None:
        return None
    return degrees(atan2(height_to - height_from, distance_km * 1000.0))


def _vector_from_azimuth_elevation_deg(azimuth_deg: float, elevation_deg: float) -> tuple[float, float, float]:
    az = radians(azimuth_deg)
    el = radians(elevation_deg)
    horizontal = cos(el)
    x = horizontal * sin(az)
    y = horizontal * cos(az)
    z = sin(el)
    return x, y, z


def _spatial_angular_difference_deg(
    azimuth_a_deg: Optional[float],
    elevation_a_deg: Optional[float],
    azimuth_b_deg: Optional[float],
    elevation_b_deg: Optional[float],
) -> Optional[float]:
    if azimuth_a_deg is None or azimuth_b_deg is None:
        return None
    if elevation_a_deg is None or elevation_b_deg is None:
        return angular_difference_deg(azimuth_a_deg, azimuth_b_deg)
    ax, ay, az = _vector_from_azimuth_elevation_deg(azimuth_a_deg, elevation_a_deg)
    bx, by, bz = _vector_from_azimuth_elevation_deg(azimuth_b_deg, elevation_b_deg)
    dot = max(-1.0, min(1.0, ax * bx + ay * by + az * bz))
    return degrees(acos(dot))


def _endpoint_discrimination_metrics(
    tx_site: Any,
    intended_rx_site: Any,
    victim_rx_site: Any,
    victim_desired_tx_site: Any,
    tx_freq_ghz: Optional[float] = None,
    victim_rx_freq_ghz: Optional[float] = None,
) -> dict[str, Any]:
    coupling_distance_km = _site_distance_km(tx_site, victim_rx_site)
    if coupling_distance_km <= SITE_MATCH_THRESHOLD_KM:
        return {
            "total_penalty_db": 0.0,
            "coupling_distance_km": coupling_distance_km,
            "tx_main_azimuth_deg": None,
            "tx_main_elevation_deg": None,
            "tx_interference_azimuth_deg": None,
            "tx_interference_elevation_deg": None,
            "rx_main_azimuth_deg": None,
            "rx_main_elevation_deg": None,
            "rx_interference_azimuth_deg": None,
            "rx_interference_elevation_deg": None,
            "tx_off_axis_deg": None,
            "rx_off_axis_deg": None,
            "tx_penalty_db": 0.0,
            "rx_penalty_db": 0.0,
            "used_catalog_pattern": False,
        }

    tx_main_bearing = _bearing_between_sites(tx_site, intended_rx_site)
    tx_interference_bearing = _bearing_between_sites(tx_site, victim_rx_site)
    rx_main_bearing = _bearing_between_sites(victim_rx_site, victim_desired_tx_site)
    rx_interference_bearing = _bearing_between_sites(victim_rx_site, tx_site)
    tx_main_elevation = _elevation_between_sites(tx_site, intended_rx_site)
    tx_interference_elevation = _elevation_between_sites(tx_site, victim_rx_site)
    rx_main_elevation = _elevation_between_sites(victim_rx_site, victim_desired_tx_site)
    rx_interference_elevation = _elevation_between_sites(victim_rx_site, tx_site)

    tx_penalty_db = 0.0
    rx_penalty_db = 0.0
    used_catalog_pattern = False
    tx_azimuth_diff = None
    rx_azimuth_diff = None
    tx_diff = None
    rx_diff = None
    if tx_main_bearing is not None and tx_interference_bearing is not None:
        tx_azimuth_diff = angular_difference_deg(tx_main_bearing, tx_interference_bearing)
        tx_diff = _spatial_angular_difference_deg(
            tx_main_bearing,
            tx_main_elevation,
            tx_interference_bearing,
            tx_interference_elevation,
        )
        tx_penalty_db = _angle_penalty_from_diff(tx_azimuth_diff)
        catalog_penalty = interpolate_attenuation_db(
            getattr(tx_site, "antenna_type", None),
            getattr(tx_site, "antenna_vendor", None),
            tx_freq_ghz,
            tx_azimuth_diff,
        )
        if catalog_penalty is not None:
            tx_penalty_db = catalog_penalty
            used_catalog_pattern = True
    if rx_main_bearing is not None and rx_interference_bearing is not None:
        rx_azimuth_diff = angular_difference_deg(rx_main_bearing, rx_interference_bearing)
        rx_diff = _spatial_angular_difference_deg(
            rx_main_bearing,
            rx_main_elevation,
            rx_interference_bearing,
            rx_interference_elevation,
        )
        rx_penalty_db = _angle_penalty_from_diff(rx_azimuth_diff)
        catalog_penalty = interpolate_attenuation_db(
            getattr(victim_rx_site, "antenna_type", None),
            getattr(victim_rx_site, "antenna_vendor", None),
            victim_rx_freq_ghz,
            rx_azimuth_diff,
        )
        if catalog_penalty is not None:
            rx_penalty_db = catalog_penalty
            used_catalog_pattern = True
    total_penalty_db = tx_penalty_db + rx_penalty_db
    if used_catalog_pattern:
        return {
            "total_penalty_db": total_penalty_db,
            "coupling_distance_km": coupling_distance_km,
            "tx_main_azimuth_deg": tx_main_bearing,
            "tx_main_elevation_deg": tx_main_elevation,
            "tx_interference_azimuth_deg": tx_interference_bearing,
            "tx_interference_elevation_deg": tx_interference_elevation,
            "rx_main_azimuth_deg": rx_main_bearing,
            "rx_main_elevation_deg": rx_main_elevation,
            "rx_interference_azimuth_deg": rx_interference_bearing,
            "rx_interference_elevation_deg": rx_interference_elevation,
            "tx_off_axis_deg": tx_diff,
            "rx_off_axis_deg": rx_diff,
            "tx_azimuth_off_axis_deg": tx_azimuth_diff,
            "rx_azimuth_off_axis_deg": rx_azimuth_diff,
            "tx_penalty_db": tx_penalty_db,
            "rx_penalty_db": rx_penalty_db,
            "used_catalog_pattern": True,
        }
    if coupling_distance_km <= 1.0:
        total_penalty_db = min(total_penalty_db, 12.0)
    if coupling_distance_km <= 2.0:
        total_penalty_db = min(total_penalty_db, 24.0)
    if coupling_distance_km <= 5.0:
        total_penalty_db = min(total_penalty_db, 32.0)
    return {
        "total_penalty_db": total_penalty_db,
        "coupling_distance_km": coupling_distance_km,
        "tx_main_azimuth_deg": tx_main_bearing,
        "tx_main_elevation_deg": tx_main_elevation,
        "tx_interference_azimuth_deg": tx_interference_bearing,
        "tx_interference_elevation_deg": tx_interference_elevation,
        "rx_main_azimuth_deg": rx_main_bearing,
        "rx_main_elevation_deg": rx_main_elevation,
        "rx_interference_azimuth_deg": rx_interference_bearing,
        "rx_interference_elevation_deg": rx_interference_elevation,
        "tx_off_axis_deg": tx_diff,
        "rx_off_axis_deg": rx_diff,
        "tx_azimuth_off_axis_deg": tx_azimuth_diff,
        "rx_azimuth_off_axis_deg": rx_azimuth_diff,
        "tx_penalty_db": tx_penalty_db,
        "rx_penalty_db": rx_penalty_db,
        "used_catalog_pattern": used_catalog_pattern,
    }


def _request_leg_eirp_dbm(request: WlrRequest, direction: str) -> float:
    if direction == "ab":
        tx_site = request.site_a
    else:
        tx_site = request.site_b
    return (tx_site.tx_power_dbm or 18.0) + (tx_site.antenna_gain_dbi or 0.0)


def _request_radio_profile_params(request: WlrRequest) -> dict[str, Any]:
    profile = lookup_internal_radio_profile(
        radio_type=request.radio_type,
        radio_vendor=request.radio_vendor,
        freqs_ghz=(request.freq_ab_ghz, request.freq_ba_ghz),
        channel_width_mhz=request.channel_width_mhz,
    )
    return {
        "profile": profile,
        "noise_figure_db": (
            profile.rx_noise_figure_db
            if profile is not None and profile.rx_noise_figure_db is not None
            else DEFAULT_RECEIVER_NOISE_FIGURE_DB
        ),
        "atpc_db": (
            float(profile.atpc_attenuation_db or 0.0)
            if profile is not None and profile.atpc_attenuation_db is not None
            else 0.0
        ),
    }


def _wanted_signal_dbm(
    tx_eirp_dbm: float,
    tx_site: Any,
    rx_site: Any,
    freq_ghz: float,
    rx_antenna_gain_dbi: float,
    rx_attenuation_db: float,
) -> float:
    path_distance_km = max(_site_distance_km(tx_site, rx_site), 0.05)
    return (
        tx_eirp_dbm
        - fspl_db(path_distance_km, freq_ghz)
        - DEFAULT_MISC_LOSS_DB
        + rx_antenna_gain_dbi
        - rx_attenuation_db
    )


def _build_emc_input(
    direction: str,
    aggressor_eirp_dbm: float,
    aggressor_atpc_db: float,
    aggressor_freq_ghz: float,
    victim_wanted_eirp_dbm: float,
    victim_wanted_freq_ghz: float,
    victim_bw_mhz: float,
    victim_noise_figure_db: float,
    victim_rx_antenna_gain_dbi: float,
    victim_rx_attenuation_db: float,
    overlap_ratio: float,
    freq_delta_mhz: float,
    cross_pol_bonus_db: float,
    enable_mask_lookup: bool,
    aggressor_main_azimuth_deg: Optional[float],
    aggressor_main_elevation_deg: Optional[float],
    aggressor_interference_azimuth_deg: Optional[float],
    aggressor_interference_elevation_deg: Optional[float],
    victim_main_azimuth_deg: Optional[float],
    victim_main_elevation_deg: Optional[float],
    victim_interference_azimuth_deg: Optional[float],
    victim_interference_elevation_deg: Optional[float],
    aggressor_off_axis_deg: Optional[float],
    victim_off_axis_deg: Optional[float],
) -> EMCInput:
    return EMCInput(
        direction=direction,
        aggressor_eirp_dbm=aggressor_eirp_dbm,
        aggressor_atpc_db=aggressor_atpc_db,
        aggressor_freq_ghz=aggressor_freq_ghz,
        victim_wanted_eirp_dbm=victim_wanted_eirp_dbm,
        victim_wanted_freq_ghz=victim_wanted_freq_ghz,
        victim_bw_mhz=victim_bw_mhz,
        victim_noise_figure_db=victim_noise_figure_db,
        victim_rx_antenna_gain_dbi=victim_rx_antenna_gain_dbi,
        victim_rx_attenuation_db=victim_rx_attenuation_db,
        overlap_ratio=overlap_ratio,
        freq_delta_mhz=freq_delta_mhz,
        cross_pol_bonus_db=cross_pol_bonus_db,
        enable_mask_lookup=enable_mask_lookup,
        aggressor_main_azimuth_deg=aggressor_main_azimuth_deg,
        aggressor_main_elevation_deg=aggressor_main_elevation_deg,
        aggressor_interference_azimuth_deg=aggressor_interference_azimuth_deg,
        aggressor_interference_elevation_deg=aggressor_interference_elevation_deg,
        victim_main_azimuth_deg=victim_main_azimuth_deg,
        victim_main_elevation_deg=victim_main_elevation_deg,
        victim_interference_azimuth_deg=victim_interference_azimuth_deg,
        victim_interference_elevation_deg=victim_interference_elevation_deg,
        aggressor_off_axis_deg=aggressor_off_axis_deg,
        victim_off_axis_deg=victim_off_axis_deg,
    )


def _emc_margin_db(ci_db: float, degradation_db: float) -> float:
    # Positive margin means the pair still fits within ACCEPTED thresholds.
    degradation_margin_db = MAX_ACCEPTED_DEGRADATION_DB - degradation_db
    ci_margin_db = ci_db - MIN_ACCEPTED_CI_DB
    return min(degradation_margin_db, ci_margin_db)


def _emc_margin_at_thresholds(
    ci_db: float,
    degradation_db: float,
    ci_threshold_db: float,
    degradation_threshold_db: float,
) -> float:
    return min(degradation_threshold_db - degradation_db, ci_db - ci_threshold_db)


def _directional_interference_case(
    direction: str,
    aggressor_tx_site: Any,
    aggressor_intended_rx_site: Any,
    aggressor_eirp_dbm: float,
    aggressor_atpc_db: float,
    aggressor_freq_ghz: float,
    victim_rx_site: Any,
    victim_desired_tx_site: Any,
    victim_wanted_eirp_dbm: float,
    victim_wanted_freq_ghz: float,
    victim_bw_mhz: float,
    victim_noise_figure_db: float,
    victim_rx_antenna_gain_dbi: float,
    victim_rx_attenuation_db: float,
    overlap_ratio: float,
    freq_delta_mhz: float,
    cross_pol_bonus_db: float,
    enable_mask_lookup: bool = False,
) -> dict[str, Any]:
    endpoint_metrics = _endpoint_discrimination_metrics(
        aggressor_tx_site,
        aggressor_intended_rx_site,
        victim_rx_site,
        victim_desired_tx_site,
        tx_freq_ghz=aggressor_freq_ghz,
        victim_rx_freq_ghz=victim_wanted_freq_ghz,
    )
    emc_input = _build_emc_input(
        direction=direction,
        aggressor_eirp_dbm=aggressor_eirp_dbm,
        aggressor_atpc_db=aggressor_atpc_db,
        aggressor_freq_ghz=aggressor_freq_ghz,
        victim_wanted_eirp_dbm=victim_wanted_eirp_dbm,
        victim_wanted_freq_ghz=victim_wanted_freq_ghz,
        victim_bw_mhz=victim_bw_mhz,
        victim_noise_figure_db=victim_noise_figure_db,
        victim_rx_antenna_gain_dbi=victim_rx_antenna_gain_dbi,
        victim_rx_attenuation_db=victim_rx_attenuation_db,
        overlap_ratio=overlap_ratio,
        freq_delta_mhz=freq_delta_mhz,
        cross_pol_bonus_db=cross_pol_bonus_db,
        enable_mask_lookup=enable_mask_lookup,
        aggressor_main_azimuth_deg=endpoint_metrics["tx_main_azimuth_deg"],
        aggressor_main_elevation_deg=endpoint_metrics["tx_main_elevation_deg"],
        aggressor_interference_azimuth_deg=endpoint_metrics["tx_interference_azimuth_deg"],
        aggressor_interference_elevation_deg=endpoint_metrics["tx_interference_elevation_deg"],
        victim_main_azimuth_deg=endpoint_metrics["rx_main_azimuth_deg"],
        victim_main_elevation_deg=endpoint_metrics["rx_main_elevation_deg"],
        victim_interference_azimuth_deg=endpoint_metrics["rx_interference_azimuth_deg"],
        victim_interference_elevation_deg=endpoint_metrics["rx_interference_elevation_deg"],
        aggressor_off_axis_deg=endpoint_metrics["tx_off_axis_deg"],
        victim_off_axis_deg=endpoint_metrics["rx_off_axis_deg"],
    )
    coupling_distance_km = max(_site_distance_km(aggressor_tx_site, victim_rx_site), 0.05)
    path_loss_db = fspl_db(coupling_distance_km, min(victim_wanted_freq_ghz, aggressor_freq_ghz)) + DEFAULT_MISC_LOSS_DB
    endpoint_penalty_db = endpoint_metrics["total_penalty_db"]
    reference_bw_mhz = max(victim_bw_mhz, 0.001)
    filter_discrimination_db = _empirical_filter_discrimination_db(freq_delta_mhz, reference_bw_mhz, overlap_ratio)
    if enable_mask_lookup and overlap_ratio <= 0.0:
        mask_db = lookup_mask_discrimination_db(
            min(victim_wanted_freq_ghz, aggressor_freq_ghz),
            reference_bw_mhz,
            freq_delta_mhz,
        )
        if mask_db is not None:
            filter_discrimination_db = mask_db
    if overlap_ratio > 0.0:
        md_db = max(0.0, -10.0 * log10(max(overlap_ratio, 1e-6)))
        nfd_db = max(0.0, filter_discrimination_db - md_db)
    else:
        md_db = 0.0
        nfd_db = filter_discrimination_db
    interference_dbm = (
        aggressor_eirp_dbm
        - aggressor_atpc_db
        - path_loss_db
        + victim_rx_antenna_gain_dbi
        - victim_rx_attenuation_db
        - endpoint_penalty_db
        - cross_pol_bonus_db
        - md_db
        - nfd_db
    )
    wanted_signal_dbm = _wanted_signal_dbm(
        victim_wanted_eirp_dbm,
        victim_desired_tx_site,
        victim_rx_site,
        victim_wanted_freq_ghz,
        victim_rx_antenna_gain_dbi,
        victim_rx_attenuation_db,
    )
    noise_dbm = thermal_noise_dbm(victim_bw_mhz, victim_noise_figure_db)
    ci_db = wanted_signal_dbm - interference_dbm
    degradation_db = threshold_degradation_db(interference_dbm, noise_dbm)
    margin_db = _emc_margin_db(ci_db, degradation_db)
    return {
        "distance_km": coupling_distance_km,
        "endpoint_penalty_db": endpoint_penalty_db,
        "tx_main_azimuth_deg": endpoint_metrics["tx_main_azimuth_deg"],
        "tx_main_elevation_deg": endpoint_metrics["tx_main_elevation_deg"],
        "tx_interference_azimuth_deg": endpoint_metrics["tx_interference_azimuth_deg"],
        "tx_interference_elevation_deg": endpoint_metrics["tx_interference_elevation_deg"],
        "rx_main_azimuth_deg": endpoint_metrics["rx_main_azimuth_deg"],
        "rx_main_elevation_deg": endpoint_metrics["rx_main_elevation_deg"],
        "rx_interference_azimuth_deg": endpoint_metrics["rx_interference_azimuth_deg"],
        "rx_interference_elevation_deg": endpoint_metrics["rx_interference_elevation_deg"],
        "tx_off_axis_deg": endpoint_metrics["tx_off_axis_deg"],
        "rx_off_axis_deg": endpoint_metrics["rx_off_axis_deg"],
        "tx_penalty_db": endpoint_metrics["tx_penalty_db"],
        "rx_penalty_db": endpoint_metrics["rx_penalty_db"],
        "md_db": md_db,
        "nfd_db": nfd_db,
        "interference_dbm": interference_dbm,
        "wanted_signal_dbm": wanted_signal_dbm,
        "noise_dbm": noise_dbm,
        "ci_db": ci_db,
        "degradation_db": degradation_db,
        "margin_db": margin_db,
        "emc_input": emc_input,
    }


def _worse_case(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    if right["degradation_db"] > left["degradation_db"] + 1e-9:
        return right
    if left["degradation_db"] > right["degradation_db"] + 1e-9:
        return left
    if right["ci_db"] < left["ci_db"] - 1e-9:
        return right
    return left


def _recompute_case_with_extra_isolation(case_data: dict[str, Any], extra_isolation_db: float) -> dict[str, Any]:
    updated = dict(case_data)
    updated["interference_dbm"] = case_data["interference_dbm"] - extra_isolation_db
    updated["ci_db"] = case_data["wanted_signal_dbm"] - updated["interference_dbm"]
    updated["degradation_db"] = threshold_degradation_db(
        updated["interference_dbm"],
        case_data["noise_dbm"],
    )
    updated["margin_db"] = _emc_margin_db(updated["ci_db"], updated["degradation_db"])
    return updated


def _apply_shared_site_cross_isolation(
    relationship: str,
    case_data: dict[str, Any],
) -> dict[str, Any]:
    if relationship != "shared_site":
        return case_data
    emc_input = case_data.get("emc_input")
    if emc_input is None:
        return case_data
    if not emc_input.direction.endswith("_cross"):
        return case_data
    if emc_input.overlap_ratio > 0.0:
        return case_data
    if emc_input.freq_delta_mhz < SHARED_SITE_CROSS_MIN_DELTA_MHZ:
        return case_data
    return _recompute_case_with_extra_isolation(case_data, SHARED_SITE_CROSS_EXTRA_ISOLATION_DB)


def _apply_radio_specific_cross_hardening(
    relationship: str,
    case_data: dict[str, Any],
    link_radio_type: Optional[str],
) -> dict[str, Any]:
    if relationship != "shared_site":
        return case_data
    emc_input = case_data.get("emc_input")
    if emc_input is None:
        return case_data
    if not emc_input.direction.endswith("_cross"):
        return case_data
    if emc_input.overlap_ratio > 0.0:
        return case_data
    if emc_input.aggressor_atpc_db and emc_input.aggressor_atpc_db > 0.0:
        return case_data
    if emc_input.freq_delta_mhz < SHARED_SITE_CROSS_MIN_DELTA_MHZ:
        return case_data

    radio_type = (link_radio_type or "").lower()
    if "ipasolink ex 80" in radio_type:
        return _recompute_case_with_extra_isolation(case_data, -IPASOLINK_SHARED_SITE_CROSS_EXTRA_COUPLING_DB)
    return case_data


def _empirical_filter_discrimination_db(freq_delta_mhz: float, bw_mhz: float, overlap_ratio: float) -> float:
    if overlap_ratio >= 0.95 or freq_delta_mhz <= 1e-6:
        return 0.0

    ratio = freq_delta_mhz / max(bw_mhz, 0.001)
    if ratio <= 0.25:
        return 2.0
    if ratio <= 0.50:
        return 4.0
    if ratio <= 1.00:
        return 6.0
    if ratio <= 1.50:
        return 12.0
    if ratio <= 2.00:
        return 20.0
    return 20.0 + 20.0 * log10(max(ratio / 2.0, 1.0))


def estimate_interference_metrics(
    request: WlrRequest,
    candidate: ChannelCandidate,
    link: DuplexLink,
) -> dict[str, Any]:
    request_bw_mhz = request.channel_width_mhz or 1.0
    link_bw_mhz = link.emission_ab.channel_width_mhz or request_bw_mhz

    relationship = classify_relationship(request, link)

    overlap_ab_direct = spectral_overlap_ratio(candidate.freq_ab_ghz, request_bw_mhz, link.emission_ab.center_freq_ghz, link_bw_mhz)
    overlap_ba_direct = spectral_overlap_ratio(candidate.freq_ba_ghz, request_bw_mhz, link.emission_ba.center_freq_ghz, link_bw_mhz)
    overlap_ab_cross = spectral_overlap_ratio(candidate.freq_ab_ghz, request_bw_mhz, link.emission_ba.center_freq_ghz, link_bw_mhz)
    overlap_ba_cross = spectral_overlap_ratio(candidate.freq_ba_ghz, request_bw_mhz, link.emission_ab.center_freq_ghz, link_bw_mhz)
    overlap_ab = max(overlap_ab_direct, overlap_ab_cross)
    overlap_ba = max(overlap_ba_direct, overlap_ba_cross)
    max_overlap = max(overlap_ab, overlap_ba)

    freq_delta_ab = abs(candidate.freq_ab_ghz * 1000.0 - link.emission_ab.center_freq_mhz)
    freq_delta_ba = abs(candidate.freq_ba_ghz * 1000.0 - link.emission_ba.center_freq_mhz)
    freq_delta_cross_ab = abs(candidate.freq_ab_ghz * 1000.0 - link.emission_ba.center_freq_mhz)
    freq_delta_cross_ba = abs(candidate.freq_ba_ghz * 1000.0 - link.emission_ab.center_freq_mhz)
    min_freq_delta = min(freq_delta_ab, freq_delta_ba, freq_delta_cross_ab, freq_delta_cross_ba)

    same_polarization = (candidate.polarization or request.requested_polarization or "") == (link.polarization or "")
    cross_pol_bonus_db = 0.0 if same_polarization else DEFAULT_CROSS_POL_DISCRIMINATION_DB

    request_eirp_ab_dbm = _request_leg_eirp_dbm(request, "ab")
    request_eirp_ba_dbm = _request_leg_eirp_dbm(request, "ba")
    request_radio_params = _request_radio_profile_params(request)
    request_noise_figure_db = request_radio_params["noise_figure_db"]
    request_atpc_db = request_radio_params["atpc_db"] if APPLY_ATPC_TO_COORDINATION_AGGRESSOR else 0.0
    link_eirp_ab_dbm = link.emission_ab.eirp_dbm if link.emission_ab.eirp_dbm is not None else 40.0
    link_eirp_ba_dbm = link.emission_ba.eirp_dbm if link.emission_ba.eirp_dbm is not None else 40.0
    link_atpc_ab_db = link.emission_ab.atpc_attenuation_db if link.emission_ab.atpc_attenuation_db is not None else 0.0
    link_atpc_ba_db = link.emission_ba.atpc_attenuation_db if link.emission_ba.atpc_attenuation_db is not None else 0.0
    coordination_atpc_ab_db = link_atpc_ab_db if APPLY_ATPC_TO_COORDINATION_AGGRESSOR else 0.0
    coordination_atpc_ba_db = link_atpc_ba_db if APPLY_ATPC_TO_COORDINATION_AGGRESSOR else 0.0
    enable_mask_lookup_ab = ENABLE_MASK_LOOKUP and link_atpc_ab_db <= 0.0
    enable_mask_lookup_ba = ENABLE_MASK_LOOKUP and link_atpc_ba_db <= 0.0
    link_noise_ab_db = link.emission_ab.rx_noise_figure_db if link.emission_ab.rx_noise_figure_db is not None else DEFAULT_RECEIVER_NOISE_FIGURE_DB
    link_noise_ba_db = link.emission_ba.rx_noise_figure_db if link.emission_ba.rx_noise_figure_db is not None else DEFAULT_RECEIVER_NOISE_FIGURE_DB
    request_rx_gain_ab_dbi = request.site_b.antenna_gain_dbi or 0.0
    request_rx_gain_ba_dbi = request.site_a.antenna_gain_dbi or 0.0
    request_rx_attenuation_ab_db = 0.0
    request_rx_attenuation_ba_db = 0.0
    link_rx_gain_ab_dbi = link.site_b.antenna_gain_dbi or 0.0
    link_rx_gain_ba_dbi = link.site_a.antenna_gain_dbi or 0.0
    link_rx_attenuation_ab_db = link.emission_ab.rx_antenna_attenuation_db or 0.0
    link_rx_attenuation_ba_db = link.emission_ba.rx_antenna_attenuation_db or 0.0

    ab_incoming_direct = _directional_interference_case(
        direction="ab_incoming_direct",
        aggressor_tx_site=link.site_a,
        aggressor_intended_rx_site=link.site_b,
        aggressor_eirp_dbm=link_eirp_ab_dbm,
        aggressor_atpc_db=coordination_atpc_ab_db,
        aggressor_freq_ghz=link.emission_ab.center_freq_ghz,
        victim_rx_site=request.site_b,
        victim_desired_tx_site=request.site_a,
        victim_wanted_eirp_dbm=request_eirp_ab_dbm,
        victim_wanted_freq_ghz=candidate.freq_ab_ghz,
        victim_bw_mhz=request_bw_mhz,
        victim_noise_figure_db=request_noise_figure_db,
        victim_rx_antenna_gain_dbi=request_rx_gain_ab_dbi,
        victim_rx_attenuation_db=request_rx_attenuation_ab_db,
        overlap_ratio=overlap_ab_direct,
        freq_delta_mhz=freq_delta_ab,
        cross_pol_bonus_db=cross_pol_bonus_db,
        enable_mask_lookup=enable_mask_lookup_ab,
    )
    ab_incoming_cross = _directional_interference_case(
        direction="ab_incoming_cross",
        aggressor_tx_site=link.site_b,
        aggressor_intended_rx_site=link.site_a,
        aggressor_eirp_dbm=link_eirp_ba_dbm,
        aggressor_atpc_db=coordination_atpc_ba_db,
        aggressor_freq_ghz=link.emission_ba.center_freq_ghz,
        victim_rx_site=request.site_b,
        victim_desired_tx_site=request.site_a,
        victim_wanted_eirp_dbm=request_eirp_ab_dbm,
        victim_wanted_freq_ghz=candidate.freq_ab_ghz,
        victim_bw_mhz=request_bw_mhz,
        victim_noise_figure_db=request_noise_figure_db,
        victim_rx_antenna_gain_dbi=request_rx_gain_ab_dbi,
        victim_rx_attenuation_db=request_rx_attenuation_ab_db,
        overlap_ratio=overlap_ab_cross,
        freq_delta_mhz=freq_delta_cross_ab,
        cross_pol_bonus_db=cross_pol_bonus_db,
        enable_mask_lookup=enable_mask_lookup_ba,
    )
    ab_outgoing_direct = _directional_interference_case(
        direction="ab_outgoing_direct",
        aggressor_tx_site=request.site_a,
        aggressor_intended_rx_site=request.site_b,
        aggressor_eirp_dbm=request_eirp_ab_dbm,
        aggressor_atpc_db=request_atpc_db,
        aggressor_freq_ghz=candidate.freq_ab_ghz,
        victim_rx_site=link.site_b,
        victim_desired_tx_site=link.site_a,
        victim_wanted_eirp_dbm=link_eirp_ab_dbm,
        victim_wanted_freq_ghz=link.emission_ab.center_freq_ghz,
        victim_bw_mhz=link_bw_mhz,
        victim_noise_figure_db=link_noise_ab_db,
        victim_rx_antenna_gain_dbi=link_rx_gain_ab_dbi,
        victim_rx_attenuation_db=link_rx_attenuation_ab_db,
        overlap_ratio=overlap_ab_direct,
        freq_delta_mhz=freq_delta_ab,
        cross_pol_bonus_db=cross_pol_bonus_db,
        enable_mask_lookup=False,
    )
    ab_outgoing_cross = _directional_interference_case(
        direction="ab_outgoing_cross",
        aggressor_tx_site=request.site_a,
        aggressor_intended_rx_site=request.site_b,
        aggressor_eirp_dbm=request_eirp_ab_dbm,
        aggressor_atpc_db=request_atpc_db,
        aggressor_freq_ghz=candidate.freq_ab_ghz,
        victim_rx_site=link.site_a,
        victim_desired_tx_site=link.site_b,
        victim_wanted_eirp_dbm=link_eirp_ba_dbm,
        victim_wanted_freq_ghz=link.emission_ba.center_freq_ghz,
        victim_bw_mhz=link_bw_mhz,
        victim_noise_figure_db=link_noise_ba_db,
        victim_rx_antenna_gain_dbi=link_rx_gain_ba_dbi,
        victim_rx_attenuation_db=link_rx_attenuation_ba_db,
        overlap_ratio=overlap_ab_cross,
        freq_delta_mhz=freq_delta_cross_ab,
        cross_pol_bonus_db=cross_pol_bonus_db,
        enable_mask_lookup=False,
    )
    ba_incoming_direct = _directional_interference_case(
        direction="ba_incoming_direct",
        aggressor_tx_site=link.site_b,
        aggressor_intended_rx_site=link.site_a,
        aggressor_eirp_dbm=link_eirp_ba_dbm,
        aggressor_atpc_db=coordination_atpc_ba_db,
        aggressor_freq_ghz=link.emission_ba.center_freq_ghz,
        victim_rx_site=request.site_a,
        victim_desired_tx_site=request.site_b,
        victim_wanted_eirp_dbm=request_eirp_ba_dbm,
        victim_wanted_freq_ghz=candidate.freq_ba_ghz,
        victim_bw_mhz=request_bw_mhz,
        victim_noise_figure_db=request_noise_figure_db,
        victim_rx_antenna_gain_dbi=request_rx_gain_ba_dbi,
        victim_rx_attenuation_db=request_rx_attenuation_ba_db,
        overlap_ratio=overlap_ba_direct,
        freq_delta_mhz=freq_delta_ba,
        cross_pol_bonus_db=cross_pol_bonus_db,
        enable_mask_lookup=enable_mask_lookup_ba,
    )
    ba_incoming_cross = _directional_interference_case(
        direction="ba_incoming_cross",
        aggressor_tx_site=link.site_a,
        aggressor_intended_rx_site=link.site_b,
        aggressor_eirp_dbm=link_eirp_ab_dbm,
        aggressor_atpc_db=coordination_atpc_ab_db,
        aggressor_freq_ghz=link.emission_ab.center_freq_ghz,
        victim_rx_site=request.site_a,
        victim_desired_tx_site=request.site_b,
        victim_wanted_eirp_dbm=request_eirp_ba_dbm,
        victim_wanted_freq_ghz=candidate.freq_ba_ghz,
        victim_bw_mhz=request_bw_mhz,
        victim_noise_figure_db=request_noise_figure_db,
        victim_rx_antenna_gain_dbi=request_rx_gain_ba_dbi,
        victim_rx_attenuation_db=request_rx_attenuation_ba_db,
        overlap_ratio=overlap_ba_cross,
        freq_delta_mhz=freq_delta_cross_ba,
        cross_pol_bonus_db=cross_pol_bonus_db,
        enable_mask_lookup=enable_mask_lookup_ab,
    )
    ba_outgoing_direct = _directional_interference_case(
        direction="ba_outgoing_direct",
        aggressor_tx_site=request.site_b,
        aggressor_intended_rx_site=request.site_a,
        aggressor_eirp_dbm=request_eirp_ba_dbm,
        aggressor_atpc_db=request_atpc_db,
        aggressor_freq_ghz=candidate.freq_ba_ghz,
        victim_rx_site=link.site_a,
        victim_desired_tx_site=link.site_b,
        victim_wanted_eirp_dbm=link_eirp_ba_dbm,
        victim_wanted_freq_ghz=link.emission_ba.center_freq_ghz,
        victim_bw_mhz=link_bw_mhz,
        victim_noise_figure_db=link_noise_ba_db,
        victim_rx_antenna_gain_dbi=link_rx_gain_ba_dbi,
        victim_rx_attenuation_db=link_rx_attenuation_ba_db,
        overlap_ratio=overlap_ba_direct,
        freq_delta_mhz=freq_delta_ba,
        cross_pol_bonus_db=cross_pol_bonus_db,
        enable_mask_lookup=False,
    )
    ba_outgoing_cross = _directional_interference_case(
        direction="ba_outgoing_cross",
        aggressor_tx_site=request.site_b,
        aggressor_intended_rx_site=request.site_a,
        aggressor_eirp_dbm=request_eirp_ba_dbm,
        aggressor_atpc_db=request_atpc_db,
        aggressor_freq_ghz=candidate.freq_ba_ghz,
        victim_rx_site=link.site_b,
        victim_desired_tx_site=link.site_a,
        victim_wanted_eirp_dbm=link_eirp_ab_dbm,
        victim_wanted_freq_ghz=link.emission_ab.center_freq_ghz,
        victim_bw_mhz=link_bw_mhz,
        victim_noise_figure_db=link_noise_ab_db,
        victim_rx_antenna_gain_dbi=link_rx_gain_ab_dbi,
        victim_rx_attenuation_db=link_rx_attenuation_ab_db,
        overlap_ratio=overlap_ba_cross,
        freq_delta_mhz=freq_delta_cross_ba,
        cross_pol_bonus_db=cross_pol_bonus_db,
        enable_mask_lookup=False,
    )

    ab_incoming_cross = _apply_radio_specific_cross_hardening(relationship, ab_incoming_cross, link.emission_ba.radio_type)
    ab_outgoing_cross = _apply_radio_specific_cross_hardening(relationship, ab_outgoing_cross, link.emission_ba.radio_type)
    ba_incoming_cross = _apply_radio_specific_cross_hardening(relationship, ba_incoming_cross, link.emission_ab.radio_type)
    ba_outgoing_cross = _apply_radio_specific_cross_hardening(relationship, ba_outgoing_cross, link.emission_ab.radio_type)

    ab_incoming_case = _worse_case(ab_incoming_direct, ab_incoming_cross)
    ab_outgoing_case = _worse_case(ab_outgoing_direct, ab_outgoing_cross)
    ba_incoming_case = _worse_case(ba_incoming_direct, ba_incoming_cross)
    ba_outgoing_case = _worse_case(ba_outgoing_direct, ba_outgoing_cross)

    ab_incoming_case = _apply_shared_site_cross_isolation(relationship, ab_incoming_case)
    ab_outgoing_case = _apply_shared_site_cross_isolation(relationship, ab_outgoing_case)
    ba_incoming_case = _apply_shared_site_cross_isolation(relationship, ba_incoming_case)
    ba_outgoing_case = _apply_shared_site_cross_isolation(relationship, ba_outgoing_case)

    dominant_case = max(
        (ab_incoming_case, ab_outgoing_case, ba_incoming_case, ba_outgoing_case),
        key=lambda item: (item["degradation_db"], -item["ci_db"]),
    )

    md_db = min(
        ab_incoming_case["md_db"],
        ab_outgoing_case["md_db"],
        ba_incoming_case["md_db"],
        ba_outgoing_case["md_db"],
    )
    nfd_db = min(
        ab_incoming_case["nfd_db"],
        ab_outgoing_case["nfd_db"],
        ba_incoming_case["nfd_db"],
        ba_outgoing_case["nfd_db"],
    )
    interference_victim_dbm = max(ab_incoming_case["interference_dbm"], ba_incoming_case["interference_dbm"])
    interference_aggressor_dbm = max(ab_outgoing_case["interference_dbm"], ba_outgoing_case["interference_dbm"])
    noise_request_dbm = thermal_noise_dbm(request_bw_mhz, request_noise_figure_db)
    noise_existing_dbm = min(
        ab_outgoing_case["noise_dbm"],
        ba_outgoing_case["noise_dbm"],
    )
    ci_victim_db = min(ab_incoming_case["ci_db"], ba_incoming_case["ci_db"])
    ci_aggressor_db = min(ab_outgoing_case["ci_db"], ba_outgoing_case["ci_db"])
    degradation_victim_db = max(ab_incoming_case["degradation_db"], ba_incoming_case["degradation_db"])
    degradation_aggressor_db = max(ab_outgoing_case["degradation_db"], ba_outgoing_case["degradation_db"])
    degradation_ab_db = max(ab_incoming_case["degradation_db"], ab_outgoing_case["degradation_db"])
    degradation_ba_db = max(ba_incoming_case["degradation_db"], ba_outgoing_case["degradation_db"])
    ci_ab_db = min(ab_incoming_case["ci_db"], ab_outgoing_case["ci_db"])
    ci_ba_db = min(ba_incoming_case["ci_db"], ba_outgoing_case["ci_db"])
    margin_ab_db = min(ab_incoming_case["margin_db"], ab_outgoing_case["margin_db"])
    margin_ba_db = min(ba_incoming_case["margin_db"], ba_outgoing_case["margin_db"])
    spectral_coupling_db = -md_db

    return {
        "distance_km": dominant_case["distance_km"],
        "relationship": relationship,
        "freq_delta_ab_mhz": freq_delta_ab,
        "freq_delta_ba_mhz": freq_delta_ba,
        "freq_delta_cross_ab_mhz": freq_delta_cross_ab,
        "freq_delta_cross_ba_mhz": freq_delta_cross_ba,
        "effective_freq_delta_mhz": min_freq_delta,
        "overlap_ab_ratio": overlap_ab,
        "overlap_ba_ratio": overlap_ba,
        "overlap_ab_direct_ratio": overlap_ab_direct,
        "overlap_ba_direct_ratio": overlap_ba_direct,
        "overlap_ab_cross_ratio": overlap_ab_cross,
        "overlap_ba_cross_ratio": overlap_ba_cross,
        "same_polarization": same_polarization,
        "cross_pol_bonus_db": cross_pol_bonus_db,
        "off_axis_penalty_db": dominant_case["endpoint_penalty_db"],
        "tx_rx_directivity_penalty_db": dominant_case["endpoint_penalty_db"],
        "md_db": md_db,
        "nfd_db": nfd_db,
        "spectral_coupling_db": spectral_coupling_db,
        "request_noise_figure_db": request_noise_figure_db,
        "request_radio_type": request.radio_type,
        "request_radio_vendor": request.radio_vendor,
        "request_radio_profile_type": getattr(request_radio_params["profile"], "radio_type", None),
        "request_radio_profile_vendor": getattr(request_radio_params["profile"], "radio_vendor", None),
        "noise_request_dbm": noise_request_dbm,
        "noise_existing_dbm": noise_existing_dbm,
        "estimated_interference_victim_dbm": interference_victim_dbm,
        "estimated_interference_aggressor_dbm": interference_aggressor_dbm,
        "estimated_ci_victim_db": ci_victim_db,
        "estimated_ci_aggressor_db": ci_aggressor_db,
        "estimated_degradation_victim_db": degradation_victim_db,
        "estimated_degradation_aggressor_db": degradation_aggressor_db,
        "estimated_ci_ab_db": ci_ab_db,
        "estimated_ci_ba_db": ci_ba_db,
        "estimated_degradation_ab_db": degradation_ab_db,
        "estimated_degradation_ba_db": degradation_ba_db,
        "estimated_margin_ab_db": margin_ab_db,
        "estimated_margin_ba_db": margin_ba_db,
        "ab_incoming_direct": ab_incoming_direct,
        "ab_incoming_cross": ab_incoming_cross,
        "ab_outgoing_direct": ab_outgoing_direct,
        "ab_outgoing_cross": ab_outgoing_cross,
        "ba_incoming_direct": ba_incoming_direct,
        "ba_incoming_cross": ba_incoming_cross,
        "ba_outgoing_direct": ba_outgoing_direct,
        "ba_outgoing_cross": ba_outgoing_cross,
        "ab_incoming_case": ab_incoming_case,
        "ab_outgoing_case": ab_outgoing_case,
        "ba_incoming_case": ba_incoming_case,
        "ba_outgoing_case": ba_outgoing_case,
    }


def classify_conflict_type(overlap_ab: float, overlap_ba: float, min_freq_delta_mhz: float, bw_mhz: float) -> str:
    max_overlap = max(overlap_ab, overlap_ba)
    if max_overlap >= 0.95:
        return "cochannel"
    if max_overlap > 0.0 or min_freq_delta_mhz <= bw_mhz:
        return "adjacent"
    return "geometry"


def classify_risk(
    conflict_type: str,
    overlap_ab_ratio: float,
    overlap_ba_ratio: float,
    estimated_ci_victim_db: float,
    estimated_ci_aggressor_db: float,
    estimated_degradation_victim_db: float,
    estimated_degradation_aggressor_db: float,
) -> str:
    max_overlap = max(overlap_ab_ratio, overlap_ba_ratio)
    worst_ci = min(estimated_ci_victim_db, estimated_ci_aggressor_db)
    worst_degradation = max(estimated_degradation_victim_db, estimated_degradation_aggressor_db)

    if conflict_type == "geometry" and max_overlap <= 0.0:
        return "green"

    if worst_degradation > MAX_ACCEPTED_DEGRADATION_DB:
        return "red"
    if max_overlap > 0.0 and worst_ci < MIN_HARD_BLOCKING_CI_DB:
        return "red"

    if conflict_type == "cochannel" and max_overlap >= 0.95 and worst_ci < MIN_ACCEPTED_CI_DB:
        return "amber"
    if conflict_type == "adjacent" and (worst_ci < MIN_ACCEPTED_CI_DB or worst_degradation > 0.25):
        return "amber"
    if worst_degradation > 0.25 or (max_overlap > 0.0 and worst_ci < MIN_ACCEPTED_CI_DB):
        return "amber"

    return "green"


def is_blocking_conflict(conflict: ConflictAssessment) -> bool:
    max_overlap = max(conflict.overlap_ab_ratio or 0.0, conflict.overlap_ba_ratio or 0.0)
    worst_margin = min(
        conflict.estimated_margin_ab_db if conflict.estimated_margin_ab_db is not None else 999.0,
        conflict.estimated_margin_ba_db if conflict.estimated_margin_ba_db is not None else 999.0,
    )
    worst_degradation = max(
        conflict.estimated_degradation_victim_db or 0.0,
        conflict.estimated_degradation_aggressor_db or 0.0,
    )
    worst_ci = min(
        conflict.estimated_ci_victim_db if conflict.estimated_ci_victim_db is not None else 999.0,
        conflict.estimated_ci_aggressor_db if conflict.estimated_ci_aggressor_db is not None else 999.0,
    )

    if max_overlap <= 0.0 and conflict.conflict_type == "geometry":
        return False
    if max_overlap <= 0.0 and worst_degradation <= MAX_ACCEPTED_DEGRADATION_DB:
        return False
    if worst_margin < 0.0:
        return True
    if worst_degradation > MAX_ACCEPTED_DEGRADATION_DB:
        return True
    if max_overlap > 0.0 and worst_ci < MIN_HARD_BLOCKING_CI_DB:
        return True
    return False


def count_cochannel_conflicts(conflicts: list[ConflictAssessment]) -> int:
    return sum(1 for conflict in conflicts if conflict.conflict_type == "cochannel")


def worst_blocking_degradation(conflicts: list[ConflictAssessment]) -> float:
    blocking = [conflict for conflict in conflicts if is_blocking_conflict(conflict)]
    if not blocking:
        return 0.0
    return max(
        max(conflict.estimated_degradation_victim_db or 0.0, conflict.estimated_degradation_aggressor_db or 0.0)
        for conflict in blocking
    )


def worst_blocking_ci(conflicts: list[ConflictAssessment]) -> float:
    blocking = [conflict for conflict in conflicts if is_blocking_conflict(conflict)]
    if not blocking:
        return 999.0
    return min(
        min(conflict.estimated_ci_victim_db or 999.0, conflict.estimated_ci_aggressor_db or 999.0)
        for conflict in blocking
    )


def worst_blocking_margin(conflicts: list[ConflictAssessment]) -> float:
    blocking = [conflict for conflict in conflicts if is_blocking_conflict(conflict)]
    if not blocking:
        return 999.0
    return min(
        min(
            conflict.estimated_margin_ab_db if conflict.estimated_margin_ab_db is not None else 999.0,
            conflict.estimated_margin_ba_db if conflict.estimated_margin_ba_db is not None else 999.0,
        )
        for conflict in blocking
    )


def _channel_index_value(channel_number: str) -> int:
    digits = "".join(ch for ch in channel_number if ch.isdigit())
    return int(digits) if digits else 0



def requested_channel_distance(request: WlrRequest, candidate: ChannelCandidate) -> int:
    requested_values: list[int] = []
    if request.channel_ab:
        requested_values.append(_channel_index_value(request.channel_ab))
    if request.channel_ba:
        requested_values.append(_channel_index_value(request.channel_ba))

    if not requested_values:
        return 0

    candidate_values = [_channel_index_value(candidate.channel_ab), _channel_index_value(candidate.channel_ba)]
    return min(abs(req - cand) for req in requested_values for cand in candidate_values)



def polarization_preference_penalty(request: WlrRequest, candidate: ChannelCandidate) -> int:
    if not request.requested_polarization:
        return 0
    return 0 if candidate.polarization == request.requested_polarization else 1


def _is_prime_channel(channel_number: Optional[str]) -> Optional[bool]:
    if not channel_number:
        return None
    text = channel_number.strip()
    if not text:
        return None
    return ("'" in text) or ("’" in text) or ("′" in text)


def orientation_preference_penalty(request: WlrRequest, candidate: ChannelCandidate) -> int:
    req_ab_prime = _is_prime_channel(request.channel_ab)
    req_ba_prime = _is_prime_channel(request.channel_ba)
    cand_ab_prime = _is_prime_channel(candidate.channel_ab)
    cand_ba_prime = _is_prime_channel(candidate.channel_ba)

    if req_ab_prime is not None and req_ba_prime is not None and req_ab_prime != req_ba_prime:
        if cand_ab_prime is not None and cand_ba_prime is not None and cand_ab_prime != cand_ba_prime:
            return 0 if cand_ab_prime == req_ab_prime else 1

    if request.freq_ab_ghz is not None and request.freq_ba_ghz is not None:
        req_ab_is_lower = request.freq_ab_ghz < request.freq_ba_ghz
        cand_ab_is_lower = candidate.freq_ab_ghz < candidate.freq_ba_ghz
        return 0 if req_ab_is_lower == cand_ab_is_lower else 1

    return 0


def should_prioritize_requested_orientation(request: WlrRequest, assessments: list[ChannelAssessment]) -> bool:
    for assessment in assessments:
        if orientation_preference_penalty(request, assessment.candidate) != 0:
            continue
        if assessment.status != "REJECTED":
            return True
    return False


def determine_channel_status(conflicts: list[ConflictAssessment]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not conflicts:
        return "ACCEPTED", reasons

    blocking_conflicts = [conflict for conflict in conflicts if is_blocking_conflict(conflict)]
    if not blocking_conflicts:
        return "ACCEPTED", []

    worst_degradation_victim = max(conflict.estimated_degradation_victim_db or 0.0 for conflict in blocking_conflicts)
    worst_degradation_aggressor = max(conflict.estimated_degradation_aggressor_db or 0.0 for conflict in blocking_conflicts)
    worst_ci_victim = min(conflict.estimated_ci_victim_db or 999.0 for conflict in blocking_conflicts)
    worst_ci_aggressor = min(conflict.estimated_ci_aggressor_db or 999.0 for conflict in blocking_conflicts)
    worst_margin_ab = min(conflict.estimated_margin_ab_db if conflict.estimated_margin_ab_db is not None else 999.0 for conflict in blocking_conflicts)
    worst_margin_ba = min(conflict.estimated_margin_ba_db if conflict.estimated_margin_ba_db is not None else 999.0 for conflict in blocking_conflicts)
    cochannel_conflicts = [conflict for conflict in blocking_conflicts if conflict.conflict_type == "cochannel"]
    adjacent_conflicts = [conflict for conflict in blocking_conflicts if conflict.conflict_type == "adjacent"]
    red_conflicts = [conflict for conflict in blocking_conflicts if conflict.risk_level == "red"]
    amber_conflicts = [conflict for conflict in blocking_conflicts if conflict.risk_level == "amber"]

    if worst_margin_ab < 0.0 or worst_margin_ba < 0.0:
        reasons.append(
            f"ujemny margines EMC: A→B={worst_margin_ab:.2f} dB, B→A={worst_margin_ba:.2f} dB"
        )
    if red_conflicts:
        reasons.append(f"{len(red_conflicts)} konflikt(y) RED w oknie kanałowym")
    if cochannel_conflicts:
        reasons.append(f"{len(cochannel_conflicts)} konflikt(y) współkanałowych")
    elif adjacent_conflicts:
        reasons.append(f"{len(adjacent_conflicts)} konflikt(y) sąsiedniokanałowych")

    if not reasons:
        return "ACCEPTED", []

    conditional_reasons: list[str] = []
    conditional_margin_ab = min(
        _emc_margin_at_thresholds(
            conflict.estimated_ci_ab_db if conflict.details.get("estimated_ci_ab_db") is not None else (conflict.estimated_ci_victim_db or 999.0),
            conflict.details.get("estimated_degradation_ab_db", conflict.estimated_degradation_victim_db or 0.0),
            MIN_CONDITIONAL_CI_DB,
            MAX_CONDITIONAL_DEGRADATION_DB,
        )
        for conflict in blocking_conflicts
    )
    conditional_margin_ba = min(
        _emc_margin_at_thresholds(
            conflict.details.get("estimated_ci_ba_db", conflict.estimated_ci_aggressor_db or 999.0),
            conflict.details.get("estimated_degradation_ba_db", conflict.estimated_degradation_aggressor_db or 0.0),
            MIN_CONDITIONAL_CI_DB,
            MAX_CONDITIONAL_DEGRADATION_DB,
        )
        for conflict in blocking_conflicts
    )

    if worst_degradation_victim <= MAX_CONDITIONAL_DEGRADATION_DB and worst_degradation_aggressor <= MAX_CONDITIONAL_DEGRADATION_DB:
        conditional_reasons.append(
            f"degradacja w zakresie warunkowym <= {MAX_CONDITIONAL_DEGRADATION_DB:.1f} dB"
        )
    if worst_ci_victim >= MIN_CONDITIONAL_CI_DB and worst_ci_aggressor >= MIN_CONDITIONAL_CI_DB:
        conditional_reasons.append(
            f"CI w zakresie warunkowym >= {MIN_CONDITIONAL_CI_DB:.1f} dB"
        )
    if len(red_conflicts) == 0 and (amber_conflicts or cochannel_conflicts or adjacent_conflicts):
        conditional_reasons.append("brak konfliktów RED w oknie kanałowym")

    if conditional_margin_ab >= 0.0 and conditional_margin_ba >= 0.0:
        conditional_reasons.append(
            f"margines warunkowy dodatni: A→B={conditional_margin_ab:.2f} dB, B→A={conditional_margin_ba:.2f} dB"
        )

    if conditional_reasons:
        return "CONDITIONAL", reasons

    return "REJECTED", reasons


def _directional_overlap(conflict: ConflictAssessment, direction: str) -> float:
    return conflict.overlap_ab_ratio if direction == "ab" else conflict.overlap_ba_ratio


def _directional_ci(conflict: ConflictAssessment, direction: str) -> float:
    details_value = conflict.details.get(f"estimated_ci_{direction}_db")
    if details_value is not None:
        return details_value
    value = conflict.estimated_ci_victim_db if direction == "ab" else conflict.estimated_ci_aggressor_db
    return 999.0 if value is None else value


def _directional_degradation(conflict: ConflictAssessment, direction: str) -> float:
    details_value = conflict.details.get(f"estimated_degradation_{direction}_db")
    if details_value is not None:
        return details_value
    value = conflict.estimated_degradation_victim_db if direction == "ab" else conflict.estimated_degradation_aggressor_db
    return 0.0 if value is None else value


def _directional_margin(conflict: ConflictAssessment, direction: str) -> float:
    details_value = conflict.details.get(f"estimated_margin_{direction}_db")
    if details_value is not None:
        return details_value
    value = conflict.estimated_margin_ab_db if direction == "ab" else conflict.estimated_margin_ba_db
    return 999.0 if value is None else value


def _directional_total_degradation(conflicts: list[ConflictAssessment], direction: str) -> float:
    ratios_sum = 0.0
    for conflict in conflicts:
        if _directional_overlap(conflict, direction) <= 0.0 and conflict.conflict_type == "geometry":
            continue
        degradation = _directional_degradation(conflict, direction)
        ratios_sum += max(0.0, 10.0 ** (degradation / 10.0) - 1.0)
    return 10.0 * log10(1.0 + ratios_sum) if ratios_sum > 0.0 else 0.0


def _directional_is_blocking(conflict: ConflictAssessment, direction: str) -> bool:
    overlap = _directional_overlap(conflict, direction)
    margin = _directional_margin(conflict, direction)
    degradation = _directional_degradation(conflict, direction)
    ci = _directional_ci(conflict, direction)

    if overlap <= 0.0 and conflict.conflict_type == "geometry":
        return False
    if overlap <= 0.0 and degradation <= MAX_ACCEPTED_DEGRADATION_DB:
        return False
    if margin < 0.0:
        return True
    if degradation > MAX_ACCEPTED_DEGRADATION_DB:
        return True
    if overlap > 0.0 and ci < MIN_HARD_BLOCKING_CI_DB:
        return True
    return False


def _is_eband_request(request: WlrRequest) -> bool:
    freqs = [freq for freq in (request.freq_ab_ghz, request.freq_ba_ghz) if freq is not None]
    return bool(freqs and min(freqs) >= EBAND_FULL_WINDOW_GHZ)


def _directional_dense_eband_counts(
    request: WlrRequest,
    conflicts: list[ConflictAssessment],
) -> tuple[int, int]:
    if not _is_eband_request(request):
        return 0, 0

    request_bw_mhz = request.channel_width_mhz or 1.0
    close_count = 0
    very_close_count = 0
    for conflict in conflicts:
        effective_delta = conflict.effective_freq_delta_mhz
        distance = conflict.distance_km
        if effective_delta is None or distance is None:
            continue
        if effective_delta > request_bw_mhz * EBAND_DENSE_DELTA_FACTOR:
            continue
        if distance <= EBAND_DENSE_NEAR_KM:
            close_count += 1
        if distance <= EBAND_DENSE_VERY_NEAR_KM:
            very_close_count += 1
    return close_count, very_close_count


def determine_directional_status(
    request: WlrRequest,
    conflicts: list[ConflictAssessment],
    direction: str,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    total_degradation = _directional_total_degradation(conflicts, direction)
    directional_conflicts = [conflict for conflict in conflicts if _directional_is_blocking(conflict, direction)]
    dense_close_count, dense_very_close_count = _directional_dense_eband_counts(request, conflicts)
    if (
        not directional_conflicts
        and total_degradation <= MAX_ACCEPTED_DEGRADATION_DB
    ):
        return "ACCEPTED", []

    worst_degradation = max((_directional_degradation(conflict, direction) for conflict in directional_conflicts), default=0.0)
    worst_ci = min((_directional_ci(conflict, direction) for conflict in directional_conflicts), default=999.0)
    worst_margin = min((_directional_margin(conflict, direction) for conflict in directional_conflicts), default=999.0)
    red_conflicts = [conflict for conflict in directional_conflicts if conflict.risk_level == "red"]
    cochannel_conflicts = [conflict for conflict in directional_conflicts if conflict.conflict_type == "cochannel"]
    adjacent_conflicts = [conflict for conflict in directional_conflicts if conflict.conflict_type == "adjacent"]

    if worst_margin < 0.0:
        reasons.append(
            f"ujemny margines EMC {direction.upper()} ({worst_margin:.2f} dB)"
        )
    if total_degradation > MAX_ACCEPTED_DEGRADATION_DB:
        reasons.append(
            f"degradacja skumulowana {direction.upper()} > {MAX_ACCEPTED_DEGRADATION_DB:.1f} dB ({total_degradation:.2f})"
        )
    if worst_degradation > MAX_ACCEPTED_DEGRADATION_DB:
        reasons.append(f"degradacja {direction.upper()} > {MAX_ACCEPTED_DEGRADATION_DB:.1f} dB ({worst_degradation:.2f})")
    if worst_ci < MIN_HARD_BLOCKING_CI_DB:
        reasons.append(f"CI {direction.upper()} poniżej progu krytycznego ({MIN_HARD_BLOCKING_CI_DB:.1f} dB): {worst_ci:.1f}")
    if red_conflicts:
        reasons.append(f"{len(red_conflicts)} konflikt(y) RED dla {direction.upper()}")
    if cochannel_conflicts:
        reasons.append(f"{len(cochannel_conflicts)} konflikt(y) współkanałowych dla {direction.upper()}")
    elif adjacent_conflicts:
        reasons.append(f"{len(adjacent_conflicts)} konflikt(y) sąsiedniokanałowych dla {direction.upper()}")
    if directional_conflicts and dense_close_count >= EBAND_DENSE_CONDITIONAL_COUNT:
        reasons.append(
            f"gęste środowisko E-band dla {direction.upper()}: {dense_close_count} bliskich linków <= {EBAND_DENSE_NEAR_KM:.1f} km i deltaf <= {((request.channel_width_mhz or 1.0) * EBAND_DENSE_DELTA_FACTOR):.1f} MHz"
        )
    if directional_conflicts and dense_very_close_count >= 1:
        reasons.append(
            f"bardzo bliskie linki E-band dla {direction.upper()}: {dense_very_close_count} <= {EBAND_DENSE_VERY_NEAR_KM:.1f} km"
        )

    conditional_margin = min(
        (
            _emc_margin_at_thresholds(
                _directional_ci(conflict, direction),
                _directional_degradation(conflict, direction),
                MIN_CONDITIONAL_CI_DB,
                MAX_CONDITIONAL_DEGRADATION_DB,
            )
            for conflict in directional_conflicts
        ),
        default=999.0,
    )

    if directional_conflicts and (dense_close_count >= EBAND_DENSE_REJECT_COUNT or dense_very_close_count >= 2):
        return "REJECTED", reasons
    if conditional_margin >= 0.0 and total_degradation <= MAX_CONDITIONAL_DEGRADATION_DB and worst_ci >= MIN_HARD_BLOCKING_CI_DB:
        return "CONDITIONAL", reasons
    return "REJECTED", reasons


def build_explanation(
    link: DuplexLink,
    conflict_type: str,
    same_operator: bool,
    relationship: str,
    shared_sites: int,
    metrics: dict[str, Any],
) -> str:
    operator_text = "ten sam operator" if same_operator else "inny operator"
    return (
        f"{conflict_type}; operator={link.operator_name or '-'}; {operator_text}; "
        f"rel={relationship}; shared_sites={shared_sites}; "
        f"dist={metrics['distance_km']:.2f} km; "
        f"ov_ab={metrics['overlap_ab_ratio']:.2f}; ov_ba={metrics['overlap_ba_ratio']:.2f}; "
        f"CI_ab={metrics['estimated_ci_ab_db']:.1f} dB; "
        f"CI_ba={metrics['estimated_ci_ba_db']:.1f} dB; "
        f"M_ab={metrics['estimated_margin_ab_db']:.2f} dB; "
        f"M_ba={metrics['estimated_margin_ba_db']:.2f} dB; "
        f"TD_ab={metrics['estimated_degradation_ab_db']:.2f} dB; "
        f"TD_ba={metrics['estimated_degradation_ba_db']:.2f} dB"
    )


def _site_station_label(site: Any) -> str:
    parts = [
        getattr(site, "city", None),
        getattr(site, "street", None),
        getattr(site, "location_description", None),
    ]
    return " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())


def evaluate_pair_conflict(
    request: WlrRequest,
    candidate: ChannelCandidate,
    existing_link: DuplexLink,
    request_operator_name: str = DEFAULT_REQUEST_OPERATOR,
) -> ConflictAssessment:
    metrics = estimate_interference_metrics(request, candidate, existing_link)
    relationship = classify_relationship(request, existing_link)
    shared_sites = shared_site_count(request, existing_link)
    same_span = relationship == "same_span"
    min_freq_delta_mhz = metrics["effective_freq_delta_mhz"]
    conflict_type = classify_conflict_type(
        metrics["overlap_ab_ratio"],
        metrics["overlap_ba_ratio"],
        min_freq_delta_mhz,
        request.channel_width_mhz or 1.0,
    )

    same_operator = (existing_link.operator_name or "").strip().lower() == request_operator_name.strip().lower()

    max_overlap = max(metrics["overlap_ab_ratio"], metrics["overlap_ba_ratio"])
    worst_ci = min(metrics["estimated_ci_ab_db"], metrics["estimated_ci_ba_db"])
    worst_degradation = max(metrics["estimated_degradation_ab_db"], metrics["estimated_degradation_ba_db"])

    overlap_penalty = 25.0 * max_overlap
    ci_deficit_penalty = max(0.0, MIN_ACCEPTED_CI_DB - worst_ci) * 6.0
    degradation_penalty = worst_degradation * 60.0
    distance_penalty = max(0.0, 5.0 - metrics["distance_km"]) * 2.0 if max_overlap > 0.0 else 0.0
    angle_penalty = max(0.0, 18.0 - metrics["off_axis_penalty_db"]) * 1.2 if max_overlap > 0.0 else 0.0
    shared_site_penalty = 8.0 * shared_sites if max_overlap > 0.0 else 0.0
    same_operator_adjustment = -10.0 if same_operator else 0.0
    same_span_penalty = -250.0 if same_span else 0.0

    score = max(
        0.0,
        overlap_penalty + ci_deficit_penalty + degradation_penalty + distance_penalty + angle_penalty + shared_site_penalty + same_operator_adjustment + same_span_penalty,
    )
    risk_level = classify_risk(
        conflict_type,
        metrics["overlap_ab_ratio"],
        metrics["overlap_ba_ratio"],
        metrics["estimated_ci_ab_db"],
        metrics["estimated_ci_ba_db"],
        metrics["estimated_degradation_ab_db"],
        metrics["estimated_degradation_ba_db"],
    )

    explanation = build_explanation(existing_link, conflict_type, same_operator, relationship, shared_sites, metrics)

    return ConflictAssessment(
        link_id=existing_link.link_id,
        operator_name=existing_link.operator_name,
        permit_number=existing_link.permit_number,
        same_operator=same_operator,
        conflict_type=conflict_type,
        role="mutual",
        score=score,
        risk_level=risk_level,
        distance_km=metrics["distance_km"],
        freq_delta_ab_mhz=metrics["freq_delta_ab_mhz"],
        freq_delta_ba_mhz=metrics["freq_delta_ba_mhz"],
        freq_delta_cross_ab_mhz=metrics["freq_delta_cross_ab_mhz"],
        freq_delta_cross_ba_mhz=metrics["freq_delta_cross_ba_mhz"],
        effective_freq_delta_mhz=metrics["effective_freq_delta_mhz"],
        overlap_ab_ratio=metrics["overlap_ab_ratio"],
        overlap_ba_ratio=metrics["overlap_ba_ratio"],
        estimated_interference_victim_dbm=metrics["estimated_interference_victim_dbm"],
        estimated_interference_aggressor_dbm=metrics["estimated_interference_aggressor_dbm"],
        estimated_ci_victim_db=metrics["estimated_ci_victim_db"],
        estimated_ci_aggressor_db=metrics["estimated_ci_aggressor_db"],
        estimated_degradation_victim_db=metrics["estimated_degradation_victim_db"],
        estimated_degradation_aggressor_db=metrics["estimated_degradation_aggressor_db"],
        estimated_margin_ab_db=metrics["estimated_margin_ab_db"],
        estimated_margin_ba_db=metrics["estimated_margin_ba_db"],
        decision_explanation=explanation,
        relationship=relationship,
        shared_site_count=shared_sites,
        same_span=same_span,
        details={
            "plan_symbol": existing_link.plan_symbol,
            "polarization": existing_link.polarization,
            "site_a_station_label": _site_station_label(existing_link.site_a),
            "site_b_station_label": _site_station_label(existing_link.site_b),
            "candidate_channel_ab": candidate.channel_ab,
            "candidate_channel_ba": candidate.channel_ba,
            "relationship": relationship,
            "shared_site_count": shared_sites,
            "same_span": same_span,
            "freq_delta_cross_ab_mhz": metrics["freq_delta_cross_ab_mhz"],
            "freq_delta_cross_ba_mhz": metrics["freq_delta_cross_ba_mhz"],
            "effective_freq_delta_mhz": metrics["effective_freq_delta_mhz"],
            "off_axis_penalty_db": metrics["off_axis_penalty_db"],
            "tx_rx_directivity_penalty_db": metrics["tx_rx_directivity_penalty_db"],
            "md_db": metrics["md_db"],
            "nfd_db": metrics["nfd_db"],
            "spectral_coupling_db": metrics["spectral_coupling_db"],
            "noise_request_dbm": metrics["noise_request_dbm"],
            "noise_existing_dbm": metrics["noise_existing_dbm"],
            "estimated_ci_ab_db": metrics["estimated_ci_ab_db"],
            "estimated_ci_ba_db": metrics["estimated_ci_ba_db"],
            "estimated_degradation_ab_db": metrics["estimated_degradation_ab_db"],
            "estimated_degradation_ba_db": metrics["estimated_degradation_ba_db"],
            "estimated_margin_ab_db": metrics["estimated_margin_ab_db"],
            "estimated_margin_ba_db": metrics["estimated_margin_ba_db"],
            "ab_incoming_direct": metrics["ab_incoming_direct"],
            "ab_incoming_cross": metrics["ab_incoming_cross"],
            "ab_outgoing_direct": metrics["ab_outgoing_direct"],
            "ab_outgoing_cross": metrics["ab_outgoing_cross"],
            "ba_incoming_direct": metrics["ba_incoming_direct"],
            "ba_incoming_cross": metrics["ba_incoming_cross"],
            "ba_outgoing_direct": metrics["ba_outgoing_direct"],
            "ba_outgoing_cross": metrics["ba_outgoing_cross"],
            "ab_incoming_case": metrics["ab_incoming_case"],
            "ab_outgoing_case": metrics["ab_outgoing_case"],
            "ba_incoming_case": metrics["ba_incoming_case"],
            "ba_outgoing_case": metrics["ba_outgoing_case"],
        },
    )


def should_ignore_conflict_for_consultation(conflict: ConflictAssessment) -> bool:
    if not ENABLE_CONSULTATION_FILTER:
        return False
    if not conflict.same_operator:
        return False
    return conflict.relationship in {"same_span", "same_span_like"}


def assess_channel_candidate(
    request: WlrRequest,
    candidate: ChannelCandidate,
    existing_links: list[DuplexLink],
    request_operator_name: str = DEFAULT_REQUEST_OPERATOR,
) -> ChannelAssessment:
    filtered_links = [
        link for link in existing_links
        if candidate_matches_frequency_window(request, candidate, link)
    ]

    conflicts = [
        evaluate_pair_conflict(request, candidate, link, request_operator_name=request_operator_name)
        for link in filtered_links
    ]
    ignored_conflicts = [conflict for conflict in conflicts if should_ignore_conflict_for_consultation(conflict)]
    effective_conflicts = [conflict for conflict in conflicts if not should_ignore_conflict_for_consultation(conflict)]
    effective_conflicts.sort(key=lambda item: item.score, reverse=True)

    blocking_conflicts = [conflict for conflict in effective_conflicts if is_blocking_conflict(conflict)]
    score_source = blocking_conflicts if blocking_conflicts else effective_conflicts
    sorted_scores = sorted((conflict.score for conflict in score_source), reverse=True)
    total_score = sum(sorted_scores[:3]) + 0.15 * sum(sorted_scores[3:])
    red_conflicts = sum(1 for conflict in effective_conflicts if conflict.risk_level == "red")
    amber_conflicts = sum(1 for conflict in effective_conflicts if conflict.risk_level == "amber")
    green_conflicts = sum(1 for conflict in effective_conflicts if conflict.risk_level == "green")

    status_ab, reasons_ab = determine_directional_status(request, effective_conflicts, "ab")
    status_ba, reasons_ba = determine_directional_status(request, effective_conflicts, "ba")

    if status_ab == "ACCEPTED" and status_ba == "ACCEPTED":
        status = "ACCEPTED"
        rejection_reasons: list[str] = []
    elif status_ab == "REJECTED" and status_ba == "REJECTED":
        status = "REJECTED"
        rejection_reasons = reasons_ab[:2] + reasons_ba[:2]
    else:
        status = "CONDITIONAL"
        rejection_reasons = reasons_ab[:2] + reasons_ba[:2]

    deduped_reasons: list[str] = []
    for reason in rejection_reasons:
        if reason not in deduped_reasons:
            deduped_reasons.append(reason)
    rejection_reasons = deduped_reasons

    requested_distance = requested_channel_distance(request, candidate)

    if status == "ACCEPTED":
        best_explanation = "Kanał czysty w analizowanym planie i oknie częstotliwościowym"
    elif effective_conflicts:
        prefix = f"dist_req={requested_distance}; " if requested_distance else ""
        best_explanation = prefix + f"A→B={status_ab}, B→A={status_ba}; " + "; ".join(rejection_reasons[:4])
    else:
        best_explanation = "Brak konfliktów w oknie częstotliwościowym"
        if ignored_conflicts:
            best_explanation = f"Brak blokujących konfliktów po filtrze konsultacyjnym ({len(ignored_conflicts)} pominiętych)"

    return ChannelAssessment(
        candidate=candidate,
        status=status,
        score=total_score,
        red_conflicts=red_conflicts,
        amber_conflicts=amber_conflicts,
        green_conflicts=green_conflicts,
        candidate_links_count=len(filtered_links),
        best_explanation=best_explanation,
        rejection_reasons=rejection_reasons,
        conflicts=effective_conflicts,
        status_ab=status_ab,
        status_ba=status_ba,
        reasons_ab=reasons_ab,
        reasons_ba=reasons_ba,
        ignored_conflicts=ignored_conflicts,
    )


def analyze_wlr_request(
    request: WlrRequest,
    request_operator_name: str = DEFAULT_REQUEST_OPERATOR,
    radius_km: float = DEFAULT_RADIUS_KM,
    max_links: int = DEFAULT_MAX_LINKS,
) -> AnalysisResult:
    plan = find_matching_plan(request)
    if plan is None:
        raise ValueError("Nie znaleziono planu częstotliwości dla zapytania WLR")

    hcm_radius_km = hcm_fixed_service_coordination_distance_km(request) if ENABLE_ANNEX11_SEARCH_EXPANSION else None
    effective_radius_km = max(radius_km, hcm_radius_km or radius_km)
    low_freq = min(freq for freq in (request.freq_ab_ghz, request.freq_ba_ghz) if freq is not None) if (request.freq_ab_ghz or request.freq_ba_ghz) else None
    is_eband_or_higher = bool(low_freq is not None and low_freq >= 30.0)
    apply_corridor_filter = (not is_eband_or_higher) and (
        not ENABLE_ANNEX11_SEARCH_EXPANSION or effective_radius_km <= (radius_km + 1e-6)
    )
    preselector_max_links = max_links
    # For E-band on the internal UKE catalog we keep the full spatial pool and
    # let the cheap per-candidate frequency screen do the heavy pruning.
    if internal_catalog_available() and low_freq is not None and low_freq >= EBAND_FULL_WINDOW_GHZ:
        preselector_max_links = DEFAULT_INTERNAL_EBAND_MAX_LINKS

    bbox, candidate_links = select_candidate_links(
        request,
        plan,
        request_operator_name=request_operator_name,
        radius_km=effective_radius_km,
        max_links=preselector_max_links,
        apply_corridor_filter=apply_corridor_filter,
    )

    channel_candidates = generate_channel_candidates(request, plan)
    assessments = [
        assess_channel_candidate(request, candidate, candidate_links, request_operator_name=request_operator_name)
        for candidate in channel_candidates
    ]

    accepted_assessments = [item for item in assessments if item.status == "ACCEPTED"]
    conditional_assessments = [item for item in assessments if item.status == "CONDITIONAL"]
    rejected_assessments = [item for item in assessments if item.status == "REJECTED"]
    prioritize_orientation = should_prioritize_requested_orientation(request, assessments)
    candidate_frequency_records = build_candidate_frequency_records(request, assessments)
    assessment_by_key = {
        (item.candidate.channel_ab, item.candidate.channel_ba, item.candidate.polarization): item
        for item in assessments
    }
    candidate_frequency_records.sort(
        key=lambda record: _candidate_record_sort_key(request, record, prioritize_orientation)
    )
    ordered_assessments = [
        assessment_by_key[(record.channel_ab, record.channel_ba, record.polarization)]
        for record in candidate_frequency_records
    ]
    accepted_assessments = [item for item in ordered_assessments if item.status == "ACCEPTED"]
    conditional_assessments = [item for item in ordered_assessments if item.status == "CONDITIONAL"]
    rejected_assessments = [item for item in ordered_assessments if item.status == "REJECTED"]

    return AnalysisResult(
        request_operator_name=request_operator_name,
        bbox=bbox,
        candidate_links=candidate_links,
        channel_candidates=channel_candidates,
        candidate_frequency_records=candidate_frequency_records,
        accepted_assessments=accepted_assessments,
        conditional_assessments=conditional_assessments,
        rejected_assessments=rejected_assessments,
        channel_assessments=ordered_assessments,
    )
