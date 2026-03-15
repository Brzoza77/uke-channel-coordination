# UKE Channel Coordination

Silnik analizy zaklocen dla linii radiowych, oparty o wejscie `WLR`, dane pozwolen radiowych z XLSX oraz dodatkowe dane antenowe/maski z baz UKE.

Projekt sklada sie z:
- silnika obliczeniowego w `analysis.py`
- parsera WLR w `wlr.py`
- warstwy danych i planow w `uke.py`, `plany/`, `data/`
- API i raportow PDF w `app.py`
- frontendu dashboardowego w `index.html` i `static/`

Aktualna wersja silnika:
- `hcm-consultation-filter-2026-03-14`

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
3. Dobiera kandydackie linki z bazy pozwolen
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
- `uke.py` - ladowanie XLSX i planow
- `static/` - frontend
- `plany/` - pliki planow kanalowych
- `testy/` - pary `wlr-doc` do porownan z UKE
- `results/` - skrypty pomocnicze, tuning, ekstrakcje MDB
- `hcm/` - materialy HCM

## Dokumentacja

- [Architektura](docs/ARCHITECTURE.md)
- [Operacje i workflow](docs/OPERATIONS.md)

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

