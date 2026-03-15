from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import analysis as analysis_engine  # noqa: E402
from wlr import WlrRequest, parse_wlr_file  # noqa: E402


DOC_FREQ_TOLERANCE_GHZ = 0.03


@dataclass(frozen=True)
class CasePair:
    key: str
    wlr_path: Path
    doc_path: Path


@dataclass(frozen=True)
class PreparedCase:
    key: str
    wlr_name: str
    doc_name: str
    request: WlrRequest
    expected_status: str


@dataclass(frozen=True)
class ParsedDocReference:
    decisions: dict[str, dict[float, str]]
    fallback_status: Optional[str]


def normalize_doc_stem(stem: str) -> str:
    if stem.endswith("_1"):
        return stem[:-2]
    return stem


def discover_pairs(tests_dir: Path) -> list[CasePair]:
    wlrs = sorted(tests_dir.glob("*.wlr"))
    docs = sorted(tests_dir.glob("*.doc"))
    doc_by_key = {normalize_doc_stem(doc.stem): doc for doc in docs}

    pairs: list[CasePair] = []
    for wlr in wlrs:
        doc = doc_by_key.get(wlr.stem)
        if not doc:
            continue
        pairs.append(CasePair(key=wlr.stem, wlr_path=wlr, doc_path=doc))
    return pairs


def parse_doc_reference(doc_path: Path) -> ParsedDocReference:
    lines = extract_doc_lines(doc_path)
    lines = [line.strip().lower() for line in lines if line.strip()]

    rows: list[tuple[str, float, str]] = []
    for i in range(len(lines) - 2):
        freq_token = lines[i]
        decision = lines[i + 1]
        direction = lines[i + 2]

        if decision not in {"tak", "nie"}:
            continue
        normalized_direction = normalize_direction(direction)
        if normalized_direction is None:
            continue

        freq_match = parse_frequency_token(freq_token)
        if freq_match is None:
            continue
        rows.append((normalized_direction, round(freq_match, 6), decision))

    decisions: dict[str, dict[float, list[str]]] = {}
    for direction, freq_ghz, decision in rows:
        decisions.setdefault(direction, {}).setdefault(freq_ghz, []).append(decision)

    collapsed: dict[str, dict[float, str]] = {}
    for direction, freq_map in decisions.items():
        collapsed[direction] = {}
        for freq_ghz, votes in freq_map.items():
            yes = sum(1 for vote in votes if vote == "tak")
            no = sum(1 for vote in votes if vote == "nie")
            collapsed[direction][freq_ghz] = "tak" if yes >= no else "nie"
    fallback_status = infer_fallback_doc_status(lines)
    return ParsedDocReference(decisions=collapsed, fallback_status=fallback_status)


def extract_doc_lines(doc_path: Path) -> list[str]:
    if not is_compound_doc(doc_path) and zipfile.is_zipfile(doc_path):
        lines = extract_docx_lines(doc_path)
        if lines:
            return lines

    merged: list[str] = []
    for cmd in (["strings", "-el", str(doc_path)], ["strings", "-n", "3", str(doc_path)]):
        try:
            output = subprocess.check_output(cmd, text=True, errors="ignore")
        except Exception:
            continue
        merged.extend(line.strip() for line in output.splitlines() if line.strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for line in merged:
        if line in seen:
            continue
        seen.add(line)
        deduped.append(line)
    return deduped


def is_compound_doc(doc_path: Path) -> bool:
    try:
        header = doc_path.read_bytes()[:8]
    except OSError:
        return False
    return header == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def extract_docx_lines(doc_path: Path) -> list[str]:
    wanted = (
        "word/document.xml",
        "word/header1.xml",
        "word/header2.xml",
        "word/footer1.xml",
        "word/footer2.xml",
    )
    pieces: list[str] = []
    with zipfile.ZipFile(doc_path) as zf:
        for name in wanted:
            if name not in zf.namelist():
                continue
            try:
                xml_bytes = zf.read(name)
            except KeyError:
                continue
            pieces.extend(extract_text_pieces_from_openxml(xml_bytes))
            pieces.append("\n")
    return [piece for piece in pieces if piece]


def extract_text_pieces_from_openxml(xml_bytes: bytes) -> list[str]:
    pieces: list[str] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return pieces

    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "t":
            text = (node.text or "").strip()
            if text:
                pieces.append(text)
        elif tag in {"tr", "p", "br"}:
            pieces.append("\n")
    return pieces


def normalize_direction(direction: str) -> Optional[str]:
    compact = direction.lower().replace(" ", "")
    if compact in {"a->b", "a-b", "ab"}:
        return "a -> b"
    if compact in {"b->a", "b-a", "ba"}:
        return "b -> a"
    return None


def infer_fallback_doc_status(lines: list[str]) -> Optional[str]:
    has_tak = any(token == "tak" for token in lines)
    has_nie = any(token == "nie" for token in lines)
    if has_tak and not has_nie:
        return "ACCEPTED"
    if has_nie and not has_tak:
        return "REJECTED"
    if has_tak and has_nie:
        return "REJECTED"

    has_ab = any("a -> b" in token for token in lines)
    has_ba = any("b -> a" in token for token in lines)
    has_freq = any(parse_frequency_token(token) is not None for token in lines)
    if has_ab and has_ba and has_freq:
        return "ACCEPTED"
    return None


def parse_frequency_token(token: str) -> Optional[float]:
    normalized = token.strip().replace(" ", "")
    if normalized.endswith("ghz"):
        normalized = normalized[:-3]
    normalized = normalized.replace(",", ".")
    parts = normalized.split(".")
    if len(parts) != 2:
        return None
    if not parts[0].isdigit() or not parts[1].isdigit():
        return None
    try:
        return float(f"{parts[0]}.{parts[1]}")
    except ValueError:
        return None


def nearest_decision(
    decisions: dict[str, dict[float, str]],
    direction: str,
    freq_ghz: Optional[float],
) -> Optional[str]:
    if freq_ghz is None:
        return None
    direction_map = decisions.get(direction) or {}
    if not direction_map:
        return None

    best_decision: Optional[str] = None
    best_delta = 999.0
    for known_freq_ghz, decision in direction_map.items():
        delta = abs(known_freq_ghz - freq_ghz)
        if delta < best_delta:
            best_delta = delta
            best_decision = decision
    if best_delta <= DOC_FREQ_TOLERANCE_GHZ:
        return best_decision
    return None


def expected_status_from_doc(
    parsed_doc: ParsedDocReference,
    freq_ab_ghz: Optional[float],
    freq_ba_ghz: Optional[float],
) -> Optional[str]:
    ab = nearest_decision(parsed_doc.decisions, "a -> b", freq_ab_ghz)
    ba = nearest_decision(parsed_doc.decisions, "b -> a", freq_ba_ghz)
    if ab is None or ba is None:
        return parsed_doc.fallback_status
    if ab == "tak" and ba == "tak":
        return "ACCEPTED"
    return "REJECTED"


def requested_assessment_status(
    request,
    analysis_result: analysis_engine.AnalysisResult,
) -> Optional[str]:
    preferred_pol = request.requested_polarization if request.requested_polarization in {"H", "V"} else None

    for assessment in analysis_result.channel_assessments:
        if assessment.candidate.channel_ab != request.channel_ab:
            continue
        if assessment.candidate.channel_ba != request.channel_ba:
            continue
        if preferred_pol and assessment.candidate.polarization != preferred_pol:
            continue
        return assessment.status

    if request.freq_ab_ghz is None or request.freq_ba_ghz is None:
        return None

    best_status: Optional[str] = None
    best_delta = 999.0
    for assessment in analysis_result.channel_assessments:
        if preferred_pol and assessment.candidate.polarization != preferred_pol:
            continue
        direct_delta = abs(assessment.candidate.freq_ab_ghz - request.freq_ab_ghz) + abs(assessment.candidate.freq_ba_ghz - request.freq_ba_ghz)
        swapped_delta = abs(assessment.candidate.freq_ab_ghz - request.freq_ba_ghz) + abs(assessment.candidate.freq_ba_ghz - request.freq_ab_ghz)
        delta = min(direct_delta, swapped_delta)
        if delta < best_delta:
            best_delta = delta
            best_status = assessment.status

    return best_status


def prepare_cases(
    pairs: list[CasePair],
    doc_cache: dict[Path, ParsedDocReference],
    limit: Optional[int],
) -> tuple[list[PreparedCase], dict[str, int]]:
    prepared: list[PreparedCase] = []
    stats = {
        "pairs_seen": 0,
        "parse_failed": 0,
        "missing_expected": 0,
    }
    selected_pairs = pairs[:limit] if limit else pairs
    for pair in selected_pairs:
        stats["pairs_seen"] += 1
        try:
            request = parse_wlr_file(pair.wlr_path)
        except Exception:
            stats["parse_failed"] += 1
            continue

        if pair.doc_path not in doc_cache:
            try:
                doc_cache[pair.doc_path] = parse_doc_reference(pair.doc_path)
            except Exception:
                stats["missing_expected"] += 1
                continue

        expected_status = expected_status_from_doc(
            doc_cache[pair.doc_path],
            request.freq_ab_ghz,
            request.freq_ba_ghz,
        )
        if not expected_status:
            stats["missing_expected"] += 1
            continue

        prepared.append(
            PreparedCase(
                key=pair.key,
                wlr_name=pair.wlr_path.name,
                doc_name=pair.doc_path.name,
                request=request,
                expected_status=expected_status,
            )
        )
    return prepared, stats


def run_iteration(
    cases: list[PreparedCase],
    params: dict[str, float],
    max_links: int,
    progress_every: int,
) -> dict:
    old_values = {
        "MAX_ACCEPTED_DEGRADATION_DB": analysis_engine.MAX_ACCEPTED_DEGRADATION_DB,
        "MIN_ACCEPTED_CI_DB": analysis_engine.MIN_ACCEPTED_CI_DB,
        "MAX_CONDITIONAL_DEGRADATION_DB": analysis_engine.MAX_CONDITIONAL_DEGRADATION_DB,
        "MIN_CONDITIONAL_CI_DB": analysis_engine.MIN_CONDITIONAL_CI_DB,
        "MAX_CHANNEL_DELTA_FACTOR": analysis_engine.MAX_CHANNEL_DELTA_FACTOR,
    }

    for key, value in params.items():
        setattr(analysis_engine, key, value)

    started = time.time()
    compared = 0
    matched_heuristic = 0
    matched_strict = 0
    skipped = 0
    failed = 0
    mismatches: list[dict] = []

    for index, case in enumerate(cases, start=1):
        try:
            analysis_result = analysis_engine.analyze_wlr_request(
                case.request,
                max_links=max_links,
            )
            got_status = requested_assessment_status(case.request, analysis_result)
            if not got_status:
                skipped += 1
                continue

            expected_status = case.expected_status

            compared += 1

            heuristic_ok = (
                (expected_status == "ACCEPTED" and got_status == "ACCEPTED")
                or (expected_status == "REJECTED" and got_status != "ACCEPTED")
            )
            strict_ok = (expected_status == got_status)
            if heuristic_ok:
                matched_heuristic += 1
            if strict_ok:
                matched_strict += 1
            if not heuristic_ok and len(mismatches) < 30:
                mismatches.append(
                    {
                        "case": case.key,
                        "wlr": case.wlr_name,
                        "doc": case.doc_name,
                        "expected": expected_status,
                        "got": got_status,
                    }
                )

        except Exception as exc:  # noqa: BLE001
            failed += 1
            if len(mismatches) < 30:
                mismatches.append(
                    {
                        "case": case.key,
                        "wlr": case.wlr_name,
                        "doc": case.doc_name,
                        "error": str(exc),
                    }
                )

        if progress_every > 0 and index % progress_every == 0:
            print(
                f"[iter] done={index}/{len(cases)} compared={compared} "
                f"heur={matched_heuristic}/{max(compared, 1)} strict={matched_strict}/{max(compared, 1)}"
            )

    for key, value in old_values.items():
        setattr(analysis_engine, key, value)

    elapsed_sec = round(time.time() - started, 3)
    heuristic_accuracy = (matched_heuristic / compared) if compared else 0.0
    strict_accuracy = (matched_strict / compared) if compared else 0.0
    return {
        "params": params,
        "compared": compared,
        "skipped": skipped,
        "failed": failed,
        "matched_heuristic": matched_heuristic,
        "matched_strict": matched_strict,
        "heuristic_accuracy": heuristic_accuracy,
        "strict_accuracy": strict_accuracy,
        "elapsed_sec": elapsed_sec,
        "mismatches_sample": mismatches,
    }


def build_param_grid() -> list[dict[str, float]]:
    grid: list[dict[str, float]] = []
    for max_acc_deg in (0.8, 1.0, 1.2):
        for min_acc_ci in (18.0, 20.0, 22.0):
            for max_delta in (1.5, 2.0):
                grid.append(
                    {
                        "MAX_ACCEPTED_DEGRADATION_DB": max_acc_deg,
                        "MIN_ACCEPTED_CI_DB": min_acc_ci,
                        "MAX_CONDITIONAL_DEGRADATION_DB": 3.0,
                        "MIN_CONDITIONAL_CI_DB": 10.0,
                        "MAX_CHANNEL_DELTA_FACTOR": max_delta,
                    }
                )
    return grid


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune analysis.py against UKE WLR-DOC pairs.")
    parser.add_argument("--tests-dir", default="testy")
    parser.add_argument("--logs-dir", default="logs")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-links", type=int, default=500)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--max-runs", type=int, default=0)
    args = parser.parse_args()

    tests_dir = Path(args.tests_dir).resolve()
    logs_dir = Path(args.logs_dir).resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)

    pairs = discover_pairs(tests_dir)
    if not pairs:
        raise SystemExit(f"Brak par WLR-DOC w {tests_dir}")

    run_id = time.strftime("%Y%m%d_%H%M%S")
    log_jsonl = logs_dir / f"uke_tuning_iterations_{run_id}.jsonl"
    log_summary = logs_dir / f"uke_tuning_summary_{run_id}.json"

    limit = args.limit if args.limit > 0 else None
    doc_cache: dict[Path, ParsedDocReference] = {}
    grid = build_param_grid()
    if args.max_runs > 0:
        grid = grid[:args.max_runs]
    prepared_cases, prep_stats = prepare_cases(
        pairs=pairs,
        doc_cache=doc_cache,
        limit=limit,
    )
    if not prepared_cases:
        raise SystemExit("Nie udało się przygotować żadnego porównywalnego case'u WLR-DOC")

    print(
        "[prepared] "
        f"pairs_seen={prep_stats['pairs_seen']} "
        f"prepared={len(prepared_cases)} "
        f"parse_failed={prep_stats['parse_failed']} "
        f"missing_expected={prep_stats['missing_expected']}"
    )

    best: Optional[dict] = None
    with log_jsonl.open("w", encoding="utf-8") as fh:
        for idx, params in enumerate(grid, start=1):
            print(f"[run {idx}/{len(grid)}] params={params}")
            result = run_iteration(
                cases=prepared_cases,
                params=params,
                max_links=args.max_links,
                progress_every=args.progress_every,
            )
            row = {
                "run_index": idx,
                "total_runs": len(grid),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                **result,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print(
                f"[run {idx}] compared={result['compared']} "
                f"heur={result['heuristic_accuracy']:.4f} strict={result['strict_accuracy']:.4f} "
                f"elapsed={result['elapsed_sec']}s"
            )
            if best is None:
                best = row
            else:
                if row["heuristic_accuracy"] > best["heuristic_accuracy"]:
                    best = row
                elif row["heuristic_accuracy"] == best["heuristic_accuracy"] and row["strict_accuracy"] > best["strict_accuracy"]:
                    best = row

    summary = {
        "run_id": run_id,
        "tests_dir": str(tests_dir),
        "pairs_total": len(pairs),
        "prepared_cases": len(prepared_cases),
        "prep_stats": prep_stats,
        "limit": limit,
        "max_links": args.max_links,
        "iterations": len(grid),
        "best": best,
        "log_jsonl": str(log_jsonl),
    }
    log_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
