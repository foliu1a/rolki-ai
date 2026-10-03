# rolki-ai — instrukcja dla Claude

Fabryka rolek AI per "modelka" (persona): filmik zrodlowy -> Seedance 2.5 Edit (CLI Higgsfield) albo Wan 3.0 (yapper.so API)
-> Media Tool -> lipsync (sync.so) -> gotowy plik + podpis; do tego zdjecia persony i autopilot.
Wlasciciel prowadzi wlasne AI-persony (np. @uroczanoemi) na materialach, do ktorych ma prawa.

## Podzial rol

- Subagent **rolkarz** (`~/.claude/agents/rolkarz.md`) - produkcja: oglada klatki, pisze prompty,
  odpala fabryke, ocenia wyniki. Komenda uzytkownika: `/rolki` (`~/.claude/skills/rolki/SKILL.md`).
- Ty (glowna sesja / tom) - kod fabryki, panel, integracje.

## Foldery usera (2026-10-03)

- Panel przy starcie (`app._foldery_na_pulpicie` -> `baza.przygotuj_foldery_pulpitu_wszystkich`) i `POST /api/modelki` tworza na pulpicie
  `ROLKI AI\tu wrzucasz rolki\<Nazwa>` (`zrodla_dir`), `ROLKI AI\tu rolki zrobione\<Nazwa>` (`wyniki_dir`, PO Media Tool),
  `ROLKI AI\tu zdjecia zrobione\<Nazwa>` (`zdjecia_dir`). Nazwa folderu = nazwa z profilu (Noemi, Alicja, Bianka).
  Stare `ROLKI AI\przed\<slug>` / `po\<slug>` sa przenoszone (rename) razem ze sciezkami w pomysly/zdjecia/lipsync.json.
  Wlasny folder usera (inny) zostaje. `ROLKI_PULPIT` w env nadpisuje korzen (testy: tmp). `python fabryka.py foldery`.
- Surowy wynik zostaje w `modelki/<slug>/wyniki/NNN_nazwa.raw.mp4`, klatki w `modelki/<slug>/klatki/`,
  lipsync w `wyniki_dir/NNN_nazwa_lipsync.mp4`.
- Zdjecia person (zrodlo): `Desktop\ROLKI AI\<persona>\` - skopiowane do `referencje/` z numeracja.

## Budzet i powtorki

- `budzet.json` (wspolny): `max_kredyty_dziennie` = 300 (user) + `wydatki` per dzien = Higgsfield; `dostawcy.yapper` i
  `dostawcy.sync` osobno (`baza.limit_dzienny(d)`, `baza.wydano_dzis(d)`, `baza.dopisz_wydatek(kr, d)`).
  Liczy FAKTYCZNE zuzycie (saldo przed - saldo po), bo Seedance przy odrzuceniu oddaje kredyty. sync.so nie ma salda -
  liczymy szacunek w centach USD z dlugosci wyniku.
- `powtorki` (ustawienia, 2): przy odrzuceniu/bledzie powtarza po 10 s. Job "completed" bez `result_url`: dostawca
  najpierw doczytuje `generate get <id>` 5x (0 kr, `hf.doczytaj_url`), a gdy dalej nic - status blad BEZ powtorki.
- `min_kredyty` (200) i `max_kredyty_na_rolke` (150) = Higgsfield; yapper ma wlasne `yapper.min_kredyty` /
  `yapper.max_kredyty_na_rolke` (inna skala kredytow). Zmienia tylko user. Autopilot dodatkowo `autopilot_max_rolek_dziennie`.
- Koszt rolki rosnie z DLUGOSCIA zrodla (edit = wejscie + wyjscie): `fabryka.KR_NA_SEKUNDE` 720p ~7.5 kr/s, 1080p ~12 kr/s. Dlatego
  `max_sekund_rolki` (domyslnie 15; `skanuj` tnie dluzsze zrodla na takie kawalki) i zestawy `PRESETY_JAKOSCI` oszczednie (720p/10 s,
  ~75 kr) / normalnie (720p/15 s, ~112 kr) / najlepiej (1080p/15 s, ~180 kr > max/rolka 150 -> panel ostrzega). `jakosc_i_koszt(slug)`,
  `POST /api/ustawienia/preset`, `dzis.rolek_zostalo` w /api/stan. Szacunek tylko do podpowiedzi - prawdziwa cena z `generate cost`.
- Filtr tresci (status `nsfw` / `ip_detected`): `fabryka.powod_odrzucenia` -> pomysl dostaje `powod` (nsfw|ip|inny); po DWOCH
  odrzuceniach NSFW z rzedu petla powtorek konczy (kredyty wracaja, ale czas nie). `fabryka.wskazowki_nsfw(slug)` / `GET /api/nsfw` /
  `python fabryka.py nsfw`: ryzykowne slowa w promptach (`SLOWA_RYZYKOWNE`), liczba odrzucen, wskazowki. Filtr Higgsfield+Seedance
  sprawdza naraz filmik, referencje, stroj i prompt - user mial odrzucenia "mimo niewinnego filmiku" najpewniej przez zdjecia strojow
  (siatka/koronka/przeswity) i slowa typu mesh/sheer/lingerie w promptach.

## Postprodukcja

- Wideo: `mediatool.py` odpala worker Media Tool headless (`ELECTRON_RUN_AS_NODE=1 "Media Tool.exe" worker.cjs <json>`,
  env MEDIA_FFMPEG/FFPROBE/EXIFTOOL/ASSETS_DIR jak w main.cjs). ~4 s/klip, h264_amf, iPhone 17 Pro Max + GPS.
  Wlaczone `mediatool=true`; recznie `python fabryka.py pierz <id>` albo `--plik x.mp4`.
- Zdjecia: Suczkowatka (osobna apka, [[suczkowatka-synthid]]) - fabryka robi zdjecia (zdjecia.py), ale ich nie "pierze".
  Stroje (character elements) z `stroje/`: `zdjecia_stroje=true` -> co drugie zdjecie w kolejnym stroju (strój = OSTATNI obraz +
  `zdjecia_prompt_stroj` doklejony do promptu); recznie `stroj=auto|bez|<plik>` (API/CLI `--stroj`). Modele *soul* bez strojow.
- Lipsync TYLKO recznie (panel -> Lipsync / CLI). Autopilot wola `fabryka.generuj(lipsync=False)`; `lipsync_auto` (domyslnie False)
  dziala wylacznie przy recznym "Zrob rolke". Glos z Telegrama z podpisem = nazwa filmiku -> `pomysl.audio` (do recznego lipsyncu).
- VideoRemixer (`warianty`) wylaczony (0) - user go nie uzywa.

## Pliki

```
fabryka.py          logika + CLI (status, diagnoza, skanuj, prompt, koszt, generuj, pierz, zdjecia, lipsync, autopilot, ocen,
                    warianty, podpis, wgraj, ustaw, budzet, model, modele, glosy, konto). Funkcje skanuj()/koszt()/generuj()/
                    pierz()/podpis()/podglad() przyjmuja (slug, ..., log=, stop=) - wola je CLI, panel i autopilot.
                    podglad(slug, pid) = tani draft (~21 kr), pomysl zostaje 'nowy' (podglad_plik). sprawdz_prompt(slug) =
                    ostrzezenia o @Image vs liczba zdjec (nie blokuje). diagnoza() = ffmpeg/Higgsfield/Media Tool/Telegram/persony.
                    skanuj: zrodlo > 30 s -> klatki.potnij na kawalki (dziel_dlugie), _klatki_wyniku po generacji.
autopilot.py        petla: telefon (Telegram) -> skanuj -> generuj (max rolek/dzien, HAMULEC autopilot_stop_po_bledach) -> pranie
                    -> zdjecia -> podpisy (+hashtagi z profilu) -> gotowe rolki na Telegram (konto persony `telegram_czat` albo czat
                    glowny; `czat_persony`) -> raport dnia po 20:00. BEZ lipsyncu.
                    Stan hamulca: modelki/<slug>/autopilot_stan.json (pauza, bledy_z_rzedu) - baza.autopilot_pauza/wznow.
                    Z Telegramem przebieg co 60 s (ODSTEP_TELEGRAM_S). Komendy z telefonu: /status /raport /stop /wznow /pomoc
                    (/stop i /wznow tylko z czatu glownego). Odpowiedzi ida na czat nadawcy.
zdjecia.py          zdjecia persony: zdjecia_model + referencje (albo soul_id dla modeli *soul*), prompty/zdjecia.txt w kolko
lipsync.py          zrob(slug, wideo, audio, styl=) -> przygotuj_glos (ffmpeg: styl telefon = pasmo mikrofonu + krotkie odbicia pokoju +
                    kompresja + szum + loudnorm -16 LUFS; czysty = loudnorm; brak = bez zmian; ogg z Telegrama -> mp3) -> sync.so
                    (multipart <20 MB, wieksze zmniejsza ffmpeg) albo model Higgsfield -> wyniki/<n>_lipsync.raw.mp4 -> Media Tool
                    (jak rolka) -> wyniki_dir/<n>_lipsync.mp4; tts_z_tekstu. Ustawienie lipsync_glos_styl. Autopilot wysyla wersje
                    z ustami na Telegram raz (telegram_wyslano_lipsync). api.sync.so jest ZABLOKOWANE z chmury - testy tylko lokalnie.
dostawcy/           wspolny interfejs (gotowy/saldo/koszt/podglad/generuj/pobierz): higgsfield.py (CLI), yapper.py (REST),
                    sync_so.py (REST lipsync/TTS), telegram.py (Bot API: odbierz(dozwolone)/pobierz_plik/wyslij_wideo(chat_id);
                    telegram.json obok stan.json: chat_id = czat glowny (pierwszy, ktory napisal), `czaty` = sparowane konta person
                    (tylko te z ustawien telegram_czat; obce ignorowane); `czat_dla(konto)`; limity 20 MB pobieranie / 50 MB
                    wysylka), http.py (urllib: JSON, multipart, PUT, pobierz, powtorki)
higgsfield_cli.py   wrapper na CLI @higgsfield/cli (subprocess + --json); NIE ma tu klucza API - logowanie OAuth robi user
                    env (YAPPER_API_KEY, SYNC_API_KEY, TELEGRAM_BOT_TOKEN...) albo klucze.json (.gitignore, chmod 600)
mediatool.py        most do Media Tool (C:\claude programy\Media Tool) - pranie wideo bez GUI
klatki.py           ffprobe/ffmpeg: info, klatki PNG, arkusz.jpg (siatka do ogladania), potnij (dlugie zrodla na kawalki po 30 s)
sekrety.py          klucze API (yapper, sync, elevenlabs, telegram = token bota)
baza.py             warstwa danych (modelki/<slug>/*.json, budzet, dziennik.jsonl) - zawsze przez nia, nie edytuj JSON-ow recznie
postprocess.py      most do ..\VideoRemixer (NIE modyfikowac VideoRemixera)
app.py              panel Flask :5077 - kontrakt w API.md; jedno zadanie w tle naraz (Konsola), autopilot jako watek,
                    /api/plik serwuje tylko z folderow modelek/wrzutni/gotowych/zdjec; /api/zamknij (aktualizuj.bat),
                    /api/statystyki, /api/diagnoza, /api/autopilot/wznow; saldo w tle (stale-while-revalidate)
templates/, static/ index.html + style.css + app.js (SPA, vanilla JS, bez CDN), widget.html (/widget - male okno)
panel.py            stary panel w konsoli
modelki/<slug>/
  ustawienia.json   patrz baza.USTAWIENIA_DOMYSLNE (komentarze = dokumentacja): dostawca, model/mode/aspect/resolution/duration,
                    mode_bez_zrodla, yapper{model,resolution,duration,prompt,min_kredyty,max_kredyty_na_rolke}, prompty A/B,
                    stroj_domyslny, prompt_auto, soul_id, min_kredyty, max_kredyty_na_rolke, powtorki, zrodla_dir, wyniki_dir,
                    mediatool, autopilot*, telegram_wysylaj, telegram_czat, zdjecia_* (+zdjecia_stroje, zdjecia_prompt_stroj),
                    lipsync_* (lipsync_auto domyslnie False), tts_*
  prompty/          stroj_z_filmu.txt (A), stroj_ze_zdjecia.txt (B), zdjecia.txt - PROMPTY USERA, nie zmieniaj tresci
  zrodla/           WRZUTNIA (gdy zrodla_dir puste); <nazwa>.stroj.png = wariant B, <nazwa>.audio.mp3 = lipsync po generacji
  referencje/       zdjecia persony, 01_, 02_... = kolejnosc @[Image N] w prompcie (-> --image)
  stroje/ audio/    stroje do wariantu B; glosy do lipsyncu (panel: upload)
  wyniki/ zdjecia/  surowe rolki NNN_nazwa.raw.mp4, NNN_podpis.txt; zdjecia NNN_data.png
  pomysly.json      kolejka; statusy: nowy -> wygenerowany -> postprodukcja -> gotowe (+ blad); pola dostawca, audio, lipsync_plik,
                    podpis, klatki_wyniku (siatka klatek GOTOWEJ rolki), telegram_wyslano, powod (nsfw|ip|inny przy bledzie)
  pociete.json      dlugie zrodla (>30 s) juz pociete na modelki/<slug>/zrodla_ciete/ (skanuj je pomija; dziel_dlugie)
  autopilot_stan.json  hamulec: bledy_z_rzedu, pauza, pauza_od
  zdjecia.json / lipsync.json / uploady.json / uploady_yapper.json / profil.json / szablony.json / teksty.json / uzyte_tekstow.json
```

Zmienna `ROLKI_MODELKI` przenosi folder modelek gdzie indziej (testy, dysk D:); stan.json, budzet.json, dziennik.jsonl, klucze.json
i telegram.json leza wtedy obok tego folderu.

Pliki .bat dla usera (nietechniczny - komunikuj sie z nim przez "kliknij dwa razy w X.bat"): skrot "Rolki AI" na pulpicie
(skroty.vbs pulpit -> rolki.vbs: panel w tle `python app.py --autopilot --bez-przegladarki` + FIREFOX `-new-tab` (szukany w App Paths
HKCU/HKLM, %ProgramFiles%, %ProgramFiles(x86)%, %LOCALAPPDATA%; bez Firefoksa domyslna przegladarka); ikona static/rolki.ico,
generator w scratchpadzie), panel.bat (panel z oknem - do ogladania bledow; ten sam Firefox przez env BROWSER="cmd /c start ...
-new-tab %s" dla webbrowser w app.py), aktualizuj.bat (git pull z main-mj7alw + testy +
odswiezenie skrotu + panel), autostart.bat / autostart-usun.bat (skrot w folderze Autostart -> start-cicho.vbs; BEZ schtasks, bo
user dostawal "Odmowa dostepu"), skrot-na-pulpit.bat, zaloguj-higgsfield.bat, instaluj.bat, widget.bat, autopilot.bat.
Statyczne pliki panelu maja `?v=WERSJA` (app.WERSJA) - podbij przy zmianach w static/, inaczej przegladarka usera trzyma stary app.js.

## Testy

`python -m pytest` (raz: `python -m pip install pytest flask`). Testy w `tests/` dzialaja na katalogu tymczasowym,
udawanym CLI Higgsfield (`tests/conftest.py`: `UdawaneCLI`) i udawanym HTTP (`tests/test_dostawcy.py`: `UdawanyHTTP`) -
nie wydaja kredytow, nie ruszaja `modelki/`, `budzet.json`, kluczy ani Media Tool. Panel: `tests/test_app.py` (Flask test client).
Nowa logika = nowy test.

## Higgsfield CLI - fakty (zweryfikowane na binarce 1.1.26, 2026-10-02)

- Instalacja: `npm install -g --allow-scripts=@higgsfield/cli @higgsfield/cli` (bez `--allow-scripts` binarka sie nie pobierze).
- Logowanie: `higgsfield auth login` (OAuth w przegladarce) - **tylko uzytkownik** (`zaloguj-higgsfield.bat`). Potem
  `workspace set <id>` (czysto lokalne, zapis do config.json). PowerShell blokuje shim .ps1 -> `higgsfield.cmd` albo pelna sciezka hf.exe.
  Token w `~/.config/higgsfield/credentials.json`. Konto: plan Ultra.
- Zmiana konta (zrobiona 2026-10-03, nowe konto ma ~5700 kr): `hf.exe auth logout` -> `python zaloguj_firefox.py --prywatne`
  (okno prywatne Firefoksa, bo zwykle okno pamieta STARE konto i zatwierdza je od razu) -> `workspace list` + `workspace set <id>`
  -> `python fabryka.py --modelka <slug> wgraj --od-nowa` dla kazdej persony (UUID-y referencji sa per konto; wgranie ~1,5 kr/plik).
  Logowanie i generowanie sa TYLKO lokalne na laptopie - sesje w chmurze nie maja i nie potrzebuja konta Higgsfield.
- `generate create --wait --json` drukuje LISTE jobow `{id, job_type, display_name, status, created_at, params, result_url,
  min_result_url, thumbnail_url?}`; bez `--wait` liste UUID-ow (stringi). CLI widzi TYLKO result_url/min_result_url.
  Statusy: queued, pending, in_progress, completed, failed, nsfw, ip_detected, canceled. Job nieudany z --wait = exit 3.
  `completed` + `result_url: null` = exit 0 -> wrapper doczytuje `generate get` (hf.doczytaj_url).
- `generate cost` -> `{"credits": N}`; `account status --json` -> `{credits, email, subscription_plan_type}`; `upload create` -> `{id,type,url}`;
  `model get <jst> --json` -> `{display_name, job_type, type, params[{name,type,default,required,enum}], rules}`.
- Koszt video_edit (zmierzone 2026-10-01, 6 s zrodlo, 5 ref): 480p ? / 720p 45 kr / 1080p 72 kr; `--duration` nie zmienia
  ceny edycji (liczy sie dlugosc zrodla); `--draft true` = 21 kr (podglad). `generate cost` z UUID-ami ~12 s, ze sciezkami ~60 s.
- Referencje wgrane raz: `python fabryka.py wgraj` -> `modelki/<slug>/uploady.json` (UUID per plik, cache po size+mtime).
- `hf` w PATH na tej maszynie to CLI Hugging Face, nie Higgsfield - wrapper uzywa pelnej sciezki do `vendor\hf.exe`.
- Seedance 2.5: `seedance_2_5`, `--mode t2v|omni_reference|video_edit|video_extension`, media `--video`, `--image`
  (repeatable), `--start-image`, `--end-image`, `--audio`; parametry `--aspect_ratio`, `--resolution 480p|720p|1080p`,
  `--duration 4-30`. Schema: `python fabryka.py model seedance_2_5` (wymaga logowania).
- Modele obrazu (do zdjec): `nano_banana_2` (= Nano Banana Pro, image_references <=14), `nano_banana_flash`, `seedream_v4_5`,
  `text2image_soul_v2` (`--soul-id` z `soul-id create --soul-2 --image x5-20`, wymaga planu Basic+), `gpt_image_2`.
  Lista: `python fabryka.py modele --typ image`. TTS: `text2speech_v2 --variant elevenlabs --voice_id --voice_type preset|element`
  (glosy: `python fabryka.py glosy`). Brak osobnego modelu lipsync w CLI (lipsync = `--audio` w omni_reference) - dlatego sync.so.
- Issue cli#94: prompt z PUSTA LINIA bywa ucinany na pierwszym akapicie -> dostawcy/higgsfield.py skleja akapity
  (`_prompt_na_drut`), tresc bez zmian.
- `higgsfield account status --json` = saldo. Jarvis (`..\claudzik\jarvis\sources\higgsfield.py`) czyta je stad.
- Virality Predictor = `brain_activity --video <plik>` (kosztuje kredyty).
- Cennik apki (Seedance 2.5, 10 s): 30 kr 480p / 70 kr 720p / 120 kr 1080p; Edit liczy input + output.

## yapper.so i sync.so - fakty (z dokumentacji, 2026-10-02; nie testowane na zywo)

- yapper: `https://yapper.so/api/v1`, `Authorization: Bearer <klucz>` (Account -> API -> Create key, Read+Write; platny plan).
  `GET /credits` (availableCredits), `GET /models`, `POST /processes` `{type:"video-generation", model:"wan-3.0", input:{prompt,
  aspectRatio, resolution:1080, videoLength, referenceImages:[{assetId|url}], referenceVideos:[...]}, dryRun}` + `Idempotency-Key`,
  `GET /processes/{id}` (queued|processing|completed|failed, outputs[].url, creditsUsed), `POST /assets/uploads` (bilet -> PUT ->
  completeUrl; DOKLADNE POLA BILETU NIEZWERYFIKOWANE - patrz https://yapper.so/api/v1/openapi.json). Wan 3.0 1080p ~50 kr/s, Prime ~25 kr/s.
- sync.so: `https://api.sync.so/v2`, `x-api-key` (sync.so/settings/api-keys). `POST /generate` JSON (URL-e) albo multipart
  (`video`, `audio` <20 MB + `model`, `options`), `GET /generate/{id}` (PENDING|PROCESSING|COMPLETED|FAILED|REJECTED, outputUrl),
  `POST /analyze/cost` (USD), `POST /tts` {script, voiceId, provider:"elevenlabs"}, `GET /voices`, `GET /models`
  (lipsync-2, lipsync-2-pro, sync-3). Rozliczenie z dolu (bez salda); darmowy plan: 3 generacje/mies, 20 s, watermark.
- Pierwsze prawdziwe wywolania robi user lokalnie; jak API odpowie inaczej niz w dostawcy/*.py, popraw parser (testy w tests/test_dostawcy.py).

## Prompty

- Prompty usera sa STALE per persona i NIE zaleza od klipu ("complete character replacement", strój z filmu
  albo ze zdjecia). `skanuj` z `prompt_auto=true` wpisuje je automatycznie. Agent nie pisze promptow od zera.
- `@[Image N](image_N)` w prompcie = N-ty `--image` w kolejnosci: referencje/ (01_, 02_...) a na koncu strój.
  Liczba @Image w prompcie MUSI zgadzac sie z liczba zdjec: Alicja 4, Noemi 5 (+1 strój w B), Bianka 6 (6 = tatuaz).
  CLI przekazuje prompt doslownie (nie zna tej skladni) - czy backend ja honoruje, potwierdzic na pierwszej taniej generacji
  (`--draft true` / 480p). yapper dostaje prompt bez tej skladni (`yapper.prompt` = osobny prompt dla Wan, gdy ustawiony).
- Agent moze dopisac do promptu krotka notatke per klip tylko gdy klip tego wymaga (np. tatuaze, tekst na ekranie),
  i tylko na koncu, nie zmieniajac tresci usera. Zmiany w samych plikach prompty/*.txt robi tylko user (panel -> Persona -> Prompty).
- Brak promptu / referencji -> nie zgaduj, popros usera.

## Granice

- Nie scrapuj Instagrama; zrodla i referencje dostarcza uzytkownik.
- Wizerunek realnych osob tylko za ich zgoda. Content jest AI - nie pomagaj udawac, ze jest inaczej.
- Bezpiecznik budzetu (min_kredyty, max_kredyty_na_rolke, limity dzienne, yapper.*) zmienia tylko user.
- Publikacja jest reczna. Fabryka konczy na pliku w folderze gotowych.
- Klucze API tylko w klucze.json / env - nigdy w kodzie, commitach ani w czacie.
