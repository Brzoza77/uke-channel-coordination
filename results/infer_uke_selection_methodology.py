from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path


def _rows_by_query(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    return [dict(row) for row in cur.execute(query, params).fetchall()]


def infer_selection(sqlite_path: Path, source_db: str) -> dict:
    source_prefix = source_db.lower()
    cand_table = f"{source_prefix}__czestotliwosc_kandydujaca"
    emc_table = f"{source_prefix}__dane_emc"
    wynik_table = f"{source_prefix}__wynik_emc_lr"
    pd_table = f"{source_prefix}__przeslo_decyzji"
    pzp_table = f"{source_prefix}__przeslo_zakres_plan"

    conn = sqlite3.connect(str(sqlite_path))
    try:
        candidates = _rows_by_query(conn, f'SELECT * FROM "{cand_table}" ORDER BY fkandydujaca_id')
        emc_rows = _rows_by_query(conn, f'SELECT * FROM "{emc_table}" ORDER BY przeslo_id')
        wynik_rows = _rows_by_query(
            conn,
            f'SELECT * FROM "{wynik_table}" ORDER BY fkandydujaca_b_id, prz_s_o_i_id',
        )
        emc_by_span = {row["przeslo_id"]: row for row in emc_rows}
        wyniki_by_candidate: dict[int, list[dict]] = defaultdict(list)
        for row in wynik_rows:
            wyniki_by_candidate[row["fkandydujaca_b_id"]].append(row)

        grouped_variants: dict[tuple, list[dict]] = defaultdict(list)
        for row in candidates:
            key = (
                row["numer_przesla"],
                row["numer_pary_f"],
                row["polaryzacja"],
                row["plan"],
            )
            grouped_variants[key].append(row)

        variants: list[dict] = []
        consultation_spans: set[int] = set()
        for key, rows in sorted(grouped_variants.items()):
            directional_rows = sorted(rows, key=lambda item: item["kod_nadawczej"])
            row_a = next((row for row in directional_rows if row["kod_nadawczej"] == "A"), None)
            row_b = next((row for row in directional_rows if row["kod_nadawczej"] == "B"), None)
            for row in directional_rows:
                consultation_spans.add(row["prz_s_o_id"])
            pair_margins = []
            pair_error_codes = []
            pair_error_texts = []
            for row in directional_rows:
                for wynik in wyniki_by_candidate.get(row["fkandydujaca_id"], []):
                    if wynik.get("margines_b_i") is not None:
                        pair_margins.append(wynik["margines_b_i"])
                    if wynik.get("margines_i_b") not in (None, ""):
                        try:
                            pair_margins.append(float(wynik["margines_i_b"]))
                        except (TypeError, ValueError):
                            pass
                    if wynik.get("blad_obliczen") is not None:
                        pair_error_codes.append(wynik["blad_obliczen"])
                    if wynik.get("opis_bledu"):
                        pair_error_texts.append(wynik["opis_bledu"])

            variants.append(
                {
                    "variant_key": {
                        "numer_przesla": key[0],
                        "numer_pary_f": key[1],
                        "polaryzacja": key[2],
                        "plan": key[3],
                    },
                    "directional_candidates": [
                        {
                            "fkandydujaca_id": row["fkandydujaca_id"],
                            "kod_nadawczej": row["kod_nadawczej"],
                            "channel_number": row["numer_czestotliwosci"],
                            "frequency_ghz": row["wartosc_czestotliwosci"],
                            "status": row["status"],
                            "margnad": row["margnad"],
                            "margodb": row["margodb"],
                            "przeslo_id": row["prz_s_o_id"],
                            "emc_input": emc_by_span.get(row["prz_s_o_id"]),
                            "wynik_emc_lr": wyniki_by_candidate.get(row["fkandydujaca_id"], []),
                        }
                        for row in directional_rows
                    ],
                    "paired_channel": {
                        "channel_ab": row_b["numer_czestotliwosci"] if row_b else None,
                        "channel_ba": row_a["numer_czestotliwosci"] if row_a else None,
                        "freq_ab_ghz": row_b["wartosc_czestotliwosci"] if row_b else None,
                        "freq_ba_ghz": row_a["wartosc_czestotliwosci"] if row_a else None,
                    },
                    "aggregate": {
                        "status_values": sorted({row["status"] for row in directional_rows}),
                        "worst_pair_margin_db": min(pair_margins) if pair_margins else None,
                        "error_codes": sorted(set(pair_error_codes)),
                        "error_texts": sorted(set(pair_error_texts)),
                    },
                }
            )

        consultation_spans_sorted = sorted(consultation_spans)
        linked_to_admin = _rows_by_query(
            conn,
            f'SELECT * FROM "{pd_table}" WHERE prz_s_o_id IN ({",".join("?" for _ in consultation_spans_sorted)})',
            tuple(consultation_spans_sorted),
        ) if consultation_spans_sorted else []
        linked_to_plan = _rows_by_query(
            conn,
            f'SELECT * FROM "{pzp_table}" WHERE prz_s_o_id IN ({",".join("?" for _ in consultation_spans_sorted)})',
            tuple(consultation_spans_sorted),
        ) if consultation_spans_sorted else []

        status_values = sorted({row["status"] for row in candidates})
        methodology = {
            "observations": [
                "UKE tworzy kandydatów kierunkowych w tabeli Czestotliwosc kandydujaca; jeden wiersz odpowiada jednemu kierunkowi nadawczemu.",
                "Duplex kanału powstaje przez sparowanie dwóch rekordów: kod_nadawczej=A oraz kod_nadawczej=B dla tej samej pary częstotliwości i polaryzacji.",
                "Wynik EMC-LR przechowuje wynik per kandydat kierunkowy i para zakłócająca; z tej tabeli da się odtworzyć minimalny margines dla danego wariantu.",
                "Dane_EMC dostarczają pełne wejście obliczeniowe dla danego przęsła i są bezpośrednio powiązane z kandydatem po Przeslo#.",
                "Dla tego konsultacyjnego przebiegu przęsła nie są obecne w Przeslo decyzji ani Przeslo-zakres-plan, więc wybór kanału odbywa się przed warstwą administracyjną.",
            ],
            "inferred_selection_rules": [
                "1. Wygeneruj wszystkie kandydaty kierunkowe dla obu kierunków i obu polaryzacji.",
                "2. Sparuj kandydaty A/B w wariant duplexowy po numerze pary częstotliwości i polaryzacji.",
                "3. Dla każdego kierunku oblicz margines wynikowy na podstawie Wynik EMC-LR oraz pola MargNad/MargOdb.",
                "4. Wyznacz status wariantu duplexowego z najgorszego kierunkowego marginesu oraz ewentualnych błędów obliczeń/problemów konsultacyjnych.",
                "5. Wybierz kanał końcowy przez sortowanie: status dopuszczalności, następnie najwyższy najgorszy margines duplexowy, następnie mniejsza liczba konfliktów współkanałowych i czerwonych, a dopiero później tie-breakery użytkowe.",
            ],
        }

        return {
            "sqlite_path": str(sqlite_path),
            "source_db": source_db,
            "candidate_row_count": len(candidates),
            "emc_row_count": len(emc_rows),
            "wynik_row_count": len(wynik_rows),
            "status_values": status_values,
            "consultation_spans": consultation_spans_sorted,
            "admin_links": {
                "przeslo_decyzji_rows": len(linked_to_admin),
                "przeslo_zakres_plan_rows": len(linked_to_plan),
            },
            "variants": variants,
            "methodology": methodology,
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Infer UKE final channel selection methodology from workflow SQLite")
    parser.add_argument("--sqlite", required=True, help="Path to workflow SQLite")
    parser.add_argument("--source-db", default="LR_Konsultacja_349", help="Source DB prefix")
    parser.add_argument("--out", required=True, help="Output JSON path")
    args = parser.parse_args()

    result = infer_selection(Path(args.sqlite), args.source_db)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
