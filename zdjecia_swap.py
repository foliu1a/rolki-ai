# -*- coding: utf-8 -*-
"""Zdjecia "character swap" (panel 3.2, strona Zdjecia): user wstawia zdjecie, persona zajmuje miejsce osoby na nim.

    katalog(slug)                          -> modele z chipami wg schematu, domyslne (dla panelu)
    zapisz_zrodlo(slug, plik, nazwa)       -> wstawione zdjecie: kopia obrocona wg EXIF, bez metadanych -> swap_zrodla/
    zbuduj(slug, zrodlo, opcje)            -> prompt + obrazy (kolejnosc!) + parametry modelu (zero wysylania)
    wycena(slug, opcje, zrodlo)            -> cena z `generate cost` (darmowe, BEZ mediow, cache po parametrach) + bezpieczniki
    zlec(slug, zrodlo, opcje, kr)          -> 3.3: "Generuj" = N wpisow w kolejce (rezerwacja limitu atomowo), nic nie wysyla;
                                              KOLEJKA (dyspozytor panelu w tle) wysyla je rownolegle, max `zdjecia_rownolegle`
    generuj(slug, zrodlo, opcje, kr)       -> CLI/testy: zlec + obsluga tych zdjec do konca (rownolegle), pelne zabezpieczenie pieniedzy
    zatrzymaj()                            -> STOP strony Zdjecia: kolejka anulowana, przyjete joby dokoncza sie przy nastepnym sprawdzeniu
    wznow_w_toku(slug) / wznow_wszystkie() -> dokancza zdjecia w toku (ten sam job, nic nie wysyla drugi raz)

Obrazy (prompt mowi "image N" + "the first / the last image"): 1 = wstawione zdjecie (kadr, poza, tlo, swiatlo, aparat, mimika,
a przy "ze zdjecia" takze ubranie), 2..R+1 = WSZYSTKIE referencje persony (01_, 02_...), na koncu (opcjonalnie) stroj z
biblioteki - z niego tylko ubranie. Tozsamosc (twarz, skora, oczy, piercing, tatuaze persony) = scenariusz.tozsamosc, wlosy =
profil.wlosy, sylwetka = profil.sylwetka (mocno: "highest priority after her face"), wzrost = profil.wzrost_cm. Tekst promptu
bez slow z fabryka.SLOWA_RYZYKOWNE (filtr NSFW) - opisy persony i dopisek przechodza przez bez_slow_ryzykownych().

Pieniadze jak w rolkach: wpis w zdjecia.json (status w_toku + znacznik) PRZED wyslaniem; wszystkie pliki wgrane przed
'wysylam' (wstawione zdjecie swiezym uploadem - jego id odnajduje job na `generate list --image`); create bez --wait, job_id
zapisany od razu, potem `generate get`; po 'wysylam' NIGDY drugi create (blad = szukamy joba, nie ma = czeka 60 min, potem
"sprawdz w apce"); limit dzienny Higgsfield wspolny (z rezerwa w toku i w kolejce; rezerwacja przy "Generuj" atomowa); jeden
wlasciciel zdjecia (baza.BlokadaZdjecia, takze miedzy procesami) zamiast blokady generacji persony - zdjecia nie czekaja na
rolki; przed kazdym wyslaniem cena jeszcze raz - wyzsza niz zatwierdzona = nic nie idzie. Ceny obrazow sa ulamkowe (Seedream
5.0 Pro 2K = 2,5 kr) - do limitu dnia liczymy w gore (3 kr). Wynik: zdjecia_dir persony, NNN_swap_<nazwa zrodla>.<ext>, bez
obrobki (jak zdjecia).
"""
import itertools
import math
import os
import re
import shutil
import threading
import time
import traceback

import baza
import dostawcy
import fabryka
import scenariusz

# ---------------- modele (najlepsze do pelnej podmiany postaci na zdjeciu z referencjami) ----------------
# Schematy w ksztalcie `model get --json` (params z enum + rules), sprawdzone na CLI 1.1.26 2026-10-07. Chipy w panelu biora z
# nich proporcje / jakosc / rozdzielczosc - opcja, ktorej model nie ma, znika. Panel przy starcie odswieza je z CLI (darmowe
# `model get`, odswiez_schematy); bez CLI zostaje ta kopia. Ceny `generate cost` 2026-10-07 (liczba zdjec nie zmienia ceny):
#   seedream_v5_pro 1k/1.5k 1.25, 2k 2.5 | nano_banana_pro 1k 2, 2k 2, 4k 4 | gpt_image_2_5 high 1k 1.5, 2k 2.75, 4k 4.25
#   (low 2k 0.5, medium 2k 1, xhigh 2k 4.5, max 2k 9) | gpt_image_2 (od 2026-10-08) medium 1k/2k/4k 1/2/2.5, high 3.5/6.5/11
#   | dla porownania nano_banana_flash 2k 2 (tyle co Pro).
MODELE = {
    "seedream_v5_pro": {
        "nazwa": "Seedream 5.0 Pro",
        "opis": "najwierniejsza twarz (polecany)",
        "schemat": {"params": [
            {"name": "aspect_ratio", "enum": ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9"]},
            {"name": "resolution", "enum": ["1k", "1.5k", "2k"]}],
            "rules": [{"cel": "size(params.image_references) <= 10"}]},
    },
    "nano_banana_pro": {
        "nazwa": "Nano Banana Pro",
        "opis": "najwyższa jakość, do 4K",
        "schemat": {"params": [
            {"name": "aspect_ratio", "enum": ["1:1", "3:2", "2:3", "4:3", "3:4", "4:5", "5:4", "9:16", "16:9", "21:9"]},
            {"name": "resolution", "enum": ["1k", "2k", "4k"]}],
            "rules": [{"cel": "size(params.image_references) <= 14"}]},
    },
    "gpt_image_2_5": {
        "nazwa": "GPT Image 2.5",
        "opis": "ostre detale, jakość do wyboru",
        "schemat": {"params": [
            {"name": "aspect_ratio", "enum": ["auto", "1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16", "21:9", "27:16", "16:27",
                                              "9:8", "8:9", "4:5", "5:4"]},
            {"name": "quality", "enum": ["low", "medium", "high", "xhigh", "max"]},
            {"name": "resolution", "enum": ["1k", "2k", "4k"]}],
            "rules": []},
    },
    # na prosbe usera 2026-10-08 (tego uzywa w apce Higgsfield); drozszy od 2.5 (high 2k 6.5 kr), schemat z `model get` 2026-10-08
    "gpt_image_2": {
        "nazwa": "GPT Image 2",
        "opis": "ten z apki Higgsfield",
        "schemat": {"params": [
            {"name": "aspect_ratio", "enum": ["auto", "1:1", "4:3", "3:4", "16:9", "21:9", "9:16", "3:2", "2:3", "4:5", "5:4"]},
            {"name": "quality", "enum": ["low", "medium", "high"]},
            {"name": "resolution", "enum": ["1k", "2k", "4k"]}],
            "rules": []},
    },
}
# Domyslny: Seedream 5.0 Pro - dokumentacja Higgsfield (skill higgsfield-generate, model-catalog) kieruje tu "one-shot face from
# reference photos / face edit on a real photo" ("Faces, character sheets, and complex scene edits with faces", do 10 referencji).
MODEL_DOMYSLNY = "seedream_v5_pro"

PROPORCJE = ("9:16", "2:3", "3:4", "4:5", "1:1", "5:4", "4:3", "3:2", "16:9", "21:9")   # kolejnosc w panelu (pion najpierw)
JAK_ZDJECIE = "jak_zdjecie"           # proporcje najblizsze wstawionemu zdjeciu (domyslnie)
STROJ_ZE_ZDJECIA = "ze_zdjecia"       # persona w ubraniu z wstawionego zdjecia (domyslnie)
JAKOSCI = {"low": "Niska", "medium": "Średnia", "high": "Wysoka", "xhigh": "Bardzo wysoka", "max": "Maksymalna"}
MAX_ILE = 4
MAX_BOK_ZRODLA = 3072                 # dluzszy bok wstawionego zdjecia (wieksze nic nie daje modelom 1-4K, a wolniej sie wgrywa)
MAX_DOPISKU = 300
CZAS_NA_ZDJECIE = "15m"               # tyle czekamy na job; dluzej = zdjecie zostaje w toku i dokonczymy je pozniej
ODSTEP_S = 5                          # co ile sprawdzamy job (`generate get`, 0 kr)
CENA_WAZNA_S = 3600                   # cache wyceny po parametrach (cena obrazu nie zalezy od zdjec ani promptu)
PROMPT_WYCENY = "price check"         # `generate cost` wymaga promptu - cena od niego nie zalezy

_schematy = {}                        # model -> schemat z CLI (odswiez_schematy)
_ceny = {}                            # (model, parametry...) -> (czas, kr)
_lock = threading.Lock()


def _log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def _zdarzenie(log, slug, typ, tekst, **dane):
    (log or _log)(tekst)
    try:
        baza.dziennik_zapisz(typ, tekst, modelka=slug, **dane)
    except OSError:
        pass


def _kr(k):
    """2.5 -> '2,5 kr', 3 -> '3 kr'."""
    if k is None:
        return "? kr"
    return f"{float(k):g}".replace(".", ",") + " kr"


def do_limitu(k):
    """Cena zdjecia (ulamkowa) -> kredyty do limitu dnia i rezerwy: w gore (2.5 -> 3)."""
    return int(math.ceil(float(k or 0) - 1e-9))


# ---------------- schematy i chipy ----------------

def schemat(model):
    """Schemat modelu: odswiezony z CLI (gdy panel go pobral) albo kopia z MODELE."""
    with _lock:
        s = _schematy.get(model)
    return s or MODELE[model]["schemat"]


def odswiez_schematy(log=None):
    """Darmowe `model get` dla modeli swapa -> chipy wg aktualnego schematu Higgsfielda. Blad = zostaje kopia z kodu."""
    import higgsfield_cli as hf
    ile = 0
    for m in MODELE:
        try:
            s = hf.model(m)
        except (hf.HiggsfieldBlad, OSError, ValueError) as e:
            if log:
                log(f"swap: schemat {m} z CLI nie przyszedl ({e}) - zostaje kopia z kodu")
            continue
        if isinstance(s, dict) and isinstance(s.get("params"), list) and chipy(s)["proporcje"]:
            with _lock:
                _schematy[m] = s
            ile += 1
    return ile


def _najlepsza(lista, chce):
    if not lista:
        return None
    return chce if chce in lista else lista[-1]


def chipy(schemat_modelu):
    """Schemat (`model get --json`) -> co da sie wybrac w panelu: proporcje (znane, bez 'auto'), jakosc i rozdzielczosc (pusta lista
    = model nie ma tej opcji, chip znika), max_obrazow (z regul, bez inpaint), domyslne (wysoka jakosc, 2K)."""
    params = {str(p.get("name")): p for p in ((schemat_modelu or {}).get("params") or []) if isinstance(p, dict)}

    def enum(nazwa):
        return [str(v) for v in ((params.get(nazwa) or {}).get("enum") or []) if v is not None]
    proporcje = [p for p in PROPORCJE if p in enum("aspect_ratio")]
    jakosc, rozdz = enum("quality"), enum("resolution")
    max_obr = None
    for r in (schemat_modelu or {}).get("rules") or []:
        cel = str((r or {}).get("cel") or "") if isinstance(r, dict) else ""
        m = re.search(r"size\(params\.image_references\)\s*<=\s*(\d+)", cel)
        if m and "is_inpaint" not in cel:
            max_obr = int(m.group(1)) if max_obr is None else min(max_obr, int(m.group(1)))
    return {"proporcje": proporcje, "jakosc": jakosc, "rozdzielczosc": rozdz, "max_obrazow": max_obr,
            "domyslne": {"jakosc": _najlepsza(jakosc, "high"), "rozdzielczosc": _najlepsza(rozdz, "2k")}}


def etykieta_rozdzielczosci(r):
    return str(r).upper().replace(".", ",")      # 1.5k -> 1,5K


def katalog(slug=None):
    """Dla panelu: modele (id, nazwa, opis, chipy wg schematu, domyslne), domyslne wybory, persona."""
    modele = []
    for m, info in MODELE.items():
        ch = chipy(schemat(m))
        modele.append({"id": m, "nazwa": info["nazwa"], "opis": info["opis"], "proporcje": ch["proporcje"],
                       "jakosc": [[q, JAKOSCI.get(q, q)] for q in ch["jakosc"]],
                       "rozdzielczosc": [[r, etykieta_rozdzielczosci(r)] for r in ch["rozdzielczosc"]],
                       "max_obrazow": ch["max_obrazow"], "domyslne": ch["domyslne"]})
    wynik = {"modele": modele, "model_domyslny": MODEL_DOMYSLNY, "jak_zdjecie": JAK_ZDJECIE, "stroj_ze_zdjecia": STROJ_ZE_ZDJECIA,
             "max_ile": MAX_ILE, "max_dopisku": MAX_DOPISKU,
             "domyslne": {"model": MODEL_DOMYSLNY, "proporcje": JAK_ZDJECIE, "ile": 1, "stroj": STROJ_ZE_ZDJECIA}}
    if slug:
        prof = baza.profil_modelki(slug)
        wynik["persona"] = {"slug": slug, "nazwa": prof.get("nazwa") or slug, "referencje": len(baza.sciezki_referencji(slug)),
                            "sylwetka": bool((prof.get("sylwetka") or "").strip()), "wlosy": bool((prof.get("wlosy") or "").strip())}
    return wynik


# ---------------- wstawione zdjecie: wymiary, proporcje, kopia bez EXIF ----------------

def wymiary(plik):
    """(szerokosc, wysokosc) zdjecia tak, jak je widac - po obrocie wg EXIF (telefony zapisuja pion jako poziom + znacznik)."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(plik) as im:
            w, h = im.size
            try:
                orientacja = im.getexif().get(0x0112)
            except Exception:       # uszkodzony EXIF nie moze zablokowac zdjecia
                orientacja = None
    except (OSError, ValueError):
        return None
    return (h, w) if orientacja in (5, 6, 7, 8) else (w, h)


def _ulamek(proporcje):
    a, b = str(proporcje).split(":")
    return float(a) / float(b)


def najblizsze_proporcje(szer, wys, dostepne):
    """Proporcje z listy `dostepne` najblizsze zdjeciu szer x wys (odleglosc w logarytmie: 4:5 vs 3:4 i 1:1 liczy sie uczciwie)."""
    if not (szer and wys and dostepne):
        return None
    r = math.log(float(szer) / float(wys))
    return min(dostepne, key=lambda p: abs(math.log(_ulamek(p)) - r))


def _bezpieczna_nazwa(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s or "").strip("_.") or "zdjecie"


_PREFIKS_CZASU = re.compile(r"^\d{8}_\d{6}(?:_\d+)?_")


def nazwa_zrodla(plik):
    """swap_zrodla/20261007_231500_IMG_1234.jpg -> 'IMG_1234' (nazwa, jaka wstawil user - do nazwy wyniku)."""
    stem = os.path.splitext(os.path.basename(str(plik or "")))[0]
    return _bezpieczna_nazwa(_PREFIKS_CZASU.sub("", stem))[:60]


def zapisz_zrodlo(slug, zrodlo, nazwa=None, folder=None):
    """Wstawione zdjecie -> modelki/<slug>/swap_zrodla/<czas>_<nazwa>.jpg|png: obrocone wg EXIF, bez metadanych (GPS z telefonu nie
    leci do Higgsfielda), dluzszy bok max MAX_BOK_ZRODLA. zrodlo = sciezka albo plik-strumien. ValueError = to nie jest zdjecie.
    Nic nie wysyla - to tylko lokalna kopia. folder (3.5): inny cel kopii (tla usera do pierwszej klatki: modelki/<slug>/tla_kopie)."""
    nazwa = nazwa or (zrodlo if isinstance(zrodlo, str) else "zdjecie.jpg")
    stem = _bezpieczna_nazwa(os.path.splitext(os.path.basename(str(nazwa)))[0])[:60]
    folder = folder or baza.folder_swap_zrodel(slug)
    try:
        from PIL import Image, ImageOps
    except ImportError:
        Image = None
    if Image is None:
        rozsz = os.path.splitext(str(nazwa))[1].lower()
        if rozsz not in baza.ROZSZERZENIA_OBRAZU:
            raise ValueError("To nie jest zdjecie (png, jpg, webp).")
        cel = _wolna_nazwa(folder, stem, rozsz)
        if isinstance(zrodlo, str):
            shutil.copyfile(zrodlo, cel)
        else:
            with open(cel, "wb") as f:
                shutil.copyfileobj(zrodlo, f)
        return cel
    try:
        with Image.open(zrodlo) as src:
            src.load()
            icc = src.info.get("icc_profile")      # profil kolorow (iPhone: Display P3) zostaje - to nie sa dane osobowe
            try:
                im = ImageOps.exif_transpose(src)
            except Exception:                    # uszkodzony EXIF: zdjecie bez obrotu
                im = src.copy()
    except Exception as e:      # PIL rzuca rozne wyjatki dla nie-zdjec (UnidentifiedImageError, DecompressionBombError...)
        raise ValueError(f"To nie jest zdjecie, ktore umiem otworzyc (png, jpg, webp): {e}")
    if max(im.size) > MAX_BOK_ZRODLA:
        im.thumbnail((MAX_BOK_ZRODLA, MAX_BOK_ZRODLA), Image.LANCZOS)
    alfa = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
    dodatki = {"icc_profile": icc} if icc else {}
    # zapis BEZ exif (GPS, model telefonu, data) - Pillow zapisuje tylko to, co dostanie w argumentach
    if alfa:
        cel = _wolna_nazwa(folder, stem, ".png")
        im.convert("RGBA").save(cel, "PNG", **dodatki)
    else:
        cel = _wolna_nazwa(folder, stem, ".jpg")
        im.convert("RGB").save(cel, "JPEG", quality=95, **dodatki)
    return cel


def _wolna_nazwa(folder, stem, rozsz):
    baza_nazwy = f"{time.strftime('%Y%m%d_%H%M%S')}_{stem}"
    cel = os.path.join(folder, baza_nazwy + rozsz)
    n = 2
    while os.path.exists(cel):
        cel = os.path.join(folder, f"{time.strftime('%Y%m%d_%H%M%S')}_{n}_{stem}{rozsz}")
        n += 1
    return cel


# ---------------- slowa, ktore lubi blokowac filtr NSFW ----------------
# Opisy persony (prompt A, profil) i dopisek usera ida do promptu - slowa z fabryka.SLOWA_RYZYKOWNE zamieniamy na neutralne
# (puste = slowo wypada). Dlugie frazy najpierw; '-' jest czescia slowa jak w sprawdzaniu (lace-up to nie lace).
ZAMIANY_SLOW = {
    "sexy": "striking", "seductive": "confident", "sensual": "soft", "erotic": "", "erotica": "", "lingerie": "fitted top",
    "underwear": "basics", "bikini": "two-piece outfit", "swimsuit": "one-piece outfit", "nude": "beige", "naked": "bare",
    "topless": "", "see-through": "light", "see through": "light", "sheer": "light", "transparent": "light", "mesh": "openwork",
    "fishnet": "diamond-net", "cleavage": "neckline", "bra": "top", "panties": "shorts", "thong": "shorts", "breast": "bust",
    "breasts": "bust", "boobs": "bust", "nipple": "", "nipples": "", "butt": "bottom", "ass": "bottom", "booty": "bottom",
    "twerk": "dance", "twerking": "dancing", "provocative": "bold", "wet t-shirt": "t-shirt", "lace": "openwork",
    "latex": "glossy vinyl", "bodysuit": "fitted one-piece top", "strip": "band", "stripper": "dancer", "lick": "", "licking": "",
    "moan": "", "kiss": "smile", "bedroom": "room", "shower": "", "bath": "", "lap dance": "dance", "pole dance": "dance",
    "hot girl": "young woman", "curvy": "full-figured", "curves": "figure", "tight dress": "fitted dress",
    "mini skirt": "very short skirt", "skimpy": "short",
}


def slowa_ryzykowne(tekst):
    """Slowa z fabryka.SLOWA_RYZYKOWNE w tekscie - tak samo jak sprawdza je fabryka (wskazowki_nsfw)."""
    t = f" {re.sub(r'[^a-z0-9 -]+', ' ', (tekst or '').lower())} "
    t = re.sub(r" +", " ", t)
    return [s for s in fabryka.SLOWA_RYZYKOWNE if f" {s} " in t or f" {s}s " in t]


def bez_slow_ryzykownych(tekst):
    """(tekst bez slow z fabryka.SLOWA_RYZYKOWNE, [zamienione slowa])."""
    wynik, zmienione = tekst or "", []
    for slowo in sorted(fabryka.SLOWA_RYZYKOWNE, key=len, reverse=True):
        czesci = [re.escape(c) for c in re.split(r"[\s-]+", slowo) if c]
        wzor = re.compile(r"(?<![\w-])" + r"[\s-]+".join(czesci) + r"(?:e?s)?(?![\w-])", re.I)
        if wzor.search(wynik):
            zmienione.append(slowo)
            wynik = wzor.sub(ZAMIANY_SLOW.get(slowo, ""), wynik)
    if zmienione:
        wynik = re.sub(r"[ \t]{2,}", " ", wynik)
        wynik = re.sub(r"\s+([,.;:])", r"\1", wynik)
        wynik = re.sub(r"([,;:])\s*(?=[,;:.])", "", wynik)
    return wynik.strip(), zmienione


# ---------------- prompt ----------------

_TOKENY = re.compile(r"<<<image_(\d+)>>>|@\[Image\s*(\d+)\]\(image_\d+\)|@Image\s*(\d+)", re.I)


def _numery_obrazow(tekst, przesun):
    """Numery zdjec persony z promptu A (<<<image_4>>>, @[Image 4](image_4)) -> 'image 5' (wstawione zdjecie jest pierwsze)."""
    return _TOKENY.sub(lambda m: f"image {int(next(g for g in m.groups() if g)) + przesun}", tekst or "")


def _obrazy_tekst(od, do):
    if do <= od:
        return f"image {od}"
    if do == od + 1:
        return f"images {od} and {do}"
    return f"images {od}-{do}"


def _ile(v):
    try:
        return max(1, min(MAX_ILE, int(v or 1)))
    except (TypeError, ValueError):
        return 1


def _parametry(o, zrodlo=None):
    """Opcje z panelu/CLI -> (model, parametry modelu {aspect_ratio, resolution, quality?}, info o proporcjach). Wartosci spoza
    schematu modelu = ValueError (nic nie idzie z parametrem, ktorego model nie zna)."""
    model = (o.get("model") or MODEL_DOMYSLNY).strip()
    if model not in MODELE:
        raise ValueError(f"Nieznany model '{model}'. Do wyboru: {', '.join(MODELE)}.")
    nazwa = MODELE[model]["nazwa"]
    ch = chipy(schemat(model))
    prop = (o.get("proporcje") or JAK_ZDJECIE).strip()
    info = {"jak_zdjecie": prop == JAK_ZDJECIE, "wymiary": None, "zgadniete": False}
    if prop == JAK_ZDJECIE:
        wym = wymiary(zrodlo) if zrodlo else None
        info["wymiary"] = wym
        prop = najblizsze_proporcje(wym[0], wym[1], ch["proporcje"]) if wym else None
        if not prop:
            prop = "3:4" if "3:4" in ch["proporcje"] else ch["proporcje"][0]
            info["zgadniete"] = True
    elif prop not in ch["proporcje"]:
        raise ValueError(f"{nazwa} nie ma proporcji {prop}. Ma: {', '.join(ch['proporcje'])}.")
    parametry = {"aspect_ratio": prop}
    if ch["rozdzielczosc"]:
        r = (o.get("rozdzielczosc") or ch["domyslne"]["rozdzielczosc"]).strip().lower()
        if r not in ch["rozdzielczosc"]:
            raise ValueError(f"{nazwa} nie ma rozdzielczosci {r}. Ma: {', '.join(ch['rozdzielczosc'])}.")
        parametry["resolution"] = r
    if ch["jakosc"]:
        q = (o.get("jakosc") or ch["domyslne"]["jakosc"]).strip().lower()
        if q not in ch["jakosc"]:
            raise ValueError(f"{nazwa} nie ma jakosci {q}. Ma: {', '.join(ch['jakosc'])}.")
        parametry["quality"] = q
    return model, parametry, info


def opis_parametrow(model, parametry):
    """'Seedream 5.0 Pro · 3:4 · 2K' (+ ' · jakość Wysoka') - do logow, wpisu i panelu."""
    czesci = [MODELE[model]["nazwa"], parametry.get("aspect_ratio")]
    if parametry.get("resolution"):
        czesci.append(etykieta_rozdzielczosci(parametry["resolution"]))
    if parametry.get("quality"):
        czesci.append("jakość " + JAKOSCI.get(parametry["quality"], parametry["quality"]))
    return " · ".join(c for c in czesci if c)


def zbuduj(slug, zrodlo, opcje=None):
    """Wstawione zdjecie + opcje -> {"prompt", "obrazy" (1 = zdjecie, potem referencje, na koncu stroj), "model", "nazwa_modelu",
    "parametry", "proporcje_jak_zdjecie", "stroj_id", "stroj_plik", "stroj_nazwa", "ostrzezenia", "znaki", "opis"}. Zero wysylania.
    opcje: model, proporcje ("jak_zdjecie" | "9:16" ...), jakosc, rozdzielczosc, stroj ("ze_zdjecia" | id z biblioteki ze
    zdjeciem), dopisek (opcjonalnie)."""
    o = dict(opcje or {})
    if not zrodlo or not os.path.isfile(zrodlo):
        raise ValueError("Najpierw wstaw zdjecie (nie ma pliku zdjecia).")
    model, parametry, info = _parametry(o, zrodlo)
    ch = chipy(schemat(model))
    ostrzezenia = []
    if info["zgadniete"]:
        ostrzezenia.append(f"Nie umiem odczytac wymiarow zdjecia - proporcje {parametry['aspect_ratio']}.")
    prof = baza.profil_modelki(slug)
    imie = (prof.get("nazwa") or slug).strip()

    # --- stroj ---
    stroj = (o.get("stroj") or STROJ_ZE_ZDJECIA).strip()
    bib = None
    if stroj != STROJ_ZE_ZDJECIA:
        bib = baza.stroj_biblioteki(stroj)
        if not bib or not bib.get("plik"):
            raise ValueError("Nie ma takiego stroju ze zdjeciem w bibliotece strojow.")

    # --- obrazy: 1 = wstawione zdjecie, 2.. = referencje persony (wszystkie, chyba ze model ma limit), na koncu stroj ---
    refy = list(baza.sciezki_referencji(slug))
    if not refy:
        raise ValueError(f"{imie} nie ma zdjec w referencje/ - bez nich model nie wie, kogo wstawic. Dodaj je w Ustawienia -> Persona.")
    if ch["max_obrazow"]:
        miejsce = ch["max_obrazow"] - 1 - (1 if bib else 0)
        if miejsce < 1:
            raise ValueError(f"{MODELE[model]['nazwa']} przyjmuje za malo zdjec na podmiane postaci.")
        if len(refy) > miejsce:
            ostrzezenia.append(f"{MODELE[model]['nazwa']} przyjmuje max {ch['max_obrazow']} zdjec - ide z pierwszymi {miejsce} "
                               f"zdjeciami persony (z {len(refy)}).")
            refy = refy[:miejsce]
    n = len(refy)
    ref = _obrazy_tekst(2, n + 1)
    k_stroju = n + 2

    # --- persona: tozsamosc (bez wlosow), wlosy, wzrost, sylwetka - bez slow ryzykownych ---
    zamienione = []

    def czysto(tekst):
        t, z = bez_slow_ryzykownych(tekst)
        zamienione.extend(z)
        return t
    toz = scenariusz.tozsamosc(slug, bez_wlosow=True, limit=700)
    toz = czysto(_numery_obrazow(toz, 1)).rstrip(". ") or f"{imie} looks exactly like in {ref}"
    wlosy = czysto(scenariusz.wlosy_wlasne(slug).replace("the reference photos", ref)).rstrip(". ")
    wzrost = scenariusz.zdanie_wzrostu(prof.get("wzrost_cm"))
    sylwetka = czysto(_numery_obrazow(re.sub(r"\s+", " ", str(prof.get("sylwetka") or "")).strip(), 1)
                      .replace("the reference photos", ref)).rstrip(". ")
    dopisek = re.sub(r"\s+", " ", str(o.get("dopisek") or "")).strip()[:MAX_DOPISKU]
    zamienione_przed = len(zamienione)
    dopisek = czysto(dopisek) if dopisek else ""
    if len(zamienione) > zamienione_przed:
        ostrzezenia.append("W dopisku byly slowa, ktore filtr NSFW lubi blokowac - zamienilem je: "
                           + ", ".join(zamienione[zamienione_przed:]) + ".")
    if not sylwetka:
        ostrzezenia.append(f"{imie} nie ma sylwetki w profilu (Ustawienia -> Persona -> Sylwetka) - figura tylko ze zdjec.")

    # --- tekst ---
    linie = [
        f"Edit image 1 (the first image) into a photo of {imie} - a complete character replacement. Keep everything in image 1 "
        f"exactly as it is: the framing and crop, camera angle, distance and lens perspective, the pose and the position of every "
        f"body part and hand, the facial expression and the direction of the gaze, the background, every object, the lighting, "
        f"shadows and colours. Replace only the person: she becomes {imie}, the young woman shown in {ref}.",
        "Nothing of the original person's look may stay - not her face, hair, hairstyle, hair colour, skin tone, eyes, eyebrows, "
        "make-up, tattoos, moles, birthmarks, piercings or body shape.",
        f"[{imie}] {ref[:1].upper() + ref[1:]} {'is' if n == 1 else 'are'} the only source of her face, eyes, skin, hair, "
        f"piercings and figure. Keep her instantly recognizable, never blend her with the original person, only one of her. "
        f"{toz}. Hair: {wlosy}." + (f" {wzrost}" if wzrost else ""),
    ]
    if sylwetka:
        linie.append(f"Body shape (highest priority after her face): {sylwetka}. Give her exactly this figure even where the person "
                     f"in image 1 is slimmer or flatter - keep the pose, reshape the body to her proportions.")
    else:
        linie.append(f"Body: her own figure and proportions from {ref}, never the body shape of the person in image 1.")
    if bib:
        opis_stroju = czysto(bib["opis_en"]).rstrip(". ")
        linie.append(f"Outfit: {opis_stroju} - exactly the clothing shown in image {k_stroju} (the last image), worn naturally on her "
                     f"figure instead of the clothes from image 1. Image {k_stroju} shows ONLY the outfit: ignore the hair, face, "
                     f"skin, tattoos and body shape of the person or mannequin wearing it - her hair, face and body come only from "
                     f"{ref}.")
    else:
        linie.append("Outfit: exactly the clothes, shoes and accessories the person in image 1 is wearing - the same garments, "
                     "colours, fabrics, fit and layering - worn naturally on her figure. Jewellery on her face and ears follows her "
                     "reference photos.")
    linie += [
        "[Clean-up] Remove everything that was added on top of image 1 - captions, text, watermarks, usernames, stickers, emoji, "
        "app buttons and frames - and fill those areas with the real scene behind them.",
        "[Look] Photorealistic, like a real unedited phone photo: the same light, white balance, grain and sharpness as image 1, "
        "natural skin texture with visible pores, realistic proportions. No beauty filter, no airbrushing, no extra make-up: she "
        "looks exactly as in her reference photos - not prettier, younger or slimmer.",
    ]
    if dopisek:
        linie.append(f"[Extra] {dopisek}")
    linie.append(f"[Check] Her face, hair and skin match {ref}" + ("; her figure matches the body shape above" if sylwetka else "")
                 + "; nothing of the original person remains.")
    prompt = "\n".join(re.sub(r"[ \t]{2,}", " ", l).strip() for l in linie)
    reszta = slowa_ryzykowne(prompt)
    if reszta:      # nie powinno sie zdarzyc (wszystko przeszlo przez czysto) - ale lepiej wiedziec przed wyslaniem
        ostrzezenia.append(f"W prompcie zostaly slowa, ktore filtr NSFW lubi blokowac: {', '.join(reszta)}.")
    if zamienione[:zamienione_przed]:
        ostrzezenia.append("Z opisu persony zamienilem slowa, ktore filtr NSFW lubi blokowac: "
                           + ", ".join(sorted(set(zamienione[:zamienione_przed]))) + ".")
    obrazy = [os.path.abspath(zrodlo)] + refy + ([bib["plik"]] if bib else [])
    stroj_nazwa = bib["nazwa"] if bib else "ze zdjęcia"
    return {"prompt": prompt, "obrazy": obrazy, "model": model, "nazwa_modelu": MODELE[model]["nazwa"], "parametry": parametry,
            "proporcje_jak_zdjecie": info["jak_zdjecie"], "wymiary": info["wymiary"], "stroj_id": bib["id"] if bib else None,
            "stroj_plik": bib["plik"] if bib else None, "stroj_nazwa": stroj_nazwa, "ostrzezenia": ostrzezenia,
            "znaki": len(prompt), "referencje": n,
            "opis": f"Podmiana postaci: {nazwa_zrodla(zrodlo)} · {opis_parametrow(model, parametry)} · strój: {stroj_nazwa}"}


def zlecenie(slug, sw):
    """Wynik zbuduj() -> zlecenie dla dostawcy Higgsfield (wstawione zdjecie = obraz_swiezy: swiezy upload, id w znaczniku)."""
    p = dict(sw["parametry"])
    return {"slug": slug, "prompt": sw["prompt"], "video": None, "images": list(sw["obrazy"]), "obraz_swiezy": sw["obrazy"][0],
            "duration": None, "aspect_ratio": p.pop("aspect_ratio", None), "resolution": p.pop("resolution", None),
            "model": sw["model"], "mode": None, "generate_audio": None, "soul_id": "", "parametry": p, "dostawca": "higgsfield"}


# ---------------- cena (darmowe `generate cost`, bez mediow, cache po parametrach) ----------------

def cena(model, parametry, swieza=False):
    """Cena JEDNEGO zdjecia (moze byc ulamkowa). Bez zdjec i z krotkim promptem - zero uploadu (cena od nich nie zalezy,
    sprawdzone 2026-10-07). swieza=True: z pominieciem cache (tuz przed wyslaniem)."""
    klucz = (model,) + tuple(sorted((k, str(v)) for k, v in (parametry or {}).items()))
    if not swieza:
        with _lock:
            w = _ceny.get(klucz)
        if w and time.time() - w[0] < CENA_WAZNA_S:
            return w[1]
    p = dict(parametry or {})
    z = {"slug": None, "prompt": PROMPT_WYCENY, "images": [], "model": model, "aspect_ratio": p.pop("aspect_ratio", None),
         "resolution": p.pop("resolution", None), "parametry": p}
    k = dostawcy.dostawca("higgsfield").koszt_dokladny(z)
    if k is not None:
        with _lock:
            _ceny[klucz] = (time.time(), k)
    return k


def wyczysc_cache():
    with _lock:
        _ceny.clear()
        _schematy.clear()


def wycena(slug, opcje=None, zrodlo=None, saldo=None, swieza=False):
    """Cena N zdjec + bezpieczniki (0 kr, nic nie tworzy). Zwraca {"model", "nazwa_modelu", "parametry", "opis", "ile",
    "kr_sztuka" (cena 1 zdjecia, np. 2.5), "kr" (razem), "kr_limit" (do limitu dnia, w gore), "saldo", "dzis" {wydano (z rezerwa
    w toku), limit}, "min_kredyty", "mozna", "powody", "ostrzezenia"}. saldo=None - pyta Higgsfield. ValueError przy zlych opcjach."""
    o = dict(opcje or {})
    ile = _ile(o.get("ile"))
    model, parametry, info = _parametry(o, zrodlo)
    ust = baza.ustawienia_modelki(slug)
    min_k, max_k = fabryka.bezpiecznik(ust, "higgsfield")
    # bez zdjecia (albo nieczytelne) proporcje "jak zdjecie" sa jeszcze nieznane - cena od nich nie zalezy, opis tego nie udaje
    opis = opis_parametrow(model, dict(parametry, aspect_ratio="proporcje jak zdjęcie") if info["zgadniete"] else parametry)
    wynik = {"model": model, "nazwa_modelu": MODELE[model]["nazwa"], "parametry": parametry, "ile": ile,
             "opis": opis, "proporcje_jak_zdjecie": info["jak_zdjecie"],
             "kr_sztuka": None, "kr": None, "kr_limit": None, "saldo": saldo, "min_kredyty": min_k,
             "dzis": {"wydano": baza.wydano_z_rezerwa("higgsfield"), "limit": baza.limit_dzienny("higgsfield")},
             "mozna": False, "powody": [], "ostrzezenia": []}
    if not baza.sciezki_referencji(slug):
        wynik["powody"].append("persona nie ma zdjec w referencje/ (Ustawienia -> Persona).")
    try:
        k = cena(model, parametry, swieza=swieza)
    except dostawcy.BladDostawcy as e:
        wynik["powody"].append(f"Higgsfield nie podal ceny: {e}")
        return wynik
    if k is None:
        wynik["powody"].append("Higgsfield nie podal ceny - sprobuj jeszcze raz.")
        return wynik
    if saldo is None:
        try:
            saldo = dostawcy.dostawca("higgsfield").saldo()
        except dostawcy.BladDostawcy as e:
            wynik["powody"].append(f"nie moge sprawdzic salda Higgsfield: {e}")
    kl = do_limitu(k)
    wynik.update({"kr_sztuka": k, "kr": round(float(k) * ile, 2), "kr_limit": kl * ile, "saldo": saldo})
    if isinstance(wynik["kr"], float) and wynik["kr"].is_integer():
        wynik["kr"] = int(wynik["kr"])
    wydano, limit = wynik["dzis"]["wydano"], wynik["dzis"]["limit"]
    # saldo: minus to, co juz zarezerwowane (rolki i zdjecia w toku + kolejka) - tak samo liczy zlec() przy "Generuj"
    rezerwa = baza.koszt_w_toku("higgsfield")
    if kl > max_k:
        wynik["powody"].append(f"{_kr(k)} za zdjecie to wiecej niz bezpiecznik {max_k} kr.")
    if saldo is not None and saldo - rezerwa - kl * ile < min_k:
        wynik["powody"].append(f"po tych zdjeciach zostaloby {saldo - rezerwa - kl * ile} kr" + (f" (z tym, co w toku i w kolejce: "
                               f"{rezerwa} kr)" if rezerwa else "") + f", a minimum to {min_k} kr.")
    if limit and wydano + kl * ile > limit:
        wejdzie = max(0, (limit - wydano) // kl) if kl else 0
        wynik["powody"].append(f"dzis wydano {wydano} z {limit} kr - {ile} zdj. ({kl * ile} kr) przekroczyloby dzienny limit"
                               + (f" (zmiesci sie {wejdzie})." if wejdzie else "."))
    wynik["mozna"] = not wynik["powody"]
    return wynik


# ---------------- generacja: kolejka zdjec i wysylanie rownolegle (3.3) ----------------
# "Generuj" = zlec(): wpisy 'w_kolejce' z rezerwacja w limicie dnia i saldzie - ATOMOWO pod blokada kolejki (watki i procesy),
# liczac rolki i zdjecia w toku oraz cala kolejke - nic nie wysyla. Wysyla _Obsluga: w panelu dyspozytor w tle (KOLEJKA, wszystkie
# persony, niezalezny od zadan konsoli/rolek), w CLI i testach generuj() (tylko swoje zdjecia, az do konca). Najwyzej
# `zdjecia_rownolegle` (ustawienie globalne, domyslnie 4) zdjec w toku naraz - liczonych z dysku, wiec takze z innego procesu;
# nadmiar czeka w kolejce. Kazde zdjecie ma jednego wlasciciela (baza.BlokadaZdjecia) i jest przejmowane atomowo (w_kolejce ->
# w_toku). Potem jak dawniej: swieza cena i bezpieczniki -> _wyslij (znacznik w_toku przed wysylka, job_id od razu) -> _dokoncz
# (generate get, 0 kr). Higgsfield odmowil "za duzo naraz" (HTTP 429 / too many / concurrent / rate limit) i job NA PEWNO nie
# powstal -> zdjecie wraca do kolejki (po chwili); przy watpliwosci, czy job powstal - NIGDY drugi raz (jak rolki).

STATUS_KOLEJKA = "w_kolejce"
STATUS_ANULOWANE = "anulowane"
STATUSY_KONCOWE = ("gotowe", "blad", STATUS_ANULOWANE)
ROWNOLEGLE_MAX = 8
PONOW_PO_S = 30                 # odmowa "za duzo naraz": zdjecie wraca do kolejki - proba po tylu s (potem 2x dluzej, max PONOW_MAX_S)
PONOW_MAX_S = 300
MAX_PONOWIEN = 10               # po tylu odmowach "za duzo naraz" zdjecie konczy sie bledem (nic nie zeszlo)
ODSTEP_KOLEJKI_S = 2            # dyspozytor patrzy w kolejke co tyle s (i od razu po "Generuj" albo koncu zdjecia)
ODSTEP_OSIEROCONYCH_S = 60      # zdjecie w toku bez wlasciciela (restart, limit czasu czekania) sprawdzamy znowu najwczesniej po tylu s
CZEKAJ_NA_MIEJSCE_S = 15 * 60   # generuj() (CLI): tyle czekamy na wolne miejsce, gdy wszystkie zajmuja cudze zdjecia w toku

NOTATKA_STOP = "Zatrzymane (STOP) przed wyslaniem - nic nie poszlo do Higgsfield, 0 kr."
NOTATKA_SERIA_FILTR = ("Nie wyslane: filtr Higgsfield odrzucil inne zdjecie z tej serii (to samo zdjecie i ustawienia dalyby to samo) - "
                       "0 kr. Zmien zdjecie, stroj albo model i kliknij Generuj.")
NOTATKA_SERIA_NIEPEWNE = ("Nie wyslane: przy wysylaniu innego zdjecia z tej serii nie wiadomo, czy job powstal (siec/CLI) - nie "
                          "dokladam kolejnych, 0 kr. Kliknij Generuj jeszcze raz, gdy tamto sie wyjasni.")

_numer_serii = itertools.count(1)


class Odmowa(ValueError):
    """zlec() odmowil, zanim cokolwiek powstalo (cena, bezpieczniki, limit dnia). kod = jak dawne wynik['stop']."""

    def __init__(self, kod, tekst):
        super().__init__(tekst)
        self.kod = kod


class ZaDuzoNaraz(Exception):
    """Higgsfield odmowil przyjecia zlecenia (limit zadan naraz / za duzo zapytan) i job NA PEWNO nie powstal - wraca do kolejki."""


def _nowy_wynik():
    return {"zrobione": 0, "pliki": [], "bledy": [], "odrzucone": [], "w_toku": [], "stop": None, "ids": []}


def _scal(wynik, czesc):
    for k in ("pliki", "bledy", "odrzucone", "w_toku"):
        wynik[k].extend(czesc[k])
    wynik["zrobione"] += czesc["zrobione"]
    if czesc.get("stop") and not wynik.get("stop"):
        wynik["stop"] = czesc["stop"]


def rownolegle():
    """Ustawienie globalne `zdjecia_rownolegle` (1-8, domyslnie 4): ile zdjec moze byc w toku naraz."""
    try:
        n = int(baza.ustawienia_globalne().get("zdjecia_rownolegle") or 4)
    except (TypeError, ValueError):
        n = 4
    return max(1, min(ROWNOLEGLE_MAX, n))


def _blokada_kolejki():
    """Blokada kolejki zdjec (watki i procesy): rezerwacja przy "Generuj" i liczenie wolnych miejsc przy przejmowaniu."""
    return baza._rmw(os.path.join(os.path.dirname(baza.PLIK_BUDZETU), "kolejka_zdjec"))


_WZOR_ZA_DUZO = re.compile(
    r"\bhttp\s*429\b|\b429\s+too many|status(?:\s*code)?\s*[:=]?\s*429\b|too many|rate[ _-]?limit|ratelimit|concurren|"
    r"\bparallel\b|simultaneous|(?:max|maximum|limit)\b[^.\n]{0,40}\b(?:jobs|generations|tasks|requests)\b[^.\n]{0,30}"
    r"\b(?:running|in progress|at (?:a|the same) time|at once|active|in queue)", re.I)
_WZOR_SIECI = re.compile(r"timeout|timed out|deadline|nie odpowiedzialo|connection|connect:|socket|\beof\b|reset by peer|"
                         r"broken pipe|dial tcp|\btls\b|no such host|network|unreachable|hang up", re.I)


def za_duzo_naraz(blad):
    """Czy Higgsfield ODMOWIL zlecenia z powodu limitu zadan naraz / zapytan (HTTP 429, "too many", "concurrent", "rate limit") -
    czyli odpowiedzial serwer. NIE: filtr NSFW/IP, blad trwaly (kredyty, walidacja, logowanie) ani blad sieci (timeout, zerwane
    polaczenie = nie wiadomo, czy zlecenie dotarlo). Higgsfield nie dokumentuje dokladnego tekstu (skill higgsfield-generate:
    "Higgsfield API error (HTTP 429) - too many requests"; CLI 1.1.26 drukuje "Higgsfield API error (HTTP %d).") - stad ogolne
    wzorce."""
    t = str(blad or "")
    if not t or fabryka.powod_odrzucenia("", t) in fabryka.POWODY_ZAPASU or fabryka._blad_trwaly(blad):
        return False
    if _WZOR_SIECI.search(t):
        return False
    return bool(_WZOR_ZA_DUZO.search(t))


def zlec(slug, zrodlo, opcje=None, kr=None, saldo=None, log=None, obudz=True):
    """"Generuj": N zdjec (opcje["ile"], 1-4) do kolejki - wpisy 'w_kolejce' z rezerwacja w limicie dnia Higgsfield i w saldzie,
    ATOMOWO pod blokada kolejki (watki i procesy). Liczy rolki i zdjecia w toku oraz cala kolejke, wiec kilka szybkich klikniec nie
    przebije limitu ani min_kredyty. Nic nie wysyla (wysyla dyspozytor panelu albo generuj()). kr = cena JEDNEGO zdjecia, ktora user
    widzial: wyzsza teraz = Odmowa, rezerwacja liczy kr w gore. saldo = saldo Higgsfield (panel: z cache; None = pyta CLI).
    Zwraca liste id. Odmowa (kod, tekst) = nic nie powstalo; ValueError = zle opcje / brak zdjecia."""
    log = log or _log
    o = dict(opcje or {})
    ile = _ile(o.get("ile"))
    sw = zbuduj(slug, zrodlo, o)
    try:
        k = cena(sw["model"], sw["parametry"])
    except dostawcy.BladDostawcy as e:
        raise Odmowa(f"koszt: {e}", f"Higgsfield nie podal ceny ({e}) - nic nie wyslalem.")
    if k is None:
        raise Odmowa("koszt nieznany", "Higgsfield nie podal ceny - sprobuj jeszcze raz (nic nie wyslalem).")
    if kr is not None and float(k) > float(kr) + 1e-9:
        raise Odmowa("cena wzrosla", f"Cena wzrosla z {_kr(kr)} do {_kr(k)} - nic nie wyslalem. Sprawdz cene jeszcze raz.")
    kl = do_limitu(max(float(k), float(kr)) if kr is not None else k)
    min_k, max_k = fabryka.bezpiecznik(baza.ustawienia_modelki(slug), "higgsfield")
    if kl > max_k:
        raise Odmowa("max/zdjecie", f"{_kr(k)} za zdjecie to wiecej niz bezpiecznik {max_k} kr.")
    if saldo is None:
        try:
            saldo = dostawcy.dostawca("higgsfield").saldo()
        except dostawcy.BladDostawcy as e:
            raise Odmowa(f"saldo: {e}", f"Nie moge sprawdzic salda Higgsfield ({e}) - nic nie wyslalem.")
    seria = f"{time.strftime('%Y%m%d%H%M%S')}-{os.getpid()}-{next(_numer_serii)}"
    wpis = {"prompt": sw["prompt"], "status": STATUS_KOLEJKA, "typ": "swap", "stroj": sw["stroj_plik"], "zrodlo": sw["obrazy"][0],
            "zrodlo_nazwa": nazwa_zrodla(zrodlo), "model": sw["model"], "parametry": sw["parametry"], "stroj_bib": sw["stroj_id"],
            "opis": sw["opis"], "dostawca": "higgsfield", "wycena": k, "obrazy": list(sw["obrazy"]), "w_toku": None}
    with _blokada_kolejki():
        limit = baza.limit_dzienny("higgsfield")
        rezerwa = baza.koszt_w_toku("higgsfield")         # rolki + zdjecia w toku + kolejka zdjec (wszystkie persony)
        wydano = baza.wydano_dzis("higgsfield") + rezerwa
        if limit and wydano + kl * ile > limit:
            wejdzie = max(0, (limit - wydano) // kl) if kl else 0
            raise Odmowa("limit dzienny", f"Dzis wydano {wydano} z {limit} kr (razem z tym, co w toku i w kolejce) - {ile} zdj. "
                         f"({kl * ile} kr) przekroczyloby dzienny limit" + (f"; zmiesci sie {wejdzie}." if wejdzie else "."))
        if saldo is not None and saldo - rezerwa - kl * ile < min_k:
            raise Odmowa("min_kredyty", f"Po tych zdjeciach zostaloby {saldo - rezerwa - kl * ile} kr (saldo {saldo}, w toku i w "
                         f"kolejce {rezerwa} kr), a minimum to {min_k} kr.")
        kolejka = {"kr": kr if kr is not None else k, "koszt": kl, "od": fabryka._teraz_iso(), "seria": seria, "nie_przed": 0,
                   "ponowienia": 0}
        ids = baza.dodaj_zdjecia(slug, [dict(wpis, kolejka=dict(kolejka)) for _ in range(ile)])
    for u in sw["ostrzezenia"]:
        log(f"[UWAGA] {u}")
    _zdarzenie(log, slug, "info", f"zdjecia {', '.join('#%s' % i for i in ids)}: w kolejce (podmiana postaci, {sw['opis']}, "
               f"{_kr(k)} za sztuke, rezerwacja {kl * ile} kr) - {nazwa_zrodla(zrodlo)}", zdjecia=ids)
    if obudz:
        KOLEJKA.obudz(wznawiaj=True)
    return ids


def generuj(slug, zrodlo, opcje=None, kr=None, log=None, stop=None, timeout=CZAS_NA_ZDJECIE, saldo=None):
    """CLI i testy: zlec() + obsluga TYCH zdjec w tym procesie az do konca - wysylane od razu, rownolegle (najwyzej rownolegle()
    w toku naraz, nadmiar czeka w kolejce), kazde jako osobne zlecenie z pelnym zabezpieczeniem pieniedzy. Przy okazji (tez
    rownolegle) dokancza zdjecia persony w toku (0 kr). Zwraca {"zrobione", "pliki", "bledy", "odrzucone" (NSFW/IP), "w_toku",
    "stop", "ids"}."""
    log = log or _log
    wynik = _nowy_wynik()
    try:
        ids = zlec(slug, zrodlo, opcje, kr=kr, saldo=saldo, log=log, obudz=False)
    except Odmowa as e:
        _zdarzenie(log, slug, "uwaga", f"zdjecia: {e}")
        wynik["stop"] = e.kod
        return wynik
    wynik["ids"] = list(ids)
    tylko = {(slug, i) for i in ids} | {(slug, z["id"]) for z in baza.zdjecia_w_toku(slug)}
    log(f"zdjecia: {len(ids)} szt. wysylam rownolegle (najwyzej {rownolegle()} w toku naraz) | dzis wydano "
        f"{baza.wydano_dzis('higgsfield')}/{baza.limit_dzienny('higgsfield')} (+{baza.koszt_w_toku('higgsfield')} w toku i w kolejce)")
    _Obsluga(log=log, timeout=timeout, tylko=tylko, stop=stop, wynik=wynik).do_konca()
    log(f"zdjecia: {wynik['zrobione']} zrobione, dzis wydano {baza.wydano_dzis('higgsfield')}/{baza.limit_dzienny('higgsfield')} kr"
        + (f", w toku: {', '.join('#%s' % i for i in wynik['w_toku'])}" if wynik["w_toku"] else ""))
    return wynik


def _swap_na_dysku():
    """[(slug, zdjecie)] zdjec w toku i w kolejce - wszystkie persony, prosto z dysku (takze te z innego procesu)."""
    wynik = []
    for slug in baza.lista_modelek():
        try:
            lista = baza.lista_zdjec(slug)
        except (OSError, ValueError):
            continue
        wynik += [(slug, z) for z in lista if z.get("status") in ("w_toku", STATUS_KOLEJKA)]
    return wynik


class _Obsluga:
    """Wysyla zdjecia z kolejki i dokancza zdjecia w toku - kazde w osobnym watku, najwyzej rownolegle() w toku naraz (liczone z
    dysku, wiec takze zdjecia innego procesu zajmuja miejsca). tylko = {(slug, id)}: tylko te (generuj / wznow_w_toku - kazde
    zdjecie w toku najwyzej raz); None = wszystkie persony (dyspozytor panelu - osierocone w toku sprawdza znowu najwczesniej co
    ODSTEP_OSIEROCONYCH_S)."""

    def __init__(self, log=None, timeout=CZAS_NA_ZDJECIE, tylko=None, stop=None, wynik=None):
        self.log = log or _log
        self.timeout = timeout
        self.tylko = set(tylko) if tylko is not None else None
        self.stop = stop if stop is not None else threading.Event()
        self.wynik = wynik if wynik is not None else _nowy_wynik()
        self.lock = threading.Lock()
        self.watki = {}             # (slug, id) -> watek
        self.ruszone = set()        # zdjecia, ktore ten obiekt juz obslugiwal (tryb `tylko`: w toku najwyzej raz)
        self.nie_przed = {}         # (slug, id) w toku -> czas, przed ktorym dyspozytor go nie rusza
        self.budzik = threading.Event()
        self.katalog = baza.KATALOG_MODELEK     # bezpiecznik: inny katalog person (koniec testu) = nic nie robimy
        self.wstrzymane = False     # panel sie zamyka: nic nie przejmujemy (kolejka zostaje na nastepny start)

    def _moje(self, klucz):
        return self.tylko is None or klucz in self.tylko

    def aktywne(self):
        with self.lock:
            return {k for k, w in self.watki.items() if w.is_alive()}

    def katalog_zmieniony(self):
        return baza.KATALOG_MODELEK != self.katalog

    def krok(self, wznawiaj=True):
        """Jeden obrot: osierocone zdjecia w toku -> watek dokonczenia (nic nie wysyla), potem z kolejki (najstarsze najpierw) tyle,
        ile jest wolnych miejsc. Zwraca liczbe uruchomionych watkow."""
        if self.katalog_zmieniony() or self.wstrzymane:
            return 0
        teraz = time.time()
        stan = _swap_na_dysku()
        aktywne = self.aktywne()
        n = 0
        if wznawiaj and not self.stop.is_set():
            for slug, z in stan:
                klucz = (slug, z["id"])
                if z.get("status") != "w_toku" or klucz in aktywne or not self._moje(klucz):
                    continue
                if (self.tylko is not None and klucz in self.ruszone) or self.nie_przed.get(klucz, 0) > teraz:
                    continue
                blok = baza.BlokadaZdjecia(slug, z["id"])
                if not blok.zablokuj():
                    continue            # obsluguje je ktos inny (watek dyspozytora, inny proces)
                self._start(klucz, self._dokoncz_w_toku, blok)
                n += 1
        if self.stop.is_set():
            return n
        kolejka = [(slug, z) for slug, z in stan if z.get("status") == STATUS_KOLEJKA and self._moje((slug, z["id"]))
                   and (slug, z["id"]) not in aktywne and float((z.get("kolejka") or {}).get("nie_przed") or 0) <= teraz]
        if not kolejka:
            return n
        kolejka.sort(key=lambda x: (str((x[1].get("kolejka") or {}).get("od") or x[1].get("utworzono") or ""), x[0], x[1]["id"]))
        with _blokada_kolejki():
            if self.katalog_zmieniony():
                return n
            # wolne miejsca liczone swiezo POD blokada - drugi proces nie przejmie w tej samej chwili ponad limit
            wolne = rownolegle() - sum(1 for _, z in _swap_na_dysku() if z.get("status") == "w_toku")
            for slug, z in kolejka:
                if wolne <= 0:
                    break
                blok = baza.BlokadaZdjecia(slug, z["id"])
                if not blok.zablokuj():
                    continue
                if not baza.przejmij_zdjecie(slug, z["id"]):
                    blok.odblokuj()
                    continue
                wolne -= 1
                self._start((slug, z["id"]), self._wyslij_z_kolejki, blok)
                n += 1
        return n

    def _start(self, klucz, fn, blok):
        stop = self.stop
        with self.lock:
            self.ruszone.add(klucz)
            w = threading.Thread(target=self._watek, args=(klucz, fn, blok, stop), daemon=True,
                                 name=f"zdjecie-{klucz[0]}-{klucz[1]}")
            self.watki[klucz] = w
        w.start()

    def _watek(self, klucz, fn, blok, stop):
        slug, zid = klucz
        czesc = _nowy_wynik()
        try:
            fn(slug, zid, stop, czesc)
        except Exception as e:      # watek nie moze zginac bez sladu; zdjecie zostaje, jak jest (nic nie wysylamy drugi raz)
            traceback.print_exc()
            _zdarzenie(self.log, slug, "blad", f"zdjecie #{zid}: nieoczekiwany blad ({type(e).__name__}: {str(e)[:200]}) - nic nie "
                       f"wysylam drugi raz, sprawdze je jeszcze", zdjecie=zid)
        finally:
            try:
                status = baza.zdjecie(slug, zid).get("status")
            except (ValueError, OSError):
                status = None
            blok.odblokuj(usun=status in STATUSY_KONCOWE or status is None)
            with self.lock:
                _scal(self.wynik, czesc)
                self.watki.pop(klucz, None)
                if status == "w_toku":
                    self.nie_przed[klucz] = time.time() + ODSTEP_OSIEROCONYCH_S
            self.budzik.set()

    def _dokoncz_w_toku(self, slug, zid, stop, wynik):
        z = baza.zdjecie(slug, zid)
        if z.get("status") == "w_toku":
            _wznow_jedno(slug, z, dostawcy.dostawca("higgsfield"), self.log, stop, self.timeout, wynik)

    def _wyslij_z_kolejki(self, slug, zid, stop, wynik):
        _obsluz_z_kolejki(slug, zid, self.log, stop, self.timeout, wynik)

    def do_konca(self):
        """Tryb `tylko` (generuj, wznow_w_toku): obroty, az wybrane zdjecia skoncza sie albo zostana w toku (dokonczy je nastepne
        sprawdzenie). STOP: wybrane zdjecia z kolejki -> anulowane (nic nie poszlo)."""
        bez_miejsca_od = None
        while not self.katalog_zmieniony():
            uruchomione = self.krok()
            if self.aktywne():
                bez_miejsca_od = None
                self.budzik.wait(ODSTEP_KOLEJKI_S)
                self.budzik.clear()
                continue
            czeka = [(s, z) for s, z in _swap_na_dysku() if z.get("status") == STATUS_KOLEJKA and self._moje((s, z["id"]))]
            if not czeka:
                break
            if self.stop.is_set():
                for s in {s for s, _ in czeka}:
                    ids = baza.anuluj_zdjecia_w_kolejce(s, NOTATKA_STOP, ids={z["id"] for x, z in czeka if x == s})
                    if ids:
                        _zdarzenie(self.log, s, "info", f"zdjecia {', '.join('#%s' % i for i in ids)}: {NOTATKA_STOP}")
                self.wynik["stop"] = self.wynik["stop"] or "stop"
                break
            teraz = time.time()
            if not uruchomione and any(float((z.get("kolejka") or {}).get("nie_przed") or 0) <= teraz for _, z in czeka):
                # gotowe do wyslania, a wszystkie miejsca zajmuja cudze zdjecia w toku
                bez_miejsca_od = bez_miejsca_od or teraz
                if teraz - bez_miejsca_od > CZEKAJ_NA_MIEJSCE_S:
                    self.log(f"zdjecia: od {CZEKAJ_NA_MIEJSCE_S // 60} min nie ma wolnego miejsca (w toku {rownolegle()} naraz) - "
                             f"{len(czeka)} zostaje w kolejce, wysle je panel")
                    self.wynik["stop"] = self.wynik["stop"] or "kolejka pelna"
                    break
            self.budzik.wait(ODSTEP_KOLEJKI_S)
            self.budzik.clear()


def _obsluz_z_kolejki(slug, zid, log, stop, timeout, wynik):
    """Zdjecie przejete z kolejki (status w_toku, etap 'wysylanie', nic jeszcze nie poszlo): swieza cena i bezpieczniki -> wyslanie
    (job_id od razu) -> czekanie na TEN job -> pobranie. Odmowa 'za duzo naraz' (job na pewno nie powstal) = z powrotem do kolejki.
    Odrzucenie NSFW/IP albo niepewne wysylanie = reszta tej serii z kolejki nie idzie."""
    z = baza.zdjecie(slug, zid)
    k = z.get("kolejka") or {}
    kr, kl, seria = k.get("kr"), int(k.get("koszt") or 0), k.get("seria")
    sw = {"prompt": z.get("prompt") or "", "obrazy": list(z.get("obrazy") or []), "model": z.get("model") or MODEL_DOMYSLNY,
          "parametry": dict(z.get("parametry") or {})}
    brak = [os.path.basename(o) for o in sw["obrazy"] if not os.path.isfile(o)]
    if not sw["obrazy"] or brak:
        _nie_wyslane(slug, zid, log, wynik, f"brakuje plikow ({', '.join(brak) or 'zdjec'}) - wstaw zdjecie i kliknij Generuj "
                     f"jeszcze raz")
        return
    if stop.is_set():
        _anuluj(slug, zid, log, wynik)
        return
    d = dostawcy.dostawca("higgsfield")
    try:
        c = cena(sw["model"], sw["parametry"], swieza=True)        # tuz przed wyslaniem jeszcze raz (0 kr)
    except dostawcy.BladDostawcy as e:
        if za_duzo_naraz(e):
            _do_kolejki(slug, zid, log, e)
        else:
            _nie_wyslane(slug, zid, log, wynik, f"Higgsfield nie podal ceny ({str(e)[:200]})", stop_kod=f"koszt: {e}")
        return
    if c is None:
        _nie_wyslane(slug, zid, log, wynik, "Higgsfield nie podal ceny", stop_kod="koszt nieznany")
        return
    if kr is not None and float(c) > float(kr) + 1e-9:
        _nie_wyslane(slug, zid, log, wynik, f"cena wzrosla z {_kr(kr)} do {_kr(c)} - sprawdz cene i kliknij Generuj jeszcze raz",
                     stop_kod="cena wzrosla", typ="uwaga")
        return
    kl2 = do_limitu(c)
    min_k, max_k = fabryka.bezpiecznik(baza.ustawienia_modelki(slug), "higgsfield")
    if kl2 > max_k:
        _nie_wyslane(slug, zid, log, wynik, f"{_kr(c)} to wiecej niz max {max_k} kr na jedno zlecenie", stop_kod="max/zdjecie",
                     typ="uwaga")
        return
    try:
        saldo = d.saldo()
    except dostawcy.BladDostawcy as e:
        if za_duzo_naraz(e):
            _do_kolejki(slug, zid, log, e)
        else:
            _nie_wyslane(slug, zid, log, wynik, f"nie moge sprawdzic salda Higgsfield ({str(e)[:200]})", stop_kod=f"saldo: {e}")
        return
    # saldo swieze; minus inne rolki i zdjecia w toku (moga jeszcze nie byc zaksiegowane) - to zdjecie ma w znaczniku rezerwacje kl
    inne = max(0, baza.koszt_w_drodze("higgsfield") - kl)
    if saldo is not None and saldo - inne - kl2 < min_k:
        _nie_wyslane(slug, zid, log, wynik, f"{_kr(c)} zostawiloby {saldo - inne - kl2} kr (saldo {saldo}, inne w toku {inne} kr) "
                     f"< min_kredyty {min_k}", stop_kod="min_kredyty", typ="uwaga")
        return
    limit = baza.limit_dzienny("higgsfield")
    wydano = baza.wydano_z_rezerwa("higgsfield") - kl          # bez rezerwacji tego zdjecia
    if limit and wydano + kl2 > limit:
        _nie_wyslane(slug, zid, log, wynik, f"limit dzienny ({wydano}+{kl2} > {limit} kr)", stop_kod="limit dzienny", typ="uwaga")
        return
    if stop.is_set():
        _anuluj(slug, zid, log, wynik)
        return
    # panel sie zamyka (aktualizacja): najpierw znacznik "wysylam" w fabryka._WYSYLANIE (na niego czeka /api/zamknij), potem flaga
    # zamykania - albo panel poczeka na koniec wysylania, albo zdjecie wraca do kolejki (nic nie poszlo) i pojdzie po starcie
    straz = ("zdjecie-start", slug, zid)
    with fabryka._WYSYLANIE_LOCK:
        fabryka._WYSYLANIE.add(straz)
    job, blad = None, None
    try:
        if KOLEJKA.zamykanie:
            baza.zwroc_zdjecie_do_kolejki(slug, zid, notatki="Panel sie zamykal - zdjecie czeka w kolejce i pojdzie po starcie "
                                                             "(nic nie zeszlo).")
            log(f"zdjecie #{zid}: panel sie zamyka - wraca do kolejki, pojdzie po starcie (nic nie poszlo)")
            return
        _zdarzenie(log, slug, "info", f"zdjecie #{zid}: start (podmiana postaci, {z.get('opis') or sw['model']}, ~{_kr(c)})",
                   zdjecie=zid)
        try:
            job = _wyslij(slug, zid, d, zlecenie(slug, sw), kl2, log)
        except ZaDuzoNaraz as e:
            _do_kolejki(slug, zid, log, e)
            return
        except fabryka.JobTrwa:
            # nie wiadomo, czy job powstal (siec/CLI) - zostaje w toku (wznowienie szuka go 60 min); reszty serii nie dokladamy
            wynik["w_toku"].append(zid)
            wynik["stop"] = wynik["stop"] or "niepewne wysylanie"
            _anuluj_serie(slug, seria, zid, NOTATKA_SERIA_NIEPEWNE, log)
            return
        except dostawcy.BladDostawcy as e:
            blad = e
    finally:
        with fabryka._WYSYLANIE_LOCK:
            fabryka._WYSYLANIE.discard(straz)      # wyslane (job_id zapisany) - czekanie na wynik nie blokuje zamkniecia panelu
    if job is None:
        _nie_wyszlo(slug, zid, None, fabryka.powod_odrzucenia("", str(blad)) or "inny", log, wynik, blad=str(blad))
    elif job.get("job_id") is None:          # odrzucone juz przy wysylaniu (filtr)
        _nie_wyszlo(slug, zid, job, fabryka.powod_odrzucenia(job.get("status"), job.get("blad")) or "inny", log, wynik)
    else:
        _dokoncz(slug, zid, d, job["job_id"], kl2, log, stop, timeout, wynik, gotowy=job.get("gotowy"))
    if zid in wynik["odrzucone"]:
        # filtr odrzucil to zdjecie - reszta serii (te same wejscia) dostalaby to samo: zero powtorek
        wynik["stop"] = wynik["stop"] or "odrzucone przez filtr"
        _anuluj_serie(slug, seria, zid, NOTATKA_SERIA_FILTR, log)


def _nie_wyslane(slug, zid, log, wynik, przyczyna, stop_kod=None, typ="blad"):
    """Zdjecie z kolejki NIE poszlo (cena, bezpiecznik, brak plikow) - status blad, 0 kr, rezerwacja zwolniona."""
    notatki = f"Nie wyslane: {przyczyna} - nic nie zeszlo, 0 kr."
    baza.ustaw_zdjecie(slug, zid, status="blad", w_toku=None, powod="inny", notatki=notatki[:1000], koszt=0)
    wynik["bledy"].append(zid)
    if stop_kod and not wynik.get("stop"):
        wynik["stop"] = stop_kod
    _zdarzenie(log, slug, typ, f"zdjecie #{zid}: {notatki}", zdjecie=zid)


def _anuluj(slug, zid, log, wynik):
    """STOP, zanim zdjecie poszlo: status 'anulowane' (nic nie zeszlo)."""
    baza.ustaw_zdjecie(slug, zid, status=STATUS_ANULOWANE, w_toku=None, notatki=NOTATKA_STOP)
    wynik["stop"] = wynik["stop"] or "stop"
    _zdarzenie(log, slug, "info", f"zdjecie #{zid}: {NOTATKA_STOP}", zdjecie=zid)


def _anuluj_serie(slug, seria, zid, notatki, log):
    """Reszta serii (to samo klikniecie) czekajaca w kolejce -> anulowane (nic nie poszlo). Zwraca anulowane id."""
    if not seria:
        return []
    ids = baza.anuluj_zdjecia_w_kolejce(slug, notatki, seria=seria)
    if ids:
        _zdarzenie(log, slug, "info", f"zdjecie #{zid}: reszta serii nie idzie ({', '.join('#%s' % i for i in ids)}) - {notatki}",
                   zdjecie=zid)
    return ids


def _do_kolejki(slug, zid, log, blad):
    """Higgsfield odmowil 'za duzo naraz', job NA PEWNO nie powstal: zdjecie wraca do kolejki (proba za chwile, coraz rzadziej);
    po MAX_PONOWIEN - blad (nic nie zeszlo)."""
    z = baza.zdjecie(slug, zid)
    n = int((z.get("kolejka") or {}).get("ponowienia") or 0) + 1
    if n > MAX_PONOWIEN:
        notatki = (f"Higgsfield {n - 1} razy odmowil przyjecia (za duzo zadan naraz: {str(blad)[:150]}) - nic nie zeszlo, 0 kr. "
                   f"Kliknij Generuj pozniej albo zmniejsz 'Ile zdjec naraz' w Ustawienia -> Zdjecia.")
        baza.ustaw_zdjecie(slug, zid, status="blad", w_toku=None, powod="inny", notatki=notatki[:1000], koszt=0)
        _zdarzenie(log, slug, "blad", f"zdjecie #{zid}: {notatki}", zdjecie=zid)
        return
    za = min(PONOW_MAX_S, PONOW_PO_S * 2 ** (n - 1))
    baza.zwroc_zdjecie_do_kolejki(slug, zid, notatki=f"Higgsfield: za duzo zadan naraz - czeka w kolejce, sprobuje znowu za {za} s "
                                  f"(nic nie zeszlo).", ponowienia=n, nie_przed=time.time() + za)
    _zdarzenie(log, slug, "info", f"zdjecie #{zid}: Higgsfield odmowil ({str(blad)[:160]}) - job nie powstal, wraca do kolejki "
               f"(proba {n}/{MAX_PONOWIEN} za {za} s)", zdjecie=zid)


def _wyslij(slug, zid, d, z, kl, log):
    """Znacznik w_toku -> zlec() (wszystkie pliki wgrane, wstawione zdjecie swiezo; 'wysylam' tuz przed create) -> job_id zapisany
    od razu. Ponowne wyslanie TYLKO gdy job na pewno nie powstal (blad przed 'wysylam' albo blad trwaly). Odmowa 'za duzo naraz'
    (odpowiedz serwera) i joba nie ma na liscie -> ZaDuzoNaraz (zdjecie wraca do kolejki). Po 'wysylam' inny blad = szukamy joba
    po id wstawionego zdjecia; nie ma -> JobTrwa (zdjecie czeka w toku, NIGDY drugi create)."""
    ile = 1 + max(0, int(baza.ustawienia_modelki(slug).get("powtorki") or 0))
    model = z.get("model")
    klucz = ("zdjecie", slug, zid)
    blad = None
    for proba in range(1, ile + 1):
        baza.zacznij_zdjecie_w_toku(slug, zid, dostawca=d.NAZWA, model=model, koszt=kl)

        def znacznik(**pola):
            # dostawca wola to tuz PRZED nieodwracalnym wyslaniem (wszystko juz wgrane): od tej chwili job MOZE powstac
            if pola.get("wysylam"):
                pola.setdefault("wysylam_od", fabryka._teraz_iso())
            baza.ustaw_zdjecie_w_toku(slug, zid, **pola)
        with fabryka._WYSYLANIE_LOCK:
            fabryka._WYSYLANIE.add(klucz)             # panel nie zamknie sie w trakcie wysylania (fabryka.trwa_wysylanie)
        try:
            try:
                job, blad = d.zlec(z, znacznik=znacznik, log=log), None
            except dostawcy.BladDostawcy as e:
                job, blad = None, e
            if job is None:
                powod = fabryka.powod_odrzucenia("", str(blad))
                if powod in fabryka.POWODY_ZAPASU:
                    return {"job_id": None, "status": "nsfw" if powod == "nsfw" else "ip_detected", "urls": [], "blad": str(blad),
                            "surowe": {}}
                marker = baza.zdjecie(slug, zid).get("w_toku") or {}
                if za_duzo_naraz(blad):
                    job = _po_odmowie(slug, zid, d, model, marker, blad, log)     # job / ZaDuzoNaraz / JobTrwa
                elif marker.get("wysylam") and not fabryka._blad_trwaly(blad):
                    job = _szukaj_wyslanego(slug, zid, d, model, marker, blad, log)
            if job is not None:
                baza.ustaw_zdjecie_w_toku(slug, zid, job_id=job["job_id"], etap="czeka", wyslano=fabryka._teraz_iso())
                return job
        finally:
            with fabryka._WYSYLANIE_LOCK:
                fabryka._WYSYLANIE.discard(klucz)
        log(f"zdjecie #{zid}: wyslanie nie wyszlo ({str(blad)[:200]})")
        if fabryka._blad_trwaly(blad) or proba >= ile:
            raise blad
        log(f"zdjecie #{zid}: job nie powstal - wysylam jeszcze raz za 10 s (proba {proba + 1}/{ile})")
        time.sleep(10)
    raise blad or dostawcy.BladDostawcy("wyslanie nie wyszlo")


def _po_odmowie(slug, zid, d, model, marker, blad, log):
    """Higgsfield odmowil 'za duzo naraz'. Przed 'wysylam' (np. odmowa przy wgrywaniu) nic nie poszlo -> ZaDuzoNaraz. Po 'wysylam'
    odmowa przyszla z samego create (odpowiedz serwera = job nie powstal), ale dla pewnosci rzut oka na liste jobow po id
    wstawionego zdjecia: jest job -> ten job (bez wysylania); listy nie widac -> jak niepewne wyslanie (_szukaj_wyslanego, potem
    JobTrwa - NIGDY drugi raz); lista jest, a joba nie ma -> ZaDuzoNaraz (zdjecie wraca do kolejki)."""
    if not marker.get("wysylam"):
        raise ZaDuzoNaraz(str(blad))
    if marker.get("obraz_id"):
        try:
            znaleziony = d.znajdz(model, obraz_id=marker["obraz_id"])
        except dostawcy.BladDostawcy as e:
            log(f"zdjecie #{zid}: odmowa ({str(blad)[:120]}), a listy jobow nie widac ({str(e)[:120]}) - nie wysylam drugi raz, "
                f"sprawdzam dalej")
        else:
            if znaleziony:
                _zdarzenie(log, slug, "info", f"zdjecie #{zid}: mimo odmowy job {znaleziony['job_id']} powstal - czekam na niego (bez "
                           f"drugiego wysylania)", zdjecie=zid)
                return znaleziony
            raise ZaDuzoNaraz(str(blad))
    return _szukaj_wyslanego(slug, zid, d, model, marker, blad, log)


def _szukaj_wyslanego(slug, zid, d, model, marker, blad, log):
    """`generate create` zwrocil blad, ale 'wysylam' juz bylo - job MOGL powstac. Szukamy go po id wstawionego zdjecia (po 5 s
    i 15 s). Nie ma -> JobTrwa: NIE wysylamy drugi raz (lista bywa opozniona), wznow_w_toku szuka dalej przez 60 min."""
    if marker.get("obraz_id"):
        for pauza in (5, 15):
            time.sleep(pauza)
            try:
                znaleziony = d.znajdz(model, obraz_id=marker["obraz_id"])
            except dostawcy.BladDostawcy as e:
                log(f"zdjecie #{zid}: nie moge sprawdzic listy jobow ({e})")
                break
            if znaleziony:
                _zdarzenie(log, slug, "info", f"zdjecie #{zid}: job {znaleziony['job_id']} jednak powstal - czekam na niego (bez "
                           f"drugiego wysylania)", zdjecie=zid)
                return znaleziony
    _zdarzenie(log, slug, "uwaga", f"zdjecie #{zid}: wysylanie zwrocilo blad ({str(blad)[:200]}), a joba (jeszcze) nie widac na "
               f"liscie Higgsfield - NIE wysylam drugi raz. Zdjecie czeka w toku; sprawdzam przy kolejnych przebiegach przez "
               f"{fabryka.OKNO_NIEPEWNEGO_WYSLANIA_S // 60} min.", zdjecie=zid)
    raise fabryka.JobTrwa("nie wiadomo, czy job powstal")


def _czekaj(slug, zid, d, jid, timeout, log, stop, gotowy=None):
    """Odpytuje TEN job (0 kr) az do konca. JobTrwa = limit czasu albo STOP (zdjecie zostaje w toku). Nigdy nie wysyla nowego."""
    if gotowy and d.koncowy(gotowy.get("status") or ""):
        return gotowy
    odpytan = max(1, dostawcy.sekundy(timeout) // ODSTEP_S)
    bledy = 0
    for i in range(odpytan + 1):
        if stop is not None and stop.is_set():
            raise fabryka.JobTrwa("zatrzymane - dokoncze pozniej")
        try:
            w = d.sprawdz(jid)
            bledy = 0
        except dostawcy.BladDostawcy as e:
            w = None
            bledy += 1
            if bledy in (1, 5) or bledy % 30 == 0:
                log(f"zdjecie #{zid}: nie moge sprawdzic joba {jid} ({str(e)[:150]}) - probuje dalej, nic nie wysylam")
        if w is not None and d.koncowy(w.get("status") or ""):
            return w
        if i and i % 12 == 0:
            log(f"zdjecie #{zid}: job {jid} jeszcze sie robi ({(w or {}).get('status') or '?'})...")
        if i < odpytan:
            fabryka._spij(ODSTEP_S, stop)
    raise fabryka.JobTrwa(f"job {jid} jeszcze sie robi")


def _dokoncz(slug, zid, d, jid, kl, log, stop, timeout, wynik, gotowy=None):
    try:
        w = _czekaj(slug, zid, d, jid, timeout, log, stop, gotowy)
    except fabryka.JobTrwa as e:
        _zdarzenie(log, slug, "info", f"zdjecie #{zid}: {e} - zostaje w toku, dokoncze przy nastepnym przebiegu (nic nie wysylam "
                   f"drugi raz)", zdjecie=zid)
        wynik["w_toku"].append(zid)
        if stop is not None and stop.is_set():
            wynik["stop"] = "stop"
        return
    kr = _rozlicz(slug, zid, d, w, kl)
    if d.udany(w.get("status") or "") and w.get("urls"):
        _pobierz(slug, zid, d, w, kr, log, wynik)
    else:
        _nie_wyszlo(slug, zid, w, fabryka.powod_odrzucenia(w.get("status"), w.get("blad")) or "inny", log, wynik, kr=kr)


def _rozlicz(slug, zid, d, w, kl):
    """Koszt zakonczonego joba: wycena (w gore) za udany, 0 za odrzucony - raz na job (budzet pamieta rozliczone job_id)."""
    kr = int(d.koszt_joba(w, kl) or 0)
    jid = w.get("job_id")
    if kr:
        juz = baza.rozliczony(jid, d.NAZWA)
        wydano = baza.dopisz_wydatek(kr, d.NAZWA, job_id=jid)
        if not juz:
            baza.dziennik_zapisz("kredyty", f"zdjecie #{zid}: {kr} kr (higgsfield podmiana postaci), dzis {wydano}/"
                                 f"{baza.limit_dzienny(d.NAZWA)}", modelka=slug, zdjecie=zid, kredyty=kr, dostawca=d.NAZWA)
    baza.ustaw_zdjecie(slug, zid, koszt=kr, job_id=jid)
    return kr


def _pobierz(slug, zid, d, w, kr, log, wynik):
    urls = w.get("urls") or []
    z = baza.zdjecie(slug, zid)
    rozsz = os.path.splitext(urls[0].split("?")[0])[1].lower()
    if rozsz not in baza.ROZSZERZENIA_OBRAZU:
        rozsz = ".png"
    cel = os.path.join(baza.folder_zdjec(slug), f"{zid:03d}_swap_{z.get('zrodlo_nazwa') or 'zdjecie'}{rozsz}")
    try:
        d.pobierz(urls[0], cel)
    except Exception as e:
        wiek = fabryka._wiek_s((z.get("w_toku") or {}).get("od"))
        if wiek is not None and wiek > fabryka.MAX_GODZIN_W_TOKU * 3600:
            baza.ustaw_zdjecie(slug, zid, status="blad", w_toku=None, wynik_url=urls[0], powod="inny",
                               notatki=f"Pobranie nie wychodzi od {fabryka.MAX_GODZIN_W_TOKU} h ({e}) - pobierz recznie: {urls[0]}"[:1000])
            wynik["bledy"].append(zid)
            _zdarzenie(log, slug, "blad", f"zdjecie #{zid}: pobranie nie wychodzi ({e}) - pobierz recznie: {urls[0]}", zdjecie=zid)
            return
        # job zaplacony i gotowy - zostaje w toku: nastepny przebieg pobierze go jeszcze raz (bez nowego joba)
        _zdarzenie(log, slug, "blad", f"zdjecie #{zid}: pobranie nie wyszlo ({e}) - sprobuje jeszcze raz przy nastepnym przebiegu",
                   zdjecie=zid)
        wynik["w_toku"].append(zid)
        return
    baza.ustaw_zdjecie(slug, zid, status="gotowe", plik=cel, w_toku=None, wynik_url=urls[0], koszt=kr, notatki="", powod=None)
    wynik["zrobione"] += 1
    wynik["pliki"].append(cel)
    _zdarzenie(log, slug, "ok", f"zdjecie #{zid}: GOTOWE ({kr} kr, podmiana postaci) -> {cel}", zdjecie=zid, plik=cel)


# Komunikaty dla usera (panel pokazuje je przy zdjeciu) - po polsku, bez ponownego wysylania
NOTATKA_NSFW = ("Filtr tresci Higgsfield odrzucil to zdjecie (NSFW) - kredyty wrocily, nic nie wysylam drugi raz. Sprobuj innego "
                "zdjecia (mniej skory, bez bielizny/kostiumu kapielowego), stroju albo modelu.")
NOTATKA_IP = ("Model wykryl znana postac albo marke (ip_detected) - kredyty wrocily, nic nie wysylam drugi raz. Sprawdz, czy na "
              "zdjeciu nie ma logo, celebryty albo postaci z filmu.")


def _nie_wyszlo(slug, zid, w, powod, log, wynik, blad="", kr=0):
    blad = blad or (w or {}).get("blad") or ""
    if powod == "nsfw":
        notatki = NOTATKA_NSFW
        wynik["odrzucone"].append(zid)
    elif powod == "ip":
        notatki = NOTATKA_IP
        wynik["odrzucone"].append(zid)
    elif w is not None and dostawcy.dostawca("higgsfield").udany((w or {}).get("status") or ""):
        notatki = (f"Job {w.get('job_id')} skonczyl sie, ale nie znajduje linku do zdjecia - NIE wysylam drugi raz. Sprawdz w apce "
                   f"Higgsfield (lista generacji).")
    else:
        notatki = (f"Nie wyszlo ({(blad or (w or {}).get('status') or '?')[:300]}) - nic nie wysylam drugi raz. Popraw przyczyne i "
                   f"kliknij Generuj jeszcze raz.")
    if (w or {}).get("job_id"):
        notatki += f" (job {w['job_id']})"
    baza.ustaw_zdjecie(slug, zid, status="blad", w_toku=None, powod=powod, notatki=notatki[:1000], koszt=kr,
                       **({"job_id": w["job_id"]} if (w or {}).get("job_id") else {}))
    wynik["bledy"].append(zid)
    _zdarzenie(log, slug, "blad", f"zdjecie #{zid}: {notatki}", zdjecie=zid, powod=powod)


def _niepewne(slug, zid, m, przyczyna, log, wynik):
    """Nie wiadomo, czy przerwane wysylanie utworzylo job, i nie ma juz sensu czekac: blad z prosba o sprawdzenie w apce - BEZ
    drugiego wysylania. Wycena idzie do limitu dnia na wszelki wypadek."""
    k = int(m.get("koszt") or 0)
    if k:
        baza.dopisz_wydatek(k, "higgsfield", job_id=f"niepewne:zdjecie-{slug}-{zid}")
    notatki = (f"Wysylanie przerwane ({przyczyna}) - nie wiadomo, czy zdjecie powstalo. Sprawdz w apce Higgsfield (lista generacji), "
               f"czy go nie ma - jesli jest, pobierz je stamtad." + (f" {k} kr wliczone do dzisiejszego limitu na wszelki wypadek."
                                                                    if k else ""))
    baza.ustaw_zdjecie(slug, zid, status="blad", w_toku=None, powod="inny", notatki=notatki[:1000])
    wynik["bledy"].append(zid)
    _zdarzenie(log, slug, "blad", f"zdjecie #{zid}: {notatki}", zdjecie=zid)


# ---------------- wznawianie (restart panelu, timeout, STOP) ----------------

def wznow_w_toku(slug, log=None, stop=None, timeout=CZAS_NA_ZDJECIE, wynik=None):
    """Dokancza zdjecia persony w toku: job_id znany -> odpytuje TEN job; 'wysylam' bez job_id -> szuka joba po id wstawionego
    zdjecia (60 min, potem 'sprawdz w apce'); bez 'wysylam' -> nic nie poszlo, zdjecie 'nie wyszlo' (user kliknie jeszcze raz).
    Nigdy nie wysyla nowego joba. Rownolegle, kazde zdjecie pod jego blokada (obslugiwane juz przez kogos innego - pominiete).
    W panelu (dziala dyspozytor KOLEJKA) tylko go budzi (zdejmuje STOP) i wraca od razu - dokancza w tle."""
    log = log or _log
    wynik = wynik if wynik is not None else _nowy_wynik()
    w_toku = baza.zdjecia_w_toku(slug)
    if not w_toku:
        return wynik
    if KOLEJKA.dziala():
        KOLEJKA.obudz(wznawiaj=True)
        wynik["w_toku"] = [z["id"] for z in w_toku]
        return wynik
    _Obsluga(log=log, timeout=timeout, tylko={(slug, z["id"]) for z in w_toku}, stop=stop, wynik=wynik).do_konca()
    return wynik


def _wznow_jedno(slug, z, d, log, stop, timeout, wynik):
    zid = z["id"]
    m = z.get("w_toku") or {}
    jid = m.get("job_id")
    kl = int(m.get("koszt") or 0)
    gotowy = None
    if not jid:
        if not m.get("wysylam") and z.get("kolejka"):
            # zdjecie z kolejki (3.3) przerwane PRZED 'wysylam' (zamkniety panel w trakcie sprawdzania ceny / wgrywania) - nic nie
            # poszlo do Higgsfield, wiec wraca do kolejki i pojdzie normalnie (cena i bezpieczniki jeszcze raz)
            baza.zwroc_zdjecie_do_kolejki(slug, zid, notatki="Wysylanie przerwane, zanim cokolwiek poszlo - wraca do kolejki "
                                                             "(nic nie zeszlo).")
            _zdarzenie(log, slug, "info", f"zdjecie #{zid}: wysylanie nie zaczelo sie przed przerwaniem - wraca do kolejki (nic nie "
                       f"zeszlo)", zdjecie=zid)
            return
        if not m.get("wysylam"):
            baza.ustaw_zdjecie(slug, zid, status="blad", w_toku=None, powod="inny",
                               notatki="Wysylanie przerwane, zanim cokolwiek poszlo do Higgsfield - nic nie zeszlo. Kliknij Generuj "
                                       "jeszcze raz.")
            wynik["bledy"].append(zid)
            _zdarzenie(log, slug, "info", f"zdjecie #{zid}: wysylanie nie zaczelo sie przed przerwaniem - nic nie zeszlo", zdjecie=zid)
            return
        od = m.get("wysylam_od") or m.get("od")
        wiek = fabryka._wiek_s(od)
        try:
            znaleziony = d.znajdz(m.get("model") or "", obraz_id=m["obraz_id"]) if m.get("obraz_id") else None
        except dostawcy.BladDostawcy as e:
            if wiek is not None and wiek > fabryka.MAX_GODZIN_W_TOKU * 3600:
                _niepewne(slug, zid, m, f"od {fabryka.MAX_GODZIN_W_TOKU} h nie da sie sprawdzic listy jobow: {e}", log, wynik)
                return
            log(f"zdjecie #{zid}: nie moge sprawdzic, czy przerwane wysylanie utworzylo job ({e}) - sprobuje pozniej, nic nie wysylam")
            wynik["w_toku"].append(zid)
            return
        if not znaleziony:
            okno = fabryka.OKNO_NIEPEWNEGO_WYSLANIA_S
            if wiek is None or wiek < okno:
                log(f"zdjecie #{zid}: wysylanie przerwane {int(wiek or 0)} s temu, joba nie widac na liscie - czekam (do "
                    f"{okno // 60} min), nic nie wysylam drugi raz")
                wynik["w_toku"].append(zid)
                return
            _niepewne(slug, zid, m, f"po {okno // 60} min joba dalej nie widac na liscie", log, wynik)
            return
        jid = znaleziony["job_id"]
        baza.ustaw_zdjecie_w_toku(slug, zid, job_id=jid, etap="czeka")
        _zdarzenie(log, slug, "info", f"zdjecie #{zid}: odnaleziony job {jid} z przerwanego wysylania - czekam na niego", zdjecie=zid)
        gotowy = znaleziony if d.koncowy(znaleziony.get("status") or "") else None
    else:
        _zdarzenie(log, slug, "info", f"zdjecie #{zid}: wznawiam - job {jid} byl juz wyslany, sprawdzam go (bez wysylania nowego)",
                   zdjecie=zid)
    wiek = fabryka._wiek_s(m.get("od"))
    if wiek is not None and wiek > fabryka.MAX_GODZIN_W_TOKU * 3600 and not gotowy:
        try:
            teraz = d.sprawdz(jid)
        except dostawcy.BladDostawcy:
            teraz = {"job_id": jid, "status": "", "blad": "nie odpowiada"}
        if not d.koncowy(teraz.get("status") or ""):
            if kl:
                baza.dopisz_wydatek(kl, d.NAZWA, job_id=jid)       # job byl wyslany - na wszelki wypadek (raz na job)
            _nie_wyszlo(slug, zid, dict(teraz, blad=f"job nie skonczyl sie w {fabryka.MAX_GODZIN_W_TOKU} h - "
                                                    f"{fabryka.sprawdz_w_apce()}"), "inny", log, wynik, kr=kl)
            return
        gotowy = teraz
    _dokoncz(slug, zid, d, jid, kl, log, stop, timeout, wynik, gotowy=gotowy)


def wznow_wszystkie(log=None, stop=None, timeout=CZAS_NA_ZDJECIE):
    """Start panelu: dokoncz zdjecia w toku wszystkich person. {slug: wynik} (tylko persony, ktore cos mialy)."""
    wyniki = {}
    for slug in baza.lista_modelek():
        if baza.zdjecia_w_toku(slug):
            wyniki[slug] = wznow_w_toku(slug, log=log, stop=stop, timeout=timeout)
    return wyniki


# ---------------- dyspozytor panelu (watek w tle), STOP, stan kolejki (3.3) ----------------

class _Dyspozytor:
    """Panel: watek w tle - co ODSTEP_KOLEJKI_S (i od razu po "Generuj" / koncu zdjecia) obrot _Obsluga dla wszystkich person:
    wysyla z kolejki tyle, ile wolnych miejsc, i dokancza osierocone zdjecia w toku. Niezalezny od zadan konsoli (rolki, autopilot),
    wiec zdjecia i rolki ida obok siebie. Bez dzialajacego dyspozytora (CLI, testy) kolejke obsluguje generuj()."""

    def __init__(self):
        self.lock = threading.Lock()
        self.watek = None
        self.obsluga = None
        self.koniec = False
        self.zatrzymane = False     # po STOP: osierocone w toku czekaja na nastepne sprawdzenie (Generuj, autopilot, restart)
        self.zamykanie = False      # panel sie zamyka: przejete, a jeszcze nie wyslane zdjecia wracaja do kolejki

    def dziala(self):
        w, o = self.watek, self.obsluga
        return bool(w and w.is_alive() and o is not None and not o.katalog_zmieniony() and not self.koniec)

    def uruchom(self, log=None):
        """Start watku (panel: przy starcie i przy "Generuj"). False = juz dziala."""
        with self.lock:
            if self.watek and self.watek.is_alive() and not self.koniec:
                return False
            self.koniec = False
            self.zatrzymane = False
            self.zamykanie = False
            self.obsluga = _Obsluga(log=log)
            self.watek = threading.Thread(target=self._petla, args=(self.obsluga,), daemon=True, name="kolejka-zdjec")
            self.watek.start()
        return True

    def _petla(self, o):
        while not self.koniec and not o.katalog_zmieniony():
            try:
                o.krok(wznawiaj=not self.zatrzymane)
            except Exception as e:      # jeden zly obrot nie moze zatrzymac kolejki
                traceback.print_exc()
                o.log(f"kolejka zdjec: {type(e).__name__}: {e}")
            o.budzik.wait(ODSTEP_KOLEJKI_S)
            o.budzik.clear()

    def obudz(self, wznawiaj=False):
        """Nowa praca (Generuj, przebieg autopilota): obrot od razu. wznawiaj=True zdejmuje STOP (nowe watki dostaja swiezy STOP,
        osierocone w toku dokanczamy od razu). False = dyspozytor nie dziala."""
        o = self.obsluga
        if o is None or not self.dziala():
            return False
        if wznawiaj:
            self.zatrzymane = False
            if o.stop.is_set():
                o.stop = threading.Event()
            with o.lock:
                o.nie_przed.clear()
        o.budzik.set()
        return True

    def zatrzymaj(self):
        """STOP: watki przestaja czekac (job zostaje w toku), osieroconych nie dokanczamy do nastepnego sprawdzenia. Kolejke
        anuluje zatrzymaj() modulu."""
        self.zatrzymane = True
        o = self.obsluga
        if o is not None:
            o.stop.set()
            o.budzik.set()

    def wstrzymaj(self):
        """Panel sie zamyka: nic nowego nie przejmujemy z kolejki (zostaje na nastepny start), przejete, a jeszcze nie wyslane wracaja
        do kolejki; wysylane koncza wysylanie (na nie czeka /api/zamknij), zdjecia w toku czekaja dalej."""
        self.zamykanie = True
        o = self.obsluga
        if o is not None:
            o.wstrzymane = True

    def zakoncz(self, czekaj_s=10):
        """Konczy watek dyspozytora i watki zdjec (STOP - job zostaje w toku). Testy (sprzatanie po tescie)."""
        with self.lock:
            w, o = self.watek, self.obsluga
            self.koniec = True
        if o is not None:
            o.wstrzymane = True
            o.stop.set()
            o.budzik.set()
        if w is not None:
            w.join(czekaj_s)
        if o is not None:
            for t in list(o.watki.values()):
                t.join(czekaj_s)
        with self.lock:
            self.watek = None
            self.obsluga = None
            self.zatrzymane = False
            self.zamykanie = False


KOLEJKA = _Dyspozytor()


def zatrzymaj(log=None):
    """STOP na stronie Zdjecia (wszystkie persony): zdjecia z kolejki -> 'anulowane' (nic nie poszlo, 0 kr), czekanie na joby w toku
    przerwane. Przyjete joby NIE sa anulowane - dokoncza sie przy nastepnym sprawdzeniu (kolejne Generuj, przebieg autopilota,
    restart panelu, `python fabryka.py wznow`). Zwraca {"anulowane": [[slug, id], ...], "w_toku": n}."""
    KOLEJKA.zatrzymaj()
    anulowane, w_toku = [], 0
    for slug in baza.lista_modelek():
        anulowane += [[slug, zid] for zid in baza.anuluj_zdjecia_w_kolejce(slug, NOTATKA_STOP)]
        w_toku += len(baza.zdjecia_w_toku(slug))
    tekst = (f"zdjecia: STOP - z kolejki anulowane {len(anulowane)} (nic nie poszlo, 0 kr), w toku {w_toku} (juz przyjete - "
             f"dokoncza sie przy nastepnym sprawdzeniu)")
    (log or _log)(tekst)
    baza.dziennik_zapisz("info", tekst)
    return {"anulowane": anulowane, "w_toku": w_toku}


def wysylane(slug, zid):
    """Czy to zdjecie jest wlasnie wysylane (upload + create) - wtedy nie wolno go 'przestac czekac'."""
    with fabryka._WYSYLANIE_LOCK:
        return ("zdjecie", slug, int(zid)) in fabryka._WYSYLANIE


def stan_kolejki(slug=None):
    """Dla panelu: zdjecia w toku i w kolejce (wszystkie persony i `slug`), limit naraz, czy dyspozytor dziala, czy po STOP."""
    w = {"w_toku": 0, "w_kolejce": 0}
    p = {"w_toku": 0, "w_kolejce": 0}
    for s, z in _swap_na_dysku():
        k = "w_toku" if z.get("status") == "w_toku" else "w_kolejce"
        w[k] += 1
        if s == slug:
            p[k] += 1
    return dict(w, limit=rownolegle(), dziala=KOLEJKA.dziala(), zatrzymane=bool(KOLEJKA.zatrzymane), persona=p)
