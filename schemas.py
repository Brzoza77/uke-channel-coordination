from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    app: str = "uke-channel-coordination"
    engine_version: Optional[str] = None


class SourceSummaryResponse(BaseModel):
    engine_version: str
    source_kind: Literal["sqlite"]
    plan_source_kind: Optional[str] = None
    filename: str
    full_path: str
    rows_count: int
    sheet_name: str
    file_size_bytes: int
    modified_at: str
    duplex_links: int
    paired_records_count: int
    orphan_records_count: int
    plans_count: int
    plan_files_count: int


class WlrEndpointModel(BaseModel):
    name: Optional[str] = None
    lat_deg: float
    lon_deg: float
    terrain_m_asl: Optional[float] = None
    antenna_height_m_agl: Optional[float] = None
    tx_power_dbm: Optional[float] = None
    antenna_gain_dbi: Optional[float] = None
    antenna_type: Optional[str] = None
    polarization_preferred: Optional[str] = None


class UploadWlrSummaryResponse(BaseModel):
    upload_id: str
    original_filename: str
    stored_filename: str
    stored_path: str
    content_type: Optional[str] = None
    size_bytes: int
    uploaded_at: str
    parsed: bool = False
    request_summary: Optional[dict[str, Any]] = None


class MapFeatureProperties(BaseModel):
    feature_type: str
    label: Optional[str] = None
    operator_name: Optional[str] = None
    permit_number: Optional[str] = None
    plan_symbol: Optional[str] = None
    polarization: Optional[str] = None
    score: Optional[float] = None
    risk_level: Optional[Literal["green", "amber", "red"]] = None
    details: dict[str, Any] = Field(default_factory=dict)


class MapFeatureGeometry(BaseModel):
    type: Literal["Point", "LineString", "Polygon"]
    coordinates: Any


class MapFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: MapFeatureGeometry
    properties: MapFeatureProperties


class MapFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[MapFeature] = Field(default_factory=list)


class ConflictItem(BaseModel):
    link_id: str
    operator_name: Optional[str] = None
    permit_number: Optional[str] = None
    same_operator: bool = False
    conflict_type: Literal["cochannel", "adjacent", "geometry", "unknown"]
    role: Literal["victim", "aggressor", "mutual", "unknown"] = "unknown"
    score: float = 0.0
    risk_level: Literal["green", "amber", "red"] = "amber"
    distance_km: Optional[float] = None
    freq_delta_ab_mhz: Optional[float] = None
    freq_delta_ba_mhz: Optional[float] = None
    overlap_ab_ratio: Optional[float] = None
    overlap_ba_ratio: Optional[float] = None
    channel_ab: Optional[str] = None
    channel_ba: Optional[str] = None
    polarization: Optional[str] = None
    estimated_interference_victim_dbm: Optional[float] = None
    estimated_interference_aggressor_dbm: Optional[float] = None
    estimated_ci_victim_db: Optional[float] = None
    estimated_ci_aggressor_db: Optional[float] = None
    estimated_degradation_victim_db: Optional[float] = None
    estimated_degradation_aggressor_db: Optional[float] = None
    decision_explanation: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


class ChannelRecommendation(BaseModel):
    rank: int
    channel_ab: str
    channel_ba: str
    polarization: Literal["H", "V"]
    score: float
    status: Optional[str] = None
    red_conflicts: int = 0
    amber_conflicts: int = 0
    green_conflicts: int = 0
    candidate_links_count: int = 0
    summary: Optional[str] = None
    best_explanation: Optional[str] = None
    rejection_reasons: list[str] = Field(default_factory=list)
    top_conflicts: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    upload_id: str
    radius_km: float = 30.0
    max_links: int = 500
    operator_name: str = "Towerlink Poland Sp. z o.o."
    preferred_polarization: Optional[Literal["H", "V"]] = None
    preferred_plan_symbol: Optional[str] = None


class AnalyzeRequestSummary(BaseModel):
    upload_id: str
    link_name: Optional[str] = None
    plan_symbol: Optional[str] = None
    channel_width_mhz: Optional[float] = None
    requested_channel: Optional[str] = None
    requested_polarization: Optional[str] = None
    site_a: Optional[WlrEndpointModel] = None
    site_b: Optional[WlrEndpointModel] = None
    details: dict[str, Any] = Field(default_factory=dict)


class AnalyzeMapSection(BaseModel):
    bbox: Optional[list[float]] = None
    features: MapFeatureCollection = Field(default_factory=MapFeatureCollection)


class AnalyzeSummary(BaseModel):
    request_operator_name: Optional[str] = None
    candidate_links_count: int = 0
    channels_evaluated: int = 0
    accepted_count: int = 0
    conditional_count: int = 0
    rejected_count: int = 0
    has_accepted: bool = False
    best_channel_ab: Optional[str] = None
    best_channel_ba: Optional[str] = None
    best_polarization: Optional[str] = None
    best_score: Optional[float] = None


class ChannelInterferenceBar(BaseModel):
    label: str
    channel_ab: str
    channel_ba: str
    polarization: Literal["H", "V"]
    status: str
    gate_status: Optional[str] = None
    requested: bool = False
    recommended: bool = False
    td_max_db: float = 0.0
    td_max_ab_db: float = 0.0
    td_max_ba_db: float = 0.0
    over_threshold_pair_count: int = 0
    pairwise_results_count: int = 0
    red_pair_count: int = 0
    blocking_pair_count: int = 0


class ChannelInterferenceChart(BaseModel):
    threshold_db: float = 1.0
    max_td_db: float = 0.0
    items: list[ChannelInterferenceBar] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    request: AnalyzeRequestSummary
    map: AnalyzeMapSection
    summary: AnalyzeSummary
    channel_chart: ChannelInterferenceChart = Field(default_factory=ChannelInterferenceChart)
    recommendations: list[ChannelRecommendation] = Field(default_factory=list)
    conflicts: list[ConflictItem] = Field(default_factory=list)
    debug: dict[str, Any] = Field(default_factory=dict)
