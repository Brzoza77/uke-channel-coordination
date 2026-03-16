# Reverse Engineering workflow UKE

## Cel

Odtworzyc, jak najprawdopodobniej przebiega proces konsultacyjny UKE dla linii radiowych, na podstawie:
- struktury MDB `LR_Konsultacja_349.mdb`
- tabel wejściowych i wynikowych
- wyników dokumentów konsultacyjnych `wlr-doc`
- obecnych zachowan naszego silnika

To nie jest jeszcze dowód formalny 1:1, ale jest to roboczy model procesu, oparty o dane, które udało się potwierdzić.

## Najważniejsze tabele MDB

### Dane wejściowe / parametry obliczeń

#### `Dane_EMC`

Tabela wygląda jak zbiór wejść dla przęsła badanego w procesie EMC.

Potwierdzone pola:
- `Przeslo#`
- `Numer_przesla`
- `Antena_nad`
- `Producent_ant_N`
- `Antena_odb`
- `Producent_ant_O`
- `Liczba_szumowa`
- `Moc_nadajnika`
- `Tlum_cyrk_N`
- `Tlum_cyrk_O`
- `KierPromN`
- `KierPromO`
- `KatelewN`
- `KatelewO`
- `F_przydzielona`
- `F_dolna`
- `F_górna`
- `Szerokosc_kanalu`
- `Dupleks`

Interpretacja:
- to wygląda na „zmaterializowane” wejście do liczeń EMC
- zawiera nie tylko częstotliwość i szerokość kanału, ale też:
  - kierunki promieniowania
  - kąty elewacji
  - liczbę szumową
  - moc nadajnika
  - tłumienia toru/cyrkulatora

Wniosek:
- UKE prawdopodobnie liczy EMC nie bezpośrednio z surowego WLR, tylko z pośredniego modelu wejściowego podobnego do `Dane_EMC`

#### `Czestotliwosc kandydujaca`

Nazwa sugeruje tabelę kandydatów częstotliwości / kanałów.

Interpretacja:
- workflow UKE najpewniej generuje kandydatów kanałowych oddzielnie od samych obliczeń EMC
- to pasuje do naszego modelu:
  - `generate_channel_candidates()`
- pojedynczy rekord nie opisuje jeszcze pełnego kanału duplexowego
- w praktyce jeden wiersz odpowiada jednemu kierunkowi nadawczemu (`kod_nadawczej = A` albo `B`)
- pełny wariant duplexowy powstaje przez sparowanie dwóch rekordów:
  - tego samego `numer_pary_f`
  - tej samej `polaryzacja`
  - z przeciwnymi wartościami `kod_nadawczej`

Wniosek:
- selekcja finalnego kanału w UKE wygląda na proces dwuetapowy:
  - najpierw kandydaci kierunkowi
  - potem sparowanie do kanału duplexowego i agregacja marginesów

#### `NADAJNIK`

Potwierdzone wcześniej:
- `Typ nadajnika`
- `Wsp szumów`
- `Szer_pasma_odb`
- `Homologacja#`
- `ATPC`
- oraz punkty Tx/Rx dla części urządzeń

Interpretacja:
- UKE ma radio-specyficzne parametry odbiornika/nadajnika
- to może być źródło:
  - liczby szumowej
  - selektywności
  - zachowania ATPC
  - szerokości pasma odbiornika

#### `maski`

Potwierdzone:
- wpisy zależne od pasma (`fd`, `fg`)
- wpisy zależne od szerokości kanału (`szer1`, `szer2`)
- punkty `(f1..f6, att1..att6)`

Interpretacja:
- to wygląda na katalog masek / selektywności lub wymaganych tłumień zależnych od odstępu częstotliwości
- bardzo mocno pasuje do modelowania adjacent-channel

#### `ANTENA`, `PASMO ANTENY`, `CHARAKTERYSTYKA`

Potwierdzone:
- dają realne charakterystyki anten
- pozwalają odtworzyć tłumienie off-axis

Interpretacja:
- UKE korzysta z realnych danych antenowych, nie tylko z heurystyki kąta

### Dane przestrzenne / terenowe

#### `ELEWACJA_HORYZONTU`

Potwierdzone pola:
- `Id_stacji`
- `Azymut`
- `Kat_elewacji`
- `d`

Interpretacja:
- bardzo prawdopodobne źródło preobliczonego horyzontu lub przesłonięcia terenowego
- możliwe użycie:
  - ograniczenie widoczności
  - korekta propagacji
  - ocena toru poza prostym LOS

#### `ZASIEG`

Potwierdzone pola:
- `Kanal#`
- `Azymut`
- `Dystans_mod1`
- `Dystans_mod2`
- `Zysk_energetyczny`

Interpretacja:
- możliwe preobliczone zasięgi zależne od kanału/azymutu/modulacji
- to może być używane jako szybki filtr przestrzenny lub trigger

### Dane wynikowe / decyzyjne

#### `Wynik EMC-LR`

Potwierdzone pola:
- `FKandydujaca_b#`
- `Przęsło_i#`
- `Metoda`
- `Odleglosc_b-i`
- `Odleglosc_i-b`
- `Margines_b-i`
- `Margines_i-b`
- `blad_obliczen`
- `opis_bledu`
- `Data_utworzenia`
- `Kraj`

Interpretacja:
- to wygląda jak tabela wyników dla konkretnej pary:
  - kanał kandydujący
  - przęsło interferujące
- `Margines_b-i` i `Margines_i-b` najpewniej odpowiadają dwóm kierunkom ochrony:
  - badany -> interferujący
  - interferujący -> badany

Wniosek:
- UKE prawdopodobnie podejmuje decyzję na bazie marginesów EMC, nie tylko na bazie uproszczonego progu typu `TD < 1 dB`

#### `DECYZJA`

Nazwa sugeruje końcową decyzję procesu.

Interpretacja:
- prawdopodobnie wiąże wynik per kandydat z decyzją:
  - tak
  - nie
  - warunkowo

Aktualny ważny wniosek z lokalnej SQLite:
- konsultacyjne przęsła z tabeli `Czestotliwosc kandydujaca` dla `LR_Konsultacja_349`
  nie występują w `Przeslo decyzji`
- nie występują też w `Przeslo-zakres-plan`

Wniosek praktyczny:
- finalny wybór kanału dla konsultacji dzieje się przed warstwą administracyjną `DECYZJA`
- `DECYZJA` wygląda bardziej na zapis decyzji dla istniejących pozwoleń niż na miejsce,
  z którego da się bezpośrednio odtworzyć ranking kanałów konsultacyjnych

#### `PROCES_AP28`

Interpretacja:
- bardzo możliwe, że to tabela sterująca lub rejestrująca przebieg procesu koordynacyjnego / konsultacyjnego

## Hipoteza workflow UKE

Najbardziej prawdopodobny przebieg procesu wygląda tak:

1. Rejestracja badanego przęsła i parametrów wejściowych
   - źródło: `PRZESLO`, `Dane_EMC`, `NADAJNIK`, `ANTENA`

2. Wygenerowanie kandydatów kanałowych
   - źródło: `Czestotliwosc kandydujaca`

3. Dobór przęseł potencjalnie interferujących
   - filtr przestrzenny i/lub azymutalny
   - możliwe wsparcie:
     - `ZASIEG`
     - `ELEWACJA_HORYZONTU`

4. Dla każdej pary:
   - kandydat kanałowy
   - przęsło interferujące
   liczony jest wynik EMC
   - źródło wejść: `Dane_EMC`
   - źródło charakterystyk: `ANTENA`, `CHARAKTERYSTYKA`
   - źródło masek/selektywności: `maski`, możliwie `NADAJNIK`

5. Wynik per para trafia do `Wynik EMC-LR`
   - z marginesami w obu kierunkach
   - plus informacją o metodzie i ewentualnym błędzie

6. Na podstawie najgorszych marginesów powstaje końcowa decyzja
   - najprawdopodobniej jeszcze w warstwie konsultacyjnej, przed `DECYZJA`
   - a w dokumentach wynikowych UKE użytkownik widzi:
     - degradacje
     - linki zakłócające
     - numery pozwoleń
     - wynik tak/nie

## Odtworzona metodologia wyboru finalnego kanału

Na podstawie tabel:
- `Czestotliwosc kandydujaca`
- `Dane_EMC`
- `Wynik EMC-LR`
- `problem_kons`

najbardziej prawdopodobna logika wyboru kanału wygląda tak:

## Access EMC End-to-End

Na podstawie zapisanych `QueryDef` w `LR_Konsultacja_349.mdb` udało się odtworzyć
bardziej literalny przebieg Accessa od wejścia EMC do wiersza DOC.

Najważniejszy artefakt:
- `logs/access_emc_end_to_end_20260316.json`

Przebieg:

1. `jest_nadajnik_w_bazie`
   - Access dopasowuje radio po:
     - typie
     - producencie
     - zakresie częstotliwości
     - zakresie szerokości kanału
   - to jest najbliższy odpowiednik doboru request-side profilu radia.

2. `Dane_EMC_druk`
   - Access wzbogaca `Dane_EMC` o snapshoty:
     - `Nadajnik_kons`
     - `Antena_kons`
     - `Producent_kons`

3. `ExportTx_przeslo` / `ExportRx_przeslo`
   - Access serializuje payloady `T_dane_koor` / `R_dane_koor`
   - payload zawiera m.in.:
     - częstotliwość
     - szerokość kanału
     - maskę radia
     - azymut główny
     - elewację główną
     - moc Tx
     - poziom szumów Rx
     - tłumienie cyrkulatora
     - producenta i typ radia
     - producenta i typ anteny
     - charakterystyki copol/crosspol

4. `Czestotliwosc kandydujaca`
   - kandydat przechowuje:
     - `T_dane_koor`
     - `R_dane_koor`
     - `MargNad`
     - `MargOdb`
     - `Status`

5. `Dane_do_EMC_BENNER`
   - Access łączy:
     - `Czestotliwosc kandydujaca`
     - `Dane_EMC`
   - po `Przeslo#`
   - i przygotowuje wejście do obliczeń EMC dla konkretnego `FKandydujaca#`

6. `Wynik EMC-LR`
   - wynik parowy EMC:
     - `FKandydujaca_b#`
     - `Przęsło_i#`
     - `Margines_b-i`
     - `Margines_i-b`
     - `Metoda`
     - `blad_obliczen`

7. `Wyniki_b-i` / `Wyniki_i-b`
   - Access buduje z `Wynik EMC-LR` wiersze widoczne w wydruku DOC
   - filtruje:
     - `Margines > 1`
     - `Metoda < 2`
   - i dopiero tutaj dokleja:
     - permit (`DECYZJA.NrDecyzji`)
     - stacje
     - operatora
     - radio

8. `Wyniki_do_wydruku`
   - Access wybiera kandydaty do wydruku po:
     - `Numer_przesla`
     - `Status = 2`

9. `Pary_fk_ABprim` / `Pary_fk_AprimB`
   - Access paruje rekordy `A/B` do kanału duplexowego:
     - ten sam `Numer_przesla`
     - ta sama `Polaryzacja`
     - numer kanału z apostrofem i bez apostrofu

Potwierdzone zależności payloadu:
- `payload main azimuth ~= Dane_EMC.KierPromN/O`
- `payload main elevation ~= Dane_EMC.KatElewN/O`
- `payload tx_power_dbw = Dane_EMC.Moc_nadajnika - 30`
- `payload noise_floor_dbw = -174 dBm/Hz + 10log10(BW_Hz) + NF`, przeliczone do dBW
- `payload circulator_loss_db ~= Dane_EMC.Tlum_cyrk_N/O`

Wniosek praktyczny:
- nasz `EMCInput` powinien jawnie przenosić:
  - azymut
  - elewację
  - parametry maski
  - poziom szumów / NF
  - tłumienia torowe
- sama obecność azymutu i elewacji w payloadzie nie dowodzi jeszcze, że Access
  stosuje dodatkową 3D dyskryminację ponad standardowe użycie charakterystyk antenowych.

## Status i rodzina `Wyniki_*`

Najważniejszy artefakt:
- `logs/access_status_results_analysis_20260316.json`

Potwierdzone:
- `Wyniki_b-i` / `Wyniki_i-b` budują naziemne wiersze DOC z `Wynik EMC-LR`
  tylko wtedy, gdy:
  - `Margines_b-i > 1` lub `Margines_i-b > 1`
  - `Metoda < 2`
- `Wyniki_b-iz` / `Wyniki_iz-b` są osobną gałęzią zagraniczną
  z `Wynik EMC-LR`, gdy:
  - `Metoda = 2`
- `Wyniki_b-iss` / `Wyniki_iss-b` są osobną gałęzią SS
  opartą o `Wynik EMC-SS`
- `Wyniki_do_wydruku` wybiera kandydaty po:
  - `Numer_przesla`
  - `Status = 2`
- `Wyniki do wydruku_tab4` używa tych samych pól kandydata,
  ale bez filtra `Status = 2`

Wniosek:
- `Status` w `Czestotliwosc kandydujaca` nie wygląda na surowy wynik EMC,
  tylko na flagę workflow / warstwy wydruku
- `Wynik EMC-LR` jest źródłem surowych konfliktów parowych
- `Wyniki_*` dopiero zamieniają ten wynik na końcowe wiersze raportowe

Co jeszcze nie jest dowiedzione:
- dokładne mapowanie kodów `Status` na etykiety użytkowe typu
  `ACCEPTED / CONDITIONAL / REJECTED`
- czy `Status = 2` oznacza:
  - kandydat wybrany do wydruku
  - kandydat raportowany
  - kandydat konfliktowy
  - czy po prostu kandydat z określonej sekcji raportu

Praktycznie:
- nie powinniśmy próbować mapować `Status` 1:1 na nasz końcowy status kanału
  bez kolejnych danych
- bardziej wiarygodne jest traktowanie:
  - `Wynik EMC-LR` jako warstwy obliczeniowej
  - `Status` jako warstwy organizacji / wydruku / wyboru kandydata

### Gdzie najpewniej ustawiany jest `Status = 2`

Najważniejszy artefakt:
- `logs/access_status_assignment_20260316.json`

Potwierdzone:
- `Wyniki_do_wydruku` konsumuje `Status = 2`
- `Wyniki do wydruku_tab4` czyta te same kandydaty bez tego filtra
- w zapisanych `QueryDef` nie udało się znaleźć jednoznacznej kwerendy typu:
  - `UPDATE Czestotliwosc kandydujaca SET Status = 2`

Wniosek:
- samo ustawienie `Status = 2` najprawdopodobniej nie siedzi w widocznych kwerendach `SELECT`
- najbardziej prawdopodobne miejsce tej logiki to:
  - moduły VBA
    - `Zadania_LR`
    - `Zadania_LR_Tlumienie`
    - `Master`
  - albo makra:
    - `start`
    - `autoexec`

Praktycznie:
- `Status = 2` traktujemy na dziś jako flagę wyboru kandydata do końcowej ścieżki raportowej
- ale nie zakładamy jeszcze, że oznacza on bezpośrednio:
  - `ACCEPTED`
  - `best`
  - lub inną etykietę użytkową

### Twardy ślad VBA aktualizującego kandydatów

Najważniejszy artefakt:
- `logs/access_vba_status_traces_20260316.json`
- `logs/access_candidate_state_flow_20260316.json`

W surowych stringach `LR_Konsultacja_349.mdb` udało się potwierdzić ślady VBA:

- `UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].[status] = ... WHERE ((([Czestotliwosc kandydujaca].[FKandydujaca#])= ...`
- `strpyt = "UPDATE [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].T_dane_koor = Null, [Czestotliwosc kandydujaca].R_dane_koor = Null WHERE ((([Czestotliwosc kandydujaca].[FKandydujaca#])=" & fid & "));"`
- `Sub wyniki_EMC_fk(db, fid As Long, marg As Variant, dz As Double, idprzesla As Long, wsk As Byte, metoda As Byte, blad As Long, opis_bledu As String)`
- `Set dbb = CurrentDb`
- użycie `QueryDef`, `OpenRecordset`, `CurrentProject.Path`, `Zadania_LR`

Ważny kontekst:
- ślad `UPDATE ... status = ...` pojawia się obok kodu związanego z:
  - doborem charakterystyki anteny
  - `kod_polaryzacji`
  - obsługą błędów typu:
    - brak charakterystyki
    - za mała liczba punktów na charakterystyce

Wniosek:
- `Status` kandydata jest aktywnie ustawiany przez kod proceduralny VBA
- ścieżka końcowa Accessa wygląda więc bardziej tak:
  - wygeneruj kandydatów
  - przygotuj payloady EMC
  - sprawdź warunki pomocnicze i charakterystyki
  - uruchom EMC / zapisz `Wynik EMC-LR`
  - zaktualizuj rekord `Czestotliwosc kandydujaca`
  - wybierz do raportu kandydaty z `Status = 2`

### Co już wiemy o przejściu `Status 1 -> 2`

Najmocniejsze ślady z `MDB`:
- `statusfk = 1`
- `If status_fkand_zagr = 2 Then status_fkand = 2`
- `If blad > 0 Then Koniec_obliczen dbb, fid(i), status_fkand: Exit Function`
- `UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [Czestotliwosc kandydujaca].[status] = ...`
- identyfikatory:
  - `wstaw_status`
  - `status_kand`
  - `kwalifikacja_koor`
  - `Kwalifikacja_EMC`
  - `Stan_wniosku_po_weryfikacji`

Najbardziej prawdopodobny przebieg:
1. Podczas tworzenia kandydatów Access ustawia pomocniczy znacznik:
   - `DobryKanal = "0"`
2. Access inicjalizuje kandydata proceduralnego jako `statusfk = 1`.
3. Dla gałęzi problemowej / zagranicznej wywołuje `obliczenia_EMC_POL_ZAGR`.
4. Jeżeli `status_fkand_zagr = 2`, to kandydat lokalny dostaje promocję:
   - `status_fkand = 2`
5. Jeżeli występuje problem kompatybilności (`TD > 1`), Access:
   - zapisuje rekord `problem_kons`
   - oznacza `stat_koor`
6. Osobno utrzymuje stan problemu:
   - `Problem.decyzja_o_koordynacji = IIf([d11] > [dgr], 1, 2)`
7. Access zapisuje dane koordynacyjne i wykonuje:
   - `wpisz_dane_koor`
   - `kwalifikacja_koor`
   - `Kwalifikacja_EMC`
   - `Stan_wniosku_po_weryfikacji`
8. Na końcu procedura VBA wykonuje `UPDATE` rekordu w `Czestotliwosc kandydujaca`.
9. Warstwa `Wyniki_do_wydruku` bierze już tylko kandydaty z `Status = 2`.

Najuczciwszy stan wiedzy:
- `Status = 1` wygląda na stan startowy / domyślny
- `Status = 2` wygląda na stan promowany proceduralnie i używany przez końcową ścieżkę raportową
- `DobryKanal` i `Problem.decyzja_o_koordynacji` wyglądają na oddzielne stany pomocnicze
- nadal nie jest jeszcze odtworzona pełna semantyka wszystkich możliwych kodów statusu

### Gdzie najpewniej siedzi kwalifikacja krajowa

Najważniejszy artefakt:
- `logs/access_qualification_flow_20260316.json`

Najbardziej prawdopodobny podział:
1. wrapper krajowy planu:
   - `Kwalifikacja_EMC_kraj`
   - `generuj_fk`
   - `druk_wynikow`
2. weryfikacja konkretnego kandydata:
   - `wpisz_dane_koor`
   - `kwalifikacja_koor`
   - `Kwalifikacja_EMC`
   - `Stan_wniosku_po_weryfikacji`
3. finalna promocja stanu:
   - `wstaw_status`
   - proceduralny `UPDATE Czestotliwosc kandydujaca.status`

Wniosek praktyczny:
- `Kwalifikacja_EMC_kraj` wygląda bardziej jak orchestration wrapper dla krajowego przebiegu planu
- bliżej końcowego wyboru kandydata siedzi para:
  - `Kwalifikacja_EMC`
  - `Stan_wniosku_po_weryfikacji`
- samo wpisanie `Status = 2` nadal wygląda na osobny krok VBA, nie na prosty wynik pojedynczej kwerendy

### Która procedura wygląda na writer `Wynik EMC-LR`

Najważniejszy artefakt:
- `logs/access_result_writers_20260316.json`

Najmocniejsze rozróżnienie:
- `utworz_wynik_zaklocen`
  - wygląda na tor NSS/sat -> LR
  - nie jest najlepszym kandydatem na writer naziemnego benchmarku
- `wyniki_EMC_fk`
  - wygląda na właściwy writer wyników parowych do `Wynik EMC-LR`
  - ma parametry:
    - `marg`
    - `dz`
    - `idprzesla`
    - `wsk`
    - `metoda`
    - `blad`
    - `opis_bledu`
  - i siedzi obok śladów:
    - `FKandydujaca_b#`
    - `Wynik EMC-LR`
    - `metoda=2`
    - `brak maski`
    - `brak nadajnika`

Wniosek praktyczny:
- następny najbardziej wartościowy reverse engineering powinien już iść w semantykę argumentów `wyniki_EMC_fk`
- a nie w dalsze rozkładanie `utworz_wynik_zaklocen`, które wygląda na poboczny tor raportowania

Obecnie najbardziej prawdopodobne mapowanie parametrów `wyniki_EMC_fk` jest takie:
- `fid`
  - `Wynik EMC-LR.[FKandydujaca_b#]`
- `idprzesla`
  - `Wynik EMC-LR.[Przęsło_i#]`
- `metoda`
  - `Wynik EMC-LR.metoda`
- `blad`
  - `Wynik EMC-LR.blad_obliczen`
- `opis_bledu`
  - `Wynik EMC-LR.opis_bledu`
- `marg`
  - pojedynczy margines kierunkowy zapisany do:
    - `Margines_b-i`
    - albo `Margines_i-b`
- `dz`
  - pojedyncza odległość kierunkowa zapisana do:
    - `Odleglosc_b-i`
    - albo `Odleglosc_i-b`
- `wsk`
  - najpewniej wybór strony zapisu `b-i` vs `i-b`

Dodatkowe ślady z tej samej okolicy:
- `sprz`
- `TlumCyrk_NO`
- `dd_n`
- `dd_o`
- `wsp_szum_i`
- `moc_szumow`
- `distance`

To wygląda tak, jakby writer działał bezpośrednio na wyniku jednego kierunku pary, a nie na pełnym dwukierunkowym agregacie naraz.

Ważne ograniczenie z danych `_349`:
- w `75/85 GHz` wartości `TlumCyrk` są najczęściej bardzo małe:
  - mediana `0.0 dB`
  - `p90 = 0.5 dB`
- więc `TlumCyrk` nadal jest elementem wejścia Accessa,
- ale samodzielnie nie wyjaśnia już największych residuali benchmarku.

Raport bieżącego stanu:
- `logs/access_wyniki_emc_fk_semantics_20260316.json`

Nowy mocny ślad z call site wrappera:
- `wyniki_EMC_prz db, filen![przeslo#], Marg_n, dz, file![Przęsło#], 1, 1, blad, "", "POL"`
- `wyniki_EMC_prz db, filen![przeslo#], Marg_o, Dzi, file![Przęsło#], 2, 1, blad, "", "POL"`

To pozwala już powiedzieć konkretniej:
- `wsk = 1` dla gałęzi `Marg_n / dz`
- `wsk = 2` dla gałęzi `Marg_o / Dzi`
- `metoda = 1` to krajowy writer path

Otwarte pytanie zostało zawężone do:
- `Marg_n / dz -> b-i` czy `i-b`
- `Marg_o / Dzi -> i-b` czy `b-i`

Raport tej warstwy:
- `logs/access_writer_callsite_20260316.json`

Wynik testu hipotez:
- proste hipotezy:
  - `wsk=1 -> b-i`, `wsk=2 -> i-b`
  - albo odwrotna
  nie są dziś najlepiej wspierane
- najlepiej wspiera się hipoteza pośrednia:
  - `wsk=1/2` wybiera gałąź `N/O`
  - a końcowe mapowanie do `Margines_b-i` / `Margines_i-b` dzieje się warstwę później

Powód:
- `Marg_n` i `Marg_o` są opisane jako degradacja odbiornika `i-tego przęsła`
- więc wyglądają bardziej jak podgałęzie writer flow niż gotowe finalne kolumny `Wynik EMC-LR`

Raport testu:
- `logs/access_writer_hypotheses_20260316.json`

## Brakująca warstwa: aktualizacja `fkand`

Najmocniejszy nowy trop z VBA i surowych stringów `MDB` wskazuje, że pomiędzy:
- `wyniki_EMC_prz`
- a `wyniki_EMC_fk`

Access ma jeszcze jeden etap proceduralny:
- `aktualizacja parametr`
- `w fkand`
- `Czestotliwosc kandydujaca`
- `[FKandydujaca#] = ...`

To wygląda na warstwę, która nie zapisuje jeszcze finalnego wiersza `Wynik EMC-LR`,
tylko najpierw scala gałęzie:
- `Marg_n / dz`
- `Marg_o / Dzi`

do pól rekordu kandydata:
- `MargNad`
- `MargOdb`
- `N-nad`
- `N-odb`

Najmocniejsze ślady:
- wspólny blok lokalnych zmiennych zawiera jednocześnie:
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
- komentarz proceduralny:
  - `FID - identyfikator fkand lub zero(null) dla przesła`
  - `p_czy_fk = 0 dla przęsła`
  - `p_czy_fk = 1 dla fkand`
- bezpośrednio po dwóch wywołaniach `wyniki_EMC_prz` pojawia się blok:
  - `aktualizacja parametr w fkand`

Najbardziej prawdopodobny przebieg jest dziś taki:
1. Access liczy dwie krajowe gałęzie EMC dla przęsła:
   - `Marg_n / dz`
   - `Marg_o / Dzi`
2. zapisuje je wrapperem `wyniki_EMC_prz`
3. wchodzi w blok aktualizacji `fkand`
4. uzupełnia kierunkowe pola kandydata:
   - `MargNad`
   - `MargOdb`
   - `N-nad`
   - `N-odb`
5. dopiero potem zapisuje wynik kandydata i przechodzi do statusu / wydruku

Wniosek:
- brakująca logika nie jest prostym mapowaniem `wsk -> b-i/i-b`
- to osobny etap agregacji i aktualizacji stanu kandydata

Raport tej warstwy:
- `logs/access_fk_update_layer_20260316.json`

Eksperymentalne wejście w ten model w Pythonie pokazało na wzorcu:
- `MargNad/MargOdb` z warstwy `fkand update` pokrywają się dziś z naszymi
  obecnymi polami:
  - `uke_like_margnad_db`
  - `uke_like_margodb_db`
- nowa warstwa dodaje jednak osobny, jawny stan Access-like:
  - `jest_wynikN`
  - `jest_wynikO`
  - `N-nad`
  - `N-odb`

Wniosek praktyczny:
- trafiliśmy najpewniej w dobrą warstwę workflow Accessa,
- ale sama dodatkowa transformacja marginesów nie jest jeszcze odkryta,
- więc kolejny postęp powinien iść w dokładny zapis VBA, który ustawia:
  - `MargNad`
  - `MargOdb`
  - `N-nad`
  - `N-odb`

Dodatkowy ważny wynik z przeszukania VBA:
- `Marg_n` i `Marg_o` są widoczne literalnie i mają jasne call-site do `wyniki_EMC_prz`
- `MargNad`, `MargOdb`, `N-nad`, `N-odb` są widoczne jako zmienne procedury
- ale nie ma dziś w surowych stringach literalnego:
  - `UPDATE ... SET [MargNad] = ...`
  - ani odpowiednika dla `MargOdb`, `N-nad`, `N-odb`

To sugeruje, że Access zapisuje te pola najpewniej przez:
- `Recordset.Edit / Update`
- albo krótszy dynamiczny SQL składany z fragmentów
- a nie przez długi, jawny `UPDATE` taki jak dla `Status`

Raport:
- `logs/access_margin_traces_20260316.json`

Wąski search `Recordset/Edit/Update` wokół `fkand` dołożył jeszcze jedno ważne rozróżnienie:
- odzyskane proceduralne zapisy przez `Recordset.Update` dotyczą dziś na pewno:
  - `problem_kons`
  - oraz warstwy `Dane_EMC` / mask nadajnika
- ale nadal nie odsłoniły literalnego zapisu:
  - `MargNad`
  - `MargOdb`
  - `N-nad`
  - `N-odb`

To wzmacnia wniosek, że setter marginów kandydata jest nadal ukryty:
- albo w innej gałęzi `Recordset`
- albo w krótkim dynamicznym SQL
- albo w fragmencie VBA niewidocznym w obecnym `strings`

Raport:
- `logs/access_fkand_recordset_search_20260316.json`

## Mapa obiektów DAO

Z dotychczasowych śladów da się już złożyć użyteczną mapę nazw
`DAO/Recordset/QueryDef` do lokalnych ról w Accessie.

Najważniejsze:
- `dbb`
  - główny `CurrentDb`
- `db`
  - lokalny uchwyt bazy
- `myq`
  - przeciążony `QueryDef`
- `filen`
  - przeciążony `Recordset`
  - raz jako:
    - `przeslo badane`
  - raz jako:
    - wynik zapytania selekcyjnego NSS/LR
- `filep`
  - rekordset przęsła problemowego / zakłócającego
- `filepk`
  - writer `problem_kons`
- `file`
  - writer warstwy `Dane_EMC` / masek nadajnika
- `set_wybor` / `zap_wybor`
  - selekcja NSS/LR

To porządkuje dalszy reverse engineering:
- nie szukamy już “którykolwiek `file.Update`”
- tylko konkretnego obiektu DAO, który lokalnie reprezentuje `fkand`

Raport:
- `logs/access_dao_object_map_20260316.json`

1. Wygeneruj kandydaty kierunkowe dla obu kierunków i polaryzacji.
2. Sparuj rekordy `A/B` do wariantu duplexowego po `numer_pary_f` i `polaryzacja`.
3. Dla każdego kierunku policz lub odczytaj margines:
   - z `MargNad` / `MargOdb`
   - oraz z rekordów `Wynik EMC-LR`
4. Zbuduj status wariantu z najgorszego kierunkowego marginesu i ewentualnych błędów/problematycznych rekordów.
5. Posortuj warianty według:
   - dopuszczalności statusu
   - najwyższego najgorszego marginesu duplexowego
   - mniejszej liczby konfliktów współkanałowych / czerwonych
   - dopiero na końcu pomocniczych tie-breakerów

To jest bardzo bliskie temu, jak dziś działa nasz nowy pipeline:
- `EMCInput`
- `PairwiseEmcResult`
- `CandidateFrequencyRecord`

## Co różni to od naszego silnika dzisiaj

Nasz silnik już ma:
- kandydatów kanałowych
- analizę victim i aggressor
- maski radiowe
- charakterystyki anten
- filtr konsultacyjny

Ale nadal różni się od workflow UKE w kilku ważnych miejscach:

1. Nie mamy jeszcze formalnego modelu „marginesu EMC”
   - UKE wygląda na oparte o `Margines_b-i` i `Margines_i-b`
   - my pracujemy głównie na:
     - `CI`
     - `TD`
     - progach akceptacji

2. Nie mamy jeszcze wejściowej warstwy pośredniej odpowiadającej `Dane_EMC`
   - UKE prawdopodobnie liczy z przetworzonych, ustandaryzowanych parametrów
   - my liczymy bardziej bezpośrednio z WLR i bazy pozwoleń

3. Nie korzystamy jeszcze z warstwy terenowej / horyzontu
   - `ELEWACJA_HORYZONTU`
   - możliwie `ZASIEG`

4. Nie mamy jeszcze pełnej radio-specyficznej selektywności odbiornika
   - samo `maski` to prawdopodobnie tylko część obrazu
   - część logiki może siedzieć też w `NADAJNIK`

## Co da się wdrożyć od razu

### Etap 1

Najbardziej realny krok bez ryzyka:
- wprowadzić w naszym silniku pojęcie marginesu EMC per kierunek
- liczyć i przechowywać:
  - `margin_ab`
  - `margin_ba`
- budować decyzję na bazie marginesów, a nie wyłącznie progów `TD/CI`

### Etap 2

Zbudować wewnętrzną warstwę wejściową analogiczną do `Dane_EMC`:
- antena Tx
- antena Rx
- zysk
- liczba szumowa
- moc nadajnika
- tłumienia toru
- kierunki promieniowania
- kąty elewacji
- częstotliwość dolna/górna
- szerokość kanału
- dupleks

To pozwoli:
- uprościć logikę silnika
- zbliżyć strukturę obliczeń do UKE
- łatwiej porównywać rekord do rekordu

### Etap 3

Rozszerzyć warstwę selektywności:
- `maski`
- parametry z `NADAJNIK`

### Etap 4

Dopiero potem dołączyć topografię i horyzont:
- `ELEWACJA_HORYZONTU`
- możliwie `ZASIEG`

## Rekomendacja dalszych prac

Najbardziej sensowna kolejność:

1. Zaimplementować wewnętrzny model `EMCInput`
2. Dodać wyliczanie marginesów EMC per kierunek
3. Przełączyć decyzję kanału na model marginesowy
4. Dopiero potem wrócić do terenu i horyzontu

## Dalszy reverse engineering Accessa

Po wejściu w systemowe tabele Accessa i końcowy blok proceduralny widać już
kilka rzeczy dość jasno.

### Systemowe obiekty

- `MSysObjects` trzyma właściwe `Id` dla modułów VBA i makr:
  - moduły: `Master`, `Zadania_LR`, `Zadania_LR_Tlumienie`, `koordynacja_zagr`, itd.
  - makra: `autoexec`, `start`, `klepsydra_nie`, `Uaktualnienie bazy`
- `MSysNavPaneObjectIDs` potwierdza te same obiekty:
  - moduły jako `Type = 32775`
  - makra jako `Type = 32770`
- `MSysAccessObjects` da się już sparsować po wstrzyknięciu prawidłowego `Id`
  z `MSysObjects`, ale na obecnym poziomie parsera:
  - tabela ma `141` rekordów
  - `Data` wychodzi puste dla wszystkich rekordów

Wniosek:
- systemowe tabele pomagają nam mapować obiekty i ich `Id`,
- ale nie odsłoniły jeszcze pełnych ciał modułów VBA.

### Najmocniejszy blok końcowy kandydata

Najbardziej spójny proceduralny łańcuch, który dziś widzimy w stringach `MDB`,
to:

1. `statusfk = 1`
2. `aktualizacja parametr`
3. `w fkand`
4. `Czestotliwosc kandydujaca`
5. `filepk.Update`
6. `ExportTx_przeslo`
7. `ExportRx_przeslo`
8. `wpisz_dane_koor`
9. `kwalifikacja_koor`
10. `Kwalifikacja_EMC`
11. `Stan_wniosku_po_weryfikacji`
12. `wstaw_status`
13. `status_kand`

To sugeruje bardzo konkretny przebieg:
- zapis problemów do `problem_kons`
- przygotowanie payloadów EMC
- kwalifikacja i weryfikacja
- dopiero potem końcowe ustawienie stanu kandydata

Czyli:
- finalny status kandydata nie jest częścią samego write path `Wynik EMC-LR`
- tylko leży w późniejszej warstwie po `Stan_wniosku_po_weryfikacji`

Raport:
- `logs/access_system_tables_and_state_flow_20260316.json`

### `wstaw_status`

Osobna analiza `wstaw_status` wzmacnia ten sam obraz:

- `statusfk = 1` to proceduralny seed stanu kandydata
- odzyskana jawna promocja to:
  - `If status_fkand_zagr = 2 Then status_fkand = 2`
- `Koniec_obliczen dbb, fid(i), status_fkand` pokazuje, że Access potrafi
  przerwać przebieg, ale nadal niesie akumulator stanu
- `Stan_wniosku_po_weryfikacji(...)` występuje po warstwie:
  - `ExportTx_przeslo`
  - `ExportRx_przeslo`
  - `wpisz_dane_koor`
  - `kwalifikacja_koor`
  - `Kwalifikacja_EMC`
- `wstaw_status` i `status_kand` siedzą właśnie w tej post-weryfikacyjnej
  warstwie

Najbardziej prawdopodobny przebieg jest więc taki:
1. akumulacja `statusfk`
2. kwalifikacja i weryfikacja
3. `Stan_wniosku_po_weryfikacji`
4. `wstaw_status`
5. wyznaczenie `status_kand`
6. późniejszy `UPDATE Czestotliwosc kandydujaca.status`

Wniosek:
- finalny status kandydata wygląda na wynik helpera proceduralnego po
  kwalifikacji
- a nie prostą projekcję z `Wynik EMC-LR`

Raport:
- `logs/access_wstaw_status_20260316.json`

To daje:
- największą szansę na zbliżenie do metodologii UKE
- bez natychmiastowego wejścia w najcięższy obszar danych terenowych
