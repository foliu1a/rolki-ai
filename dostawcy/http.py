# -*- coding: utf-8 -*-
"""Minimalny klient HTTP na stdlib (urllib) - JSON, multipart, pobieranie. Bez requests, zeby instaluj.bat
nie musial nic doinstalowywac. Powtarza 3x przy bledach sieci i 5xx."""
import json
import mimetypes
import os
import shutil
import time
import urllib.error
import urllib.request
import uuid

UA = "rolki-ai/2.0"
POWTORKI = 3


class BladHTTP(Exception):
    def __init__(self, status, tekst, url=""):
        super().__init__(f"HTTP {status} {url}: {tekst[:500]}")
        self.status = status
        self.tekst = tekst
        self.url = url


def _parsuj(dane_bajty, naglowki):
    tekst = dane_bajty.decode("utf-8", errors="replace") if dane_bajty else ""
    typ = (naglowki.get("Content-Type") or "") if naglowki else ""
    if "json" in typ or tekst[:1] in ("{", "["):
        try:
            return json.loads(tekst) if tekst.strip() else None
        except json.JSONDecodeError:
            pass
    return tekst


def zapytanie(metoda, url, dane=None, naglowki=None, timeout=60, surowe_cialo=None, typ_ciala=None, powtorki=POWTORKI):
    """JSON in / JSON out. `dane` (dict/list) idzie jako JSON; `surowe_cialo` (bytes) jak jest.
    Zwraca sparsowany JSON (albo tekst). Przy 4xx/5xx rzuca BladHTTP (5xx i bledy sieci powtarzane `powtorki` razy)."""
    cialo = None
    naglowki_req = {"User-Agent": UA, "Accept": "application/json"}
    naglowki_req.update(naglowki or {})
    if surowe_cialo is not None:
        cialo = surowe_cialo
        if typ_ciala:
            naglowki_req["Content-Type"] = typ_ciala
    elif dane is not None:
        cialo = json.dumps(dane).encode("utf-8")
        naglowki_req["Content-Type"] = "application/json"
    ostatni = None
    powtorki = max(1, int(powtorki or 1))
    for proba in range(1, powtorki + 1):
        req = urllib.request.Request(url, data=cialo, method=metoda.upper(), headers=naglowki_req)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as odp:
                return _parsuj(odp.read(), odp.headers)
        except urllib.error.HTTPError as e:
            tekst = e.read().decode("utf-8", errors="replace") if e.fp else ""
            ostatni = BladHTTP(e.code, tekst, url)
            if e.code < 500 and e.code != 429:
                raise ostatni
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            ostatni = BladHTTP(0, f"blad sieci: {e}", url)
        if proba < powtorki:
            time.sleep(2 ** (proba - 1))
    raise ostatni


def zapytanie_bajty(metoda, url, dane=None, naglowki=None, timeout=120, powtorki=2):
    """Jak zapytanie(), ale zwraca SUROWE bajty odpowiedzi (np. mp3 z ElevenLabs TTS) i jej Content-Type: (bajty, typ).
    `dane` idzie jako JSON. 4xx (poza 429) od razu BladHTTP; 5xx, 429 i bledy sieci - powtorki."""
    naglowki_req = {"User-Agent": UA}
    naglowki_req.update(naglowki or {})
    cialo = None
    if dane is not None:
        cialo = json.dumps(dane).encode("utf-8")
        naglowki_req["Content-Type"] = "application/json"
    ostatni = None
    powtorki = max(1, int(powtorki or 1))
    for proba in range(1, powtorki + 1):
        req = urllib.request.Request(url, data=cialo, method=metoda.upper(), headers=naglowki_req)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as odp:
                return odp.read(), (odp.headers.get("Content-Type") or "")
        except urllib.error.HTTPError as e:
            tekst = e.read().decode("utf-8", errors="replace") if e.fp else ""
            ostatni = BladHTTP(e.code, tekst, url)
            if e.code < 500 and e.code != 429:
                raise ostatni
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            ostatni = BladHTTP(0, f"blad sieci: {e}", url)
        if proba < powtorki:
            time.sleep(2 ** (proba - 1))
    raise ostatni


def multipart(url, pola=None, pliki=None, naglowki=None, timeout=900):
    """multipart/form-data: `pola` = {nazwa: tekst}, `pliki` = {nazwa: sciezka}."""
    granica = "----rolkiai" + uuid.uuid4().hex
    czesci = []
    for k, v in (pola or {}).items():
        czesci.append(f"--{granica}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
    for k, sciezka in (pliki or {}).items():
        nazwa = os.path.basename(sciezka)
        typ = mimetypes.guess_type(nazwa)[0] or "application/octet-stream"
        with open(sciezka, "rb") as f:
            zawartosc = f.read()
        czesci.append(
            f"--{granica}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{nazwa}\"\r\n"
            f"Content-Type: {typ}\r\n\r\n".encode("utf-8") + zawartosc + b"\r\n")
    czesci.append(f"--{granica}--\r\n".encode("utf-8"))
    return zapytanie("POST", url, naglowki=naglowki, timeout=timeout, surowe_cialo=b"".join(czesci),
                     typ_ciala=f"multipart/form-data; boundary={granica}")


def wyslij_plik(url, sciezka, naglowki=None, metoda="PUT", timeout=900):
    """Surowy upload (np. na podpisany URL S3/GCS). Naglowki z biletu ida 1:1 - Content-Type z biletu NIE jest nadpisywany
    zgadywanym typem pliku (jest czescia podpisu; inny = 403). Zgadujemy go tylko, gdy bilet go nie podal."""
    naglowki = dict(naglowki or {})
    typ = None
    if not any(k.lower() == "content-type" for k in naglowki):
        typ = mimetypes.guess_type(sciezka)[0] or "application/octet-stream"
    with open(sciezka, "rb") as f:
        zawartosc = f.read()
    return zapytanie(metoda, url, naglowki=naglowki, timeout=timeout, surowe_cialo=zawartosc, typ_ciala=typ)


def pobierz(url, sciezka, naglowki=None, timeout=600):
    os.makedirs(os.path.dirname(os.path.abspath(sciezka)), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(naglowki or {})})
    with urllib.request.urlopen(req, timeout=timeout) as odp, open(sciezka, "wb") as f:
        shutil.copyfileobj(odp, f)
    return sciezka
