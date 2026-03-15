# Operacje i workflow

## Start aplikacji

```bash
cd /home/brzoza/uke
./run.sh
```

Skrypt:
- sprawdza, czy port nie jest zajety
- uruchamia `uvicorn`
- uzywa `--reload`

## Podstawowy workflow

1. Wyslij `WLR` przez UI lub `POST /api/upload-wlr`
2. Uruchom analize przez `POST /api/analyze`
3. Ocen:
   - podsumowanie
   - rekomendacje
   - konfliktowe linki
   - mape
4. Wygeneruj PDF, jesli potrzebny

## Batch testy

Do lekkich batchy na Raspberry zalecany jest limit:
- `10-15` case'ow

Powod:
- wieksze paczki (`20+`) potrafia dobic do timeoutu przy `max_links=300`

Przykladowe artefakty batchy trafiaja do:
- `logs/`

## Wazne zbiory

### Testy regresyjne
- `testy/`

### Logi strojenia i analiz
- `logs/`

### Skrypty pomocnicze
- `results/`

## Zasady pracy z duzymi danymi

Na tej maszynie warto unikac:
- pelnych przebiegow na setkach case'ow
- masowego parsowania MDB bez limitow

Zalecenia:
- jeden rdzen CPU
- `nice`
- `timeout`
- male paczki testowe

## Co sprawdzac po zmianach

### Silnik
- `python3 -m py_compile analysis.py app.py schemas.py wlr.py`

### API
- `GET /api/health`
- `GET /api/source`

### Frontend
- czy wersja silnika jest widoczna
- czy skrajny przypadek `0 ACCEPTED` nie wyglada jak pozytywna rekomendacja
- czy mapa i legenda sa spojne

