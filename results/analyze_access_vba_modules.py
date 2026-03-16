#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


def _load_inventory(path: Path) -> tuple[list[str], list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    objects = payload.get("inventory", {}).get("objects_by_type", {})
    modules = list(objects.get("-32761", []))
    macros = list(objects.get("-32766", []))
    return modules, macros


def _collect_strings(mdb_path: Path) -> list[str]:
    output = subprocess.check_output(
        ["strings", "-a", str(mdb_path)],
        text=True,
        errors="ignore",
    )
    return output.splitlines()


def _procedure_inventory(lines: list[str]) -> list[dict[str, Any]]:
    proc_pattern = re.compile(r"\b(?:Public |Private )?(?:Sub|Function)\s+([A-Za-z0-9_@]+)")
    procedures: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        match = proc_pattern.search(line)
        if not match:
            continue
        procedures.append(
            {
                "line": index + 1,
                "procedure": match.group(1),
                "raw": line,
            }
        )
    return procedures


def _module_report(name: str, kind: str, lines: list[str]) -> dict[str, Any]:
    proc_pattern = re.compile(r"\b(?:Public |Private )?(?:Sub|Function)\s+([A-Za-z0-9_@]+)")
    keywords = [
        "Sub ",
        "Function ",
        "CurrentDb",
        "OpenRecordset",
        "QueryDef",
        "UPDATE ",
        "DELETE ",
        "INSERT ",
        "Czestotliwosc kandydujaca",
        "Wynik EMC-LR",
        "Problem_kons",
        "Zadania_LR",
        "T_dane_koor",
        "R_dane_koor",
    ]

    direct_hits: list[dict[str, Any]] = []
    nearby_procs: set[str] = set()
    for index, line in enumerate(lines):
        if name not in line:
            continue
        start = max(0, index - 8)
        end = min(len(lines), index + 25)
        context = lines[start:end]
        direct_hits.append({"line": index + 1, "context": context[:33]})
        for item in context:
            match = proc_pattern.search(item)
            if match:
                nearby_procs.add(match.group(1))

    theme_hits: list[dict[str, Any]] = []
    if name in ("Zadania_LR", "Master", "Zadania_LR_Tlumienie", "koordynacja_zagr", "start", "autoexec"):
        for index, line in enumerate(lines):
            if not any(keyword in line for keyword in keywords):
                continue
            if 598500 <= index + 1 <= 603800:
                theme_hits.append(
                    {
                        "line": index + 1,
                        "context": lines[max(0, index - 3): min(len(lines), index + 8)],
                    }
                )

    return {
        "name": name,
        "object_kind": kind,
        "direct_hit_count": len(direct_hits),
        "direct_hits": direct_hits[:8],
        "procedure_names_nearby": sorted(nearby_procs)[:50],
        "theme_hits": theme_hits[:30],
    }


def _curated_traces(lines: list[str]) -> list[dict[str, Any]]:
    markers = [
        "Sub wyniki_EMC_fk",
        "utworz_wynik_zaklocen",
        "UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].[status]",
        "Set dbb = CurrentDb",
        "EMC_FS_POL_ZAGR",
        "brak charakterystyki",
        "za ma",
        "kod_polaryzacji",
        "DELETE DISTINCTROW [",
        "Wynik EMC-LR",
        "status_fkand",
        "Koniec_obliczen",
        "obliczenia_EMC_POL_ZAGR",
    ]
    traces: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not any(marker in line for marker in markers):
            continue
        traces.append(
            {
                "line": index + 1,
                "context": lines[max(0, index - 5): min(len(lines), index + 12)],
            }
        )
    return traces[:120]


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze VBA/module traces embedded in Access MDB strings.")
    parser.add_argument("--mdb", default="LR_Konsultacja_349.mdb")
    parser.add_argument("--inventory-json", default="logs/access_querydefs_inventory_20260316.json")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    mdb_path = Path(args.mdb).resolve()
    inventory_path = Path(args.inventory_json).resolve()
    modules, macros = _load_inventory(inventory_path)
    lines = _collect_strings(mdb_path)

    report = {
        "mdb": str(mdb_path),
        "inventory_json": str(inventory_path),
        "modules": modules,
        "macros": macros,
        "procedure_inventory": _procedure_inventory(lines),
        "module_reports": [
            _module_report(name, "module", lines) for name in modules
        ] + [
            _module_report(name, "macro", lines) for name in macros
        ],
        "curated_traces": _curated_traces(lines),
        "notes": [
            "AccessParser does not expose module source tables directly for this MDB.",
            "Analysis is based on MSysObjects module names plus raw string/procedure traces embedded in the MDB file.",
            "This is enough to prove that VBA orchestrates candidate updates and EMC result handling, but not enough to reconstruct all source code verbatim.",
        ],
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
