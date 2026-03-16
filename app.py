from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from schemas import (
    AnalyzeRequest,
    AnalyzeRequestSummary,
    AnalyzeResponse,
    AnalyzeSummary,
    ChannelRecommendation,
    ConflictItem,
    HealthResponse,
    MapFeatureCollection,
    SourceSummaryResponse,
    UploadWlrSummaryResponse,
)
from wlr import (
    WlrParseError,
    build_wlr_request_summary,
    parse_uploaded_wlr,
    parse_wlr_file,
)
from uke import get_pairing_summary, get_plan_summary, get_source_summary

from analysis import ENGINE_VERSION, analyze_wlr_request, build_uke_like_directional_candidate_rows


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = BASE_DIR / "uploads" / "wlr"
REPORTS_DIR = BASE_DIR / "reports"
INDEX_FILE = BASE_DIR / "index.html"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


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


async def _run_analysis(request: AnalyzeRequest) -> tuple[AnalyzeResponse, object]:
    try:
        parsed_request = await run_in_threadpool(parse_uploaded_wlr, request.upload_id, UPLOADS_DIR)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WlrParseError as exc:
        raise HTTPException(status_code=400, detail=f"Nie udało się sparsować WLR: {exc}") from exc
    except Exception as exc:
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
    reason_assessments = conditional_assessments + rejected_assessments if not accepted_assessments else []
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
            "channel_ab": requested_assessment.candidate.channel_ab if requested_assessment else None,
            "channel_ba": requested_assessment.candidate.channel_ba if requested_assessment else None,
            "candidate_polarization": requested_assessment.candidate.polarization if requested_assessment else None,
            "requested_distance": requested_record.requested_distance if requested_record else None,
            "uke_like_directional_rows": build_uke_like_directional_candidate_rows(requested_record) if requested_record else [],
            "top_conflicts_count": len(requested_assessment.conflicts) if requested_assessment else 0,
        } if requested_assessment else None,
        "requested_channel_top_conflicts": requested_channel_top_conflicts,
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
        recommendations=recommendations,
        conflicts=conflicts,
        debug=debug,
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


def _fit_text(pdf: canvas.Canvas, text: str, max_width: float, font_name: str, font_size: float) -> str:
    if stringWidth(text, font_name, font_size) <= max_width:
        return text
    ellipsis = "..."
    trimmed = text
    while trimmed and stringWidth(trimmed + ellipsis, font_name, font_size) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + ellipsis) if trimmed else ellipsis


def _draw_kv_row(pdf: canvas.Canvas, y: float, label: str, value: str, label_width: float, page_width: float) -> float:
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(16 * mm, y, label)
    pdf.setFont("Helvetica", 9)
    available_width = page_width - 16 * mm - label_width - 18 * mm
    pdf.drawString(16 * mm + label_width, y, _fit_text(pdf, value, available_width, "Helvetica", 9))
    return y - 5.8 * mm


def _build_report_pdf(response: AnalyzeResponse, parsed_request, source_summary: dict) -> bytes:
    buffer = BytesIO()
    page_width, page_height = A4
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(f"Raport koordynacji {response.request.upload_id}")
    pdf.setAuthor("UKE Channel Coordination")

    y = page_height - 16 * mm

    pdf.setFillColor(colors.HexColor("#0f172a"))
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(16 * mm, y, "Raport analizy kompatybilnosci lacza radiowego")
    y -= 7 * mm
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(colors.HexColor("#475569"))
    run_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pdf.drawString(16 * mm, y, f"Data wykonania: {run_stamp}")
    y -= 4 * mm
    pdf.drawString(16 * mm, y, f"Silnik: {ENGINE_VERSION}    Zrodlo: {source_summary['filename']}")
    y -= 8 * mm

    pdf.setStrokeColor(colors.HexColor("#cbd5e1"))
    pdf.setLineWidth(0.5)
    pdf.line(16 * mm, y, page_width - 16 * mm, y)
    y -= 7 * mm

    pdf.setFillColor(colors.HexColor("#0f172a"))
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

    y -= 2 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(16 * mm, y, "Rekomendowane kanaly")
    y -= 6.5 * mm

    table_x = 16 * mm
    table_width = page_width - 32 * mm
    col_widths = [12 * mm, 22 * mm, 22 * mm, 14 * mm, 24 * mm, 18 * mm, table_width - (12 + 22 + 22 + 14 + 24 + 18) * mm]
    headers = ["Lp.", "A->B", "B->A", "Pol.", "Status", "Score", "Uzasadnienie"]
    row_height = 7 * mm

    pdf.setFillColor(colors.HexColor("#e2e8f0"))
    pdf.rect(table_x, y - row_height + 1.2 * mm, table_width, row_height, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor("#0f172a"))
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
        pdf.setFillColor(colors.white if item.rank % 2 else colors.HexColor("#f8fafc"))
        pdf.rect(table_x, y - row_height + 1.2 * mm, table_width, row_height, fill=1, stroke=0)
        pdf.setFillColor(colors.HexColor("#0f172a"))
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
    pdf.setFillColor(colors.HexColor("#475569"))
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
    response, _parsed_request = await _run_analysis(request)
    return response


@app.post("/api/report.pdf")
async def api_report_pdf(request: AnalyzeRequest) -> StreamingResponse:
    response, parsed_request = await _run_analysis(request)
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
    response, parsed_request = await _run_analysis(request)
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
