# API panelu rolki-ai (app.py, port 5077)

Wszystkie odpowiedzi to JSON: `{"ok": true, ...}` albo `{"ok": false, "blad": "..."}` (HTTP 400 / 409 zajęte / 500).
Panel: `GET /` (templates/index.html), widget: `GET /widget` (templates/widget.html), statyczne: `/static/...`.
Ścieżki plików (miniatury, wideo, zdjęcia) serwuje `GET /api/plik?s=<ścieżka>` – tylko z folderów modelki,
wrzutni, gotowych i zdjęć. Backend podaje gotowe pola `*_url` – frontend ich nie buduje sam.

## Stan ogólny

`GET /api/stan` (`?saldo=1` wymusza odświeżenie sald – normalnie cache 60 s)
```json
{"ok": true,
 "aktywna": "noemi",
 "modelki": [{"slug": "noemi", "nazwa": "Noemi", "autopilot": true, "dostawca": "higgsfield",
              "statystyki": {"nowy": 2, "wygenerowany": 0, "postprodukcja": 0, "gotowe": 5, "blad": 1}}],
 "stan": {                                   // null gdy brak aktywnej modelki
   "modelka": "noemi", "dostawca": "higgsfield",
   "ustawienia": {...pełne ustawienia modelki...},
   "statystyki": {"nowy": 2, "wygenerowany": 0, "postprodukcja": 0, "gotowe": 5, "blad": 1},
   "bez_promptu": [7], "do_generacji": [5, 6], "niezeskanowane": ["klip9.mp4"],
   "wrzutnia": "C:\\...\\przed\\noemi", "gotowe_dir": "C:\\...\\po\\noemi",
   "referencje": ["01_twarz.png", "02_sylwetka.jpg"], "prompt_a": true, "prompt_b": true,
   "budzet": {"dostawca": "higgsfield", "wydano_dzis": 90, "limit_dzienny": 300, "min_kredyty": 200,
              "max_kredyty_na_rolke": 150, "rolki_dzis": 2, "max_rolek_dziennie": 10},
   "zdjecia_dzis": 1, "audio": ["glos1.mp3"]},
 "saldo": {"higgsfield": {"kredyty": 1234, "blad": null, "czas": 1759440000.0},
           "yapper": {"kredyty": null, "blad": "brak klucza API yapper.so (panel -> Konta)", "czas": 1759440000.0}},
 "autopilot": {"wlaczony": true, "trwa": false, "modelka": null, "etap": "", "ostatni": 1759440000.0,
               "nastepny": 1759440900.0, "przebiegi": 3},
 "zadanie": {"trwa": false, "typ": null, "modelka": null, "start": null, "koniec": null, "wynik": null,
             "blad": null, "log_dlugosc": 0},
 "konta": {"higgsfield": {"ok": true, "komunikat": "zalogowany"},
           "yapper": {"jest": false, "ok": null, "komunikat": ""},
           "sync": {"jest": true, "ok": null, "komunikat": ""}},
 "dziennik_ostatni": {"czas": "...", "typ": "ok", "modelka": "noemi", "tekst": "#5: GOTOWE -> ..."},
 "autopilot_stan": {"bledy_z_rzedu": 0, "pauza": null, "pauza_od": null},   // hamulec aktywnej persony; pauza = powód (tekst) gdy zatrzymany
 "telegram": {"skonfigurowany": true, "sparowany": false, "czat": "", "czaty": [{"nazwa": "yux", "glowny": true}, {"nazwa": "huy7128", "glowny": false}]},
 "dzis": {"rolki": 3, "zdjecia": 1, "bledy": 0, "kredyty": {"higgsfield": 135, "yapper": 0, "sync": 0}, "rolki_persony": 2},
 "foldery": {"wrzutnia": "C:\\Users\\yux\\Desktop\\ROLKI AI\\tu wrzucasz rolki\\Noemi", "gotowe": "...\\tu rolki zrobione\\Noemi", "zdjecia": "...\\tu zdjecia zrobione\\Noemi"},
 "pulpit": "C:\\Users\\yux\\Desktop\\ROLKI AI",
 "wersja": "2.1"}
```
- Foldery na pulpicie (2.1): panel przy starcie (i `POST /api/modelki`) tworzy `Pulpit\ROLKI AI\tu wrzucasz rolki\<Persona>`,
  `...\tu rolki zrobione\<Persona>`, `...\tu zdjecia zrobione\<Persona>` i wpisuje je w `zrodla_dir` / `wyniki_dir` / `zdjecia_dir`
  (puste albo stare `przed`/`po` – te są przenoszone). Własny folder usera zostaje. `modelki[]` mają `foldery {wrzutnia, gotowe, zdjecia}` i `telegram_czat`.
- `POST /api/folder/otworz` `{"co": "wrzutnia"|"gotowe"|"zdjecia"|"pulpit"|"modelka"|"referencje"|"stroje"|"audio"}` → otwiera folder w Eksploratorze
  (Windows; `{"sciezka": "..."}`; poza Windows 400 z komunikatem i ścieżką).
- `GET /api/nsfw` → `{"odrzucone": 3, "odrzucone_ostatnio": 1, "dni": 14, "slowa": {"A": ["mesh"], "B": [], "zdjecia": []}, "wskazowki": ["..."]}`
  – czemu filtr treści Higgsfield/Seedance odrzuca rolki aktywnej persony. Pomysł ze statusem `blad` ma `powod`: `"nsfw"` (filtr treści),
  `"ip"` (znana postać/marka), `"inny"` albo `null`. Po dwóch odrzuceniach NSFW z rzędu fabryka nie próbuje dalej.
- `GET /api/statystyki` → `razem.nsfw` = odrzucone przez filtr w tym okresie.
- Telegram per persona: ustawienie `telegram_czat` (`"@huy7128"`, `""` = czat główny). Takie konto musi raz napisać `/start` do bota
  (bot paruje tylko czat główny i konta z `telegram_czat`; obce ignoruje). Gotowe rolki/zdjęcia persony lecą na jej konto;
  alarmy i raport – na czat główny. `/stop`, `/wznow` tylko z czatu głównego. Akcja `telegram_wyslij` wysyła na konto persony
  (400, gdy to konto nie napisało jeszcze `/start`). `telegram.czaty` w `/api/stan` = sparowane konta.
- Autopilot NIE robi lipsyncu (`fabryka.generuj(lipsync=False)`); `lipsync_auto` (domyślnie false) działa tylko przy ręcznym „Zrób rolkę”.
- Zdjęcia ze strojów: ustawienia `zdjecia_stroje` (bool, co drugie zdjęcie w kolejnym stroju ze `stroje/`) i `zdjecia_prompt_stroj`
  (dopisek do promptu, strój = ostatni obraz). Akcja `{"typ": "zdjecia", "stroj": "auto"|"bez"|"<plik ze stroje/>"}` (brak = automatycznie).
  Wpis w `/api/zdjecia` ma `stroj` (ścieżka albo null).
- Salda (2.5): `/api/stan.saldo` = `{"higgsfield": {"kredyty", "blad", "czas", "jednostka": "kr"}, "yapper": {...} (gdy klucz albo robi rolki
  aktywnej persony), "elevenlabs": {"kredyty": zostało znaków, "limit", "plan", "jednostka": "zn", ...} (gdy klucz)}`. Pasek u góry pokazuje
  po jednej pastylce na konto (`.saldo-pill`, aktywne konto = ramka akcentu) + „dziś wydałeś X z Y” dla konta robiącego rolki.
  `POST /api/konta/test {"dostawca": "elevenlabs"}` sprawdza klucz przez `GET /v1/user/subscription` (dostawcy/elevenlabs.py: tylko gotowy/saldo).
- Jakość i koszt (2.2, 2.6): `/api/stan.jakosc` = `{"preset": "oszczednie"|"normalnie"|"najlepiej"|"wlasne", "resolution": "720p (≤8 s → 1080p)",
  "max_sekund_rolki", "koszt_rolki": 112, "koszt_sekundy": 7.5, "koszt_sekundy_1080p": 12.0, "koszt_sekundy_720p": 7.5, "prog_1080p_s": 8.0,
  "zasada_rozdzielczosci": "≤8 s → 1080p, dłuższe → 720p", "za_drogo": false, "max_kredyty_na_rolke": 150, "presety": {"oszczednie":
  {"resolution": "720p (≤8 s → 1080p)", "max_sekund_rolki": 10, "koszt_rolki": 75}, "normalnie": {...112}, "najlepiej": {"resolution": "1080p",
  "max_sekund_rolki": 8, "koszt_rolki": 96}}}` (szacunek: sekundy × stawka rozdzielczości z zasady; prawdziwą cenę daje akcja `koszt`).
  **Rozdzielczość rolki wybiera długość (pociętego) klipu: ≤ 8 s → 1080p, dłuższy → 720p** (Higgsfield i yapper; `fabryka.PROG_1080P_S`);
  ustawienie `resolution` działa tylko dla pomysłów bez filmiku. Wybrana rozdzielczość jest w pomyśle (`resolution`) i idzie do wyceny,
  bezpiecznika i zapytania. `dzis.rolek_zostalo` = ile rolek jeszcze wejdzie dziś (limit dzienny i saldo ponad `min_kredyty`, co niższe; null bez danych).
  `POST /api/ustawienia/preset {"nazwa": "oszczednie"}` → `{"ustawienia", "jakosc"}` (ustawia `resolution` + `max_sekund_rolki`).
  Ustawienie `max_sekund_rolki` (4–30, domyślnie 15): filmik dłuższy jest cięty na kawałki tej długości (`dziel_dlugie`) – krótsza rolka = mniej kredytów.
- Skrót na pulpit i autostart bez admina: `skroty.vbs pulpit|autostart|autostart-usun` (wołane przez `skrot-na-pulpit.bat`, `autostart.bat`,
  `autostart-usun.bat`, `aktualizuj.bat`, `instaluj.bat`); skrót „Rolki AI” uruchamia `rolki.vbs` (panel w tle + przeglądarka).
  Ikona: `static/rolki.ico` / `static/rolki.png`. Statyczne pliki: `?v=<wersja>` + `SEND_FILE_MAX_AGE_DEFAULT=0` (bez cache po aktualizacji).
- `POST /api/autopilot/wznow` `{"slug"?: "noemi"}` → zdejmuje hamulec (pauzę) z aktywnej/wskazanej persony → `{"autopilot_stan": {...}}`
- Pomysł ma dodatkowo `wynik_miniatura_url` (siatka klatek GOTOWEJ rolki, albo null) i `telegram_wyslano` (bool).
- Akcja `{"typ": "telegram_wyslij", "id": 5}` wysyła gotową rolkę na telefon (wymaga sparowanego bota).
- Konta: `konta.telegram` = karta tokena bota (`jest`, `maska`, `jak`) + `sparowany`, `czat`; `POST /api/konta/test {"dostawca": "telegram"}`
  sprawdza bota i, gdy sparowany, wysyła testową wiadomość.
- Nowe ustawienia persony: `autopilot_stop_po_bledach` (int, 0 = nigdy), `telegram_wysylaj` (bool), `dziel_dlugie` (bool – filmik > 30 s tnij na kawałki).
- Autostart (Windows): `autostart.bat` kładzie skrót w folderze Autostart (bez praw administratora); `autostart-usun.bat` wyłącza. Panel nie ma API do tego – pokazuj tylko instrukcję.
- `modelki[]` w `/api/stan` mają dodatkowo `autopilot_stan` (hamulec tej persony), `rolki_dzis` (int) i `avatar_url` (pierwsze zdjęcie persony albo null).
- `GET /api/diagnoza` → `{"diagnoza": [{"co": "ffmpeg"|"higgsfield"|"mediatool"|"telegram"|"yapper"|"limit yappera"|"persona <slug>"|"foldery <slug>"|"telefon <slug>", "ok": true|false|null, "info": "..."}]}`
  (`yapper` = GET /credits, `limit yappera` = czy jest dzienny limit – bez niego zapas po NSFW nic nie wyda; obie pozycje tylko, gdy jest klucz
  yappera albo persona go używa)
  (null = opcjonalne, nie skonfigurowane). Lista kontrolna „pierwsze kroki”. `foldery <slug>` ma też `wrzutnia`, `gotowe` (ścieżki);
  `telefon <slug>` tylko gdy persona ma `telegram_czat` (ok = to konto napisało /start).
- `GET /api/statystyki?dni=14` → `{"dni": [{"dzien": "2026-10-03", "rolki": 2, "zdjecia": 1, "bledy": 0, "kredyty": {"higgsfield": 90, "yapper": 0, "sync": 0}}, ...], "razem": {...}}` (od najstarszego do dziś).
- Akcja `{"typ": "podglad", "id": 5}` = tani podgląd rolki (Seedance draft, ~21 kr): pomysł zostaje „nowy”, dostaje `podglad_url` (wideo) i `podglad_miniatura_url` (siatka klatek) oraz `podglad_koszt`. Tylko dostawca Higgsfield.
- `POST /api/zamknij` zamyka panel (używa go `aktualizuj.bat`) → `{"zamykam": true, "czekam": false|true, "komunikat"?}`. Gdy coś się robi:
  autopilot i STOP od razu, a proces kończy się dopiero po bezpiecznym punkcie – nigdy w trakcie wysyłania rolki (upload + create);
  rolka już wysłana dokończy się po ponownym uruchomieniu (ten sam job). `aktualizuj.bat` czeka, aż panel przestanie odpowiadać.
- Generacja w toku (2.6): rolka wysłana do dostawcy ma status `w_toku` i `w_toku` = `{dostawca, model, krok, klucz, koszt, od, etap:
  "wysylanie"|"czeka", job_id, wideo_id?, wysylam?}`; fabryka odpytuje TEN job (po restarcie też – start panelu odpala zadanie `wznow`),
  nigdy nie wysyła drugiego. Pomysł ma `proby` = `[{dostawca, model, krok, job_id, status, powod, kr, czas, info?}]`, po zapasie `zapas: true`
  + `model`; dla panelu `w_toku_opis` ("higgsfield seedance_2_5, job …") i `zapas_opis` ("zrobione na wan-3.0-prime (zapas)").
  `/api/stan.stan` ma `w_toku` (lista id) i `zapas_nsfw` (opis kroków). Ponów/usuń/PATCH status rolki `w_toku` → 409 (komunikat
  w `blad`). `POST /api/pomysly/<id>/przerwij {"potwierdzam": true}` = „Przestań czekać” na rolkę w toku (np. bez numeru joba): status
  `blad` + notatka „sprawdź w apce”; bez potwierdzenia 400, w trakcie samego wysyłania 409. Zdjęcie może mieć status `niepewne`
  (błąd po wysłaniu – job mógł powstać; liczy się jak zrobione, koszt zarezerwowany).
- Profil persony ma pole `hashtagi` (tekst doklejany do każdego podpisu) – zapis przez `POST /api/profil`.

## Modelki (persony)
- `POST /api/modelki` `{"nazwa": "Noemi", "instagram": "@uroczanoemi"}` → `{"slug": "noemi"}` (ustawia jako aktywną)
- `POST /api/modelki/aktywna` `{"slug": "noemi"}`
- `POST /api/profil` `{"instagram": "", "opis_stylu": "", "nazwa": "", "cechy": "a, b"}` → `{"profil": {...}}`

## Kolejka pomysłów (rolki)
- `GET /api/pomysly` → `{"pomysly": [...], "statusy": ["nowy","w_toku","wygenerowany","postprodukcja","gotowe","blad"]}`
  Każdy pomysł: `id, opis, prompt_higgsfield, status, zrodlo, stroj, klatki, info_zrodla{czas,szer,wys,fps}, plik_wynikowy,
  wynik_url, job_id, koszt, dostawca, model?, resolution?, w_toku?, proby?, zapas?, krok_startowy?, audio, lipsync_plik, podpis, notatki,
  utworzono, zaktualizowano, wygenerowano`
  + pola dla panelu: `miniatura_url` (arkusz klatek albo null), `wideo_url` (gotowy plik albo null),
  `zrodlo_url`, `lipsync_url`, `stroj_url`, `audio_nazwa`, `wariant` ("A" / "B" / "tekst").
- `POST /api/pomysly` `{"opis": "...", "prompt": "..."}` → `{"id": 9}` (pomysł tekstowy, bez filmiku; generuje się trybem `mode_bez_zrodla`)
- `PATCH /api/pomysly/<id>` `{"status"?, "opis"?, "prompt_higgsfield"?, "notatki"?}` → `{"pomysl": {...}}`
- `POST /api/pomysly/<id>/ponow` → status `blad` → `nowy` → `{"pomysl", "od_zapasu": bool}`. Rolka odrzucona przez filtr (`powod` nsfw/ip)
  przy włączonym `zapas_nsfw` dostaje `krok_startowy: 1` – następne „Zrób” idzie od razu na pierwszy krok zapasu (Seedance odrzuciłby
  te same wejścia); akcja `koszt` wycenia ją wtedy u dostawcy zapasu (`pozycje: [[id, koszt, "yapper"]]`). Rolka `w_toku` → 409.
- `DELETE /api/pomysly/<id>` (`?plik=1` kasuje też pliki wynikowe)

## Akcje (zadania w tle – jedno naraz)
`POST /api/akcja` → `{"zadanie": {...}}` albo 409, gdy coś już trwa (również przebieg autopilota).
```json
{"typ": "skanuj"}
{"typ": "koszt", "ids": [5, 6]}            // ids opcjonalne = wszystkie 'nowe' z promptem; wynik.pozycje = [[id, koszt|null, dostawca]]
{"typ": "generuj", "ids": [5], "limit": 3, "dry_run": false}
{"typ": "pierz", "id": 5}                    // Media Tool na wyniku pomysłu
{"typ": "lipsync", "id": 5, "audio": "C:\\...\\glos.mp3", "styl": "telefon"}   // albo {"wideo": "...", "audio": "..."}; styl: telefon|czysty|brak (brak pola = ustawienie lipsync_glos_styl)
{"typ": "zdjecia", "ile": 2, "prompt": "opcjonalny prompt", "stroj": "auto"}   // stroj: brak = automatycznie, "bez", "auto", "plik.png"
{"typ": "podpis", "id": 5}
{"typ": "tts", "tekst": "Cześć!", "voice_id": "EXAVITQu4vr4xnSDxMaL", "nazwa": "intro"}   // sync.so -> audio/<nazwa>.mp3
{"typ": "autopilot_raz"}                     // jeden przebieg autopilota dla aktywnej modelki
```
Panel sam odpala przy starcie zadanie `wznow` (dokończenie rolek `w_toku`, bez wysyłania drugi raz). Wynik `generuj`:
`{"wygenerowane", "bledy": [id], "odrzucone": [id] (NSFW/IP – podzbiór błędów, hamulec autopilota ich nie liczy), "pominiete", "w_toku", "stop"}`.
- `GET /api/zadanie?od=0` → `{"trwa", "typ", "modelka", "start", "koniec", "wynik", "blad", "log": ["..."], "log_dlugosc": 42}`
  (`od` = indeks pierwszej linii logu, którą chcemy – panel dociąga tylko nowe)
- `POST /api/zadanie/stop` → zatrzymuje między pozycjami albo w trakcie czekania na job (job zostaje `w_toku` i dokończy się później;
  nie przerywa wysyłania ani generacji u dostawcy)

## Ustawienia aktywnej modelki
- `GET /api/ustawienia` →
```json
{"ustawienia": {...}, "domyslne": {...}, "profil": {"nazwa": "Noemi", "instagram": "", "opis_stylu": "", "cechy": [], "hashtagi": ""},
 "prompty": {"a": "tekst wariantu A", "b": "tekst wariantu B", "zdjecia": "linia\nlinia"},
 "referencje": [{"nazwa": "01_twarz.png", "url": "/api/plik?s=..."}],
 "stroje": [{"nazwa": "mesh.png", "url": "..."}],
 "audio": [{"nazwa": "glos.mp3", "sciezka": "C:\\..."}],
 "foldery": {"modelka": "...", "wrzutnia": "...", "gotowe": "...", "zdjecia": "...", "audio": "..."}}
```
- `POST /api/ustawienia` `{"resolution": "1080p", "autopilot": true, "yapper": {"model": "wan-3.0"}, "prompt_a_tekst": "...", "prompt_b_tekst": "...", "zdjecia_prompty_tekst": "..."}`
  → `{"ustawienia": {...}}`. Słowniki (`yapper`, `zdjecia_parametry`, `lipsync_parametry`, `dodatkowe_parametry`) są scalane.
  Klucze ustawień i znaczenie: patrz `baza.USTAWIENIA_DOMYSLNE` (komentarze). Najważniejsze dla GUI:
  `dostawca` (higgsfield|yapper), `model`, `mode`, `mode_bez_zrodla`, `aspect_ratio`, `resolution`, `duration`,
  `yapper.model`, `yapper.resolution`, `yapper.duration`, `prompt_auto`, `stroj_domyslny`, `min_kredyty`,
  `max_kredyty_na_rolke`, `powtorki` (ponowne WYSŁANIE tylko, gdy job nie powstał), `zapas_nsfw` (lista kroków
  `[{"dostawca": "yapper", "model": "wan-3.0-prime"}, ...]` albo tekst JSON; `[]` = wyłączone), `zrodla_dir`, `wyniki_dir`, `mediatool`, `autopilot`, `autopilot_co_minut`,
  `autopilot_max_rolek_dziennie`, `telegram_wysylaj`, `telegram_czat`, `zdjecia_model`, `zdjecia_dziennie`, `zdjecia_parametry`, `zdjecia_dir`,
  `zdjecia_stroje`, `zdjecia_prompt_stroj`, `lipsync_dostawca` (sync|higgsfield), `lipsync_model`, `lipsync_auto` (tylko ręczne „Zrób rolkę”),
  `lipsync_parametry.sync_mode`, `tts_model`, `tts_glos`, `tts_glos_typ`.
- `POST /api/upload` multipart: pole `typ` ∈ `referencja | stroj | audio | zrodlo`, pliki w polu `pliki` (wiele) → `{"zapisane": ["01_x.png"]}`
  (referencje dostają numer 01_, 02_... na początku nazwy, jeśli go nie mają)
- `POST /api/pliki/usun` `{"typ": "referencja"|"stroj"|"audio", "nazwa": "01_x.png"}`

## Konta i klucze
- `GET /api/konta` →
```json
{"konta": {
  "higgsfield": {"nazwa": "Higgsfield", "typ": "oauth", "ok": true, "komunikat": "zalogowany", "jak": "Logowanie: zaloguj-higgsfield.bat (Firefox) albo `higgsfield auth login`"},
  "yapper": {"nazwa": "yapper.so", "typ": "klucz", "opis": "...", "jest": false, "maska": "", "z_env": false, "ok": null, "komunikat": "", "jak": "yapper.so -> Account -> API -> Create key (Read + Write)"},
  "sync": {"nazwa": "sync.so", "typ": "klucz", "jest": true, "maska": "sk_1…abcd", "z_env": false, "ok": null, "komunikat": "", "jak": "https://sync.so/settings/api-keys"},
  "elevenlabs": {...}}}
```
- `POST /api/konta` `{"dostawca": "yapper", "klucz": "..."}` (pusty klucz = usuń) → `{"konta": {...}}`
- `POST /api/konta/test` `{"dostawca": "yapper"}` → `{"dziala": true, "komunikat": "1234 kr dostepnych"}`

## Modele i głosy (listy do selectów; cache 10 min, `?odswiez=1`)
- `GET /api/modele?dostawca=higgsfield&typ=image|video|audio` → `{"modele": [{"id": "nano_banana_2", "nazwa": "Nano Banana 2", "typ": "image", "opis": ""}]}`
- `GET /api/modele?dostawca=yapper` → jak wyżej (modele wideo yapper, np. `wan-3.0`, `wan-3.0-prime`)
- `GET /api/modele?dostawca=sync` → modele lipsync (`lipsync-2`, `lipsync-2-pro`, `sync-3`...)
- `GET /api/glosy?dostawca=sync|higgsfield` → `{"glosy": [{"id": "...", "nazwa": "Rachel", "typ": "preset", "opis": "female"}]}`
  Gdy dostawca nie jest zalogowany/brak klucza: `{"ok": false, "blad": "..."}` (400) – GUI pokazuje komunikat, nie wywala się.

## Zdjęcia, lipsync, dziennik, budżet, autopilot
- `GET /api/zdjecia` → `{"zdjecia": [{"id", "prompt", "plik", "url", "status", "koszt", "utworzono", "notatki", "stroj"}]}`
- `DELETE /api/zdjecia/<id>` (`?plik=1` kasuje też plik)
- `GET /api/lipsync` → `{"lipsync": [{"id", "wideo", "audio", "dostawca", "model", "pomysl_id", "status", "plik_wynikowy", "url", "koszt", "notatki", "utworzono", "styl"?, "audio_przygotowane"?}]}`
- Brzmienie głosu (2.2): przed wysłaniem do sync.so głos jest przerabiany ffmpegiem wg ustawienia `lipsync_glos_styl`
  (`telefon` = jak nagranie z telefonu w pokoju: pasmo mikrofonu, lekki pogłos, szum tła, wyrównana głośność – domyślnie;
  `czysty` = tylko głośność; `brak` = plik bez zmian). Głosówki z Telegrama (.ogg) też przechodzą. Wynik w `modelki/<slug>/audio/_przygotowane/`.
  GUI: select „Brzmienie głosu” w dialogu Lipsync (pole `styl` akcji) + ustawienie w sekcji Lipsync (tryb pełny).
  Wynik lipsyncu idzie jak rolka: surowy plik z API do `modelki/<slug>/wyniki/<nazwa>_lipsync.raw.mp4`, potem Media Tool (gdy `mediatool`)
  → `wyniki_dir/<nazwa>_lipsync.mp4`. Autopilot wysyła wersję z dopasowanymi ustami na Telegram raz (`telegram_wyslano_lipsync`).
- `DELETE /api/lipsync/<id>`
- `GET /api/dziennik?ile=100&typ=blad` → `{"wpisy": [{"czas", "typ", "modelka", "tekst", "dane"}]}` (najnowszy na końcu)
- `GET /api/budzet` → `{"budzet": {...plik budzet.json...}, "dzis": {"higgsfield": {"wydano": 90, "limit": 300, "jednostka": "kr"}, "yapper": {"wydano": 0, "limit": 0, "jednostka": "kr"}, "sync": {"wydano": 50, "limit": 0, "jednostka": "c"}}}`
- `POST /api/budzet` `{"dostawca": "higgsfield", "max_kredyty_dziennie": 300}`
- `POST /api/autopilot` `{"wlacz": true}` → `{"autopilot": {...jak w /api/stan...}}` (pętla w tle; `wlacz: false` zatrzymuje)

## Teksty i szablony (bez zmian)
- `GET /api/teksty`, `POST /api/teksty` `{"teksty": "linia\nlinia", "zrodlo": ""}` → `{"dodano": n}`, `POST /api/teksty/losuj` → `{"tekst", "nieuzyte", "wszystkie"}`
- `GET /api/szablony`, `POST /api/szablony` `{"nazwa", "tresc"}`, `DELETE /api/szablony/<nazwa>`, `POST /api/szablony/wypelnij` `{"tresc", "wartosci": {}}` → `{"prompt"}`
