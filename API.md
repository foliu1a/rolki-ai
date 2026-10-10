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
 "wersja": "3.3",
 "zdjecia_kolejka": {"w_toku": 2, "w_kolejce": 1, "limit": 4, "dziala": true, "zatrzymane": false,
                     "persona": {"w_toku": 2, "w_kolejce": 1}},           // 3.3: zdjęcia (wszystkie persony + aktywna)
 "autopilot_z_promptu": {"dziennie": 1, "dzis": 0, "nieudane": 0, "model": "seedance_2_5", "od_godziny": "10:00", "persony": ["noemi"],
                         "stan": "przed_godzina", "tekst": "Rolki z promptu: dziś 0 z 1 (następna po 10:00)",
                         // 3.5.1: wybór modelu na Starcie (kr = wideo + 3 za pierwszą klatkę, gdy włączona)
                         "modele": [{"id": "seedance_2_5", "nazwa": "Seedance 2.5", "opis": "…", "kr": 73},
                                    {"id": "wan3_0_prime", "nazwa": "Wan 3.0 Premium", "opis": "…", "kr": 33}],
                         "kr_rolki": 73, "limit_dzienny": 300},
 "rolki_ig": {"wlaczone": false, "dziennie": 3, "dzis": 0, "profile": [], "persony": ["noemi"], "do_person": "round-robin",
              "ma_klucz": false, "stan": "wylaczone", "tekst": "Rolki z Instagrama: wyłączone (…)"}}   // 3.4: źródło klipów z IG
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
- Telegram per persona: ustawienie `telegram_czat` (`"@huy7128"`, `""` = brak). Takie konto musi raz napisać `/start` do bota
  (bot paruje tylko czat główny, konta z `telegram_czat` i konta dodatkowe; obce ignoruje bez odpowiedzi). 3.6.1: gotowe rolki/zdjęcia
  persony lecą na czat główny + konta dodatkowe + jej konto (każde raz); alarmy i raport – czat główny + dodatkowe. `/stop`, `/wznow`
  tylko z czatu głównego (`/zdjecie` – główny albo konto persony). Akcja `telegram_wyslij` wysyła na wszystkie te konta (400 tylko,
  gdy żadne nie jest sparowane). `telegram.czaty` w `/api/stan` = sparowane konta.
- Telefon 3.6.1 (niezależnie od autopilota – wątek panelu co 20 s: odbiór, gotowe rolki/zdjęcia, raport dnia):
  `GET /api/telegram` → `{"telegram": {"skonfigurowany", "bot": {"username", "link": "https://t.me/<bot>", "imie"} | null, "bot_blad",
  "glowny": {"nazwa", "polaczone"} | null, "dodatkowe": [{"konto", "polaczone", "glowny"}], "persony": [{"slug", "persona", "konto",
  "polaczone"}], "odbior": {"dziala", "ostatni", "blad", "autopilot"}}}`; `POST /api/telegram {"dodatkowe": ["@a", "b"] | "@a
@b"}`
  (ustawienie globalne `telegram_dodatkowe`, zły wpis → 400; to samo przez `POST /api/ustawienia/globalne {"telegram_dodatkowe": [...]}`);
  `POST /api/telegram/test` → `{"wyniki": [{"nazwa", "rola": glowny|dodatkowe|persona, "ok", "blad"}], "wyslane": n}` (wiadomość
  testowa na każde połączone konto osobno; 400 gdy żadne); `POST /api/telegram/rozparuj {"potwierdzam": true}` – odłącza czat główny
  (następny `/start` spoza list zostaje głównym). Pomysł/zdjęcie: `telegram_do` (lista chat_id, które dostały), `telegram_do_lipsync`,
  `telegram_bledy` ({chat_id: n} – po 3 nieudanych próbach to konto jest pomijane).
- Autopilot NIE robi lipsyncu (`fabryka.generuj(lipsync=False)`); `lipsync_auto` (domyślnie false) działa tylko przy ręcznym „Zrób rolkę”.
- Zdjęcia ze strojów: ustawienia `zdjecia_stroje` (bool, co drugie zdjęcie w kolejnym stroju ze `stroje/`) i `zdjecia_prompt_stroj`
  (dopisek do promptu, strój = ostatni obraz). Akcja `{"typ": "zdjecia", "stroj": "auto"|"bez"|"<plik ze stroje/>"}` (brak = automatycznie).
  Wpis w `/api/zdjecia` ma `stroj` (ścieżka albo null).
- WaveSpeed (2.8): trzeci dostawca rolek (`dostawca: "wavespeed"`, dostawcy/wavespeed.py, REST WaveSpeedAI). Wszystkie jego kwoty są
  w **centach USD** (`"jednostka": "c"` – panel pokazuje dolary): `saldo.wavespeed {"kredyty": 1234 = $12,34, "jednostka": "c"}` (gdy klucz
  albo robi rolki aktywnej persony), `stan.budzet.jednostka` (`"kr"` | `"c"`), `dzis.kredyty.wavespeed`, `statystyki ... kredyty.wavespeed`,
  `jakosc` persony na WaveSpeed: `"dostawca": "wavespeed", "jednostka": "c"` i stawki/koszty w centach (Turbo: 720p 24 c/s, 1080p 26 c/s
  sekundy klipu). Bez dziennego limitu WaveSpeed (`/api/budzet` dostawca `wavespeed`) generacja kończy się od razu z
  `stop: "brak limitu dziennego wavespeed"` i wpisem w dzienniku – zero zapytań do WaveSpeed. `dzis.rolek_zostalo` dla takiej persony = 0.
- Salda (2.5): `/api/stan.saldo` = `{"higgsfield": {"kredyty", "blad", "czas", "jednostka": "kr"}, "yapper": {...} (gdy klucz albo robi rolki
  aktywnej persony), "wavespeed": {... "jednostka": "c"} (2.8), "elevenlabs": {"kredyty": zostało znaków, "limit", "plan", "jednostka": "zn", ...} (gdy klucz)}`. Pasek u góry pokazuje
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
- `GET /api/diagnoza` → `{"diagnoza": [{"co": "ffmpeg"|"higgsfield"|"mediatool"|"telegram"|"yapper"|"limit yappera"|"wavespeed"|"limit wavespeed"|"persona <slug>"|"foldery <slug>"|"telefon <slug>", "ok": true|false|null, "info": "..."}]}`
  (`yapper` = GET /credits, `limit yappera` = czy jest dzienny limit – bez niego zapas po NSFW nic nie wyda; obie pozycje tylko, gdy jest klucz
  yappera albo persona go używa (dostawca albo krok zapasu); `wavespeed` = GET /balance ("klucz dziala, saldo $12.34"), `limit wavespeed`
  = "dzis $2.60/$10.00" albo "nie ustawiony" – tylko, gdy jest klucz WaveSpeed albo persona go używa)
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

## Rolka z promptu (2.9, zakładka „Z promptu”, scenariusz.py)
Rolka bez filmiku: pomysł po polsku → prompt Seedance 2.5 (`omni_reference`, `<<<image_N>>>`) + zdjęcia persony → zawsze Higgsfield.
Opcje (wszystkie opcjonalne, te same w każdym endpointcie): `slug` (persona, domyślnie aktywna; nieznana = 404), `pomysl_id`
(gotowy pomysł), `tekst` (pomysł PL), `miejsce` (`""` = dobierz, `"losowe"`, id z katalogu), `model` (`seedance_2_5` |
`wan3_0_prime` | `gemini_omni_flash_1_1`), `dlugosc` (8/10/15; Gemini max 10), `rozdzielczosc` (`"auto"` = ≤ 8 s → 1080p, dłuższe →
720p, albo `480p|720p|1080p`), `wlosy` `{"kolor", "fryzura", "grzywka"}` (domyślnie `wlasne`/`wlasna`), `stroj` (`zdjecia` |
`codzienny` | `cosplay` | `wlasny` + `stroj_tekst` | `plik:<nazwa ze stroje/>`), `reakcja`, `komentarz` (`losowy` | `bez` |
`wlasny` + `komentarz_tekst` | tekst z listy), `sezon` / `pora` / `kamera` (`auto` albo klucz), `ustalone` (z poprzedniej
odpowiedzi – te same losowe szczegóły = ten sam prompt).
- `GET /api/z-promptu?slug=` → katalog: `modele [{id, nazwa, opis, dlugosci, rozdzielczosci, max_obrazow}]`, `pomysly [{id, pl,
  miejsce}]`, `miejsca [{id, nazwa, kat}]`, `kategorie`, `wlosy {kolory, fryzury, grzywki}` (pary `[id, etykieta]`), `stroje`,
  `reakcje`, `komentarze`, `kamery`, `sezony`, `sezon_teraz`, `pory`, `persona {slug, imie, wzrost_cm, wlosy, zdjec, stroje}`,
  `domyslne` (ustawienie persony `z_promptu`).
- `POST /api/z-promptu/losuj {slug?, bez?, sezon?}` → `{"pomysl": {id, pl, miejsce}}` (bez powtórek z 14 dni, plaża tylko latem).
- `POST /api/z-promptu/wycena {...opcje, bez_ceny?}` → `{slug, prompt, znaki, limit, obrazy: ["01_x.png"], model, dlugosc,
  rozdzielczosc, tytul, miejsce, miejsce_nazwa, pomysl_id, ustalone, ostrzezenia, kr, saldo, dzis {wydano, limit}, min_kredyty,
  max_kredyty_na_rolke, mozna, powody, dostawca: "higgsfield"}` – **darmowe** (`generate cost`), nic nie tworzy; `bez_ceny` = sam
  prompt (od razu, `kr: null`). Złe opcje (np. Gemini 15 s, zły plik stroju, persona bez zdjęć) = 400.
- `POST /api/z-promptu {...opcje, ustalone, kr, prompt?}` → `{"id": 7, "zadanie": {...}}`: pomysł `typ: "prompt"` z zamrożonym
  promptem + zadanie `generuj` tylko dla niego. `kr` (cena z wyceny) wymagane (400 bez niego); fabryka liczy cenę jeszcze raz tuż
  przed wysłaniem i pomija rolkę, gdy wyszłaby wyższa. `prompt` = ręczna poprawka (tryb pełny; sprawdzane numery zdjęć i limit).
  409, gdy coś już trwa (nic nie tworzy).
- Pomysł z promptu w `/api/pomysly`: `typ: "prompt"`, `wariant: "prompt"`, `z_promptu {model, mode, dlugosc, rozdzielczosc,
  obrazy, miejsce, miejsce_nazwa, wlosy_zmienione, wycena, ustalone, opcje, ...}`, `z_promptu_opis` („Galeria handlowa – … ·
  Seedance 2.5 · 10 s · 720p”). Nie wchodzi do zbiorczego „Zrób rolki” (`stan.do_generacji`); czekające: `stan.z_promptu_czeka`.
  „Zrób tę rolkę” w Rolkach działa (`koszt` + `generuj` po id). Bez zapasu po NSFW (`ponow` → `od_zapasu: false`).
- Akcja `{"typ": "generuj", "ids": [...], "max_kr": 70}` – `max_kr` (opcjonalnie): rolka nie pójdzie, gdy świeża cena głównego
  dostawcy wyjdzie wyższa (panel wysyła cenę z pytania „Robić?”).
- Profil persony: `POST /api/profil {"wzrost_cm": "158-160", "wlosy": "long straight platinum blonde hair"}` (zły wzrost = 400).

### Rolka z promptu 3.0 – asystent, głos, nowe opcje
- Nowe opcje (wszystkie endpointy z-promptu): `stroj: "odwazny" | "odwazny:<id>"` (katalog `stroje_odwazne [[id, etykieta,
  pory]]`), `kamera` (domyślnie z ukrycia wg miejsca, `kamery_ukryte`), `nazwy: "prawdziwe" | "opisowe"`, `obiekt` (id z
  `obiekty[miejsce]`: galerie, dworce, stacje metra, dzielnice, miasta), `glos: "auto" | "tts" | "model"` (auto = tts, gdy klucz
  ElevenLabs działa), `wymowa: "fonetyczna" | "zwykla"`, `asystent {dlaczego, zrodlo, podsumowanie}` (zapisywane w rolce).
  Reakcje zdziwienia: `reakcje_zdziwienie`, `linie_reakcji {reakcja: [polskie linie]}`. Katalog ma też `glosy`, `wymowy`, `nazwy`,
  `glos_tts {ok, komunikat}`, `asystent_llm` (jest klucz OpenRouter). (3.1: `glos_id` / `z_promptu_glos` już nieużywane.)
- Wycena zwraca dodatkowo `glos` (rozstrzygnięty), `wymowa`, `komentarz_t` (sekunda komentarza), `obiekt`, `obiekt_nazwa`, `nazwy`,
  `stroj_id`, `reakcja`; `ustalone.glos` zamraża głos (ten sam prompt przy „Zrób rolkę”).
- `POST /api/z-promptu/asystent {slug?, tekst, pomysl_id?, zablokowane: {pole: wartość ustawiona ręcznie}, bez_llm?}` →
  `{opcje, podsumowanie, dlaczego, zrodlo: "openrouter:<model>" | "reguly", uwaga, nauka, glos_tts}` – **0 kr**, nic nie wycenia.
- `POST /api/pomysly/<id>/ocena {"ocena": "dobra" | "slaba" | null}` – ocena rolki z promptu (nauka asystenta); `DELETE` rolki z
  promptu dopisuje ją do `modelki/<slug>/asystent_archiwum.json` (gotowa bez oceny = słaba).
- Akcja `{"typ": "dograj_glos", "id": 7}` – komentarz ElevenLabs do gotowej rolki z głosem `tts` (tylko znaki ElevenLabs).
  Karta rolki: `z_promptu_dlaczego`, `mozna_dograc_glos`, `ocena`, `glos_dograny`, `glos_blad`.
- **3.6 uwagi do ocen**: `POST /api/pomysly/<id>/ocena {"ocena": "dobra" | "slaba" | null, "komentarz": "za wysoka, głos jak
  lektor"}` → `{pomysl, pamiec}`; karta: `ocena_komentarz`, `ocena_poprawki` (klucze), `ocena_poprawki_nazwy` (PL). Uwaga →
  `asystent_uwagi.json` (obok stan.json). `GET /api/asystent/pamiec?slug=` → `{poprawki: [{klucz, nazwa, zakres: persona|wszystkie,
  efekt, dotyczy, persony, z_uwag}], uwagi: [{id, persona, persona_nazwa, pid, ocena, tekst, data, poprawki, miejsce, model}]}`.
  `POST /api/asystent/pamiec/usun {"poprawka": "wzrost"}` (znika ze wszystkich uwag) albo `{"uwaga": "<id>"}` (cała uwaga) →
  pamięć; nieznane = 400. Opcje z-promptu: `komentarze_ton: "ostre" | "lagodne"`, `poprawki: [klucze]` (zwykle z `ustalone.poprawki`);
  wycena/zbuduj oddaje `komentarze_ton`, `poprawki`. Katalog: `komentarze_ostre`, `komentarze_plec_ostre`, `komentarze_tony`,
  `persona.komentarze_ton`. Ustawienia persony: `komentarze_ton` (ostre domyślnie | lagodne – inne = 400), `glosy_rotuj` (bool).
- **3.5 pierwsza klatka** (rolka z promptu: najpierw zdjęcie, potem wideo od niego). Nowe opcje wszystkich endpointów z-promptu:
  `klatka: "wl" | "wyl"` (brak = `pierwsza_klatka.wlaczona` z ustawień wspólnych), `klatka_model` (`gpt_image_2_5` | `nano_banana_pro`
  | `gpt_image_2` | `seedream_v5_pro`), `tlo: "auto" | "bez" | "<plik z Pulpit/ROLKI AI/tla/<miejsce>>"` (`ustalone.tlo` zamraża
  wybór). `GET /api/z-promptu` → dodatkowo `klatka: {modele: [[id, nazwa, opis]], domyslne: {wlaczona, model, kontrola,
  max_dodatkowych}, tla: {folder, miejsca: {id_miejsca: liczba_zdjęć}}, kontrola_ai: bool}`. Wycena → `kr` = wideo + klatka (w górę,
  np. 70 + 3 = 73), `kr_wideo`, `kr_klatka` (ułamek, np. 2.75), `kr_max` (z dodatkowymi klatkami, gdy działa kontrola AI), `klatka:
  {model, nazwa_modelu, prompt, znaki, obrazy, tlo, folder_tel, kontrola, kontrola_ustawiona, max_dodatkowych}` albo `null`.
  `POST /api/z-promptu` wymaga `kr` = ta suma. Karta rolki: `ma_klatke`, `klatka_url` (miniatura klatki), `klatka_info {ok, powod,
  zaakceptowana, proby, kr, model, tlo, kontrola}`, `mozna_uzyc_klatki`; `w_toku_opis` zaczyna się od „pierwsza klatka:” w fazie
  zdjęcia. `koszt` gotowej rolki = wideo + klatki.
- `POST /api/pomysly/<id>/klatka {"uzyj": true}` (3.5) – „Zrób wideo z tej klatki”: klatka odrzucona przez kontrolę AI idzie jednak
  do wideo (rolka `blad` → `nowy`, nic nie wysyła; wideo dopiero po „Zrób tę rolkę” z ceną). Bez `uzyj` → 400, rolka w toku → 409.
  `POST /api/pomysly/<id>/ponow` przy klatce odrzuconej przez kontrolę = następnym razem nowe klatki; klatka dobra zostaje.
- Konta: `openrouter` (klucz `sk-or-…`, test = `GET /api/v1/key`, darmowe). `POST /api/konta` odrzuca klucz ElevenLabs bez `sk_`
  i OpenRouter bez `sk-or-` (400).

### 3.1 – biblioteka strojów, sylwetka, głos tylko ElevenLabs
- `stroj: "biblioteka" | "biblioteka:<id>"` (domyślny; katalog `stroje_biblioteka [{id, nazwa, ulubiony, ma_zdjecie, url}]`, ulubione
  pierwsze). Wycena zwraca `stroj_id`, `stroj_tryb`, `stroj_nazwa`, `stroj_plik` (nazwa zdjęcia albo null), `nagrywa`.
- `glos`: tylko `"auto" | "tts"` (stare `"model"` = tts z ostrzeżeniem) – model wideo nigdy nie mówi; bez działającego ElevenLabs
  wycena ma ostrzeżenie, a rolka wychodzi bez komentarza (`glos_blad`, „Dograj głos”). `nagrywa: "chlopak" | "dziewczyna"` (brak =
  ustawienie persony) – komentarz w formie mówiącego; katalog: `nagrywa`, `komentarze_plec {chlopak: [...], dziewczyna: [...]}`,
  `persona.nagrywa`, `persona.sylwetka`. `glos_id` i `wymowa` w panelu usunięte.
- `POST /api/pomysly/<id>/stroj {"stroj": "z_filmu" | "<id ze stroje_biblioteka ze zdjęciem>"}` – zmiana stroju rolki z filmu przed
  generacją (A <-> B, prompt persony podmieniany; własny prompt zostaje + `uwaga`) → `{pomysl, uwaga}`; `w_toku` → 409, zrobiona /
  z promptu / bez zdjęcia → 400. `GET /api/pomysly` ma też `biblioteka` (stroje ze zdjęciem) i `ma_prompt_b`; karta: `stroj_bib`,
  `stroj_nazwa`, `stroj_ulubiony`, `mozna_zmienic_stroj`.
- Ustawienia: `stroj_swap` (`biblioteka` | `z_filmu`), `nagrywa`, `glos_chlopak`, `glos_dziewczyna` (złe wartości → 400);
  `GET /api/ustawienia` ma `biblioteka` (wszystkie stroje z miniaturami). Profil: `POST /api/profil {"sylwetka": "<EN>"}`.

## Modelki (persony)
- `POST /api/modelki` `{"nazwa": "Noemi", "instagram": "@uroczanoemi"}` → `{"slug": "noemi"}` (ustawia jako aktywną)
- `POST /api/modelki/aktywna` `{"slug": "noemi"}`
- `POST /api/profil` `{"instagram": "", "opis_stylu": "", "nazwa": "", "cechy": "a, b", "wzrost_cm": "158-160", "wlosy": "", "sylwetka": ""}` → `{"profil": {...}}`

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
Panel sam odpala przy starcie zadanie `wznow` (dokończenie rolek i zdjęć `w_toku`, bez wysyłania drugi raz). Wynik `generuj`:
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
  `dostawca` (higgsfield|yapper|wavespeed), `model`, `mode`, `mode_bez_zrodla`, `aspect_ratio`, `resolution`, `duration`,
  `yapper.model`, `yapper.resolution`, `yapper.duration`, `wavespeed.model` (`bytedance/seedance-2.5/video-edit-turbo` domyślnie |
  `bytedance/seedance-2.5/video-edit` | `alibaba/wan-3.0/reference-to-video` | `alibaba/wan-3.0-prime/reference-to-video`),
  `wavespeed.generate_audio` (false = oryginalny dźwięk filmiku), `wavespeed.parametry` (dict), `wavespeed.min_kredyty` /
  `wavespeed.max_kredyty_na_rolke` (centy USD, domyślnie 0 / 400), `prompt_auto`, `stroj_domyslny`, `min_kredyty`,
  `max_kredyty_na_rolke`, `powtorki` (ponowne WYSŁANIE tylko, gdy job nie powstał), `zapas_nsfw` (lista kroków
  `[{"dostawca": "yapper"|"wavespeed", "model": "wan-3.0-prime"}, ...]` albo tekst JSON; inny dostawca = 400; `[]` = wyłączone), `zrodla_dir`, `wyniki_dir`, `mediatool`, `autopilot`, `autopilot_co_minut`,
  `autopilot_max_rolek_dziennie`, `telegram_wysylaj`, `telegram_czat`, `zdjecia_model`, `zdjecia_dziennie`, `zdjecia_parametry`, `zdjecia_dir`,
  `zdjecia_stroje`, `zdjecia_prompt_stroj`, `lipsync_dostawca` (sync|higgsfield), `lipsync_model`, `lipsync_auto` (tylko ręczne „Zrób rolkę”),
  `lipsync_parametry.sync_mode`, `tts_model`, `tts_glos`, `tts_glos_typ`.
  Zmiana `resolution`, `dostawca`, `wavespeed.model` albo `yapper.model` czyści policzone koszty rolek „nowy” (`koszt: null` – liczone od nowa).
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
  "wavespeed": {"nazwa": "WaveSpeed", "typ": "klucz", "jest": false, "maska": "", "z_env": false, "ok": null, "komunikat": "", "jak": "... https://wavespeed.ai/dashboard -> API Keys ..."},
  "elevenlabs": {...}}}
```
- `POST /api/konta` `{"dostawca": "yapper", "klucz": "..."}` (pusty klucz = usuń) → `{"konta": {...}}`
- `POST /api/konta/test` `{"dostawca": "yapper"}` → `{"dziala": true, "komunikat": "1234 kr dostepnych"}`; `{"dostawca": "wavespeed"}` →
  `{"dziala": true, "komunikat": "klucz dziala, saldo $12.34"}` (GET /balance, nic nie kosztuje; przy $0 dopisek "doladuj konto")

## Modele i głosy (listy do selectów; cache 10 min, `?odswiez=1`)
- `GET /api/modele?dostawca=higgsfield&typ=image|video|audio` → `{"modele": [{"id": "nano_banana_2", "nazwa": "Nano Banana 2", "typ": "image", "opis": ""}]}`
- `GET /api/modele?dostawca=yapper` → jak wyżej (modele wideo yapper, np. `wan-3.0`, `wan-3.0-prime`)
- `GET /api/modele?dostawca=wavespeed` → modele, które fabryka umie wysłać do WaveSpeed (`wavespeed.MODELE`, bez zapytania do API i bez klucza)
- `GET /api/modele?dostawca=sync` → modele lipsync (`lipsync-2`, `lipsync-2-pro`, `sync-3`...)
- `GET /api/glosy?dostawca=sync|higgsfield` → `{"glosy": [{"id": "...", "nazwa": "Rachel", "typ": "preset", "opis": "female"}]}`
  Gdy dostawca nie jest zalogowany/brak klucza: `{"ok": false, "blad": "..."}` (400) – GUI pokazuje komunikat, nie wywala się.

## Zdjęcia – podmiana postaci (3.2, strona Zdjęcia, `zdjecia_swap.py`)
User wstawia zdjęcie, persona aktywna w panelu zajmuje miejsce osoby na nim (kadr/poza/tło/światło ze zdjęcia; twarz, włosy,
sylwetka, wzrost, piercing i tatuaże persony z referencji i profilu). Zawsze Higgsfield CLI.
- `GET /api/swap` → `{"modele": [{"id": "seedream_v5_pro", "nazwa", "opis", "proporcje": ["9:16", ...], "jakosc": [["high", "Wysoka"], ...]
  (pusta = model nie ma jakości – chip znika), "rozdzielczosc": [["2k", "2K"], ...], "max_obrazow": 10|null, "domyslne": {"jakosc", "rozdzielczosc"}}],
  "model_domyslny": "seedream_v5_pro", "jak_zdjecie": "jak_zdjecie", "stroj_ze_zdjecia": "ze_zdjecia", "max_ile": 4, "max_dopisku": 300,
  "domyslne": {"model", "proporcje": "jak_zdjecie", "ile": 1, "stroj": "ze_zdjecia"}, "persona": {slug, nazwa, referencje, sylwetka, wlosy},
  "stroje": [{id, nazwa, ulubiony, ma_zdjecie, url}] (biblioteka – tylko ze zdjęciem, ulubione pierwsze), "folder": "...\\tu zdjecia zrobione\\Noemi"}`.
  Modele: `seedream_v5_pro` (domyślny), `nano_banana_pro`, `gpt_image_2_5` – schematy z `model get` (panel odświeża je przy starcie, darmowe).
- `POST /api/swap/zdjecie` multipart `plik` (png/jpg/webp) → kopia obrócona wg EXIF, bez metadanych, dłuższy bok ≤ 3072 px w
  `modelki/<slug>/swap_zrodla/<czas>_<nazwa>.jpg|png` (nic nie idzie do Higgsfield) → `{"zrodlo": "<nazwa pliku>", "url", "nazwa",
  "szer", "wys", "proporcje": {"<model>": "3:4"}}` (najbliższe obsługiwane proporcje). Nie-zdjęcie → 400.
- `POST /api/swap/wycena {zrodlo?, model?, proporcje? ("jak_zdjecie" | "9:16"...), jakosc?, rozdzielczosc?, ile? (1-4), stroj?, dopisek?}`
  → `{"model", "nazwa_modelu", "parametry": {aspect_ratio, resolution, quality?}, "opis", "ile", "kr_sztuka": 2.5 (cena 1 zdjęcia,
  może być ułamkowa), "kr": 5 (razem), "kr_limit": 6 (do limitu dnia – w górę), "saldo", "dzis": {wydano (z rezerwą w toku), limit},
  "min_kredyty", "mozna", "powody", "ostrzezenia"}`. Darmowe `generate cost` BEZ zdjęć (cena od nich nie zależy), cache 1 h po
  parametrach. Wartość spoza schematu modelu → 400.
- `POST /api/swap {zrodlo, model, proporcje, jakosc, rozdzielczosc, ile, stroj, dopisek, kr}` (3.3) → `{"ids": [12, 13], "kolejka":
  {...jak zdjecia_kolejka...}}` OD RAZU – N wpisów `w_kolejce` (nic jeszcze nie wysłane); konsola zajęta (rolki, autopilot) NIE
  przeszkadza (bez 409). Bez `kr` (cena 1 zdjęcia z wyceny) → 400. Rezerwacja w limicie dnia i saldzie atomowa (blokada kolejki,
  liczy rolki i zdjęcia w toku + całą kolejkę); odmowa → 400 `{"ok": false, "blad", "kod": "cena wzrosla"|"limit dzienny"|
  "min_kredyty"|"max/zdjecie"|...}` i nic nie powstaje. Dyspozytor w tle wysyła równolegle, max `zdjecia_rownolegle` (globalne,
  domyślnie 4) w toku naraz; każde zdjęcie: świeża cena (wyższa = blad, 0 kr), bezpieczniki, wpis `w_toku` przed wysłaniem, świeży
  upload (`w_toku.obraz_id`), create bez `--wait`, `job_id` od razu. Higgsfield odmówił „za dużo naraz” (HTTP 429 / too many /
  concurrent / rate limit) i job na pewno nie powstał → zdjęcie wraca do kolejki (`kolejka.nie_przed`, `ponowienia`); wątpliwość →
  nigdy drugi raz. NSFW/IP albo niepewne wysyłanie jednego → reszta serii z kolejki `anulowane`.
- `POST /api/swap/stop` → `{"anulowane": n, "w_toku": m, "kolejka": {...}}` – STOP strony Zdjęcia: kolejka (wszystkie persony) →
  `anulowane` (0 kr); przyjęte joby nie są anulowane – dokończą się przy następnym sprawdzeniu (Generuj, przebieg autopilota, restart).
- CLI `zdjecie-swap` = `zdjecia_swap.generuj` (zlec + obsługa tych zdjęć do końca, też równolegle) → `{"zrobione", "pliki", "bledy",
  "odrzucone", "w_toku", "stop", "ids"}`. Wznawianie: dyspozytor panelu (start, co 60 s osierocone), autopilot, `fabryka.py wznow`.

## Zdjęcia, lipsync, dziennik, budżet, autopilot
- `GET /api/zdjecia` → `{"zdjecia": [{"id", "prompt", "plik", "url", "status", "koszt", "utworzono", "notatki", "stroj"}]}`; swap (3.2):
  `typ: "swap"`, `status` też `w_toku`, `zrodlo` + `zrodlo_url` (miniatura wstawionego zdjęcia), `zrodlo_nazwa`, `model`, `parametry`,
  `stroj_bib`, `stroj_url`, `opis` (krótko po polsku), `wycena` (np. 2.5), `koszt` (do limitu, w górę), `powod` (nsfw|ip|inny), `w_toku`
- `DELETE /api/zdjecia/<id>` (`?plik=1` kasuje też plik); zdjęcie `w_toku` → 409; `w_kolejce` → wyjęte z kolejki (sprawdzenie i
  usunięcie pod blokadą). Statusy zdjęć swap (3.3): `w_kolejce` (czeka, `kolejka` {kr, koszt, od, seria, nie_przed, ponowienia}),
  `w_toku`, `gotowe`, `blad`, `anulowane` (STOP / reszta serii po filtrze – nic nie poszło).
- `POST /api/zdjecia/<id>/przerwij {"potwierdzam": true}` – „Przestań czekać” na zdjęcie `w_toku` (status blad + prośba o sprawdzenie
  w apce); bez potwierdzenia 400, w trakcie wysyłania 409
- `GET /api/lipsync` → `{"lipsync": [{"id", "wideo", "audio", "dostawca", "model", "pomysl_id", "status", "plik_wynikowy", "url", "koszt", "notatki", "utworzono", "styl"?, "audio_przygotowane"?}]}`
- Brzmienie głosu (2.2): przed wysłaniem do sync.so głos jest przerabiany ffmpegiem wg ustawienia `lipsync_glos_styl`
  (`telefon` = jak nagranie z telefonu w pokoju: pasmo mikrofonu, lekki pogłos, szum tła, wyrównana głośność – domyślnie;
  `czysty` = tylko głośność; `brak` = plik bez zmian). Głosówki z Telegrama (.ogg) też przechodzą. Wynik w `modelki/<slug>/audio/_przygotowane/`.
  GUI: select „Brzmienie głosu” w dialogu Lipsync (pole `styl` akcji) + ustawienie w sekcji Lipsync (tryb pełny).
  Wynik lipsyncu idzie jak rolka: surowy plik z API do `modelki/<slug>/wyniki/<nazwa>_lipsync.raw.mp4`, potem Media Tool (gdy `mediatool`)
  → `wyniki_dir/<nazwa>_lipsync.mp4`. Autopilot wysyła wersję z dopasowanymi ustami na Telegram raz (`telegram_wyslano_lipsync`).
- `DELETE /api/lipsync/<id>`
- `GET /api/dziennik?ile=100&typ=blad` → `{"wpisy": [{"czas", "typ", "modelka", "tekst", "dane"}]}` (najnowszy na końcu)
- `GET /api/budzet` → `{"budzet": {...plik budzet.json...}, "dzis": {"higgsfield": {"wydano": 90, "limit": 300, "jednostka": "kr"}, "yapper": {"wydano": 0, "limit": 0, "jednostka": "kr"}, "sync": {"wydano": 50, "limit": 0, "jednostka": "c"}, "wavespeed": {"wydano": 260, "limit": 1000, "jednostka": "c"}}}`
- `POST /api/budzet` `{"dostawca": "higgsfield", "max_kredyty_dziennie": 300}` (WaveSpeed: w centach, 1000 = $10; nieznany dostawca = 400)
- `POST /api/autopilot` `{"wlacz": true}` → `{"autopilot": {...jak w /api/stan...}}` (pętla w tle; `wlacz: false` zatrzymuje).
  `autopilot.etap` może być `z_promptu`, a `autopilot.opis` = np. „robię rolkę z promptu: Noemi, Galeria Posnania” (3.3).
- Ustawienia wspólne dla person (3.3, `ustawienia_globalne.json`): `GET /api/ustawienia/globalne` → `{"ustawienia":
  {"zdjecia_rownolegle": 4, "autopilot_z_promptu": {"dziennie": 1, "model": "seedance_2_5", "persony": [], "od_godziny": "10:00"},
  "autopilot_rolki_ig": {"wlaczone": false, "profile": [], "konto_obserwowanych": "", "dziennie": 3, "kandydatow_na_profil": 5,
  "do_person": "round-robin", "pobieranie_przez_apify": false}},
  "domyslne", "modele_z_promptu": [{id, nazwa}], "persony": [{slug, nazwa, referencje}], "z_promptu": {...jak w /api/stan...},
  "rolki_ig": {...jak w /api/stan...}, "ma_klucz_apify": bool, "max_rownolegle": 8}`; `POST /api/ustawienia/globalne`
  `{"zdjecia_rownolegle": 1-8}` / `{"autopilot_z_promptu": {dowolne z pól}}` (dziennie 0-20, 0 = wyłączone, ŁĄCZNIE dla person;
  model `seedance_2_5` | `wan3_0_prime`; persony = istniejące slugi; od_godziny GG:MM) / `{"autopilot_rolki_ig": {dowolne z pól}}`
  (3.4: `profile` = lista albo tekst po @ w linii/przecinku; dziennie 0-50; kandydatow_na_profil 1-50; do_person `round-robin`|slug)
  / `{"pierwsza_klatka": {dowolne z pól}}` (3.5: `wlaczona` bool, `model` jak `klatka_model`, `kontrola` bool, `max_dodatkowych` 0-2;
  3.5.1: `zapas_nsfw` lista modeli klatki po odrzuceniu przez filtr NSFW, domyślnie `["seedream_v5_pro", "nano_banana_pro"]`, [] = bez;
  GET oddaje też `modele_klatki [{id, nazwa, opis}]`, `folder_tel` (Pulpit/ROLKI AI/tla), `ma_klucz_openrouter`)
  – złe wartości → 400. Limitów budżetu tu nie ma.
- 3.5: każdy przebieg autopilota (i start panelu) dokańcza rolki ORAZ zdjęcia w toku WSZYSTKICH person, także bez włączonego
  autopilota (ten sam job, 0 kr). Rolka z pierwszą klatką przerwana w fazie zdjęcia: dokańcza się tylko klatka, rolka wraca do `nowy`.
- Autopilot rolek z promptu (3.3): co przebieg (po rolkach ze swapu), od `od_godziny`, aż `dziennie` rolek z promptu autopilota
  dziś (dzień lokalny, osobny licznik od swapu): persony na zmianę → losowy pomysł + asystent → darmowa wycena i bezpieczniki →
  ta sama ścieżka co „Zrób rolkę” → ElevenLabs, Media Tool, Telegram. Max 2 nieudane dziennie; pominięcie (limit/saldo) = wpis
  „uwaga” w dzienniku. Pomysł ma `autopilot_z_promptu: true` (karta: „autopilot · ...”).
- Rolki z Instagrama (3.4, źródło klipów do swapa): `/api/stan.rolki_ig` = `{"wlaczone", "dziennie", "dzis", "profile", "persony",
  "do_person", "ma_klucz", "stan": wylaczone|brak_klucza|brak_profili|brak_person|gotowe|czeka, "tekst": "Rolki z Instagrama: dziś
  X z N (…)"}`. Autopilot (`krok_rolki_ig`, w `przebieg_wszystkich` PRZED personami): przez Apify (`dostawcy/instagram.py`, klucz
  `apify`) pobiera najnowsze rolki z `profile`, AI/heurystyki odsiewają słabe, dobre lądują w `tu wrzucasz rolki\<Persona>` (round-robin
  po personach z referencjami albo `do_person`) – skanuj je potem podejmie. Dzienny licznik `dziennie` (osobny od generacji),
  dedup po shortcode (`instagram_widziane.json`, poza gitem). Bez klucza Apify = nie pobiera + „uwaga” w dzienniku. Konto Apify:
  `POST /api/konta {"dostawca": "apify", "klucz": "apify_api_…"}`, test = `GET /v2/users/me` (zielone „działa” gdy klucz dobry).

## Teksty i szablony (bez zmian)
- `GET /api/teksty`, `POST /api/teksty` `{"teksty": "linia\nlinia", "zrodlo": ""}` → `{"dodano": n}`, `POST /api/teksty/losuj` → `{"tekst", "nieuzyte", "wszystkie"}`
- `GET /api/szablony`, `POST /api/szablony` `{"nazwa", "tresc"}`, `DELETE /api/szablony/<nazwa>`, `POST /api/szablony/wypelnij` `{"tresc", "wartosci": {}}` → `{"prompt"}`
