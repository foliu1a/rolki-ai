# rolki-ai — instrukcja dla Claude

Fabryka rolek AI per "modelka" (persona): filmik zrodlowy -> Seedance 2.5 Edit (CLI Higgsfield), Wan 3.0 (yapper.so API) albo
Seedance 2.5 Edit Turbo (WaveSpeedAI API) -> Media Tool -> lipsync (sync.so) -> gotowy plik + podpis; do tego zdjecia persony i autopilot.
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

- `budzet.json` (wspolny, poza gitem): `max_kredyty_dziennie` = 300 (user) + `wydatki` per dzien = Higgsfield; `dostawcy.yapper`
  (limit 500/dzien - decyzja usera 2026-10-04) i `dostawcy.sync` osobno (`baza.limit_dzienny(d)`, `baza.wydano_dzis(d)`,
  `baza.dopisz_wydatek(kr, d, job_id=)`). Koszt liczony Z JOBA, nie z roznicy salda (user generuje tez recznie w apce - to nie zjada
  limitu fabryki): Higgsfield = wycena `generate cost` za udany job, 0 za odrzucony (kredyty wracaja); yapper = `creditsUsed`, 0 gdy
  `refunded`/failed. `rozliczone` (job_id per dostawca) = ten sam job liczy sie raz, takze po wznowieniu. sync.so: szacunek w centach USD.
  WaveSpeed (`dostawcy.wavespeed`): kwoty w CENTACH USD (saldo, wycena, limit dnia, `wavespeed.min_kredyty`/`max_kredyty_na_rolke`
  domyslnie 0/400 = $4); `WYMAGA_LIMITU` - bez dziennego limitu WaveSpeed ZERO zapytan (i jako dostawca rolek, i jako krok zapasu),
  wskazowka `fabryka.BRAK_LIMITU_WAVESPEED`. Koszt = wycena sprzed wyslania (WaveSpeed nie podaje kosztu w wyniku): udany = wycena,
  odrzucony przez moderacje = wycena na wszelki wypadek (Refund Policy nie mowi, czy oddaja), failed/timeout/cancelled = 0 (zwrot auto).
  Bezpieczniki dzienne licza `baza.wydano_z_rezerwa(d)` = wydane + `koszt_w_toku(d)` (wyceny rolek w toku wszystkich person), a
  `autopilot_max_rolek_dziennie` / `max_rolek` licza tez rolki w toku - kilka wolnych jobow naraz nie przebije limitu.
- `powtorki` (ustawienia, 2) = ponowne WYSLANIE tylko wtedy, gdy NIC nie poszlo (blad przed znacznikiem `wysylam`, np. przy wgrywaniu
  plikow) albo - u yappera - z tym samym Idempotency-Key. Higgsfield po `wysylam` NIGDY nie wysyla drugi raz: blad create = szukamy joba
  na `generate list` (po 5 s i 15 s), nie ma -> rolka czeka `w_toku` (`OKNO_NIEPEWNEGO_WYSLANIA_S` = 60 min od `wysylam_od`), potem
  status blad z prosba "Sprawdz w apce Higgsfield, czy rolka nie powstala" (wycena wliczona do limitu na wszelki wypadek). Blad trwaly
  (`_blad_trwaly`: brak kredytow, walidacja, logowanie) = job nie powstal, bez czekania i powtorek. Job, ktory powstal i padl, NIE jest
  wysylany drugi raz (status blad, "Sprobuj jeszcze raz" w panelu). Odrzucenie NSFW/IP: zero powtorek na tym samym modelu -> `zapas_nsfw`. Job "completed" bez `result_url`:
  doczytanie `generate get <id>` 5x (0 kr, `hf.doczytaj_url`), a gdy dalej nic - status blad BEZ powtorki.

## Generacja: job_id od razu, wznawianie (podwojne placenie - naprawione 2026-10-04)

- Kiedys: `generate create --wait`; zamkniecie panelu/aktualizacja/timeout = drugi, platny job (Noemi #2: 92 kr zamiast 46).
- Teraz (`fabryka._rolka` / `_wyslij` / `_czekaj`): znacznik `w_toku` w pomysle PRZED wyslaniem (status `w_toku`, `w_toku.etap
  wysylanie`) -> Higgsfield: WSZYSTKIE lokalne pliki wgrane osobno (`upload create`; filmik swiezo per proba = `w_toku.wideo_id`,
  referencje do cache), dopiero potem znacznik `wysylam` + `wysylam_od` i krotki `generate create` BEZ --wait; yapper:
  POST /processes ze stalym `Idempotency-Key = rolki-{slug}-{id}-{model}-{proba}` -> job_id zapisany od razu (`etap czeka`) ->
  odpytywanie `generate get` / `GET /processes/{id}` co 10 s. Timeout, blad sieci, STOP = rolka zostaje `w_toku`, dokanczamy TEN job.
- Wznawianie: start panelu (zadanie `wznow`, `fabryka.wznow_wszystkie`), kazde `generuj` (najpierw `wznow_w_toku`), autopilot (takze
  w pauzie / po limicie rolek), `python fabryka.py wznow`. Znacznik bez job_id: `wysylam` nieustawione = create nie ruszyl -> do kolejki;
  ustawione -> szukamy joba (`dostawca.znajdz`: Higgsfield po `wideo_id` na `generate list` - bez filtra czasu, yapper po
  `metadata.rolki_klucz`); brak: yapper po `CZAS_NA_WYSLANIE_S` (180 s) wraca do kolejki (ten sam klucz = ten sam proces), Higgsfield
  czeka 60 min od `wysylam_od`, potem blad "sprawdz w apce" (`_niepewne_wyslanie`) - nigdy samo nie wysyla. Lista jobow nie odpowiada
  > 24 h albo job po 24 h dalej "trwa" -> blad (bez nowego wysylania). Okno "wysylania" (`trwa_wysylanie`) trwa do zapisu job_id.
- WaveSpeed (2026-10-07) nie ma Idempotency-Key (`IDEMPOTENTNY = False`, sciezka jak Higgsfield): wszystkie media wgrane PRZED
  `wysylam`, `POST /{model}` RAZ (`powtorki=1`, tak robi oficjalne SDK). Odpowiedz 4xx = serwer odrzucil, zadanie NIE powstalo ->
  `znacznik(wysylam=False)` (fabryka moze wyslac ponownie; 429 = powtorka po 10 s, 400/401/402/403 = blad trwaly). Blad sieci / 5xx =
  nie wiadomo -> `wavespeed.znajdz`: lista `POST /predictions {model}` NIE ma wejsc zadania, wiec szuka po modelu i czasie (okno
  `wysylam_od` -3/+10 min) z pominieciem jobow znanych fabryce (`baza.znane_job_id`); DOKLADNIE jedno = nasze, zero/kilka = czekamy 60 min,
  potem blad "Sprawdz w apce WaveSpeed" (`fabryka.sprawdz_w_apce(dostawca)`) - nigdy drugie wysylanie.
- `baza.blokada_generacji(slug)` (plik `modelki/<slug>/generacja.lock`, msvcrt/fcntl) = jedna generacja naraz na persone takze miedzy
  procesami (panel + `python fabryka.py generuj` + agent) -> drugi dostaje stop "zajete".
- `/api/zamknij` i `aktualizuj.bat` nie zabijaja wysylania: panel konczy sie po bezpiecznym punkcie (`fabryka.trwa_wysylanie()`), bat
  czeka, az panel przestanie odpowiadac. Rolka `w_toku`: panel blokuje Ponow/Usun/zmiane statusu (409); jedyne wyjscie =
  "Przestan czekac (sprawdzilem w apce)" z potwierdzeniem (`POST /api/pomysly/<id>/przerwij {"potwierdzam": true}` -> blad + notatka).
- Zapisy JSON (pomysly, budzet, zdjecia, lipsync, ustawienia, autopilot_stan...) ida pod `baza._rmw(plik)` - blokada watkow i procesow
  (`<plik>.lock`), wiec PATCH panelu, autopilot i CLI nie nadpisza sobie znacznika `w_toku` ani wydatku stara kopia.
- Zdjecia (`zdjecia.py`, nadal `--wait`): blad po wyslaniu (timeout/siec, nie filtr) = status `niepewne` (job_id z tresci bledu),
  wycena zarezerwowana w limicie, przebieg sie konczy, autopilot liczy je jak zrobione (`zdjecia_z_dnia(z_niepewnymi=True)`).
  Lipsync przez Higgsfield: koszt z wyceny joba + limit dnia z rezerwa.

## Rozdzielczosc (zasada usera 2026-10-04)

- Klip <= 8 s -> 1080p, dluzszy -> 720p - Higgsfield (Seedance), yapper (Wan) i WaveSpeed (Turbo nie ma 480p -> 720p). Liczy sie dlugosc (pocietego) klipu z `info_zrodla`
  w chwili generacji (`fabryka.rozdzielczosc_rolki`, `PROG_1080P_S`); idzie do `generate cost`/dryRun, bezpiecznika i zapytania, zapisana
  w pomysle (`resolution`). Ustawienie `resolution` persony = tylko pomysly bez filmiku. Ciecie (`max_sekund_rolki`) bez zmian.
  Zmierzone `generate cost` 2026-10-04: 6,04 s -> 1080p 73 / 720p 46 kr; 10,03 s -> 1080p 121 / 720p 76 kr (1080p <= 8 s miesci sie w 150).
  Zestaw "najlepiej" = 1080p / rolki do 8 s (~96 kr).
- `min_kredyty` (200) i `max_kredyty_na_rolke` (150) = Higgsfield; yapper ma wlasne `yapper.min_kredyty` /
  `yapper.max_kredyty_na_rolke` (inna skala kredytow; domyslnie 400, persony utworzone wczesniej maja zapisane 1000). Zmienia tylko user.
  Autopilot dodatkowo `autopilot_max_rolek_dziennie`.
- Koszt rolki rosnie z DLUGOSCIA zrodla (edit = wejscie + wyjscie): `fabryka.KR_NA_SEKUNDE` 720p ~7.5 kr/s, 1080p ~12 kr/s. Dlatego
  `max_sekund_rolki` (domyslnie 15; `skanuj` tnie dluzsze zrodla na takie kawalki) i zestawy `PRESETY_JAKOSCI` oszczednie (720p/10 s,
  ~75 kr) / normalnie (720p/15 s, ~112 kr) / najlepiej (1080p/8 s, ~96 kr; rozdzielczosc i tak wybiera zasada <= 8 s). `jakosc_i_koszt(slug)`,
  `POST /api/ustawienia/preset`, `dzis.rolek_zostalo` w /api/stan. Szacunek tylko do podpowiedzi - prawdziwa cena z `generate cost`.
- Filtr tresci (status `nsfw` / `ip_detected`): `fabryka.powod_odrzucenia` -> pomysl dostaje `powod` (nsfw|ip|inny); BEZ powtorki na
  tym samym modelu. Zapas: ustawienie `zapas_nsfw` (domyslnie `[]` = wylaczone; panel tryb pelny -> "Gdy filtr odrzuci rolke") np.
  `[{"dostawca":"yapper","model":"wan-3.0-prime"},{"dostawca":"yapper","model":"wan-3.0"}]` - kazdy krok raz (`_przygotuj_zapas`):
  bez dziennego limitu yappera (albo wyczerpany) = ZERO zapytan do yappera + wskazowka w dzienniku; dalej saldo, dryRun (odmowa przy
  canStart=false/blockedBy), max/rolka i limit dnia yappera. Ten sam klip i referencje, prompt `prompty/wan.txt`, Wan dostaje max 15 s filmiku
  (dluzszy -> kopia `zrodla_ciete/<nazwa>_max15s.mp4`). Kazda proba w `p['proby']`; sukces: `zapas: true`, `model`, dziennik
  "NSFW -> zapas <model>". Miedzy krokami rolka ma status `nowy` + `krok_startowy` (awaria = rusza od zapasu). "Ponow" przy nsfw/ip
  z wlaczonym zapasem = `krok_startowy: 1`. Rolki ze strojem ze zdjecia (wariant B) NIE ida na zapas (wan.txt bierze stroj z filmu -
  zapas zgubilby stroj): zero zapytan do yappera, notatka w rolce. "not eligible" (plan) to nie IP - zapasu nie uruchamia. NSFW/IP to `wynik['odrzucone']` - hamulec autopilota ich nie liczy (tylko awarie techniczne).
  Kroki moga byc tez `{"dostawca": "wavespeed", "model": ...}` (`dostawcy.NAZWY_ZAPASU`, panel odrzuca innych). `_BezZapasu` (brak/wyczerpany
  limit, saldo) pomija tylko kroki TEGO dostawcy - krok innego dostawcy dalej probuje (`_nastepny_krok_innego_dostawcy`). Wariant B: krok
  WaveSpeed Seedance dostaje prompt persony (B, stroj = ostatnie @Image), wiec stroj zachowa (`zapas_dla_stroju`, "Ponow" od zapasu);
  kroki Wan (yapper, WaveSpeed Wan) sa pomijane, a gdy nie ma kroku Seedance - jak dawniej `_BezZapasu(wszystkie=True)`.
  `fabryka.wskazowki_nsfw(slug)` / `GET /api/nsfw` /
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
- Most do VideoRemixera (`warianty`, `postprocess.py`) usuniety z kodu 2026-10-04 (user go nie uzywal); `postprocess.py` czeka na skasowanie.

## Pliki

```
fabryka.py          logika + CLI (status, diagnoza, skanuj, prompt, koszt, generuj, pierz, zdjecia, lipsync, autopilot, ocen,
                    wznow, podpis, wgraj, ustaw, budzet, model, modele, glosy, konto). Funkcje skanuj()/koszt()/generuj()/
                    pierz()/podpis()/podglad() przyjmuja (slug, ..., log=, stop=) - wola je CLI, panel i autopilot.
                    podglad(slug, pid) = tani draft (~21 kr), pomysl zostaje 'nowy' (podglad_plik). sprawdz_prompt(slug) =
                    ostrzezenia o @Image vs liczba zdjec (nie blokuje). diagnoza() = ffmpeg/Higgsfield/Media Tool/Telegram/persony.
                    skanuj: zrodlo > 30 s -> klatki.potnij na kawalki (dziel_dlugie), _klatki_wyniku po generacji.
                    generuj(): wznow_w_toku -> kandydaci -> _rolka (krok 0 + zapas_nsfw) -> _wyslij / _czekaj / _rozlicz / _sukces.
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
dostawcy/           wspolny interfejs (gotowy/saldo/koszt/podglad/generuj/pobierz + rolki: zlec/sprawdz/koncowy/koszt_joba/znajdz/
                    IDEMPOTENTNY, JEDNOSTKA kr|c, WYMAGA_LIMITU; `dostawcy.kwota(k, nazwa)` = "46 kr" / "$2.60"):
                    higgsfield.py (CLI), yapper.py (REST; cialo per model z GET /models + schema.json, wycena dryRun),
                    wavespeed.py (REST WaveSpeedAI; MODELE = Seedance 2.5 Edit Turbo/Edit, Wan 3.0/Prime R2V z cennikiem; centy USD),
                    elevenlabs.py (TYLKO gotowy/saldo_szczegoly: zostalo znakow TTS z GET /v1/user/subscription - do paska sald;
                    NAZWY_SALDA = NAZWY + elevenlabs; glos z tekstu nadal przez sync.so),
                    sync_so.py (REST lipsync/TTS), telegram.py (Bot API: odbierz(dozwolone)/pobierz_plik/wyslij_wideo(chat_id);
                    telegram.json obok stan.json: chat_id = czat glowny (pierwszy, ktory napisal), `czaty` = sparowane konta person
                    (tylko te z ustawien telegram_czat; obce ignorowane); `czat_dla(konto)`; limity 20 MB pobieranie / 50 MB
                    wysylka), http.py (urllib: JSON, multipart, PUT, pobierz, powtorki)
higgsfield_cli.py   wrapper na CLI @higgsfield/cli (subprocess + --json); NIE ma tu klucza API - logowanie OAuth robi user
                    env (YAPPER_API_KEY, WAVESPEED_API_KEY, SYNC_API_KEY, TELEGRAM_BOT_TOKEN...) albo klucze.json (.gitignore, chmod 600)
mediatool.py        most do Media Tool (C:\claude programy\Media Tool) - pranie wideo bez GUI
klatki.py           ffprobe/ffmpeg: info, klatki PNG, arkusz.jpg (siatka do ogladania), potnij (dlugie zrodla na kawalki po 30 s)
sekrety.py          klucze API (yapper, wavespeed, sync, elevenlabs, telegram = token bota)
baza.py             warstwa danych (modelki/<slug>/*.json, budzet, dziennik.jsonl) - zawsze przez nia, nie edytuj JSON-ow recznie
postprocess.py      (nieuzywany - do skasowania, decyzja usera 2026-10-04)
app.py              panel Flask :5077 - kontrakt w API.md; jedno zadanie w tle naraz (Konsola), autopilot jako watek,
                    /api/plik serwuje tylko z folderow modelek/wrzutni/gotowych/zdjec; /api/zamknij (aktualizuj.bat),
                    /api/statystyki, /api/diagnoza, /api/autopilot/wznow; saldo w tle (stale-while-revalidate)
templates/, static/ index.html + style.css + app.js (SPA, vanilla JS, bez CDN), widget.html (/widget - male okno)
panel.py            (stary panel w konsoli - do skasowania, decyzja usera 2026-10-04)
modelki/<slug>/
  ustawienia.json   patrz baza.USTAWIENIA_DOMYSLNE (komentarze = dokumentacja): dostawca (higgsfield|yapper|wavespeed), model/mode/aspect/resolution/duration,
                    mode_bez_zrodla, yapper{model,resolution,duration,prompt,min_kredyty,max_kredyty_na_rolke},
                    wavespeed{model,generate_audio,parametry,min_kredyty,max_kredyty_na_rolke - centy USD}, prompty A/B,
                    stroj_domyslny, prompt_auto, soul_id, min_kredyty, max_kredyty_na_rolke, powtorki, zrodla_dir, wyniki_dir,
                    mediatool, autopilot*, telegram_wysylaj, telegram_czat, zdjecia_* (+zdjecia_stroje, zdjecia_prompt_stroj),
                    lipsync_* (lipsync_auto domyslnie False), tts_*
  prompty/          stroj_z_filmu.txt (A), stroj_ze_zdjecia.txt (B), zdjecia.txt - PROMPTY USERA, nie zmieniaj tresci;
                    wan.txt = prompt dla Wan (yapper/zapas): max 5000 znakow, bez @[Image N], "the reference photos" (2026-10-04: SZKICE
                    od Claude do akceptacji usera - zapas_nsfw wylaczony, dopoki ich nie zatwierdzi)
  zrodla/           WRZUTNIA (gdy zrodla_dir puste); <nazwa>.stroj.png = wariant B, <nazwa>.audio.mp3 = lipsync po generacji
  referencje/       zdjecia persony, 01_, 02_... = kolejnosc @[Image N] w prompcie (-> --image)
  stroje/ audio/    stroje do wariantu B; glosy do lipsyncu (panel: upload)
  wyniki/ zdjecia/  surowe rolki NNN_nazwa.raw.mp4, NNN_podpis.txt; zdjecia NNN_data.png
  pomysly.json      kolejka; statusy: nowy -> w_toku (job wyslany) -> wygenerowany -> postprodukcja -> gotowe (+ blad); pola dostawca,
                    model, resolution, w_toku (znacznik), proby, zapas, krok_startowy, audio, lipsync_plik, podpis, klatki_wyniku,
                    telegram_wyslano, powod (nsfw|ip|inny przy bledzie)
  pociete.json      dlugie zrodla (>30 s) juz pociete na modelki/<slug>/zrodla_ciete/ (skanuj je pomija; dziel_dlugie)
  autopilot_stan.json  hamulec: bledy_z_rzedu, pauza, pauza_od
  zdjecia.json / lipsync.json / uploady.json / uploady_yapper.json / uploady_wavespeed.json (URL-e plikow wgranych do WaveSpeed,
                    max 6 dni - WaveSpeed trzyma 7) / profil.json / szablony.json / teksty.json / uzyte_tekstow.json
  generacja.lock    blokada generacji (miedzy procesami)
```

Zmienna `ROLKI_MODELKI` przenosi folder modelek gdzie indziej (testy, dysk D:); stan.json, budzet.json, dziennik.jsonl, klucze.json
i telegram.json leza wtedy obok tego folderu. Te pliki (i server.log, *.tmp, *.lock) sa w .gitignore - `git pull` ich nie rusza.

Pliki .bat dla usera (nietechniczny - komunikuj sie z nim przez "kliknij dwa razy w X.bat"): skrot "Rolki AI" na pulpicie
(skroty.vbs pulpit -> rolki.vbs: panel w tle `python app.py --autopilot --bez-przegladarki` + FIREFOX `-new-tab` (szukany w App Paths
HKCU/HKLM, %ProgramFiles%, %ProgramFiles(x86)%, %LOCALAPPDATA%; bez Firefoksa domyslna przegladarka); ikona static/rolki.ico,
generator w scratchpadzie), panel.bat (panel z oknem - do ogladania bledow; ten sam Firefox przez env BROWSER="cmd /c start ...
-new-tab %s" dla webbrowser w app.py), aktualizuj.bat (/api/zamknij + CZEKA, az panel skonczy wysylanie i przestanie odpowiadac,
potem git pull z main-mj7alw + testy + odswiezenie skrotu + panel), autostart.bat / autostart-usun.bat (skrot w folderze Autostart ->
start-cicho.vbs; BEZ schtasks, bo user dostawal "Odmowa dostepu"), skrot-na-pulpit.bat (sam skrot, bez aktualizacji), zaloguj-higgsfield.bat,
instaluj.bat. autopilot.bat i widget.bat - do skasowania (decyzja usera 2026-10-04; drugi autopilot obok panelu i tak dostanie "zajete").
Statyczne pliki panelu maja `?v=WERSJA` (app.WERSJA) - podbij przy zmianach w static/, inaczej przegladarka usera trzyma stary app.js.

## Testy

`python -m pytest` (raz: `python -m pip install pytest flask`). Testy w `tests/` dzialaja na katalogu tymczasowym,
udawanym CLI Higgsfield (`tests/conftest.py`: `UdawaneCLI`) i udawanym HTTP (`tests/test_dostawcy.py`: `UdawanyHTTP`) -
nie wydaja kredytow, nie ruszaja `modelki/`, `budzet.json`, kluczy ani Media Tool. Panel: `tests/test_app.py` (Flask test client).
Nowa logika = nowy test. `UdawaneCLI` udaje tez serwer jobow (`generate create` bez --wait zapisuje job, `job()` = generate get,
`joby()` = generate list); `UdawanyHTTP` porownuje DOKLADNE adresy (pelne URL-e - endswith ukryl kiedys sklejony completeUrl).
Podwojne placenie/wznawianie: tests/test_wznawianie.py, zapas po NSFW: tests/test_zapas_nsfw.py, rozdzielczosc: tests/test_rozdzielczosc.py,
WaveSpeed (udawany HTTP `HTTPWaveSpeed` z automatycznymi biletami uploadu, DOKLADNE adresy https://api.wavespeed.ai/api/v3/...):
tests/test_wavespeed.py.

## Higgsfield CLI - fakty (zweryfikowane na binarce 1.1.26, 2026-10-02)

- Instalacja: `npm install -g --allow-scripts=@higgsfield/cli @higgsfield/cli` (bez `--allow-scripts` binarka sie nie pobierze).
- Logowanie: `higgsfield auth login` (OAuth w przegladarce) - **tylko uzytkownik** (`zaloguj-higgsfield.bat`). Potem
  `workspace set <id>` (czysto lokalne, zapis do config.json). PowerShell blokuje shim .ps1 -> `higgsfield.cmd` albo pelna sciezka hf.exe.
  Token w `~/.config/higgsfield/credentials.json`. Konto: plan Ultra.
- Zmiana konta (zrobiona 2026-10-03, nowe konto ma ~5700 kr): `hf.exe auth logout` -> `python zaloguj_firefox.py --prywatne`
  (okno prywatne Firefoksa, bo zwykle okno pamieta STARE konto i zatwierdza je od razu) -> `workspace list` + `workspace set <id>`
  -> `python fabryka.py --modelka <slug> wgraj --od-nowa` dla kazdej persony (UUID-y referencji sa per konto; wgranie jest darmowe - sprawdzone 2026-10-06 na 4 plikach Lilianny, saldo bez zmian).
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

## yapper.so i sync.so - fakty

- yapper (openapi https://yapper.so/api/v1/openapi.json; ZWERYFIKOWANE na zywo darmowym dryRun 2026-10-04): `https://yapper.so/api/v1`,
  `Authorization: Bearer <klucz>`. `GET /credits` (availableCredits), `GET /models` (lista: capabilities.maxPromptLength 5000,
  referenceVideos.maxCombinedDurationSeconds 15, maxReferenceImages 10, pricing), `GET /models/{id}/schema.json` (additionalProperties
  false - Wan NIE ma generateAudio; seedance-2.5-edit/genjutsu: aspectRatio const "auto"). `POST /assets/uploads {type, mimeType, name}`
  (0 kr) -> bilet `{assetId, uploadUrl (podpisany GCS), method PUT, headers{Content-Type, x-goog-content-length-range}, completeUrl
  ABSOLUTNY https://yapper.so/api/v1/assets/uploads/<id>/complete}` -> PUT z naglowkami biletu 1:1 -> POST completeUrl -> Asset{id}.
  `POST /processes {type:"video-generation", model, input:{prompt, aspectRatio "9:16", resolution 1080|720, durationMode "auto",
  referenceImages:[{assetId}], referenceVideos:[{assetId}]}, metadata, dryRun}` + `Idempotency-Key` (ten sam klucz + to samo cialo = ten
  sam proces; inne cialo = 409 idempotency_conflict). dryRun -> `{creditsEstimated, canStart, blockedBy, credits{available}}`.
  `GET /processes/{id}` (queued|processing|completed|failed, outputs[].url, creditsUsed, refunded: bool). Lista: `GET /processes?model=`
  -> `{data: [...]}`. Na zywo (Noemi #2, 6,04 s, 5 ref, 1080p, durationMode auto): wan-3.0-prime 130 kr (~137 s), wan-3.0 250 kr (~299 s)
  - to ceny 5 s z cennika, wiec wynik "auto" moze wyjsc o ~1 s krotszy niz klip. Konto: 7000 kr.
- sync.so: `https://api.sync.so/v2`, `x-api-key` (sync.so/settings/api-keys). `POST /generate` JSON (URL-e) albo multipart
  (`video`, `audio` <20 MB + `model`, `options`), `GET /generate/{id}` (PENDING|PROCESSING|COMPLETED|FAILED|REJECTED, outputUrl),
  `POST /analyze/cost` (USD), `POST /tts` {script, voiceId, provider:"elevenlabs"}, `GET /voices`, `GET /models`
  (lipsync-2, lipsync-2-pro, sync-3). Rozliczenie z dolu (bez salda); darmowy plan: 3 generacje/mies, 20 s, watermark.
- sync.so nie byl testowany na zywo. Jak API odpowie inaczej niz w dostawcy/*.py, popraw parser (testy w tests/test_dostawcy.py).

## WaveSpeedAI - fakty (z dokumentacji i oficjalnego SDK, 2026-10-07; BEZ klucza - nic nie bylo wolane na zywo)

- Zrodla: https://wavespeed.ai/docs (submit-task, get-result, upload-files-api, check-balance, pricing-api, predictions-api,
  error-codes, refund-policy), strony modeli, SDK github.com/WaveSpeedAI/wavespeed-python (`src/wavespeed/api/client.py`).
  Konto: logowanie Google/GitHub, bez KYC; platnosc przedplacona (karta/Stripe, PayPal...), kredyty nie wygasaja; poziom Bronze bez
  doladowania = 5 zadan/min, 2 naraz. Klucz: dashboard -> API Keys (https://wavespeed.ai/accesskey), `WAVESPEED_API_KEY` / panel Konta.
- `https://api.wavespeed.ai/api/v3`, `Authorization: Bearer`, koperta `{code, message, data}`. `GET /balance` -> data.balance (USD).
  `POST /{model_id}` (cialo = parametry modelu) -> data {id, status "created", urls.get}; `GET /predictions/{id}/result` -> status
  created|processing|completed|failed|cancelled|timeout|deleted, outputs [url], error. `POST /predictions {page, page_size, model}` ->
  data.items (bez wejsc zadania!). Upload: `POST /media/uploads {filename, size, content_type}` -> data {download_url, upload {method PUT,
  url podpisany, headers}} -> PUT naglowkami biletu 1:1 (BEZ klucza), bez "complete"; plik zyje 7 dni, max 200 MB. Stary sposob:
  `POST /media/upload/binary` multipart `file` (uzywany, gdy bilet da 404/405). Darmowa wycena: `POST /model/price {model_id, inputs}`
  -> {price, discounted_price (to sie placi), discount_rate} - media z inputs WaveSpeed mierzy sam.
- Bledy: 1200 moderacja ("The content contains sensitive information.") -> `status 'nsfw'` (+ `has_nsfw_contents` przy completed),
  1400/1401 parametry, 1402 media, 1407 insufficient_credits, 5004 timeout. Nieudane = zwrot automatyczny (Refund Policy).
- Modele (`wavespeed.MODELE`, panel: lista bez zapytania do API): `bytedance/seedance-2.5/video-edit-turbo` (domyslny; 720p/1080p,
  filmik max 15 s - dluzszy przycinamy do KOPII `zrodla_ciete/<nazwa>_max15s.mp4`, cena (wejscie+wyjscie) x $0.11 + wyjscie x $0.02
  (720p) / $0.04 (1080p): 10 s 1080p = $2.60, 720p = $2.40), `bytedance/seedance-2.5/video-edit` (480p $0.11, 720p $0.22, 1080p $0.55 za
  sekunde wejscia+wyjscia), `alibaba/wan-3.0/reference-to-video` ($0.05/0.10/0.20 za s filmiku ref + wyjscia) i `alibaba/wan-3.0-prime/...`
  ($0.075/0.15/0.30). Szacunek z cennika liczy sekundy w gore (Wan: "rounded up"); `wycena()` = WIEKSZA z cennika i API (cennik =
  podloga - API, ktore nie zmierzy filmiku albo poda 0, nie obnizy bezpiecznika). Na stronach jest teraz ~10% rabatu - bezpiecznik
  liczy pelna cene.
- Cialo: Seedance edit = `{prompt, video, reference_images, resolution, generate_audio}` (bez aspect_ratio - proporcje z filmiku);
  prompt = prompt persony A/B z `@[Image N](image_N)` -> `@Image N` (ta sama kolejnosc: referencje 01_, 02_..., stroj ostatni);
  `generate_audio=false` (domyslnie, `wavespeed.generate_audio`) = zostaje ORYGINALNY dzwiek filmiku. Wan R2V = `{prompt z wan.txt,
  reference_images, reference_videos, resolution, aspect_ratio 9:16, duration = dlugosc klipu (ref + wyjscie <= 30 s),
  enable_prompt_expansion false, generate_audio}`. `wavespeed.parametry` = dodatkowe pola (bez nadpisywania prompt/video/referencji).
- NIESPRAWDZONE do pierwszej generacji: limit dlugosci promptu Seedance na WaveSpeed (nieznany; nasze prompty A maja 7-13 tys. znakow -
  przy 1401 skrocic), czy WaveSpeed honoruje `@Image N` w edycji jak Higgsfield `@[Image N]`, dokladne ksztalty odpowiedzi (parser jest
  tolerancyjny), czy wycena API dziala dla video-edit, czy moderacja oddaje pieniadze. Pierwsza rolka: krotki klip 720p, sprawdzic koszt
  w dashboardzie WaveSpeed (Billing / historia) z `p['koszt']` i dziennikiem.

## Prompty

- Prompty usera sa STALE per persona i NIE zaleza od klipu ("complete character replacement", strój z filmu
  albo ze zdjecia). `skanuj` z `prompt_auto=true` wpisuje je automatycznie. Agent nie pisze promptow od zera.
- `@[Image N](image_N)` w prompcie = N-ty `--image` w kolejnosci: referencje/ (01_, 02_...) a na koncu strój.
  Liczba @Image w prompcie MUSI zgadzac sie z liczba zdjec: Alicja 4, Noemi 5 (+1 strój w B), Bianka 6 (06 = cala sylwetka z boku w dlugim rekawie - bez tatuazu; prompt Bianki mowi jeszcze o 5 zdjeciach - do decyzji usera).
  CLI przekazuje prompt doslownie (nie zna tej skladni) - czy backend ja honoruje, potwierdzic na pierwszej taniej generacji
  (`--draft true` / 480p). yapper NIGDY nie dostaje tej skladni: prompt Wan = `yapper.prompt` albo `prompty/wan.txt` (max 5000 znakow);
  `dostawcy/yapper.py` odmawia (zanim cokolwiek wysle) promptu z @[Image N], za dlugiego albo filmiku > 15 s.
  WaveSpeed Seedance dostaje prompt persony z zamiana `@[Image N](image_N)` -> `@Image N` (`wavespeed.prompt_na_wavespeed`, tresc bez
  zmian); WaveSpeed Wan - prompt Wan (te same zasady co yapper: bez @[Image N], max 5000 znakow).
- Agent moze dopisac do promptu krotka notatke per klip tylko gdy klip tego wymaga (np. tatuaze, tekst na ekranie),
  i tylko na koncu, nie zmieniajac tresci usera. Zmiany w samych plikach prompty/*.txt robi tylko user (panel -> Persona -> Prompty).
- Brak promptu / referencji -> nie zgaduj, popros usera.

## Granice

- Nie scrapuj Instagrama; zrodla i referencje dostarcza uzytkownik.
- Wizerunek realnych osob tylko za ich zgoda. Content jest AI - nie pomagaj udawac, ze jest inaczej.
- Bezpiecznik budzetu (min_kredyty, max_kredyty_na_rolke, limity dzienne, yapper.*, wavespeed.*) zmienia tylko user.
- Publikacja jest reczna. Fabryka konczy na pliku w folderze gotowych.
- Klucze API tylko w klucze.json / env - nigdy w kodzie, commitach ani w czacie.
