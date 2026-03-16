#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Summarize reconstructed Access qualification flow from VBA/string traces.')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    payload = {
        'artifacts': [
            'logs/access_candidate_state_deep_context_20260316.json',
            'logs/access_vba_target_strings_20260316.txt',
            'logs/access_candidate_status_keywords_20260316.json',
        ],
        'evidence': [
            {
                'topic': 'Kwalifikacja_EMC_kraj wrapper',
                'lines': '595331-595360',
                'raw': [
                    'druk_wynikow',
                    'Kwalifikacja_EMC_kraj(',
                    'DCount',
                    'szer_kan',
                    'nr_przesla',
                    'generuj_fk',
                    'Plan#',
                    'PlanL',
                    'symbol_planu',
                    'id_fk',
                    'status',
                ],
                'inference': 'Kwalifikacja_EMC_kraj appears to sit at a higher orchestration layer around domestic candidate generation/qualification for a plan, likely before print/export.',
            },
            {
                'topic': 'Per-candidate qualification sequence',
                'lines': '603582-603590',
                'raw': [
                    'ExportTx_przeslo',
                    'ExportRx_przeslo',
                    'wpisz_dane_koor',
                    'kwalifikacja_koor',
                    'Kwalifikacja_EMC',
                    'Stan_wniosku_po_weryfikacji',
                ],
                'inference': 'Access runs a lower-level candidate verification path after writing coordination payloads; this looks like the closest procedural stage before final candidate status update.',
            },
            {
                'topic': 'Problem and coordination decision separation',
                'lines': '598641-598654',
                'raw': [
                    'SELECT Problem.[Przeslo#], Problem.[TD p-p], Problem.decyzja_o_koordynacji',
                    'WHERE Problem.[TD p-p] > 1',
                    'UPDATE Problem SET Problem.decyzja_o_koordynacji = IIf([d11] > [dgr],1,2)',
                    'SELECT Problem.[Przeslo#], Problem.decyzja_o_koordynacji WHERE decyzja_o_koordynacji = 1',
                ],
                'inference': 'Problem-level coordination decision is maintained separately from final candidate Status, so Kwalifikacja_EMC likely consumes more than a simple yes/no problem flag.',
            },
            {
                'topic': 'Final status writer remains procedural',
                'lines': '599245-599246 and nearby',
                'raw': [
                    'UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [status] = ...',
                    'WHERE [FKandydujaca#] = ...',
                    'wstaw_status',
                    'status_kand',
                ],
                'inference': 'Even after qualification stages, candidate selection is finalized by VBA, not by a visible saved SELECT query.',
            },
        ],
        'reconstructed_layers': [
            {
                'layer': 'plan/domestic wrapper',
                'procedures': ['Kwalifikacja_EMC_kraj', 'generuj_fk', 'druk_wynikow'],
                'role': 'Generate/iterate domestic candidates for a plan and prepare the result path.',
            },
            {
                'layer': 'per-candidate verification',
                'procedures': ['wpisz_dane_koor', 'kwalifikacja_koor', 'Kwalifikacja_EMC', 'Stan_wniosku_po_weryfikacji'],
                'role': 'Verify the specific candidate after coordination payload export and before final state promotion.',
            },
            {
                'layer': 'state promotion',
                'procedures': ['wstaw_status', 'Koniec_obliczen'],
                'role': 'Write back final candidate state to Czestotliwosc kandydujaca and terminate/report.',
            },
        ],
        'strong_conclusions': [
            'Kwalifikacja_EMC_kraj is probably not the final status setter itself; it looks more like the domestic orchestration wrapper for generating and qualifying candidate frequencies.',
            'Kwalifikacja_EMC plus Stan_wniosku_po_weryfikacji is the closest visible procedural step before final candidate state promotion.',
            'The final candidate Status still appears to be written procedurally by VBA after qualification, likely through or near wstaw_status/status_kand.',
        ],
        'next_best_step': [
            'Model a dedicated intermediate qualification state in our pipeline rather than jumping directly from pairwise EMC to final selection.',
            'Compare our candidate set against an Access-like wrapper logic: generated candidate -> problem decision -> qualification -> final status promotion.',
            'Search for any additional string traces around Stan_wniosku_po_weryfikacji return values or DCount/status counters if a richer module extraction becomes possible.',
        ],
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
