# Git - szybka sciaga

To jest minimalny zestaw komend potrzebnych do codziennej pracy z tym projektem.

## Gdzie pracujemy

Repo lokalne:

```bash
cd /home/brzoza/uke
```

Repo zdalne:

```text
https://github.com/Brzoza77/uke-channel-coordination.git
```

## Najczestszy workflow

### 1. Sprawdz, co sie zmienilo

```bash
git status
```

### 2. Dodaj zmiany do commita

```bash
git add .
```

Jesli chcesz dodac tylko jeden plik:

```bash
git add analysis.py
```

### 3. Zapisz zmiany lokalnie

```bash
git commit -m "Opis zmian"
```

Przyklady:

```bash
git commit -m "Add consultation filter for same-span links"
git commit -m "Improve frontend empty-state for no accepted channels"
```

### 4. Wyslij na GitHub

```bash
git push
```

## Jak pobrac projekt na inna maszyne

Pierwszy raz:

```bash
git clone https://github.com/Brzoza77/uke-channel-coordination.git
```

Potem wejdz do katalogu:

```bash
cd uke-channel-coordination
```

## Jak pobrac najnowsze zmiany

Na innej maszynie lub po dluzszej przerwie:

```bash
git pull
```

## Jak zobaczyc historie

```bash
git log --oneline
```

## Jak zobaczyc roznice przed commitem

```bash
git diff
```

## Jak sprawdzic, czy wszystko jest wyslane

```bash
git status
```

Jesli zobaczysz:

```text
nothing to commit, working tree clean
```

to lokalnie jest czysto.

## Dwie bezpieczne zasady

Na razie nie uzywaj samodzielnie:

```bash
git reset --hard
git push --force
```

Te komendy potrafia usunac lub nadpisac zmiany.

## Najprostszy model zapamietania

Po kazdej sensownej zmianie:

```bash
git status
git add .
git commit -m "Opis zmian"
git push
```

