#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_PATH = REPO_ROOT / ".vendor" / "accessparse"


def _load_parser():
    sys.path.insert(0, str(VENDOR_PATH))
    from access_parser import AccessParser  # type: ignore

    return AccessParser


def _columnar_to_rows(columnar: dict[str, list[Any]]) -> list[dict[str, Any]]:
    keys = list(columnar.keys())
    if not keys:
        return []
    row_count = len(columnar[keys[0]])
    rows: list[dict[str, Any]] = []
    for idx in range(row_count):
        row = {}
        for key in keys:
            values = columnar.get(key, [])
            row[key] = values[idx] if idx < len(values) else None
        rows.append(row)
    return rows


def _safe_parse_table(parser: Any, table_name: str) -> list[dict[str, Any]]:
    raw = parser.parse_table(table_name)
    if isinstance(raw, dict):
        return _columnar_to_rows(raw)
    if isinstance(raw, list):
        return raw
    raise TypeError(f"Unsupported table payload for {table_name}: {type(raw)!r}")


def _normalize_bytes(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    return value


def _collect_querydefs(msys_objects: list[dict[str, Any]], msys_queries: list[dict[str, Any]]) -> dict[str, Any]:
    querydefs = {
        row["Id"]: row
        for row in msys_objects
        if row.get("Type") == 5 and row.get("Id") is not None and row.get("Name")
    }
    rows_by_object_id: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in msys_queries:
        object_id = row.get("ObjectId")
        if object_id in querydefs:
            rows_by_object_id[object_id].append(row)

    query_summaries: list[dict[str, Any]] = []
    for object_id, meta in sorted(querydefs.items(), key=lambda item: str(item[1].get("Name", "")).lower()):
        rows = rows_by_object_id.get(object_id, [])
        attrs = Counter(row.get("Attribute") for row in rows)
        sources = []
        selected = []
        joins = []
        filters = []
        order_by = []
        other = []
        for row in rows:
            attribute = row.get("Attribute")
            name1 = row.get("Name1")
            name2 = row.get("Name2")
            expr = _normalize_bytes(row.get("Expression"))
            if attribute == 5 and name1:
                entry = {"source": name1}
                if name2:
                    entry["alias"] = name2
                sources.append(entry)
            elif attribute == 6 and expr:
                selected.append(str(expr))
            elif attribute == 7 and expr:
                joins.append(str(expr))
            elif attribute == 8 and expr:
                filters.append(str(expr))
            elif attribute == 11 and expr:
                order_by.append(str(expr))
            elif expr or name1 or name2:
                other.append(
                    {
                        "attribute": attribute,
                        "flag": row.get("Flag"),
                        "name1": name1,
                        "name2": name2,
                        "expression": expr,
                    }
                )

        query_summaries.append(
            {
                "object_id": object_id,
                "name": meta.get("Name"),
                "created_at": meta.get("DateCreate"),
                "updated_at": meta.get("DateUpdate"),
                "attribute_counts": dict(sorted(attrs.items(), key=lambda item: str(item[0]))),
                "sources": sources,
                "selected_fields": selected,
                "joins": joins,
                "filters": filters,
                "order_by": order_by,
                "other_rows": other[:20],
                "raw_row_count": len(rows),
            }
        )
    return {
        "querydef_count": len(query_summaries),
        "querydefs": query_summaries,
    }


def _collect_object_inventory(msys_objects: list[dict[str, Any]]) -> dict[str, Any]:
    type_counts = Counter(row.get("Type") for row in msys_objects)
    objects_by_type: dict[str, list[str]] = defaultdict(list)
    for row in msys_objects:
        objects_by_type[str(row.get("Type"))].append(str(row.get("Name")))
    return {
        "object_count": len(msys_objects),
        "type_counts": dict(sorted(type_counts.items(), key=lambda item: str(item[0]))),
        "objects_by_type": {
            object_type: sorted(names)
            for object_type, names in sorted(objects_by_type.items(), key=lambda item: item[0])
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory saved Access objects and querydefs from MDB.")
    parser.add_argument("--mdb", required=True, help="Path to MDB file")
    parser.add_argument("--out", required=True, help="Path to output JSON")
    args = parser.parse_args()

    AccessParser = _load_parser()
    db = AccessParser(args.mdb)

    msys_objects = _safe_parse_table(db, "MSysObjects")
    # access_parser omits system tables from its catalog. We patch just enough to read MSysQueries.
    db.catalog["MSysQueries"] = 4
    msys_queries = _safe_parse_table(db, "MSysQueries")

    payload = {
        "mdb": str(Path(args.mdb).resolve()),
        "inventory": _collect_object_inventory(msys_objects),
        "query_inventory": _collect_querydefs(msys_objects, msys_queries),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
