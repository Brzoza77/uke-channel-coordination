# UKE Channel Coordination

Silnik analizy zaklocen dla linii radiowych, oparty o wejscie `WLR` i wewnetrzna baze `SQLite` budowana z publikacji `MDB` UKE.

Projekt sklada sie z:
- silnika obliczeniowego w `analysis.py`
- parsera WLR w `wlr.py`
- warstwy danych i planow w `uke.py` oraz `data/`
- API i raportow PDF w `app.py`
- frontendu dashboardowego w `index.html` i `static/`

Uwaga:
- pliki `*.mdb`, `*.rar`, `logs/`, `reports/`, `data/*.sqlite` oraz `.vendor/` nie sa przechowywane w repo
- podstawowym zrodlem danych jest teraz `data/uke_workflow.sqlite`, odswiezane z publikacji UKE

Aktualna wersja silnika:
- `hcm-margin-first-2026-03-15`

## Szybki start

Uruchomienie API:

```bash
cd /home/brzoza/uke
./run.sh
```

Domyslnie aplikacja startuje na:

```text
http://0.0.0.0:8012
```

Mozna zmienic port:

```bash
PORT=8013 ./run.sh
```

## Co robi system

1. Wczytuje plik `WLR`
2. Parsuje zadane przeslo, plan, czestotliwosci, polaryzacje i parametry radiowe
3. Dobiera kandydackie linki z wewnetrznego katalogu UKE zbudowanego z `MDB`
4. Liczy konflikty:
   - co zakloca nas
   - co my zaklocamy
5. Klasyfikuje kanaly jako:
   - `ACCEPTED`
   - `CONDITIONAL`
   - `REJECTED`
6. Wystawia wynik przez FastAPI i dashboard
7. Potrafi wygenerowac raport PDF

## Najwazniejsze katalogi

- `analysis.py` - glowny silnik
- `app.py` - FastAPI, raport PDF, mapa i odpowiedzi API
- `wlr.py` - parser plikow WLR
- `uke.py` - ladowanie danych i planow z wewnetrznej SQLite UKE
- `static/` - frontend
- `data/` - lokalna baza SQLite budowana z `MDB`
- `testy/` - pary `wlr-doc` do porownan z UKE
- `results/` - skrypty pomocnicze, tuning, ekstrakcje MDB
- `hcm/` - materialy HCM

## Odswiezanie bazy UKE

Jednym poleceniem:

```bash
./refresh_uke_sqlite.sh
```

Skrypt:
- sprawdza publikacje UKE,
- pobiera najnowsze `lr_konsultacja`,
- rozpakowuje `MDB`,
- buduje `data/uke_workflow.sqlite`,
- odswieza artefakty workflow.

Domyslnie nie pobiera archiwum planow, bo plany kanalowe sa odtwarzane z `MDB`.

## Dokumentacja

- [Architektura](docs/ARCHITECTURE.md)
- [Operacje i workflow](docs/OPERATIONS.md)
- [Git - szybka sciaga](docs/GIT.md)
- [Workflow UKE - reverse engineering](docs/UKE_WORKFLOW.md)
- [Eksport MDB UKE](docs/UKE_MDB_EXPORT.md)

## Git

Repo zostalo zainicjalizowane lokalnie:

```bash
git status
```

Domyslny `.gitignore` pomija:
- duze bazy MDB
- XLSX
- uploady
- raporty PDF
- logi
- artefakty lokalne

Jesli chcesz wersjonowac wybrane dane testowe lub eksporty, trzeba je dodac swiadomie wyjatkami w `.gitignore`.
