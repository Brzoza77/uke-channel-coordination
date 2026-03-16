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
- `data/`

Zadania:
- ladowanie wewnetrznego katalogu UKE z `data/uke_workflow.sqlite`
- parowanie rekordow simplex w linki duplex
- ladowanie planow kanalowych z `MDB/sqlite`
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

### MDB UKE
- zrodlo pelnego workflow UKE
- po odswiezeniu sa eksportowane do `sqlite`

### SQLite UKE
- glowny runtime dataset aplikacji
- katalog linkow, planow, anten, nadajnikow i workflow konsultacyjnego

## Ograniczenia obecnego modelu

- nie wszystkie fragmenty VBA Accessa zostaly literalnie odzyskane
- topografia i morfologia terenu nie sa jeszcze w pelni dolaczone do modelu
- czesc przypadkow nadal wymaga dalszego strojenia mimo wysokiej zgodnosci na paczce referencyjnej
