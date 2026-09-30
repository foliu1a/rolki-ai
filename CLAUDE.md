# rolki-ai — instrukcja dla Claude

Fabryka rolek AI per "modelka" (persona): filmik zrodlowy -> Seedance 2.5 Edit
(oficjalne CLI Higgsfield) -> ocena -> postprodukcja -> gotowy plik + podpis.
Wlasciciel prowadzi wlasne AI-persony (np. @uroczanoemi) na materialach, do ktorych ma prawa.

## Podzial rol

- Subagent **rolkarz** (`~/.claude/agents/rolkarz.md`) - produkcja: oglada klatki, pisze prompty,
  odpala fabryke, ocenia wyniki. Komenda uzytkownika: `/rolki` (`~/.claude/skills/rolki/SKILL.md`).
- Ty (glowna sesja / tom) - kod fabryki, panel, integracje.

## Pliki

```
fabryka.py          automat (status, skanuj, prompt, koszt, generuj, ocen, warianty, podpis, ustaw, model, konto)
higgsfield_cli.py   wrapper na CLI @higgsfield/cli (subprocess + --json); NIE ma tu klucza API - logowanie OAuth robi user
klatki.py           ffprobe/ffmpeg: info, klatki PNG, arkusz.jpg (siatka do ogladania)
baza.py             warstwa danych (modelki/<slug>/*.json) - zawsze przez nia, nie edytuj JSON-ow recznie
postprocess.py      most do ..\VideoRemixer (NIE modyfikowac VideoRemixera)
app.py + templates  panel Flask :5077 (podglad kolejki, bank tekstow, warianty)
panel.py            to samo w konsoli
modelki/<slug>/
  ustawienia.json   model/mode/aspect/resolution/duration, prompt_bazowy, prompt_zasady, referencje, soul_id,
                    min_kredyty, max_kredyty_na_rolke, warianty, dodatkowe_parametry
  zrodla/           WRZUTNIA - user wrzuca filmiki; zrodla/_klatki/<nazwa>/arkusz.jpg = podglad
  referencje/       zdjecia persony (-> --image do Seedance)
  wyniki/           pobrane rolki: 001_<nazwa>.mp4, 001_warianty/, 001_podpis.txt
  pomysly.json      kolejka; statusy: nowy -> wygenerowany -> postprodukcja -> gotowe (+ blad)
  profil.json / szablony.json / teksty.json / uzyte_tekstow.json
```

Zmienna `ROLKI_MODELKI` przenosi folder modelek gdzie indziej (testy, dysk D:).

## Higgsfield CLI - fakty

- Instalacja: `npm install -g --allow-scripts=@higgsfield/cli @higgsfield/cli` (bez `--allow-scripts` binarka sie nie pobierze).
- Logowanie: `higgsfield auth login` (OAuth w przegladarce) - **tylko uzytkownik**. Ty nigdy tego nie odpalasz.
- `hf` w PATH na tej maszynie to CLI Hugging Face, nie Higgsfield - wrapper uzywa pelnej sciezki do `vendor\hf.exe`.
- Seedance 2.5: `seedance_2_5`, `--mode t2v|omni_reference|video_edit|video_extension`, media `--video`, `--image`
  (repeatable), `--start-image`, `--end-image`, `--audio`; parametry `--aspect_ratio`, `--resolution 480p|720p|1080p`,
  `--duration 4-30`. Schema: `python fabryka.py model seedance_2_5` (wymaga logowania).
- `higgsfield generate cost <model> ...` liczy kredyty bez generacji - fabryka robi to przed kazda pozycja.
- `higgsfield account status --json` = saldo. Jarvis (`..\claudzik\jarvis\sources\higgsfield.py`) czyta je stad.
- Virality Predictor = `brain_activity --video <plik>` (kosztuje kredyty).
- Cennik apki (Seedance 2.5, 10 s): 30 kr 480p / 70 kr 720p / 120 kr 1080p; Edit liczy input + output.

## Prompty

- Punkt wyjscia = `prompt_bazowy` z ustawien (sprawdzony przez usera). Zmieniaj tylko to, co wynika z klipu.
- Persona: imie + cechy z profil.json. Pion 9:16. Konkret: miejsce, ubior, pora dnia, ruch kamery.
- Brak `prompt_bazowy` -> nie zgaduj, popros usera.

## Granice

- Nie scrapuj Instagrama; zrodla i referencje dostarcza uzytkownik.
- Wizerunek realnych osob tylko za ich zgoda. Content jest AI - nie pomagaj udawac, ze jest inaczej.
- Bezpiecznik budzetu (min_kredyty, max_kredyty_na_rolke) zmienia tylko user.
- Publikacja jest reczna. Fabryka konczy na pliku w `wyniki/`.
