from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from analysis import ChannelAssessment, ConflictAssessment, analyze_wlr_request  # noqa: E402
from wlr import parse_wlr_file  # noqa: E402


def _import_sharepoint2text():
    try:
        import sharepoint2text  # type: ignore

        return sharepoint2text
    except Exception:
        temp_target = Path("/tmp/docparse_pkg")
        if temp_target.exists():
            sys.path.insert(0, str(temp_target))
            import sharepoint2text  # type: ignore

            return sharepoint2text
        raise RuntimeError(
            "Brak modułu sharepoint2text. Zainstaluj go albo przygotuj /tmp/docparse_pkg."
        )


NUM_RE = r"\d+(?:,\d+)?(?:E[-+]?\d+)?"
HEADER_RE = re.compile(
    r"Stacja Tx ->Stacja Rx Symbol planu Numer kanału Częstotliwość \[GHz\] Polaryzacja "
    r"(?P<direction>A -> B|B -> A) (?P<plan>\S+) (?P<channel>\S+) (?P<freq>\d+,\d+) (?P<pol>[HV]) "
)
ROW_RE = re.compile(
    rf"(?P<degradation>{NUM_RE}) "
    rf"(?P<station>.*?) "
    rf"(?P<freq>{NUM_RE}) "
    rf"(?P<pol>[HV]) "
    rf"(?P<bw>{NUM_RE}) "
    rf"(?P<equipment>.*?) "
    rf"(?P<distance>{NUM_RE}) "
    rf"(?P<status>(?:Doręczono|Do odbioru)[^\d]*?) "
    rf"(?P<permit>\d+\.\d{{4}}\.\d+) "
    rf"(?P<operator>.*?(?:Sp\. z o\.o\.|S\.A\.))"
    rf"(?= {NUM_RE}|$)",
    re.S,
)


@dataclass(frozen=True)
class UkeRow:
    section: str
    direction: str
    plan_symbol: str
    channel: str
    freq_ghz: float
    polarization: str
    uke_link_degradation_db: float
    station_name: str
    interferer_freq_ghz: float
    interferer_polarization: str
    interferer_bw_mhz: float
    interferer_equipment: str
    distance_km: float
    permit_number: str
    operator_name: str


def parse_number(value: str) -> float:
    return float(value.replace(",", "."))


def sum_degradation_db(values: list[float]) -> float:
    ratios_sum = 0.0
    for value in values:
        ratios_sum += max(0.0, 10.0 ** (value / 10.0) - 1.0)
    return 10.0 * math.log10(1.0 + ratios_sum) if ratios_sum > 0.0 else 0.0


def extract_doc_text(doc_path: Path) -> str:
    try:
        sharepoint2text = _import_sharepoint2text()
    except Exception:
        sharepoint2text = None

    if sharepoint2text is not None:
        with doc_path.open("rb") as fh:
            contents = list(sharepoint2text.read_doc(fh, path=str(doc_path)))
        if not contents:
            raise RuntimeError(f"Nie udało się odczytać DOC: {doc_path}")
        text = contents[0].main_text
    else:
        text = "\n".join(extract_doc_lines(doc_path))

    start = text.find("\nPrzęsło\nStacja Tx ->Stacja Rx Symbol planu Numer kanału Częstotliwość [GHz] Polaryzacja")
    return text[start + 1 :] if start >= 0 else text


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


def parse_doc_rows(doc_path: Path) -> list[UkeRow]:
    text = extract_doc_text(doc_path)
    blocks = [block for block in text.split("\n\nPrzęsło\n") if block.strip()]
    rows: list[UkeRow] = []
    for block in blocks:
        header = HEADER_RE.search(block)
        if not header:
            continue
        info = header.groupdict()
        sat_marker = "Zakłócenia w środowisku naziemnych stacji satelitarnych"
        incoming_marker = "Degradacja mocy prog. odb. [dB] Zakłócana stacja odbiorcza"
        outgoing_marker = "Degradacja mocy prog. odb. [dB] Zakłócająca stacja nadawcza"
        incoming_start = block.find(incoming_marker)
        outgoing_start = block.find(outgoing_marker)
        sat_start = block.find(sat_marker)
        if incoming_start < 0 or outgoing_start < 0 or sat_start < 0:
            continue
        incoming_text = block[incoming_start:outgoing_start]
        outgoing_text = block[outgoing_start:sat_start]

        for section_name, section_text in (("incoming", incoming_text), ("outgoing", outgoing_text)):
            for match in ROW_RE.finditer(section_text):
                data = match.groupdict()
                rows.append(
                    UkeRow(
                        section=section_name,
                        direction=info["direction"],
                        plan_symbol=info["plan"],
                        channel=info["channel"],
                        freq_ghz=parse_number(info["freq"]),
                        polarization=info["pol"],
                        uke_link_degradation_db=parse_number(data["degradation"]),
                        station_name=" ".join(data["station"].split()),
                        interferer_freq_ghz=parse_number(data["freq"]),
                        interferer_polarization=data["pol"],
                        interferer_bw_mhz=parse_number(data["bw"]),
                        interferer_equipment=" ".join(data["equipment"].split()),
                        distance_km=parse_number(data["distance"]),
                        permit_number=data["permit"],
                        operator_name=" ".join(data["operator"].split()),
                    )
                )
    return rows


def find_assessment(
    assessments: list[ChannelAssessment],
    direction: str,
    channel: str,
    freq_ghz: float,
    polarization: str,
) -> Optional[ChannelAssessment]:
    candidates: list[tuple[float, ChannelAssessment]] = []
    for assessment in assessments:
        candidate = assessment.candidate
        if candidate.polarization != polarization:
            continue
        if direction == "A -> B":
            if candidate.channel_ab != channel:
                continue
            delta = abs(candidate.freq_ab_ghz - freq_ghz)
        else:
            if candidate.channel_ba != channel:
                continue
            delta = abs(candidate.freq_ba_ghz - freq_ghz)
        candidates.append((delta, assessment))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def match_engine_conflict(conflicts: list[ConflictAssessment], permit_number: str) -> Optional[ConflictAssessment]:
    matches = [conflict for conflict in conflicts if conflict.permit_number == permit_number]
    if not matches:
        return None
    matches.sort(
        key=lambda conflict: max(
            conflict.estimated_degradation_victim_db or 0.0,
            conflict.estimated_degradation_aggressor_db or 0.0,
        ),
        reverse=True,
    )
    return matches[0]


def build_comparison_rows(doc_rows: list[UkeRow], assessments: list[ChannelAssessment]) -> list[dict]:
    grouped_totals: dict[tuple[str, str, str, float, str], dict[str, float]] = {}
    for row in doc_rows:
        key = (row.section, row.direction, row.channel, row.freq_ghz, row.polarization)
        grouped_totals.setdefault(key, {"uke_rows": []})
        grouped_totals[key]["uke_rows"].append(row.uke_link_degradation_db)

    comparison: list[dict] = []
    for row in doc_rows:
        assessment = find_assessment(
            assessments=assessments,
            direction=row.direction,
            channel=row.channel,
            freq_ghz=row.freq_ghz,
            polarization=row.polarization,
        )
        engine_conflict = match_engine_conflict(assessment.conflicts, row.permit_number) if assessment else None
        key = (row.section, row.direction, row.channel, row.freq_ghz, row.polarization)
        uke_total = sum_degradation_db(grouped_totals[key]["uke_rows"])
        engine_total_victim = sum_degradation_db(
            [conflict.estimated_degradation_victim_db or 0.0 for conflict in (assessment.conflicts if assessment else [])]
        )
        engine_total_aggressor = sum_degradation_db(
            [conflict.estimated_degradation_aggressor_db or 0.0 for conflict in (assessment.conflicts if assessment else [])]
        )
        comparison.append(
            {
                "section": row.section,
                "direction": row.direction,
                "plan_symbol": row.plan_symbol,
                "channel": row.channel,
                "freq_ghz": row.freq_ghz,
                "polarization": row.polarization,
                "uke_total_degradation_db": round(uke_total, 6),
                "uke_link_permit": row.permit_number,
                "uke_link_operator": row.operator_name,
                "uke_link_station": row.station_name,
                "uke_link_degradation_db": row.uke_link_degradation_db,
                "engine_assessment_status": assessment.status if assessment else None,
                "engine_status_ab": assessment.status_ab if assessment else None,
                "engine_status_ba": assessment.status_ba if assessment else None,
                "engine_candidate_channel_ab": assessment.candidate.channel_ab if assessment else None,
                "engine_candidate_channel_ba": assessment.candidate.channel_ba if assessment else None,
                "engine_total_victim_db": round(engine_total_victim, 6),
                "engine_total_aggressor_db": round(engine_total_aggressor, 6),
                "engine_conflict_found": engine_conflict is not None,
                "engine_conflict_link_id": engine_conflict.link_id if engine_conflict else None,
                "engine_conflict_operator": engine_conflict.operator_name if engine_conflict else None,
                "engine_conflict_permit": engine_conflict.permit_number if engine_conflict else None,
                "engine_victim_db": round(engine_conflict.estimated_degradation_victim_db or 0.0, 6) if engine_conflict else None,
                "engine_aggressor_db": round(engine_conflict.estimated_degradation_aggressor_db or 0.0, 6) if engine_conflict else None,
                "engine_ci_victim_db": round(engine_conflict.estimated_ci_victim_db or 0.0, 6) if engine_conflict else None,
                "engine_ci_aggressor_db": round(engine_conflict.estimated_ci_aggressor_db or 0.0, 6) if engine_conflict else None,
                "engine_effective_freq_delta_mhz": round(engine_conflict.effective_freq_delta_mhz or 0.0, 6) if engine_conflict else None,
                "engine_overlap_ab_ratio": round(engine_conflict.overlap_ab_ratio or 0.0, 6) if engine_conflict else None,
                "engine_overlap_ba_ratio": round(engine_conflict.overlap_ba_ratio or 0.0, 6) if engine_conflict else None,
            }
        )
    return comparison


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise RuntimeError("Brak danych do zapisu CSV")
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build comparison table for one UKE WLR-DOC case.")
    parser.add_argument("--wlr", required=True)
    parser.add_argument("--doc", required=True)
    parser.add_argument("--out-dir", default="logs")
    args = parser.parse_args()

    wlr_path = Path(args.wlr).resolve()
    doc_path = Path(args.doc).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    request = parse_wlr_file(wlr_path)
    analysis_result = analyze_wlr_request(request)
    doc_rows = parse_doc_rows(doc_path)
    comparison_rows = build_comparison_rows(doc_rows, analysis_result.channel_assessments)

    stem = wlr_path.stem
    csv_path = out_dir / f"{stem}_uke_engine_comparison.csv"
    json_path = out_dir / f"{stem}_uke_engine_comparison_summary.json"
    write_csv(csv_path, comparison_rows)

    summary = {
        "case": stem,
        "rows_total": len(comparison_rows),
        "variants_total": len(
            {
                (row["section"], row["direction"], row["channel"], row["freq_ghz"], row["polarization"])
                for row in comparison_rows
            }
        ),
        "sections": {
            "incoming": sum(1 for row in comparison_rows if row["section"] == "incoming"),
            "outgoing": sum(1 for row in comparison_rows if row["section"] == "outgoing"),
        },
        "csv_path": str(csv_path),
    }
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
