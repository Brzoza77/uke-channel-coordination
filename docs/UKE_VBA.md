# Access VBA i Makra

Najważniejsze artefakty:
- `logs/access_vba_modules_analysis_20260316.json`
- `logs/access_vba_status_traces_20260316.json`
- `logs/access_status_assignment_20260316.json`
- `logs/access_candidate_state_flow_20260316.json`

## Co udało się potwierdzić

W `LR_Konsultacja_349.mdb` istnieją obiekty VBA i makr:

### Moduły
- `Aktualizacja_bazy`
- `Master`
- `Przylaczenie_baz`
- `Separator`
- `Usuwanie_ukrytych_operatorow`
- `Zadania_LR`
- `Zadania_LR_Tlumienie`
- `Zlecenie_zadania_do_serwera`
- `import_wnelw`
- `koordynacja_zagr`

### Makra
- `Uaktualnienie bazy`
- `autoexec`
- `klepsydra_nie`
- `start`

## Ograniczenie techniczne

Nie udało się wyciągnąć pełnego kodu źródłowego modułów bezpośrednio z tabel MDB:
- `Modules`
- `MSysModules`
- `MSysModules2`
- `MSysAccessObjects`

AccessParser ich nie udostępnia dla tej bazy, a plik nie otwiera się jako zwykły kontener OLE
narzędziami typu `olefile`.

Dlatego analiza VBA opiera się na:
- nazwach modułów z `MSysObjects`
- surowych stringach osadzonych w `MDB`
- nazwach procedur i dynamicznych SQL widocznych w tych stringach

To nie daje pełnego źródła, ale daje bardzo mocne ślady wykonania.

## Najważniejsze procedury znalezione w stringach

Potwierdzone nazwy procedur:
- `Odl`
- `sta@rt`
- `kompat_sat_linie_R`
- `utworz_wynik_zaklocen`
- `wyniki_EMC_fk`
- `sta`
- `Ob`
- `wc`

Najważniejsze dla workflow UKE:
- `wyniki_EMC_fk`
- `utworz_wynik_zaklocen`
- `kompat_sat_linie_R`

## Najważniejsze ślady proceduralne

Potwierdzone ślady:
- `Set dbb = CurrentDb`
- użycie `QueryDef`
- użycie `OpenRecordset`
- dynamiczne `DELETE` i `UPDATE`
- czyszczenie:
  - `Wynik EMC-LR`
  - `Wynik EMC-SS`
  - `problem_kons`
  - `Czestotliwosc kandydujaca`
  - `Dane_EMC`
  - `Charakterystyka_kons`
  - `Antena_kons`
  - `Nadajnik_kons`
  - `Producent_kons`

Najważniejszy ślad:
- `UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].[status] = ... WHERE ((([Czestotliwosc kandydujaca].[FKandydujaca#])= ...`

To jest twardy dowód, że `Status` kandydata jest aktualizowany proceduralnie z VBA.

## Co to mówi o roli modułów

### `Master`

Najmocniej powiązany z głównym przebiegiem:
- dużo bezpośrednich trafień w stringach
- ślady:
  - `CurrentDb`
  - `QueryDef`
  - `Wynik EMC-LR`
  - `status_fkand`
  - `Koniec_obliczen`
  - `obliczenia_EMC_POL_ZAGR`

Wniosek:
- bardzo prawdopodobny główny moduł orkiestrujący workflow

### `Zadania_LR`

Bardzo mocny kandydat na moduł wykonujący przebieg dla linii radiowych:
- nazwa bezpośrednio wskazuje tor LR
- ślady proceduralne występują w tym samym obszarze stringów co:
  - `wyniki_EMC_fk`
  - czyszczenie wyników
  - aktualizacja statusu

Wniosek:
- jeden z najbardziej prawdopodobnych modułów odpowiedzialnych za generowanie i ocenę kandydatów LR

### `Zadania_LR_Tlumienie`

Najpewniej wariant / pomocnicza ścieżka związana z tłumieniem:
- nazwa bezpośrednio to sugeruje
- pojawia się w tym samym obszarze co logika EMC

Wniosek:
- prawdopodobny moduł pomocniczy do strat/tłumień toru lub korekt EMC

### `koordynacja_zagr`

Silny związek z torem zagranicznym:
- w stringach mamy:
  - `EMC_FS_POL_ZAGR`
  - `metoda=2`
  - `nie ma zagranicznych stacji zakłócających`

Wniosek:
- bardzo prawdopodobnie odpowiada za gałąź zagraniczną / koordynację międzynarodową

### `Aktualizacja_bazy`

Wygląda na moduł techniczny do odświeżania bazy:
- nazwa jednoznaczna
- nie jest dziś głównym tropem dla wyboru kandydatów

### `Przylaczenie_baz`

Bardzo prawdopodobnie odpowiada za podłączanie zewnętrznych baz:
- w stringach są ślady:
  - `CurrentProject.Path & "\\SAT_NSS.mdb"`
  - `CurrentProject.Path & "\\Stacje_zagraniczne.mdb"`
  - `CurrentProject.Path & "\\Baza_LR.mdb"`

Wniosek:
- moduł od łączenia źródeł danych

### `Zlecenie_zadania_do_serwera`

Najpewniej warstwa wykonawcza / zlecanie obliczeń:
- nazwa wskazuje na delegowanie zadania
- wymaga dalszych śladów, ale nie wygląda na główny moduł logiki statusu

### `import_wnelw`

Najpewniej import danych wejściowych:
- nazwa wskazuje import
- możliwe powiązanie z wczytaniem WLR / danych konsultacji

### `Separator`

Prawdopodobnie moduł pomocniczy / techniczny:
- na razie bez mocnego śladu merytorycznego

### `Usuwanie_ukrytych_operatorow`

Prawdopodobnie operacja porządkowa / filtracyjna:
- możliwy wpływ na widoczność części rekordów
- warto pamiętać, ale nie jest dziś głównym driverem workflow EMC

## Makra

### `start`

To najważniejsze makro startowe:
- znaleziony ślad `Sub sta@rt()`
- bardzo prawdopodobnie punkt wejścia UI / workflow

### `autoexec`

Najpewniej makro uruchamiane automatycznie przy starcie Accessa.

### `Uaktualnienie bazy`

Makro pomocnicze do aktualizacji danych.

### `klepsydra_nie`

Najpewniej makro interfejsowe / UX.

## Najmocniejszy wniosek

Workflow Accessa nie kończy się na zapisanych `QueryDef`.

Realny przebieg wygląda raczej tak:
1. makro `start` / `autoexec`
2. moduły typu `Master` / `Zadania_LR`
3. generowanie kandydatów i payloadów EMC
4. uruchomienie procedur EMC
5. proceduralny `UPDATE` rekordów `Czestotliwosc kandydujaca`, w tym `Status`
6. dopiero potem wydruk przez `Wyniki_do_wydruku`

## Rekonstrukcja stanu kandydata

Najważniejsze twarde ślady z `MDB`:
- `statusfk = 1`
- `If status_fkand_zagr = 2 Then status_fkand = 2`
- `If blad > 0 Then Koniec_obliczen dbb, fid(i), status_fkand: Exit Function`
- `UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].[status] = ... WHERE [FKandydujaca#] = ...`
- identyfikatory:
  - `wstaw_status`
  - `status_kand`
  - `kwalifikacja_koor`
  - `Kwalifikacja_EMC`
  - `Stan_wniosku_po_weryfikacji`

Najbardziej prawdopodobny przebieg proceduralny:
1. kandydat startuje z `statusfk = 1`
2. Access otwiera dane pomocnicze:
   - `Nadajnik`
   - `maski`
   - `charakterystyka`
3. dla gałęzi problemowej / zagranicznej wywoływane jest:
   - `obliczenia_EMC_POL_ZAGR`
4. jeśli gałąź zagraniczna zwróci `status_fkand_zagr = 2`, to:
   - `status_fkand = 2`
5. jeśli wykryty jest problem kompatybilności (`TD > 1`), Access:
   - dopisuje rekord do `problem_kons`
   - oznacza `stat_koor`
6. Access eksportuje payloady:
   - `ExportTx_przeslo`
   - `ExportRx_przeslo`
   i wykonuje:
   - `wpisz_dane_koor`
   - `kwalifikacja_koor`
   - `Kwalifikacja_EMC`
   - `Stan_wniosku_po_weryfikacji`
7. na końcu VBA aktualizuje `Czestotliwosc kandydujaca.status`
8. warstwa raportowa konsumuje kandydaty z `Status = 2`

Najważniejsze ograniczenie:
- nadal nie mamy pełnego kodu VBA 1:1
- ale już mamy wystarczająco mocne dowody, że:
  - `Status = 1` jest stanem startowym/domyslnym
  - `Status = 2` jest stanem promowanym proceduralnie i używanym dalej przez wydruk

## Najbardziej sensowny następny krok

Skupić dalszy reverse engineering na:
- `wyniki_EMC_fk`
- `utworz_wynik_zaklocen`
- `Master`
- `Zadania_LR`
- `start`

Bo tam najprawdopodobniej siedzi:
- ustawianie `Status`
- wybór finalnego kandydata
- spinanie `Wynik EMC-LR` z końcowym DOC
