# -*- coding: utf-8 -*-
"""Warstwa danych: modelki (persony), kolejka pomyslow, bank tekstow."""
import json
import os
import re
from datetime import datetime, timezone

KATALOG_SKRYPTU = os.path.dirname(os.path.abspath(__file__))
# ROLKI_MODELKI pozwala trzymac dane gdzie indziej (np. na D:) albo odpalac testy na boku.
KATALOG_MODELEK = os.environ.get("ROLKI_MODELKI") or os.path.join(KATALOG_SKRYPTU, "modelki")
PLIK_STANU = os.path.join(KATALOG_MODELEK, "..", "stan.json") if os.environ.get("ROLKI_MODELKI") \
    else os.path.join(KATALOG_SKRYPTU, "stan.json")

STATUSY = ["nowy", "wygenerowany", "postprodukcja", "gotowe", "blad"]

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
    "powtorki": 2,                  # ile razy powtorzyc, gdy Seedance odrzuci (kredyty wracaja)
    "zrodla_dir": "",               # wrzutnia poza projektem, np. C:\Users\yux\Desktop\ROLKI AI\przed\noemi ("" = modelki/<slug>/zrodla)
    "wyniki_dir": "",               # gotowe rolki poza projektem, np. ...\ROLKI AI\po\noemi ("" = modelki/<slug>/wyniki)
    "mediatool": True,              # po generacji przepusc wideo przez Media Tool (iPhone meta, GPS, spoof)
    "warianty": 0,                  # ile wariantow VideoRemixer po generacji (0 = pomin)
    "dodatkowe_parametry": {},      # cokolwiek ekstra dla CLI, np. {"seed": 42}
}

# Budzet wspolny dla wszystkich modelek (kredyty sa jedne na konto): rolki-ai/budzet.json
PLIK_BUDZETU = os.path.join(os.path.dirname(PLIK_STANU), "budzet.json")
BUDZET_DOMYSLNY = {"max_kredyty_dziennie": 300, "wydatki": {}}


def _teraz():
    return datetime.now(timezone.utc).isoformat()


def _wczytaj_json(sciezka, domyslnie):
    if os.path.isfile(sciezka):
        with open(sciezka, encoding="utf-8") as f:
            return json.load(f)
    return domyslnie


def _zapisz_json(sciezka, dane):
    os.makedirs(os.path.dirname(sciezka), exist_ok=True)
    with open(sciezka, "w", encoding="utf-8") as f:
        json.dump(dane, f, ensure_ascii=False, indent=2)


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
        if os.path.isdir(os.path.join(KATALOG_MODELEK, n))
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
    _zapisz_json(os.path.join(folder, "ustawienia.json"), dict(USTAWIENIA_DOMYSLNE))
    _zapisz_json(os.path.join(folder, "pomysly.json"), [])
    _zapisz_json(os.path.join(folder, "teksty.json"), [])
    _zapisz_json(os.path.join(folder, "uzyte_tekstow.json"), [])
    _zapisz_json(os.path.join(folder, "szablony.json"), [])
    _zapisz_json(os.path.join(folder, "profil.json"), {
        "nazwa": nazwa,
        "instagram": "",
        "opis_stylu": "",
        "cechy": [],
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
    return _wczytaj_json(_plik_profilu(slug), {
        "nazwa": slug, "instagram": "", "opis_stylu": "", "cechy": [],
    })


def zapisz_profil(slug, **pola):
    profil = profil_modelki(slug)
    profil.update(pola)
    _zapisz_json(_plik_profilu(slug), profil)
    return profil


# ---------------- ustawienia generacji ----------------

def _plik_ustawien(slug):
    return os.path.join(folder_modelki(slug), "ustawienia.json")


def ustawienia_modelki(slug):
    """Ustawienia generacji z domyslnymi uzupelnionymi (stare modelki bez pliku tez dzialaja)."""
    dane = dict(USTAWIENIA_DOMYSLNE)
    dane.update(_wczytaj_json(_plik_ustawien(slug), {}))
    return dane


def zapisz_ustawienia(slug, **pola):
    nieznane = [k for k in pola if k not in USTAWIENIA_DOMYSLNE]
    if nieznane:
        raise ValueError(f"Nieznane ustawienia: {', '.join(nieznane)}. "
                         f"Dozwolone: {', '.join(USTAWIENIA_DOMYSLNE)}")
    dane = ustawienia_modelki(slug)
    dane.update(pola)
    _zapisz_json(_plik_ustawien(slug), dane)
    return dane


def _sciezka_w_modelce(slug, wartosc):
    return wartosc if os.path.isabs(wartosc) else os.path.join(folder_modelki(slug), wartosc)


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


# ---------------- budzet dzienny (wspolny) ----------------

def budzet():
    dane = dict(BUDZET_DOMYSLNY)
    dane.update(_wczytaj_json(PLIK_BUDZETU, {}))
    dane.setdefault("wydatki", {})
    return dane


def zapisz_budzet(**pola):
    dane = budzet()
    dane.update(pola)
    _zapisz_json(PLIK_BUDZETU, dane)
    return dane


def wydano_dzis():
    return int(budzet()["wydatki"].get(datetime.now().strftime("%Y-%m-%d"), 0))


def dopisz_wydatek(kredyty):
    """Dopisuje faktycznie zuzyte kredyty do dzisiejszego dnia (ujemne/zero ignorowane)."""
    kredyty = int(kredyty)
    if kredyty <= 0:
        return wydano_dzis()
    dane = budzet()
    dzis = datetime.now().strftime("%Y-%m-%d")
    dane["wydatki"][dzis] = int(dane["wydatki"].get(dzis, 0)) + kredyty
    # trzymaj tylko ostatnie 60 dni
    for k in sorted(dane["wydatki"])[:-60]:
        dane["wydatki"].pop(k, None)
    _zapisz_json(PLIK_BUDZETU, dane)
    return dane["wydatki"][dzis]


def folder_referencji(slug):
    """Zdjecia persony (twarz/sylwetka) - przekazywane jako --image do Seedance."""
    folder = os.path.join(folder_modelki(slug), "referencje")
    os.makedirs(folder, exist_ok=True)
    return folder


def folder_wynikow(slug):
    folder = os.path.join(folder_modelki(slug), "wyniki")
    os.makedirs(folder, exist_ok=True)
    return folder


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
        p = r if os.path.isabs(r) else os.path.join(folder, r)
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
        "ocena": None,
        "notatki": "",
        "utworzono": _teraz(),
        "zaktualizowano": _teraz(),
    })
    _zapisz_json(plik, pomysly)
    return nowy_id


def aktualizuj_pomysl(slug, pomysl_id, **pola):
    if "status" in pola and pola["status"] not in STATUSY:
        raise ValueError(f"Nieznany status '{pola['status']}'. Dozwolone: {', '.join(STATUSY)}")
    plik = _plik_pomyslow(slug)
    pomysly = _wczytaj_json(plik, [])
    for p in pomysly:
        if p["id"] == pomysl_id:
            p.update(pola)
            p["zaktualizowano"] = _teraz()
            _zapisz_json(plik, pomysly)
            return p
    raise ValueError(f"Nie ma pomyslu #{pomysl_id}.")


def usun_pomysl(slug, pomysl_id):
    plik = _plik_pomyslow(slug)
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
    bank = _wczytaj_json(_plik_tekstow(slug), [])
    uzyte = set(_wczytaj_json(_plik_uzytych(slug), []))
    for wpis in bank:
        if wpis["tekst"] not in uzyte:
            uzyte.add(wpis["tekst"])
            _zapisz_json(_plik_uzytych(slug), sorted(uzyte))
            return wpis["tekst"]
    return None
