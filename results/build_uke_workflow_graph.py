from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def load_tables(conn: sqlite3.Connection, source_db: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT source_table, target_table, row_count, primary_keys_json, columns_json
        FROM source_table_manifest
        WHERE source_db = ? AND status = 'ok'
        ORDER BY source_table
        """,
        (source_db,),
    ).fetchall()
    tables = []
    for source_table, target_table, row_count, primary_keys_json, columns_json in rows:
        tables.append(
            {
                "source_table": source_table,
                "target_table": target_table,
                "row_count": row_count,
                "primary_keys": json.loads(primary_keys_json or "[]"),
                "columns": json.loads(columns_json or "[]"),
            }
        )
    return tables


def infer_edges(tables: list[dict[str, object]]) -> list[dict[str, object]]:
    edges: list[dict[str, object]] = []
    index = {table["source_table"]: table for table in tables}

    def add_edge(left: str, right: str, rule: str, left_column: str, right_column: str, confidence: str) -> None:
        if left not in index or right not in index:
            return
        edge = {
            "from": left,
            "to": right,
            "rule": rule,
            "left_column": left_column,
            "right_column": right_column,
            "confidence": confidence,
        }
        if edge not in edges:
            edges.append(edge)

    # Explicit, high-confidence workflow joins.
    add_edge("Czestotliwosc kandydujaca", "Wynik EMC-LR", "explicit_fkandydujaca", "FKandydujaca#", "FKandydujaca_b#", "high")
    add_edge("Czestotliwosc kandydujaca", "problem_kons", "explicit_fkandydujaca", "FKandydujaca#", "FKandydujaca#", "high")
    add_edge("Czestotliwosc kandydujaca", "Dane_EMC", "explicit_przeslo", "Przęsło#", "Przeslo#", "high")
    add_edge("Wynik EMC-LR", "Dane_EMC", "explicit_interfering_span", "Przęsło_i#", "Przeslo#", "high")
    add_edge("problem_kons", "Dane_EMC", "explicit_przeslo", "Przeslo#", "Przeslo#", "high")
    add_edge("Przeslo decyzji", "DECYZJA", "explicit_decyzja", "Decyzja#", "Decyzja#", "high")
    add_edge("Przeslo decyzji", "Dane_EMC", "explicit_przeslo", "Przęsło#", "Przeslo#", "high")
    add_edge("Dane_EMC", "NADAJNIK", "likely_reference", "Nadajnik", "Nadajnik#", "medium")
    add_edge("Dane_EMC", "ANTENA", "likely_reference", "Antena_nad", "Antena#", "medium")
    add_edge("Dane_EMC", "ANTENA", "likely_reference", "Antena_odb", "Antena#", "medium")
    add_edge("Dane_EMC", "Nadajnik_kons", "consultation_reference", "Nadajnik", "Nadajnik#", "high")
    add_edge("Dane_EMC", "Antena_kons", "consultation_reference", "Antena_nad", "Antena#", "high")
    add_edge("Dane_EMC", "Antena_kons", "consultation_reference", "Antena_odb", "Antena#", "high")
    add_edge("Dane_EMC", "PRODUCENT", "likely_reference", "Producent_ant_N", "Producent#", "medium")
    add_edge("Dane_EMC", "PRODUCENT", "likely_reference", "Producent_ant_O", "Producent#", "medium")
    add_edge("Dane_EMC", "PRODUCENT", "likely_reference", "Producent_nad", "Producent#", "medium")
    add_edge("Dane_EMC", "Producent_kons", "consultation_reference", "Producent_ant_N", "Producent#", "high")
    add_edge("Dane_EMC", "Producent_kons", "consultation_reference", "Producent_ant_O", "Producent#", "high")
    add_edge("Dane_EMC", "Producent_kons", "consultation_reference", "Producent_nad", "Producent#", "high")
    add_edge("ANTENA", "PASMO ANTENY", "explicit_antenna_band", "Antena#", "Antena#", "high")
    add_edge("PASMO ANTENY", "CHARAKTERYSTYKA", "likely_band_pattern", "Pasmo anteny#", "Pasmo anteny#", "medium")
    add_edge("Antena_kons", "charakterystyka_kons", "consultation_pattern", "Antena#", "Antena#", "high")

    # Generic FK heuristics on identical source-column names.
    for left in tables:
        left_name = str(left["source_table"])
        left_columns = {col["source"] for col in left["columns"]}  # type: ignore[index]
        for right in tables:
            right_name = str(right["source_table"])
            if left_name == right_name:
                continue
            right_columns = {col["source"] for col in right["columns"]}  # type: ignore[index]
            common_fk = sorted(col for col in left_columns & right_columns if "#" in col)
            for col in common_fk:
                add_edge(left_name, right_name, "shared_hash_column", col, col, "low")

    return edges


def build_dot(tables: list[dict[str, object]], edges: list[dict[str, object]]) -> str:
    lines = [
        "digraph UKEWorkflow {",
        '  rankdir=LR;',
        '  graph [fontname="Helvetica"];',
        '  node [shape=box, style="rounded,filled", fillcolor="#f8fafc", color="#334155", fontname="Helvetica"];',
        '  edge [color="#64748b", fontname="Helvetica"];',
    ]
    for table in tables:
        label = f"{table['source_table']}\\nrows={table['row_count']}"
        node_id = str(table["source_table"]).replace('"', '\\"')
        lines.append(f'  "{node_id}" [label="{label}"];')
    for edge in edges:
        color = "#0f766e" if edge["confidence"] == "high" else "#a16207" if edge["confidence"] == "medium" else "#64748b"
        label = f"{edge['left_column']} -> {edge['right_column']}\\n{edge['rule']}\\n{edge['confidence']}"
        lines.append(
            f'  "{edge["from"]}" -> "{edge["to"]}" [label="{label}", color="{color}"];'
        )
    lines.append("}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Buduje graf relacji workflow UKE z wyeksportowanej SQLite.")
    parser.add_argument("--sqlite", default="data/uke_workflow.sqlite")
    parser.add_argument("--source-db", default="LR_Konsultacja_349")
    parser.add_argument("--out-json", default="logs/uke_workflow_graph.json")
    parser.add_argument("--out-dot", default="logs/uke_workflow_graph.dot")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).resolve()
    out_json = Path(args.out_json).resolve()
    out_dot = Path(args.out_dot).resolve()
    out_json.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(sqlite_path) as conn:
        tables = load_tables(conn, args.source_db)
        edges = infer_edges(tables)

    payload = {
        "sqlite_path": str(sqlite_path),
        "source_db": args.source_db,
        "table_count": len(tables),
        "edge_count": len(edges),
        "tables": tables,
        "edges": edges,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_dot.write_text(build_dot(tables, edges), encoding="utf-8")
    print(json.dumps({"out_json": str(out_json), "out_dot": str(out_dot), "edge_count": len(edges)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
