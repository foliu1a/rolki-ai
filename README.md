# rolki-ai

Fabryka rolek AI, osobno dla każdej "modelki" (persony). Ty wrzucasz filmiki źródłowe,
agent dobiera prompt na bazie Twojego sprawdzonego, generuje przez **Seedance 2.5 Edit**
(oficjalne CLI Higgsfield), ocenia wynik i zostawia gotowy plik z podpisem.

Nie jest to auto-publikacja - kończy się na pliku w `wyniki/`. Wrzucasz ręcznie.

## Założenie

Materiały źródłowe i wizerunek persony są Twoje albo masz do nich prawa. Narzędzie nie
służy do podmiany twarzy realnych osób bez ich zgody.

## Struktura

```
rolki-ai/
  panel.bat              <- panel webowy (dwuklik)
  instaluj.bat           <- instalacja: flask, CLI Higgsfield, skille (jednorazowo)
  fabryka.py             <- AUTOMAT: status / skanuj / prompt / koszt / generuj / ocen / warianty / podpis / ustaw
  higgsfield_cli.py      <- wrapper na CLI @higgsfield/cli (logowanie OAuth, bez kluczy w plikach)
  klatki.py              <- klatki + arkusz podglądu z wideo (ffmpeg)
  baza.py                <- warstwa danych
  postprocess.py         <- most do ..\VideoRemixer (unikalne warianty)
  app.py, templates/     <- panel Flask :5077
  panel.py               <- panel w konsoli
  modelki/<slug>/
    ustawienia.json      <- model, prompty (A/B), budżet (min_kredyty, max_kredyty_na_rolke)
    prompty/             <- stroj_z_filmu.txt (wariant A), stroj_ze_zdjecia.txt (wariant B) - Twoje prompty
    zrodla/              <- WRZUTNIA: tu wrzucasz filmiki; <nazwa>.stroj.png obok = wariant B z tym strojem
    zrodla/_klatki/      <- podgląd klatek (arkusz.jpg) dla agenta
    referencje/          <- zdjęcia persony, 01_ 02_ ... = kolejność @[Image N] w prompcie -> --image
    stroje/              <- zdjęcia strojów do wariantu B (stroj_domyslny w ustawieniach = dla wszystkich)
    wyniki/              <- gotowe rolki: 001_nazwa.mp4, 001_warianty/, 001_podpis.txt
    pomysly.json         <- kolejka (nowy -> wygenerowany -> postprodukcja -> gotowe / blad)
    profil.json, szablony.json, teksty.json, uzyte_tekstow.json
```

## Start (raz)

1. `instaluj.bat`
2. `higgsfield auth login` - loguje CLI do Twojego konta Higgsfield (przeglądarka). Kredyty idą z Twojego planu.
3. W panelu (`panel.bat`) załóż modelkę, wrzuć zdjęcia persony do `modelki/<slug>/referencje/`.
4. Wklej swoje prompty do `modelki/<slug>/prompty/stroj_z_filmu.txt` (A) i `stroj_ze_zdjecia.txt` (B). Budżet:

```
python fabryka.py ustaw min_kredyty=200 max_kredyty_na_rolke=150
```

## Obieg pracy (codziennie)

1. Wrzuć filmiki do `Desktop/ROLKI AI/przed/<persona>/` (gotowe lądują w `Desktop/ROLKI AI/po/<persona>/`, już po Media Tool)
2. `python fabryka.py skanuj` - każdy filmik dostaje numer i `arkusz.jpg` z klatkami
3. `skanuj` sam wpisuje Twój prompt (A: strój z filmu, B: strój ze zdjęcia gdy obok leży `<nazwa>.stroj.png`)
4. `python fabryka.py koszt` - ile kredytów zejdzie
5. `python fabryka.py generuj --tak` - generacja z bezpiecznikiem (min_kredyty, max/rolka, limit dzienny 300, powtórki po odrzuceniu), Media Tool, plik w `po/`
6. Opcjonalnie: `ocen <id>` (Virality Predictor), `warianty <id> --ile 10` (VideoRemixer), `podpis <id>`

`python fabryka.py status` mówi, co czeka i ile masz kredytów. `python fabryka.py generuj --dry-run`
pokazuje komendy bez wydawania kredytów.

## Z Claude Code

- `/rolki` - status i co dalej
- `/rolki skanuj` - skanuj + prompty do akceptacji
- `/rolki generuj` - koszt, generacja, raport z oceną
- `/rolki nowa <nazwa>` - nowa persona
- Subagent `rolkarz` robi robotę, Ty tylko akceptujesz prompty i koszty.

## Koszty (apka Higgsfield, Seedance 2.5, 10 s)

| Rozdzielczość | Kredyty |
|---|---|
| 480p | 30 |
| 720p | 70 |
| 1080p | 120 |

Edit liczy czas wejścia i wyjścia razem. `fabryka.py koszt` podaje dokładną liczbę przed generacją.

## Postprodukcja

`..\VideoRemixer\glitch_cuts_generator.py` (ffmpeg w PATH). `ustawienia.json: warianty=N` robi je automatycznie po generacji.

## Przenosiny na inny komputer

Skopiuj `rolki-ai` (+ `VideoRemixer` obok), zainstaluj Pythona i Node.js, odpal `instaluj.bat`, potem `higgsfield auth login`.
