from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
import json
import re
import threading
import time
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from schemas import (
    AnalyzeRequest,
    AnalyzeRequestSummary,
    AnalyzeResponse,
    AnalyzeSummary,
    ChannelInterferenceBar,
    ChannelInterferenceChart,
    ChannelRecommendation,
    ConflictItem,
    HealthResponse,
    LinkBudgetPlan,
    MapFeatureCollection,
    SourceSummaryResponse,
    UploadWlrSummaryResponse,
)
from simple_pdf import A4, HexColor, SimplePdfCanvas, WHITE, mm
from wlr import (
    WlrParseError,
    build_wlr_request_summary,
    parse_uploaded_wlr,
    parse_wlr_file,
)
from uke import get_pairing_summary, get_plan_summary, get_source_summary

from analysis import (
    ENGINE_VERSION,
    analyze_wlr_request,
    build_uke_like_directional_candidate_rows,
    fspl_db,
    haversine_km,
)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = BASE_DIR / "uploads" / "wlr"
REPORTS_DIR = BASE_DIR / "reports"
LOGS_DIR = BASE_DIR / "logs"
ANALYSIS_RUN_LOG = LOGS_DIR / "wlr_analysis_runs.jsonl"
INDEX_FILE = BASE_DIR / "index.html"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

ANALYSIS_LOG_LOCK = threading.Lock()

WORKING_ATPC_ENABLED = True
WORKING_KO_RX_TARGET_DBM = -36.0
WORKING_ATPC_RX_MAX_SET_DBM = -35.0
WORKING_ATPC_RX_MIN_DBM = -40.0
WORKING_MIN_TX_FLOOR_DBM = -5.0
WORKING_RX_OVERDRIVE_WARNING_DBM = -25.0
WORKING_MAX_TX_FALLBACK_DBM = 18.0
WORKING_EBAND_GAIN_FALLBACK_DBI = 50.5
WORKING_MIN_GAIN_FALLBACK_THRESHOLD_DBI = 10.0
WORKING_TX_CHAIN_LOSS_DB = 0.0
WORKING_RX_CHAIN_LOSS_DB = 0.0
WORKING_PLANNED_MODULATION_FALLBACK = "64QAM"
WORKING_LOWEST_MODULATION = "4QAM"
ATOLL_ANNUAL_OUTAGE_FIT_A = -0.3478162981646218
ATOLL_ANNUAL_OUTAGE_FIT_B = -0.036797469416063024
ATOLL_SENSITIVITY_DBM = {
    "HALFBPSKS": -80.5,
    "HALFBPSK": -78.5,
    "BPSK": -75.5,
    "4QAM": -73.0,
    "16QAMS": -69.5,
    "16QAM": -67.0,
    "32QAM": -64.0,
    "64QAM": -61.0,
    "128QAM": -58.0,
    "256QAM": -55.0,
    "512QAM": -51.0,
    "1024QAM": -48.0,
}


app = FastAPI(title="UKE Channel Coordination", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=404, detail="Brak pliku index.html")
    return FileResponse(str(INDEX_FILE))


@app.get("/api/health", response_model=HealthResponse)
def api_health() -> HealthResponse:
    return HealthResponse(engine_version=ENGINE_VERSION)


@app.get("/api/source", response_model=SourceSummaryResponse)
def api_source() -> SourceSummaryResponse:
    source = get_source_summary()
    pairing = get_pairing_summary()
    plans = get_plan_summary()

    return SourceSummaryResponse(
        engine_version=ENGINE_VERSION,
        source_kind=source["source_kind"],
        plan_source_kind=plans.get("primary_source_format"),
        antenna_catalog_present=source.get("antenna_catalog_present", False),
        antenna_catalog_path=source.get("antenna_catalog_path"),
        filename=source["filename"],
        full_path=source["full_path"],
        rows_count=source["rows_count"],
        sheet_name=source["sheet_name"],
        file_size_bytes=source["file_size_bytes"],
        modified_at=source["modified_at"],
        duplex_links=pairing["duplex_links"],
        paired_records_count=pairing["paired_records_count"],
        orphan_records_count=pairing["orphan_records_count"],
        plans_count=plans["plans_count"],
        plan_files_count=plans["loaded_files_count"],
    )


@app.post("/api/upload-wlr", response_model=UploadWlrSummaryResponse)
async def api_upload_wlr(file: UploadFile = File(...)) -> UploadWlrSummaryResponse:
    original_filename = file.filename or "upload.wlr"
    suffix = Path(original_filename).suffix.lower()
    if suffix != ".wlr":
        raise HTTPException(status_code=400, detail="Dozwolony jest wyłącznie plik .wlr")

    upload_id = uuid4().hex
    stored_filename = f"{upload_id}_{Path(original_filename).name}"
    stored_path = UPLOADS_DIR / stored_filename

    size_bytes = 0
    try:
        with stored_path.open("wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size_bytes += len(chunk)
                fh.write(chunk)
    except Exception as exc:
        if stored_path.exists():
            stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Nie udało się zapisać pliku WLR: {exc}") from exc
    finally:
        await file.close()

    uploaded_at = datetime.now().isoformat(timespec="seconds")
    try:
        parsed_request = parse_wlr_file(stored_path)
        request_summary = build_wlr_request_summary(parsed_request, upload_id=upload_id)
        parsed_ok = True
    except WlrParseError as exc:
        request_summary = {
            "upload_id": upload_id,
            "details": {
                "source_filename": original_filename,
                "source_path": str(stored_path),
                "parse_error": str(exc),
            },
        }
        parsed_ok = False
    except Exception as exc:
        request_summary = {
            "upload_id": upload_id,
            "details": {
                "source_filename": original_filename,
                "source_path": str(stored_path),
                "parse_error": f"Nieoczekiwany błąd parsera WLR: {exc}",
            },
        }
        parsed_ok = False

    return UploadWlrSummaryResponse(
        upload_id=upload_id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        stored_path=str(stored_path),
        content_type=file.content_type,
        size_bytes=size_bytes,
        uploaded_at=uploaded_at,
        parsed=parsed_ok,
        request_summary=request_summary,
    )


def _build_analyze_request_summary(payload: dict) -> AnalyzeRequestSummary:
    return AnalyzeRequestSummary(**payload)


def _normalize_modulation_label(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]+", "", value.upper())
    return normalized or None


def _estimate_clear_air_specific_loss_db_per_km(freq_ghz: float) -> float:
    if freq_ghz >= 70.0:
        return max(0.25, min(0.40, 0.184 + 0.00172 * freq_ghz))
    if freq_ghz >= 30.0:
        return 0.03
    if freq_ghz >= 10.0:
        return 0.01
    return 0.0


def _clear_sky_path_loss_db(distance_km: float, freq_ghz: float) -> float:
    return fspl_db(distance_km, freq_ghz) + _estimate_clear_air_specific_loss_db_per_km(freq_ghz) * distance_km


def _working_gain_dbi(endpoint, *, max_freq_ghz: float) -> float:
    gain = getattr(endpoint, "antenna_gain_dbi", None)
    if gain is not None and (max_freq_ghz < 70.0 or gain >= WORKING_MIN_GAIN_FALLBACK_THRESHOLD_DBI):
        return float(gain)
    if max_freq_ghz >= 70.0:
        return WORKING_EBAND_GAIN_FALLBACK_DBI
    return float(gain or 0.0)


def _annual_outage_pct_from_margin(margin_db: float) -> float:
    outage_pct = 10 ** (ATOLL_ANNUAL_OUTAGE_FIT_A + ATOLL_ANNUAL_OUTAGE_FIT_B * margin_db)
    return max(0.0001, min(99.0, outage_pct))


def _build_link_budget_plan(parsed_request, record) -> LinkBudgetPlan | None:
    if record is None:
        return None

    path_length_km = parsed_request.path_length_km
    if path_length_km is None:
        path_length_km = haversine_km(
            parsed_request.site_a.lat_deg,
            parsed_request.site_a.lon_deg,
            parsed_request.site_b.lat_deg,
            parsed_request.site_b.lon_deg,
        )

    max_freq_ghz = max(record.freq_ab_ghz, record.freq_ba_ghz)
    tx_gain_a_dbi = _working_gain_dbi(parsed_request.site_a, max_freq_ghz=max_freq_ghz)
    tx_gain_b_dbi = _working_gain_dbi(parsed_request.site_b, max_freq_ghz=max_freq_ghz)

    configured_tx_values = [
        float(value)
        for value in (parsed_request.site_a.tx_power_dbm, parsed_request.site_b.tx_power_dbm)
        if value is not None
    ]
    configured_tx_dbm = max(configured_tx_values) if configured_tx_values else None
    max_tx_power_dbm = max([WORKING_MAX_TX_FALLBACK_DBM, *configured_tx_values])

    configured_modulation_key = _normalize_modulation_label(parsed_request.modulation)
    modulation_key = WORKING_PLANNED_MODULATION_FALLBACK
    lowest_modulation_key = WORKING_LOWEST_MODULATION

    planned_sensitivity_dbm = ATOLL_SENSITIVITY_DBM[modulation_key]
    lowest_sensitivity_dbm = ATOLL_SENSITIVITY_DBM[lowest_modulation_key]

    clear_loss_ab_db = _clear_sky_path_loss_db(path_length_km, record.freq_ab_ghz)
    clear_loss_ba_db = _clear_sky_path_loss_db(path_length_km, record.freq_ba_ghz)

    ko_tx_ab_dbm = (
        WORKING_KO_RX_TARGET_DBM
        + clear_loss_ab_db
        + WORKING_TX_CHAIN_LOSS_DB
        + WORKING_RX_CHAIN_LOSS_DB
        - tx_gain_a_dbi
        - tx_gain_b_dbi
    )
    ko_tx_ba_dbm = (
        WORKING_KO_RX_TARGET_DBM
        + clear_loss_ba_db
        + WORKING_TX_CHAIN_LOSS_DB
        + WORKING_RX_CHAIN_LOSS_DB
        - tx_gain_b_dbi
        - tx_gain_a_dbi
    )
    set_tx_ab_dbm = (
        WORKING_ATPC_RX_MIN_DBM
        + clear_loss_ab_db
        + WORKING_TX_CHAIN_LOSS_DB
        + WORKING_RX_CHAIN_LOSS_DB
        - tx_gain_a_dbi
        - tx_gain_b_dbi
    )
    set_tx_ba_dbm = (
        WORKING_ATPC_RX_MIN_DBM
        + clear_loss_ba_db
        + WORKING_TX_CHAIN_LOSS_DB
        + WORKING_RX_CHAIN_LOSS_DB
        - tx_gain_b_dbi
        - tx_gain_a_dbi
    )

    ko_tx_power_dbm = max(ko_tx_ab_dbm, ko_tx_ba_dbm)
    min_tx_power_dbm = max(set_tx_ab_dbm, set_tx_ba_dbm)

    ko_tx_power_dbm = max(WORKING_MIN_TX_FLOOR_DBM, min(max_tx_power_dbm, ko_tx_power_dbm))
    min_tx_power_dbm = max(WORKING_MIN_TX_FLOOR_DBM, min(max_tx_power_dbm, min_tx_power_dbm))

    rsl_ab_at_min_tx_dbm = (
        min_tx_power_dbm
        + tx_gain_a_dbi
        + tx_gain_b_dbi
        - clear_loss_ab_db
        - WORKING_TX_CHAIN_LOSS_DB
        - WORKING_RX_CHAIN_LOSS_DB
    )
    rsl_ba_at_min_tx_dbm = (
        min_tx_power_dbm
        + tx_gain_b_dbi
        + tx_gain_a_dbi
        - clear_loss_ba_db
        - WORKING_TX_CHAIN_LOSS_DB
        - WORKING_RX_CHAIN_LOSS_DB
    )
    rsl_ab_at_ko_tx_dbm = (
        ko_tx_power_dbm
        + tx_gain_a_dbi
        + tx_gain_b_dbi
        - clear_loss_ab_db
        - WORKING_TX_CHAIN_LOSS_DB
        - WORKING_RX_CHAIN_LOSS_DB
    )
    rsl_ba_at_ko_tx_dbm = (
        ko_tx_power_dbm
        + tx_gain_b_dbi
        + tx_gain_a_dbi
        - clear_loss_ba_db
        - WORKING_TX_CHAIN_LOSS_DB
        - WORKING_RX_CHAIN_LOSS_DB
    )

    rsl_ab_at_max_tx_dbm = (
        max_tx_power_dbm
        + tx_gain_a_dbi
        + tx_gain_b_dbi
        - clear_loss_ab_db
        - WORKING_TX_CHAIN_LOSS_DB
        - WORKING_RX_CHAIN_LOSS_DB
    )
    rsl_ba_at_max_tx_dbm = (
        max_tx_power_dbm
        + tx_gain_b_dbi
        + tx_gain_a_dbi
        - clear_loss_ba_db
        - WORKING_TX_CHAIN_LOSS_DB
        - WORKING_RX_CHAIN_LOSS_DB
    )
    worst_rsl_at_max_tx_dbm = min(rsl_ab_at_max_tx_dbm, rsl_ba_at_max_tx_dbm)

    planned_margin_db = worst_rsl_at_max_tx_dbm - planned_sensitivity_dbm
    lowest_margin_db = worst_rsl_at_max_tx_dbm - lowest_sensitivity_dbm

    planned_annual_outage_pct = _annual_outage_pct_from_margin(planned_margin_db)
    annual_outage_pct = _annual_outage_pct_from_margin(lowest_margin_db)
    minutes_per_year = 365.0 * 24.0 * 60.0

    assumptions = [
        "KO RX target fixed at -36 dBm",
        "ATPC expected RX window fixed at -35 to -40 dBm",
        f"KO planned modulation fixed to {WORKING_PLANNED_MODULATION_FALLBACK}",
        "Availability metrics assume ATPC can ramp up to Max TX before declaring outage",
        "Global outage counted at max TX and lowest modulation 4QAM/QPSK",
        "Sensitivity table calibrated from supplied Atoll report (BER 1e-06)",
        "Clear-sky atmospheric loss approximated from Atoll E-band reference (FSPL + gas/water vapour specific loss)",
        "If WLR antenna gain is missing or implausibly low in E-band, fallback gain 50.5 dBi is used",
    ]
    if configured_modulation_key and configured_modulation_key != modulation_key:
        assumptions.append(
            f"WLR modulation {configured_modulation_key} ignored for KO; fixed planned modulation {modulation_key} used instead"
        )
    if configured_tx_dbm is not None:
        assumptions.append(
            f"Configured WLR TX found: {configured_tx_dbm:.1f} dBm; planning cap uses {max_tx_power_dbm:.1f} dBm "
            f"until radio max from UKE/vendor is confirmed"
        )
    else:
        assumptions.append(f"No explicit WLR max TX found, fallback cap {WORKING_MAX_TX_FALLBACK_DBM:.1f} dBm used")

    warnings: list[str] = []
    worst_min_rsl_dbm = min(rsl_ab_at_min_tx_dbm, rsl_ba_at_min_tx_dbm)
    worst_ko_rsl_dbm = min(rsl_ab_at_ko_tx_dbm, rsl_ba_at_ko_tx_dbm)
    best_min_rsl_dbm = max(rsl_ab_at_min_tx_dbm, rsl_ba_at_min_tx_dbm)
    best_ko_rsl_dbm = max(rsl_ab_at_ko_tx_dbm, rsl_ba_at_ko_tx_dbm)
    best_max_rsl_dbm = max(rsl_ab_at_max_tx_dbm, rsl_ba_at_max_tx_dbm)

    if best_min_rsl_dbm > WORKING_RX_OVERDRIVE_WARNING_DBM:
        warnings.append(
            f"Przy minimalnej mocy TX {min_tx_power_dbm:.1f} dBm poziom RX moze przekroczyc {WORKING_RX_OVERDRIVE_WARNING_DBM:.0f} dBm "
            f"(najwyzej {best_min_rsl_dbm:.1f} dBm)."
        )
    if best_min_rsl_dbm > WORKING_ATPC_RX_MAX_SET_DBM:
        warnings.append(
            f"Przy minimalnej mocy TX {min_tx_power_dbm:.1f} dBm gorna granica okna ATPC {WORKING_ATPC_RX_MAX_SET_DBM:.0f} dBm moze byc przekroczona "
            f"(najwyzej {best_min_rsl_dbm:.1f} dBm)."
        )
    if best_ko_rsl_dbm > WORKING_RX_OVERDRIVE_WARNING_DBM:
        warnings.append(
            f"Przy KO TX {ko_tx_power_dbm:.1f} dBm poziom RX moze przekroczyc {WORKING_RX_OVERDRIVE_WARNING_DBM:.0f} dBm "
            f"(najwyzej {best_ko_rsl_dbm:.1f} dBm)."
        )
    if best_max_rsl_dbm > WORKING_RX_OVERDRIVE_WARNING_DBM:
        warnings.append(
            f"Przy Max TX {max_tx_power_dbm:.1f} dBm poziom RX moze przekroczyc {WORKING_RX_OVERDRIVE_WARNING_DBM:.0f} dBm "
            f"(najwyzej {best_max_rsl_dbm:.1f} dBm)."
        )
    if planned_margin_db < 0.0:
        warnings.append(
            f"Docelowa modulacja {modulation_key} ma ujemny margines {planned_margin_db:.1f} dB nawet przy Max TX {max_tx_power_dbm:.1f} dBm."
        )
    if lowest_margin_db < 0.0:
        warnings.append(
            f"Nawet najnizsza modulacja {lowest_modulation_key} ma ujemny margines {lowest_margin_db:.1f} dB; global outage bedzie wysoki."
        )
    if ko_tx_power_dbm == WORKING_MIN_TX_FLOOR_DBM and worst_ko_rsl_dbm > WORKING_KO_RX_TARGET_DBM:
        warnings.append(
            f"Cel KO RX {WORKING_KO_RX_TARGET_DBM:.0f} dBm nie jest osiagalny bez zejscia ponizej minimalnej mocy TX {WORKING_MIN_TX_FLOOR_DBM:.0f} dBm."
        )

    return LinkBudgetPlan(
        channel_label=f"{record.channel_ab}/{record.channel_ba} {record.polarization}",
        channel_ab=record.channel_ab,
        channel_ba=record.channel_ba,
        polarization=record.polarization,
        status=record.status,
        gate_status=record.access_fkand_gate_status,
        path_length_km=round(path_length_km, 3),
        planned_modulation=modulation_key,
        lowest_modulation=lowest_modulation_key,
        atpc_enabled=WORKING_ATPC_ENABLED,
        min_tx_power_dbm=round(min_tx_power_dbm),
        set_rx_power_dbm=round(WORKING_ATPC_RX_MAX_SET_DBM),
        min_rx_power_dbm=round(WORKING_ATPC_RX_MIN_DBM),
        ko_tx_power_dbm=round(ko_tx_power_dbm),
        ko_rx_power_dbm=round(WORKING_KO_RX_TARGET_DBM),
        max_tx_power_dbm=round(max_tx_power_dbm),
        planned_margin_db=round(planned_margin_db, 1),
        planned_annual_reliability_pct=round(100.0 - planned_annual_outage_pct, 2),
        planned_annual_outage_min=round(planned_annual_outage_pct / 100.0 * minutes_per_year, 1),
        annual_uninterruptibility_pct=round(100.0 - annual_outage_pct, 2),
        annual_outage_min=round(annual_outage_pct / 100.0 * minutes_per_year, 1),
        warnings=warnings,
        assumptions=assumptions,
    )


def _append_analysis_run_log(entry: dict) -> None:
    with ANALYSIS_LOG_LOCK:
        with ANALYSIS_RUN_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _build_analysis_run_entry(
    *,
    trigger: str,
    request: AnalyzeRequest,
    started_at: datetime,
    duration_ms: float,
    status: str,
    parsed_request=None,
    response: AnalyzeResponse | None = None,
    error_detail: str | None = None,
) -> dict:
    entry = {
        "trigger": trigger,
        "status": status,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "duration_ms": round(duration_ms, 2),
        "upload_id": request.upload_id,
        "operator_name": request.operator_name,
        "radius_km": request.radius_km,
        "max_links": request.max_links,
        "preferred_polarization": request.preferred_polarization,
        "preferred_plan_symbol": request.preferred_plan_symbol,
    }

    if parsed_request is not None:
        entry.update(
            {
                "link_name": getattr(parsed_request, "link_name", None),
                "plan_symbol": getattr(parsed_request, "plan_symbol", None),
                "requested_channel_ab": getattr(parsed_request, "channel_ab", None),
                "requested_channel_ba": getattr(parsed_request, "channel_ba", None),
                "requested_polarization": getattr(parsed_request, "requested_polarization", None),
            }
        )

    if response is not None:
        entry.update(
            {
                "summary": {
                    "candidate_links_count": response.summary.candidate_links_count,
                    "channels_evaluated": response.summary.channels_evaluated,
                    "accepted_count": response.summary.accepted_count,
                    "conditional_count": response.summary.conditional_count,
                    "rejected_count": response.summary.rejected_count,
                    "has_accepted": response.summary.has_accepted,
                    "best_channel_ab": response.summary.best_channel_ab,
                    "best_channel_ba": response.summary.best_channel_ba,
                    "best_polarization": response.summary.best_polarization,
                    "best_score": response.summary.best_score,
                }
            }
        )

    if error_detail:
        entry["error"] = error_detail

    return entry


async def _run_analysis(request: AnalyzeRequest, *, trigger: str) -> tuple[AnalyzeResponse, object]:
    started_at = datetime.now()
    started_perf = time.perf_counter()
    parsed_request = None
    try:
        parsed_request = await run_in_threadpool(parse_uploaded_wlr, request.upload_id, UPLOADS_DIR)
    except FileNotFoundError as exc:
        _append_analysis_run_log(
            _build_analysis_run_entry(
                trigger=trigger,
                request=request,
                started_at=started_at,
                duration_ms=(time.perf_counter() - started_perf) * 1000.0,
                status="error",
                error_detail=str(exc),
            )
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WlrParseError as exc:
        _append_analysis_run_log(
            _build_analysis_run_entry(
                trigger=trigger,
                request=request,
                started_at=started_at,
                duration_ms=(time.perf_counter() - started_perf) * 1000.0,
                status="error",
                error_detail=f"Nie udało się sparsować WLR: {exc}",
            )
        )
        raise HTTPException(status_code=400, detail=f"Nie udało się sparsować WLR: {exc}") from exc
    except Exception as exc:
        _append_analysis_run_log(
            _build_analysis_run_entry(
                trigger=trigger,
                request=request,
                started_at=started_at,
                duration_ms=(time.perf_counter() - started_perf) * 1000.0,
                status="error",
                error_detail=f"Błąd odczytu WLR: {exc}",
            )
        )
        raise HTTPException(status_code=500, detail=f"Błąd odczytu WLR: {exc}") from exc

    try:
        analysis = await run_in_threadpool(
            analyze_wlr_request,
            parsed_request,
            request.operator_name,
            request.radius_km,
            request.max_links,
        )
    except Exception as exc:
        _append_analysis_run_log(
            _build_analysis_run_entry(
                trigger=trigger,
                request=request,
                started_at=started_at,
                duration_ms=(time.perf_counter() - started_perf) * 1000.0,
                status="error",
                parsed_request=parsed_request,
                error_detail=f"Błąd analizy WLR: {exc}",
            )
        )
        raise HTTPException(status_code=500, detail=f"Błąd analizy WLR: {exc}") from exc

    request_summary_payload = build_wlr_request_summary(parsed_request, upload_id=request.upload_id)
    request_summary = _build_analyze_request_summary(request_summary_payload)

    accepted_assessments = list(analysis.accepted_assessments)
    conditional_assessments = list(analysis.conditional_assessments)
    rejected_assessments = list(analysis.rejected_assessments)
    candidate_frequency_records = list(analysis.candidate_frequency_records)
    record_by_key = {
        (record.channel_ab, record.channel_ba, record.polarization): record
        for record in candidate_frequency_records
    }
    display_assessments = accepted_assessments if accepted_assessments else (conditional_assessments + rejected_assessments)
    display_assessment_by_key = {
        (item.candidate.channel_ab, item.candidate.channel_ba, item.candidate.polarization): item
        for item in display_assessments
    }
    global_best_record = candidate_frequency_records[0] if candidate_frequency_records else None

    recommendations: list[ChannelRecommendation] = []
    for rank, assessment in enumerate(display_assessments[:20], start=1):
        record = record_by_key.get(
            (assessment.candidate.channel_ab, assessment.candidate.channel_ba, assessment.candidate.polarization)
        )
        top_conflicts = [
            f"{conflict.link_id} | {conflict.operator_name or '-'} | {conflict.risk_level} | {conflict.score:.1f}"
            for conflict in assessment.conflicts[:5]
        ]
        status_label = getattr(assessment, "status", "UNKNOWN")
        rejection_reasons = list(getattr(assessment, "rejection_reasons", []))
        td_values = [
            value
            for conflict in assessment.conflicts
            for value in (conflict.estimated_degradation_victim_db, conflict.estimated_degradation_aggressor_db)
            if value is not None
        ]
        ci_values = [result.ci_db for result in (record.pairwise_results if record else []) if result.ci_db is not None]
        td_worst = max(td_values) if td_values else 0.0
        ci_worst = min(ci_values) if ci_values else 999.0
        margin_ab = record.worst_margin_ab_db if record else None
        margin_ba = record.worst_margin_ba_db if record else None
        decision_core = (
            f"A→B={assessment.status_ab}, B→A={assessment.status_ba}; "
            f"MargAB={margin_ab:.2f} dB, MargBA={margin_ba:.2f} dB; "
            f"TDmax={td_worst:.2f} dB; CImin={ci_worst:.1f} dB"
            if margin_ab is not None and margin_ba is not None
            else f"A→B={assessment.status_ab}, B→A={assessment.status_ba}; "
            f"TDmax={td_worst:.2f} dB; CImin={ci_worst:.1f} dB"
        )

        if status_label == "ACCEPTED":
            summary_text = f"ZGODNY (TAK) — {decision_core}"
        elif status_label == "CONDITIONAL":
            extra = "; ".join(rejection_reasons[:2]) if rejection_reasons else assessment.best_explanation
            summary_text = f"WARUNKOWY (KOORDYNACJA) — {decision_core}; {extra}"
        elif rejection_reasons:
            summary_text = f"NIEZGODNY (NIE) — {decision_core}; " + "; ".join(rejection_reasons[:2])
        else:
            summary_text = f"{status_label} — {decision_core}; {assessment.best_explanation}"

        recommendations.append(
            ChannelRecommendation(
                rank=rank,
                channel_ab=assessment.candidate.channel_ab,
                channel_ba=assessment.candidate.channel_ba,
                polarization=assessment.candidate.polarization,
                score=assessment.score,
                status=status_label,
                red_conflicts=assessment.red_conflicts,
                amber_conflicts=assessment.amber_conflicts,
                green_conflicts=assessment.green_conflicts,
                candidate_links_count=assessment.candidate_links_count,
                summary=summary_text,
                best_explanation=assessment.best_explanation,
                rejection_reasons=rejection_reasons,
                top_conflicts=top_conflicts,
                details={
                    "status": status_label,
                    "rejection_reasons": rejection_reasons,
                    "plan_symbol": assessment.candidate.plan_symbol,
                    "freq_ab_ghz": assessment.candidate.freq_ab_ghz,
                    "freq_ba_ghz": assessment.candidate.freq_ba_ghz,
                    "requested_distance": record.requested_distance if record else None,
                    "uke_like_margnad_db": record.uke_like_margnad_db if record else None,
                    "uke_like_margodb_db": record.uke_like_margodb_db if record else None,
                    "inferred_uke_like_status": record.inferred_uke_like_status if record else None,
                    "uke_like_problem_flags": record.uke_like_problem_flags if record else [],
                    "worst_margin_ab_db": margin_ab,
                    "worst_margin_ba_db": margin_ba,
                    "worst_duplex_margin_db": record.worst_duplex_margin_db if record else None,
                    "access_like_dobry_kanal_seed": record.access_like_dobry_kanal_seed if record else None,
                    "access_like_dobry_kanal_value": record.access_like_dobry_kanal_value if record else None,
                    "access_like_problem_pair_count": record.access_like_problem_pair_count if record else None,
                    "access_like_problem_decision": record.access_like_problem_decision if record else None,
                    "access_like_problem_decision_1_count": record.access_like_problem_decision_1_count if record else None,
                    "access_like_problem_decision_2_count": record.access_like_problem_decision_2_count if record else None,
                    "access_like_qualification_state": record.access_like_qualification_state if record else None,
                    "access_like_qualification_rank": record.access_like_qualification_rank if record else None,
                    "access_like_status_seed": record.access_like_status_seed if record else None,
                    "access_like_status_code": record.access_like_status_code if record else None,
                    "access_like_status_label": record.access_like_status_label if record else None,
                    "access_like_state_notes": record.access_like_state_notes if record else [],
                },
            )
        )

    conflicts: list[ConflictItem] = []
    reason_assessments = conditional_assessments + rejected_assessments
    for assessment in reason_assessments[:20]:
        rejection_reasons = list(getattr(assessment, "rejection_reasons", []))
        primary_reason = "; ".join(rejection_reasons[:3]) if rejection_reasons else assessment.best_explanation
        conflicts.append(
            ConflictItem(
                link_id=f"{assessment.candidate.channel_ab}/{assessment.candidate.channel_ba}/{assessment.candidate.polarization}",
                operator_name=None,
                permit_number=None,
                same_operator=False,
                conflict_type="unknown",
                role="unknown",
                score=assessment.score,
                risk_level="amber" if getattr(assessment, "status", "UNKNOWN") == "CONDITIONAL" else "red",
                distance_km=None,
                freq_delta_ab_mhz=None,
                freq_delta_ba_mhz=None,
                overlap_ab_ratio=None,
                overlap_ba_ratio=None,
                channel_ab=assessment.candidate.channel_ab,
                channel_ba=assessment.candidate.channel_ba,
                polarization=assessment.candidate.polarization,
                estimated_interference_victim_dbm=None,
                estimated_interference_aggressor_dbm=None,
                estimated_ci_victim_db=None,
                estimated_ci_aggressor_db=None,
                estimated_degradation_victim_db=None,
                estimated_degradation_aggressor_db=None,
                decision_explanation=primary_reason,
                details={
                    "status": getattr(assessment, "status", "UNKNOWN"),
                    "rejection_reasons": rejection_reasons,
                    "top_conflicts": [
                        {
                            "link_id": conflict.link_id,
                            "operator_name": conflict.operator_name,
                            "risk_level": conflict.risk_level,
                            "score": conflict.score,
                            "decision_explanation": conflict.decision_explanation,
                        }
                        for conflict in assessment.conflicts[:5]
                    ],
                },
            )
        )

    best_assessment = display_assessments[0] if display_assessments else None
    best_record = None
    if best_assessment:
        best_record = record_by_key.get(
            (best_assessment.candidate.channel_ab, best_assessment.candidate.channel_ba, best_assessment.candidate.polarization)
        )

    requested_assessments = [
        item
        for item in analysis.channel_assessments
        if item.candidate.channel_ab == parsed_request.channel_ab
        and item.candidate.channel_ba == parsed_request.channel_ba
    ]
    requested_assessment = None
    if requested_assessments:
        if parsed_request.requested_polarization:
            requested_assessment = next(
                (
                    item
                    for item in requested_assessments
                    if item.candidate.polarization == parsed_request.requested_polarization
                ),
                requested_assessments[0],
            )
        else:
            requested_assessment = requested_assessments[0]
    requested_record = None
    if requested_assessment:
        requested_record = record_by_key.get(
            (
                requested_assessment.candidate.channel_ab,
                requested_assessment.candidate.channel_ba,
                requested_assessment.candidate.polarization,
            )
        )

    requested_channel_top_conflicts: list[dict] = []
    if requested_assessment:
        for conflict in requested_assessment.conflicts[:10]:
            requested_channel_top_conflicts.append(
                {
                    "link_id": conflict.link_id,
                    "operator_name": conflict.operator_name,
                    "permit_number": conflict.permit_number,
                    "same_operator": conflict.same_operator,
                    "conflict_type": conflict.conflict_type,
                    "risk_level": conflict.risk_level,
                    "score": conflict.score,
                    "distance_km": conflict.distance_km,
                    "freq_delta_ab_mhz": conflict.freq_delta_ab_mhz,
                    "freq_delta_ba_mhz": conflict.freq_delta_ba_mhz,
                    "freq_delta_cross_ab_mhz": conflict.freq_delta_cross_ab_mhz,
                    "freq_delta_cross_ba_mhz": conflict.freq_delta_cross_ba_mhz,
                    "effective_freq_delta_mhz": conflict.effective_freq_delta_mhz,
                    "overlap_ab_ratio": conflict.overlap_ab_ratio,
                    "overlap_ba_ratio": conflict.overlap_ba_ratio,
                    "estimated_ci_victim_db": conflict.estimated_ci_victim_db,
                    "estimated_ci_aggressor_db": conflict.estimated_ci_aggressor_db,
                    "estimated_degradation_victim_db": conflict.estimated_degradation_victim_db,
                    "estimated_degradation_aggressor_db": conflict.estimated_degradation_aggressor_db,
                    "decision_explanation": conflict.decision_explanation,
                    "details": conflict.details,
                }
            )

    link_by_id = {link.link_id: link for link in analysis.candidate_links}

    map_features: list[dict] = [
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [parsed_request.site_a.lon_deg, parsed_request.site_a.lat_deg],
                    [parsed_request.site_b.lon_deg, parsed_request.site_b.lat_deg],
                ],
            },
            "properties": {
                "feature_type": "requested_link",
                "kind": "requested_link",
                "label": parsed_request.link_name or "Requested WLR",
                "plan_symbol": parsed_request.plan_symbol,
                "channel_ab": parsed_request.channel_ab,
                "channel_ba": parsed_request.channel_ba,
                "polarization": parsed_request.requested_polarization,
            },
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [parsed_request.site_a.lon_deg, parsed_request.site_a.lat_deg],
            },
            "properties": {
                "feature_type": "requested_site",
                "kind": "requested_site",
                "site": "A",
                "label": parsed_request.site_a.name or "A",
            },
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [parsed_request.site_b.lon_deg, parsed_request.site_b.lat_deg],
            },
            "properties": {
                "feature_type": "requested_site",
                "kind": "requested_site",
                "site": "B",
                "label": parsed_request.site_b.name or "B",
            },
        },
    ]

    if requested_assessment:
        for conflict in requested_assessment.conflicts[:10]:
            link = link_by_id.get(conflict.link_id)
            if not link:
                continue
            map_features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [link.site_a.point.lon_deg, link.site_a.point.lat_deg],
                            [link.site_b.point.lon_deg, link.site_b.point.lat_deg],
                        ],
                    },
                    "properties": {
                        "feature_type": "conflict_link",
                        "kind": "conflict_link",
                        "link_id": conflict.link_id,
                        "operator_name": conflict.operator_name,
                        "permit_number": conflict.permit_number,
                        "plan_symbol": link.plan_symbol or conflict.details.get("plan_symbol"),
                        "polarization": link.polarization or conflict.details.get("polarization"),
                        "same_plan_as_request": (link.plan_symbol or conflict.details.get("plan_symbol")) == parsed_request.plan_symbol,
                        "risk_level": conflict.risk_level,
                        "conflict_type": conflict.conflict_type,
                        "score": conflict.score,
                        "distance_km": conflict.distance_km,
                        "effective_freq_delta_mhz": conflict.effective_freq_delta_mhz,
                        "estimated_ci_victim_db": conflict.estimated_ci_victim_db,
                        "estimated_ci_aggressor_db": conflict.estimated_ci_aggressor_db,
                        "estimated_degradation_victim_db": conflict.estimated_degradation_victim_db,
                        "estimated_degradation_aggressor_db": conflict.estimated_degradation_aggressor_db,
                        "decision_explanation": conflict.decision_explanation,
                    },
                }
            )

    summary = AnalyzeSummary(
        request_operator_name=analysis.request_operator_name,
        candidate_links_count=len(analysis.candidate_links),
        channels_evaluated=len(analysis.channel_candidates),
        accepted_count=len(accepted_assessments),
        conditional_count=len(conditional_assessments),
        rejected_count=len(rejected_assessments),
        has_accepted=bool(accepted_assessments),
        best_channel_ab=best_assessment.candidate.channel_ab if best_assessment else None,
        best_channel_ba=best_assessment.candidate.channel_ba if best_assessment else None,
        best_polarization=best_assessment.candidate.polarization if best_assessment else None,
        best_score=best_record.score if best_record else (best_assessment.score if best_assessment else None),
    )
    recommended_key = None
    if best_assessment:
        recommended_key = (
            best_assessment.candidate.channel_ab,
            best_assessment.candidate.channel_ba,
            best_assessment.candidate.polarization,
        )
    channel_chart = _build_channel_chart(candidate_frequency_records, parsed_request, recommended_key)
    link_budget_plan = _build_link_budget_plan(parsed_request, global_best_record)

    debug = {
        "bbox": {
            "min_lon": analysis.bbox.min_lon,
            "min_lat": analysis.bbox.min_lat,
            "max_lon": analysis.bbox.max_lon,
            "max_lat": analysis.bbox.max_lat,
        },
        "candidate_links_scope": {
            "mode": "all_spatial_links",
            "same_plan_count": sum(1 for link in analysis.candidate_links if link.plan_symbol == parsed_request.plan_symbol),
            "other_plan_count": sum(1 for link in analysis.candidate_links if link.plan_symbol != parsed_request.plan_symbol),
        },
        "candidate_links_count": len(analysis.candidate_links),
        "channel_candidates_count": len(analysis.channel_candidates),
        "candidate_frequency_records_count": len(candidate_frequency_records),
        "accepted_count": len(accepted_assessments),
        "conditional_count": len(conditional_assessments),
        "rejected_count": len(rejected_assessments),
        "has_accepted": bool(accepted_assessments),
        "requested_channel": {
            "channel_ab": parsed_request.channel_ab,
            "channel_ba": parsed_request.channel_ba,
            "polarization": parsed_request.requested_polarization,
        },
        "requested_channel_assessment": {
            "status": getattr(requested_assessment, "status", None),
            "score": requested_record.score if requested_record else (requested_assessment.score if requested_assessment else None),
            "red_conflicts": requested_assessment.red_conflicts if requested_assessment else None,
            "amber_conflicts": requested_assessment.amber_conflicts if requested_assessment else None,
            "green_conflicts": requested_assessment.green_conflicts if requested_assessment else None,
            "ignored_conflicts_count": len(getattr(requested_assessment, "ignored_conflicts", [])) if requested_assessment else None,
            "candidate_links_count": requested_assessment.candidate_links_count if requested_assessment else None,
            "best_explanation": requested_assessment.best_explanation if requested_assessment else None,
            "rejection_reasons": list(getattr(requested_assessment, "rejection_reasons", [])) if requested_assessment else [],
            "estimated_margin_ab_db": requested_record.worst_margin_ab_db if requested_record else None,
            "estimated_margin_ba_db": requested_record.worst_margin_ba_db if requested_record else None,
            "uke_like_margnad_db": requested_record.uke_like_margnad_db if requested_record else None,
            "uke_like_margodb_db": requested_record.uke_like_margodb_db if requested_record else None,
            "inferred_uke_like_status": requested_record.inferred_uke_like_status if requested_record else None,
            "uke_like_problem_flags": requested_record.uke_like_problem_flags if requested_record else [],
            "worst_duplex_margin_db": requested_record.worst_duplex_margin_db if requested_record else None,
            "access_like_dobry_kanal_seed": requested_record.access_like_dobry_kanal_seed if requested_record else None,
            "access_like_dobry_kanal_value": requested_record.access_like_dobry_kanal_value if requested_record else None,
            "access_like_problem_pair_count": requested_record.access_like_problem_pair_count if requested_record else None,
            "access_like_problem_decision": requested_record.access_like_problem_decision if requested_record else None,
            "access_like_problem_decision_1_count": requested_record.access_like_problem_decision_1_count if requested_record else None,
            "access_like_problem_decision_2_count": requested_record.access_like_problem_decision_2_count if requested_record else None,
            "access_like_qualification_state": requested_record.access_like_qualification_state if requested_record else None,
            "access_like_qualification_rank": requested_record.access_like_qualification_rank if requested_record else None,
            "access_like_status_seed": requested_record.access_like_status_seed if requested_record else None,
            "access_like_status_code": requested_record.access_like_status_code if requested_record else None,
            "access_like_status_label": requested_record.access_like_status_label if requested_record else None,
            "access_like_state_notes": requested_record.access_like_state_notes if requested_record else [],
            "access_fkand_jest_wynik_n": requested_record.access_fkand_jest_wynik_n if requested_record else None,
            "access_fkand_jest_wynik_o": requested_record.access_fkand_jest_wynik_o if requested_record else None,
            "access_fkand_margnad_db": requested_record.access_fkand_margnad_db if requested_record else None,
            "access_fkand_margodb_db": requested_record.access_fkand_margodb_db if requested_record else None,
            "access_fkand_n_nad": requested_record.access_fkand_n_nad if requested_record else None,
            "access_fkand_n_odb": requested_record.access_fkand_n_odb if requested_record else None,
            "access_fkand_update_notes": requested_record.access_fkand_update_notes if requested_record else [],
            "access_fkand_problem_path_margnad_db": requested_record.access_fkand_problem_path_margnad_db if requested_record else None,
            "access_fkand_problem_path_margodb_db": requested_record.access_fkand_problem_path_margodb_db if requested_record else None,
            "access_fkand_problem_path_n_nad": requested_record.access_fkand_problem_path_n_nad if requested_record else None,
            "access_fkand_problem_path_n_odb": requested_record.access_fkand_problem_path_n_odb if requested_record else None,
            "access_fkand_incompatible_path_margnad_db": requested_record.access_fkand_incompatible_path_margnad_db if requested_record else None,
            "access_fkand_incompatible_path_margodb_db": requested_record.access_fkand_incompatible_path_margodb_db if requested_record else None,
            "access_fkand_incompatible_path_n_nad": requested_record.access_fkand_incompatible_path_n_nad if requested_record else None,
            "access_fkand_incompatible_path_n_odb": requested_record.access_fkand_incompatible_path_n_odb if requested_record else None,
            "access_fkand_problem_only_count": requested_record.access_fkand_problem_only_count if requested_record else None,
            "access_fkand_blocking_only_count": requested_record.access_fkand_blocking_only_count if requested_record else None,
            "access_fkand_overlap_count": requested_record.access_fkand_overlap_count if requested_record else None,
            "access_fkand_dual_path_notes": requested_record.access_fkand_dual_path_notes if requested_record else [],
            "access_fkand_gate_status": requested_record.access_fkand_gate_status if requested_record else None,
            "access_fkand_gate_rank": requested_record.access_fkand_gate_rank if requested_record else None,
            "access_fkand_gate_notes": requested_record.access_fkand_gate_notes if requested_record else [],
            "channel_ab": requested_assessment.candidate.channel_ab if requested_assessment else None,
            "channel_ba": requested_assessment.candidate.channel_ba if requested_assessment else None,
            "candidate_polarization": requested_assessment.candidate.polarization if requested_assessment else None,
            "requested_distance": requested_record.requested_distance if requested_record else None,
            "uke_like_directional_rows": build_uke_like_directional_candidate_rows(requested_record) if requested_record else [],
            "top_conflicts_count": len(requested_assessment.conflicts) if requested_assessment else 0,
        } if requested_assessment else None,
        "requested_channel_top_conflicts": requested_channel_top_conflicts,
        "link_budget_plan": link_budget_plan.dict() if link_budget_plan else None,
        "top_candidates": [
            {
                "status": record.status,
                "status_ab": record.status_ab,
                "status_ba": record.status_ba,
                "channel_ab": record.channel_ab,
                "channel_ba": record.channel_ba,
                "polarization": record.polarization,
                "score": record.score,
                "requested_distance": record.requested_distance,
                "uke_like_margnad_db": record.uke_like_margnad_db,
                "uke_like_margodb_db": record.uke_like_margodb_db,
                "inferred_uke_like_status": record.inferred_uke_like_status,
                "uke_like_problem_flags": record.uke_like_problem_flags,
                "worst_duplex_margin_db": record.worst_duplex_margin_db,
                "pairwise_results_count": len(record.pairwise_results),
                "pairwise_blocking_count": record.pairwise_blocking_count,
                "cochannel_pairwise_count": record.pairwise_cochannel_count,
                "red_pairwise_count": record.pairwise_red_count,
                "access_like_dobry_kanal_seed": record.access_like_dobry_kanal_seed,
                "access_like_dobry_kanal_value": record.access_like_dobry_kanal_value,
                "access_like_problem_pair_count": record.access_like_problem_pair_count,
                "access_like_problem_decision": record.access_like_problem_decision,
                "access_like_problem_decision_1_count": record.access_like_problem_decision_1_count,
                "access_like_problem_decision_2_count": record.access_like_problem_decision_2_count,
                "access_like_qualification_state": record.access_like_qualification_state,
                "access_like_qualification_rank": record.access_like_qualification_rank,
                "access_like_status_seed": record.access_like_status_seed,
                "access_like_status_code": record.access_like_status_code,
                "access_like_status_label": record.access_like_status_label,
                "access_like_state_notes": record.access_like_state_notes,
                "access_fkand_jest_wynik_n": record.access_fkand_jest_wynik_n,
                "access_fkand_jest_wynik_o": record.access_fkand_jest_wynik_o,
                "access_fkand_margnad_db": record.access_fkand_margnad_db,
                "access_fkand_margodb_db": record.access_fkand_margodb_db,
                "access_fkand_n_nad": record.access_fkand_n_nad,
                "access_fkand_n_odb": record.access_fkand_n_odb,
                "access_fkand_update_notes": record.access_fkand_update_notes,
                "uke_like_directional_rows": build_uke_like_directional_candidate_rows(record),
                "best_explanation": (
                    display_assessment_by_key[
                        (record.channel_ab, record.channel_ba, record.polarization)
                    ].best_explanation
                    if (record.channel_ab, record.channel_ba, record.polarization) in display_assessment_by_key
                    else None
                ),
                "estimated_margin_ab_db": record.worst_margin_ab_db,
                "estimated_margin_ba_db": record.worst_margin_ba_db,
                "rejection_reasons": (
                    list(
                        getattr(
                            display_assessment_by_key[(record.channel_ab, record.channel_ba, record.polarization)],
                            "rejection_reasons",
                            [],
                        )
                    )
                    if (record.channel_ab, record.channel_ba, record.polarization) in display_assessment_by_key
                    else []
                ),
            }
            for record in candidate_frequency_records[:10]
        ],
        "access_like_top_candidates": [
            {
                "status": record.status,
                "channel_ab": record.channel_ab,
                "channel_ba": record.channel_ba,
                "polarization": record.polarization,
                "requested_distance": record.requested_distance,
                "worst_duplex_margin_db": record.worst_duplex_margin_db,
                "access_like_dobry_kanal_seed": record.access_like_dobry_kanal_seed,
                "access_like_dobry_kanal_value": record.access_like_dobry_kanal_value,
                "access_like_problem_pair_count": record.access_like_problem_pair_count,
                "access_like_problem_decision": record.access_like_problem_decision,
                "access_like_problem_decision_1_count": record.access_like_problem_decision_1_count,
                "access_like_problem_decision_2_count": record.access_like_problem_decision_2_count,
                "access_like_qualification_state": record.access_like_qualification_state,
                "access_like_qualification_rank": record.access_like_qualification_rank,
                "access_like_status_seed": record.access_like_status_seed,
                "access_like_status_code": record.access_like_status_code,
                "access_like_status_label": record.access_like_status_label,
                "access_like_state_notes": record.access_like_state_notes,
                "access_fkand_jest_wynik_n": record.access_fkand_jest_wynik_n,
                "access_fkand_jest_wynik_o": record.access_fkand_jest_wynik_o,
                "access_fkand_margnad_db": record.access_fkand_margnad_db,
                "access_fkand_margodb_db": record.access_fkand_margodb_db,
                "access_fkand_n_nad": record.access_fkand_n_nad,
                "access_fkand_n_odb": record.access_fkand_n_odb,
                "access_fkand_update_notes": record.access_fkand_update_notes,
            }
            for record in sorted(candidate_frequency_records, key=_access_like_record_sort_key)[:10]
        ],
    }

    if not accepted_assessments and not recommendations:
        recommendations.append(
            ChannelRecommendation(
                rank=1,
                channel_ab="-",
                channel_ba="-",
                polarization="V",
                score=0.0,
                status="NO_ACCEPTED",
                red_conflicts=0,
                amber_conflicts=0,
                green_conflicts=0,
                candidate_links_count=0,
                summary="Nie znaleziono kanału ACCEPTED w analizowanym planie.",
                best_explanation="Brak kanału spełniającego próg degradacji 1.0 dB i progi CI.",
                rejection_reasons=[],
                top_conflicts=[],
                details={"status": "NO_ACCEPTED"},
            )
        )

    response = AnalyzeResponse(
        request=request_summary,
        map={
            "bbox": [analysis.bbox.min_lon, analysis.bbox.min_lat, analysis.bbox.max_lon, analysis.bbox.max_lat],
            "features": MapFeatureCollection(type="FeatureCollection", features=map_features),
        },
        summary=summary,
        channel_chart=channel_chart,
        link_budget_plan=link_budget_plan,
        recommendations=recommendations,
        conflicts=conflicts,
        debug=debug,
    )

    _append_analysis_run_log(
        _build_analysis_run_entry(
            trigger=trigger,
            request=request,
            started_at=started_at,
            duration_ms=(time.perf_counter() - started_perf) * 1000.0,
            status="ok",
            parsed_request=parsed_request,
            response=response,
        )
    )

    return response, parsed_request


def _format_endpoint(parsed_request, endpoint, fallback_label: str) -> str:
    address = endpoint.name or fallback_label
    coords = f"{endpoint.lat_deg:.5f}, {endpoint.lon_deg:.5f}"
    return f"{address} ({coords})"


def _access_like_record_sort_key(record) -> tuple:
    worst_margin = record.worst_duplex_margin_db if record.worst_duplex_margin_db is not None else -999.0
    return (
        0 if record.access_like_status_code == 2 else 1,
        0 if record.access_like_problem_decision in (None, 1) else 1,
        record.access_like_problem_decision_2_count,
        record.access_like_problem_pair_count,
        -worst_margin,
        record.pairwise_blocking_count,
        record.pairwise_cochannel_count,
        record.pairwise_red_count,
        record.requested_distance,
        record.channel_ab,
        record.channel_ba,
        record.polarization,
    )


def _channel_sort_key(channel_value: str) -> tuple[int, int, str]:
    match = re.match(r"^(\d+)(.*)$", str(channel_value or "").strip())
    if not match:
        return (10_000, 10_000, str(channel_value))
    number = int(match.group(1))
    suffix = match.group(2)
    prime_rank = suffix.count("'")
    return (number, prime_rank, suffix)


def _build_channel_chart(candidate_frequency_records, parsed_request, recommended_key: tuple[str, str, str] | None = None) -> ChannelInterferenceChart:
    items: list[ChannelInterferenceBar] = []
    threshold_db = 1.0

    for record in sorted(
        candidate_frequency_records,
        key=lambda item: (
            _channel_sort_key(item.channel_ab),
            _channel_sort_key(item.channel_ba),
            item.polarization,
        ),
    ):
        td_ab_values = [
            result.degradation_db
            for result in record.pairwise_results
            if result.direction == "A->B" and result.degradation_db is not None
        ]
        td_ba_values = [
            result.degradation_db
            for result in record.pairwise_results
            if result.direction == "B->A" and result.degradation_db is not None
        ]
        td_max_ab_db = max(td_ab_values) if td_ab_values else 0.0
        td_max_ba_db = max(td_ba_values) if td_ba_values else 0.0
        td_max_db = max(td_max_ab_db, td_max_ba_db)
        over_threshold_pair_count = sum(
            1
            for result in record.pairwise_results
            if result.degradation_db is not None and result.degradation_db > threshold_db
        )

        items.append(
            ChannelInterferenceBar(
                label=f"{record.channel_ab}/{record.channel_ba} {record.polarization}",
                channel_ab=record.channel_ab,
                channel_ba=record.channel_ba,
                polarization=record.polarization,
                status=record.status,
                gate_status=record.access_fkand_gate_status,
                requested=(
                    record.channel_ab == parsed_request.channel_ab
                    and record.channel_ba == parsed_request.channel_ba
                    and record.polarization == parsed_request.requested_polarization
                ),
                recommended=(
                    recommended_key is not None
                    and (record.channel_ab, record.channel_ba, record.polarization) == recommended_key
                ),
                td_max_db=td_max_db,
                td_max_ab_db=td_max_ab_db,
                td_max_ba_db=td_max_ba_db,
                over_threshold_pair_count=over_threshold_pair_count,
                pairwise_results_count=len(record.pairwise_results),
                red_pair_count=record.pairwise_red_count,
                blocking_pair_count=record.pairwise_blocking_count,
            )
        )

    max_td_db = max((item.td_max_db for item in items), default=0.0)
    return ChannelInterferenceChart(
        threshold_db=threshold_db,
        max_td_db=max_td_db,
        items=items,
    )


def _fit_text(pdf: SimplePdfCanvas, text: str, max_width: float, font_name: str, font_size: float) -> str:
    if pdf.string_width(text, font_name, font_size) <= max_width:
        return text
    ellipsis = "..."
    trimmed = text
    while trimmed and pdf.string_width(trimmed + ellipsis, font_name, font_size) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + ellipsis) if trimmed else ellipsis


def _draw_kv_row(pdf: SimplePdfCanvas, y: float, label: str, value: str, label_width: float, page_width: float) -> float:
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(16 * mm, y, label)
    pdf.setFont("Helvetica", 9)
    available_width = page_width - 16 * mm - label_width - 18 * mm
    pdf.drawString(16 * mm + label_width, y, _fit_text(pdf, value, available_width, "Helvetica", 9))
    return y - 5.8 * mm


def _build_report_pdf(response: AnalyzeResponse, parsed_request, source_summary: dict) -> bytes:
    buffer = BytesIO()
    page_width, page_height = A4
    pdf = SimplePdfCanvas(buffer, pagesize=A4)
    pdf.setTitle(f"Raport koordynacji {response.request.upload_id}")
    pdf.setAuthor("UKE Channel Coordination")

    y = page_height - 16 * mm

    pdf.setFillColor(HexColor("#0f172a"))
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(16 * mm, y, "Raport analizy kompatybilnosci lacza radiowego")
    y -= 7 * mm
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(HexColor("#475569"))
    run_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pdf.drawString(16 * mm, y, f"Data wykonania: {run_stamp}")
    y -= 4 * mm
    pdf.drawString(16 * mm, y, f"Silnik: {ENGINE_VERSION}    Zrodlo: {source_summary['filename']}")
    y -= 8 * mm

    pdf.setStrokeColor(HexColor("#cbd5e1"))
    pdf.setLineWidth(0.5)
    pdf.line(16 * mm, y, page_width - 16 * mm, y)
    y -= 7 * mm

    pdf.setFillColor(HexColor("#0f172a"))
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(16 * mm, y, "Badane przeslo")
    y -= 6.5 * mm

    label_width = 40 * mm
    y = _draw_kv_row(pdf, y, "Link:", response.request.link_name or "-", label_width, page_width)
    y = _draw_kv_row(pdf, y, "Upload ID:", response.request.upload_id or "-", label_width, page_width)
    y = _draw_kv_row(pdf, y, "Adres A:", _format_endpoint(parsed_request, parsed_request.site_a, "Site A"), label_width, page_width)
    y = _draw_kv_row(pdf, y, "Adres B:", _format_endpoint(parsed_request, parsed_request.site_b, "Site B"), label_width, page_width)
    y = _draw_kv_row(pdf, y, "Plan / pasmo:", f"{response.request.plan_symbol or '-'} / {response.request.channel_width_mhz or '-'} MHz", label_width, page_width)
    y = _draw_kv_row(
        pdf,
        y,
        "Czestotliwosci:",
        f"A->B {parsed_request.freq_ab_ghz:.4f} GHz, B->A {parsed_request.freq_ba_ghz:.4f} GHz",
        label_width,
        page_width,
    )
    y = _draw_kv_row(
        pdf,
        y,
        "Kanal zadany:",
        f"{response.request.requested_channel or '-'} / pol. {response.request.requested_polarization or '-'}",
        label_width,
        page_width,
    )
    y = _draw_kv_row(
        pdf,
        y,
        "Podsumowanie:",
        (
            f"ACCEPTED {response.summary.accepted_count}, CONDITIONAL {response.summary.conditional_count}, "
            f"REJECTED {response.summary.rejected_count}, analizowane lacza {response.summary.candidate_links_count}"
        ),
        label_width,
        page_width,
    )

    if response.link_budget_plan and y > 70 * mm:
        y -= 2 * mm
        pdf.setFillColor(HexColor("#0f172a"))
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(16 * mm, y, "Robocze parametry KO, budzetu i niedostepnosci")
        y -= 6.5 * mm

        plan = response.link_budget_plan
        y = _draw_kv_row(pdf, y, "Kanal:", plan.channel_label or "-", label_width, page_width)
        y = _draw_kv_row(pdf, y, "Planowana modulacja:", plan.planned_modulation or "-", label_width, page_width)
        y = _draw_kv_row(pdf, y, "ATPC:", "ON" if plan.atpc_enabled else "OFF", label_width, page_width)
        y = _draw_kv_row(pdf, y, "Min moc nadajnika [dBm]:", f"{plan.min_tx_power_dbm:.0f}" if plan.min_tx_power_dbm is not None else "-", label_width, page_width)
        y = _draw_kv_row(pdf, y, "Maks./ust. moc odbierana [dBm]:", f"{plan.set_rx_power_dbm:.0f}" if plan.set_rx_power_dbm is not None else "-", label_width, page_width)
        y = _draw_kv_row(pdf, y, "Min moc odbierana [dBm]:", f"{plan.min_rx_power_dbm:.0f}" if plan.min_rx_power_dbm is not None else "-", label_width, page_width)
        y = _draw_kv_row(pdf, y, "KO moc nadajnika [dBm]:", f"{plan.ko_tx_power_dbm:.0f}" if plan.ko_tx_power_dbm is not None else "-", label_width, page_width)
        y = _draw_kv_row(pdf, y, "KO moc odbierana [dBm]:", f"{plan.ko_rx_power_dbm:.0f}" if plan.ko_rx_power_dbm is not None else "-", label_width, page_width)
        y = _draw_kv_row(pdf, y, "Maks. moc nadajnika [dBm]:", f"{plan.max_tx_power_dbm:.0f}" if plan.max_tx_power_dbm is not None else "-", label_width, page_width)
        y = _draw_kv_row(pdf, y, "Planowany margines [dB]:", f"{plan.planned_margin_db:.1f}" if plan.planned_margin_db is not None else "-", label_width, page_width)
        y = _draw_kv_row(
            pdf,
            y,
            "Planowana roczna dostepnosc:",
            f"{plan.planned_annual_reliability_pct:.2f} %" if plan.planned_annual_reliability_pct is not None else "-",
            label_width,
            page_width,
        )
        y = _draw_kv_row(
            pdf,
            y,
            "Planowana roczna niedostepnosc:",
            f"{plan.planned_annual_outage_min:.1f} min" if plan.planned_annual_outage_min is not None else "-",
            label_width,
            page_width,
        )
        y = _draw_kv_row(
            pdf,
            y,
            "Roczna nieprzerywalnosc:",
            f"{plan.annual_uninterruptibility_pct:.2f} %" if plan.annual_uninterruptibility_pct is not None else "-",
            label_width,
            page_width,
        )
        y = _draw_kv_row(
            pdf,
            y,
            "Roczna niedostepnosc:",
            f"{plan.annual_outage_min:.1f} min" if plan.annual_outage_min is not None else "-",
            label_width,
            page_width,
        )
        if plan.warnings:
            pdf.setFont("Helvetica-Bold", 9)
            pdf.setFillColor(HexColor("#7c2d12"))
            pdf.drawString(16 * mm, y, "Ostrzezenia:")
            y -= 5.0 * mm
            pdf.setFont("Helvetica", 8)
            pdf.setFillColor(HexColor("#0f172a"))
            for warning in plan.warnings[:3]:
                pdf.drawString(20 * mm, y, _fit_text(pdf, f"- {warning}", page_width - 36 * mm, "Helvetica", 8))
                y -= 4.5 * mm

    y -= 2 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(16 * mm, y, "Rekomendowane kanaly")
    y -= 6.5 * mm

    table_x = 16 * mm
    table_width = page_width - 32 * mm
    col_widths = [12 * mm, 22 * mm, 22 * mm, 14 * mm, 24 * mm, 18 * mm, table_width - (12 + 22 + 22 + 14 + 24 + 18) * mm]
    headers = ["Lp.", "A->B", "B->A", "Pol.", "Status", "Score", "Uzasadnienie"]
    row_height = 7 * mm

    pdf.setFillColor(HexColor("#e2e8f0"))
    pdf.rect(table_x, y - row_height + 1.2 * mm, table_width, row_height, fill=1, stroke=0)
    pdf.setFillColor(HexColor("#0f172a"))
    pdf.setFont("Helvetica-Bold", 8)
    x = table_x + 1.2 * mm
    for header, width in zip(headers, col_widths):
        pdf.drawString(x, y - 4.2 * mm, header)
        x += width
    y -= row_height

    pdf.setFont("Helvetica", 7.5)
    rows = response.recommendations[:6]
    if not rows:
        rows = [
            ChannelRecommendation(
                rank=1,
                channel_ab="-",
                channel_ba="-",
                polarization="V",
                score=0.0,
                status="BRAK",
                summary="Brak rekomendacji.",
            )
        ]

    for item in rows:
        if y < 22 * mm:
            break
        pdf.setFillColor(WHITE if item.rank % 2 else HexColor("#f8fafc"))
        pdf.rect(table_x, y - row_height + 1.2 * mm, table_width, row_height, fill=1, stroke=0)
        pdf.setFillColor(HexColor("#0f172a"))
        cells = [
            str(item.rank),
            item.channel_ab,
            item.channel_ba,
            item.polarization,
            item.status or "-",
            f"{item.score:.1f}",
            (item.summary or item.best_explanation or "-").replace("ZGODNY (TAK) — ", "").replace("WARUNKOWY (KOORDYNACJA) — ", "").replace("NIEZGODNY (NIE) — ", ""),
        ]
        x = table_x + 1.2 * mm
        for cell, width in zip(cells, col_widths):
            font_name = "Helvetica-Bold" if width == col_widths[4] else "Helvetica"
            pdf.setFont(font_name, 7.5)
            pdf.drawString(x, y - 4.2 * mm, _fit_text(pdf, str(cell), width - 2.4 * mm, font_name, 7.5))
            x += width
        y -= row_height

    y -= 3 * mm
    pdf.setFillColor(HexColor("#475569"))
    pdf.setFont("Helvetica", 7.5)
    footer = "Raport pogladowy generowany automatycznie z aktualnej analizy WLR."
    pdf.drawString(16 * mm, 12 * mm, footer)

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _safe_report_name(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char in ("-", "_") else "-" for char in value)
    sanitized = sanitized.strip("-_")
    return sanitized or "raport"


def _store_report_pdf(pdf_bytes: bytes, link_name: str, upload_id: str) -> tuple[Path, str]:
    base_name = _safe_report_name(link_name or upload_id)
    filename = f"raport_{base_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    file_path = REPORTS_DIR / filename
    file_path.write_bytes(pdf_bytes)
    return file_path, filename


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def api_analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    response, _parsed_request = await _run_analysis(request, trigger="api.analyze")
    return response


@app.post("/api/report.pdf")
async def api_report_pdf(request: AnalyzeRequest) -> StreamingResponse:
    response, parsed_request = await _run_analysis(request, trigger="api.report.pdf")
    source_summary = get_source_summary()
    pdf_bytes = await run_in_threadpool(_build_report_pdf, response, parsed_request, source_summary)
    _file_path, filename = await run_in_threadpool(
        _store_report_pdf,
        pdf_bytes,
        response.request.link_name or "",
        request.upload_id,
    )
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/report/{upload_id}.pdf")
async def api_report_pdf_get(
    upload_id: str,
    radius_km: float = 30.0,
    max_links: int = 500,
    operator_name: str = "Towerlink Poland Sp. z o.o.",
) -> FileResponse:
    request = AnalyzeRequest(
        upload_id=upload_id,
        radius_km=radius_km,
        max_links=max_links,
        operator_name=operator_name,
    )
    response, parsed_request = await _run_analysis(request, trigger="api.report.get")
    source_summary = get_source_summary()
    pdf_bytes = await run_in_threadpool(_build_report_pdf, response, parsed_request, source_summary)
    file_path, filename = await run_in_threadpool(
        _store_report_pdf,
        pdf_bytes,
        response.request.link_name or "",
        upload_id,
    )
    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=filename,
    )
