# -*- coding: utf-8 -*-
"""Dostawca: WaveSpeedAI (Seedance 2.5 Video Edit Turbo, Seedance 2.5 Edit, Wan 3.0 / Wan 3.0 Prime reference-to-video) przez REST API.

Zrodla (2026-10-07, BEZ klucza - nic nie bylo wolane na zywo): https://wavespeed.ai/docs (submit-task, get-result, upload-files-api,
check-balance, pricing-api, predictions-api, error-codes, refund-policy), strony modeli i oficjalne SDK
github.com/WaveSpeedAI/wavespeed-python (src/wavespeed/api/client.py).

  https://api.wavespeed.ai/api/v3, naglowek `Authorization: Bearer <klucz>`, odpowiedzi w kopercie {"code": 200, "message", "data": {...}}
  GET  /balance                         -> data.balance (USD)
  POST /{model_id}                      -> cialo = parametry modelu (prompt, video, reference_images, resolution, generate_audio...)
                                           -> data {id, status "created", urls.get}. BEZ Idempotency-Key - POST idzie NAJWYZEJ RAZ
                                           (tak robi SDK: rozlaczenie po wyslaniu moze znaczyc, ze zadanie juz powstalo)
  GET  /predictions/{id}/result         -> data {id, status created|processing|completed|failed|cancelled|timeout|deleted,
                                           outputs [url], error, code?}
  POST /predictions {page, page_size, model} -> data.items [{id, model, status, created_at, outputs, error}] - BEZ wejsc zadania
  POST /media/uploads {filename, size, content_type} -> data {download_url, upload {method PUT, url (podpisany), headers}}
                                           -> PUT bajtow na upload.url z naglowkami biletu 1:1 (BEZ klucza API); plik zyje 7 dni.
       Stary sposob (gdy bilet nie dziala): POST /media/upload/binary multipart "file" -> data.download_url
  POST /model/price {model_id, inputs}  -> data {price, discounted_price, discount_rate, currency} - darmowa wycena (placi sie
                                           discounted_price); media z inputs WaveSpeed sam mierzy (dlugosc filmiku)
Bledy (error-codes): 1200 moderacja tresci ("The content contains sensitive information.") -> status 'nsfw' (zapas_nsfw dziala jak
przy Higgsfield), 1400/1401 zle parametry, 1402 nie da sie pobrac mediow, 1407 insufficient_credits. Nieudane zadania WaveSpeed
zwraca sam (Refund Policy); czy zwraca tez odrzucone przez moderacje - nie napisali, wiec liczymy je do limitu na wszelki wypadek.

Kwoty sa w CENTACH USD (JEDNOSTKA "c", int jak kredyty innych dostawcow): saldo, wycena, limit dzienny, bezpiecznik
wavespeed.min_kredyty / wavespeed.max_kredyty_na_rolke. Klucz: panel Konta (klucze.json) albo zmienna WAVESPEED_API_KEY.
Bez dziennego limitu WaveSpeed fabryka nic tu nie wyda (WYMAGA_LIMITU).
"""
import json
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import baza
import dostawcy
import sekrety
from dostawcy import BladDostawcy, BrakKlucza
from dostawcy import http

NAZWA = "wavespeed"
JEDNOSTKA = "c"              # centy USD
IDEMPOTENTNY = False         # brak Idempotency-Key: po przerwanym wysylaniu fabryka szuka zadania (znajdz) - nigdy nie wysyla drugi raz
WYMAGA_LIMITU = True         # bez dziennego limitu (Ustawienia -> Limity) fabryka nic tu nie wyda
BAZA_URL = "https://api.wavespeed.ai/api/v3"
HOST = "api.wavespeed.ai"
PANEL_URL = "https://wavespeed.ai/dashboard"
KLUCZE_URL = "https://wavespeed.ai/accesskey"
HISTORIA_URL = "https://wavespeed.ai/dashboard"
ODSTEP_ODPYTYWANIA = 10
WAZNOSC_UPLOADU_S = 6 * 24 * 3600     # WaveSpeed trzyma wgrane pliki 7 dni - po 6 wgrywamy jeszcze raz
MAX_PLIKU = 200 * 1024 * 1024         # limit uploadu WaveSpeed
LIMIT_PROMPTU_WAN = 5000              # Wan (jak u yappera; WaveSpeed limitu nie podaje)
OKNO_SZUKANIA_PRZED_S = 3 * 60        # znajdz(): zadanie utworzone najwyzej tyle przed wyslaniem (zegar laptopa vs serwer)...
OKNO_SZUKANIA_PO_S = 10 * 60          # ...i najwyzej tyle po
STATUSY_W_TOKU = ("", "created", "queued", "pending", "processing", "running", "starting", "in_progress")
STATUSY_OK = ("completed",)
STATUSY_BLEDU = ("failed", "cancelled", "canceled", "timeout", "deleted", "nsfw")
_ALIASY_OK = ("succeeded", "success")       # gdyby API kiedys tak napisalo - traktujemy jak completed
KOD_MODERACJI = 1200
KODY = {1200: "content_moderation", 1400: "invalid_request", 1401: "invalid_request", 1402: "media_access_failed",
        1403: "task_failed", 1405: "unknown_error", 1406: "retry_exhausted", 1407: "insufficient_credits",
        5000: "internal_error", 5003: "service_unavailable", 5004: "timeout"}
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
        ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".aac": "audio/aac", ".flac": "audio/flac", ".m4a": "audio/mp4", ".opus": "audio/ogg"}

MODEL_DOMYSLNY = "bytedance/seedance-2.5/video-edit-turbo"
# Modele, dla ktorych umiemy zbudowac cialo zapytania i policzyc cene. Cennik w CENTACH za sekunde (strony modeli 2026-10-07):
#   edit_turbo: (wejscie + wyjscie) x 11 c + wyjscie x doplata rozdzielczosci (720p 2 c, 1080p 4 c) - 10 s klip 1080p = $2.60
#   edit:       (wejscie + wyjscie) x stawka rozdzielczosci (480p 11 c, 720p 22 c, 1080p 55 c)
#   r2v (Wan):  (filmik referencyjny, max 15 s, zaokraglony w gore + wyjscie) x stawka rozdzielczosci
MODELE = {
    "bytedance/seedance-2.5/video-edit-turbo": {
        "nazwa": "Seedance 2.5 Edit Turbo", "opis": "podmiana persony w filmiku, najtaniej w 1080p (polecane)",
        "rodzaj": "edit", "prompt": "persona", "rozdzielczosci": ("720p", "1080p"), "max_wideo_s": 15.0, "min_wideo_s": 2.0,
        "max_obrazow": 30, "cennik": {"wzor": "edit_turbo", "baza": 11, "doplata": {"720p": 2, "1080p": 4}}},
    "bytedance/seedance-2.5/video-edit": {
        "nazwa": "Seedance 2.5 Edit", "opis": "zwykła edycja: tania w 480p, w 1080p ok. 4x droższa od Turbo",
        "rodzaj": "edit", "prompt": "persona", "rozdzielczosci": ("480p", "720p", "1080p"), "max_wideo_s": 30.0, "min_wideo_s": 4.0,
        "max_obrazow": 30, "cennik": {"wzor": "edit", "stawki": {"480p": 11, "720p": 22, "1080p": 55}}},
    "alibaba/wan-3.0/reference-to-video": {
        "nazwa": "Wan 3.0 (reference-to-video)", "opis": "filmik jako wzór ruchu + zdjęcia persony; prompt z prompty/wan.txt",
        "rodzaj": "r2v", "prompt": "wan", "rozdzielczosci": ("480p", "720p", "1080p"), "max_wideo_s": 15.0, "min_wideo_s": 1.0,
        "max_obrazow": 10, "aspect": ("16:9", "9:16", "1:1", "4:3", "3:4"), "dlugosci": (2, 30), "suma_max_s": 30,
        "cennik": {"wzor": "r2v", "stawki": {"480p": 5, "720p": 10, "1080p": 20}}},
    "alibaba/wan-3.0-prime/reference-to-video": {
        "nazwa": "Wan 3.0 Prime (reference-to-video)", "opis": "ostrzejszy i stabilniejszy od Wan 3.0, 1,5x droższy; prompt z wan.txt",
        "rodzaj": "r2v", "prompt": "wan", "rozdzielczosci": ("480p", "720p", "1080p"), "max_wideo_s": 15.0, "min_wideo_s": 1.0,
        "max_obrazow": 10, "aspect": ("16:9", "9:16", "1:1", "4:3", "3:4"), "dlugosci": (2, 30), "suma_max_s": 30,
        "cennik": {"wzor": "r2v", "stawki": {"480p": 7.5, "720p": 15, "1080p": 30}}},
}
_WZORZEC_HIGGSFIELD = re.compile(r"@\[\s*Image\s*(\d+)\s*\]\(\s*image_\d+\s*\)", re.I)
_WZORZEC_IMAGE = re.compile(r"@Image\s*(\d+)", re.I)
_SLOWA_MODERACJI = ("sensitive information", "sensitive content", "nsfw", "moderation", "content policy", "safety checker",
                    "safety check")

_ostatnia_wycena = {}


# ---------------- HTTP ----------------

class BladWaveSpeed(BladDostawcy):
    def __init__(self, tekst, status=None, kod=""):
        super().__init__(tekst)
        self.status = status
        self.kod = kod


def _naglowki():
    klucz = sekrety.klucz(NAZWA)
    if not klucz:
        raise BrakKlucza("Brak klucza API WaveSpeed - wpisz go w panelu (Ustawienia -> Konta) albo ustaw WAVESPEED_API_KEY.")
    return {"Authorization": f"Bearer {klucz}"}


def _url(sciezka_lub_url):
    """'/balance' -> https://api.wavespeed.ai/api/v3/balance; pelny adres https://api.wavespeed.ai/... bez zmian.
    Pelny adres na INNY host -> BladDostawcy (klucz API idzie tylko do api.wavespeed.ai)."""
    s = str(sciezka_lub_url or "")
    if s.startswith(("http://", "https://")):
        host = (urlparse(s).hostname or "").lower()
        if host != HOST:
            raise BladDostawcy(f"WaveSpeed: adres spoza {HOST} ({host}) - nie wysylam tam klucza API")
        return s
    if s.startswith("/api/v3/"):
        return "https://" + HOST + s
    return BAZA_URL + (s if s.startswith("/") else "/" + s)


def _kod_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _moderacja(kod=None, tekst=""):
    return _kod_int(kod) == KOD_MODERACJI or any(s in str(tekst or "").lower() for s in _SLOWA_MODERACJI)


def _opis_i_kod(status, tekst):
    """Tresc bledu HTTP WaveSpeed -> (czytelny opis, kod slowny do _blad_trwaly)."""
    msg, kod_app = "", None
    try:
        d = json.loads(tekst)
    except (TypeError, ValueError):
        d = None
    if isinstance(d, dict):
        dane = d.get("data") if isinstance(d.get("data"), dict) else {}
        msg = str(d.get("message") or d.get("error") or d.get("msg") or dane.get("error") or dane.get("message") or "")
        for kand in (dane.get("code"), d.get("code")):
            k = _kod_int(kand)
            if k is not None and k not in (0, 200, status):
                kod_app = k
                break
    msg = msg or str(tekst or "")[:300]
    if (status or 0) < 500 and _moderacja(kod_app, msg):      # 5xx to awaria serwera, nie decyzja filtra
        return f"WaveSpeed odrzucil tresc (NSFW / moderacja, kod {KOD_MODERACJI}): {msg}".strip(), "content_moderation"
    if status == 401:
        return "WaveSpeed 401: zly klucz API (sprawdz w panelu Ustawienia -> Konta)", "unauthorized"
    niski = msg.lower()
    if kod_app == 1407 or status == 402 or any(x in niski for x in ("insufficient", "enough credit", "enough balance", "low balance")):
        return (f"WaveSpeed: za malo pieniedzy na koncie (insufficient credits) - doladuj na {PANEL_URL} (Billing). {msg}".strip(),
                "insufficient_credits")
    if status == 429:
        return "WaveSpeed 429: za duzo zapytan naraz (limit konta) - sprobuje pozniej", "rate_limited"
    if status == 403:
        return f"WaveSpeed 403: konto nie ma dostepu ({msg})", "forbidden"
    kod_slowny = KODY.get(kod_app, "invalid_request" if status in (400, 422) else "")
    return f"WaveSpeed {status}{f' kod {kod_app}' if kod_app else ''}: {msg}".strip(), kod_slowny


def _wywolaj(metoda, sciezka, dane=None, timeout=120, powtorki=http.POWTORKI):
    try:
        odp = http.zapytanie(metoda, _url(sciezka), dane=dane, naglowki=_naglowki(), timeout=timeout, powtorki=powtorki)
    except http.BladHTTP as e:
        opis, kod = _opis_i_kod(e.status, e.tekst)
        if e.status == 0:
            opis = f"WaveSpeed: blad sieci ({str(e.tekst)[:200]})"
        raise BladWaveSpeed(opis, status=e.status, kod=kod)
    return odp


def _dane(odp, co=""):
    """Koperta {"code", "message", "data"} -> data. Kod bledu w kopercie (np. 400 przy HTTP 200) -> BladWaveSpeed."""
    if not isinstance(odp, dict):
        raise BladDostawcy(f"WaveSpeed{co}: dziwna odpowiedz: {str(odp)[:200]}")
    kod = _kod_int(odp.get("code"))
    dane = odp.get("data")
    if kod is not None and kod not in (0, 200) and not isinstance(dane, dict):
        status = kod if 100 <= kod < 600 else 400
        opis, slowny = _opis_i_kod(status, json.dumps(odp))
        raise BladWaveSpeed(opis, status=status, kod=slowny)
    return dane if isinstance(dane, dict) else odp


# ---------------- konto ----------------

def saldo():
    """Saldo w CENTACH USD (GET /balance -> data.balance w dolarach)."""
    d = _dane(_wywolaj("GET", "/balance", timeout=20, powtorki=1), " /balance")
    for k in ("balance", "available_balance", "credits"):
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return int(round(float(v) * 100))
    raise BladDostawcy(f"WaveSpeed: GET /balance bez pola balance: {str(d)[:200]}")


def gotowy():
    if not sekrety.klucz(NAZWA):
        return False, "brak klucza API WaveSpeed (panel -> Konta)"
    try:
        c = saldo()
    except BladDostawcy as e:
        return False, str(e)
    return True, f"klucz dziala, saldo {usd(c)}" + ("" if c > 0 else f" - doladuj konto ({PANEL_URL} -> Billing)")


def usd(centy):
    """260 -> '$2.60' (None -> '$?')."""
    if centy is None:
        return "$?"
    return f"${int(centy) / 100:.2f}"


def modele():
    """Modele, ktore fabryka umie wyslac do WaveSpeed (lista do selecta w panelu - bez zapytania do API)."""
    return [{"id": mid, "name": m["nazwa"], "type": "video", "description": m["opis"]} for mid, m in MODELE.items()]


def zasady_modelu(model):
    """Zasady modelu z MODELE (max_wideo_s, rozdzielczosci, max_obrazow...). Nieznany model -> BladDostawcy."""
    model = (model or MODEL_DOMYSLNY).strip()
    if model not in MODELE:
        raise BladDostawcy(f"WaveSpeed: nie znam modelu '{model}' - wybierz jeden z: {', '.join(MODELE)} "
                           f"(panel -> Ustawienia -> Jak robic rolki)")
    return MODELE[model]


def uzywa_promptu_persony(model):
    """Czy model dostaje prompt persony A/B (Seedance - zachowa tez stroj ze zdjecia), a nie prompt Wan (prompty/wan.txt)."""
    return (MODELE.get((model or MODEL_DOMYSLNY).strip()) or {}).get("prompt") == "persona"


# ---------------- wycena (cennik) ----------------

def _rozdzielczosc(chciana, dozwolone):
    """'1080p' w dozwolonych -> '1080p'; inaczej najwyzsza dozwolona nizsza od chcianej, a gdy takiej nie ma - najnizsza."""
    def wys(r):
        cyfry = "".join(ch for ch in str(r or "") if ch.isdigit())
        return int(cyfry) if cyfry else 720
    chciana = f"{wys(chciana)}p"
    if chciana in dozwolone:
        return chciana
    nizsze = [r for r in dozwolone if wys(r) <= wys(chciana)]
    return max(nizsze, key=wys) if nizsze else min(dozwolone, key=wys)


def _w_gore(sekundy, tolerancja):
    return int(math.ceil(max(0.0, float(sekundy) - tolerancja)))


def stawki_za_sekunde(model=None):
    """Ile centow kosztuje SEKUNDA KLIPU (wejscie + wyjscie tej samej dlugosci) per rozdzielczosc - do szacunku w panelu.
    480p u Turbo nie ma (idzie 720p)."""
    m = zasady_modelu(model)
    c = m["cennik"]
    wynik = {}
    for r in ("480p", "720p", "1080p"):
        rr = _rozdzielczosc(r, m["rozdzielczosci"])
        if c["wzor"] == "edit_turbo":
            wynik[r] = 2 * c["baza"] + c["doplata"].get(rr, 0)
        else:
            wynik[r] = 2 * c["stawki"][rr]
    return wynik


def _czasy(z, m):
    """(sekundy wejscia do rozliczenia, sekundy wyjscia) wg zasad modelu."""
    czas = z.get("video_czas")
    try:
        czas = float(czas) if czas else None
    except (TypeError, ValueError):
        czas = None
    if czas is None and z.get("video"):
        czas = float(m["max_wideo_s"])          # dlugosc filmiku nieznana -> liczymy najdrozszy przypadek, nigdy za malo
    if m["rodzaj"] == "edit":
        s = min(m["max_wideo_s"], max(m["min_wideo_s"], czas or 0.0))
        we = max(1, _w_gore(s, 0.05))           # wyjscie = dlugosc wejscia (zaokraglenia WaveSpeed nie podaje - liczymy w gore)
        return we, we
    lo, hi = m["dlugosci"]
    if z.get("video") and czas:
        ref = max(1, _w_gore(min(m["max_wideo_s"], max(m["min_wideo_s"], czas)), 0.001))   # "rounded up to a whole second"
        wy = max(lo, min(hi, m["suma_max_s"] - ref, int(round(czas))))
        return ref, wy
    dlugosc = z.get("duration") or (z.get("wavespeed") or {}).get("duration") or 5
    try:
        dlugosc = int(round(float(dlugosc)))
    except (TypeError, ValueError):
        dlugosc = 5
    return 0, max(lo, min(hi, dlugosc))


def szacunek(z):
    """Cena z cennika (centy, w gore) BEZ zapytania do API: {"c", "wejscie_s", "wyjscie_s", "rozdzielczosc", "model"}.
    To szacunek - prawdziwa cene podaje WaveSpeed (POST /model/price), a placi sie po wygenerowaniu."""
    model = ((z.get("wavespeed") or {}).get("model") or MODEL_DOMYSLNY).strip()
    m = zasady_modelu(model)
    rozdz = _rozdzielczosc(z.get("resolution") or "720p", m["rozdzielczosci"])
    we, wy = _czasy(z, m)
    c = m["cennik"]
    if c["wzor"] == "edit_turbo":
        centy = (we + wy) * c["baza"] + wy * c["doplata"].get(rozdz, 0)
    else:
        centy = (we + wy) * c["stawki"][rozdz]
    return {"c": int(math.ceil(centy - 1e-9)), "wejscie_s": we, "wyjscie_s": wy, "rozdzielczosc": rozdz, "model": model}


# ---------------- uploady ----------------

def _plik_cache(slug):
    return os.path.join(baza.folder_modelki(slug), "uploady_wavespeed.json")


def _klucz_pliku(sciezka):
    return os.path.normcase(os.path.abspath(sciezka))


def _z_cache(slug, sciezka):
    if not slug or not os.path.isfile(sciezka):
        return None
    try:
        wpis = baza._wczytaj_json(_plik_cache(slug), {}).get(_klucz_pliku(sciezka))
    except (OSError, ValueError):
        return None
    if not wpis:
        return None
    st = os.stat(sciezka)
    swiezy = time.time() - float(wpis.get("czas") or 0) < WAZNOSC_UPLOADU_S
    if swiezy and wpis.get("size") == st.st_size and abs(wpis.get("mtime", 0) - st.st_mtime) < 1:
        return wpis.get("url")
    return None


def _do_cache(slug, sciezka, url):
    if not slug:
        return
    plik = _plik_cache(slug)
    st = os.stat(sciezka)
    with baza._rmw(plik):
        cache = baza._wczytaj_json(plik, {})
        cache[_klucz_pliku(sciezka)] = {"url": url, "size": st.st_size, "mtime": st.st_mtime, "czas": time.time(),
                                        "plik": os.path.basename(sciezka)}
        baza._zapisz_json(plik, cache)


def _download_url(d):
    if isinstance(d, dict):
        for k in ("download_url", "url", "file_url"):
            if isinstance(d.get(k), str) and d[k].startswith("http"):
                return d[k]
    return None


def wgraj(slug, sciezka):
    """Wgrywa lokalny plik do WaveSpeed (0 zl) i zwraca jego URL (download_url) do zapytania. Bilet POST /media/uploads ->
    PUT na podpisany adres z naglowkami biletu 1:1 (BEZ klucza API); gdy bilet nie dziala (404/405) - stary
    POST /media/upload/binary (multipart "file"). Cache per persona (rozmiar + data zmiany, max 6 dni - WaveSpeed trzyma 7)."""
    url = _z_cache(slug, sciezka)
    if url:
        return url
    nazwa = os.path.basename(sciezka)
    ext = os.path.splitext(nazwa)[1].lower()
    mime = MIME.get(ext)
    if not mime:
        raise BladDostawcy(f"WaveSpeed: format {ext or '?'} nie jest przyjmowany (jpg/png/webp/gif, mp4/mov/webm, mp3/wav...)")
    rozmiar = os.path.getsize(sciezka)
    if rozmiar > MAX_PLIKU:
        raise BladDostawcy(f"WaveSpeed: plik {nazwa} ma {rozmiar // (1024 * 1024)} MB, a limit to 200 MB")
    try:
        bilet = _dane(_wywolaj("POST", "/media/uploads", {"filename": nazwa, "size": rozmiar, "content_type": mime}, timeout=60),
                      " /media/uploads")
    except BladWaveSpeed as e:
        if e.status not in (404, 405):
            raise
        bilet = None
    if bilet is None:
        try:
            odp = http.multipart(_url("/media/upload/binary"), pliki={"file": sciezka}, naglowki=_naglowki(), timeout=900)
        except http.BladHTTP as e:
            raise BladWaveSpeed(f"WaveSpeed: upload {nazwa} nie wyszedl: {_opis_i_kod(e.status, e.tekst)[0]}", status=e.status)
        url = _download_url(_dane(odp, " /media/upload/binary"))
        if not url:
            raise BladDostawcy(f"WaveSpeed: upload {nazwa} bez download_url: {str(odp)[:300]}")
    else:
        instr = bilet.get("upload") if isinstance(bilet.get("upload"), dict) else {}
        metoda = str(instr.get("method") or "PUT").upper()
        if metoda != "PUT" or not instr.get("url"):
            raise BladDostawcy(f"WaveSpeed: bilet uploadu bez adresu PUT: {json.dumps(bilet)[:300]}")
        naglowki = {str(k): str(v) for k, v in instr["headers"].items()} if isinstance(instr.get("headers"), dict) else {}
        try:
            http.wyslij_plik(instr["url"], sciezka, naglowki=naglowki, metoda="PUT")
        except http.BladHTTP as e:
            # status=None: blad magazynu plikow (np. wygasly podpis), nie zapytania - zadanie na pewno nie poszlo, fabryka moze
            # sprobowac jeszcze raz (nowy bilet)
            raise BladWaveSpeed(f"WaveSpeed: upload {nazwa} nie wyszedl (HTTP {e.status})", status=None)
        url = _download_url(bilet)
        if not url:
            raise BladDostawcy(f"WaveSpeed: bilet uploadu bez download_url: {json.dumps(bilet)[:300]}")
    _do_cache(slug, sciezka, url)
    return url


# ---------------- zapytanie ----------------

def prompt_na_wavespeed(prompt):
    """Prompt persony (skladnia Higgsfielda) -> WaveSpeed: @[Image N](image_N) -> @Image N (numer = kolejnosc reference_images:
    referencje 01_, 02_..., stroj ostatni - tak samo jak u Higgsfielda). Reszta tresci bez zmian."""
    t = _WZORZEC_HIGGSFIELD.sub(lambda m: f"@Image {m.group(1)}", prompt or "")
    t = _WZORZEC_IMAGE.sub(lambda m: f"@Image {m.group(1)}", t)
    return t.strip()


def _prompt(z, m):
    w = z.get("wavespeed") or {}
    if m["prompt"] == "wan":
        prompt = (w.get("prompt_wan") or "").strip()
        problemy = []
        if not prompt:
            problemy.append("brak promptu Wan (plik prompty/wan.txt persony)")
        elif _WZORZEC_HIGGSFIELD.search(prompt):
            problemy.append("prompt ma skladnie @[Image N](image_N) z Higgsfielda - Wan jej nie zna (pisz 'the reference photos')")
        if len(prompt) > LIMIT_PROMPTU_WAN:
            problemy.append(f"prompt ma {len(prompt)} znakow, a model przyjmuje max {LIMIT_PROMPTU_WAN}")
        if problemy:
            raise BladDostawcy("WaveSpeed Wan: " + "; ".join(problemy))
        return prompt
    prompt = prompt_na_wavespeed(z.get("prompt"))
    if not prompt:
        raise BladDostawcy("WaveSpeed: brak promptu rolki (prompt persony A/B)")
    return prompt


def _wideo_do_wyslania(z, m, log=None, przytnij=True):
    """(sciezka filmiku, dlugosc) - dluzszy niz model przyjmuje (Turbo/Wan: 15 s) -> KOPIA pierwszych max-0,1 s w
    modelki/<slug>/zrodla_ciete/<nazwa>_maxNs.mp4 (oryginal bez zmian; ta sama nazwa co przy zapasie po NSFW).
    przytnij=False (podglad --dry-run): bez ffmpeg, tylko dlugosc po przycieciu."""
    wideo, czas = z.get("video"), z.get("video_czas")
    if not wideo or not czas or float(czas) <= float(m["max_wideo_s"]) + 0.05 or str(wideo).startswith("http"):
        return wideo, czas
    max_s = float(m["max_wideo_s"])
    if not przytnij:
        return wideo, round(max_s - 0.1, 2)
    slug = z.get("slug")
    if not slug:
        raise BladDostawcy(f"WaveSpeed: filmik ma {float(czas):.1f} s, a model przyjmuje max {m['max_wideo_s']:g} s")
    import klatki
    stem = os.path.splitext(os.path.basename(wideo))[0]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("_") or "plik"
    cel = os.path.join(baza.folder_modelki(slug), "zrodla_ciete", f"{stem}_max{int(max_s)}s.mp4")
    if not os.path.isfile(cel):
        try:
            klatki.przytnij(wideo, cel, max_s - 0.1)
        except Exception as e:
            raise BladDostawcy(f"WaveSpeed: nie moge przyciac filmiku do {max_s:g} s ({e})")
        if log:
            log(f"filmik ma {float(czas):.1f} s - do WaveSpeed ida pierwsze {max_s - 0.1:.1f} s (kopia {os.path.basename(cel)})")
    return cel, round(max_s - 0.1, 2)


def przygotuj(z, log=None, przytnij=True):
    """Zlecenie generyczne -> (model, cialo z LOKALNYMI sciezkami mediow, zasady modelu, szacunek). Waliduje (model, prompt,
    filmik) ZANIM cokolwiek pojdzie do WaveSpeed. Rozdzielczosc = rozdzielczosc rolki (z["resolution"], zasada <= 8 s -> 1080p)."""
    w = z.get("wavespeed") or {}
    model = (w.get("model") or MODEL_DOMYSLNY).strip()
    m = zasady_modelu(model)
    prompt = _prompt(z, m)
    wideo, czas = _wideo_do_wyslania(z, m, log=log, przytnij=przytnij)
    z = dict(z, video=wideo, video_czas=czas)
    sz = szacunek(z)
    obrazy = [o for o in (z.get("images") or []) if o][:m["max_obrazow"]]
    cialo = {"prompt": prompt}
    if m["rodzaj"] == "edit":
        if not wideo:
            raise BladDostawcy(f"WaveSpeed {model}: ten model edytuje filmik - pomysl nie ma filmiku zrodlowego")
        cialo["video"] = wideo
        if obrazy:
            cialo["reference_images"] = obrazy
        cialo["resolution"] = sz["rozdzielczosc"]
    else:
        if not obrazy and not wideo:
            raise BladDostawcy(f"WaveSpeed {model}: potrzebne zdjecia persony albo filmik referencyjny")
        if obrazy:
            cialo["reference_images"] = obrazy
        if wideo:
            cialo["reference_videos"] = [wideo]
        cialo["resolution"] = sz["rozdzielczosc"]
        aspect = z.get("aspect_ratio")
        cialo["aspect_ratio"] = aspect if aspect in m["aspect"] else "9:16"
        cialo["duration"] = sz["wyjscie_s"]
        cialo["enable_prompt_expansion"] = False
    # dzwiek: false = Seedance zostawia oryginalny dzwiek filmiku (Wan: bez wygenerowanego dzwieku)
    cialo["generate_audio"] = bool(w.get("generate_audio", False))
    for k, v in (w.get("parametry") or {}).items():
        if k not in ("prompt", "video", "reference_images", "reference_videos"):
            cialo[k] = v
    return model, cialo, m, sz


def _z_urlami(slug, cialo):
    """Lokalne sciezki mediow w ciele -> URL-e z uploadu WaveSpeed (adresy http zostaja)."""
    def url(x):
        return x if str(x).startswith(("http://", "https://")) else wgraj(slug, x)
    wynik = dict(cialo)
    if wynik.get("video"):
        wynik["video"] = url(wynik["video"])
    for pole in ("reference_images", "reference_videos"):
        if wynik.get(pole):
            wynik[pole] = [url(x) for x in wynik[pole]]
    return wynik


def _w_centy_w_gore(dolary):
    return int(math.ceil(float(dolary) * 100 - 1e-6))


def wycena(z, api=True):
    """{"c", "cennik", "api", "api_blad", "zrodlo", "szacunek"} - c = WIEKSZA z: cena z cennika (zawsze) i darmowa wycena WaveSpeed
    (POST /model/price; wgrywa media - 0 zl), gdy jest klucz. Cennik jest podloga: gdyby API nie zmierzylo filmiku albo podalo 0,
    bezpiecznik i tak liczy pelna stawke."""
    model, cialo, m, sz = przygotuj(z)
    wynik = {"c": sz["c"], "cennik": sz["c"], "api": None, "api_blad": None, "zrodlo": "cennik", "szacunek": sz, "model": model}
    if api and sekrety.klucz(NAZWA):
        try:
            wejscie = _z_urlami(z.get("slug"), cialo)
            d = _dane(_wywolaj("POST", "/model/price", {"model_id": model, "inputs": wejscie}, timeout=60, powtorki=2), " /model/price")
            placisz = d.get("discounted_price")
            if not isinstance(placisz, (int, float)) or isinstance(placisz, bool):
                placisz = d.get("price")
            if isinstance(placisz, (int, float)) and not isinstance(placisz, bool):
                wynik["api"] = _w_centy_w_gore(placisz)
                if wynik["api"] > wynik["c"]:
                    wynik["c"], wynik["zrodlo"] = wynik["api"], "api"
            else:
                wynik["api_blad"] = f"bez ceny: {str(d)[:200]}"
        except BrakKlucza:
            pass
        except BladDostawcy as e:
            wynik["api_blad"] = str(e)[:300]
    _ostatnia_wycena.clear()
    _ostatnia_wycena.update(wynik)
    return wynik


def koszt(z):
    """Koszt rolki w CENTACH (wycena(); bez klucza - sam cennik). Nie wydaje pieniedzy."""
    return wycena(z)["c"]


def opis_wyceny():
    """Skad ostatnia wycena (do logu fabryki): cennik / WaveSpeed API."""
    w = _ostatnia_wycena
    if not w:
        return ""
    if w.get("api") is None:
        return "szacunek z cennika" + (f" (wycena API nie wyszla: {w['api_blad'][:120]})" if w.get("api_blad") else "")
    if w.get("zrodlo") == "api":
        return f"wycena WaveSpeed {usd(w['api'])} (cennik {usd(w['cennik'])})"
    return f"cennik {usd(w['cennik'])} (WaveSpeed liczy {usd(w['api'])})"


def podglad(z):
    model, cialo, m, sz = przygotuj(z, przytnij=False)
    return f"POST {BAZA_URL}/{model} {json.dumps(cialo, ensure_ascii=False)}   (szacunek {usd(sz['c'])})"


# ---------------- wyniki ----------------

def _urls(dane):
    wynik = []
    for o in (dane or {}).get("outputs") or []:
        if isinstance(o, str) and o.startswith("http"):
            wynik.append(o)
        elif isinstance(o, dict) and isinstance(o.get("url"), str):
            wynik.append(o["url"])
    return wynik


def _normalizuj(dane, pid=None):
    """data predykcji -> {"job_id", "status", "urls", "blad", "surowe"}. Moderacja (kod 1200 / 'sensitive', has_nsfw_contents)
    -> status 'nsfw' - fabryka traktuje to jak odrzucenie NSFW (zapas_nsfw, hamulec autopilota go nie liczy)."""
    dane = dane if isinstance(dane, dict) else {}
    status = str(dane.get("status") or "").lower()
    if status in _ALIASY_OK:
        status = "completed"
    blad = dane.get("error")
    blad = blad.get("message") if isinstance(blad, dict) else blad
    blad = str(blad or "")
    kod = dane.get("code") if _kod_int(dane.get("code")) not in (None, 200) else (dane.get("error_code") or None)
    nsfw = dane.get("has_nsfw_contents")
    if status in STATUSY_BLEDU and _moderacja(kod, blad):
        status = "nsfw"
        blad = f"NSFW / moderacja WaveSpeed (kod {KOD_MODERACJI}): {blad}".strip()
    elif status == "completed" and isinstance(nsfw, list) and any(nsfw):
        status = "nsfw"
        blad = "NSFW: WaveSpeed oznaczyl wynik jako tresc NSFW (has_nsfw_contents)"
    return {"job_id": str(dane.get("id") or pid or ""), "status": status, "urls": _urls(dane), "blad": blad, "surowe": dane}


def zlec(z, klucz=None, znacznik=None, log=None):
    """Wysyla rolke BEZ czekania i od razu zwraca {"job_id", "status", "surowe"} (+ "gotowy", gdy zadanie juz sie skonczylo).
    WSZYSTKIE media sa wgrywane PRZED znacznikiem 'wysylam'; POST /{model} idzie RAZ (bez powtorek HTTP - WaveSpeed nie ma
    Idempotency-Key). Odpowiedz 4xx = serwer odrzucil zapytanie, zadanie NIE powstalo -> znacznik(wysylam=False) (fabryka moze
    sprobowac pozniej); blad sieci / 5xx = nie wiadomo -> fabryka szuka zadania (znajdz), nigdy nie wysyla drugi raz.
    klucz: WaveSpeed nie ma Idempotency-Key - ignorowany."""
    model, cialo, m, sz = przygotuj(z, log=log)
    cialo = _z_urlami(z.get("slug"), cialo)
    if znacznik:
        znacznik(wysylam=True, wideo_id=cialo.get("video") or (cialo.get("reference_videos") or [None])[0])
    try:
        odp = _wywolaj("POST", f"/{model}", cialo, timeout=120, powtorki=1)
        dane = _dane(odp, f" /{model}")
    except BladWaveSpeed as e:
        if znacznik and e.status and 400 <= int(e.status) < 500:
            znacznik(wysylam=False)
        raise
    wynik = _normalizuj(dane)
    if not wynik["job_id"]:
        raise BladDostawcy(f"WaveSpeed: POST /{model} bez id zadania: {json.dumps(odp)[:300]}")
    if koncowy(wynik["status"]):
        wynik["gotowy"] = dict(wynik)
    return wynik


def sprawdz(job_id):
    """GET /predictions/{id}/result (0 zl) -> {"job_id", "status", "urls", "blad", "surowe"}."""
    return _normalizuj(_dane(_wywolaj("GET", f"/predictions/{job_id}/result", timeout=60), " /predictions"), pid=job_id)


def koncowy(status):
    """Tylko znane statusy koncowe - nieznany status = dalej czekamy (po 24 h fabryka prosi o sprawdzenie w apce), zeby
    nie uznac oplaconej rolki za blad."""
    return status in STATUSY_OK or status in STATUSY_BLEDU


def udany(status):
    return status in STATUSY_OK


def nieudany(status):
    return status in STATUSY_BLEDU


def koszt_joba(wynik, wycena=None):
    """Ile zjadlo zadanie: WaveSpeed nie podaje kosztu w wyniku - bierzemy wycene sprzed wyslania. Udane = wycena; odrzucone
    przez moderacje (nsfw) = wycena NA WSZELKI WYPADEK (Refund Policy nie mowi, czy oddaja); failed/cancelled/timeout/deleted = 0
    (zwrot automatyczny wg Refund Policy). NIE liczymy z roznicy salda (reczne generacje na koncie nie zjadaja limitu fabryki)."""
    status = (wynik.get("status") or "").lower()
    if status in ("completed", "nsfw"):
        return int(wycena or 0)
    return 0


def _czas(s):
    """'2025-05-19T06:09:15.948268264Z' -> datetime UTC (ulamki sekund przyciete do 6 cyfr) albo None."""
    s = str(s or "").strip()
    if not s:
        return None
    s = re.sub(r"(\.\d{6})\d+", r"\1", s.replace("Z", "+00:00"))
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def znajdz(model, od=None, pomin=(), **_):
    """Zadanie wyslane przez przerwane wysylanie. Lista predykcji (POST /predictions) NIE ma wejsc zadania, wiec szukamy po
    modelu i czasie: utworzone w oknie [od - 3 min, od + 10 min], bez zadan znanych juz fabryce (wszystkie persony) i `pomin`.
    Dokladnie JEDNO = nasze; zero albo kilka = None (fabryka czeka, potem prosi o sprawdzenie historii WaveSpeed - nigdy nie
    wysyla drugi raz). Rzuca BladDostawcy, gdy listy nie da sie pobrac."""
    start = _czas(od)
    if not model or start is None:
        return None
    dane = _dane(_wywolaj("POST", "/predictions", {"page": 1, "page_size": 50, "model": model}, timeout=60), " /predictions")
    lista = dane.get("items") if isinstance(dane.get("items"), list) else (dane.get("list") or dane.get("data") or [])
    znane = set(str(x) for x in (pomin or []) if x) | baza.znane_job_id(NAZWA)
    kandydaci = []
    for it in lista if isinstance(lista, list) else []:
        if not isinstance(it, dict) or not it.get("id") or str(it["id"]) in znane:
            continue
        if it.get("model") and it.get("model") != model:
            continue
        if str(it.get("status") or "").lower() == "deleted":
            continue
        kiedy = _czas(it.get("created_at"))
        if kiedy is None or not (start - timedelta(seconds=OKNO_SZUKANIA_PRZED_S) <= kiedy <= start + timedelta(seconds=OKNO_SZUKANIA_PO_S)):
            continue
        kandydaci.append(it)
    if len(kandydaci) == 1:
        return _normalizuj(kandydaci[0])
    return None


def generuj(z, timeout="30m", log=None, klucz=None):
    """Jedna proba z czekaniem (bez zapisu stanu - rolki ida przez fabryke: zlec + sprawdz)."""
    w = zlec(z, klucz=klucz, log=log)
    jid = w["job_id"]
    koniec = time.time() + dostawcy.sekundy(timeout)
    wynik = w.get("gotowy") or w
    while not koncowy(wynik["status"]) and time.time() < koniec:
        time.sleep(ODSTEP_ODPYTYWANIA)
        wynik = sprawdz(jid)
    if not koncowy(wynik["status"]):
        raise BladDostawcy(f"WaveSpeed: zadanie {jid} nie skonczylo sie w {timeout}")
    return wynik


def pobierz(url, sciezka):
    return http.pobierz(url, sciezka)
