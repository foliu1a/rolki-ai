# rolki-ai

Fabryka rolek AI, osobno dla każdej "modelki" (persony). Wrzucasz filmiki źródłowe, fabryka podmienia
postać na Twoją personę (**Seedance 2.5 Edit** przez oficjalne CLI Higgsfield albo **Wan 3.0** przez API
yapper.so), pierze plik w Media Tool, robi lipsync z głosem (**sync.so**), zdjęcia persony i podpisy.
Panel w przeglądarce (ciemny, prosty) + **autopilot**, który robi to wszystko sam, w pętli, z bezpiecznikiem kredytów.

Nie jest to auto-publikacja - kończy się na pliku w folderze gotowych. Wrzucasz ręcznie.

## Założenie

Materiały źródłowe i wizerunek persony są Twoje albo masz do nich prawa. Narzędzie nie
służy do podmiany twarzy realnych osób bez ich zgody.

## Start (raz)

1. `instaluj.bat` (Python: flask, pytest; Node: CLI Higgsfield; odpala testy).
2. `zaloguj-higgsfield.bat` - logowanie CLI do Twojego konta Higgsfield (OAuth w Firefoksie). Kredyty idą z Twojego planu.
3. `panel.bat` → otwiera http://localhost:5077. W panelu:
   - **+ nowa modelka**, wrzuć zdjęcia persony (zakładka *Persona → Referencje*, przeciągnij pliki),
   - wklej swoje prompty A/B (*Persona → Prompty*),
   - ustaw foldery wrzutni i gotowych (*Persona → Foldery*), np. `C:\Users\yux\Desktop\ROLKI AI\przed\noemi`,
   - w *Konta* wpisz klucze API yapper.so i sync.so (jeśli chcesz z nich korzystać). Klucze zostają w `klucze.json` na Twoim dysku.
4. Bezpiecznik budżetu (*Persona → Bezpiecznik*): `min_kredyty`, `max_kredyty_na_rolke`, limit dzienny. Zmieniasz tylko Ty.

## Obieg pracy

Ręcznie (panel albo konsola):
1. Wrzuć filmiki do wrzutni (`przed\<persona>\`). Obok filmiku możesz położyć `<nazwa>.stroj.png` (strój ze zdjęcia, wariant B)
   i `<nazwa>.audio.mp3` (głos - po generacji fabryka zrobi lipsync).
2. **Skanuj** - każdy filmik dostaje numer, podgląd klatek i Twój prompt (A albo B).
3. **Policz koszt** - ile kredytów zejdzie. **Generuj** - z bezpiecznikiem (min_kredyty, max/rolka, limit dzienny, powtórki po odrzuceniu).
4. Gotowy plik ląduje w `po\<persona>\NNN_nazwa.mp4` (po Media Tool). Surowy wynik zostaje w `modelki\<slug>\wyniki\`.
5. Opcjonalnie: **Lipsync** (wideo + głos z folderu `audio/` albo TTS z tekstu), **Zdjęcia** (model obrazu z referencjami), **Podpis** z banku tekstów.

Automatycznie - **Autopilot** (przełącznik w panelu albo `autopilot.bat`): co `autopilot_co_minut` minut robi
skanuj → generuj → Media Tool → lipsync (gdy jest głos) → zdjęcia (`zdjecia_dziennie`) → podpisy, dla każdej modelki
z włączonym `autopilot`. Pilnuje `autopilot_max_rolek_dziennie`, limitu dziennego i salda. Ty tylko wrzucasz filmiki.

- **Hamulec**: po `autopilot_stop_po_bledach` (3) nieudanych rolkach z rzędu autopilot zatrzymuje personę, alarmuje
  na telefon i czeka na „Wznów” w panelu (albo `/wznow` z Telegrama) - nie pali kredytów w kółko.
- **Długie filmiki**: źródło dłuższe niż 30 s (limit Seedance) jest cięte na kawałki po 30 s (`dziel_dlugie`), każdy to osobna rolka.
- **Podpisy**: z banku tekstów + hashtagi persony (Ustawienia → Persona).
- **Tani podgląd**: zanim wydasz 45–72 kr na rolkę, „Tani podgląd (~21 kr)” w Rolkach pokaże, czy prompt działa (Seedance draft).
- **Porządki**: raz dziennie kasuje surowe pliki `.raw.mp4` starsze niż `sprzataj_po_dniach` (gdy gotowy plik jest)
  i robi kopię zapasową danych person (`modelki/_kopie/<data>/`, 7 dni).
- **Diagnoza**: panel (Start → „Pierwsze kroki”) i `python fabryka.py diagnoza` mówią, czego brakuje (ffmpeg, logowanie,
  Media Tool, Telegram, zdjęcia/prompty person). Prompty są sprawdzane pod kątem numerów `@[Image N]`.
- **Autostart z Windows**: `autostart.bat` (raz) - panel z autopilotem startuje po zalogowaniu, w tle. `autostart-usun.bat` wyłącza.

## Telefon jako pilot (Telegram)

1. W Telegramie napisz do **@BotFather**: `/newbot`, nadaj nazwę → dostaniesz token.
2. Panel → **Ustawienia → Konta → Telefon (Telegram)**: wklej token, „Zapisz”, „Testuj”.
3. Na telefonie napisz do swojego bota `/start` - od tej chwili jest sparowany (tylko ten czat).

Potem: wysyłasz botowi filmik (w podpisie możesz dać nazwę persony) → trafia do wrzutni → autopilot robi rolkę →
bot odsyła gotową rolkę z podpisem. Nagranie głosu z podpisem = nazwa filmiku → lipsync po generacji.
Komendy: `/status`, `/raport`, `/stop`, `/wznow`, `/pomoc`. Raport dnia przychodzi sam po 20:00.
Limity Telegrama: bot pobiera pliki do 20 MB, wysyła do 50 MB.

Konsola robi to samo: `python fabryka.py status | skanuj | koszt | generuj --tak | zdjecia | lipsync | autopilot --raz`.
`python fabryka.py generuj --dry-run` pokazuje komendy bez wydawania kredytów.

## Dostawcy

| Co | Kto | Logowanie | Gdzie w panelu |
|---|---|---|---|
| Rolki (Seedance 2.5 Edit) | Higgsfield CLI | OAuth: `zaloguj-higgsfield.bat` | Persona → Generowanie: dostawca *Higgsfield* |
| Rolki (Wan 3.0 / Wan 3.0 Prime, Seedance, Kling...) | yapper.so Public API | klucz API (yapper.so → Account → API, Read+Write, płatny plan) | Konta + Persona → Generowanie: dostawca *yapper* |
| Lipsync + TTS (ElevenLabs) | sync.so API | klucz API (sync.so/settings/api-keys) | Konta + Lipsync |
| Zdjęcia persony | Higgsfield CLI (np. `nano_banana_2`, `text2image_soul_v2` z Soul ID) | jak wyżej | Persona → Zdjęcia |

Kredyty każdego dostawcy liczymy osobno (`budzet.json`). Uwaga: kredyty yapper mają inną skalę niż Higgsfield
(Wan 3.0 1080p ≈ 50 kr/s, Prime ≈ 25 kr/s), dlatego yapper ma własny bezpiecznik (`yapper.min_kredyty`, `yapper.max_kredyty_na_rolke`).

## Struktura

```
rolki-ai/
  panel.bat / widget.bat / autopilot.bat / instaluj.bat / aktualizuj.bat / zaloguj-higgsfield.bat
  autostart.bat / autostart-usun.bat / start-cicho.vbs   autostart panelu z autopilotem (Harmonogram zadań Windows)
  app.py + templates/ + static/   panel Flask :5077 (API w API.md), /widget = małe okno z saldem i kolejką
  fabryka.py             logika: status / skanuj / koszt / generuj / pierz / zdjecia / lipsync / podpis / autopilot / ustaw / budzet
  autopilot.py           pętla: telefon -> skanuj -> generuj (hamulec) -> pranie -> lipsync -> zdjęcia -> podpisy -> rolka na telefon
  zdjecia.py             zdjęcia persony (model obrazu + referencje albo Soul ID)
  lipsync.py             wideo + głos -> sync.so (albo model Higgsfield); TTS z tekstu
  dostawcy/              higgsfield.py (CLI), yapper.py (API), sync_so.py (API), telegram.py (bot), http.py (urllib)
  higgsfield_cli.py      wrapper na CLI @higgsfield/cli (logowanie OAuth, bez kluczy w plikach)
  mediatool.py           most do Media Tool (pranie wideo bez GUI)
  klatki.py              klatki + arkusz podglądu z wideo (ffmpeg)
  baza.py                warstwa danych; sekrety.py = klucze API (klucze.json, w .gitignore)
  postprocess.py         most do ..\VideoRemixer (warianty, wyłączone)
  budzet.json            limity dzienne i wydatki per dostawca; dziennik.jsonl = log zdarzeń (panel → Dziennik)
  modelki/<slug>/
    ustawienia.json      model, dostawca, prompty, bezpiecznik, autopilot, zdjęcia, lipsync
    prompty/             stroj_z_filmu.txt (A), stroj_ze_zdjecia.txt (B), zdjecia.txt (1 linia = 1 zdjęcie)
    zrodla/              wrzutnia (gdy zrodla_dir puste); <nazwa>.stroj.png / <nazwa>.audio.mp3 obok filmiku
    referencje/          zdjęcia persony 01_, 02_... = kolejność @[Image N] w prompcie
    stroje/, audio/      stroje do wariantu B; głosy do lipsyncu
    wyniki/, zdjecia/    surowe wyniki; zdjęcia (gdy zdjecia_dir puste)
    pomysly.json, zdjecia.json, lipsync.json, teksty.json, uzyte_tekstow.json, szablony.json, profil.json
```

## Testy

```
python -m pytest
```

Testy nie łączą się z Higgsfieldem, yapperem ani sync.so i nie wydają kredytów (udawane CLI/HTTP i pliki tymczasowe).

## Przenosiny na inny komputer

Skopiuj `rolki-ai` (+ `VideoRemixer` obok, jeśli używasz), zainstaluj Pythona i Node.js, odpal `instaluj.bat`,
potem `zaloguj-higgsfield.bat` i wpisz klucze w panelu (Konta). `klucze.json`, `modelki/` i `budzet.json` przenieś ręcznie.
