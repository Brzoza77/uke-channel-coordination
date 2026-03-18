# UKE Channel Coordination

Narzędzie do analizy koordynacji częstotliwości dla linii radiowych na podstawie:

- wejścia `WLR`
- wewnętrznej bazy `SQLite`
- budowanej z publikacji `MDB` UKE

Projekt zawiera:

- silnik analizy w [analysis.py](/home/brzoza/uke/analysis.py)
- parser `WLR` w [wlr.py](/home/brzoza/uke/wlr.py)
- warstwę danych i planów w [uke.py](/home/brzoza/uke/uke.py)
- API FastAPI i PDF w [app.py](/home/brzoza/uke/app.py)
- frontend dashboardowy w [index.html](/home/brzoza/uke/index.html) i `static/`
- zestaw skryptów reverse engineeringu w `results/`

Podstawowym źródłem danych jest teraz:

- [data/uke_workflow.sqlite](/home/brzoza/uke/data/uke_workflow.sqlite)
- [data/antenna_catalog.sqlite](/home/brzoza/uke/data/antenna_catalog.sqlite)

czyli lokalne `SQLite` budowane z publikacji `MDB` UKE.

Runtime aplikacji nie korzysta już z dawnych wejść `XLSX` ani `RTF`.
Obowiązujący model danych to wyłącznie:

- `MDB -> SQLite + antenna catalog`
- `WLR -> analiza -> PDF/UI`

## Instalacja

### 1. Sklonuj repo

```bash
git clone https://github.com/Brzoza77/uke-channel-coordination.git
cd uke-channel-coordination
```

### 2. Utwórz środowisko i zainstaluj zależności

Najprościej:

```bash
./bootstrap_mdb.sh
source .venv/bin/activate
```

Skrypt instaluje:

- runtime aplikacji z [requirements.txt](/home/brzoza/uke/requirements.txt)
- zależności MDB z [requirements-mdb.txt](/home/brzoza/uke/requirements-mdb.txt)

Ręcznie:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-mdb.txt
```

### 3. Wymagania systemowe

Do pełnego odświeżania publikacji UKE potrzebne są:

- `python3`
- `unrar` kompatybilny ekstraktor:
  - preferowany `unar`
  - fallback `7z`
  - działa też `unrar`
  - działa też `bsdtar`

Na tej maszynie smoke test był wykonywany z:

- `unar`
- `7z`

Przykład dla Ubuntu/Debian:

```bash
sudo apt install unar
```

albo:

```bash
sudo apt install p7zip-full
```

## Zależności Pythona

Runtime aplikacji:

- `fastapi==0.92.0`
- `uvicorn==0.17.6`
- `pydantic==1.10.22`
- `python-multipart==0.0.5`

Generator PDF jest teraz wbudowany w projekt i nie wymaga:

- `reportlab`
- `ft2build.h`
- pakietów developerskich `freetype`

Warstwa MDB / Access:

- `access_parser==0.0.6`
- `construct==2.10.70`
- `tabulate==0.10.0`

## Odświeżenie bazy UKE

Jednym poleceniem:

```bash
./refresh_uke_sqlite.sh
```

Skrypt:

1. sprawdza stronę publikacji UKE
2. pobiera najnowsze archiwum `lr_konsultacja`
3. rozpakowuje `MDB`
4. buduje `data/uke_workflow.sqlite`
5. buduje `data/antenna_catalog.sqlite`
6. odświeża artefakty workflow w `logs/`

`data/antenna_catalog.sqlite` jest wymagana do pelnej analizy EMC.
Bez niej runtime przechodzi na uproszczony fallback charakterystyk anten i wyniki moga
rozjechac sie wzgledem srodowiska referencyjnego.

Przydatne warianty:

Tylko lokalne `MDB`, bez sprawdzania publikacji:

```bash
UKE_AUTO_UPDATE=0 ./refresh_uke_sqlite.sh
```

Sprawdzenie publikacji bez pobierania:

```bash
python3 results/update_uke_publication.py --check-only
```

Zmiana katalogu roboczego pobrań/ekstrakcji:

```bash
UKE_SOURCE_ROOT=/ścieżka/robocza ./refresh_uke_sqlite.sh
```

## Uruchomienie aplikacji

Po aktywacji środowiska:

```bash
./run.sh
```

Domyślnie aplikacja startuje na:

```text
http://0.0.0.0:8012
```

Zmiana portu:

```bash
PORT=8013 ./run.sh
```

## Podstawowa obsługa użytkownika

### 1. Odśwież źródło UKE

```bash
./refresh_uke_sqlite.sh
```

### 2. Uruchom aplikację

```bash
./run.sh
```

### 3. Otwórz dashboard

W przeglądarce:

```text
http://localhost:8012
```

### 4. Wgraj plik `WLR`

W UI:

- wybierz `Upload WLR`
- wskaż plik `.wlr`
- kliknij `Wyślij plik`
- kliknij `Analizuj WLR`

### 5. Odczytaj wynik

W dashboardzie zobaczysz:

- źródło danych UKE
- sparsowane zapytanie
- mapę analizowanego linku i konfliktów
- rekomendacje kanałów
- tabelę `CONDITIONAL / REJECTED`
- wykres degradacji `TDmax` dla całego badanego pasma z progiem `1 dB`

### 6. Wygeneruj PDF

Po analizie:

- kliknij `Pobierz PDF`

## Log analiz

Serwer zapisuje każde uruchomienie analizy WLR do:

- [logs/wlr_analysis_runs.jsonl](/home/brzoza/uke/logs/wlr_analysis_runs.jsonl)

Każdy wpis zawiera m.in.:

- timestamp startu i końca
- czas trwania analizy w `ms`
- `upload_id`
- źródło wywołania:
  - `api.analyze`
  - `api.report.pdf`
  - `api.report.get`
- wynik analizy albo błąd

## Co sprawdzić po instalacji

Składnia Pythona:

```bash
python3 -m py_compile analysis.py app.py schemas.py wlr.py uke.py
```

Składnia frontendu:

```bash
node --check static/js/app.js
```

Kontrola API:

```bash
curl -s http://127.0.0.1:8012/api/health
curl -s http://127.0.0.1:8012/api/source
```

W `api/source` sprawdzisz tez, czy runtime widzi:

- `antenna_catalog_present`
- `antenna_catalog_path`

## Dokumentacja

- [Reverse engineered workflow UKE - syntetycznie](docs/UKE_WORKFLOW_REVERSE_ENGINEERED.md)
- [Workflow UKE - pełne notatki reverse engineeringu](docs/UKE_WORKFLOW.md)
- [VBA i makra Accessa](docs/UKE_VBA.md)
- [Eksport MDB UKE](docs/UKE_MDB_EXPORT.md)
- [Architektura](docs/ARCHITECTURE.md)
- [Operacje](docs/OPERATIONS.md)
- [Git - szybka ściąga](docs/GIT.md)

## Uwaga praktyczna

Najlepiej działający dziś model końcowego statusu kanału to eksperymentalny
`dual-path status gate`, wyprowadzony z reverse engineeringu Accessa.

Na paczce referencyjnej `80 GHz` osiąga:

- `303 / 308`
- `98.38%`

To jest bardzo dobry wynik, ale nadal należy go traktować jako model odtworzony,
a nie oficjalną specyfikację UKE.
