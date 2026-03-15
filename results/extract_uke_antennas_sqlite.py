from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
VENDOR_PATH = ROOT_DIR / ".vendor" / "accessparse"
if VENDOR_PATH.exists():
    sys.path.insert(0, str(VENDOR_PATH))

from access_parser import AccessParser  # type: ignore


DEFAULT_BANDS_GHZ = (23.0, 38.0, 80.0)


def _row_count(parsed: dict[str, list[Any]]) -> int:
    return len(next(iter(parsed.values()))) if parsed else 0


def _iter_rows(parsed: dict[str, list[Any]]):
    columns = list(parsed.keys())
    row_count = _row_count(parsed)
    for index in range(row_count):
        yield {column: parsed[column][index] for column in columns}


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS producers (
            producer_id INTEGER PRIMARY KEY,
            producer_name TEXT NOT NULL,
            country TEXT
        );
        CREATE TABLE IF NOT EXISTS antennas (
            antenna_id INTEGER PRIMARY KEY,
            producer_id INTEGER,
            antenna_type TEXT,
            antenna_kind TEXT,
            diameter_m REAL,
            omnidirectional INTEGER,
            source_code INTEGER,
            correctness_code INTEGER,
            FOREIGN KEY (producer_id) REFERENCES producers(producer_id)
        );
        CREATE TABLE IF NOT EXISTS antenna_bands (
            band_id INTEGER PRIMARY KEY,
            antenna_id INTEGER NOT NULL,
            freq_low_ghz REAL,
            freq_high_ghz REAL,
            beamwidth_deg REAL,
            gain_dbi REAL,
            symmetric_pattern INTEGER,
            pattern_source_code INTEGER,
            itu_symbol TEXT,
            correctness_code INTEGER,
            verified_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (antenna_id) REFERENCES antennas(antenna_id)
        );
        CREATE TABLE IF NOT EXISTS pattern_points (
            pattern_id INTEGER PRIMARY KEY,
            band_id INTEGER NOT NULL,
            polarization_layout INTEGER,
            azimuth_deg REAL NOT NULL,
            attenuation_db REAL NOT NULL,
            verified_at TEXT,
            FOREIGN KEY (band_id) REFERENCES antenna_bands(band_id)
        );
        CREATE INDEX IF NOT EXISTS idx_antennas_type ON antennas(antenna_type);
        CREATE INDEX IF NOT EXISTS idx_antenna_bands_antenna ON antenna_bands(antenna_id);
        CREATE INDEX IF NOT EXISTS idx_pattern_points_band ON pattern_points(band_id);
        CREATE TABLE IF NOT EXISTS extraction_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_mdb TEXT NOT NULL,
            target_bands_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()


def export_selected_bands(db_path: Path, sqlite_path: Path, target_bands_ghz: list[float]) -> dict[str, Any]:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    db = AccessParser(str(db_path))

    with sqlite3.connect(sqlite_path) as conn:
        ensure_schema(conn)

        producers = db.get_table("PRODUCENT").parse()
        producer_rows = list(_iter_rows(producers))
        conn.executemany(
            """
            INSERT INTO producers (producer_id, producer_name, country)
            VALUES (?, ?, ?)
            ON CONFLICT(producer_id) DO UPDATE SET
                producer_name=excluded.producer_name,
                country=excluded.country
            """,
            [
                (
                    row["Producent#"],
                    row.get("Nazwa producenta"),
                    row.get("Kraj"),
                )
                for row in producer_rows
            ],
        )

        antennas = db.get_table("ANTENA").parse()
        antenna_rows = list(_iter_rows(antennas))
        conn.executemany(
            """
            INSERT INTO antennas (
                antenna_id, producer_id, antenna_type, antenna_kind, diameter_m,
                omnidirectional, source_code, correctness_code
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(antenna_id) DO UPDATE SET
                producer_id=excluded.producer_id,
                antenna_type=excluded.antenna_type,
                antenna_kind=excluded.antenna_kind,
                diameter_m=excluded.diameter_m,
                omnidirectional=excluded.omnidirectional,
                source_code=excluded.source_code,
                correctness_code=excluded.correctness_code
            """,
            [
                (
                    row["Antena#"],
                    row.get("Producent#"),
                    row.get("Typ anteny"),
                    row.get("Rodzaj anteny"),
                    row.get("Średnica anteny"),
                    1 if row.get("Charakterystyka dookolna") else 0,
                    row.get("Pochodzenie danych"),
                    row.get("Poprawna"),
                )
                for row in antenna_rows
            ],
        )

        bands = db.get_table("PASMO ANTENY").parse()
        selected_band_rows: list[dict[str, Any]] = []
        for row in _iter_rows(bands):
            low = row.get("f dolna anteny")
            high = row.get("f górna anteny")
            if low is None or high is None:
                continue
            if not any(float(low) <= band <= float(high) for band in target_bands_ghz):
                continue
            selected_band_rows.append(row)

        conn.executemany(
            """
            INSERT INTO antenna_bands (
                band_id, antenna_id, freq_low_ghz, freq_high_ghz, beamwidth_deg, gain_dbi,
                symmetric_pattern, pattern_source_code, itu_symbol, correctness_code,
                verified_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(band_id) DO UPDATE SET
                antenna_id=excluded.antenna_id,
                freq_low_ghz=excluded.freq_low_ghz,
                freq_high_ghz=excluded.freq_high_ghz,
                beamwidth_deg=excluded.beamwidth_deg,
                gain_dbi=excluded.gain_dbi,
                symmetric_pattern=excluded.symmetric_pattern,
                pattern_source_code=excluded.pattern_source_code,
                itu_symbol=excluded.itu_symbol,
                correctness_code=excluded.correctness_code,
                verified_at=excluded.verified_at,
                updated_at=excluded.updated_at
            """,
            [
                (
                    row["Pasmo anteny#"],
                    row["Antena#"],
                    row.get("f dolna anteny"),
                    row.get("f górna anteny"),
                    row.get("Szerokość wiązki"),
                    row.get("Zysk energetyczny"),
                    row.get("Charakterystyka symetryczna"),
                    row.get("Zrodlo charakterystyki"),
                    row.get("Symbol UIT"),
                    row.get("Poprawna"),
                    row.get("Data weryfikacji"),
                    row.get("Data aktualizacji"),
                )
                for row in selected_band_rows
            ],
        )

        selected_band_ids = {row["Pasmo anteny#"] for row in selected_band_rows}
        patterns = db.get_table("CHARAKTERYSTYKA").parse()
        selected_pattern_rows = [
            row
            for row in _iter_rows(patterns)
            if row.get("Pasmo anteny#") in selected_band_ids
        ]
        conn.executemany(
            """
            INSERT INTO pattern_points (
                pattern_id, band_id, polarization_layout, azimuth_deg, attenuation_db, verified_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(pattern_id) DO UPDATE SET
                band_id=excluded.band_id,
                polarization_layout=excluded.polarization_layout,
                azimuth_deg=excluded.azimuth_deg,
                attenuation_db=excluded.attenuation_db,
                verified_at=excluded.verified_at
            """,
            [
                (
                    row["Charakterystyka#"],
                    row["Pasmo anteny#"],
                    row.get("Układ polaryzacji"),
                    row.get("Kierunek promieniowania"),
                    row.get("Wytłumienie"),
                    row.get("Data weryfikacji"),
                )
                for row in selected_pattern_rows
            ],
        )

        summary = {
            "source_mdb": str(db_path),
            "sqlite_path": str(sqlite_path),
            "target_bands_ghz": target_bands_ghz,
            "producer_rows": len(producer_rows),
            "antenna_rows": len(antenna_rows),
            "selected_band_rows": len(selected_band_rows),
            "selected_pattern_rows": len(selected_pattern_rows),
        }
        conn.execute(
            """
            INSERT INTO extraction_runs (source_mdb, target_bands_json, summary_json)
            VALUES (?, ?, ?)
            """,
            (
                str(db_path),
                json.dumps(target_bands_ghz, ensure_ascii=False),
                json.dumps(summary, ensure_ascii=False),
            ),
        )
        conn.commit()
        return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract selected UKE antenna patterns from MDB to SQLite.")
    parser.add_argument("--mdb", default="LR_Konsultacja_349.mdb")
    parser.add_argument("--sqlite", default="data/antenna_catalog.sqlite")
    parser.add_argument("--bands-ghz", nargs="*", type=float, default=list(DEFAULT_BANDS_GHZ))
    args = parser.parse_args()

    summary = export_selected_bands(
        db_path=Path(args.mdb).resolve(),
        sqlite_path=Path(args.sqlite).resolve(),
        target_bands_ghz=list(args.bands_ghz),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
