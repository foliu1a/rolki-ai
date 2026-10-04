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
3. Skrót **Rolki AI** na pulpicie (robi go `instaluj.bat` / `aktualizuj.bat`; ręcznie: `skrot-na-pulpit.bat`) → panel
   http://localhost:5077 (bez czarnego okna; `panel.bat` = to samo z oknem, gdy chcesz widzieć błędy). W panelu:
   - **+ nowa modelka**, wrzuć zdjęcia persony (zakładka *Persona → Referencje*, przeciągnij pliki),
   - wklej swoje prompty A/B (*Persona → Prompty*),
   - foldery robią się same na pulpicie (patrz niżej); własne ustawisz w *Persona → Foldery*,
   - w *Konta* wpisz klucze API yapper.so i sync.so (jeśli chcesz z nich korzystać). Klucze zostają w `klucze.json` na Twoim dysku.
4. Bezpiecznik budżetu (*Persona → Bezpiecznik*): `min_kredyty`, `max_kredyty_na_rolke`, limit dzienny. Zmieniasz tylko Ty.

## Gdzie wrzucam, gdzie odbieram

Panel przy starcie tworzy na pulpicie folder **`ROLKI AI`**:

```
Pulpit\ROLKI AI\
  tu wrzucasz rolki\    Noemi\  Alicja\  Bianka\     <- tu wrzucasz filmiki źródłowe (wrzutnia)
  tu rolki zrobione\    Noemi\  Alicja\  Bianka\     <- tu wychodzą gotowe rolki NNN_nazwa.mp4 (po Media Tool)
  tu zdjecia zrobione\  Noemi\  Alicja\  Bianka\     <- gotowe zdjęcia persony
```

Stare foldery `ROLKI AI\przed\<persona>` i `po\<persona>` są przenoszone pod nowe nazwy razem z kolejką.
Start w panelu pokazuje te ścieżki z przyciskiem „Otwórz folder”; `python fabryka.py foldery` to samo w konsoli.

## Obieg pracy

Ręcznie (panel albo konsola):
1. Wrzuć filmiki do wrzutni (`tu wrzucasz rolki\<persona>\`). Obok filmiku możesz położyć `<nazwa>.stroj.png` (strój ze zdjęcia, wariant B)
   i `<nazwa>.audio.mp3` (głos do lipsyncu - robisz go potem ręcznie w zakładce *Lipsync*).
2. **Skanuj** - każdy filmik dostaje numer, podgląd klatek i Twój prompt (A albo B).
3. **Policz koszt** - ile kredytów zejdzie. **Generuj** - z bezpiecznikiem (min_kredyty, max/rolka, limit dzienny).
   Rozdzielczość wybiera długość klipu: **≤ 8 s → 1080p, dłuższy → 720p** (Higgsfield i yapper).
4. Gotowy plik ląduje w `tu rolki zrobione\<persona>\NNN_nazwa.mp4` (po Media Tool). Surowy wynik zostaje w `modelki\<slug>\wyniki\`.
5. Opcjonalnie: **Lipsync** (wideo + głos z folderu `audio/`, głosówka z Telegrama albo TTS z tekstu; głos jest najpierw
   przerabiany, żeby brzmiał jak nagranie z telefonu w pokoju – `lipsync_glos_styl`: telefon / czysty / brak), **Zdjęcia**
   (model obrazu z referencjami, co drugie w stroju z folderu *Stroje*), **Podpis** z banku tekstów.

Automatycznie - **Autopilot** (przełącznik w panelu): co `autopilot_co_minut` minut robi
skanuj → generuj (Higgsfield albo yapper) → Media Tool → zdjęcia (`zdjecia_dziennie`) → podpisy → rolka na Telegram, dla każdej
modelki z włączonym `autopilot`. Pilnuje `autopilot_max_rolek_dziennie`, limitu dziennego i salda. Ty tylko wrzucasz filmiki.
**Autopilot nie robi lipsyncu** - dopasowanie ust jest tylko ręczne (zakładka *Lipsync*).

- **Hamulec**: po `autopilot_stop_po_bledach` (3) nieudanych rolkach z rzędu (awarie techniczne - odrzucenia przez filtr NSFW się
  nie liczą) autopilot zatrzymuje personę, alarmuje na telefon i czeka na „Wznów” w panelu (albo `/wznow` z Telegrama).
- **Nigdy dwa razy za jedną rolkę**: rolka idzie do Higgsfield/yapper bez czekania, numer joba zapisuje się od razu (status
  „generuje się”), a fabryka tylko sprawdza ten job. Zamknięcie panelu, aktualizacja, błąd sieci czy STOP nie wysyłają rolki drugi raz -
  po ponownym uruchomieniu panel sam dokończy rolki w toku (ręcznie: `python fabryka.py wznow`). „Zamknij program” i `aktualizuj.bat`
  czekają, aż skończy się wysyłanie. Gdy nie wiadomo, czy rolka dotarła do Higgsfield (błąd w trakcie wysyłania), fabryka szuka jej
  przez godzinę, a potem prosi, żebyś sprawdził w apce – sama nigdy nie wysyła drugi raz („więcej → Przestań czekać”, gdy utknie).
  Koszt liczony z joba, więc Twoje ręczne generacje w apce Higgsfield nie zjadają limitu fabryki; limit dzienny liczy też rolki w toku.
- **Długie filmiki i koszt**: koszt rolki rośnie z długością (720p ≈ 7,5 kr/s, 1080p ≈ 12 kr/s), więc źródło dłuższe niż
  `max_sekund_rolki` (domyślnie 15 s, max 30) jest cięte na kawałki tej długości (`dziel_dlugie`) – każdy to osobna rolka.
  Rozdzielczość wybiera długość kawałka: **≤ 8 s → 1080p, dłuższy → 720p**.
  Panel → Ustawienia → **Jakość i koszt**: *Oszczędnie* (rolki do 10 s, ~75 kr) / *Normalnie* (do 15 s, ~112 kr) / *Najlepiej*
  (do 8 s, zawsze 1080p, ~96 kr). Start pokazuje, ile rolek jeszcze „wejdzie” dziś w limit.
- **Podpisy**: z banku tekstów + hashtagi persony (Ustawienia → Persona).
- **Tani podgląd**: zanim wydasz 45–72 kr na rolkę, „Tani podgląd (~21 kr)” w Rolkach pokaże, czy prompt działa (Seedance draft).
- **Porządki**: raz dziennie kasuje surowe pliki `.raw.mp4` starsze niż `sprzataj_po_dniach` (gdy gotowy plik jest)
  i robi kopię zapasową danych person (`modelki/_kopie/<data>/`, 7 dni).
- **Diagnoza**: panel (Start → „Pierwsze kroki”) i `python fabryka.py diagnoza` mówią, czego brakuje (ffmpeg, logowanie,
  Media Tool, Telegram, zdjęcia/prompty person, foldery, konto Telegram persony). Prompty są sprawdzane pod kątem numerów `@[Image N]`.
- **Filtr NSFW**: odrzucona rolka dostaje `powod: nsfw` (kredyty wracają) i nie jest powtarzana na tym samym modelu.
  **Zapas po NSFW** (Ustawienia → Jak robić rolki, tryb pełny → „Gdy filtr odrzuci rolkę”): fabryka próbuje tę samą rolkę na yapper.so
  (Wan 3.0 Prime, potem Wan 3.0) – raz na model, z promptem `prompty/wan.txt` persony, w limicie dziennym yappera (bez ustawionego
  limitu zapas nic nie wyda). Gotowa rolka ma plakietkę „zrobione na wan-3.0-prime (zapas)”; „Spróbuj jeszcze raz” przy odrzuconej
  rolce zaczyna od zapasu. Domyślnie wyłączone.
  Panel → Pomoc → „Filtr NSFW” (albo `python fabryka.py nsfw`) pokazuje, co u Ciebie może go uruchamiać: ryzykowne słowa w promptach
  (mesh, sheer, lingerie...), zdjęcia strojów z prześwitami/bielizną, dużo skóry na referencjach - filtr sprawdza wszystko naraz,
  więc jedno ryzykowne zdjęcie stroju psuje niewinny filmik.
- **Autostart z Windows**: `autostart.bat` (raz, bez praw administratora - skrót w folderze Autostart) - panel z autopilotem startuje
  po zalogowaniu, w tle. `autostart-usun.bat` wyłącza. Skrót na pulpit: `skrot-na-pulpit.bat` (ikona `static/rolki.ico`).
- **Aktualizacja**: `aktualizuj.bat` zamyka panel (czeka, aż skończy wysyłać rolkę), pobiera nową wersję, puszcza testy i uruchamia panel.

## Telefon jako pilot (Telegram)

1. W Telegramie napisz do **@BotFather**: `/newbot`, nadaj nazwę → dostaniesz token.
2. Panel → **Ustawienia → Konta → Telefon (Telegram)**: wklej token, „Zapisz”, „Testuj”.
3. Na telefonie napisz do swojego bota `/start` - od tej chwili to Twój **czat główny** (alarmy, raporty, komendy).

Potem: wysyłasz botowi filmik (w podpisie możesz dać nazwę persony) → trafia do wrzutni → autopilot robi rolkę →
bot odsyła gotową rolkę z podpisem. Nagranie głosu z podpisem = nazwa filmiku → zapisane przy rolce (usta dopasujesz w panelu → Lipsync).
Komendy: `/status`, `/raport`, `/stop`, `/wznow`, `/pomoc`. Raport dnia przychodzi sam po 20:00.
Limity Telegrama: bot pobiera pliki do 20 MB, wysyła do 50 MB.

**Osobne konto per persona**: *Ustawienia → Persona → Konto Telegram tej persony* = np. `@huy7128`. Z tego konta trzeba raz
napisać `/start` do bota (Telegram nie pozwala botom pisać pierwszym) - bot paruje tylko konta wpisane w ustawieniach, obce ignoruje.
Od tej chwili gotowe rolki i zdjęcia tej persony lecą na to konto; filmik wysłany z tego konta trafia do jej wrzutni.
`/stop` i `/wznow` działają tylko z czatu głównego.

Konsola robi to samo: `python fabryka.py status | skanuj | koszt | generuj --tak | wznow | zdjecia | lipsync | autopilot --raz`.
`python fabryka.py generuj --dry-run` pokazuje komendy bez wydawania kredytów.

## Dostawcy

| Co | Kto | Logowanie | Gdzie w panelu |
|---|---|---|---|
| Rolki (Seedance 2.5 Edit) | Higgsfield CLI | OAuth: `zaloguj-higgsfield.bat` | Persona → Generowanie: dostawca *Higgsfield* |
| Rolki (Wan 3.0 / Wan 3.0 Prime, Seedance, Kling...) | yapper.so Public API | klucz API (yapper.so → Account → API, Read+Write, płatny plan) | Konta + Persona → Generowanie: dostawca *yapper* |
| Lipsync + TTS (ElevenLabs) | sync.so API | klucz API (sync.so/settings/api-keys) | Konta + Lipsync |
| Zdjęcia persony | Higgsfield CLI (np. `nano_banana_2`, `text2image_soul_v2` z Soul ID) | jak wyżej | Persona → Zdjęcia |

Kredyty każdego dostawcy liczymy osobno (`budzet.json`, poza gitem) - z jobów, nie z różnicy salda. Uwaga: kredyty yapper mają inną skalę
niż Higgsfield (6 s klip w 1080p: Wan 3.0 Prime ≈ 130 kr, Wan 3.0 ≈ 250 kr), dlatego yapper ma własny bezpiecznik (`yapper.min_kredyty`,
`yapper.max_kredyty_na_rolke` - domyślnie 400) i własny limit dzienny (ustawiony: 500 kr; `python fabryka.py budzet max_kredyty_dziennie=500 --dostawca yapper`).
Wan potrzebuje własnego krótkiego promptu (`modelki/<persona>/prompty/wan.txt`, max 5000 znaków, bez `@[Image N]`).

## Struktura

```
rolki-ai/
  panel.bat / instaluj.bat / aktualizuj.bat / zaloguj-higgsfield.bat
  skroty.vbs / rolki.vbs / skrot-na-pulpit.bat   skrót "Rolki AI" na pulpicie (ikona static/rolki.ico; panel w tle + przeglądarka)
  autostart.bat / autostart-usun.bat / start-cicho.vbs   autostart panelu z autopilotem (folder Autostart, bez admina)
  app.py + templates/ + static/   panel Flask :5077 (API w API.md), /widget = małe okno z saldem i kolejką
  fabryka.py             logika: status / skanuj / koszt / generuj / wznow / pierz / zdjecia / lipsync / podpis / autopilot / foldery / nsfw / ustaw / budzet
  autopilot.py           pętla: telefon -> skanuj -> generuj (hamulec) -> pranie -> zdjęcia -> podpisy -> rolka na Telegram (konto persony); bez lipsyncu
  zdjecia.py             zdjęcia persony (model obrazu + referencje albo Soul ID; co drugie w stroju ze stroje/)
  lipsync.py             wideo + głos -> sync.so (albo model Higgsfield); TTS z tekstu
  dostawcy/              higgsfield.py (CLI), yapper.py (API), sync_so.py (API), telegram.py (bot), http.py (urllib)
  higgsfield_cli.py      wrapper na CLI @higgsfield/cli (logowanie OAuth, bez kluczy w plikach)
  mediatool.py           most do Media Tool (pranie wideo bez GUI)
  klatki.py              klatki + arkusz podglądu z wideo (ffmpeg)
  baza.py                warstwa danych; sekrety.py = klucze API (klucze.json, w .gitignore)
  budzet.json            limity dzienne i wydatki per dostawca; dziennik.jsonl = log zdarzeń (panel → Dziennik) - oba poza gitem
  modelki/<slug>/
    ustawienia.json      model, dostawca, prompty, bezpiecznik, autopilot, zdjęcia, lipsync
    prompty/             stroj_z_filmu.txt (A), stroj_ze_zdjecia.txt (B), zdjecia.txt (1 linia = 1 zdjęcie), wan.txt (prompt dla Wan / zapasu)
    zrodla/              wrzutnia (gdy zrodla_dir puste - normalnie Pulpit\ROLKI AI\tu wrzucasz rolki\<Persona>); <nazwa>.stroj.png / <nazwa>.audio.mp3 obok filmiku
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

Skopiuj `rolki-ai`, zainstaluj Pythona i Node.js, odpal `instaluj.bat`,
potem `zaloguj-higgsfield.bat` i wpisz klucze w panelu (Konta). `klucze.json`, `modelki/` i `budzet.json` przenieś ręcznie.
