# -*- coding: utf-8 -*-
"""Panel webowy rolki-ai (Flask, :5077) - odpalasz panel.bat i klikasz w przegladarce.

Kontrakt API: API.md. Logika produkcji siedzi w fabryka.py / zdjecia.py / lipsync.py / autopilot.py -
panel tylko ja odpala w tle (jedno zadanie naraz, wspolna konsola) i pokazuje stan.
"""
import json
import mimetypes
import os
import re
import sys
import threading
import time
import traceback

from flask import Flask, abort, jsonify, render_template, request, send_file

import autopilot
import baza
import dostawcy
import fabryka
import asystent
import scenariusz
import sekrety
import zdjecia_swap

if sys.platform == "win32":
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")

KATALOG = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(KATALOG, "templates"), static_folder=os.path.join(KATALOG, "static"))
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024   # 2 GB uploadu (filmiki zrodlowe)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0                 # po aktualizacji przegladarka ma brac nowy app.js, nie z cache

PORT = 5077
WERSJA = "3.3"
CACHE_SALDA_S = 60
CACHE_MODELI_S = 600


def _ok(**dane):
    return jsonify({"ok": True, **dane})


def _blad(msg, kod=400):
    return jsonify({"ok": False, "blad": str(msg)}), kod


class Zajete(Exception):
    pass


# ---------------- zadania w tle (jedno naraz, wspolna konsola) ----------------

class Konsola:
    """Jedno zadanie naraz: reczne (watek) albo przebieg autopilota (w watku petli). Log w pamieci."""

    def __init__(self):
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.log = []
        self.stan = {"trwa": False, "typ": None, "modelka": None, "start": None, "koniec": None, "wynik": None, "blad": None}
        self.watek = None

    def dopisz(self, linia):
        linia = str(linia)
        self.log.append(time.strftime("%H:%M:%S ") + linia)
        if len(self.log) > 2000:
            del self.log[:500]
        print(linia, flush=True)

    def opis(self):
        return dict(self.stan, log_dlugosc=len(self.log))

    def _start(self, typ, slug):
        if not self.lock.acquire(blocking=False):
            raise Zajete(f"trwa: {self.stan.get('typ') or 'inne zadanie'}")
        self.stop.clear()
        self.log = []
        self.stan.update({"trwa": True, "typ": typ, "modelka": slug, "start": time.time(), "koniec": None, "wynik": None, "blad": None})

    def _koniec(self, wynik=None, blad=None):
        self.stan.update({"trwa": False, "koniec": time.time(), "wynik": wynik, "blad": blad})
        self.lock.release()

    def uruchom_tutaj(self, typ, slug, fn):
        """Wykonuje fn(log, stop) w biezacym watku (autopilot). Zwraca wynik; wyjatki przepuszcza."""
        self._start(typ, slug)
        try:
            wynik = fn(self.dopisz, self.stop)
        except fabryka.Przerwano as e:
            self._koniec(blad=f"zatrzymane: {e}")
            raise
        except BaseException as e:
            self._koniec(blad=f"{type(e).__name__}: {e}")
            raise
        self._koniec(wynik=_serializowalne(wynik))
        return wynik

    def uruchom(self, typ, slug, fn):
        """Odpala fn(log, stop) w watku. 409, gdy cos trwa."""
        self._start(typ, slug)

        def _w_tle():
            try:
                wynik = fn(self.dopisz, self.stop)
                self._koniec(wynik=_serializowalne(wynik))
            except fabryka.Przerwano as e:
                self.dopisz(f"[STOP] {e}")
                self._koniec(blad=f"zatrzymane: {e}")
            except BaseException as e:   # takze SystemExit - inaczej blokada zostalaby na zawsze
                traceback.print_exc()
                self.dopisz(f"[BLAD] {type(e).__name__}: {e}")
                self._koniec(blad=f"{type(e).__name__}: {e}")
        self.watek = threading.Thread(target=_w_tle, daemon=True, name=f"zadanie-{typ}")
        self.watek.start()
        return self.opis()


def _serializowalne(w):
    try:
        json.dumps(w)
        return w
    except (TypeError, ValueError):
        return str(w)


konsola = Konsola()

# ---------------- autopilot (petla w tle) ----------------

_autopilot = {"watek": None, "stop": threading.Event()}


def _autopilot_wlaczony():
    w = _autopilot["watek"]
    return bool(w and w.is_alive())


def _przebieg_z_konsoli(log, stop):
    """Przebieg autopilota opakowany w konsole (wspolna blokada z zadaniami recznymi)."""
    try:
        return konsola.uruchom_tutaj("autopilot", None, lambda l, s: autopilot.przebieg_wszystkich(log=l, stop=s))
    except Zajete:
        autopilot._log("cos trwa w panelu - przebieg autopilota za chwile")
        return None


def _petla_autopilota():
    autopilot.petla(stop=_autopilot["stop"], przebieg_fn=_przebieg_z_konsoli)


def autopilot_start():
    if _autopilot_wlaczony():
        return
    _autopilot["stop"] = threading.Event()
    w = threading.Thread(target=_petla_autopilota, daemon=True, name="autopilot")
    _autopilot["watek"] = w
    w.start()
    baza.dziennik_zapisz("info", "autopilot wlaczony (panel)")


def autopilot_stop():
    if not _autopilot_wlaczony():
        return
    _autopilot["stop"].set()
    konsola.stop.set()
    baza.dziennik_zapisz("info", "autopilot wylaczony (panel)")


def _stan_autopilota():
    return dict(autopilot.STAN, wlaczony=_autopilot_wlaczony())


# ---------------- cache sald i modeli ----------------

_saldo = {}
_saldo_lock = threading.Lock()
_saldo_watki = {}
_modele_cache = {}
_konta_test = {}
CZEKAJ_NA_SALDO_S = 3   # tyle /api/stan czeka na swieze saldo; dluzej = oddaje stare i dociaga w tle


NAZWY_KONT_Z_KLUCZEM = {"yapper": "yapper.so", "wavespeed": "WaveSpeed", "elevenlabs": "ElevenLabs"}


def _pobierz_saldo(nazwa):
    d = None
    try:
        d = dostawcy.dostawca(nazwa)
        if nazwa in NAZWY_KONT_Z_KLUCZEM and not sekrety.klucz(nazwa):
            raise dostawcy.BrakKlucza(f"brak klucza API {NAZWY_KONT_Z_KLUCZEM[nazwa]} (panel -> Konta)")
        if hasattr(d, "saldo_szczegoly"):
            wpis = dict(d.saldo_szczegoly(), blad=None, czas=time.time())      # np. ElevenLabs: zostalo/limit znakow, plan
        else:
            wpis = {"kredyty": d.saldo(), "blad": None, "czas": time.time()}
        wpis.setdefault("jednostka", getattr(d, "JEDNOSTKA", "kr"))
    except dostawcy.BladDostawcy as e:
        wpis = {"kredyty": None, "blad": str(e), "czas": time.time(), "jednostka": getattr(dostawcy.dostawca(nazwa), "JEDNOSTKA", "kr")}
        # klucz ElevenLabs bez prawa odczytu konta: salda nie widac, ale TTS dziala - to nie blad (pastylka zielona "dziala")
        if nazwa == "elevenlabs" and hasattr(d, "stan_klucza") and d.stan_klucza()[0] == "ok":
            wpis.update(blad=None, dziala=True)
    except Exception as e:
        wpis = {"kredyty": None, "blad": f"{type(e).__name__}: {e}", "czas": time.time()}
    with _saldo_lock:
        _saldo[nazwa] = wpis
    return wpis


def _saldo_dostawcy(nazwa, wymus=False):
    """Saldo z cache (60 s). Przeterminowane odswieza watek w tle; czekamy na niego max CZEKAJ_NA_SALDO_S,
    potem oddajemy stare (CLI/API bywa wolne, a panel pyta co 5 s)."""
    with _saldo_lock:
        wpis = _saldo.get(nazwa)
        swieze = wpis and not wymus and time.time() - wpis["czas"] < CACHE_SALDA_S
        if swieze:
            return wpis
        w = _saldo_watki.get(nazwa)
        if not (w and w.is_alive()):
            w = threading.Thread(target=_pobierz_saldo, args=(nazwa,), daemon=True, name=f"saldo-{nazwa}")
            _saldo_watki[nazwa] = w
            w.start()
    w.join(CZEKAJ_NA_SALDO_S)
    with _saldo_lock:
        return _saldo.get(nazwa) or {"kredyty": None, "blad": None, "czas": 0, "laduje": True}


def _salda(wymus=False, dostawca_aktywnej=None):
    """Salda do paska w panelu: Higgsfield zawsze, yapper.so / WaveSpeed (centy USD) gdy jest klucz albo robi rolki aktywnej
    persony, ElevenLabs (znaki TTS) gdy jest klucz."""
    nazwy = ["higgsfield"]
    if dostawca_aktywnej == "yapper" or sekrety.klucz("yapper"):
        nazwy.append("yapper")
    if dostawca_aktywnej == "wavespeed" or sekrety.klucz("wavespeed"):
        nazwy.append("wavespeed")
    if sekrety.klucz("elevenlabs"):
        nazwy.append("elevenlabs")
    return {n: _saldo_dostawcy(n, wymus) for n in nazwy}


def _normalizuj_model(m, dostawca):
    if not isinstance(m, dict):
        return {"id": str(m), "nazwa": str(m), "typ": "", "opis": ""}
    ident = m.get("job_type") or m.get("id") or m.get("slug") or m.get("name") or ""
    return {
        "id": str(ident),
        "nazwa": str(m.get("name") or m.get("display_name") or m.get("title") or ident),
        "typ": str(m.get("type") or m.get("media_type") or m.get("processType") or m.get("category") or "").lower(),
        "opis": str(m.get("description") or m.get("opis") or "")[:200],
    }


def _lista_modeli(dostawca, typ=None, odswiez=False):
    klucz = f"{dostawca}:{typ or ''}"
    wpis = _modele_cache.get(klucz)
    if wpis and not odswiez and time.time() - wpis["czas"] < CACHE_MODELI_S:
        return wpis["modele"]
    if dostawca == "sync":
        from dostawcy import sync_so
        surowe = sync_so.modele()
    elif dostawca == "yapper":
        from dostawcy import yapper
        surowe = yapper.modele_wideo() if (typ in (None, "", "video")) else yapper.modele()
    elif dostawca == "wavespeed":
        from dostawcy import wavespeed
        surowe = wavespeed.modele()          # modele, ktore fabryka umie wyslac (bez zapytania do API, bez klucza)
    else:
        from dostawcy import higgsfield
        surowe = higgsfield.modele(typ)
    modele = [_normalizuj_model(m, dostawca) for m in surowe]
    if typ and dostawca == "higgsfield":
        modele = [m for m in modele if not m["typ"] or typ in m["typ"]]
    _modele_cache[klucz] = {"czas": time.time(), "modele": modele}
    return modele


# ---------------- pliki (bezpieczne serwowanie) ----------------

def _dozwolone_foldery():
    foldery = [baza.KATALOG_MODELEK, baza.KATALOG_BIBLIOTEKI]      # biblioteka strojow: tylko miniatury (podglad w panelu)
    for slug in baza.lista_modelek():
        ust = baza.ustawienia_modelki(slug)
        for k in ("zrodla_dir", "wyniki_dir", "zdjecia_dir"):
            if (ust.get(k) or "").strip():
                foldery.append(ust[k].strip())
    return [os.path.realpath(f) for f in foldery]


def _plik_dozwolony(sciezka):
    if not sciezka:
        return False
    real = os.path.realpath(sciezka)
    for f in _dozwolone_foldery():
        try:
            if os.path.commonpath([real, f]) == f:
                return True
        except ValueError:
            continue
    return False


def _url_pliku(sciezka):
    if not sciezka or not os.path.isfile(sciezka):
        return None
    from urllib.parse import quote
    return "/api/plik?s=" + quote(sciezka)


@app.route("/api/plik")
def api_plik():
    sciezka = request.args.get("s", "")
    if not _plik_dozwolony(sciezka) or not os.path.isfile(sciezka):
        abort(404)
    typ = mimetypes.guess_type(sciezka)[0] or "application/octet-stream"
    return send_file(sciezka, mimetype=typ, conditional=True)


# ---------------- strony ----------------

@app.route("/")
def index():
    return render_template("index.html", wersja=WERSJA)


@app.route("/widget")
def widget():
    return render_template("widget.html", wersja=WERSJA)


@app.route("/static/rolki.ico")
def ikona():
    return send_file(os.path.join(KATALOG, "static", "rolki.ico"), mimetype="image/x-icon")


# ---------------- stan ogolny ----------------

def _aktywna():
    aktywna = baza.aktywna_modelka()
    return aktywna if aktywna in baza.lista_modelek() else None


def _wymaga_modelki():
    aktywna = _aktywna()
    if not aktywna:
        raise ValueError("Brak aktywnej modelki.")
    return aktywna


def _konta_skrot(salda):
    hf = salda.get("higgsfield") or {}
    konta = {"higgsfield": {"ok": hf.get("kredyty") is not None, "komunikat": "zalogowany" if hf.get("kredyty") is not None else (hf.get("blad") or "")}}
    for d, info in sekrety.stan().items():
        t = _konta_test.get(d) or {}
        konta[d] = {"jest": info["jest"], "ok": t.get("dziala"), "komunikat": t.get("komunikat", "")}
    return konta


@app.route("/api/stan")
def api_stan():
    aktywna = _aktywna()
    modelki = []
    for slug in baza.lista_modelek():
        ust = baza.ustawienia_modelki(slug)
        modelki.append({"slug": slug, "nazwa": baza.profil_modelki(slug).get("nazwa") or slug,
                        "autopilot": bool(ust.get("autopilot")), "dostawca": ust.get("dostawca") or "higgsfield",
                        "statystyki": baza.statystyki_pomyslow(slug), "autopilot_stan": baza.autopilot_stan(slug),
                        "rolki_dzis": len(baza.pomysly_z_dnia(slug)),
                        "avatar_url": _avatar(slug), "telegram_czat": ust.get("telegram_czat") or "",
                        "foldery": _foldery(slug)})
    stan = fabryka.stan_modelki(aktywna) if aktywna else None
    salda = _salda(wymus=request.args.get("saldo") == "1", dostawca_aktywnej=(stan or {}).get("dostawca"))
    ostatnie = baza.dziennik_ostatnie(1)
    jakosc = fabryka.jakosc_i_koszt(aktywna) if aktywna else None
    dzis = _dzis(aktywna)
    if jakosc and jakosc["koszt_rolki"]:
        # ile rolek jeszcze "wejdzie" dzis: limit dzienny (z rezerwa rolek w toku) i saldo (ponad minimum), co nizsze -
        # Higgsfield w kredytach, persona na WaveSpeed w centach USD (bez limitu WaveSpeed nie wejdzie zadna)
        ws = jakosc.get("dostawca") == "wavespeed"
        konto = "wavespeed" if ws else "higgsfield"
        limit, wydano = baza.limit_dzienny(konto), baza.wydano_z_rezerwa(konto)
        zostalo = [(limit - wydano) // jakosc["koszt_rolki"]] if limit else ([0] if ws else [])
        kredyty = (salda.get(konto) or {}).get("kredyty")
        if kredyty is not None:
            min_k = fabryka.bezpiecznik(baza.ustawienia_modelki(aktywna), konto)[0]
            zostalo.append(max(0, int(kredyty) - int(min_k)) // jakosc["koszt_rolki"])
        dzis["rolek_zostalo"] = max(0, min(zostalo)) if zostalo else None
    try:
        zdjecia_kolejka = zdjecia_swap.stan_kolejki(aktywna)
    except Exception as e:          # stan kolejki zdjec to dodatek - nie moze wywalic /api/stan
        zdjecia_kolejka = {"w_toku": 0, "w_kolejce": 0, "blad": str(e)}
    try:
        z_promptu = autopilot.stan_z_promptu(wlaczony=_autopilot_wlaczony())
    except Exception as e:
        z_promptu = {"tekst": "", "blad": str(e)}
    return _ok(aktywna=aktywna, modelki=modelki, stan=stan, saldo=salda, autopilot=_stan_autopilota(),
               autopilot_stan=baza.autopilot_stan(aktywna) if aktywna else None, telegram=_stan_telegramu(),
               dzis=dzis, zadanie=konsola.opis(), konta=_konta_skrot(salda), jakosc=jakosc,
               foldery=_foldery(aktywna) if aktywna else None, pulpit=baza.pulpit(),
               dziennik_ostatni=ostatnie[-1] if ostatnie else None, wersja=WERSJA,
               zdjecia_kolejka=zdjecia_kolejka, autopilot_z_promptu=z_promptu)


@app.route("/api/ustawienia/preset", methods=["POST"])
def api_preset_jakosci():
    """Zestaw 'Jakosc i koszt': {"nazwa": "oszczednie"|"normalnie"|"najlepiej"} -> ustawia resolution + max_sekund_rolki."""
    try:
        slug = _wymaga_modelki()
        fabryka.ustaw_preset_jakosci(slug, (request.json or {}).get("nazwa", ""))
    except ValueError as e:
        return _blad(e)
    return _ok(ustawienia=baza.ustawienia_modelki(slug), jakosc=fabryka.jakosc_i_koszt(slug))


def _foldery(slug):
    """Foldery persony dla panelu (gdzie wrzucasz, gdzie wychodzi) - tworzy je, gdy ich nie ma."""
    try:
        return {"wrzutnia": baza.folder_zrodel(slug), "gotowe": baza.folder_gotowych(slug), "zdjecia": baza.folder_zdjec(slug)}
    except OSError as e:
        return {"wrzutnia": "", "gotowe": "", "zdjecia": "", "blad": str(e)}


@app.route("/api/folder/otworz", methods=["POST"])
def api_otworz_folder():
    """Otwiera folder persony w Eksploratorze Windows (co: wrzutnia | gotowe | zdjecia | pulpit | modelka | referencje | stroje | audio)."""
    dane = request.json or {}
    co = (dane.get("co") or "wrzutnia").strip()
    try:
        if co == "pulpit":
            sciezka = baza.pulpit()
            os.makedirs(sciezka, exist_ok=True)
        else:
            slug = _wymaga_modelki()
            sciezka = {"wrzutnia": baza.folder_zrodel, "gotowe": baza.folder_gotowych, "zdjecia": baza.folder_zdjec,
                       "modelka": baza.folder_modelki, "referencje": baza.folder_referencji, "stroje": baza.folder_strojow,
                       "audio": baza.folder_audio}[co](slug)
    except (ValueError, KeyError) as e:
        return _blad(e if isinstance(e, ValueError) else f"Nieznany folder '{co}'.")
    if not hasattr(os, "startfile"):
        return _blad(f"Otwieranie folderu dziala tylko na Windows. Folder: {sciezka}")
    try:
        os.startfile(sciezka)   # noqa: S606 - lokalny panel, sciezka z naszych ustawien
    except OSError as e:
        return _blad(f"Nie moge otworzyc {sciezka}: {e}")
    return _ok(sciezka=sciezka)


def _avatar(slug):
    """Pierwsze zdjecie referencyjne persony jako avatar (albo None)."""
    try:
        refs = baza.sciezki_referencji(slug)
        return _url_pliku(refs[0]) if refs else None
    except Exception:
        return None


def _stan_telegramu():
    try:
        from dostawcy import telegram
        s = telegram.stan()
        return {"skonfigurowany": telegram.skonfigurowany(), "sparowany": telegram.sparowany(), "czat": s.get("czat") or "",
                "czaty": [{"nazwa": i.get("nazwa") or c, "glowny": bool(i.get("glowny"))} for c, i in telegram.czaty().items()]}
    except Exception as e:
        return {"skonfigurowany": False, "sparowany": False, "czat": "", "czaty": [], "blad": str(e)}


def _dzis(aktywna):
    """Podsumowanie dnia dla panelu: rolki, zdjecia, kredyty per dostawca, problemy."""
    dzien = baza._dzis()
    rolki = sum(len(baza.pomysly_z_dnia(s)) for s in baza.lista_modelek())
    zdjecia = sum(len(baza.zdjecia_z_dnia(s)) for s in baza.lista_modelek())
    bledy = len([w for w in baza.dziennik_ostatnie(500, typ="blad") if baza.dzien_lokalny(w.get("czas")) == dzien])
    return {"rolki": rolki, "zdjecia": zdjecia, "bledy": bledy,
            "kredyty": {d: baza.wydano_dzis(d) for d in ("higgsfield", "yapper", "sync", "wavespeed")},   # wavespeed/sync: centy USD
            "rolki_persony": len(baza.pomysly_z_dnia(aktywna)) if aktywna else 0}


# ---------------- modelki ----------------

@app.route("/api/modelki", methods=["POST"])
def api_nowa_modelka():
    dane = request.json or {}
    nazwa = (dane.get("nazwa") or "").strip()
    if not nazwa:
        return _blad("Podaj nazwe modelki.")
    try:
        slug = baza.utworz_modelke(nazwa)
    except ValueError as e:
        return _blad(e)
    baza.ustaw_aktywna_modelke(slug)
    ig = (dane.get("instagram") or "").strip()
    if ig:
        baza.zapisz_profil(slug, instagram=ig)
    try:
        foldery = baza.przygotuj_foldery_pulpitu(slug)["foldery"]      # od razu: Pulpit\ROLKI AI\tu wrzucasz rolki\<nazwa> itd.
    except OSError as e:
        foldery = {"blad": str(e)}
    baza.dziennik_zapisz("info", f"nowa modelka: {slug}", modelka=slug)
    return _ok(slug=slug, foldery=foldery)


@app.route("/api/modelki/aktywna", methods=["POST"])
def api_aktywna_modelka():
    try:
        baza.ustaw_aktywna_modelke((request.json or {}).get("slug", ""))
    except ValueError as e:
        return _blad(e)
    return _ok()


@app.route("/api/profil", methods=["POST"])
def api_profil():
    try:
        aktywna = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    dane = request.json or {}
    zmiany = {}
    for pole in ("instagram", "opis_stylu", "nazwa", "hashtagi", "wlosy", "sylwetka"):
        if pole in dane:
            zmiany[pole] = str(dane[pole]).strip()
    if "wzrost_cm" in dane:
        # wzrost persony do rolek z promptu: "158-160" albo "170" (cm); puste = brak
        wzrost = str(dane["wzrost_cm"] or "").strip().replace(" ", "").replace("cm", "").replace("–", "-")
        if wzrost and not scenariusz._wzrost(wzrost):
            return _blad("Wzrost wpisz w cm, np. 158-160 albo 170.")
        zmiany["wzrost_cm"] = wzrost
    if "cechy" in dane:
        if isinstance(dane["cechy"], list):
            zmiany["cechy"] = [str(c).strip() for c in dane["cechy"] if str(c).strip()]
        else:
            zmiany["cechy"] = [c.strip() for c in str(dane["cechy"]).split(",") if c.strip()]
    return _ok(profil=baza.zapisz_profil(aktywna, **zmiany))


# ---------------- pomysly ----------------

def _pomysl_dla_panelu(p):
    p = dict(p)
    klatki = p.get("klatki")
    arkusz = os.path.join(klatki, "arkusz.jpg") if klatki else None
    p["miniatura_url"] = _url_pliku(arkusz)
    p["wynik_miniatura_url"] = _url_pliku(p.get("klatki_wyniku"))
    p["podglad_url"] = _url_pliku(p.get("podglad_plik"))
    p["podglad_miniatura_url"] = _url_pliku(p.get("klatki_podgladu"))
    p["wideo_url"] = _url_pliku(p.get("plik_wynikowy")) if p.get("plik_wynikowy") and os.path.isfile(p["plik_wynikowy"] or "") else None
    p["zrodlo_url"] = _url_pliku(p.get("zrodlo"))
    p["lipsync_url"] = _url_pliku(p.get("lipsync_plik"))
    p["stroj_url"] = _url_pliku(p.get("stroj"))
    p["audio_nazwa"] = os.path.basename(p["audio"]) if p.get("audio") else None
    p["wariant"] = "prompt" if fabryka.z_promptu(p) else ("B" if p.get("stroj") else ("A" if p.get("zrodlo") else "tekst"))
    # stroj z biblioteki (rolki z filmu i z promptu): nazwa PL do karty; zmiana stroju tylko przed generacja rolki z filmu
    bib = baza.stroj_biblioteki(p.get("stroj_bib") or ((p.get("z_promptu") or {}).get("stroj_id")
                                                       if (p.get("z_promptu") or {}).get("stroj_tryb") == "biblioteka" else None))
    p["stroj_nazwa"] = bib["nazwa"] if bib else (os.path.basename(p["stroj"]) if p.get("stroj") else None)
    p["stroj_ulubiony"] = bool(bib and bib["ulubiony"])
    p["mozna_zmienic_stroj"] = (not fabryka.z_promptu(p) and bool(p.get("zrodlo")) and p.get("status") in ("nowy", "blad"))
    if fabryka.z_promptu(p):
        zp = p.get("z_promptu") or {}
        info = scenariusz.MODELE.get(zp.get("model") or "", {})
        kto = {"chlopak": "chłopak", "dziewczyna": "dziewczyna"}.get(zp.get("nagrywa") or "", "")
        glos = {"tts": ("głos ElevenLabs" + (f" ({kto})" if kto else "") + ("" if p.get("glos_dograny") else " – do dogrania")
                        if zp.get("komentarz") else ""),
                "model": "głos modelu (stara rolka)"}.get(zp.get("glos") or "", "")
        p["z_promptu_opis"] = " · ".join(x for x in ("autopilot" if p.get("autopilot_z_promptu") else "", zp.get("miejsce_nazwa"),
                                                       (info.get("nazwa") or zp.get("model") or "").split(" –")[0],
                                                       f"{zp.get('dlugosc')} s" if zp.get("dlugosc") else "", zp.get("rozdzielczosc"),
                                                       "inne włosy" if zp.get("wlosy_zmienione") else "", glos) if x)
        p["z_promptu_dlaczego"] = (zp.get("asystent") or {}).get("dlaczego") or ""
        p["mozna_dograc_glos"] = (zp.get("glos") == "tts" and bool(zp.get("komentarz")) and not p.get("glos_dograny")
                                  and p.get("status") in ("gotowe", "wygenerowany"))
        p.pop("info_zrodla", None)
    # rozdzielczosc tej rolki (zasada: <= 8 s -> 1080p, dluzsze -> 720p) - zapisana przy generacji albo wyliczona z dlugosci klipu
    if not p.get("resolution") and fabryka.czas_klipu(p):
        p["resolution"] = fabryka.rozdzielczosc_dla_czasu(fabryka.czas_klipu(p))
    marker = p.get("w_toku") if p.get("status") == "w_toku" else None
    if marker:
        p["w_toku_opis"] = (f"{marker.get('dostawca')} {marker.get('model') or ''}".strip()
                            + (f", job {marker['job_id']}" if marker.get("job_id") else ", wysylanie"))
    if p.get("zapas") and p.get("model"):
        p["zapas_opis"] = f"zrobione na {p['model']} (zapas)"
    return p


@app.route("/api/pomysly")
def api_pomysly():
    try:
        aktywna = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    return _ok(pomysly=[_pomysl_dla_panelu(p) for p in baza.lista_pomyslow(aktywna)], statusy=baza.STATUSY,
               biblioteka=_biblioteka_dla_panelu(tylko_ze_zdjeciem=True), ma_prompt_b=bool(baza.prompt_stroj(aktywna)))


@app.route("/api/pomysly", methods=["POST"])
def api_dodaj_pomysl():
    try:
        aktywna = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    dane = request.json or {}
    opis = (dane.get("opis") or "").strip()
    if not opis:
        return _blad("Podaj opis pomyslu.")
    pid = baza.dodaj_pomysl(aktywna, opis, (dane.get("prompt") or "").strip())
    return _ok(id=pid)


@app.route("/api/pomysly/<int:pid>", methods=["PATCH"])
def api_aktualizuj_pomysl(pid):
    try:
        aktywna = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    dane = {k: v for k, v in (request.json or {}).items()
            if k in ("status", "opis", "prompt_higgsfield", "plik_wynikowy", "notatki")}
    try:
        if "status" in dane and baza.pomysl(aktywna, pid).get("status") == "w_toku":
            return _blad(GENERUJE_SIE, 409)
        pomysl = baza.aktualizuj_pomysl(aktywna, pid, **dane)
    except ValueError as e:
        return _blad(e)
    return _ok(pomysl=_pomysl_dla_panelu(pomysl))


GENERUJE_SIE = ("Ta rolka wlasnie sie generuje - fabryka dokonczy ja sama (takze po restarcie panelu). "
                "Utknela? wiecej -> Przestan czekac.")


@app.route("/api/pomysly/<int:pid>/ponow", methods=["POST"])
def api_ponow_pomysl(pid):
    """'Sprobuj jeszcze raz'. Rolka odrzucona przez filtr (NSFW/IP) przy wlaczonym zapas_nsfw zaczyna od pierwszego kroku zapasu
    (Seedance odrzucilby te same wejscia) - chyba ze to rolka ze strojem ze zdjecia (wariant B), a zaden krok zapasu nie zachowa
    stroju (Wan bierze stroj z filmu; WaveSpeed Seedance dostaje prompt persony i stroj zachowa)."""
    try:
        aktywna = _wymaga_modelki()
        p = baza.pomysl(aktywna, pid)
        if p.get("status") == "w_toku":
            return _blad(GENERUJE_SIE, 409)
        zapas = baza.ustawienia_modelki(aktywna).get("zapas_nsfw") or []
        krok = 1 if (p.get("powod") in fabryka.POWODY_ZAPASU and zapas and not fabryka.z_promptu(p)
                     and (not p.get("stroj") or fabryka.zapas_dla_stroju(zapas))) else None
        pomysl = baza.aktualizuj_pomysl(aktywna, pid, status="nowy", notatki="", krok_startowy=krok)
    except ValueError as e:
        return _blad(e)
    return _ok(pomysl=_pomysl_dla_panelu(pomysl), od_zapasu=bool(krok))


@app.route("/api/pomysly/<int:pid>/stroj", methods=["POST"])
def api_stroj_pomyslu(pid):
    """Zmiana stroju rolki z filmu PRZED generacja: {"stroj": "z_filmu" | "<id ze stroje_biblioteka (ze zdjeciem)>"}.
    z_filmu = wariant A (prompt A), stroj z biblioteki = wariant B (prompt B, zdjecie stroju jako ostatni obraz). Prompt
    zmieniamy tylko, gdy rolka ma prompt persony (A/B) albo pusty - wlasny prompt rolki zostaje (z uwaga)."""
    try:
        aktywna = _wymaga_modelki()
        p = baza.pomysl(aktywna, pid)
    except ValueError as e:
        return _blad(e)
    if p.get("status") == "w_toku":
        return _blad(GENERUJE_SIE, 409)
    if fabryka.z_promptu(p) or not p.get("zrodlo"):
        return _blad("Stroj zmieniasz tylko w rolkach z filmiku (rolka z promptu: zrob nowa w zakladce Z promptu).")
    if p.get("status") not in ("nowy", "blad"):
        return _blad("Ta rolka jest juz zrobiona - stroj zmienia sie tylko przed generacja.")
    wybor = str((request.json or {}).get("stroj") or "").strip()
    prompt_a, prompt_b = baza.prompt_bazowy(aktywna), baza.prompt_stroj(aktywna)
    obecny = (p.get("prompt_higgsfield") or "").strip()
    persony = obecny in ("", prompt_a.strip(), prompt_b.strip())
    if wybor == "z_filmu":
        zmiany = {"stroj": None, "stroj_bib": None}
        nowy_prompt = prompt_a
    else:
        s = baza.stroj_biblioteki(wybor)
        if not s or not s.get("plik"):
            return _blad("Nie ma takiego stroju ze zdjeciem w bibliotece strojow.")
        if not prompt_b:
            return _blad("Ta persona nie ma promptu B (stroj ze zdjecia) - bez niego stroj z biblioteki nie zadziala. "
                         "Ustawienia -> Prompty.")
        zmiany = {"stroj": s["plik"], "stroj_bib": s["id"]}
        nowy_prompt = prompt_b
    uwaga = ""
    if persony:
        zmiany["prompt_higgsfield"] = nowy_prompt
    else:
        uwaga = "Ta rolka ma wlasny prompt - zostawilem go; sprawdz, czy pasuje do nowego stroju."
    pomysl = baza.aktualizuj_pomysl(aktywna, pid, **zmiany)
    baza.dziennik_zapisz("info", f"#{pid}: stroj -> {('z filmu' if wybor == 'z_filmu' else zmiany.get('stroj_bib'))}",
                         modelka=aktywna, pomysl=pid)
    return _ok(pomysl=_pomysl_dla_panelu(pomysl), uwaga=uwaga)


def _biblioteka_dla_panelu(tylko_ze_zdjeciem=False):
    """Stroje z biblioteki do list w panelu: ulubione na gorze (gwiazdka), z miniatura, gdy jest zdjecie."""
    return [{"id": s["id"], "nazwa": s["nazwa"], "ulubiony": s["ulubiony"], "ma_zdjecie": bool(s["plik"]),
             "url": _url_pliku(s["plik"]) if s["plik"] else None}
            for s in sorted(baza.stroje_biblioteki(tylko_ze_zdjeciem), key=lambda s: (not s["ulubiony"], -s["waga"]))]


@app.route("/api/pomysly/<int:pid>/przerwij", methods=["POST"])
def api_przerwij_czekanie(pid):
    """'Przestan czekac' na rolke w toku (np. utknela bez numeru joba). Wymaga {"potwierdzam": true} - panel pyta wczesniej,
    bo kredyty mogly juz zejsc. Rolka dostaje status 'blad' z prosba o sprawdzenie w apce; potem dziala Ponow/Usun.
    Nie wolno w trakcie samego wysylania (wtedy 409)."""
    if not (request.json or {}).get("potwierdzam"):
        return _blad("Potwierdz: kredyty za te rolke mogly juz zejsc - sprawdz najpierw w apce Higgsfield/yapper/WaveSpeed.")
    try:
        aktywna = _wymaga_modelki()
        p = baza.pomysl(aktywna, pid)
        if p.get("status") != "w_toku":
            return _blad("Ta rolka nie czeka na generacje.")
        if fabryka.trwa_wysylanie():
            return _blad("Rolka jest wlasnie wysylana - poczekaj chwile i sprobuj jeszcze raz.", 409)
        marker = p.get("w_toku") or {}
        job = marker.get("job_id") or p.get("job_id")
        notatki = (f"Przerwane recznie (czekanie na {marker.get('dostawca') or '?'} {marker.get('model') or ''}"
                   + (f", job {job}" if job else ", bez numeru joba") + f"). {fabryka.sprawdz_w_apce(marker.get('dostawca'))}")
        pomysl = baza.aktualizuj_pomysl(aktywna, pid, status="blad", w_toku=None, krok_startowy=None, powod="inny", notatki=notatki)
    except ValueError as e:
        return _blad(e)
    baza.dziennik_zapisz("uwaga", f"#{pid}: {notatki}", modelka=aktywna, pomysl=pid)
    return _ok(pomysl=_pomysl_dla_panelu(pomysl))


@app.route("/api/pomysly/<int:pid>", methods=["DELETE"])
def api_usun_pomysl(pid):
    try:
        aktywna = _wymaga_modelki()
        p = baza.pomysl(aktywna, pid)
        if p.get("status") == "w_toku":
            return _blad(GENERUJE_SIE + " Usuniecie teraz zgubiloby oplacony wynik - najpierw 'Przestan czekac'.", 409)
        if request.args.get("plik") == "1":
            for k in ("plik_wynikowy", "lipsync_plik"):
                if p.get(k) and os.path.isfile(p[k]) and _plik_dozwolony(p[k]):
                    os.remove(p[k])
        try:
            asystent.archiwizuj_usuniety(aktywna, p)     # asystent pamieta, ze ta rolka nie przypadla do gustu
        except OSError:
            pass
        baza.usun_pomysl(aktywna, pid)
    except ValueError as e:
        return _blad(e)
    return _ok()


# ---------------- rolka z promptu (zakladka "Z promptu", scenariusz.py) ----------------

OPCJE_Z_PROMPTU = ("pomysl_id", "tekst", "miejsce", "model", "dlugosc", "rozdzielczosc", "wlosy", "stroj", "stroj_tekst", "reakcja",
                   "komentarz", "komentarz_tekst", "sezon", "pora", "kamera", "ustalone", "obiekt", "nazwy", "glos", "wymowa",
                   "asystent", "nagrywa")


def _slug_z_promptu(dane):
    """Persona z zapytania (pole/parametr slug) albo aktywna. LookupError = nie ma takiej persony (404)."""
    slug = (dane.get("slug") or "").strip() or _wymaga_modelki()
    if slug not in baza.lista_modelek():
        raise LookupError(f"Nie ma persony '{slug}'.")
    return slug


def _opcje_z_promptu(dane):
    opcje = {k: dane[k] for k in OPCJE_Z_PROMPTU if k in dane and dane[k] is not None}
    for k in ("wlosy", "ustalone", "asystent"):
        if k in opcje and not isinstance(opcje[k], dict):
            raise ValueError(f"{k} musi byc slownikiem.")
    if "dlugosc" in opcje:
        try:
            opcje["dlugosc"] = int(opcje["dlugosc"])
        except (TypeError, ValueError):
            raise ValueError("Dlugosc musi byc liczba sekund.")
    return opcje


@app.route("/api/z-promptu")
def api_z_promptu_katalog():
    """Katalog do formularza: gotowe pomysly, miejsca, wlosy, stroje, reakcje, komentarze, kamery, modele, domyslne wybory."""
    try:
        slug = _slug_z_promptu(dict(request.args))
    except LookupError as e:
        return _blad(e, 404)
    except ValueError as e:
        return _blad(e)
    kat = scenariusz.katalog(slug)
    kat["domyslne"] = dict(baza.USTAWIENIA_DOMYSLNE["z_promptu"], **(baza.ustawienia_modelki(slug).get("z_promptu") or {}))
    kat["glos_tts"] = _stan_tts()
    kat["stroje_biblioteka"] = _biblioteka_dla_panelu()
    kat["asystent_llm"] = bool(sekrety.klucz("openrouter"))
    return _ok(**kat)


def _stan_tts():
    """Czy komentarz moze isc przez ElevenLabs (klucz jest i dziala) - sprawdzenie bez kosztu, cache 10 min. Bez ElevenLabs rolka
    wychodzi BEZ komentarza (model wideo nigdy nie mowi) - komunikat mowi to wprost."""
    bez = " – rolka wyjdzie bez komentarza zza kamery (model wideo nic nie mówi); dograsz go potem przyciskiem „Dograj głos”."
    if not sekrety.klucz("elevenlabs"):
        return {"ok": False, "komunikat": "Brak klucza ElevenLabs (Ustawienia → Konta)" + bez}
    try:
        import komentarz_glos
        ok, kom = komentarz_glos.tts_dostepne()
    except Exception as e:
        ok, kom = False, str(e)
    return {"ok": ok, "komunikat": "ElevenLabs działa – komentarz osoby nagrywającej dogram po generacji." if ok
            else f"ElevenLabs nie działa ({kom})" + bez}


@app.route("/api/z-promptu/asystent", methods=["POST"])
def api_z_promptu_asystent():
    """Asystent (agent w tle): krotki pomysl PL -> opcje (miejsce, stroj, kamera, reakcja, komentarz, wlosy, dlugosc, model)
    + jedno zdanie 'dlaczego'. Darmowy model OpenRouter, gdy jest klucz; inaczej reguly. ZERO kosztow (nic nie wycenia).
    {slug?, tekst, pomysl_id?, zablokowane: {pole: wartosc ustawiona recznie}}."""
    dane = request.json or {}
    try:
        slug = _slug_z_promptu(dane)
        zab = dane.get("zablokowane") or {}
        if not isinstance(zab, dict):
            raise ValueError("zablokowane musi byc slownikiem.")
        tts = _stan_tts()
        w = asystent.dobierz(slug, (dane.get("tekst") or "").strip(), pomysl_id=dane.get("pomysl_id") or None,
                             zablokowane=zab, uzyj_llm=not dane.get("bez_llm"),
                             glos_efektywny="tts" if tts["ok"] else "brak")
    except LookupError as e:
        return _blad(e, 404)
    except ValueError as e:
        return _blad(e)
    return _ok(slug=slug, glos_tts=tts, **w)


@app.route("/api/pomysly/<int:pid>/ocena", methods=["POST"])
def api_ocena_pomyslu(pid):
    """Ocena rolki z promptu: {"ocena": "dobra" | "slaba" | null} - asystent uczy sie z niej przy kolejnym dobieraniu."""
    try:
        aktywna = _wymaga_modelki()
        pomysl = asystent.ocen(aktywna, pid, (request.json or {}).get("ocena"))
    except ValueError as e:
        return _blad(e)
    return _ok(pomysl=_pomysl_dla_panelu(pomysl))


@app.route("/api/z-promptu/losuj", methods=["POST"])
def api_z_promptu_losuj():
    """Losowy gotowy pomysl (bez powtorek z 14 dni; 'bez' = id, ktorego nie chcemy znowu)."""
    dane = request.json or {}
    try:
        slug = _slug_z_promptu(dane)
    except LookupError as e:
        return _blad(e, 404)
    except ValueError as e:
        return _blad(e)
    uzyte = scenariusz.uzyte_pomysly(slug) + [dane.get("bez") or ""]
    sezon = dane.get("sezon") if dane.get("sezon") in scenariusz.SEZONY else None
    p = scenariusz.losuj_pomysl(slug, sezon=sezon, uzyte=uzyte)
    return _ok(pomysl={"id": p["id"], "pl": p["pl"], "miejsce": p["miejsce"]})


@app.route("/api/z-promptu/wycena", methods=["POST"])
def api_z_promptu_wycena():
    """Prompt + DARMOWA wycena (`generate cost`, nic nie tworzy). {"bez_ceny": true} = tylko prompt (od razu)."""
    dane = request.json or {}
    try:
        slug = _slug_z_promptu(dane)
        w = fabryka.wycena_z_promptu(slug, _opcje_z_promptu(dane), z_cena=not dane.get("bez_ceny"))
    except LookupError as e:
        return _blad(e, 404)
    except ValueError as e:
        return _blad(e)
    return _ok(slug=slug, **w)


@app.route("/api/z-promptu", methods=["POST"])
def api_z_promptu_zrob():
    """'Zrob rolke': pomysl typu 'prompt' z zamrozonym promptem + zadanie generuj tylko dla niego. Wymaga "kr" (cena z wyceny,
    ktora user widzial) - fabryka liczy cene jeszcze raz tuz przed wyslaniem i NIE wysyla, gdy wyszlaby wyzsza.
    409, gdy cos juz trwa (wtedy nic nie tworzymy)."""
    dane = request.json or {}
    try:
        slug = _slug_z_promptu(dane)
        opcje = _opcje_z_promptu(dane)
        kr = int(dane["kr"]) if dane.get("kr") not in (None, "") else None
    except LookupError as e:
        return _blad(e, 404)
    except (ValueError, TypeError) as e:
        return _blad(e)
    if kr is None or kr <= 0:
        return _blad("Najpierw sprawdz cene (przycisk 'Sprawdz cene') - bez wyceny nic nie wysylam.")
    if konsola.stan.get("trwa"):
        return _blad(f"Cos juz trwa ({konsola.stan.get('typ') or 'inne zadanie'}) - poczekaj, az skonczy, i kliknij jeszcze raz.", 409)
    try:
        pid = fabryka.dodaj_z_promptu(slug, opcje, prompt=dane.get("prompt"), kr=kr)
    except ValueError as e:
        return _blad(e)

    def _zrob(log, stop):
        def cena_ok(p, k, *_):
            if k is not None and k > kr:
                log(f"#{p['id']}: cena wzrosla z {kr} do {k} kr - NIE wysylam. Sprawdz cene jeszcze raz w 'Z promptu'.")
                return False
            return True
        return fabryka.generuj(slug, ids=[pid], potwierdz=cena_ok, log=log, stop=stop)
    try:
        zadanie = konsola.uruchom("generuj", slug, _zrob)
    except Zajete as e:
        return jsonify({"ok": False, "id": pid, "blad": f"Cos juz trwa ({e}) - rolka #{pid} czeka w kolejce (Rolki -> Zrob te rolke)."}), 409
    return _ok(id=pid, zadanie=zadanie)


# ---------------- akcje w tle ----------------

def _ids(dane):
    ids = dane.get("ids")
    if not ids and dane.get("id"):
        ids = [dane["id"]]
    return [int(i) for i in ids] if ids else None


def _funkcja_akcji(typ, slug, dane):
    """Zwraca fn(log, stop) dla typu akcji."""
    if typ == "skanuj":
        return lambda log, stop: fabryka.skanuj(slug, log=log, stop=stop)
    if typ == "koszt":
        return lambda log, stop: fabryka.koszt(slug, ids=_ids(dane), limit=dane.get("limit"), log=log)
    if typ == "generuj":
        # max_kr (opcjonalnie): cena, ktora user zatwierdzil w pytaniu "Robic?" - fabryka liczy cene jeszcze raz tuz przed
        # wyslaniem i pomija rolke, gdy wyszlaby wyzsza (nie placi wiecej, niz user widzial)
        max_kr = int(dane["max_kr"]) if str(dane.get("max_kr") or "").strip().isdigit() else None

        def _generuj(log, stop):
            sprawdzone = set()

            def cena_ok(p, k, *_):
                # tylko pierwsze pytanie o rolke = glowny dostawca (kolejne to kroki zapasu po NSFW, w innej walucie)
                if p["id"] in sprawdzone:
                    return True
                sprawdzone.add(p["id"])
                if max_kr is not None and k is not None and k > max_kr:
                    log(f"#{p['id']}: cena wzrosla z {max_kr} do {k} - NIE wysylam, policz koszt jeszcze raz")
                    return False
                return True
            return fabryka.generuj(slug, ids=_ids(dane), limit=dane.get("limit"), potwierdz=cena_ok if max_kr is not None else None,
                                   dry_run=bool(dane.get("dry_run")), bez_referencji=bool(dane.get("bez_referencji")),
                                   log=log, stop=stop)
        return _generuj
    if typ == "pierz":
        return lambda log, stop: fabryka.pierz(slug, pid=int(dane["id"]) if dane.get("id") else None, plik=dane.get("plik"), log=log)
    if typ in ("lipsync", "tts"):
        import lipsync
    if typ == "lipsync":
        wideo = dane.get("wideo")
        pid = int(dane["id"]) if dane.get("id") else None
        audio = dane.get("audio")
        if pid and not wideo:
            p = baza.pomysl(slug, pid)
            wideo = p.get("plik_wynikowy")
            audio = audio or p.get("audio")
        if not wideo or not os.path.isfile(wideo):
            raise ValueError("Brak pliku wideo (pomysl bez wyniku albo zla sciezka).")
        if not audio or not os.path.isfile(audio):
            raise ValueError("Brak pliku audio - wybierz glos z folderu audio/ albo podaj sciezke.")
        opcje = dict(dane.get("opcje") or {})
        if dane.get("sync_mode"):
            opcje["sync_mode"] = dane["sync_mode"]
        styl = (dane.get("styl") or "").strip().lower() or None     # telefon | czysty | brak (None = ustawienie persony)
        if styl and styl not in lipsync.STYLE_GLOSU:
            raise ValueError(f"Nieznany styl glosu '{styl}' (telefon, czysty, brak).")
        return lambda log, stop: lipsync.zrob(slug, wideo, audio, pomysl_id=pid, log=log,
                                              model=dane.get("model") or None, opcje=opcje, styl=styl)
    if typ == "zdjecia":
        import zdjecia
        stroj = dane.get("stroj")      # None = wg ustawien (co drugie w stroju), "bez", "auto" albo nazwa pliku ze stroje/
        return lambda log, stop: zdjecia.generuj(slug, ile=int(dane.get("ile") or 1), prompt=(dane.get("prompt") or "").strip() or None,
                                                 dry_run=bool(dane.get("dry_run")), log=log, stop=stop, stroj=stroj)
    if typ == "podpis":
        def _podpis(log, stop):
            tekst, cel = fabryka.podpis(slug, int(dane["id"]))
            log(tekst or "Bank tekstow pusty albo wszystko uzyte.")
            return {"tekst": tekst, "plik": cel}
        return _podpis
    if typ == "tts":
        tekst = (dane.get("tekst") or "").strip()
        if not tekst:
            raise ValueError("Podaj tekst do przeczytania.")
        return lambda log, stop: lipsync.tts_z_tekstu(slug, tekst, voice_id=dane.get("voice_id"), nazwa=_bezpieczna(dane.get("nazwa") or ""), log=log)
    if typ == "autopilot_raz":
        return lambda log, stop: autopilot.przebieg(slug, log=log, stop=stop)
    if typ == "podglad":
        pid = int(dane["id"])
        return lambda log, stop: {"plik": fabryka.podglad(slug, pid, log=log)}
    if typ == "dograj_glos":
        # komentarz ElevenLabs do gotowej rolki z promptu (glos tts) - tylko znaki ElevenLabs, zero kredytow Higgsfield
        pid = int(dane["id"])
        return lambda log, stop: {"plik": fabryka.dograj_glos(slug, pid, log=log)}
    if typ == "telegram_wyslij":
        from dostawcy import telegram
        p = baza.pomysl(slug, int(dane["id"]))
        plik = p.get("lipsync_plik") if p.get("lipsync_plik") and os.path.isfile(p["lipsync_plik"] or "") else p.get("plik_wynikowy")
        if not plik or not os.path.isfile(plik):
            raise ValueError("Ta rolka nie ma jeszcze gotowego pliku.")
        if not telegram.sparowany():
            raise ValueError("Telegram nie jest sparowany - napisz /start do bota na telefonie.")
        konto = (baza.ustawienia_modelki(slug).get("telegram_czat") or "").strip()
        cid, opis = telegram.czat_dla(konto)
        if not cid:
            raise ValueError(f"Konto {konto} tej persony nie napisalo jeszcze /start do bota ({opis}).")

        z_lipsynciem = plik == p.get("lipsync_plik")

        def _wyslij(log, stop):
            telegram.wyslij_wideo(plik, f"{slug} · rolka #{p['id']}" + (" · z dopasowanymi ustami" if z_lipsynciem else "")
                                  + (f"\n\n{p['podpis']}" if p.get("podpis") else ""), chat_id=cid)
            baza.aktualizuj_pomysl(slug, p["id"], telegram_wyslano=True, **({"telegram_wyslano_lipsync": True} if z_lipsynciem else {}))
            log(f"wyslalem #{p['id']} na Telegram ({opis})")
            return {"wyslano": p["id"], "czat": opis}
        return _wyslij
    raise ValueError(f"Nieznana akcja '{typ}'.")


def _bezpieczna(nazwa):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", nazwa).strip("_.") or ""


@app.route("/api/akcja", methods=["POST"])
def api_akcja():
    dane = request.json or {}
    typ = (dane.get("typ") or "").strip()
    try:
        slug = _wymaga_modelki()
        fn = _funkcja_akcji(typ, slug, dane)
    except ValueError as e:
        return _blad(e)
    try:
        zadanie = konsola.uruchom(typ, slug, fn)
    except Zajete as e:
        return _blad(f"Cos juz trwa ({e}) - poczekaj albo zatrzymaj w konsoli.", 409)
    return _ok(zadanie=zadanie)


@app.route("/api/zadanie")
def api_zadanie():
    od = max(0, int(request.args.get("od", 0) or 0))
    return _ok(**konsola.opis(), log=konsola.log[od:])


@app.route("/api/zadanie/stop", methods=["POST"])
def api_zadanie_stop():
    konsola.stop.set()
    konsola.dopisz("[STOP] zatrzymuje po biezacej pozycji...")
    return _ok(zadanie=konsola.opis())


# ---------------- ustawienia ----------------

def _lista_plikow(folder, rozszerzenia):
    if not os.path.isdir(folder):
        return []
    return [{"nazwa": n, "sciezka": os.path.join(folder, n), "url": _url_pliku(os.path.join(folder, n))}
            for n in sorted(os.listdir(folder)) if n.lower().endswith(rozszerzenia)]


@app.route("/api/ustawienia")
def api_ustawienia():
    try:
        slug = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    prompty_zdjec = baza._sciezka_w_modelce(slug, baza.ustawienia_modelki(slug).get("zdjecia_prompty") or "prompty/zdjecia.txt")
    tekst_zdjec = ""
    if os.path.isfile(prompty_zdjec):
        with open(prompty_zdjec, encoding="utf-8-sig") as f:
            tekst_zdjec = f.read()
    return _ok(
        ustawienia=baza.ustawienia_modelki(slug),
        profil=baza.profil_modelki(slug),
        domyslne=baza.USTAWIENIA_DOMYSLNE,
        prompty={"a": baza.prompt_bazowy(slug), "b": baza.prompt_stroj(slug), "zdjecia": tekst_zdjec},
        referencje=_lista_plikow(baza.folder_referencji(slug), baza.ROZSZERZENIA_OBRAZU),
        stroje=_lista_plikow(baza.folder_strojow(slug), baza.ROZSZERZENIA_OBRAZU),
        biblioteka=_biblioteka_dla_panelu(),
        audio=_lista_plikow(baza.folder_audio(slug), baza.ROZSZERZENIA_AUDIO),
        foldery={"modelka": baza.folder_modelki(slug), "wrzutnia": baza.folder_zrodel(slug), "gotowe": baza.folder_gotowych(slug),
                 "zdjecia": baza.folder_zdjec(slug), "audio": baza.folder_audio(slug), "referencje": baza.folder_referencji(slug),
                 "stroje": baza.folder_strojow(slug)},
    )


def _rzutuj(klucz, wartosc):
    """Wartosc z formularza -> typ jak w USTAWIENIA_DOMYSLNE (bool/int/dict/str)."""
    dom = baza.USTAWIENIA_DOMYSLNE[klucz]
    wybory = {"stroj_swap": ("biblioteka", "z_filmu"), "nagrywa": ("chlopak", "dziewczyna")}
    if klucz in wybory:
        v = str(wartosc or "").strip()
        if v not in wybory[klucz]:
            raise ValueError(f"{klucz}: dozwolone {' / '.join(wybory[klucz])}")
        return v
    if klucz == "zapas_nsfw":
        # [{"dostawca": "yapper", "model": "wan-3.0-prime"}, ...] - z formularza moze przyjsc jako tekst JSON
        if isinstance(wartosc, str):
            wartosc = json.loads(wartosc or "[]")
        if not isinstance(wartosc, list) or not all(isinstance(k, dict) and k.get("dostawca") and k.get("model") for k in wartosc):
            raise ValueError('zapas_nsfw: lista krokow [{"dostawca": "yapper", "model": "wan-3.0-prime"}, ...]')
        kroki = [{"dostawca": str(k["dostawca"]).strip().lower(), "model": str(k["model"]).strip()} for k in wartosc]
        zle = [k["dostawca"] for k in kroki if k["dostawca"] not in dostawcy.NAZWY_ZAPASU]
        if zle:
            raise ValueError(f"zapas_nsfw: nieznany dostawca {', '.join(zle)} (dozwolone: {', '.join(dostawcy.NAZWY_ZAPASU)})")
        return kroki
    if klucz in ("duration", "generate_audio"):
        if wartosc in ("", None, "null"):
            return None
        if klucz == "generate_audio":
            return str(wartosc).lower() in ("1", "true", "tak", "t")
        return int(wartosc)
    if isinstance(dom, bool):
        return wartosc if isinstance(wartosc, bool) else str(wartosc).lower() in ("1", "true", "tak", "t", "on")
    if isinstance(dom, int):
        return int(wartosc or 0)
    if isinstance(dom, dict):
        if isinstance(wartosc, str):
            wartosc = json.loads(wartosc or "{}")
        if not isinstance(wartosc, dict):
            raise ValueError(f"{klucz} musi byc slownikiem")
        return wartosc
    if isinstance(dom, list):
        return list(wartosc) if isinstance(wartosc, (list, tuple)) else [w.strip() for w in str(wartosc).split(",") if w.strip()]
    return "" if wartosc is None else str(wartosc).strip()


@app.route("/api/ustawienia", methods=["POST"])
def api_zapisz_ustawienia():
    try:
        slug = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    dane = request.json or {}
    zmiany = {}
    przed = baza.ustawienia_modelki(slug)
    rozdzielczosc_przed = przed.get("resolution")
    # koszt rolki zalezy tez od dostawcy i modelu (kredyty Higgsfield vs centy WaveSpeed) - po zmianie liczymy od nowa
    cena_przed = (przed.get("dostawca"), (przed.get("wavespeed") or {}).get("model"), (przed.get("yapper") or {}).get("model"))
    try:
        for k, v in dane.items():
            if k == "prompt_a_tekst":
                baza.zapisz_prompt(slug, "stroj_z_filmu.txt", str(v))
                zmiany["prompt_bazowy"] = "prompty/stroj_z_filmu.txt"
            elif k == "prompt_b_tekst":
                baza.zapisz_prompt(slug, "stroj_ze_zdjecia.txt", str(v))
                zmiany["prompt_stroj"] = "prompty/stroj_ze_zdjecia.txt"
            elif k == "zdjecia_prompty_tekst":
                baza.zapisz_prompt(slug, "zdjecia.txt", str(v))
                zmiany["zdjecia_prompty"] = "prompty/zdjecia.txt"
            elif k in baza.USTAWIENIA_DOMYSLNE:
                zmiany[k] = _rzutuj(k, v)
            else:
                return _blad(f"Nieznane ustawienie: {k}")
        ust = baza.zapisz_ustawienia(slug, **zmiany) if zmiany else baza.ustawienia_modelki(slug)
    except (ValueError, TypeError) as e:
        return _blad(e)
    if "autopilot" in zmiany:
        baza.dziennik_zapisz("info", f"autopilot dla {slug}: {'wlaczony' if zmiany['autopilot'] else 'wylaczony'}", modelka=slug)
    cena_po = (ust.get("dostawca"), (ust.get("wavespeed") or {}).get("model"), (ust.get("yapper") or {}).get("model"))
    if ust.get("resolution") != rozdzielczosc_przed or cena_po != cena_przed:
        fabryka.uniewaznij_koszty(slug)      # stare szacunki kosztu rolek nie pasuja do nowej rozdzielczosci / dostawcy / modelu
    return _ok(ustawienia=ust)


# ---------------- ustawienia globalne (wspolne dla wszystkich person, 3.3) ----------------

def _globalne_dla_panelu():
    return {"ustawienia": baza.ustawienia_globalne(), "domyslne": baza.USTAWIENIA_GLOBALNE_DOMYSLNE,
            "modele_z_promptu": [{"id": k, "nazwa": v["nazwa"]} for k, v in autopilot.MODELE_Z_PROMPTU.items()],
            "persony": [{"slug": s, "nazwa": baza.profil_modelki(s).get("nazwa") or s, "referencje": len(baza.sciezki_referencji(s))}
                        for s in baza.lista_modelek()],
            "z_promptu": autopilot.stan_z_promptu(wlaczony=_autopilot_wlaczony()), "max_rownolegle": zdjecia_swap.ROWNOLEGLE_MAX}


@app.route("/api/ustawienia/globalne")
def api_ustawienia_globalne():
    """Ustawienia wspolne dla person: zdjecia_rownolegle (ile zdjec naraz) i autopilot_z_promptu {dziennie, model, persony,
    od_godziny} + lista modeli/person do formularza i stan rolek z promptu na dzis."""
    return _ok(**_globalne_dla_panelu())


@app.route("/api/ustawienia/globalne", methods=["POST"])
def api_zapisz_ustawienia_globalne():
    """{"zdjecia_rownolegle": 4} albo {"autopilot_z_promptu": {"dziennie": 1, "model": "seedance_2_5", "persony": [],
    "od_godziny": "10:00"}} (dowolne z pol). Zle wartosci -> 400. Limity budzetu (300 kr dziennie, min_kredyty) sie tu nie zmieniaja."""
    dane = request.json or {}
    zmiany = {}
    try:
        for k, v in dane.items():
            if k == "zdjecia_rownolegle":
                n = int(v)
                if not 1 <= n <= zdjecia_swap.ROWNOLEGLE_MAX:
                    raise ValueError(f"Ile zdjec naraz: od 1 do {zdjecia_swap.ROWNOLEGLE_MAX}.")
                zmiany[k] = n
            elif k == "autopilot_z_promptu":
                zmiany[k] = autopilot.sprawdz_ustawienia_z_promptu(v)
            else:
                return _blad(f"Nieznane ustawienie: {k}")
    except (TypeError, ValueError) as e:
        return _blad(e)
    if zmiany:
        baza.zapisz_ustawienia_globalne(**zmiany)
        baza.dziennik_zapisz("info", "ustawienia wspolne: " + ", ".join(f"{k} = {json.dumps(v, ensure_ascii=False)}"
                                                                         for k, v in zmiany.items()))
        if "zdjecia_rownolegle" in zmiany:
            zdjecia_swap.KOLEJKA.obudz()       # wiecej miejsc = od razu kolejne zdjecia z kolejki
    return _ok(**_globalne_dla_panelu())


def _nazwa_pliku(nazwa):
    nazwa = os.path.basename(nazwa or "").strip()
    nazwa = re.sub(r"[^\w.\- ]+", "_", nazwa, flags=re.UNICODE).strip(" ._")
    return nazwa or "plik"


@app.route("/api/upload", methods=["POST"])
def api_upload():
    try:
        slug = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    typ = (request.form.get("typ") or "").strip()
    foldery = {"referencja": (baza.folder_referencji, baza.ROZSZERZENIA_OBRAZU), "stroj": (baza.folder_strojow, baza.ROZSZERZENIA_OBRAZU),
               "audio": (baza.folder_audio, baza.ROZSZERZENIA_AUDIO), "zrodlo": (baza.folder_zrodel, fabryka.ROZSZERZENIA_WIDEO + baza.ROZSZERZENIA_OBRAZU)}
    if typ not in foldery:
        return _blad("typ musi byc: referencja | stroj | audio | zrodlo")
    folder_fn, rozsz = foldery[typ]
    folder = folder_fn(slug)
    zapisane, pominiete = [], []
    for plik in request.files.getlist("pliki"):
        nazwa = _nazwa_pliku(plik.filename)
        if not nazwa.lower().endswith(rozsz):
            pominiete.append(nazwa)
            continue
        if typ == "referencja" and not re.match(r"^\d+_", nazwa):
            istniejace = [n for n in os.listdir(folder) if n.lower().endswith(baza.ROZSZERZENIA_OBRAZU)]
            nazwa = f"{len(istniejace) + 1:02d}_{nazwa}"
        cel = os.path.join(folder, nazwa)
        plik.save(cel)
        zapisane.append(nazwa)
    if typ == "referencja" and zapisane:
        baza.dziennik_zapisz("info", f"nowe referencje: {', '.join(zapisane)}", modelka=slug)
    return _ok(zapisane=zapisane, pominiete=pominiete)


@app.route("/api/pliki/usun", methods=["POST"])
def api_usun_plik():
    try:
        slug = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    dane = request.json or {}
    foldery = {"referencja": baza.folder_referencji, "stroj": baza.folder_strojow, "audio": baza.folder_audio}
    typ = dane.get("typ")
    if typ not in foldery:
        return _blad("typ musi byc: referencja | stroj | audio")
    nazwa = _nazwa_pliku(dane.get("nazwa"))
    cel = os.path.join(foldery[typ](slug), nazwa)
    if not os.path.isfile(cel):
        return _blad(f"Nie ma pliku {nazwa}")
    os.remove(cel)
    return _ok()


# ---------------- konta / klucze ----------------

JAK_LOGOWAC = {
    "higgsfield": "Logowanie: zaloguj-higgsfield.bat (Firefox) albo `higgsfield auth login`, potem `higgsfield workspace set <id>`",
    "yapper": "yapper.so -> Account -> API -> Create key (zaznacz Read + Write). Klucz pokazuje sie tylko raz - skopiuj od razu. Wymaga platnego planu.",
    "wavespeed": "Zaloguj sie (Google albo GitHub) na https://wavespeed.ai/dashboard -> API Keys, czyli https://wavespeed.ai/accesskey "
                 "-> utworz klucz i wklej go tutaj. Doladuj konto (Billing, karta albo PayPal) - bez pieniedzy na koncie rolki nie rusza. "
                 "Potem ustaw dzienny limit w Ustawienia -> Limity (bez limitu fabryka nic tam nie wyda).",
    "sync": "https://sync.so/settings/api-keys -> New API key",
    "elevenlabs": "elevenlabs.io -> Developers -> API Keys -> Create (klucz zaczyna sie od sk_; uprawnienie Text to Speech + "
                  "Voices: read) - glos komentarza zza kamery w rolkach z promptu (eleven_v3, poprawna polszczyzna)",
    "openrouter": "https://openrouter.ai/keys -> Create key (konto przez Google/GitHub, BEZ weryfikacji dowodem, bez doladowania - "
                  "asystent uzywa tylko darmowych modeli). Klucz zaczyna sie od sk-or-",
    "telegram": "W Telegramie napisz do @BotFather: /newbot, nadaj nazwe -> dostaniesz token. Wklej go tu. "
                "Potem napisz do swojego bota /start - od tej chwili wysylasz mu filmiki, a on odsyla gotowe rolki.",
}


def _konta_pelne():
    salda = _salda()
    hf = salda.get("higgsfield") or {}
    konta = {"higgsfield": {"nazwa": "Higgsfield", "typ": "oauth", "ok": hf.get("kredyty") is not None,
                            "komunikat": f"zalogowany, {hf.get('kredyty')} kr" if hf.get("kredyty") is not None else (hf.get("blad") or ""),
                            "jak": JAK_LOGOWAC["higgsfield"]}}
    for d, info in sekrety.stan().items():
        t = _konta_test.get(d) or {}
        konta[d] = {"nazwa": info["nazwa"], "typ": "klucz", "opis": info["opis"], "jest": info["jest"], "maska": info["maska"],
                    "z_env": info["z_env"], "ok": t.get("dziala"), "komunikat": t.get("komunikat", ""), "jak": JAK_LOGOWAC.get(d, "")}
    tg = _stan_telegramu()
    konta["telegram"].update(sparowany=tg["sparowany"], czat=tg["czat"])
    if konta["telegram"]["jest"] and not konta["telegram"]["komunikat"]:
        konta["telegram"]["komunikat"] = f"sparowany z {tg['czat']}" if tg["sparowany"] else "token jest - napisz /start do bota na telefonie"
    return konta


@app.route("/api/konta")
def api_konta():
    return _ok(konta=_konta_pelne())


@app.route("/api/statystyki")
def api_statystyki():
    """Ostatnie N dni (domyslnie 14): rolki, zdjecia, kredyty per dostawca, problemy - do wykresu w panelu."""
    from datetime import datetime, timedelta
    ile = max(1, min(90, int(request.args.get("dni", 14) or 14)))
    dni = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(ile - 1, -1, -1)]
    rolki = {d: 0 for d in dni}
    zdjecia = {d: 0 for d in dni}
    for slug in baza.lista_modelek():
        for p in baza.lista_pomyslow(slug):
            d = baza.dzien_lokalny(p.get("wygenerowano"))
            if d in rolki:
                rolki[d] += 1
        for z in baza.lista_zdjec(slug):
            d = baza.dzien_lokalny(z.get("utworzono"))
            if d in zdjecia and z.get("status") == "gotowe":
                zdjecia[d] += 1
    bud = baza.budzet()
    kredyty = {"higgsfield": bud.get("wydatki", {}), "yapper": (bud.get("dostawcy", {}).get("yapper") or {}).get("wydatki", {}),
               "sync": (bud.get("dostawcy", {}).get("sync") or {}).get("wydatki", {}),
               "wavespeed": (bud.get("dostawcy", {}).get("wavespeed") or {}).get("wydatki", {})}     # centy USD
    bledy = {d: 0 for d in dni}
    for w in baza.dziennik_ostatnie(2000, typ="blad"):
        d = baza.dzien_lokalny(w.get("czas"))
        if d in bledy:
            bledy[d] += 1
    nsfw = 0
    for slug in baza.lista_modelek():
        nsfw += sum(1 for p in baza.lista_pomyslow(slug) if p.get("powod") == "nsfw" and baza.dzien_lokalny(p.get("zaktualizowano")) in bledy)
    return _ok(dni=[{"dzien": d, "rolki": rolki[d], "zdjecia": zdjecia[d], "bledy": bledy[d],
                     "kredyty": {k: int(v.get(d, 0)) for k, v in kredyty.items()}} for d in dni],
               razem={"rolki": sum(rolki.values()), "zdjecia": sum(zdjecia.values()), "bledy": sum(bledy.values()), "nsfw": nsfw,
                      "kredyty": {k: sum(int(v.get(d, 0)) for d in dni) for k, v in kredyty.items()}})


@app.route("/api/diagnoza")
def api_diagnoza():
    """Czy wszystko jest na miejscu (ffmpeg, Higgsfield, Media Tool, Telegram, persony, foldery) - panel: Start -> Pierwsze kroki."""
    return _ok(diagnoza=fabryka.diagnoza())


@app.route("/api/nsfw")
def api_nsfw():
    """Czemu filtr tresci odrzuca rolki aktywnej persony: liczba odrzucen, ryzykowne slowa w promptach, wskazowki."""
    try:
        slug = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    return _ok(**fabryka.wskazowki_nsfw(slug))


@app.route("/api/konta", methods=["POST"])
def api_zapisz_klucz():
    dane = request.json or {}
    klucz = (dane.get("klucz") or "").strip()
    try:
        if klucz and dane.get("dostawca") in sekrety.PREFIKSY and not klucz.startswith(sekrety.PREFIKSY[dane["dostawca"]]):
            raise ValueError(f"To nie wyglada na klucz {sekrety.DOSTAWCY[dane['dostawca']]['nazwa']} - prawdziwy zaczyna sie od "
                             f"'{sekrety.PREFIKSY[dane['dostawca']]}'. Skopiuj go jeszcze raz (Konta -> jak zdobyc klucz).")
        sekrety.zapisz_klucz(dane.get("dostawca", ""), klucz)
    except ValueError as e:
        return _blad(e)
    _konta_test.pop(dane.get("dostawca"), None)
    _saldo.pop(dane.get("dostawca"), None)
    return _ok(konta=_konta_pelne())


@app.route("/api/konta/test", methods=["POST"])
def api_test_konta():
    d = (request.json or {}).get("dostawca", "")
    try:
        if d == "higgsfield":
            from dostawcy import higgsfield
            dziala, komunikat = higgsfield.gotowy()
            _saldo.pop("higgsfield", None)
        elif d == "sync":
            from dostawcy import sync_so
            dziala, komunikat = sync_so.gotowy()
        elif d == "yapper":
            from dostawcy import yapper
            dziala, komunikat = yapper.gotowy()
            _saldo.pop("yapper", None)
        elif d == "wavespeed":
            from dostawcy import wavespeed
            dziala, komunikat = wavespeed.gotowy()        # GET /balance - nic nie kosztuje
            _saldo.pop("wavespeed", None)
        elif d == "elevenlabs":
            from dostawcy import elevenlabs
            dziala, komunikat = elevenlabs.gotowy()
            elevenlabs._stan_klucza.clear()
            _saldo.pop("elevenlabs", None)
        elif d == "openrouter":
            dziala, komunikat = asystent.test_klucza()
        elif d == "telegram":
            from dostawcy import telegram
            dziala, komunikat = telegram.gotowy()
            if dziala and telegram.sparowany():
                telegram.wyslij_tekst("rolki-ai: polaczenie z panelem dziala.")
                komunikat += " - wyslalem testowa wiadomosc"
        else:
            return _blad("Nieznany dostawca.")
    except Exception as e:
        dziala, komunikat = False, f"{type(e).__name__}: {e}"
    _konta_test[d] = {"dziala": bool(dziala), "komunikat": str(komunikat)}
    return _ok(dziala=bool(dziala), komunikat=str(komunikat))


@app.route("/api/modele")
def api_modele():
    d = request.args.get("dostawca", "higgsfield")
    typ = request.args.get("typ") or None
    try:
        return _ok(modele=_lista_modeli(d, typ, odswiez=request.args.get("odswiez") == "1"))
    except dostawcy.BladDostawcy as e:
        return _blad(e)
    except Exception as e:
        return _blad(f"{type(e).__name__}: {e}")


def _normalizuj_glos(g):
    if not isinstance(g, dict):
        return {"id": str(g), "nazwa": str(g), "typ": "", "opis": ""}
    return {"id": str(g.get("id") or g.get("voice_id") or g.get("voiceId") or ""),
            "nazwa": str(g.get("name") or g.get("display_name") or g.get("id") or ""),
            "typ": str(g.get("voice_type") or g.get("type") or g.get("provider") or ""),
            "opis": " ".join(str(g.get(k)) for k in ("gender", "accent", "language", "description") if g.get(k))[:120]}


@app.route("/api/glosy")
def api_glosy():
    d = request.args.get("dostawca", "sync")
    try:
        if d == "sync":
            from dostawcy import sync_so
            surowe = sync_so.glosy()
        else:
            from dostawcy import higgsfield
            surowe = higgsfield.glosy()
        return _ok(glosy=[_normalizuj_glos(g) for g in surowe])
    except dostawcy.BladDostawcy as e:
        return _blad(e)
    except Exception as e:
        return _blad(f"{type(e).__name__}: {e}")


# ---------------- zdjecia / lipsync / dziennik / budzet / autopilot ----------------

@app.route("/api/zdjecia")
def api_zdjecia():
    try:
        slug = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    lista = []
    for z in baza.lista_zdjec(slug):
        z = dict(z)
        z["url"] = _url_pliku(z.get("plik"))
        if z.get("typ") == "swap":
            z["zrodlo_url"] = _url_pliku(z.get("zrodlo"))           # miniatura wstawionego zdjecia (wejscie -> wynik)
            z["stroj_url"] = _url_pliku(z.get("stroj")) if z.get("stroj") else None
        lista.append(z)
    return _ok(zdjecia=lista)


ZDJECIE_SIE_ROBI = ("To zdjecie wlasnie sie robi - fabryka dokonczy je sama (takze po restarcie panelu). Usuniecie teraz zgubiloby "
                    "oplacony wynik - najpierw 'Przestan czekac' (gdy sprawdzisz w apce Higgsfield).")


@app.route("/api/zdjecia/<int:zid>", methods=["DELETE"])
def api_usun_zdjecie(zid):
    """Usuwa wpis zdjecia (w kolejce = wypada z kolejki, nic nie poszlo); w toku -> 409. Sprawdzenie statusu i usuniecie pod jedna
    blokada - dyspozytor nie przejmie go w tej samej chwili do wysylania."""
    try:
        slug = _wymaga_modelki()
        z = baza.usun_zdjecie_jesli(slug, zid, poza=("w_toku",))
        if z is None:
            raise ValueError(f"Nie ma zdjecia #{zid}.")
        if z.get("status") == "w_toku":
            return _blad(ZDJECIE_SIE_ROBI, 409)
        if request.args.get("plik") == "1" and z.get("plik") and os.path.isfile(z["plik"]) and _plik_dozwolony(z["plik"]):
            os.remove(z["plik"])
    except ValueError as e:
        return _blad(e)
    return _ok()


@app.route("/api/zdjecia/<int:zid>/przerwij", methods=["POST"])
def api_przerwij_zdjecie(zid):
    """'Przestan czekac' na zdjecie w toku (np. utknelo bez numeru joba). Wymaga {"potwierdzam": true} - kredyty mogly juz
    zejsc. Zdjecie dostaje status 'blad' z prosba o sprawdzenie w apce. Nie w trakcie samego wysylania (409)."""
    if not (request.json or {}).get("potwierdzam"):
        return _blad("Potwierdz: kredyty za to zdjecie mogly juz zejsc - sprawdz najpierw w apce Higgsfield.")
    try:
        slug = _wymaga_modelki()
        z = baza.zdjecie(slug, zid)
        if z.get("status") != "w_toku":
            return _blad("To zdjecie nie czeka na generacje." + (" Jest w kolejce - nic jeszcze nie poszlo, mozesz je po prostu usunac."
                                                                  if z.get("status") == "w_kolejce" else ""))
        if zdjecia_swap.wysylane(slug, zid):
            return _blad("Zdjecie jest wlasnie wysylane - poczekaj chwile i sprobuj jeszcze raz.", 409)
        marker = z.get("w_toku") or {}
        job = marker.get("job_id") or z.get("job_id")
        notatki = (f"Przerwane recznie (czekanie na {marker.get('model') or 'Higgsfield'}" + (f", job {job}" if job else ", bez numeru joba")
                   + "). Sprawdz w apce Higgsfield (lista generacji), czy zdjecie nie powstalo - jesli tak, pobierz je stamtad.")
        baza.ustaw_zdjecie(slug, zid, status="blad", w_toku=None, powod="inny", notatki=notatki)
    except ValueError as e:
        return _blad(e)
    baza.dziennik_zapisz("uwaga", f"zdjecie #{zid}: {notatki}", modelka=slug, zdjecie=zid)
    return _ok(zdjecie=baza.zdjecie(slug, zid))


# ---------------- zdjecia: podmiana postaci (swap, 3.2, zdjecia_swap.py) ----------------

def _zrodlo_swap(slug, nazwa):
    """Nazwa wstawionego zdjecia (z /api/swap/zdjecie) -> sciezka w modelki/<slug>/swap_zrodla/ (tylko stamtad)."""
    nazwa = os.path.basename(str(nazwa or "").strip())
    sciezka = os.path.join(baza.folder_swap_zrodel(slug), nazwa)
    if not nazwa or not os.path.isfile(sciezka):
        raise ValueError("Wstaw zdjecie jeszcze raz (nie widze go na dysku).")
    return sciezka


OPCJE_SWAP = ("model", "proporcje", "jakosc", "rozdzielczosc", "ile", "stroj", "dopisek")


def _opcje_swap(dane):
    return {k: dane[k] for k in OPCJE_SWAP if k in dane and dane[k] is not None}


@app.route("/api/swap")
def api_swap_katalog():
    """Strona Zdjecia: modele (chipy wg schematu modelu), stroje z biblioteki ze zdjeciem (ulubione na gorze), domyslne."""
    try:
        slug = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    kat = zdjecia_swap.katalog(slug)
    kat["stroje"] = _biblioteka_dla_panelu(tylko_ze_zdjeciem=True)
    kat["folder"] = baza.folder_zdjec(slug)
    return _ok(**kat)


@app.route("/api/swap/zdjecie", methods=["POST"])
def api_swap_zdjecie():
    """Wstawione zdjecie (multipart `plik`) -> kopia obrocona wg EXIF, bez metadanych w modelki/<slug>/swap_zrodla/. Nic nie
    wysyla do Higgsfield. Zwraca {zrodlo (nazwa pliku), url, nazwa, szer, wys, proporcje {model: najblizsze}}."""
    try:
        slug = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    plik = request.files.get("plik") or next(iter(request.files.getlist("pliki")), None)
    if not plik or not plik.filename:
        return _blad("Wybierz zdjecie (png, jpg, webp).")
    try:
        sciezka = zdjecia_swap.zapisz_zrodlo(slug, plik.stream, plik.filename)
    except ValueError as e:
        return _blad(e)
    wym = zdjecia_swap.wymiary(sciezka)
    proporcje = {}
    for m in zdjecia_swap.MODELE:
        dost = zdjecia_swap.chipy(zdjecia_swap.schemat(m))["proporcje"]
        proporcje[m] = zdjecia_swap.najblizsze_proporcje(wym[0], wym[1], dost) if wym else None
    return _ok(zrodlo=os.path.basename(sciezka), url=_url_pliku(sciezka), nazwa=_nazwa_pliku(plik.filename),
               szer=wym[0] if wym else None, wys=wym[1] if wym else None, proporcje=proporcje)


@app.route("/api/swap/wycena", methods=["POST"])
def api_swap_wycena():
    """Cena N zdjec (darmowe `generate cost` bez mediow, cache po parametrach) + bezpieczniki. Nic nie tworzy, nic nie wgrywa."""
    dane = request.json or {}
    try:
        slug = _wymaga_modelki()
        zrodlo = _zrodlo_swap(slug, dane["zrodlo"]) if dane.get("zrodlo") else None
        saldo = (_saldo_dostawcy("higgsfield") or {}).get("kredyty")
        w = zdjecia_swap.wycena(slug, _opcje_swap(dane), zrodlo=zrodlo, saldo=saldo)
    except ValueError as e:
        return _blad(e)
    return _ok(**w)


@app.route("/api/swap", methods=["POST"])
def api_swap_generuj():
    """'Generuj' (3.3): N zdjec OD RAZU do kolejki zdjec - niezaleznie od innych zdjec i od zadan konsoli (rolki, autopilot).
    Dyspozytor w tle wysyla je rownolegle (najwyzej `zdjecia_rownolegle` w toku naraz, nadmiar czeka w kolejce). Wymaga "kr"
    (cena 1 zdjecia z wyceny, ktora user widzial) - przed kazdym wyslaniem cena jeszcze raz, wyzsza = nic nie idzie. Rezerwacja
    w limicie dnia i saldzie atomowa; odmowa = 400 z powodem i kodem (nic nie powstalo)."""
    dane = request.json or {}
    try:
        slug = _wymaga_modelki()
        zrodlo = _zrodlo_swap(slug, dane.get("zrodlo"))
        opcje = _opcje_swap(dane)
        kr = float(dane["kr"]) if dane.get("kr") not in (None, "") else None
        zdjecia_swap.zbuduj(slug, zrodlo, opcje)          # zle opcje / brak referencji -> 400 od razu, zanim cokolwiek ruszy
    except (ValueError, TypeError) as e:
        return _blad(e)
    if kr is None or kr <= 0:
        return _blad("Najpierw sprawdz cene - bez wyceny nic nie wysylam.")
    zdjecia_swap.KOLEJKA.uruchom()                       # dyspozytor dziala od startu panelu; gdyby nie - rusza teraz
    saldo = (_saldo_dostawcy("higgsfield") or {}).get("kredyty")
    try:
        ids = zdjecia_swap.zlec(slug, zrodlo, opcje, kr=kr, saldo=saldo)
    except zdjecia_swap.Odmowa as e:
        return jsonify({"ok": False, "blad": str(e), "kod": e.kod}), 400
    except ValueError as e:
        return _blad(e)
    return _ok(ids=ids, kolejka=zdjecia_swap.stan_kolejki(slug))


@app.route("/api/swap/stop", methods=["POST"])
def api_swap_stop():
    """STOP na stronie Zdjecia: zdjecia z kolejki (wszystkie persony) -> 'anulowane' (nic nie poszlo, 0 kr); czekanie na joby w toku
    przerwane - przyjete joby dokoncza sie przy nastepnym sprawdzeniu (kolejne Generuj, przebieg autopilota, restart panelu)."""
    w = zdjecia_swap.zatrzymaj()
    return _ok(anulowane=len(w["anulowane"]), w_toku=w["w_toku"], kolejka=zdjecia_swap.stan_kolejki(_aktywna()))


@app.route("/api/lipsync")
def api_lipsync():
    try:
        slug = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    lista = []
    for l in baza.lista_lipsync(slug):
        l = dict(l)
        l["url"] = _url_pliku(l.get("plik_wynikowy"))
        lista.append(l)
    return _ok(lipsync=lista)


@app.route("/api/lipsync/<int:lid>", methods=["DELETE"])
def api_usun_lipsync(lid):
    try:
        slug = _wymaga_modelki()
        baza.usun_lipsync(slug, lid)
    except ValueError as e:
        return _blad(e)
    return _ok()


@app.route("/api/dziennik")
def api_dziennik():
    ile = max(1, min(1000, int(request.args.get("ile", 100) or 100)))
    return _ok(wpisy=baza.dziennik_ostatnie(ile, modelka=request.args.get("modelka") or None, typ=request.args.get("typ") or None))


@app.route("/api/budzet")
def api_budzet():
    dzis = {}
    for d, jednostka in (("higgsfield", "kr"), ("yapper", "kr"), ("sync", "c"), ("wavespeed", "c")):
        dzis[d] = {"wydano": baza.wydano_dzis(d), "limit": baza.limit_dzienny(d), "jednostka": jednostka}
    return _ok(budzet=baza.budzet(), dzis=dzis)


@app.route("/api/budzet", methods=["POST"])
def api_zapisz_budzet():
    dane = request.json or {}
    d = dane.get("dostawca", "higgsfield")
    if d not in dostawcy.NAZWY + ("sync",):
        return _blad(f"Nieznany dostawca '{d}'.")
    try:
        baza.zapisz_limit_dzienny(int(dane.get("max_kredyty_dziennie", 0) or 0), d)
    except (TypeError, ValueError) as e:
        return _blad(e)
    baza.dziennik_zapisz("info", f"limit dzienny {d}: {dane.get('max_kredyty_dziennie')}")
    return api_budzet()


@app.route("/api/autopilot", methods=["POST"])
def api_autopilot():
    wlacz = bool((request.json or {}).get("wlacz"))
    if wlacz:
        autopilot_start()
    else:
        autopilot_stop()
    return _ok(autopilot=_stan_autopilota())


@app.route("/api/autopilot/wznow", methods=["POST"])
def api_autopilot_wznow():
    """Zdejmuje hamulec (pauze po nieudanych rolkach) z aktywnej modelki albo wskazanej w {"slug"}."""
    slug = (request.json or {}).get("slug") or _aktywna()
    if not slug or slug not in baza.lista_modelek():
        return _blad("Brak aktywnej modelki.")
    stan = baza.autopilot_wznow(slug)
    baza.dziennik_zapisz("info", f"autopilot {slug}: wznowiony z panelu", modelka=slug)
    return _ok(autopilot_stan=stan)


# ---------------- szablony ----------------

@app.route("/api/szablony")
def api_szablony():
    try:
        aktywna = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    szablony = baza.lista_szablonow(aktywna)
    for s in szablony:
        s["placeholdery"] = baza.placeholdery_szablonu(s["tresc"])
    return _ok(szablony=szablony)


@app.route("/api/szablony", methods=["POST"])
def api_dodaj_szablon():
    try:
        aktywna = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    dane = request.json or {}
    nazwa = (dane.get("nazwa") or "").strip()
    tresc = (dane.get("tresc") or "").strip()
    if not nazwa or not tresc:
        return _blad("Podaj nazwe i tresc szablonu.")
    try:
        baza.dodaj_szablon(aktywna, nazwa, tresc)
    except ValueError as e:
        return _blad(e)
    return _ok()


@app.route("/api/szablony/<nazwa>", methods=["DELETE"])
def api_usun_szablon(nazwa):
    try:
        aktywna = _wymaga_modelki()
        baza.usun_szablon(aktywna, nazwa)
    except ValueError as e:
        return _blad(e)
    return _ok()


@app.route("/api/szablony/wypelnij", methods=["POST"])
def api_wypelnij_szablon():
    dane = request.json or {}
    return _ok(prompt=baza.wypelnij_szablon(dane.get("tresc", ""), dane.get("wartosci", {})))


# ---------------- teksty ----------------

@app.route("/api/teksty")
def api_teksty():
    try:
        aktywna = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    return _ok(teksty=baza.lista_tekstow(aktywna))


@app.route("/api/teksty", methods=["POST"])
def api_dodaj_teksty():
    try:
        aktywna = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    dane = request.json or {}
    surowe = dane.get("teksty", "")
    if isinstance(surowe, str):
        teksty = [b.strip() for b in surowe.split("---")] if "---" in surowe else surowe.splitlines()
    else:
        teksty = list(surowe)
    return _ok(dodano=baza.dodaj_teksty(aktywna, teksty, (dane.get("zrodlo") or "").strip()))


@app.route("/api/teksty/losuj", methods=["POST"])
def api_losuj_tekst():
    try:
        aktywna = _wymaga_modelki()
    except ValueError as e:
        return _blad(e)
    tekst = baza.losuj_tekst(aktywna)
    nieuzyte, wszystkie = baza.statystyki_tekstow(aktywna)
    return _ok(tekst=tekst, nieuzyte=nieuzyte, wszystkie=wszystkie)


# ---------------- zamykanie / start ----------------

CZEKAJ_NA_ZADANIE_PRZY_ZAMYKANIU_S = 20 * 60


def _zamknij_gdy_wolne(czekaj_max=CZEKAJ_NA_ZADANIE_PRZY_ZAMYKANIU_S):
    """Konczy proces, gdy zadanie w tle sie skonczy - NIGDY w trakcie wysylania rolki (upload + create): zamkniecie wtedy
    osierocilo by job (wysylka z CLI zyje dalej) i po restarcie poszedlby drugi, platny. Job juz wyslany (job_id zapisany)
    jest bezpieczny - po ponownym uruchomieniu panel dokonczy go sam (ten sam job)."""
    start = time.time()
    while True:
        wysyla = fabryka.trwa_wysylanie()
        if not wysyla and (not konsola.stan.get("trwa") or time.time() - start > czekaj_max):
            break
        time.sleep(0.5)
    time.sleep(0.5)
    os._exit(0)


@app.route("/api/zamknij", methods=["POST"])
def api_zamknij():
    """Zamyka panel (aktualizuj.bat zatrzymuje nim stary panel w tle przed startem nowego). Tylko z tego komputera (bind 127.0.0.1).
    Gdy cos sie robi: autopilot i STOP od razu, a proces konczy sie dopiero po bezpiecznym punkcie (nie w trakcie wysylania rolki).
    Rolka, ktora juz sie generuje u dostawcy, zostaje dokonczona po ponownym uruchomieniu (bez drugiej oplaty)."""
    trwa = bool(konsola.stan.get("trwa")) or fabryka.trwa_wysylanie()
    autopilot_stop()
    konsola.stop.set()
    zdjecia_swap.KOLEJKA.wstrzymaj()      # nic nowego z kolejki zdjec (zostaje na nastepny start); wysylane koncza wysylanie
    if trwa:
        komunikat = (f"Teraz trwa: {konsola.stan.get('typ') or 'wysylanie rolki'}. Zamkne panel, gdy skonczy sie biezacy krok "
                     f"(wysylanie rolki do Higgsfield/yapper/WaveSpeed nie jest przerywane). Rolka, ktora juz sie generuje, dokonczy sie "
                     f"po ponownym uruchomieniu - bez drugiej oplaty.")
        baza.dziennik_zapisz("info", "panel zamknie sie po biezacym kroku (aktualizacja / zamknij) - " + komunikat)
        threading.Thread(target=_zamknij_gdy_wolne, daemon=True).start()
        return _ok(zamykam=True, czekam=True, komunikat=komunikat)
    baza.dziennik_zapisz("info", "panel zamkniety (aktualizacja / zamknij)")
    threading.Thread(target=_zamknij_gdy_wolne, daemon=True).start()
    return _ok(zamykam=True, czekam=False)


def wznow_przy_starcie():
    """Start panelu: rolki w toku (job wyslany przed zamknieciem/aktualizacja) dokanczamy w tle - ten sam job, nic nowego nie
    wysylamy. Zwraca opis zadania albo None (nic do wznowienia / konsola zajeta - wtedy zrobi to autopilot/generuj).
    Zdjecia (3.3) dokancza i wysyla z kolejki dyspozytor zdjec (start_kolejki_zdjec) - osobno, obok rolek."""
    w_toku = {s: [p["id"] for p in baza.pomysly_w_toku(s)] for s in baza.lista_modelek()}
    w_toku = {s: ids for s, ids in w_toku.items() if ids}
    if not w_toku:
        return None
    baza.dziennik_zapisz("info", "start panelu: dokanczam rolki w toku (bez wysylania drugi raz): "
                         + ", ".join(f"{s} #{', #'.join(map(str, ids))}" for s, ids in w_toku.items()))
    try:
        return konsola.uruchom("wznow", None, lambda log, stop: fabryka.wznow_wszystkie(log=log, stop=stop))
    except Zajete:
        return None


def start_kolejki_zdjec():
    """Start panelu: dyspozytor zdjec w tle - dokancza zdjecia w toku (ten sam job) i wysyla te, ktore czekaly w kolejce."""
    s = zdjecia_swap.stan_kolejki()
    if s["w_toku"] or s["w_kolejce"]:
        baza.dziennik_zapisz("info", f"start panelu: zdjecia w toku {s['w_toku']}, w kolejce {s['w_kolejce']} - dokanczam w tle "
                             f"(bez wysylania drugi raz tego, co juz poszlo)")
    zdjecia_swap.KOLEJKA.uruchom()


def _port_zajety():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0



def _otworz_przegladarke():
    """Otwiera panel w przegladarce dopiero, gdy serwer odpowiada (panel.bat otwieral za wczesnie -> bialy blad)."""
    import urllib.request
    import webbrowser
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/stan", timeout=2).read(1)
            break
        except Exception:
            time.sleep(0.5)
    webbrowser.open(f"http://localhost:{PORT}")


def _foldery_na_pulpicie():
    """Przy starcie: Pulpit\\ROLKI AI\\tu wrzucasz rolki\\<persona> itd. (stare przed/po przenosi). Nie wywala panelu."""
    try:
        wyniki = baza.przygotuj_foldery_pulpitu_wszystkich()
    except Exception as e:
        print(f"(foldery na pulpicie: {e})")
        return
    for slug, w in wyniki.items():
        if w.get("blad"):
            baza.dziennik_zapisz("uwaga", f"foldery na pulpicie ({slug}): {w['blad']}", modelka=slug)
        elif w.get("zmienione"):
            baza.dziennik_zapisz("info", "foldery na pulpicie: " + ", ".join(f"{k} -> {v}" for k, v in w["zmienione"].items()), modelka=slug)
        f = w.get("foldery") or {}
        if f.get("zrodla_dir"):
            print(f"  {slug}: wrzucasz do {f['zrodla_dir']}  |  gotowe: {f.get('wyniki_dir')}")


def main():
    if _port_zajety():
        # panel juz dziala (np. w tle z autostartu) - nie wywalamy sie, tylko pokazujemy ten, ktory jest
        print(f"Panel rolki-ai juz dziala: http://localhost:{PORT} (otwieram w przegladarce). "
              f"Zeby go zrestartowac po aktualizacji, uzyj aktualizuj.bat.")
        if "--bez-przegladarki" not in sys.argv:
            import webbrowser
            webbrowser.open(f"http://localhost:{PORT}")
        return 0
    print(f"Panel rolki-ai {WERSJA}: http://localhost:{PORT}   (widget: http://localhost:{PORT}/widget)")
    _foldery_na_pulpicie()
    threading.Thread(target=fabryka.zapisz_diagnoze_w_dzienniku, args=("start panelu",), daemon=True).start()
    # chipy strony Zdjecia wg aktualnego schematu modeli (darmowe `model get`); bez CLI zostaje kopia z kodu
    threading.Thread(target=zdjecia_swap.odswiez_schematy, daemon=True, name="schematy-swap").start()
    wznow_przy_starcie()
    start_kolejki_zdjec()
    if "--autopilot" in sys.argv:
        autopilot_start()
    if "--bez-przegladarki" not in sys.argv:
        threading.Thread(target=_otworz_przegladarke, daemon=True).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
