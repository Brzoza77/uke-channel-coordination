# Access VBA i Makra

Najważniejsze artefakty:
- `logs/access_vba_modules_analysis_20260316.json`
- `logs/access_vba_status_traces_20260316.json`
- `logs/access_status_assignment_20260316.json`
- `logs/access_candidate_state_flow_20260316.json`
- `logs/access_qualification_flow_20260316.json`

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

Po dalszej analizie:
- `utworz_wynik_zaklocen` wygląda na tor NSS/sat -> LR
- głównym targetem dla naziemnego benchmarku `Wynik EMC-LR` jest raczej `wyniki_EMC_fk`

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
1. podczas tworzenia kandydata Access ustawia roboczy znacznik:
   - `DobryKanal = "0"`
2. kandydat wchodzi do przebiegu proceduralnego z `statusfk = 1`
3. Access otwiera dane pomocnicze:
   - `Nadajnik`
   - `maski`
   - `charakterystyka`
4. dla gałęzi problemowej / zagranicznej wywoływane jest:
   - `obliczenia_EMC_POL_ZAGR`
5. jeśli gałąź zagraniczna zwróci `status_fkand_zagr = 2`, to:
   - `status_fkand = 2`
6. jeśli wykryty jest problem kompatybilności (`TD > 1`), Access:
   - dopisuje rekord do `problem_kons`
   - oznacza `stat_koor`
7. równolegle utrzymuje osobny stan problemu:
   - `Problem.decyzja_o_koordynacji = IIf([d11] > [dgr], 1, 2)`
8. Access eksportuje payloady:
   - `ExportTx_przeslo`
   - `ExportRx_przeslo`
   i wykonuje:
   - `wpisz_dane_koor`
   - `kwalifikacja_koor`
   - `Kwalifikacja_EMC`
   - `Stan_wniosku_po_weryfikacji`
9. na końcu VBA aktualizuje `Czestotliwosc kandydujaca.status`
10. warstwa raportowa konsumuje kandydaty z `Status = 2`

Najważniejsze ograniczenie:
- nadal nie mamy pełnego kodu VBA 1:1
- ale już mamy wystarczająco mocne dowody, że:
  - `Status = 1` jest stanem startowym/domyslnym
  - `Status = 2` jest stanem promowanym proceduralnie i używanym dalej przez wydruk
  - `DobryKanal` i `Problem.decyzja_o_koordynacji` wyglądają na osobne stany pomocnicze, a nie synonimy końcowego `Status`

## Warstwy kwalifikacji

Na dziś najbardziej prawdopodobny podział proceduralny Accessa wygląda tak:

1. warstwa planu / wrapper krajowy
   - `Kwalifikacja_EMC_kraj`
   - `generuj_fk`
   - `druk_wynikow`
   - wygląda na przebieg generujący i iterujący kandydaty w ramach planu

2. warstwa per-kandydat
   - `ExportTx_przeslo`
   - `ExportRx_przeslo`
   - `wpisz_dane_koor`
   - `kwalifikacja_koor`
   - `Kwalifikacja_EMC`
   - `Stan_wniosku_po_weryfikacji`
   - wygląda na bezpośrednią weryfikację konkretnego kandydata po przygotowaniu payloadu EMC

3. warstwa promocji stanu
   - `wstaw_status`
   - `Koniec_obliczen`
   - proceduralny `UPDATE` tabeli `Czestotliwosc kandydujaca`

Najważniejszy wniosek z tej warstwy:
- `Kwalifikacja_EMC_kraj` najpewniej nie jest samym setterem końcowego `Status`
- bliżej końcowej decyzji wygląda para:
  - `Kwalifikacja_EMC`
  - `Stan_wniosku_po_weryfikacji`
- a samo wpisanie `Status` nadal wygląda na osobny krok proceduralny VBA

## Writer wyników EMC

Najważniejszy artefakt:
- `logs/access_result_writers_20260316.json`

### `utworz_wynik_zaklocen`
- ślady:
  - zapis wyników zakłóceń dla pojedynczej NSS i stacji linii radiowych
  - `stacja_LR` w bazie satelitarnej
  - `zapisz_dane_o_zakloceniu`

Wniosek:
- to nie wygląda na główny writer naziemnego benchmarku `Wynik EMC-LR`
- raczej osobny tor raportowania NSS/sat -> LR

### `wyniki_EMC_fk`
- ślady:
  - `wpisanie 1 rekordu wyniku`
  - `Sub wyniki_EMC_fk(db, fid As Long, marg As Variant, dz As Double, idprzesla As Long, wsk As Byte, metoda As Byte, blad As Long, opis_bledu As String)`
  - `Wynik EMC-LR`
  - `FKandydujaca_b#`
  - `metoda=2`
  - `brak maski`
  - `brak nadajnika`
  - `Nfd_Md = 0`

Wniosek:
- to jest dziś najbardziej obiecujące miejsce dalszego reverse engineeringu warstwy obliczeniowej
- właśnie tutaj najpewniej trzeba odtworzyć:
  - znaczenie `marg`
  - znaczenie `dz`
  - znaczenie `wsk`
  - gałęzie `metoda`
  - zachowanie przy brakach maski/nadajnika

Najbardziej prawdopodobna semantyka parametrów:
- `fid`
  - odpowiada `Wynik EMC-LR.[FKandydujaca_b#]`
- `idprzesla`
  - odpowiada `Wynik EMC-LR.[Przęsło_i#]`
- `metoda`
  - odpowiada `Wynik EMC-LR.metoda`
  - `metoda = 2` należy do gałęzi zagranicznej
- `blad`
  - odpowiada `Wynik EMC-LR.blad_obliczen`
- `opis_bledu`
  - odpowiada `Wynik EMC-LR.opis_bledu`
- `marg`
  - wygląda na pojedynczy kierunkowy margines zapisywany do:
    - `Margines_b-i`
    - albo `Margines_i-b`
- `dz`
  - wygląda na pojedynczą kierunkową odległość zapisywaną do:
    - `Odleglosc_b-i`
    - albo `Odleglosc_i-b`
- `wsk`
  - najpewniej wybiera stronę zapisu:
    - `b-i`
    - albo `i-b`
- `sprz`
  - wygląda na pomocniczą flagę relacji / sprzężenia używaną razem z `wsk`

Dodatkowe ważne ślady z tego samego bloku:
- obok writer-a pojawiają się:
  - `TlumCyrk_NO`
  - `dd_n`
  - `dd_o`
  - `wsp_szum_i`
  - `moc_szumow`
  - `distance`
- przed wejściem w EMC Access buduje `SELECT` z:
  - `PRZESLO.[Tłumienie cyrkulatorów-n] AS TlumCyrkN`
  - `PRZESLO.[Moc nadajnika] AS Moc`
  - współrzędnymi `xN/yN/xO/yO`
  - kątami ekranu anten

To wzmacnia wniosek, że `wyniki_EMC_fk` siedzi bezpośrednio przy właściwej warstwie obliczeniowej LR, a nie tylko przy raporcie.

Wniosek praktyczny z aktualnej `_349`:
- dla `75/85 GHz` wartości `TlumCyrk` są zwykle małe:
  - mediana `0.0 dB`
  - `p90 = 0.5 dB`
  - najczęstsze mody:
    - `75/85A250`: `0.0/0.0` i `0.5/0.5`
    - `75/85A125`: prawie zawsze `0.0/0.0`
    - `75/85A62.5`: głównie `0.5/0.5` lub `0.0/0.0`
- to znaczy, że brak `TlumCyrk` nadal warto modelować dla zgodności z Accessem,
- ale sam ten parametr nie tłumaczy już residuali rzędu kilku-kilkunastu dB na benchmarku.

Aktualny raport tej warstwy:
- `logs/access_wyniki_emc_fk_semantics_20260316.json`

Nowy twardy ślad call site:
- `wyniki_EMC_prz db, filen![przeslo#], Marg_n, dz, file![Przęsło#], 1, 1, blad, "", "POL"`
- `wyniki_EMC_prz db, filen![przeslo#], Marg_o, Dzi, file![Przęsło#], 2, 1, blad, "", "POL"`

Wniosek:
- `wsk` nie jest już tylko hipotezą:
  - `wsk = 1` dla gałęzi `Marg_n / dz`
  - `wsk = 2` dla gałęzi `Marg_o / Dzi`
- `metoda = 1` jest krajowym writer path
- `wyniki_EMC_prz` wygląda na cienki wrapper nad tym samym modelem zapisu, który na poziomie kandydatów realizuje `wyniki_EMC_fk`

Wciąż otwarte pozostaje:
- czy `Marg_n` mapuje się na:
  - `Margines_b-i`
  - czy `Margines_i-b`
- i analogicznie:
  - `dz`
  - vs `Dzi`

Raport call site:
- `logs/access_writer_callsite_20260316.json`

Wynik testu hipotez:
- `H1`: `wsk=1 -> b-i`, `wsk=2 -> i-b`
  - nie ma dziś mocnego wsparcia
- `H2`: `wsk=1 -> i-b`, `wsk=2 -> b-i`
  - też nie ma dziś mocnego wsparcia
- `H3`: `wsk=1/2` wybiera gałąź `N/O`, a końcowe mapowanie do `b-i` / `i-b` dzieje się warstwę później
  - to jest obecnie najlepiej wsparta hipoteza

Dlaczego:
- oba wrappery `Marg_n` i `Marg_o` są opisane jako degradacja odbiornika `i-tego przęsła`
- samo odwrócenie etykiety `b-i` / `i-b` nie zmienia benchmarku liczbowo
- to sugeruje, że brakująca logika siedzi między:
  - `wyniki_EMC_prz`
  - a `wyniki_EMC_fk`

Raport testu:
- `logs/access_writer_hypotheses_20260316.json`

## Warstwa aktualizacji `fkand`

Najmocniejszy nowy trop nie wskazuje na prosty flip:
- `wsk=1 -> b-i`
- `wsk=2 -> i-b`

Zamiast tego Access wygląda tak, jakby robił osobny etap pomiędzy:
- `wyniki_EMC_prz`
- a `wyniki_EMC_fk`

Najważniejsze ślady:
- w jednym bloku lokalnych zmiennych współwystępują:
  - `jest_wynikN`
  - `jest_wynikO`
  - `Marg_n`
  - `Marg_o`
  - `MargNad`
  - `MargOdb`
  - `N-nad`
  - `N-odb`
  - `statusfk`
  - `p_czy_fk`
- osobny komentarz proceduralny:
  - `FID - identyfikator fkand lub zero(null) dla przesla`
  - `p_czy_fk = 0 dla przęsła`
  - `p_czy_fk = 1 dla fkand`
- zaraz po wrapperach:
  - `wyniki_EMC_prz ... Marg_n ...`
  - `wyniki_EMC_prz ... Marg_o ...`
  pojawia się:
  - `aktualizacja parametr`
  - `w fkand`
  - `Czestotliwosc kandydujaca`
  - `[FKandydujaca#] = ...`

Najbardziej prawdopodobny przebieg:
1. Access liczy dwie gałęzie krajowe:
   - `Marg_n / dz`
   - `Marg_o / Dzi`
2. zapisuje je wrapperem `wyniki_EMC_prz`
3. potem wchodzi w blok:
   - `aktualizacja parametr w fkand`
4. tam agreguje wynik do pól kandydata:
   - `MargNad`
   - `MargOdb`
   - `N-nad`
   - `N-odb`
5. dopiero potem używa:
   - `wyniki_EMC_fk`
   - i późniejszych warstw statusu / wydruku

Wniosek:
- brakująca warstwa nie jest dziś problemem etykiety `b-i/i-b`
- to proceduralna aktualizacja stanu kandydata `fkand`
- właśnie tam Access najpewniej scala surowe gałęzie `N/O` do kierunkowych marginesów używanych dalej w workflow

Raport tej warstwy:
- `logs/access_fk_update_layer_20260316.json`

## Margin traces w VBA

Przeszukanie `MDB` stricte pod kątem rodziny `margin` dało ważne rozróżnienie:

Jawnie widoczne w stringach:
- `Marg_n`
- `Marg_o`
- `MargNad`
- `MargOdb`
- `N-nad`
- `N-odb`

Co jest potwierdzone:
- `Marg_n` i `Marg_o` są literalnie opisane i przekazywane do:
  - `wyniki_EMC_prz`
- `MargNad`, `MargOdb`, `N-nad`, `N-odb` występują w tym samym bloku lokalnych zmiennych,
  co wskazuje na ich użycie w tej samej procedurze
- po `wyniki_EMC_prz` pojawia się blok:
  - `aktualizacja parametr w fkand`

Co jest równie ważne:
- nie znaleziono literalnego SQL-a w rodzaju:
  - `UPDATE ... SET [MargNad] = ...`
  - `UPDATE ... SET [MargOdb] = ...`
  - `UPDATE ... SET [N-nad] = ...`
  - `UPDATE ... SET [N-odb] = ...`
- natomiast dla innych pól kandydata są jawne SQL-e:
  - `UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET ... [status] = ...`
  - `UPDATE [Czestotliwosc kandydujaca] SET T_dane_koor = Null, R_dane_koor = Null ...`

Wniosek:
- Access z dużym prawdopodobieństwem zapisuje `MargNad/MargOdb/N-nad/N-odb`
  inaczej niż przez długi, literalny `UPDATE` osadzony w stringach
- najbardziej prawdopodobne ścieżki:
  - `DAO.Recordset.Edit / Update`
  - krótki dynamiczny SQL składany z fragmentów
  - albo fragment VBA, którego pełnej treści nie widać w obecnym zrzucie `strings`

Raport:
- `logs/access_margin_traces_20260316.json`

## Wąski search `Recordset/Edit/Update` dla `fkand`

Zawężone przeszukanie pod kątem:
- `Recordset`
- `FindFirst`
- `NoMatch`
- `.Edit`
- `.Update`
- `AddNew`
- `Czestotliwosc kandydujaca`
- `FKandydujaca#`

dało ważne rozróżnienie.

Potwierdzone proceduralne zapisy:
1. `problem_kons`
   - `filepk.AddNew`
   - `filepk![FKandydujaca#] = fid`
   - `filepk![TD p-gr] = td_o`
   - `filepk.Update`

2. warstwa `Dane_EMC` / mask nadajnika
   - `wpis_maski file, maska, ilk, i`
   - `file.Update`

3. marker poszukiwanego etapu
   - `aktualizacja parametr`
   - `w fkand`
   - `Czestotliwosc kandydujaca`
   - `[FKandydujaca#] = ...`

Ale nadal nie ma jawnie odzyskanego fragmentu w rodzaju:
- `file![MargNad] = ...`
- `file![MargOdb] = ...`
- `file![N-nad] = ...`
- `file![N-odb] = ...`

Wniosek:
- Access korzysta tu z DAO/Recordset w sąsiednich częściach workflow,
- ale literalny setter marginów `fkand` nadal nie został odzyskany.

Raport:
- `logs/access_fkand_recordset_search_20260316.json`

## Mapa obiektów DAO

Po złożeniu dotychczasowych śladów da się już zrobić użyteczną mapę nazw
`DAO/Recordset/QueryDef` do ich lokalnych ról w workflow Accessa.

Najważniejsze mapowania:
- `dbb`
  - `CurrentDb`, główny uchwyt bazy
- `db`
  - lokalny uchwyt bazy / `CurrentDb`
- `myq`
  - obiekt `QueryDef`, silnie przeciążony między procedurami
- `filen`
  - przeciążony `Recordset`
  - w torze naziemnym:
    - `przeslo badane`
  - w torze NSS:
    - wynik zapytania selekcyjnego
- `filep`
  - rekordset przęsła problemowego / zakłócającego
- `filepk`
  - writer do `problem_kons`
- `file`
  - writer warstwy `Dane_EMC` / masek nadajnika
- `set_wybor`
  - rekordset selekcji NSS/LR
- `zap_wybor`
  - parametryzowany `QueryDef` dla tej selekcji
- `zap_char_LR` / `set_char_LR`
  - pobranie charakterystyk anten LR
- `zap_stacja_SS`
  - lookup stacji satelitarnej

Wniosek:
- nazwy `file*` nie są globalnie unikalne
- trzeba je czytać proceduralnie, blok po bloku
- to jest ważne, bo inaczej łatwo pomylić:
  - zapis `problem_kons`
  - zapis `Dane_EMC`
  - i szukany zapis `fkand`

Raport:
- `logs/access_dao_object_map_20260316.json`

## Systemowe tabele Accessa i blok końcowy kandydata

Dało się wejść głębiej w systemowe tabele Accessa, jeśli ich prawdziwe `Id`
zostaną pobrane z `MSysObjects` i dopisane do katalogu parsera.

Najważniejsze ustalenia:
- `MSysObjects` trzyma stabilne `Id` dla modułów VBA i makr:
  - moduły:
    - `Aktualizacja_bazy`
    - `Master`
    - `Zadania_LR`
    - `Zadania_LR_Tlumienie`
    - `koordynacja_zagr`
    - itd.
  - makra:
    - `autoexec`
    - `start`
    - `klepsydra_nie`
    - `Uaktualnienie bazy`
- `MSysNavPaneObjectIDs` potwierdza te same identyfikatory obiektów:
  - moduły jako `Type = 32775`
  - makra jako `Type = 32770`
- `MSysAccessObjects` da się sparsować po dopisaniu właściwego `Id`,
  ale na obecnym poziomie parsera:
  - `row_count = 141`
  - `nonempty_data_rows = 0`
  - więc nie daje jeszcze bezpośredniego payloadu z kodem VBA

To oznacza:
- systemowe tabele są realnym źródłem mapowania obiektów Accessa,
- ale nie są dziś prostą drogą do odzyskania pełnych ciał modułów.

Równolegle dało się jeszcze lepiej uporządkować blok końcowy procedury
kandydata. Najmocniej potwierdzone markery to:
- `statusfk = 1`
- `aktualizacja parametr`
- `w fkand`
- `Czestotliwosc kandydujaca`
- `filepk.Update`
- `ExportTx_przeslo`
- `ExportRx_przeslo`
- `wpisz_dane_koor`
- `kwalifikacja_koor`
- `Kwalifikacja_EMC`
- `Stan_wniosku_po_weryfikacji`
- `wstaw_status`
- `status_kand`

Najbardziej prawdopodobny przebieg tej warstwy wygląda teraz tak:
1. zapis `problem_kons`
2. eksport `Tx/Rx`
3. `wpisz_dane_koor`
4. `kwalifikacja_koor`
5. `Kwalifikacja_EMC`
6. `Stan_wniosku_po_weryfikacji`
7. końcowa promocja stanu przez `wstaw_status` / `status_kand`

To nie daje jeszcze literalnego settera `MargNad/MargOdb`, ale wyraźnie
pokazuje, że końcowa promocja kandydata dzieje się po warstwie weryfikacji,
a nie w samym writerze wyników parowych.

Raport:
- `logs/access_system_tables_and_state_flow_20260316.json`

## `wstaw_status` i finalna promocja kandydata

Osobna analiza `wstaw_status` dała już dość spójny obraz końcówki workflow.

Najważniejsze ustalenia:
- `statusfk = 1` pozostaje najczytelniejszym punktem inicjalizacji
  proceduralnego stanu kandydata
- jedyna odzyskana jawnie promocja tego stanu to:
  - `If status_fkand_zagr = 2 Then status_fkand = 2`
- przy błędzie Access może przerwać ścieżkę przez:
  - `Koniec_obliczen dbb, fid(i), status_fkand`
- `Stan_wniosku_po_weryfikacji(...)` występuje po:
  - `ExportTx_przeslo`
  - `ExportRx_przeslo`
  - `wpisz_dane_koor`
  - `kwalifikacja_koor`
  - `Kwalifikacja_EMC`
- `wstaw_status` i `status_kand` siedzą w tej samej warstwie leksykalnej co
  znaczniki post-weryfikacyjne

Najbardziej prawdopodobna interpretacja:
1. `statusfk` zbiera stan po drodze
2. `Stan_wniosku_po_weryfikacji` kończy warstwę kwalifikacji
3. `wstaw_status` używa wyniku tej warstwy do wyznaczenia końcowego
   `status_kand`
4. gdzieś obok wykonywany jest literalny update:
   - `UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [status] = ...`

Czyli:
- `wstaw_status` wygląda bardziej jak helper decyzyjny / dispatcher
- a nie jak sam writer surowych wyników EMC

Otwarte pytania:
- czy `status_kand` jest lokalną zmienną liczbową, czy wynikiem pomocniczej funkcji
- czy `wstaw_status` wykonuje zapis bezpośrednio, czy tylko wyznacza wartość
  później wpisywaną przez dynamiczny SQL
- czy tor krajowy może podnieść `statusfk` do `2` bez przejścia przez gałąź
  `status_fkand_zagr`

Raport:
- `logs/access_wstaw_status_20260316.json`

## Najbardziej sensowny następny krok

Skupić dalszy reverse engineering na:
- call site `wyniki_EMC_fk`
- `Master`
- `Zadania_LR`
- `start`

Bo tam najprawdopodobniej siedzi:
- wybór strony `b-i` vs `i-b`
- przypisanie `wsk`
- spinanie `Wynik EMC-LR` z końcowym DOC
- końcowe ustawianie `Status`
