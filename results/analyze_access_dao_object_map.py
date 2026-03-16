#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Document inferred DAO object -> table/role mapping in Access workflow.")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    payload = {
        "focus": "Map DAO/Recordset/QueryDef variable names from Access VBA to likely tables and workflow roles.",
        "objects": [
            {
                "name": "dbb",
                "kind": "Database",
                "likely_target": "CurrentDb main handle",
                "confidence": "high",
                "evidence": [
                    "Set dbb = CurrentDb",
                    "used near writer flow, Problem updates, QueryDef access",
                ],
                "role": "Primary DAO database handle used across LR workflow.",
            },
            {
                "name": "db",
                "kind": "Database",
                "likely_target": "CurrentDb or local database handle",
                "confidence": "high",
                "evidence": [
                    "Set db = CurrentDb / db.OpenRecordset(...)",
                    "used near filen = db.OpenRecordset(strpyt, dbOpenDynaset)",
                ],
                "role": "Local DAO database handle inside helper procedures.",
            },
            {
                "name": "myq",
                "kind": "QueryDef",
                "likely_target": "parameterized Access query object",
                "confidence": "high",
                "evidence": [
                    "Set myq = db.QueryDefs(...)",
                    "myq.OpenRecordset()",
                ],
                "role": "Reusable QueryDef wrapper; overloaded across procedures.",
            },
            {
                "name": "filen",
                "kind": "Recordset",
                "likely_target": "overloaded; current domestic span record or selection result",
                "confidence": "medium",
                "evidence": [
                    "Set filen = dbb.OpenRecordset(strpyt, dbOpenDynaset)  'przeslo badane'",
                    "Set filen = db.OpenRecordset(strpyt, dbOpenDynaset)  'przeslo badane polskie nadajnik'",
                    "Set filen = myq.OpenRecordset() in NSS/LR compatibility procedures",
                ],
                "role": "Overloaded Recordset name. In terrestrial EMC it points at the current studied span; in NSS helpers it points at selection-query results.",
            },
            {
                "name": "filep",
                "kind": "Recordset",
                "likely_target": "interfering/problem span record",
                "confidence": "medium",
                "evidence": [
                    "td_o = Oblicz_TD(... filep!hao ... filep!pao ... filep!Gao ... filep!Szer ...)",
                    "filepk![przeslo#] = filep![przeslo#]",
                    "if not filep.eof ExportTx_przeslo / ExportRx_przeslo",
                ],
                "role": "Current interfering/problem span being checked for coordination issues before export/qualification.",
            },
            {
                "name": "filepk",
                "kind": "Recordset",
                "likely_target": "problem_kons",
                "confidence": "high",
                "evidence": [
                    "filepk.AddNew",
                    "filepk![FKandydujaca#] = fid",
                    "filepk![TD p-gr] = td_o",
                    "filepk.Update",
                ],
                "role": "Writer for coordination problem records tied to FKandydujaca#.",
            },
            {
                "name": "file",
                "kind": "Recordset",
                "likely_target": "Dane_EMC / transmitter-mask preparation row",
                "confidence": "medium-high",
                "evidence": [
                    "wpis_maski file, maska, ilk, i",
                    "file.Update",
                    "near strings: Dane_EMC, Nadajnik_kons, Producent_kons, 'Brak maski nadajnika'",
                ],
                "role": "Writer for prepared EMC input rows and transmitter mask/default-transmitter enrichment.",
            },
            {
                "name": "set_wybor",
                "kind": "Recordset",
                "likely_target": "NSS/LR joined selection result",
                "confidence": "high",
                "evidence": [
                    "Set set_wybor = dbb.OpenRecordset(nazwa_zap, dbOpenDynaset)",
                    "Set set_wybor = zap_wybor.OpenRecordset()",
                    "used with set_wybor![Kanal#], set_wybor![dlug_geo_rad], set_wybor![Tlumienie_modu_A]",
                ],
                "role": "Selection recordset for NSS/LR compatibility trigger and contour checks.",
            },
            {
                "name": "zap_wybor",
                "kind": "QueryDef",
                "likely_target": "parameterized NSS/LR selection query",
                "confidence": "high",
                "evidence": [
                    "Set zap_wybor = mbd.QueryDefs(nazwa_zap)",
                    "zap_wybor(\"fklr\") = fkand",
                ],
                "role": "Parameterized query wrapper used to bind fkand into NSS/LR compatibility queries.",
            },
            {
                "name": "zap_char_LR",
                "kind": "QueryDef",
                "likely_target": "antenna characteristic query",
                "confidence": "high",
                "evidence": [
                    "Set zap_char_LR = dbb.QueryDefs(nazwa_zap)",
                    "zap_char_LR(\"identyf_przeslo\") = PRZESLO",
                    "zap_char_LR(\"identyf_uklad_pol\") = ...",
                ],
                "role": "QueryDef used to fetch LR antenna patterns for EMC compatibility.",
            },
            {
                "name": "set_char_LR",
                "kind": "Recordset",
                "likely_target": "characterystyka(_kons) rows",
                "confidence": "high",
                "evidence": [
                    "Set set_char_LR = zap_char_LR.OpenRecordset()",
                ],
                "role": "Recordset of antenna characteristic points used in discrimination calculations.",
            },
            {
                "name": "zap_stacja_SS",
                "kind": "QueryDef",
                "likely_target": "satellite station lookup query",
                "confidence": "high",
                "evidence": [
                    "Set zap_stacja_SS = db.QueryDefs(\"zap_stacja_SS\")",
                    "zap_stacja_SS(\"kan\") = KANAL",
                ],
                "role": "QueryDef used in NSS station lookup by channel.",
            },
            {
                "name": "filekr / filepr",
                "kind": "Recordset",
                "likely_target": "problem_kons filtered by country and Tx/Rx side",
                "confidence": "medium",
                "evidence": [
                    "SELECT DISTINCT Problem_kons.Kraj FROM Problem_kons WHERE Problem_kons.[FKandydujaca#] = ...",
                    "(([Tx\\\\Rx])='Tx') AND (([FKandydujaca#])=...) AND ((Kraj)=...)",
                    "[Tx\\\\Rx]='Rx' AND [FKandydujaca#]=... AND Kraj=...",
                ],
                "role": "Per-country / per-side recordsets for foreign or cross-border problem handling.",
            },
        ],
        "strong_conclusions": [
            "Access uses generic DAO variable names reused across multiple procedures, so names alone are not globally unique.",
            "The best current mapping is procedural: each variable must be interpreted in its local workflow block.",
            "The recovered write paths clearly cover problem_kons and Dane_EMC-side preparation.",
            "The missing fkand margin setter is still not directly visible, but it now sits in a much smaller search area around the 'aktualizacja parametr w fkand' block.",
        ],
        "next_best_step": [
            "Search for additional DAO variable names beyond file/filep/filepk/filen that may point specifically to Czestotliwosc kandydujaca.",
            "Inspect any strings near 'FindFirst', 'Edit', and 'Update' that also mention mask/default-transmitter logic, to separate transmitter preparation from candidate updates.",
            "Use this DAO map as the backbone for a more literal procedural reconstruction of the Access LR path.",
        ],
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
