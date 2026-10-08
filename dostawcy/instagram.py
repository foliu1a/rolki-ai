# -*- coding: utf-8 -*-
"""Zrodlo klipow z Instagrama przez Apify (scrape po stronie Apify - omija Mullvada, NIE loguje sie na konto usera).

Pobieramy NAJNOWSZE rolki z publicznych profili tworczyn (wskazuje je user) przez zewnetrzny serwis Apify. Nic nie leci
z tej maszyny do Instagrama - Apify robi scrape u siebie i oddaje nam gotowa liste (shortcode, adres strony, adres pliku z CDN,
autor, opis, dlugosc, polubienia, data). To zrodlo klipow do istniejacego character swapa (ruch/scena/ubranie ze zrodla,
twarz+sylwetka persony z referencji). Filtrowaniem (dobre/slabe) i zapisem do wrzutni zajmuje sie instagram_rolki.py.

  https://api.apify.com/v2, naglowek `Authorization: Bearer <klucz>` (token NIE idzie w URL - prywatnosc)
  POST /acts/<actor>/run-sync-get-dataset-items   cialo = input actora -> JSON: lista itemow z datasetu (run + dataset w jednym)
  GET  /users/me                                  -> {data: {plan, username, ...}} - sprawdzenie klucza (0 zl)

Klucz: panel Konta (klucze.json, `sekrety.klucz("apify")`) albo zmienna APIFY_API_KEY. Bez klucza NIC nie wolamy (BrakKlucza) -
fabryka i tak nie odpala zywego scrape, dopoki user nie wklei klucza.

Pobieranie samego pliku wideo (pobierz) idzie z CDN Instagrama (scontent/fbcdn) - to moze blokowac Mullvad z tej maszyny.
Gdy sie nie uda, rzucamy jasny wyjatek i zostawiamy HACZYK pobierz_przez_apify() (domyslnie wylaczony, user wlacza swiadomie).
"""
import os
import re
import shutil
import urllib.error
import urllib.request

import sekrety
from dostawcy import BladDostawcy, BrakKlucza
from dostawcy import http

NAZWA = "apify"                       # klucz w klucze.json / env APIFY_API_KEY (sekrety.klucz("apify"))
JEDNOSTKA = "usd"                     # Apify rozlicza w USD (nie ma "kredytow" jak generatory) - do paska nie wchodzi
BAZA_URL = "https://api.apify.com/v2"
HOST = "api.apify.com"
PANEL_URL = "https://console.apify.com/account/integrations"
KLUCZE_URL = "https://console.apify.com/settings/integrations"

# Actor Apify do pobrania rolek po profilu. Trzymany w stalej, zeby dalo sie podmienic bez ruszania reszty kodu.
# Domyslnie ogolny scraper IG (resultsType=posts zwraca tez reele); mozna podmienic na dedykowany reel-scraper,
# np. "apify~instagram-reel-scraper", gdyby dawal lepsze wyniki. W URL actora uzywa sie "~" zamiast "/".
ACTOR_ROLKI = "apify~instagram-scraper"
# Haczyk na pobieranie pliku przez Apify (gdy CDN IG blokuje Mullvada) - actor re-hostujacy wideo. NIESPRAWDZONE na zywo.
ACTOR_POBIERANIE = "apify~instagram-scraper"
# Lista obserwowanych (following) - na IG widoczna TYLKO po zalogowaniu, wiec domyslnie nie dziala (patrz obserwowani()).
ACTOR_OBSERWOWANI = ""

PRZEGLADARKA_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36")
# rodzaje postow IG, ktore traktujemy jak film (reszta = zdjecia/karuzele - pomijamy)
_TYPY_WIDEO = ("video", "reel", "clips", "igtv")


# ---------------- HTTP / konto ----------------

def _naglowki():
    klucz = sekrety.klucz(NAZWA)
    if not klucz:
        raise BrakKlucza("Brak klucza API Apify - wpisz go w panelu (Ustawienia -> Konta) albo ustaw APIFY_API_KEY.")
    return {"Authorization": f"Bearer {klucz}"}


def _url(sciezka):
    return BAZA_URL + (sciezka if sciezka.startswith("/") else "/" + sciezka)


def _krotko(e):
    return str(e)[:200]


def _opis_bledu(e):
    """Tresc bledu HTTP Apify -> czytelny polski opis."""
    tekst = getattr(e, "tekst", "") or ""
    msg = tekst[:300]
    if isinstance(tekst, str) and tekst.strip().startswith("{"):
        import json
        try:
            d = json.loads(tekst)
            if isinstance(d.get("error"), dict):
                msg = str(d["error"].get("message") or d["error"].get("type") or msg)
        except (ValueError, TypeError):
            pass
    status = getattr(e, "status", 0)
    if status == 0:
        return f"Apify: blad sieci ({msg})"
    if status in (401, 403):
        return f"Apify {status}: zly klucz API (sprawdz w panelu Ustawienia -> Konta). {msg}".strip()
    if status == 402:
        return f"Apify 402: wyczerpany darmowy limit / brak srodkow na koncie. {msg}".strip()
    if status == 404:
        return f"Apify 404: nie znaleziono actora '{ACTOR_ROLKI}' - podmien ACTOR_ROLKI. {msg}".strip()
    if status == 429:
        return "Apify 429: za duzo zapytan naraz - sprobuje pozniej"
    return f"Apify {status}: {msg}".strip()


def _wywolaj_actor(actor_id, wejscie, timeout=300):
    """Uruchamia actora i oddaje gotowe itemy z datasetu (run-sync-get-dataset-items = run + pobranie w jednym).
    Zwraca liste itemow. Rzuca BladDostawcy z czytelnym opisem (bez klucza - BrakKlucza)."""
    if not actor_id:
        raise BladDostawcy("Apify: nie ustawiono actora (ACTOR_... pusty).")
    try:
        odp = http.zapytanie("POST", _url(f"/acts/{actor_id}/run-sync-get-dataset-items"),
                             dane=wejscie, naglowki=_naglowki(), timeout=timeout, powtorki=1)
    except http.BladHTTP as e:
        raise BladDostawcy(_opis_bledu(e))
    if isinstance(odp, list):
        return odp
    if isinstance(odp, dict):
        if odp.get("error"):
            err = odp["error"] if isinstance(odp["error"], dict) else {"message": odp["error"]}
            raise BladDostawcy("Apify: " + str(err.get("message") or err.get("type") or err)[:300])
        for k in ("items", "data"):
            if isinstance(odp.get(k), list):
                return odp[k]
    return []


def _dane_uzytkownika():
    """GET /users/me -> {plan, username} (do sprawdzenia klucza). None, gdy Apify nie poda pol."""
    try:
        odp = http.zapytanie("GET", _url("/users/me"), naglowki=_naglowki(), timeout=20, powtorki=1)
    except http.BladHTTP as e:
        raise BladDostawcy(_opis_bledu(e))
    d = odp.get("data") if isinstance(odp, dict) else None
    if not isinstance(d, dict):
        return None
    return {"plan": str((d.get("plan") or {}).get("id") or d.get("plan") or "") if not isinstance(d.get("plan"), str)
            else d.get("plan"), "username": d.get("username") or ""}


def gotowy():
    """(bool, komunikat) do panelu (Konta -> Sprawdz). Jak ElevenLabs: klucz dziala = zielone 'dziala',
    nawet gdy Apify nie poda zuzycia/limitu (saldo niedostepne)."""
    if not sekrety.klucz(NAZWA):
        return False, "brak klucza API Apify (panel -> Konta)"
    try:
        d = _dane_uzytkownika()
    except BladDostawcy as e:
        return False, str(e)
    if d and d.get("plan"):
        return True, f"klucz dziala, plan {d['plan']}"
    return True, "klucz dziala"


_stan_klucza = {}
CACHE_STANU_S = 600


def stan_klucza(odswiez=False):
    """('ok'|'brak'|'zly'|'nie_wiem', komunikat) - lekki GET /users/me (0 zl), cache 10 min. 'nie_wiem' = blad sieci/5xx
    (nie oznaczamy klucza jako zlego). Wzor jak elevenlabs.stan_klucza."""
    import time
    klucz = sekrety.klucz(NAZWA)
    if not klucz:
        return "brak", "brak klucza API Apify (panel -> Ustawienia -> Konta)"
    c = _stan_klucza
    if not odswiez and c.get("klucz") == klucz[-6:] and time.time() - c.get("czas", 0) < CACHE_STANU_S:
        return c["wynik"]
    try:
        http.zapytanie("GET", _url("/users/me"), naglowki=_naglowki(), timeout=15, powtorki=1)
        wynik = ("ok", "klucz dziala")
    except http.BladHTTP as e:
        if e.status in (401, 403):
            wynik = ("zly", _opis_bledu(e))
        else:
            return "nie_wiem", _opis_bledu(e)
    _stan_klucza.update(czas=time.time(), klucz=klucz[-6:], wynik=wynik)
    return wynik


# ---------------- rolki z profili ----------------

def _handle(h):
    """'@Noemi' / 'https://instagram.com/noemi/' / 'noemi' -> 'noemi' (bez @, male litery)."""
    s = str(h or "").strip()
    m = re.search(r"instagram\.com/([^/?#]+)", s, re.I)
    if m:
        s = m.group(1)
    return s.lstrip("@").strip().strip("/").lower()


def _url_profilu(handle):
    return f"https://www.instagram.com/{handle}/"


def _pierwsze(it, klucze):
    for k in klucze:
        v = it.get(k)
        if v not in (None, "", []):
            return v
    return None


def _liczba(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _video_url(it):
    """Adres pliku wideo z CDN. Rozne actory nazywaja go roznie; bierzemy pierwszy sensowny."""
    u = _pierwsze(it, ("videoUrl", "video_url", "videoUrlBackup", "video", "displayUrl" if it.get("isVideo") else "___"))
    if isinstance(u, str) and u.startswith("http"):
        return u
    for k in ("videoVersions", "video_versions", "media"):
        v = it.get(k)
        if isinstance(v, list):
            for w in v:
                adres = (w.get("url") if isinstance(w, dict) else w) if w else None
                if isinstance(adres, str) and adres.startswith("http"):
                    return adres
    return None


def _jest_wideo(it, video_url):
    typ = str(_pierwsze(it, ("type", "productType", "product_type", "__typename")) or "").lower()
    return bool(video_url) or it.get("isVideo") is True or any(t in typ for t in _TYPY_WIDEO)


def _na_rolke(it, domyslny_autor=""):
    """Item z Apify -> {shortcode, url, video_url, autor, opis, czas_s, polubienia, data} albo None (nie wideo / brak id)."""
    if not isinstance(it, dict):
        return None
    shortcode = _pierwsze(it, ("shortCode", "shortcode", "code", "id"))
    video_url = _video_url(it)
    if not shortcode or not _jest_wideo(it, video_url):
        return None
    autor = _pierwsze(it, ("ownerUsername", "owner_username")) or ((it.get("owner") or {}).get("username") if isinstance(it.get("owner"), dict) else None) or domyslny_autor
    strona = _pierwsze(it, ("url", "postUrl", "inputUrl")) or f"https://www.instagram.com/reel/{shortcode}/"
    czas = _pierwsze(it, ("videoDuration", "video_duration", "duration", "durationSeconds"))
    try:
        czas = round(float(czas), 2) if czas is not None else None
    except (TypeError, ValueError):
        czas = None
    return {
        "shortcode": str(shortcode),
        "url": str(strona),
        "video_url": video_url,
        "autor": str(autor or "").lstrip("@").lower(),
        "opis": str(_pierwsze(it, ("caption", "text", "title")) or ""),
        "czas_s": czas,
        "polubienia": _liczba(_pierwsze(it, ("likesCount", "likes", "like_count"))),
        "data": str(_pierwsze(it, ("timestamp", "takenAt", "taken_at", "takenAtTimestamp")) or ""),
    }


def rolki_z_profili(handles, na_profil=5, timeout=300):
    """Najnowsze rolki z publicznych profili (jeden run Apify dla wszystkich). Zwraca liste rolek:
    {shortcode, url, video_url, autor, opis, czas_s, polubienia, data}. Puste profile / braki pol pomija.
    Bez klucza -> BrakKlucza; blad Apify -> BladDostawcy."""
    handles = [_handle(h) for h in (handles or [])]
    handles = [h for h in dict.fromkeys(handles) if h]      # bez duplikatow, kolejnosc zachowana
    if not handles:
        raise BladDostawcy("Instagram: brak profili do pobrania (wklej @ profile tworczyn, po jednym w linii).")
    na_profil = max(1, min(50, int(na_profil or 5)))
    wejscie = {
        "directUrls": [_url_profilu(h) for h in handles],
        "resultsType": "posts",         # posty profilu (reele tez) - newest first
        "resultsLimit": na_profil,      # ile na profil
        "addParentData": False,
        "searchLimit": 1,
    }
    itemy = _wywolaj_actor(ACTOR_ROLKI, wejscie, timeout=timeout)
    rolki = []
    for it in itemy if isinstance(itemy, list) else []:
        # item bledu Apify (np. profil prywatny/nie istnieje) ma pole error - pomijamy, nie wywalamy calosci
        if isinstance(it, dict) and (it.get("error") or it.get("errorDescription")):
            continue
        r = _na_rolke(it)
        if r and r["video_url"]:
            rolki.append(r)
    # najnowsze pierwsze (po dacie, gdy jest)
    rolki.sort(key=lambda r: str(r.get("data") or ""), reverse=True)
    return rolki


def obserwowani(handle, limit=50):
    """Lista @ profili, ktore dane konto obserwuje. Na IG widoczna TYLKO po zalogowaniu, a logowania celowo NIE robimy
    (ban + Mullvad). Zostaje haczyk na dedykowany actor (ACTOR_OBSERWOWANI), ale domyslnie uczciwie mowimy, ze trzeba recznie."""
    h = _handle(handle)
    if not h:
        raise BladDostawcy("Instagram: podaj @ konto, z ktorego mam odczytac obserwowanych.")
    if not ACTOR_OBSERWOWANI:
        raise BladDostawcy(f"Instagram: lista obserwowanych @{h} jest ukryta - IG pokazuje ja tylko po zalogowaniu, "
                           f"a konta nie ruszamy. Wklej profile tworczyn recznie (po jednym w linii).")
    itemy = _wywolaj_actor(ACTOR_OBSERWOWANI, {"username": h, "resultsLimit": int(limit)}, timeout=120)
    konta = []
    for it in itemy if isinstance(itemy, list) else []:
        u = _handle(_pierwsze(it, ("username", "ownerUsername", "handle", "profileUrl", "url")) or "")
        if u and u not in konta:
            konta.append(u)
    if not konta:
        raise BladDostawcy(f"Instagram: nie odczytalem obserwowanych @{h} (lista moze byc ukryta) - "
                           f"wklej profile tworczyn recznie.")
    return konta[:limit]


# ---------------- pobieranie pliku ----------------

def _sprzataj(sciezka):
    try:
        if sciezka and os.path.isfile(sciezka):
            os.remove(sciezka)
    except OSError:
        pass


def pobierz(video_url, cel, timeout=120):
    """Sciaga filmik z CDN Instagrama do `cel`. UWAGA: scontent/fbcdn moze blokowac Mullvad z tej maszyny - wtedy
    rzucamy jasny wyjatek i NIE zostawiamy polpliku (sciagamy do <cel>.part, dopiero potem os.replace)."""
    if not video_url or not str(video_url).startswith(("http://", "https://")):
        raise BladDostawcy("Instagram: brak adresu CDN filmiku do pobrania.")
    cel = os.path.abspath(cel)
    os.makedirs(os.path.dirname(cel), exist_ok=True)
    tmp = cel + ".part"
    _sprzataj(tmp)
    try:
        http.pobierz(video_url, tmp, naglowki={"User-Agent": PRZEGLADARKA_UA}, timeout=timeout)
    except (urllib.error.HTTPError, urllib.error.URLError, http.BladHTTP, TimeoutError, ConnectionError, OSError) as e:
        _sprzataj(tmp)
        raise BladDostawcy("Instagram: nie moge pobrac pliku z CDN IG (moze blokowac VPN) - ustaw w .env/ustawieniach "
                           "pobieranie przez Apify. (" + _krotko(e) + ")")
    if not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
        _sprzataj(tmp)
        raise BladDostawcy("Instagram: CDN IG zwrocil pusty plik - nie zapisuje rolki.")
    os.replace(tmp, cel)
    return cel


def pobierz_przez_apify(rolka, cel, timeout=300):
    """HACZYK (domyslnie wylaczony - autopilot_rolki_ig.pobieranie_przez_apify): gdy CDN IG blokuje Mullvada, sprobuj
    pobrac plik przez Apify (actor re-hostujacy wideo albo oddajacy swiezy, dzialajacy adres). NIESPRAWDZONE na zywo -
    user wlacza to swiadomie. Uruchamia ACTOR_POBIERANIE z adresem rolki, szuka w wyniku adresu mp4, potem sciaga go
    zwyklym pobierz(). Rzuca BladDostawcy, gdy actor nie zwroci adresu (nie udajemy, ze dziala)."""
    url = str((rolka or {}).get("url") or (rolka or {}).get("video_url") or "").strip()
    if not url:
        raise BladDostawcy("Instagram: nie wiem, co pobrac przez Apify - brak adresu rolki.")
    itemy = _wywolaj_actor(ACTOR_POBIERANIE, {"directUrls": [url], "resultsType": "posts", "resultsLimit": 1}, timeout=timeout)
    for it in itemy if isinstance(itemy, list) else []:
        adres = _video_url(it) if isinstance(it, dict) else None
        if adres:
            return pobierz(adres, cel, timeout=timeout)
    raise BladDostawcy("Instagram: pobieranie przez Apify nie zwrocilo adresu pliku (actor ACTOR_POBIERANIE niesprawdzony "
                       "na zywo - sprawdz jego ustawienie).")
