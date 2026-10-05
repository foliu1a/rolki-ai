# -*- coding: utf-8 -*-
"""Warstwa danych: modelki (persony), kolejka pomyslow, bank tekstow."""
import copy
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

KATALOG_SKRYPTU = os.path.dirname(os.path.abspath(__file__))
# ROLKI_MODELKI pozwala trzymac dane gdzie indziej (np. na D:) albo odpalac testy na boku.
KATALOG_MODELEK = os.environ.get("ROLKI_MODELKI") or os.path.join(KATALOG_SKRYPTU, "modelki")
PLIK_STANU = os.path.join(KATALOG_MODELEK, "..", "stan.json") if os.environ.get("ROLKI_MODELKI") \
    else os.path.join(KATALOG_SKRYPTU, "stan.json")

# w_toku = job wyslany do dostawcy (job_id zapisany w pomysle) - fabryka tylko go odpytuje, NIGDY nie wysyla drugi raz
STATUSY = ["nowy", "w_toku", "wygenerowany", "postprodukcja", "gotowe", "blad"]

# Domyslne ustawienia generacji per modelka (modelki/<slug>/ustawienia.json).
# fabryka.py czyta je przy kazdej generacji; agent moze je zmieniac przez zapisz_ustawienia().
USTAWIENIA_DOMYSLNE = {
    "model": "seedance_2_5",
    "mode": "video_edit",           # t2v | omni_reference | video_edit | video_extension
    "aspect_ratio": "9:16",
    "resolution": "720p",           # 480p | 720p | 1080p
    "duration": None,               # None = tyle co zrodlo (zaokraglone), albo liczba sekund
    "generate_audio": None,         # None = domyslne modelu
    "referencje": [],               # sciezki do zdjec persony (--image), wzgledem folderu modelki albo absolutne
    "soul_id": "",                  # opcjonalny Soul reference_id (jesli model go przyjmuje)
    "prompt_bazowy": "prompty/stroj_z_filmu.txt",     # wariant A: persona w stroju z filmu (tekst albo plik .txt w folderze modelki)
    "prompt_stroj": "prompty/stroj_ze_zdjecia.txt",   # wariant B: persona w stroju z dolaczonego zdjecia (ostatni --image)
    "stroj_domyslny": "",           # zdjecie stroju (np. stroje/mesh.png) uzywane dla kazdego klipu bez wlasnego <nazwa>.stroj.png
    "prompt_auto": True,            # skanuj od razu wpisuje prompt do kazdego nowego pomyslu (prompt nie zalezy od klipu)
    "prompt_zasady": "",            # co w promptach ma byc zawsze / czego nigdy (notatki agenta)
    "min_kredyty": 200,             # generacja odmawia, gdy po niej zostaloby mniej
    "max_kredyty_na_rolke": 150,    # bezpiecznik na pojedyncza generacje
    "powtorki": 2,                  # ile razy ponowic WYSLANIE, gdy job nie powstal (blad sieci/CLI). Job, ktory powstal, nigdy
                                    # nie jest wysylany drugi raz (odpytujemy ten sam); odrzucenie NSFW/IP -> bez powtorki (zapas_nsfw)
    "zrodla_dir": "",               # wrzutnia poza projektem, np. C:\Users\yux\Desktop\ROLKI AI\przed\noemi ("" = modelki/<slug>/zrodla)
    "wyniki_dir": "",               # gotowe rolki poza projektem, np. ...\ROLKI AI\po\noemi ("" = modelki/<slug>/wyniki)
    "mediatool": True,              # po generacji przepusc wideo przez Media Tool (iPhone meta, GPS, spoof)
    "dodatkowe_parametry": {},      # cokolwiek ekstra dla CLI, np. {"seed": 42}
    # --- dostawca wideo ---
    "dostawca": "higgsfield",       # kto generuje rolki: higgsfield (Seedance, CLI) | yapper (Wan, API)
    "mode_bez_zrodla": "",          # tryb dla pomyslow BEZ filmiku (sam prompt + referencje), np. omni_reference; "" = pomijaj
    "yapper": {"model": "", "resolution": "720p", "duration": 5, "prompt": "", "parametry": {},   # ustawienia yapper.so (model Wan itd.)
               "min_kredyty": 0, "max_kredyty_na_rolke": 400},    # bezpiecznik w kredytach yapper (inna skala niz Higgsfield!)
                                    # yapper.prompt puste = prompty/wan.txt (prompt Wan: max 5000 znakow, bez @[Image N])
    "zapas_nsfw": [],               # zapas po odrzuceniu NSFW/IP: kroki po kolei, np. [{"dostawca": "yapper", "model": "wan-3.0-prime"},
                                    # {"dostawca": "yapper", "model": "wan-3.0"}]; [] = wylaczone. Wymaga dziennego limitu yappera.
    # --- autopilot (panel / autopilot.py) ---
    "autopilot": False,             # autopilot obsluguje te modelke (skanuj -> generuj -> pranie -> lipsync -> zdjecia)
    "autopilot_co_minut": 15,       # co ile minut autopilot sprawdza wrzutnie
    "autopilot_max_rolek_dziennie": 10,   # bezpiecznik ilosciowy (oprocz limitu kredytow)
    "autopilot_stop_po_bledach": 3,       # tyle nieudanych rolek z rzedu = autopilot sie zatrzymuje (hamulec), 0 = nigdy
    "telegram_wysylaj": True,             # gotowe rolki (i zdjecia) leca na telefon przez bota Telegram
    "telegram_czat": "",                  # konto Telegram tej persony, np. "@huy7128" - tam leca jej gotowe rolki ("" = czat glowny);
                                          # to konto musi raz napisac /start do bota (inaczej Telegram nie pozwala botowi pisac)
    "dziel_dlugie": True,                 # filmik dluzszy niz max_sekund_rolki tnij na kawalki (kazdy = osobna rolka)
    "max_sekund_rolki": 15,               # dlugosc jednej rolki (4-30; Seedance max 30). Koszt rosnie z dlugoscia: 720p ~7.5 kr/s,
                                          # 1080p ~12 kr/s -> 15 s = ~110 kr. Panel: Ustawienia -> Jakosc i koszt (oszczednie 10 s)
    "sprzataj_po_dniach": 14,             # autopilot kasuje surowe wyniki (.raw.mp4) starsze niz tyle dni, gdy gotowy plik istnieje (0 = nigdy)
    # --- zdjecia persony ---
    "zdjecia_model": "",            # job_type modelu obrazu z `model list --image` (wybor w panelu), "" = wylaczone
    "zdjecia_dziennie": 0,          # ile zdjec dziennie robi autopilot (0 = tylko recznie z panelu)
    "zdjecia_prompty": "prompty/zdjecia.txt",   # jedna linia = jeden prompt; autopilot bierze po kolei (w kolko)
    "zdjecia_parametry": {},        # parametry modelu obrazu, np. {"aspect_ratio": "3:4"}
    "zdjecia_dir": "",              # gotowe zdjecia poza projektem ("" = modelki/<slug>/zdjecia)
    "zdjecia_stroje": True,         # co drugie zdjecie: persona w stroju ze stroje/ (character elements; po kolei), gdy stroje sa
    "zdjecia_prompt_stroj": "She is wearing exactly the outfit from the last reference image - same garment, cut, colors and material.",
                                    # dopisek do promptu zdjecia, gdy dolaczamy zdjecie stroju (ostatni obraz)
    # --- lipsync (tylko recznie z panelu; autopilot NIGDY nie robi lipsyncu) ---
    "lipsync_dostawca": "sync",     # sync (sync.so API) | higgsfield (model lipsync z CLI)
    "lipsync_model": "lipsync-2",   # model sync.so albo job_type modelu Higgsfield
    "lipsync_auto": False,          # przy RECZNYM "Zrob rolke": jesli obok zrodla lezy <nazwa>.audio.mp3 -> od razu lipsync (autopilot pomija)
    "lipsync_glos_styl": "telefon", # jak przerobic glos przed lipsynciem: telefon (jak nagranie z telefonu w pokoju: pasmo mikrofonu,
                                    # lekki poglos, szum tla, wyrownana glosnosc) | czysty (tylko glosnosc) | brak (plik bez zmian)
    "lipsync_parametry": {},        # np. {"sync_mode": "loop"}
    "tts_model": "",                # job_type modelu text-to-speech Higgsfield (z `model list --audio`), "" = brak
    "tts_glos": "",                 # voice id z `higgsfield voices list`
    "tts_glos_typ": "preset",       # preset (wbudowany) | element (sklonowany)
}

# Budzet wspolny dla wszystkich modelek (kredyty sa jedne na konto): rolki-ai/budzet.json
# `max_kredyty_dziennie` + `wydatki` = Higgsfield (kompatybilne wstecz); inni dostawcy w `dostawcy`.
PLIK_BUDZETU = os.path.join(os.path.dirname(PLIK_STANU), "budzet.json")
BUDZET_DOMYSLNY = {"max_kredyty_dziennie": 300, "wydatki": {}, "dostawcy": {}}
DOSTAWCA_GLOWNY = "higgsfield"

# Dziennik zdarzen (panel pokazuje ostatnie wpisy): rolki-ai/dziennik.jsonl
PLIK_DZIENNIKA = os.path.join(os.path.dirname(PLIK_STANU), "dziennik.jsonl")


def _teraz():
    return datetime.now(timezone.utc).isoformat()


def _wczytaj_json(sciezka, domyslnie):
    if os.path.isfile(sciezka):
        with open(sciezka, encoding="utf-8") as f:
            return json.load(f)
    return domyslnie


def _zapisz_json(sciezka, dane):
    """Zapis atomowy (plik tymczasowy + os.replace): panel, autopilot i CLI pisza te same JSON-y, a przerwany zapis
    (zamkniecie okna, brak pradu) nie moze zostawic pol pliku kolejki."""
    os.makedirs(os.path.dirname(sciezka), exist_ok=True)
    tmp = f"{sciezka}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dane, f, ensure_ascii=False, indent=2)
        for proba in range(6):
            try:
                os.replace(tmp, sciezka)
                break
            except PermissionError:
                # Windows: plik chwilowo otwarty przez czytajacego (panel/CLI) - chwila i jeszcze raz
                if proba == 5:
                    raise
                time.sleep(0.05 * (proba + 1))
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


class _ZamekPliku:
    def __init__(self):
        self.rlock = threading.RLock()
        self.glebokosc = 0
        self.plik = None


_zamki_plikow = {}
_zamki_plikow_lock = threading.Lock()


@contextmanager
def _rmw(sciezka, timeout=30.0):
    """Blokada read-modify-write jednego pliku JSON: watki tego procesu (RLock, mozna wejsc ponownie) i inne procesy
    (plik <sciezka>.lock, msvcrt/fcntl). Bez niej panel (PATCH), autopilot i CLI moga nadpisac swiezy znacznik w_toku
    albo wydatek stara kopia pliku. Po `timeout` s bez blokady zapisujemy mimo to (fabryka nie moze stanac na zawsze)."""
    klucz = os.path.normcase(os.path.abspath(sciezka))
    with _zamki_plikow_lock:
        z = _zamki_plikow.setdefault(klucz, _ZamekPliku())
    with z.rlock:
        z.glebokosc += 1
        try:
            if z.glebokosc == 1:
                os.makedirs(os.path.dirname(klucz), exist_ok=True)
                f = open(klucz + ".lock", "a+")
                koniec = time.time() + timeout
                while not _zablokuj_plik(f):
                    if time.time() > koniec:
                        break
                    time.sleep(0.05)
                z.plik = f
            yield
        finally:
            z.glebokosc -= 1
            if z.glebokosc == 0 and z.plik is not None:
                _odblokuj_plik(z.plik)
                z.plik.close()
                z.plik = None


def _slug(nazwa):
    s = re.sub(r"[^a-z0-9]+", "_", nazwa.strip().lower()).strip("_")
    if not s:
        raise ValueError("Nieprawidlowa nazwa modelki.")
    return s


# ---------------- modelki ----------------

def lista_modelek():
    if not os.path.isdir(KATALOG_MODELEK):
        return []
    return sorted(
        n for n in os.listdir(KATALOG_MODELEK)
        if os.path.isdir(os.path.join(KATALOG_MODELEK, n)) and not n.startswith(("_", "."))   # _kopie to nie modelka
    )


def utworz_modelke(nazwa):
    slug = _slug(nazwa)
    folder = os.path.join(KATALOG_MODELEK, slug)
    if os.path.isdir(folder):
        raise ValueError(f"Modelka '{slug}' juz istnieje.")
    os.makedirs(os.path.join(folder, "wyniki"), exist_ok=True)
    os.makedirs(os.path.join(folder, "zrodla"), exist_ok=True)
    os.makedirs(os.path.join(folder, "referencje"), exist_ok=True)
    os.makedirs(os.path.join(folder, "stroje"), exist_ok=True)
    os.makedirs(os.path.join(folder, "prompty"), exist_ok=True)
    os.makedirs(os.path.join(folder, "audio"), exist_ok=True)
    os.makedirs(os.path.join(folder, "zdjecia"), exist_ok=True)
    _zapisz_json(os.path.join(folder, "ustawienia.json"), copy.deepcopy(USTAWIENIA_DOMYSLNE))
    _zapisz_json(os.path.join(folder, "pomysly.json"), [])
    _zapisz_json(os.path.join(folder, "teksty.json"), [])
    _zapisz_json(os.path.join(folder, "uzyte_tekstow.json"), [])
    _zapisz_json(os.path.join(folder, "szablony.json"), [])
    _zapisz_json(os.path.join(folder, "profil.json"), {
        "nazwa": nazwa,
        "instagram": "",
        "opis_stylu": "",
        "cechy": [],
        "hashtagi": "",     # doklejane do kazdego podpisu, np. "#ai #lifestyle"
    })
    return slug


def aktywna_modelka():
    stan = _wczytaj_json(PLIK_STANU, {})
    return stan.get("aktywna_modelka")


def ustaw_aktywna_modelke(slug):
    if slug not in lista_modelek():
        raise ValueError(f"Nie ma modelki '{slug}'.")
    _zapisz_json(PLIK_STANU, {"aktywna_modelka": slug})


def folder_modelki(slug):
    folder = os.path.join(KATALOG_MODELEK, slug)
    if not os.path.isdir(folder):
        raise ValueError(f"Nie ma modelki '{slug}'.")
    return folder


# ---------------- profil modelki ----------------

def _plik_profilu(slug):
    return os.path.join(folder_modelki(slug), "profil.json")


def profil_modelki(slug):
    dane = {"nazwa": slug, "instagram": "", "opis_stylu": "", "cechy": [], "hashtagi": ""}
    dane.update(_wczytaj_json(_plik_profilu(slug), {}))
    return dane


def zapisz_profil(slug, **pola):
    with _rmw(_plik_profilu(slug)):
        profil = profil_modelki(slug)
        profil.update(pola)
        _zapisz_json(_plik_profilu(slug), profil)
    return profil


# ---------------- ustawienia generacji ----------------

def _plik_ustawien(slug):
    return os.path.join(folder_modelki(slug), "ustawienia.json")


def ustawienia_modelki(slug):
    """Ustawienia generacji z domyslnymi uzupelnionymi (stare modelki bez pliku tez dzialaja)."""
    dane = copy.deepcopy(USTAWIENIA_DOMYSLNE)
    dane.update(_wczytaj_json(_plik_ustawien(slug), {}))
    return dane


def zapisz_ustawienia(slug, **pola):
    nieznane = [k for k in pola if k not in USTAWIENIA_DOMYSLNE]
    if nieznane:
        raise ValueError(f"Nieznane ustawienia: {', '.join(nieznane)}. "
                         f"Dozwolone: {', '.join(USTAWIENIA_DOMYSLNE)}")
    with _rmw(_plik_ustawien(slug)):
        dane = ustawienia_modelki(slug)
        for k, v in pola.items():
            # slowniki (yapper, zdjecia_parametry...) scalamy, zeby panel mogl zmienic jedno pole
            if isinstance(USTAWIENIA_DOMYSLNE[k], dict) and isinstance(v, dict) and isinstance(dane.get(k), dict):
                dane[k] = {**dane[k], **v}
            else:
                dane[k] = v
        _zapisz_json(_plik_ustawien(slug), dane)
    return dane


def _sciezka_w_modelce(slug, wartosc):
    """Ustawienie 'prompty/x.txt' albo 'stroje/mesh.png' -> pelna sciezka. normpath: na Windows ukosnik z ustawienia
    zamienia sie na backslash, zeby sciezki dalo sie porownywac (i zeby wygladaly normalnie w panelu)."""
    return os.path.normpath(wartosc if os.path.isabs(wartosc) else os.path.join(folder_modelki(slug), wartosc))


def _czytaj_prompt(slug, wartosc):
    """Ustawienie promptu moze byc tekstem albo sciezka do .txt (wzgledem folderu modelki)."""
    wartosc = (wartosc or "").strip()
    if wartosc.lower().endswith(".txt") and "\n" not in wartosc:
        sciezka = _sciezka_w_modelce(slug, wartosc)
        if os.path.isfile(sciezka):
            with open(sciezka, encoding="utf-8-sig") as f:
                return f.read().strip()
        return ""
    return wartosc


def prompt_bazowy(slug):
    """Wariant A: persona w stroju z filmu zrodlowego."""
    return _czytaj_prompt(slug, ustawienia_modelki(slug).get("prompt_bazowy"))


def prompt_stroj(slug):
    """Wariant B: persona w stroju z dolaczonego zdjecia (ostatni --image)."""
    return _czytaj_prompt(slug, ustawienia_modelki(slug).get("prompt_stroj"))


PLIK_PROMPTU_WAN = "prompty/wan.txt"


def prompt_wan(slug):
    """Prompt dla Wan (yapper): ustawienie yapper.prompt (tekst albo plik .txt), a gdy puste - prompty/wan.txt.
    Wan przyjmuje max 5000 znakow i nie zna skladni @[Image N](image_N) z Higgsfielda. "" = brak."""
    ustawienie = (ustawienia_modelki(slug).get("yapper") or {}).get("prompt") or ""
    return _czytaj_prompt(slug, ustawienie) or _czytaj_prompt(slug, PLIK_PROMPTU_WAN)


def zapisz_prompt(slug, nazwa_pliku, tekst):
    """Zapisuje prompt do modelki/<slug>/prompty/<nazwa_pliku>. Zwraca sciezke."""
    folder = os.path.join(folder_modelki(slug), "prompty")
    os.makedirs(folder, exist_ok=True)
    sciezka = os.path.join(folder, nazwa_pliku)
    with open(sciezka, "w", encoding="utf-8") as f:
        f.write(tekst.strip() + "\n")
    return sciezka


def stroj_domyslny(slug):
    """Sciezka do domyslnego zdjecia stroju albo None."""
    wartosc = (ustawienia_modelki(slug).get("stroj_domyslny") or "").strip()
    if not wartosc:
        return None
    sciezka = _sciezka_w_modelce(slug, wartosc)
    return sciezka if os.path.isfile(sciezka) else None


def folder_strojow(slug):
    folder = os.path.join(folder_modelki(slug), "stroje")
    os.makedirs(folder, exist_ok=True)
    return folder


def folder_zrodel(slug):
    """Wrzutnia: tu uzytkownik wrzuca filmiki zrodlowe (ustawienie zrodla_dir albo modelki/<slug>/zrodla)."""
    folder = (ustawienia_modelki(slug).get("zrodla_dir") or "").strip() or os.path.join(folder_modelki(slug), "zrodla")
    os.makedirs(folder, exist_ok=True)
    return folder


def folder_klatek(slug):
    """Podglad klatek trzymamy w projekcie, zeby nie smiecic w folderze uzytkownika."""
    folder = os.path.join(folder_modelki(slug), "klatki")
    os.makedirs(folder, exist_ok=True)
    return folder


def folder_gotowych(slug):
    """Gotowe (wyprane) rolki dla uzytkownika: wyniki_dir albo modelki/<slug>/wyniki."""
    folder = (ustawienia_modelki(slug).get("wyniki_dir") or "").strip() or os.path.join(folder_modelki(slug), "wyniki")
    os.makedirs(folder, exist_ok=True)
    return folder


# ---------------- foldery usera na pulpicie ----------------
# Pulpit\ROLKI AI\tu wrzucasz rolki\<persona>   -> zrodla_dir   (wrzutnia)
# Pulpit\ROLKI AI\tu rolki zrobione\<persona>   -> wyniki_dir   (gotowe, po Media Tool)
# Pulpit\ROLKI AI\tu zdjecia zrobione\<persona> -> zdjecia_dir
# Stare foldery "przed"/"po" (ROLKI AI\przed\<persona>) sa przenoszone pod nowe nazwy razem ze sciezkami w kolejce.

NAZWA_FOLDERU_PULPITU = "ROLKI AI"
FOLDERY_PULPITU = {"zrodla_dir": "tu wrzucasz rolki", "wyniki_dir": "tu rolki zrobione", "zdjecia_dir": "tu zdjecia zrobione"}
STARE_FOLDERY_PULPITU = {"zrodla_dir": "przed", "wyniki_dir": "po"}


def _pulpit_systemu():
    """Folder Pulpit uzytkownika (Windows: z shell32, dziala tez z OneDrive); poza Windows ~/Desktop albo ~."""
    home = os.path.expanduser("~")
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf) == 0 and buf.value:   # CSIDL_DESKTOPDIRECTORY
                return buf.value
        except Exception:
            pass
    for kandydat in (os.path.join(home, "Desktop"), os.path.join(home, "Pulpit")):
        if os.path.isdir(kandydat):
            return kandydat
    return home


def pulpit():
    """Folder 'ROLKI AI' na pulpicie (ROLKI_PULPIT w env nadpisuje - testy, inny dysk)."""
    return os.environ.get("ROLKI_PULPIT") or os.path.join(_pulpit_systemu(), NAZWA_FOLDERU_PULPITU)


def _nazwa_folderu_persony(slug):
    nazwa = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", (profil_modelki(slug).get("nazwa") or slug).strip()).strip(" .")
    return nazwa or slug


def foldery_pulpitu(slug):
    """Docelowe foldery persony na pulpicie: {"zrodla_dir": ..., "wyniki_dir": ..., "zdjecia_dir": ...} (bez tworzenia)."""
    nazwa = _nazwa_folderu_persony(slug)
    return {k: os.path.join(pulpit(), v, nazwa) for k, v in FOLDERY_PULPITU.items()}


def _ta_sama_sciezka(a, b):
    return os.path.normcase(os.path.normpath(os.path.abspath(a))) == os.path.normcase(os.path.normpath(os.path.abspath(b)))


def _przepisz_sciezki(slug, stary, nowy):
    """Po przeniesieniu folderu: sciezki w pomysly.json / zdjecia.json / lipsync.json dostaja nowy prefiks."""
    stary_n = os.path.normcase(os.path.normpath(os.path.abspath(stary))) + os.sep

    def _zamien(v):
        if isinstance(v, str) and os.path.normcase(os.path.normpath(v)).startswith(stary_n):
            return os.path.join(nowy, os.path.normpath(v)[len(stary_n):])
        return v

    for plik in (_plik_pomyslow(slug), _plik_zdjec(slug), _plik_lipsync(slug)):
        with _rmw(plik):
            lista = _wczytaj_json(plik, None)
            if not isinstance(lista, list):
                continue
            zmienione = False
            for w in lista:
                if isinstance(w, dict):
                    for k, v in list(w.items()):
                        nv = _zamien(v)
                        if nv != v:
                            w[k], zmienione = nv, True
            if zmienione:
                _zapisz_json(plik, lista)


def przygotuj_foldery_pulpitu(slug):
    """Tworzy foldery persony na pulpicie i wpisuje je w ustawienia (zrodla_dir / wyniki_dir / zdjecia_dir), gdy ustawienie
    jest puste albo wskazuje stary folder ROLKI AI\\przed|po\\... (ten jest przenoszony pod nowa nazwe, sciezki w kolejce
    tez). Wlasny folder usera (inny) zostaje bez zmian. Zwraca {"foldery": {klucz: sciezka}, "zmienione": {...}}."""
    ust = ustawienia_modelki(slug)
    docelowe = foldery_pulpitu(slug)
    zmiany, foldery = {}, {}
    for klucz, cel in docelowe.items():
        obecny = (ust.get(klucz) or "").strip()
        if obecny and _ta_sama_sciezka(obecny, cel):
            os.makedirs(cel, exist_ok=True)
            foldery[klucz] = cel
            continue
        if obecny:
            stary = STARE_FOLDERY_PULPITU.get(klucz)
            jest_stary = bool(stary) and _ta_sama_sciezka(os.path.dirname(obecny), os.path.join(pulpit(), stary))
            if not jest_stary:
                foldery[klucz] = obecny      # user ma wlasny folder - nie ruszamy
                continue
            if os.path.isdir(obecny) and os.path.exists(cel):
                foldery[klucz] = obecny      # oba istnieja - nic nie przenosimy, zeby nic nie zginelo
                continue
            if os.path.isdir(obecny):
                os.makedirs(os.path.dirname(cel), exist_ok=True)
                try:
                    os.rename(obecny, cel)
                    _przepisz_sciezki(slug, obecny, cel)
                except OSError:
                    foldery[klucz] = obecny
                    continue
                try:
                    os.rmdir(os.path.dirname(obecny))    # puste "przed"/"po" won
                except OSError:
                    pass
        os.makedirs(cel, exist_ok=True)
        zmiany[klucz] = cel
        foldery[klucz] = cel
    if zmiany:
        zapisz_ustawienia(slug, **zmiany)
    return {"foldery": foldery, "zmienione": zmiany}


def przygotuj_foldery_pulpitu_wszystkich():
    """Dla kazdej persony (panel przy starcie). Zwraca {slug: wynik}; bledy (np. brak praw) nie wywalaja."""
    wynik = {}
    for slug in lista_modelek():
        try:
            wynik[slug] = przygotuj_foldery_pulpitu(slug)
        except OSError as e:
            wynik[slug] = {"foldery": {}, "zmienione": {}, "blad": str(e)}
    return wynik


# ---------------- budzet dzienny (wspolny) ----------------

def budzet():
    dane = copy.deepcopy(BUDZET_DOMYSLNY)   # gleboka kopia: inaczej dopisz_wydatek zmienialby domyslne "wydatki"
    dane.update(_wczytaj_json(PLIK_BUDZETU, {}))
    dane.setdefault("wydatki", {})
    dane.setdefault("dostawcy", {})
    return dane


def zapisz_budzet(**pola):
    with _rmw(PLIK_BUDZETU):
        dane = budzet()
        dane.update(pola)
        _zapisz_json(PLIK_BUDZETU, dane)
    return dane


def _dzis():
    return datetime.now().strftime("%Y-%m-%d")


def dzien_lokalny(znacznik):
    """Znacznik czasu (zapisywany w UTC, np. '2026-10-05T23:30:00+00:00') -> dzien w lokalnej strefie ('2026-10-06'),
    zeby porownania z _dzis() nie gubily rolek/zdjec miedzy polnoca a 2:00. Bez strefy albo nieczytelny -> 10 pierwszych znakow."""
    s = str(znacznik or "")
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s[:10]
    if dt.tzinfo is None:
        return s[:10]
    return dt.astimezone().strftime("%Y-%m-%d")


def _konto_budzetu(dane, dostawca):
    """Slownik {max_kredyty_dziennie, wydatki} dla dostawcy (Higgsfield = korzen pliku)."""
    if dostawca in (None, "", DOSTAWCA_GLOWNY):
        return dane
    return dane["dostawcy"].setdefault(dostawca, {"max_kredyty_dziennie": 0, "wydatki": {}})


def limit_dzienny(dostawca=DOSTAWCA_GLOWNY):
    """Limit kredytow na dzien dla dostawcy (0 = bez limitu)."""
    return int(_konto_budzetu(budzet(), dostawca).get("max_kredyty_dziennie") or 0)


def zapisz_limit_dzienny(kredyty, dostawca=DOSTAWCA_GLOWNY):
    with _rmw(PLIK_BUDZETU):
        dane = budzet()
        _konto_budzetu(dane, dostawca)["max_kredyty_dziennie"] = int(kredyty)
        _zapisz_json(PLIK_BUDZETU, dane)
    return dane


def wydano_dzis(dostawca=DOSTAWCA_GLOWNY):
    konto = _konto_budzetu(budzet(), dostawca)
    return int((konto.get("wydatki") or {}).get(_dzis(), 0))


def dopisz_wydatek(kredyty, dostawca=DOSTAWCA_GLOWNY, job_id=None):
    """Dopisuje faktycznie zuzyte kredyty do dzisiejszego dnia (ujemne/zero ignorowane).
    job_id: koszt konkretnego joba liczy sie RAZ - drugie rozliczenie tego samego joba (np. po wznowieniu po restarcie)
    nic nie dopisuje (lista `rozliczone` w budzet.json, ostatnie 500 jobow per dostawca)."""
    kredyty = int(kredyty or 0)
    if kredyty <= 0:
        return wydano_dzis(dostawca)
    with _rmw(PLIK_BUDZETU):
        dane = budzet()
        konto = _konto_budzetu(dane, dostawca)
        if job_id:
            rozliczone = konto.setdefault("rozliczone", [])
            if str(job_id) in rozliczone:
                return int((konto.get("wydatki") or {}).get(_dzis(), 0))
            rozliczone.append(str(job_id))
            del rozliczone[:-500]
        wydatki = konto.setdefault("wydatki", {})
        dzis = _dzis()
        wydatki[dzis] = int(wydatki.get(dzis, 0)) + kredyty
        # trzymaj tylko ostatnie 60 dni
        for k in sorted(wydatki)[:-60]:
            wydatki.pop(k, None)
        _zapisz_json(PLIK_BUDZETU, dane)
    return wydatki[dzis]


def rozliczony(job_id, dostawca=DOSTAWCA_GLOWNY):
    """Czy koszt tego joba jest juz w budzecie (dopisz_wydatek z job_id)."""
    return bool(job_id) and str(job_id) in (_konto_budzetu(budzet(), dostawca).get("rozliczone") or [])


# ---------------- dziennik zdarzen ----------------

def dziennik_zapisz(typ, tekst, modelka=None, **dane):
    """Dopisuje wpis do dziennik.jsonl (typ: info|ok|uwaga|blad|kredyty). Zwraca wpis."""
    wpis = {"czas": _teraz(), "typ": typ, "modelka": modelka, "tekst": str(tekst)}
    if dane:
        wpis["dane"] = dane
    os.makedirs(os.path.dirname(PLIK_DZIENNIKA), exist_ok=True)
    try:
        if os.path.isfile(PLIK_DZIENNIKA) and os.path.getsize(PLIK_DZIENNIKA) > 5 * 1024 * 1024:
            os.replace(PLIK_DZIENNIKA, PLIK_DZIENNIKA + ".1")
    except OSError:
        pass
    with open(PLIK_DZIENNIKA, "a", encoding="utf-8") as f:
        f.write(json.dumps(wpis, ensure_ascii=False) + "\n")
    return wpis


def dziennik_ostatnie(ile=200, modelka=None, typ=None):
    """Ostatnie `ile` wpisow (najnowszy na koncu), opcjonalnie tylko dla modelki / typu."""
    if not os.path.isfile(PLIK_DZIENNIKA):
        return []
    with open(PLIK_DZIENNIKA, encoding="utf-8") as f:
        linie = f.readlines()[-max(ile * 4, ile):]
    wynik = []
    for linia in linie:
        linia = linia.strip()
        if not linia:
            continue
        try:
            w = json.loads(linia)
        except json.JSONDecodeError:
            continue
        if modelka and w.get("modelka") not in (None, modelka):
            continue
        if typ and w.get("typ") != typ:
            continue
        wynik.append(w)
    return wynik[-ile:]


def folder_referencji(slug):
    """Zdjecia persony (twarz/sylwetka) - przekazywane jako --image do Seedance."""
    folder = os.path.join(folder_modelki(slug), "referencje")
    os.makedirs(folder, exist_ok=True)
    return folder


def folder_wynikow(slug):
    folder = os.path.join(folder_modelki(slug), "wyniki")
    os.makedirs(folder, exist_ok=True)
    return folder


def folder_zdjec(slug):
    """Gotowe zdjecia persony: zdjecia_dir albo modelki/<slug>/zdjecia."""
    folder = (ustawienia_modelki(slug).get("zdjecia_dir") or "").strip() or os.path.join(folder_modelki(slug), "zdjecia")
    os.makedirs(folder, exist_ok=True)
    return folder


def folder_audio(slug):
    """Pliki glosu do lipsyncu (mp3/wav) - user wrzuca tu albo obok filmiku jako <nazwa>.audio.mp3."""
    folder = os.path.join(folder_modelki(slug), "audio")
    os.makedirs(folder, exist_ok=True)
    return folder


ROZSZERZENIA_AUDIO = (".mp3", ".wav", ".m4a", ".aac", ".ogg")
ROZSZERZENIA_OBRAZU = (".png", ".jpg", ".jpeg", ".webp")


def pliki_audio(slug):
    folder = folder_audio(slug)
    return [os.path.join(folder, n) for n in sorted(os.listdir(folder)) if n.lower().endswith(ROZSZERZENIA_AUDIO)]


def audio_dla_zrodla(zrodlo):
    """Plik glosu sparowany z klipem: <nazwa>.audio.<ext> albo <nazwa>_audio.<ext> obok filmiku, albo None."""
    if not zrodlo:
        return None
    folder, plik = os.path.split(zrodlo)
    stem = os.path.splitext(plik)[0]
    for wzor in (f"{stem}.audio", f"{stem}_audio"):
        for ext in ROZSZERZENIA_AUDIO:
            p = os.path.join(folder, wzor + ext)
            if os.path.isfile(p):
                return p
    return None


def _plik_uploadow(slug):
    return os.path.join(folder_modelki(slug), "uploady.json")


def upload_id(slug, sciezka):
    """UUID wgranego pliku z cache (modelki/<slug>/uploady.json), jesli plik sie nie zmienil. Inaczej None."""
    cache = _wczytaj_json(_plik_uploadow(slug), {})
    klucz = os.path.normcase(os.path.abspath(sciezka))
    wpis = cache.get(klucz)
    if not wpis or not os.path.isfile(sciezka):
        return None
    st = os.stat(sciezka)
    if wpis.get("size") == st.st_size and abs(wpis.get("mtime", 0) - st.st_mtime) < 1:
        return wpis.get("id")
    return None


def zapisz_upload_id(slug, sciezka, uid):
    with _rmw(_plik_uploadow(slug)):
        cache = _wczytaj_json(_plik_uploadow(slug), {})
        st = os.stat(sciezka)
        cache[os.path.normcase(os.path.abspath(sciezka))] = {"id": uid, "size": st.st_size, "mtime": st.st_mtime,
                                                             "plik": os.path.basename(sciezka), "dodano": _teraz()}
        _zapisz_json(_plik_uploadow(slug), cache)


def media_do_cli(slug, sciezki):
    """Zamienia sciezki na UUID-y z cache tam, gdzie sa (CLI przyjmuje UUID albo sciezke)."""
    return [upload_id(slug, s) or s for s in sciezki]


def sciezki_referencji(slug):
    """Lista zdjec referencyjnych: z ustawien (jesli podane) albo wszystko z folderu referencje/."""
    ust = ustawienia_modelki(slug)
    folder = folder_modelki(slug)
    wynik = []
    for r in ust.get("referencje") or []:
        p = os.path.normpath(r if os.path.isabs(r) else os.path.join(folder, r))
        if os.path.isfile(p):
            wynik.append(p)
    if not wynik:
        ref = folder_referencji(slug)
        for n in sorted(os.listdir(ref)):
            if n.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                wynik.append(os.path.join(ref, n))
    return wynik


# ---------------- szablony promptow ----------------
# Szablon to prompt z placeholderami w klamrach, np.
#   "noemi w {ubior}, {scena}, golden hour, 9:16"
# Przy uzyciu podajesz wartosci placeholderow i wychodzi gotowy prompt.

def _plik_szablonow(slug):
    return os.path.join(folder_modelki(slug), "szablony.json")


def lista_szablonow(slug):
    return _wczytaj_json(_plik_szablonow(slug), [])


def dodaj_szablon(slug, nazwa, tresc):
    plik = _plik_szablonow(slug)
    szablony = _wczytaj_json(plik, [])
    if any(s["nazwa"] == nazwa for s in szablony):
        raise ValueError(f"Szablon '{nazwa}' juz istnieje.")
    szablony.append({"nazwa": nazwa, "tresc": tresc, "dodano": _teraz()})
    _zapisz_json(plik, szablony)


def usun_szablon(slug, nazwa):
    plik = _plik_szablonow(slug)
    szablony = _wczytaj_json(plik, [])
    nowe = [s for s in szablony if s["nazwa"] != nazwa]
    if len(nowe) == len(szablony):
        raise ValueError(f"Nie ma szablonu '{nazwa}'.")
    _zapisz_json(plik, nowe)


def placeholdery_szablonu(tresc):
    """Zwraca liste unikalnych placeholderow {nazwa} w kolejnosci wystapienia."""
    widziane = []
    for m in re.finditer(r"\{([a-zA-Z0-9_]+)\}", tresc):
        if m.group(1) not in widziane:
            widziane.append(m.group(1))
    return widziane


def wypelnij_szablon(tresc, wartosci):
    """Podstawia wartosci pod placeholdery. Brakujace zostawia w klamrach."""
    wynik = tresc
    for klucz, wartosc in wartosci.items():
        wynik = wynik.replace("{" + klucz + "}", wartosc)
    return wynik


# ---------------- kolejka pomyslow ----------------

def _plik_pomyslow(slug):
    return os.path.join(folder_modelki(slug), "pomysly.json")


def lista_pomyslow(slug, status=None):
    pomysly = _wczytaj_json(_plik_pomyslow(slug), [])
    if status:
        pomysly = [p for p in pomysly if p["status"] == status]
    return pomysly


def pomysl(slug, pomysl_id):
    for p in _wczytaj_json(_plik_pomyslow(slug), []):
        if p["id"] == pomysl_id:
            return p
    raise ValueError(f"Nie ma pomyslu #{pomysl_id}.")


def _plik_pocietych(slug):
    return os.path.join(folder_modelki(slug), "pociete.json")


def jest_pociete(slug, zrodlo):
    """Dlugi filmik, ktory juz potnelismy na kawalki (skanuj go pomija)."""
    return os.path.normcase(os.path.abspath(zrodlo)) in _wczytaj_json(_plik_pocietych(slug), {})


def oznacz_pociete(slug, zrodlo, kawalki):
    with _rmw(_plik_pocietych(slug)):
        dane = _wczytaj_json(_plik_pocietych(slug), {})
        dane[os.path.normcase(os.path.abspath(zrodlo))] = {"kawalki": list(kawalki), "kiedy": _teraz()}
        _zapisz_json(_plik_pocietych(slug), dane)


def pomysl_po_zrodle(slug, zrodlo):
    """Pomysl podpiety pod dany filmik zrodlowy (zeby skanowanie nie dublowalo)."""
    cel = os.path.normcase(os.path.abspath(zrodlo))
    for p in _wczytaj_json(_plik_pomyslow(slug), []):
        z = p.get("zrodlo")
        if z and os.path.normcase(os.path.abspath(z)) == cel:
            return p
    return None


def dodaj_pomysl(slug, opis, prompt_higgsfield="", zrodlo=None, klatki=None, info_zrodla=None, stroj=None):
    """Nowy pomysl. `zrodlo` = filmik wejsciowy do Seedance Edit, `klatki` = folder z podgladem,
    `stroj` = zdjecie stroju (wariant B) albo None (strój z filmu)."""
    plik = _plik_pomyslow(slug)
    with _rmw(plik):
        return _dodaj_pomysl(plik, opis, prompt_higgsfield, zrodlo, klatki, info_zrodla, stroj)


def _dodaj_pomysl(plik, opis, prompt_higgsfield, zrodlo, klatki, info_zrodla, stroj):
    pomysly = _wczytaj_json(plik, [])
    nowy_id = (max((p["id"] for p in pomysly), default=0)) + 1
    pomysly.append({
        "id": nowy_id,
        "opis": opis,
        "prompt_higgsfield": prompt_higgsfield,
        "status": "nowy",
        "zrodlo": zrodlo,
        "stroj": stroj,
        "klatki": klatki,
        "info_zrodla": info_zrodla,
        "plik_wynikowy": None,
        "wynik_url": None,
        "job_id": None,
        "koszt": None,
        "dostawca": None,          # kto wygenerowal (higgsfield | yapper)
        "audio": audio_dla_zrodla(zrodlo),   # glos do lipsyncu sparowany z klipem (albo None)
        "lipsync_plik": None,      # wynik lipsyncu (jesli byl)
        "ocena": None,
        "notatki": "",
        "utworzono": _teraz(),
        "zaktualizowano": _teraz(),
    })
    _zapisz_json(plik, pomysly)
    return nowy_id


def pomysly_z_dnia(slug, dzien=None):
    """Pomysly wygenerowane danego dnia (domyslnie dzis) - do limitu autopilot_max_rolek_dziennie."""
    dzien = dzien or _dzis()
    return [p for p in _wczytaj_json(_plik_pomyslow(slug), [])
            if dzien_lokalny(p.get("wygenerowano")) == dzien]


def aktualizuj_pomysl(slug, pomysl_id, **pola):
    if "status" in pola and pola["status"] not in STATUSY:
        raise ValueError(f"Nieznany status '{pola['status']}'. Dozwolone: {', '.join(STATUSY)}")
    plik = _plik_pomyslow(slug)
    with _rmw(plik):
        pomysly = _wczytaj_json(plik, [])
        for p in pomysly:
            if p["id"] == pomysl_id:
                p.update(pola)
                p["zaktualizowano"] = _teraz()
                if pola.get("status") in ("wygenerowany", "gotowe") and not p.get("wygenerowano"):
                    p["wygenerowano"] = _teraz()
                _zapisz_json(plik, pomysly)
                return p
    raise ValueError(f"Nie ma pomyslu #{pomysl_id}.")


def usun_pomysl(slug, pomysl_id):
    plik = _plik_pomyslow(slug)
    with _rmw(plik):
        pomysly = _wczytaj_json(plik, [])
        nowe = [p for p in pomysly if p["id"] != pomysl_id]
        if len(nowe) == len(pomysly):
            raise ValueError(f"Nie ma pomyslu #{pomysl_id}.")
        _zapisz_json(plik, nowe)


def statystyki_pomyslow(slug):
    """Zwraca dict {status: liczba} dla wszystkich statusow."""
    pomysly = _wczytaj_json(_plik_pomyslow(slug), [])
    wynik = {s: 0 for s in STATUSY}
    for p in pomysly:
        wynik[p["status"]] = wynik.get(p["status"], 0) + 1
    return wynik


# ---------------- generacja w toku (job wyslany, jeszcze nie pobrany) ----------------
# Pomysl w trakcie generacji ma status "w_toku" i slownik `w_toku`:
#   {dostawca, model, krok (0 = dostawca persony, 1.. = zapas_nsfw), klucz (Idempotency-Key), koszt (wycena), od (czas wyslania),
#    etap: "wysylanie" (job_id jeszcze nieznany) | "czeka" (job_id znany - tylko odpytujemy), job_id, wideo_id (upload filmiku)}
# Marker jest zapisywany PRZED wyslaniem, a job_id zaraz po - po restarcie/timeoucie fabryka odpytuje ten sam job, nie wysyla nowego.

def zacznij_w_toku(slug, pomysl_id, **marker):
    """Status w_toku + marker (etap 'wysylanie', od = teraz). Zwraca pomysl."""
    marker.setdefault("etap", "wysylanie")
    marker.setdefault("od", _teraz())
    marker.setdefault("job_id", None)
    return aktualizuj_pomysl(slug, pomysl_id, status="w_toku", w_toku=marker)


def ustaw_w_toku(slug, pomysl_id, **pola):
    """Dopisuje pola do markera w_toku (np. job_id po wyslaniu, wideo_id przed wyslaniem). Zwraca pomysl."""
    with _rmw(_plik_pomyslow(slug)):
        p = pomysl(slug, pomysl_id)
        marker = dict(p.get("w_toku") or {})
        marker.update(pola)
        zmiany = {"w_toku": marker}
        if pola.get("job_id"):
            zmiany["job_id"] = pola["job_id"]
        return aktualizuj_pomysl(slug, pomysl_id, **zmiany)


def pomysly_w_toku(slug):
    """Pomysly z wyslanym (albo wysylanym) jobem - do wznowienia po restarcie panelu/autopilota."""
    return [p for p in lista_pomyslow(slug) if p.get("status") == "w_toku"]


def zapisz_probe(slug, pomysl_id, wpis):
    """Dopisuje probe do p['proby'] ({dostawca, model, job_id, status, powod, kr, czas}); proba z tym samym job_id
    jest aktualizowana, nie dublowana (wznowienie po restarcie). Zwraca pomysl."""
    with _rmw(_plik_pomyslow(slug)):
        p = pomysl(slug, pomysl_id)
        proby = list(p.get("proby") or [])
        wpis = dict(wpis)
        wpis.setdefault("czas", _teraz())
        jid = wpis.get("job_id")
        for i, w in enumerate(proby):
            if jid and w.get("job_id") == jid:
                proby[i] = {**w, **wpis}
                break
        else:
            proby.append(wpis)
        return aktualizuj_pomysl(slug, pomysl_id, proby=proby)


def koszt_w_toku(dostawca=DOSTAWCA_GLOWNY):
    """Kredyty zarezerwowane przez rolki w toku (job wyslany, jeszcze nie rozliczony) - wszystkie persony, jeden dostawca.
    Bezpieczniki dzienne licza je razem z wydatkami, zeby kilka wolnych jobow naraz nie przebilo limitu."""
    suma = 0
    for slug in lista_modelek():
        for p in pomysly_w_toku(slug):
            m = p.get("w_toku") or {}
            if (m.get("dostawca") or DOSTAWCA_GLOWNY) == (dostawca or DOSTAWCA_GLOWNY) and not rozliczony(p.get("job_id"), dostawca):
                try:
                    suma += int(m.get("koszt") or 0)
                except (TypeError, ValueError):
                    pass
    return suma


def wydano_z_rezerwa(dostawca=DOSTAWCA_GLOWNY):
    """Wydane dzis + zarezerwowane przez rolki w toku - to porownujemy z limitem dziennym."""
    return wydano_dzis(dostawca) + koszt_w_toku(dostawca)


# ---------------- blokada: jedna generacja naraz na persone (takze miedzy procesami) ----------------
# Panel (autopilot), `python fabryka.py generuj` i agent moga dzialac naraz - bez blokady dwa procesy wziely by te sama
# rolke 'nowy' i zaplacily dwa razy. Blokada pliku (msvcrt / fcntl) znika sama, gdy proces umrze.

_blokady = {}
_blokady_lock = threading.Lock()


def _zablokuj_plik(f):
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _odblokuj_plik(f):
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def blokada_generacji(slug):
    """`with blokada_generacji(slug) as moge:` - moge=False, gdy inny proces/watek generuje juz dla tej persony.
    W tym samym watku mozna wejsc ponownie (generuj -> wznow_w_toku)."""
    klucz = os.path.normcase(os.path.abspath(os.path.join(KATALOG_MODELEK, slug)))
    watek = threading.get_ident()
    with _blokady_lock:
        wpis = _blokady.get(klucz)
        if wpis and wpis["watek"] == watek:
            wpis["licznik"] += 1
            nowy = None
        elif wpis:
            nowy = False
        else:
            nowy = True
    if nowy is False:
        yield False
        return
    if nowy is None:
        try:
            yield True
        finally:
            with _blokady_lock:
                _blokady[klucz]["licznik"] -= 1
        return
    sciezka = os.path.join(folder_modelki(slug), "generacja.lock")
    f = open(sciezka, "a+")
    if not _zablokuj_plik(f):
        f.close()
        yield False
        return
    with _blokady_lock:
        _blokady[klucz] = {"watek": watek, "licznik": 1, "plik": f}
    try:
        yield True
    finally:
        with _blokady_lock:
            wpis = _blokady.get(klucz)
            wpis["licznik"] -= 1
            koniec = wpis["licznik"] <= 0
            if koniec:
                _blokady.pop(klucz, None)
        if koniec:
            _odblokuj_plik(f)
            f.close()


# ---------------- zdjecia persony ----------------

def _plik_zdjec(slug):
    return os.path.join(folder_modelki(slug), "zdjecia.json")


def lista_zdjec(slug):
    return _wczytaj_json(_plik_zdjec(slug), [])


def dodaj_zdjecie(slug, prompt, plik=None, job_id=None, koszt=None, status="gotowe", notatki="", stroj=None):
    plik_json = _plik_zdjec(slug)
    with _rmw(plik_json):
        zdjecia = _wczytaj_json(plik_json, [])
        nowy_id = (max((z["id"] for z in zdjecia), default=0)) + 1
        zdjecia.append({"id": nowy_id, "prompt": prompt, "plik": plik, "job_id": job_id, "koszt": koszt,
                        "status": status, "notatki": notatki, "stroj": stroj, "utworzono": _teraz()})
        _zapisz_json(plik_json, zdjecia)
    return nowy_id


def ustaw_zdjecie(slug, zid, **pola):
    """Zmienia pola zdjecia (pod blokada pliku)."""
    plik_json = _plik_zdjec(slug)
    with _rmw(plik_json):
        lista = _wczytaj_json(plik_json, [])
        for z in lista:
            if z["id"] == zid:
                z.update(pola)
        _zapisz_json(plik_json, lista)


def usun_zdjecie(slug, zid):
    plik_json = _plik_zdjec(slug)
    with _rmw(plik_json):
        zdjecia = _wczytaj_json(plik_json, [])
        nowe = [z for z in zdjecia if z["id"] != zid]
        if len(nowe) == len(zdjecia):
            raise ValueError(f"Nie ma zdjecia #{zid}.")
        _zapisz_json(plik_json, nowe)


def zdjecia_z_dnia(slug, dzien=None, z_niepewnymi=False):
    """Gotowe zdjecia z dnia; z_niepewnymi=True dolicza 'niepewne' (job mogl powstac mimo bledu - autopilot nie robi wtedy
    kolejnego, zeby nie zaplacic drugi raz)."""
    dzien = dzien or _dzis()
    statusy = ("gotowe", "niepewne") if z_niepewnymi else ("gotowe",)
    return [z for z in lista_zdjec(slug) if z["status"] in statusy and dzien_lokalny(z.get("utworzono")) == dzien]


def prompty_zdjec(slug):
    """Lista promptow zdjec z pliku zdjecia_prompty (jedna linia = jeden prompt; '#' = komentarz)."""
    wartosc = (ustawienia_modelki(slug).get("zdjecia_prompty") or "").strip()
    if not wartosc:
        return []
    sciezka = _sciezka_w_modelce(slug, wartosc)
    if not os.path.isfile(sciezka):
        return []
    with open(sciezka, encoding="utf-8-sig") as f:
        return [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]


def nastepny_prompt_zdjecia(slug):
    """Kolejny prompt zdjecia (w kolko). Zwraca (prompt, indeks) albo (None, 0)."""
    prompty = prompty_zdjec(slug)
    if not prompty:
        return None, 0
    plik = os.path.join(folder_modelki(slug), "zdjecia_stan.json")
    with _rmw(plik):
        stan = _wczytaj_json(plik, {"indeks": 0})
        i = int(stan.get("indeks", 0)) % len(prompty)
        stan["indeks"] = i + 1          # w tym samym pliku siedzi tez licznik strojow (zdjecia._nastepny_stroj) - nie nadpisuj
        _zapisz_json(plik, stan)
    return prompty[i], i


# ---------------- stan autopilota (hamulec, wyslane na telefon) ----------------

def _plik_autopilota(slug):
    return os.path.join(folder_modelki(slug), "autopilot_stan.json")


def autopilot_stan(slug):
    dane = {"bledy_z_rzedu": 0, "pauza": None, "pauza_od": None}
    dane.update(_wczytaj_json(_plik_autopilota(slug), {}))
    return dane


def zapisz_autopilot_stan(slug, **pola):
    with _rmw(_plik_autopilota(slug)):
        dane = autopilot_stan(slug)
        dane.update(pola)
        _zapisz_json(_plik_autopilota(slug), dane)
    return dane


def autopilot_pauza(slug, powod):
    return zapisz_autopilot_stan(slug, pauza=str(powod), pauza_od=_teraz())


def autopilot_wznow(slug):
    return zapisz_autopilot_stan(slug, pauza=None, pauza_od=None, bledy_z_rzedu=0)


# ---------------- lipsync ----------------

def _plik_lipsync(slug):
    return os.path.join(folder_modelki(slug), "lipsync.json")


def lista_lipsync(slug):
    return _wczytaj_json(_plik_lipsync(slug), [])


def dodaj_lipsync(slug, wideo, audio, dostawca, model, pomysl_id=None):
    plik = _plik_lipsync(slug)
    with _rmw(plik):
        lista = _wczytaj_json(plik, [])
        nowy_id = (max((l["id"] for l in lista), default=0)) + 1
        lista.append({"id": nowy_id, "wideo": wideo, "audio": audio, "dostawca": dostawca, "model": model,
                      "pomysl_id": pomysl_id, "job_id": None, "status": "nowy", "plik_wynikowy": None,
                      "koszt": None, "notatki": "", "utworzono": _teraz(), "zaktualizowano": _teraz()})
        _zapisz_json(plik, lista)
    return nowy_id


def aktualizuj_lipsync(slug, lid, **pola):
    plik = _plik_lipsync(slug)
    with _rmw(plik):
        lista = _wczytaj_json(plik, [])
        for l in lista:
            if l["id"] == lid:
                l.update(pola)
                l["zaktualizowano"] = _teraz()
                _zapisz_json(plik, lista)
                return l
    raise ValueError(f"Nie ma lipsyncu #{lid}.")


def usun_lipsync(slug, lid):
    plik = _plik_lipsync(slug)
    with _rmw(plik):
        lista = _wczytaj_json(plik, [])
        nowe = [l for l in lista if l["id"] != lid]
        if len(nowe) == len(lista):
            raise ValueError(f"Nie ma lipsyncu #{lid}.")
        _zapisz_json(plik, nowe)


# ---------------- bank tekstow ----------------

def _plik_tekstow(slug):
    return os.path.join(folder_modelki(slug), "teksty.json")


def _plik_uzytych(slug):
    return os.path.join(folder_modelki(slug), "uzyte_tekstow.json")


def dodaj_teksty(slug, teksty, zrodlo=""):
    """Dodaje teksty do banku, pomijajac puste i duplikaty (juz w banku).

    teksty: lista stringow (np. wklejone podpisy z Twojego profilu IG).
    Zwraca liczbe faktycznie dodanych pozycji.
    """
    plik = _plik_tekstow(slug)
    with _rmw(plik):
        bank = _wczytaj_json(plik, [])
        juz_w_banku = {w["tekst"] for w in bank}
        dodane = 0
        for t in teksty:
            t = t.strip()
            if t and t not in juz_w_banku:
                bank.append({"tekst": t, "zrodlo": zrodlo, "dodano": _teraz()})
                juz_w_banku.add(t)
                dodane += 1
        _zapisz_json(plik, bank)
    return dodane


def dodaj_teksty_z_pliku(slug, sciezka, zrodlo=""):
    """Wczytuje teksty z pliku .txt (jeden tekst = jedna linia; puste linie pomijane).

    Teksty wielolinijkowe oddzielaj pusta linia i uzyj separatora '---' w linii,
    zeby skleic kilka linii w jeden tekst.
    """
    with open(sciezka, encoding="utf-8-sig") as f:
        zawartosc = f.read()

    if "---" in zawartosc:
        teksty = [blok.strip() for blok in zawartosc.split("---")]
    else:
        teksty = zawartosc.splitlines()
    return dodaj_teksty(slug, teksty, zrodlo or os.path.basename(sciezka))


def lista_tekstow(slug):
    return _wczytaj_json(_plik_tekstow(slug), [])


def statystyki_tekstow(slug):
    """Zwraca (nieuzyte, wszystkie) - ile tekstow zostalo w banku."""
    bank = _wczytaj_json(_plik_tekstow(slug), [])
    uzyte = set(_wczytaj_json(_plik_uzytych(slug), []))
    nieuzyte = sum(1 for w in bank if w["tekst"] not in uzyte)
    return nieuzyte, len(bank)


def losuj_tekst(slug):
    """Zwraca pierwszy jeszcze nieuzyty tekst i oznacza go jako uzyty."""
    with _rmw(_plik_uzytych(slug)):
        bank = _wczytaj_json(_plik_tekstow(slug), [])
        uzyte = set(_wczytaj_json(_plik_uzytych(slug), []))
        for wpis in bank:
            if wpis["tekst"] not in uzyte:
                uzyte.add(wpis["tekst"])
                _zapisz_json(_plik_uzytych(slug), sorted(uzyte))
                return wpis["tekst"]
    return None
