# Architektura

## Warstwy systemu

### 1. Parser wejscia

Plik:
- `wlr.py`

Zadania:
- parsowanie pliku `WLR`
- normalizacja danych lokalizacji i parametrow radiowych
- budowa obiektu `WlrRequest`

### 2. Warstwa danych referencyjnych

Pliki:
- `uke.py`
- `plany/`
- `data/`

Zadania:
- ladowanie zbioru pozwolen radiowych z XLSX
- parowanie rekordow simplex w linki duplex
- ladowanie planow kanalowych
- lookup charakterystyk anten i masek

### 3. Silnik analizy

Plik:
- `analysis.py`

Zadania:
- generowanie kandydatow kanalowych
- selekcja linkow kandydackich w przestrzeni
- obliczenia konfliktow per link i per kierunek
- klasyfikacja `ACCEPTED / CONDITIONAL / REJECTED`

Najwazniejsze elementy logiki:
- obliczenia per-leg `A->B` i `B->A`
- uwzglednienie strony victim i aggressor
- maski radiowe
- charakterystyki anten
- hardening HCM
- filtr konsultacyjny dla wlasnych relacji `same_span` / `same_span_like`

### 4. API i prezentacja

Pliki:
- `app.py`
- `schemas.py`
- `index.html`
- `static/js/app.js`
- `static/css/app.css`

Zadania:
- upload WLR
- analiza
- mapa Leaflet
- lista rekomendacji
- raport PDF

## Głowne endpointy

- `GET /api/health`
- `GET /api/source`
- `POST /api/upload-wlr`
- `POST /api/analyze`
- `POST /api/report.pdf`
- `GET /api/report/{upload_id}.pdf`

## Dane wejściowe

### WLR
- zadane przeslo i parametry konsultacji

### XLSX z pozwoleniami
- aktualna lista linii radiowych

### MDB UKE
- zrodlo charakterystyk anten i masek
- obecnie wykorzystywane do lokalnych eksportow/agregatow

## Ograniczenia obecnego modelu

- porownania z historycznymi `doc` sa zaburzone przez aktualna liste pozwoleń
- topografia i morfologia terenu nie sa jeszcze w pelni dolaczone do modelu
- czesc przypadkow nadal jest zbyt restrykcyjna lub zbyt lagodna wzgledem UKE

