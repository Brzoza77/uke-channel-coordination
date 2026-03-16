# UKE Workflow Reverse Engineered

Ten dokument jest syntetycznym opisem workflow UKE odtworzonego na podstawie:

- `LR_Konsultacja_349.mdb`
- tabel eksportowanych do `sqlite`
- zapisanych `QueryDef` Accessa
- śladów VBA i makr
- benchmarków `wlr-doc`
- porównań `Wynik EMC-LR` oraz końcowych statusów kanałów

Nie jest to opis “jak powinno działać” według teorii, tylko nasz najlepszy stan wiedzy o tym, jak działa Access UKE w praktyce.

## 1. Wejście do procesu

Wejściem jest plik `WLR`, z którego Access pobiera:

- geometrię badanego linku
- plan kanałowy
- kanał `A/B`
- polaryzację
- parametry radiowe
- typ i producenta radia
- typ i producenta anteny

W Accessie nie ma potrzeby odwoływania się do zewnętrznego wykazu pozwoleń, jeżeli baza `_349` jest aktualna. Dane ogólnopolskie siedzą w samej bazie.

## 2. Źródło danych referencyjnych

Najważniejsze tabele ogólnopolskie:

- `PRZESLO`
- `DECYZJA`
- `Przeslo decyzji`
- `STACJA`
- `OBIEKT STACJI`
- `KONSTRUKCJA`
- `ZASTOSOWANA ANTENA`
- `PLAN`
- `KANAL`
- `NADAJNIK`
- `ANTENA`
- `CHARAKTERYSTYKA`
- `ZASIEG`
- `ELEWACJA_HORYZONTU`

Praktyczny wniosek:

- baza `_349` jest samowystarczalnym katalogiem linków UKE
- planów kanałowych nie trzeba brać z `RTF`
- listy pozwoleń nie trzeba brać z zewnętrznego `XLS`

## 3. Budowa puli kandydatów

Access nie ogranicza się do exact `channel_width`.

Potwierdzone w `QueryDef`:

- `kompat_przeslo_i`
- `Kompat-i`

Filtr overlapu jest bliższy:

```text
Abs(freq_assigned - fb) <= 0.5 * (width + szb)
```

To oznacza na przykład:

- `80 GHz / 250 MHz` współistnieje z `125 MHz` i `62.5 MHz`
- analogicznie w `38 GHz` kanał `56 MHz` musi widzieć także `28/14/7 MHz`

## 4. Parowanie kanałów duplex

Kwerendy:

- `Pary_fk_ABprim`
- `Pary_fk_AprimB`

pokazują, że Access jawnie paruje kanały `A/B` po numerze kanału i apostrofie.

To nie jest luźna heurystyka po częstotliwości, tylko osobny etap workflow.

## 5. Przygotowanie danych EMC

Warstwa wejściowa EMC składa się z:

- `Dane_EMC`
- `Dane_EMC_druk`
- `Dane_do_EMC_BENNER`
- `Czestotliwosc kandydujaca`
- payloadów `T_dane_koor / R_dane_koor`

Zrekonstruowane pola payloadu:

- częstotliwość
- szerokość kanału
- moc nadajnika
- poziom szumów / `NF`
- tłumienie cyrkulatora
- azymut głównej wiązki
- elewacja głównej wiązki
- wysokość anteny
- typ i producent anteny
- zysk anteny
- maska nadajnika
- charakterystyki antenowe `copol/crosspol`

Praktyczny wniosek:

- Access przekazuje do obliczeń pełny, proceduralnie zbudowany snapshot toru radiowego
- wynik nie jest liczony tylko z surowych rekordów `PRZESLO`

## 6. Surowe wyniki parowe EMC

Najważniejsza warstwa obliczeniowa:

- `Wynik EMC-LR`

Najważniejszy writer naziemny:

- `wyniki_EMC_fk`

Powiązany writer gałęziowy:

- `wyniki_EMC_prz`

Najmocniejszy odzyskany ślad:

- dokładnie dwa write’y `wyniki_EMC_prz` w tej gałęzi LR:
  - `Marg_n`
  - `Marg_o`

Potem dopiero pojawia się:

- `aktualizacja parametr`
- `w fkand`
- `Czestotliwosc kandydujaca`

Wniosek:

- Access nie aktualizuje kandydata po pierwszym wyniku
- kandydat jest agregowany dopiero po domknięciu obu gałęzi `N/O`

## 7. Dwie ścieżki agregacji `fkand`

To jest jeden z najważniejszych wyników reverse engineeringu.

Z VBA i z benchmarków wynika, że `fkand` nie jest jedną prostą agregacją, tylko zbiegiem co najmniej dwóch procedur:

### 7.1. Ścieżka problemowa

Powiązana z:

- `problem_kons`
- `TD p-gr`
- `D11`
- `Dgr`
- `Problem.decyzja_o_koordynacji = IIf([d11] > [dgr], 1, 2)`

Ta ścieżka najlepiej odpowiada klasie:

- `problem_only`

czyli przypadkom, które są problemowe proceduralnie, ale nie muszą być jeszcze “niekompatybilne” w sensie końcowego statusu.

### 7.2. Ścieżka niekompatybilności

Powiązana z:

- `nadaj czestotliwosci status niekompatybilna`
- `wyniki_EMC_prz`
- `aktualizacja parametr w fkand`

Ta ścieżka najlepiej odpowiada klasie:

- `blocking_only`

czyli przypadkom, które pchają kandydata w stronę odrzucenia.

### 7.3. Warstwa wspólna

W jednym bloku VBA występują razem:

- `jest_wynikN`
- `jest_wynikO`
- `Marg_n`
- `Marg_o`
- `MargNad`
- `MargOdb`
- `N-nad`
- `N-odb`
- `statusfk`

Wniosek:

- `Marg_n/Marg_o` są surowymi wynikami gałęzi
- `MargNad/MargOdb/N-nad/N-odb` są już agregatem kandydata

## 8. Status kandydata

Access używa kilku warstw stanu, nie jednej:

- `DobryKanal`
- `statusfk`
- `stanp`
- `stan_problem`
- `stanprz`
- `stanprzesla`
- `status_kand`
- końcowe `Czestotliwosc kandydujaca.Status`

Najbardziej prawdopodobny przebieg:

1. seed kandydata
2. generacja i kwalifikacja
3. obliczenia EMC
4. agregacja `fkand`
5. `Stan_wniosku_po_weryfikacji`
6. `wstaw_status`
7. wyznaczenie `status_kand`
8. osobny writeback:
   - `UPDATE DISTINCTROW [Czestotliwosc kandydujaca] SET [status] = ...`

Ważne:

- nie znaleźliśmy jednego prostego SQL-a, który sam wyjaśnia całe przejście
- setter statusu jest proceduralny i rozproszony między VBA i dynamicznym SQL

## 9. Warstwa wydruku

Kwerendy:

- `Wyniki_b-i`
- `Wyniki_i-b`
- `Wyniki_do_wydruku`

pokazują, że:

- `Wynik EMC-LR` jest warstwą surową
- `Status = 2` jest warstwą selekcji do końcowego wydruku

Czyli:

- nie każdy wynik parowy trafia do finalnego DOC
- najpierw powstaje wynik EMC
- potem kandydat przechodzi proceduralną kwalifikację
- dopiero potem wiersz trafia do dokumentu

## 10. Co udało się odtworzyć w silniku

Najważniejsze rzeczy już zaimplementowane:

- źródło kandydatów z `_349/sqlite`, bez `XLS`
- plany z `sqlite`, bez `RTF`
- szerokopasmowy preselector zgodny z `Kompat-i`
- parowanie duplex w duchu `Pary_fk_*`
- profile radiowe request-side z `_349/NADAJNIK`
- warstwa `direct/cross` i mapowanie wierszy DOC
- eksperymentalny `fkand` dual-path:
  - `problem_path`
  - `incompatible_path`
- eksperymentalny `status gate` nad dual-path

## 11. Aktualny poziom zgodności

Na paczce referencyjnej `80 GHz` eksperymentalny `status gate` nad dual-path `fkand`
osiągnął:

- `303 / 308`
- `98.38%`

To jest bardzo dobry wynik dla końcowej klasyfikacji statusu kanału, ale trzeba go czytać uczciwie:

- to nie jest jeszcze pełna, literalna rekonstrukcja całego VBA Accessa
- to jest bardzo trafny model wynikowy oparty o reverse engineering

## 12. Co nadal pozostaje nie w pełni odtworzone

- literalny writeback `status_kand -> Status`
- dokładny dispatcher dynamicznego SQL po `wstaw_status`
- pełna semantyka wszystkich pośrednich stanów `stan*`
- pełna, literalna rekonstrukcja całego call stacku VBA

## 13. Najkrótszy praktyczny opis workflow UKE

Jeśli skrócić wszystko do jednego przebiegu:

1. Access czyta `WLR`
2. lokalizuje link w ogólnopolskiej bazie `_349`
3. wybiera kandydackie przęsła i kanały
4. buduje pary duplex
5. przygotowuje pełny snapshot wejścia EMC
6. liczy wyniki parowe `Marg_n / Marg_o`
7. zapisuje surowe wyniki do `Wynik EMC-LR`
8. agreguje je do poziomu kandydata `fkand`
9. przeprowadza proceduralną kwalifikację i weryfikację
10. nadaje końcowy status kandydata
11. wybiera tylko wybrane kandydaty do wydruku `DOC`

To jest obecnie nasza najlepsza, syntetyczna rekonstrukcja workflow UKE.
