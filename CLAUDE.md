# rolki-ai — instrukcja dla Claude

Fabryka rolek AI per "modelka" (persona): filmik zrodlowy -> Seedance 2.5 Edit
(oficjalne CLI Higgsfield) -> ocena -> postprodukcja -> gotowy plik + podpis.
Wlasciciel prowadzi wlasne AI-persony (np. @uroczanoemi) na materialach, do ktorych ma prawa.

## Podzial rol

- Subagent **rolkarz** (`~/.claude/agents/rolkarz.md`) - produkcja: oglada klatki, pisze prompty,
  odpala fabryke, ocenia wyniki. Komenda uzytkownika: `/rolki` (`~/.claude/skills/rolki/SKILL.md`).
- Ty (glowna sesja / tom) - kod fabryki, panel, integracje.

## Foldery usera (2026-10-01)

- Wrzutnia: `C:\Users\yux\Desktop\ROLKI AI\przed\<noemi|alicja|bianka>\` (ustawienie `zrodla_dir`).
- Gotowe:   `C:\Users\yux\Desktop\ROLKI AI\po\<persona>\NNN_nazwa.mp4` (ustawienie `wyniki_dir`) - PO Media Tool.
- Surowy wynik Seedance zostaje w `modelki/<slug>/wyniki/NNN_nazwa.raw.mp4`, klatki w `modelki/<slug>/klatki/`.
- Zdjecia person (zrodlo): `Desktop\ROLKI AI\<persona>\` - skopiowane do `referencje/` z numeracja.

## Budzet i powtorki

- `budzet.json` (wspolny, wszystkie persony): `max_kredyty_dziennie` = 300 (user), `wydatki` per dzien.
  Liczy FAKTYCZNE zuzycie (saldo przed - saldo po), bo Seedance przy odrzuceniu oddaje kredyty.
- `powtorki` (ustawienia, 2): przy odrzuceniu/bledzie powtarza po 10 s. NIE powtarza, gdy job "completed" bez URL
  (to blad parsera `wyniki_url`, nie Seedance) - zobacz `higgsfield generate get <id> --json` i popraw parser.
- `min_kredyty` (200) i `max_kredyty_na_rolke` (150) jak wczesniej. Zmienia tylko user.

## Postprodukcja

- Wideo: `mediatool.py` odpala worker Media Tool headless (`ELECTRON_RUN_AS_NODE=1 "Media Tool.exe" worker.cjs <json>`,
  env MEDIA_FFMPEG/FFPROBE/EXIFTOOL/ASSETS_DIR jak w main.cjs). ~4 s/klip, h264_amf, iPhone 17 Pro Max + GPS.
  Wlaczone `mediatool=true`; recznie `python fabryka.py pierz <id>` albo `--plik x.mp4`.
- Zdjecia: Suczkowatka (osobna apka, [[suczkowatka-synthid]]) - fabryka na razie robi tylko wideo.
- VideoRemixer (`warianty`) wylaczony (0) - user go nie uzywa.

## Pliki

```
fabryka.py          automat (status, skanuj, prompt, koszt, generuj, pierz, ocen, warianty, podpis, ustaw, budzet, model, konto)
higgsfield_cli.py   wrapper na CLI @higgsfield/cli (subprocess + --json); NIE ma tu klucza API - logowanie OAuth robi user
mediatool.py        most do Media Tool (Desktop\Media Tool) - pranie wideo bez GUI
klatki.py           ffprobe/ffmpeg: info, klatki PNG, arkusz.jpg (siatka do ogladania)
baza.py             warstwa danych (modelki/<slug>/*.json) - zawsze przez nia, nie edytuj JSON-ow recznie
postprocess.py      most do ..\VideoRemixer (NIE modyfikowac VideoRemixera)
app.py + templates  panel Flask :5077 (podglad kolejki, bank tekstow, warianty)
panel.py            to samo w konsoli
modelki/<slug>/
  ustawienia.json   model/mode/aspect/resolution/duration, prompt_bazowy (A), prompt_stroj (B), stroj_domyslny,
                    prompt_auto, soul_id, min_kredyty, max_kredyty_na_rolke, warianty, dodatkowe_parametry
  prompty/          stroj_z_filmu.txt (wariant A) i stroj_ze_zdjecia.txt (wariant B) - PROMPTY USERA, nie zmieniaj tresci
  zrodla/           WRZUTNIA - user wrzuca filmiki; zrodla/_klatki/<nazwa>/arkusz.jpg = podglad
                    <nazwa>.stroj.png obok <nazwa>.mp4 = ten klip idzie wariantem B z tym strojem
  referencje/       zdjecia persony, numerowane 01_, 02_... = kolejnosc @[Image N] w prompcie (-> --image)
  stroje/           zdjecia strojow do wariantu B (stroj_domyslny w ustawieniach = dla wszystkich klipow)
  wyniki/           pobrane rolki: 001_<nazwa>.mp4, 001_warianty/, 001_podpis.txt
  pomysly.json      kolejka; statusy: nowy -> wygenerowany -> postprodukcja -> gotowe (+ blad)
  profil.json / szablony.json / teksty.json / uzyte_tekstow.json
```

Zmienna `ROLKI_MODELKI` przenosi folder modelek gdzie indziej (testy, dysk D:).

## Testy

`python -m pytest` (raz: `python -m pip install pytest`). Testy w `tests/` dzialaja na katalogu tymczasowym
i udawanym CLI Higgsfield (`tests/conftest.py`: `UdawaneCLI`) - nie wydaja kredytow, nie ruszaja `modelki/`,
`budzet.json` ani Media Tool. Nowa logika w fabryka.py/baza.py = nowy test.

## Higgsfield CLI - fakty

- Instalacja: `npm install -g --allow-scripts=@higgsfield/cli @higgsfield/cli` (bez `--allow-scripts` binarka sie nie pobierze).
- Logowanie: `higgsfield auth login` (OAuth w przegladarce) - **tylko uzytkownik** (`zaloguj-higgsfield.bat`). Potem
  `workspace set <id>` (bez tego 'No workspace selected'). PowerShell blokuje shim .ps1 -> `higgsfield.cmd` albo pelna sciezka hf.exe.
  Token w `~/.config/higgsfield/credentials.json`. Konto: plan Ultra.
- Koszt video_edit (zmierzone 2026-10-01, 6 s zrodlo, 5 ref): 480p ? / 720p 45 kr / 1080p 72 kr; `--duration` nie zmienia
  ceny edycji (liczy sie dlugosc zrodla); `--draft true` = 21 kr (podglad). `generate cost` z UUID-ami ~12 s, ze sciezkami ~60 s.
- Referencje wgrane raz: `python fabryka.py wgraj` -> `modelki/<slug>/uploady.json` (UUID per plik, cache po size+mtime).
- `hf` w PATH na tej maszynie to CLI Hugging Face, nie Higgsfield - wrapper uzywa pelnej sciezki do `vendor\hf.exe`.
- Seedance 2.5: `seedance_2_5`, `--mode t2v|omni_reference|video_edit|video_extension`, media `--video`, `--image`
  (repeatable), `--start-image`, `--end-image`, `--audio`; parametry `--aspect_ratio`, `--resolution 480p|720p|1080p`,
  `--duration 4-30`. Schema: `python fabryka.py model seedance_2_5` (wymaga logowania).
- `higgsfield generate cost <model> ...` liczy kredyty bez generacji - fabryka robi to przed kazda pozycja.
- `higgsfield account status --json` = saldo. Jarvis (`..\claudzik\jarvis\sources\higgsfield.py`) czyta je stad.
- Virality Predictor = `brain_activity --video <plik>` (kosztuje kredyty).
- Cennik apki (Seedance 2.5, 10 s): 30 kr 480p / 70 kr 720p / 120 kr 1080p; Edit liczy input + output.

## Prompty

- Prompty usera sa STALE per persona i NIE zaleza od klipu ("complete character replacement", strój z filmu
  albo ze zdjecia). `skanuj` z `prompt_auto=true` wpisuje je automatycznie. Agent nie pisze promptow od zera.
- `@[Image N](image_N)` w prompcie = N-ty `--image` w kolejnosci: referencje/ (01_, 02_...) a na koncu strój.
  Liczba @Image w prompcie MUSI zgadzac sie z liczba zdjec: Alicja 4, Noemi 5 (+1 strój w B), Bianka 6 (6 = tatuaz).
- Agent moze dopisac do promptu krotka notatke per klip tylko gdy klip tego wymaga (np. tatuaze, tekst na ekranie),
  i tylko na koncu, nie zmieniajac tresci usera. Zmiany w samych plikach prompty/*.txt robi tylko user.
- Brak promptu / referencji -> nie zgaduj, popros usera.
- Czy skladnia `@[Image N](image_N)` dziala przez CLI tak jak w apce - do potwierdzenia na pierwszej generacji.

## Granice

- Nie scrapuj Instagrama; zrodla i referencje dostarcza uzytkownik.
- Wizerunek realnych osob tylko za ich zgoda. Content jest AI - nie pomagaj udawac, ze jest inaczej.
- Bezpiecznik budzetu (min_kredyty, max_kredyty_na_rolke) zmienia tylko user.
- Publikacja jest reczna. Fabryka konczy na pliku w `wyniki/`.
