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
 "telegram": {"skonfigurowany": true, "sparowany": false, "czat": ""},         // bot Telegram: token jest? czat sparowany (/start)?
 "dzis": {"rolki": 3, "zdjecia": 1, "bledy": 0, "kredyty": {"higgsfield": 135, "yapper": 0, "sync": 0}, "rolki_persony": 2},
 "wersja": "2.0"}
```
- `POST /api/autopilot/wznow` `{"slug"?: "noemi"}` → zdejmuje hamulec (pauzę) z aktywnej/wskazanej persony → `{"autopilot_stan": {...}}`
- Pomysł ma dodatkowo `wynik_miniatura_url` (siatka klatek GOTOWEJ rolki, albo null) i `telegram_wyslano` (bool).
- Akcja `{"typ": "telegram_wyslij", "id": 5}` wysyła gotową rolkę na telefon (wymaga sparowanego bota).
- Konta: `konta.telegram` = karta tokena bota (`jest`, `maska`, `jak`) + `sparowany`, `czat`; `POST /api/konta/test {"dostawca": "telegram"}`
  sprawdza bota i, gdy sparowany, wysyła testową wiadomość.
- Nowe ustawienia persony: `autopilot_stop_po_bledach` (int, 0 = nigdy), `telegram_wysylaj` (bool), `dziel_dlugie` (bool – filmik > 30 s tnij na kawałki).
- Autostart (Windows): plik `autostart.bat` rejestruje start panelu z autopilotem przy logowaniu; `autostart-usun.bat` wyłącza. Panel nie ma API do tego – pokazuj tylko instrukcję.

## Modelki (persony)
- `POST /api/modelki` `{"nazwa": "Noemi", "instagram": "@uroczanoemi"}` → `{"slug": "noemi"}` (ustawia jako aktywną)
- `POST /api/modelki/aktywna` `{"slug": "noemi"}`
- `POST /api/profil` `{"instagram": "", "opis_stylu": "", "nazwa": "", "cechy": "a, b"}` → `{"profil": {...}}`

## Kolejka pomysłów (rolki)
- `GET /api/pomysly` → `{"pomysly": [...], "statusy": ["nowy","wygenerowany","postprodukcja","gotowe","blad"]}`
  Każdy pomysł: `id, opis, prompt_higgsfield, status, zrodlo, stroj, klatki, info_zrodla{czas,szer,wys,fps}, plik_wynikowy,
  wynik_url, job_id, koszt, dostawca, audio, lipsync_plik, podpis, notatki, utworzono, zaktualizowano, wygenerowano`
  + pola dla panelu: `miniatura_url` (arkusz klatek albo null), `wideo_url` (gotowy plik albo null),
  `zrodlo_url`, `lipsync_url`, `stroj_url`, `audio_nazwa`, `wariant` ("A" / "B" / "tekst").
- `POST /api/pomysly` `{"opis": "...", "prompt": "..."}` → `{"id": 9}` (pomysł tekstowy, bez filmiku; generuje się trybem `mode_bez_zrodla`)
- `PATCH /api/pomysly/<id>` `{"status"?, "opis"?, "prompt_higgsfield"?, "notatki"?}` → `{"pomysl": {...}}`
- `POST /api/pomysly/<id>/ponow` → status `blad` → `nowy`
- `DELETE /api/pomysly/<id>` (`?plik=1` kasuje też pliki wynikowe)

## Akcje (zadania w tle – jedno naraz)
`POST /api/akcja` → `{"zadanie": {...}}` albo 409, gdy coś już trwa (również przebieg autopilota).
```json
{"typ": "skanuj"}
{"typ": "koszt", "ids": [5, 6]}            // ids opcjonalne = wszystkie 'nowe' z promptem
{"typ": "generuj", "ids": [5], "limit": 3, "dry_run": false}
{"typ": "pierz", "id": 5}                    // Media Tool na wyniku pomysłu
{"typ": "lipsync", "id": 5, "audio": "C:\\...\\glos.mp3"}       // albo {"wideo": "...", "audio": "..."}
{"typ": "zdjecia", "ile": 2, "prompt": "opcjonalny prompt"}
{"typ": "podpis", "id": 5}
{"typ": "tts", "tekst": "Cześć!", "voice_id": "EXAVITQu4vr4xnSDxMaL", "nazwa": "intro"}   // sync.so -> audio/<nazwa>.mp3
{"typ": "autopilot_raz"}                     // jeden przebieg autopilota dla aktywnej modelki
```
- `GET /api/zadanie?od=0` → `{"trwa", "typ", "modelka", "start", "koniec", "wynik", "blad", "log": ["..."], "log_dlugosc": 42}`
  (`od` = indeks pierwszej linii logu, którą chcemy – panel dociąga tylko nowe)
- `POST /api/zadanie/stop` → zatrzymuje między pozycjami (nie przerywa trwającej generacji u dostawcy)

## Ustawienia aktywnej modelki
- `GET /api/ustawienia` →
```json
{"ustawienia": {...}, "domyslne": {...},
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
  `max_kredyty_na_rolke`, `powtorki`, `zrodla_dir`, `wyniki_dir`, `mediatool`, `autopilot`, `autopilot_co_minut`,
  `autopilot_max_rolek_dziennie`, `zdjecia_model`, `zdjecia_dziennie`, `zdjecia_parametry`, `zdjecia_dir`,
  `lipsync_dostawca` (sync|higgsfield), `lipsync_model`, `lipsync_auto`, `lipsync_parametry.sync_mode`,
  `tts_model`, `tts_glos`, `tts_glos_typ`.
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
- `GET /api/zdjecia` → `{"zdjecia": [{"id", "prompt", "plik", "url", "status", "koszt", "utworzono", "notatki"}]}`
- `DELETE /api/zdjecia/<id>` (`?plik=1` kasuje też plik)
- `GET /api/lipsync` → `{"lipsync": [{"id", "wideo", "audio", "dostawca", "model", "pomysl_id", "status", "plik_wynikowy", "url", "koszt", "notatki", "utworzono"}]}`
- `DELETE /api/lipsync/<id>`
- `GET /api/dziennik?ile=100&typ=blad` → `{"wpisy": [{"czas", "typ", "modelka", "tekst", "dane"}]}` (najnowszy na końcu)
- `GET /api/budzet` → `{"budzet": {...plik budzet.json...}, "dzis": {"higgsfield": {"wydano": 90, "limit": 300, "jednostka": "kr"}, "yapper": {"wydano": 0, "limit": 0, "jednostka": "kr"}, "sync": {"wydano": 50, "limit": 0, "jednostka": "c"}}}`
- `POST /api/budzet` `{"dostawca": "higgsfield", "max_kredyty_dziennie": 300}`
- `POST /api/autopilot` `{"wlacz": true}` → `{"autopilot": {...jak w /api/stan...}}` (pętla w tle; `wlacz: false` zatrzymuje)

## Teksty i szablony (bez zmian)
- `GET /api/teksty`, `POST /api/teksty` `{"teksty": "linia\nlinia", "zrodlo": ""}` → `{"dodano": n}`, `POST /api/teksty/losuj` → `{"tekst", "nieuzyte", "wszystkie"}`
- `GET /api/szablony`, `POST /api/szablony` `{"nazwa", "tresc"}`, `DELETE /api/szablony/<nazwa>`, `POST /api/szablony/wypelnij` `{"tresc", "wartosci": {}}` → `{"prompt"}`
