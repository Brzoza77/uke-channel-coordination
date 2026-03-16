#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / ".vendor" / "accessparse"))

from access_parser import AccessParser  # type: ignore


MDB_PATH = REPO_ROOT / "LR_Konsultacja_349.mdb"
TARGET_STRINGS_PATH = REPO_ROOT / "logs" / "access_vba_target_strings_20260316.txt"
OUTPUT_PATH = REPO_ROOT / "logs" / "access_system_tables_and_state_flow_20260316.json"


TARGET_OBJECTS = {
    "Aktualizacja_bazy",
    "import_wnelw",
    "koordynacja_zagr",
    "Master",
    "Przylaczenie_baz",
    "Separator",
    "Usuwanie_ukrytych_operatorow",
    "Zadania_LR",
    "Zadania_LR_Tlumienie",
    "Zlecenie_zadania_do_serwera",
    "autoexec",
    "klepsydra_nie",
    "start",
    "Uaktualnienie bazy",
}


FLOW_MARKERS = [
    "statusfk = 1",
    "aktualizacja parametr",
    "w fkand",
    "Czestotliwosc kandydujaca",
    "filepk.Update",
    "ExportTx_przeslo",
    "ExportRx_przeslo",
    "wpisz_dane_koor",
    "kwalifikacja_koor",
    "Kwalifikacja_EMC",
    "Stan_wniosku_po_weryfikacji",
    "wstaw_status",
    "status_kand",
]


def load_db() -> AccessParser:
    return AccessParser(str(MDB_PATH))


def parse_system_tables(db: AccessParser) -> dict:
    msys = db.parse_table("MSysObjects")
    rows = [
        {
            "name": name,
            "id": obj_id,
            "type": obj_type,
            "flags": flags,
        }
        for name, obj_id, obj_type, flags in zip(
            msys.get("Name", []),
            msys.get("Id", []),
            msys.get("Type", []),
            msys.get("Flags", []),
        )
        if name in TARGET_OBJECTS
    ]

    ids_by_name = {row["name"]: row["id"] for row in rows}
    for required_name in (
        "MSysAccessObjects",
        "MSysNavPaneObjectIDs",
        "MSysNavPaneGroups",
        "MSysNavPaneGroupToObjects",
        "MSysNavPaneGroupCategories",
    ):
        ids_by_name[required_name] = next(
            obj_id
            for name, obj_id in zip(msys.get("Name", []), msys.get("Id", []))
            if name == required_name
        )
        db.catalog[required_name] = ids_by_name[required_name]

    nav = db.parse_table("MSysNavPaneObjectIDs")
    nav_rows = [
        {"id": obj_id, "name": name, "type": obj_type}
        for obj_id, name, obj_type in zip(
            nav.get("Id", []),
            nav.get("Name", []),
            nav.get("Type", []),
        )
        if name in TARGET_OBJECTS
    ]

    access_objects = db.parse_table("MSysAccessObjects")
    access_rows = []
    total_rows = len(access_objects.get("ID", []))
    for idx in range(total_rows):
        data = access_objects["Data"][idx]
        access_rows.append(
            {
                "id": access_objects["ID"][idx],
                "data_type": type(data).__name__,
                "data_len": len(data) if isinstance(data, (bytes, str)) else None,
            }
        )
    nonempty_rows = [row for row in access_rows if (row["data_len"] or 0) > 0]

    return {
        "msys_objects_target_rows": rows,
        "navpane_target_rows": nav_rows,
        "msys_access_objects_summary": {
            "row_count": total_rows,
            "nonempty_data_rows": len(nonempty_rows),
            "note": (
                "MSysAccessObjects is readable after injecting the correct Id from MSysObjects, "
                "but the parsed table currently exposes empty Data payloads for all rows."
            ),
        },
    }


def load_target_lines() -> list[str]:
    if not TARGET_STRINGS_PATH.exists():
        return []
    return TARGET_STRINGS_PATH.read_text(errors="replace").splitlines()


def extract_flow_context(lines: list[str]) -> dict:
    matched = []
    for index, line in enumerate(lines):
        if any(marker in line for marker in FLOW_MARKERS):
            context = lines[max(0, index - 2): min(len(lines), index + 3)]
            matched.append(
                {
                    "line_index": index + 1,
                    "line": line,
                    "context": context,
                }
            )
    ordered_markers = [marker for marker in FLOW_MARKERS if any(marker in line for line in lines)]
    return {
        "ordered_markers_found": ordered_markers,
        "contexts": matched,
    }


def main() -> None:
    db = load_db()
    report = {
        "mdb_path": str(MDB_PATH),
        "system_tables": parse_system_tables(db),
        "candidate_state_flow_markers": extract_flow_context(load_target_lines()),
        "conclusions": [
            (
                "System object ids for VBA modules and macros are recoverable from MSysObjects and "
                "match the NavPane inventory."
            ),
            (
                "MSysAccessObjects becomes parsable once its real Id is injected into the parser catalog, "
                "but its Data column is empty at the current parser layer and does not expose module bodies."
            ),
            (
                "The strongest procedural candidate-state block remains the sequence around "
                "statusfk / aktualizacja parametr w fkand / ExportTx_przeslo / ExportRx_przeslo / "
                "wpisz_dane_koor / kwalifikacja_koor / Kwalifikacja_EMC / Stan_wniosku_po_weryfikacji."
            ),
            (
                "The same recovered string corpus still contains wstaw_status and status_kand, so the final "
                "candidate promotion likely happens after verification rather than during raw pairwise EMC writing."
            ),
        ],
    }
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
