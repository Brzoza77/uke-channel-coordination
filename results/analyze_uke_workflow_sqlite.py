from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


WORKFLOW_TABLES = [
    "czestotliwosc_kandydujaca",
    "dane_emc",
    "wynik_emc_lr",
    "decyzja",
    "przeslo_decyzji",
    "problem_kons",
    "proces_ap28",
    "antena_kons",
    "producent_kons",
    "nadajnik_kons",
    "charakterystyka_kons",
    "homologacja_kons",
    "sygnal",
    "rodzaje_modulacji",
    "fider",
    "plan_zakresu",
    "zakres",
    "przesla_do_modyfikacji",
    "sprawa",
    "osoba",
    "stan_przesla_tabela",
    "siec",
    "stacja_ns",
    "antena_sat",
]


def find_target_table(conn: sqlite3.Connection, source_db: str, source_table: str) -> str | None:
    row = conn.execute(
        """
        SELECT target_table
        FROM source_table_manifest
        WHERE source_db = ? AND source_table = ? AND status = 'ok'
        """,
        (source_db, source_table),
    ).fetchone()
    return row[0] if row else None


def row_count(conn: sqlite3.Connection, table_name: str) -> int:
    try:
        row = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row else 0


def table_columns(conn: sqlite3.Connection, source_db: str, source_table: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT source_column, target_column, sqlite_type
        FROM source_table_metadata
        WHERE source_db = ? AND source_table = ?
        ORDER BY source_column
        """,
        (source_db, source_table),
    ).fetchall()
    return [
        {"source": source, "target": target, "sqlite_type": sqlite_type}
        for source, target, sqlite_type in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Podsumowanie SQLite z workflow UKE po eksporcie z MDB.")
    parser.add_argument("--sqlite", default="data/uke_workflow.sqlite")
    parser.add_argument("--source-db", default="LR_Konsultacja_349")
    parser.add_argument("--out", default="logs/uke_workflow_sqlite_summary.json")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).resolve()
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(sqlite_path) as conn:
        summary: dict[str, object] = {
            "sqlite_path": str(sqlite_path),
            "source_db": args.source_db,
            "tables": {},
            "join_hints": {},
        }

        for source_suffix in WORKFLOW_TABLES:
            matching = conn.execute(
                """
                SELECT source_table, target_table, row_count
                FROM source_table_manifest
                WHERE source_db = ? AND target_table LIKE ?
                ORDER BY source_table
                """,
                (args.source_db, f"{args.source_db.lower()}__{source_suffix}%"),
            ).fetchall()
            for source_table, target_table, manifest_row_count in matching:
                summary["tables"][source_table] = {
                    "target_table": target_table,
                    "manifest_row_count": manifest_row_count,
                    "actual_row_count": row_count(conn, target_table),
                    "columns": table_columns(conn, args.source_db, source_table),
                }

        candidate_table = find_target_table(conn, args.source_db, "Czestotliwosc kandydujaca")
        result_table = find_target_table(conn, args.source_db, "Wynik EMC-LR")
        problem_table = find_target_table(conn, args.source_db, "problem_kons")
        if candidate_table and result_table:
            candidate_count = row_count(conn, candidate_table)
            result_count = row_count(conn, result_table)
            candidate_fk_count = conn.execute(
                f'SELECT COUNT(DISTINCT fkandydujaca_id) FROM "{candidate_table}"'
            ).fetchone()[0]
            result_fk_count = conn.execute(
                f'SELECT COUNT(DISTINCT fkandydujaca_b_id) FROM "{result_table}"'
            ).fetchone()[0]
            join_count = conn.execute(
                f'''
                SELECT COUNT(*)
                FROM "{candidate_table}" c
                JOIN "{result_table}" r
                  ON c.fkandydujaca_id = r.fkandydujaca_b_id
                '''
            ).fetchone()[0]
            summary["join_hints"]["candidate_to_result"] = {
                "candidate_rows": candidate_count,
                "result_rows": result_count,
                "candidate_distinct_fkandydujaca": candidate_fk_count,
                "result_distinct_fkandydujaca_b": result_fk_count,
                "join_rows": join_count,
            }

        if candidate_table and problem_table:
            join_count = conn.execute(
                f'''
                SELECT COUNT(*)
                FROM "{candidate_table}" c
                JOIN "{problem_table}" p
                  ON c.fkandydujaca_id = p.fkandydujaca_id
                '''
            ).fetchone()[0]
            summary["join_hints"]["candidate_to_problem_kons"] = {"join_rows": join_count}

    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
