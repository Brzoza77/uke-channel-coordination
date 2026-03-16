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

To daje:
- największą szansę na zbliżenie do metodologii UKE
- bez natychmiastowego wejścia w najcięższy obszar danych terenowych
