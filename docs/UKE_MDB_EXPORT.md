# Eksport i Analiza MDB UKE

Ten workflow służy do bezpiecznej analizy baz `LR_Konsultacja_349.mdb`, `db1.mdb`, `db2.mdb`.

## Cel

1. Przenieść kluczowe tabele workflow UKE z MDB do SQLite.
2. Zachować mapowanie nazw kolumn źródłowych.
3. Umożliwić analizę na mocniejszej maszynie bez zależności od Accessa.

## Skrypty

- Bootstrap zależności MDB:
  - [bootstrap_mdb.sh](/home/brzoza/uke/bootstrap_mdb.sh)
- Eksport workflow do SQLite:
  - [results/extract_uke_workflow_sqlite.py](/home/brzoza/uke/results/extract_uke_workflow_sqlite.py)
- Podsumowanie SQLite po eksporcie:
  - [results/analyze_uke_workflow_sqlite.py](/home/brzoza/uke/results/analyze_uke_workflow_sqlite.py)
- Graf relacji workflow:
  - [results/build_uke_workflow_graph.py](/home/brzoza/uke/results/build_uke_workflow_graph.py)
- Odtworzenie metodologii wyboru kanału:
  - [results/infer_uke_selection_methodology.py](/home/brzoza/uke/results/infer_uke_selection_methodology.py)
- Bezpieczne sondowanie pojedynczych tabel MDB:
  - [results/probe_mdb.py](/home/brzoza/uke/results/probe_mdb.py)

## Tabele workflow

Eksport domyślnie obejmuje:

- `Czestotliwosc kandydujaca`
- `Dane_EMC`
- `DECYZJA`
- `Przeslo decyzji`
- `Wynik EMC-LR`
- `PROCES_AP28`
- `problem_kons`
- `PRZESLO`
- `Przeslo linii radiowej`
- `Przeslo-zakres-plan`
- `PLAN`
- `KANAL`
- `NADAJNIK`
- `Nadajnik_kons`
- `maski`
- `ANTENA`
- `Antena_kons`
- `PASMO ANTENY`
- `CHARAKTERYSTYKA`
- `charakterystyka_kons`
- `PRODUCENT`
- `Producent_kons`
- `Homologacja_kons`
- `ELEWACJA_HORYZONTU`
- `ZASIEG`
- `STACJA`
- `OBIEKT STACJI`
- `Adresy`

## Uruchomienie na mocniejszej maszynie

W katalogu projektu:

Najpierw zależności:

```bash
./bootstrap_mdb.sh
source .venv/bin/activate
```

albo ręcznie:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-mdb.txt
```

Potem eksport:

```bash
python3 results/extract_uke_workflow_sqlite.py \
  --mdb LR_Konsultacja_349.mdb db1.mdb db2.mdb \
  --sqlite data/uke_workflow.sqlite
```

Po eksporcie:

```bash
python3 results/analyze_uke_workflow_sqlite.py \
  --sqlite data/uke_workflow.sqlite \
  --source-db LR_Konsultacja_349 \
  --out logs/uke_workflow_sqlite_summary.json
```

Budowa grafu relacji:

```bash
python3 results/build_uke_workflow_graph.py \
  --sqlite data/uke_workflow.sqlite \
  --source-db LR_Konsultacja_349 \
  --out-json logs/uke_workflow_graph.json \
  --out-dot logs/uke_workflow_graph.dot

Odtworzenie metodologii wyboru kanału:

```bash
python3 results/infer_uke_selection_methodology.py \
  --sqlite data/uke_workflow.sqlite \
  --source-db LR_Konsultacja_349 \
  --out logs/uke_selection_methodology.json
```
```

## Artefakty

Eksport tworzy:

- SQLite:
  - `data/uke_workflow.sqlite`
- manifest:
  - `data/uke_workflow.manifest.json`

Graf tworzy:

- JSON:
  - `logs/uke_workflow_graph.json`
- DOT:
  - `logs/uke_workflow_graph.dot`

Plik `.dot` mozna potem wyrenderowac np. przez Graphviz:

```bash
dot -Tpng logs/uke_workflow_graph.dot -o logs/uke_workflow_graph.png
```

W SQLite są też tabele pomocnicze:

- `source_table_metadata`
- `source_table_manifest`

To pozwala odtworzyć:

- oryginalną nazwę tabeli
- oryginalną nazwę kolumny
- nazwę kolumny w SQLite
- typ SQLite

## Co już wiemy z workflow UKE

- `Czestotliwosc kandydujaca` przechowuje:
  - kanał
  - plan
  - polaryzację
  - status
  - marginesy `MargNad`, `MargOdb`
  - teksty `T_dane_koor`, `R_dane_koor`
- `Dane_EMC` przechowuje:
  - parametry toru radiowego
  - anteny
  - nadajnik
  - liczby szumowe
  - moce
  - kierunki promieniowania
  - kąty elewacji
  - częstotliwość
  - dupleks
- `Wynik EMC-LR` przechowuje:
  - `FKandydujaca_b#`
  - `Przęsło_i#`
  - `Metoda`
  - `Margines_b-i`
  - `Margines_i-b`
  - odległości i błędy obliczeń
- `problem_kons` wygląda na warstwę problemów granicznych / koordynacyjnych:
  - `TD p-gr`
  - `TD p-p`
  - `D11`
  - `Dgr`
- `PROCES_AP28` wygląda na wynik etapu zasięgowego / klimatycznego i flagę, czy uruchomiono komponent LR
- `*_kons` wygląda na lokalny snapshot bieżącej konsultacji:
  - anteny
  - nadajniki
  - producenci
  - charakterystyki

## Bezpieczny rekonesans na Raspberry

Katalog tabel:

```bash
nice -n 15 python3 results/probe_mdb.py --db LR_Konsultacja_349.mdb --mode catalog --timeout-sec 15
```

Kolumny jednej tabeli:

```bash
nice -n 15 python3 results/probe_mdb.py --db LR_Konsultacja_349.mdb --mode columns --table "Wynik EMC-LR" --timeout-sec 15
```

Kilka wierszy:

```bash
nice -n 15 python3 results/probe_mdb.py --db db2.mdb --mode rows --table "Czestotliwosc kandydujaca" --limit 4 --timeout-sec 15
```
