# -*- coding: utf-8 -*-
"""Dostawca: yapper.so (Wan 3.0 / Wan 3.0 Prime, Seedance, Kling... przez Public API).

API (docs.yapper.so): https://yapper.so/api/v1, naglowek `Authorization: Bearer <klucz>`.
  GET  /credits                      -> {"availableCredits": n, ...}
  GET  /models                       -> lista modeli (id, typ, pola, ceny)
  POST /processes                    -> {"type": "video-generation", "model": "wan-3.0", "input": {...}, "dryRun": bool}
                                        (Idempotency-Key w naglowku; dryRun = sam koszt, bez generacji)
  GET  /processes/{id}               -> status queued|processing|completed|failed, outputs[].url, creditsUsed
  POST /assets/uploads               -> bilet uploadu: PUT bajtow na uploadUrl, potem POST completeUrl -> assetId
  POST /assets/import {type,url}     -> import z publicznego URL

Klucz: panel Konta (zapis do klucze.json) albo zmienna YAPPER_API_KEY. Wymaga platnego planu yapper.
Pola `input` wg docs (video-generation): prompt, aspectRatio, resolution (wysokosc, np. 1080), videoLength (s),
referenceImages/referenceVideos/referenceAudios = [{assetId}|{url}], generateAudio, startingFrameImageUrl.

UWAGA: dokladny ksztalt biletu uploadu (POST /assets/uploads) i pole z kosztem przy dryRun nie byly dostepne
w dokumentacji tekstowej - kod szuka kilku nazw. Jak cos nie pasuje: `python fabryka.py modele --dostawca yapper --json`
i https://yapper.so/api/v1/openapi.json pokazuja prawdziwe schematy.
"""
import json
import mimetypes
import os
import time
import uuid

import baza
import dostawcy
import sekrety
from dostawcy import BladDostawcy, BrakKlucza
from dostawcy import http

NAZWA = "yapper"
JEDNOSTKA = "kr"
BAZA_URL = "https://yapper.so/api/v1"
ODSTEP_ODPYTYWANIA = 10
TYPY_PLIKOW = {"image": baza.ROZSZERZENIA_OBRAZU, "video": (".mp4", ".mov", ".webm", ".m4v"), "audio": baza.ROZSZERZENIA_AUDIO}


def _naglowki(idempotency=None):
    klucz = sekrety.klucz("yapper")
    if not klucz:
        raise BrakKlucza("Brak klucza API yapper.so - wpisz go w panelu (Konta) albo ustaw YAPPER_API_KEY.")
    n = {"Authorization": f"Bearer {klucz}"}
    if idempotency:
        n["Idempotency-Key"] = idempotency
    return n


def _wywolaj(metoda, sciezka, dane=None, timeout=120, idempotency=None):
    try:
        return http.zapytanie(metoda, BAZA_URL + sciezka, dane=dane, naglowki=_naglowki(idempotency), timeout=timeout)
    except http.BladHTTP as e:
        raise BladDostawcy(_opis_bledu(e))


def _opis_bledu(e):
    """{"error": {"code": "insufficient_credits", "message": "..."}} -> czytelny tekst."""
    try:
        d = json.loads(e.tekst)
        err = d.get("error") if isinstance(d, dict) else None
        if isinstance(err, dict):
            kod = err.get("code") or ""
            msg = err.get("message") or ""
            if kod == "insufficient_credits":
                msg = msg or "za malo kredytow na yapper.so"
            if kod == "missing_scope":
                msg = (msg or "") + " (klucz API nie ma uprawnien - zaznacz Read+Write przy tworzeniu klucza)"
            return f"yapper {e.status} {kod}: {msg}".strip()
        if isinstance(err, str):
            return f"yapper {e.status}: {err}"
    except (ValueError, AttributeError):
        pass
    if e.status == 401:
        return "yapper 401: zly klucz API (sprawdz w panelu Konta)"
    if e.status == 402:
        return "yapper 402: API wymaga aktywnego platnego planu yapper.so"
    return f"yapper {e.status}: {e.tekst[:300]}"


# ---------------- konto ----------------

def gotowy():
    if not sekrety.klucz("yapper"):
        return False, "brak klucza API yapper.so (panel -> Konta)"
    try:
        s = saldo()
    except BladDostawcy as e:
        return False, str(e)
    return True, f"{s} kr dostepnych"


def saldo():
    dane = _wywolaj("GET", "/credits")
    if isinstance(dane, dict):
        for k in ("availableCredits", "available", "credits", "balance"):
            if isinstance(dane.get(k), (int, float)):
                return int(dane[k])
    raise BladDostawcy(f"GET /credits bez pola availableCredits: {str(dane)[:200]}")


def modele():
    dane = _wywolaj("GET", "/models")
    if isinstance(dane, dict):
        for k in ("models", "items", "data"):
            if isinstance(dane.get(k), list):
                return dane[k]
    return dane if isinstance(dane, list) else []


def modele_wideo():
    """Tylko modele wideo: [{id, name, ...}]. Jak API nie podaje typu, zwraca wszystko."""
    wynik = []
    for m in modele():
        if not isinstance(m, dict):
            continue
        typ = str(m.get("processType") or m.get("type") or m.get("category") or "").lower()
        if not typ or "video" in typ:
            wynik.append(m)
    return wynik


# ---------------- uploady (assets) ----------------

def _plik_cache(slug):
    return os.path.join(baza.folder_modelki(slug), "uploady_yapper.json")


def _z_cache(slug, sciezka):
    cache = baza._wczytaj_json(_plik_cache(slug), {})
    wpis = cache.get(os.path.normcase(os.path.abspath(sciezka)))
    if not wpis or not os.path.isfile(sciezka):
        return None
    st = os.stat(sciezka)
    if wpis.get("size") == st.st_size and abs(wpis.get("mtime", 0) - st.st_mtime) < 1:
        return wpis.get("id")
    return None


def _do_cache(slug, sciezka, aid):
    cache = baza._wczytaj_json(_plik_cache(slug), {})
    st = os.stat(sciezka)
    cache[os.path.normcase(os.path.abspath(sciezka))] = {"id": aid, "size": st.st_size, "mtime": st.st_mtime,
                                                         "plik": os.path.basename(sciezka)}
    baza._zapisz_json(_plik_cache(slug), cache)


def _typ_pliku(sciezka):
    ext = os.path.splitext(sciezka)[1].lower()
    for typ, rozsz in TYPY_PLIKOW.items():
        if ext in rozsz:
            return typ
    raise BladDostawcy(f"yapper: nie wiem, jakiego typu jest plik {os.path.basename(sciezka)}")


def _id_z(dane):
    if not isinstance(dane, dict):
        return None
    for k in ("assetId", "id"):
        if isinstance(dane.get(k), str) and dane[k]:
            return dane[k]
    for k in ("asset", "data"):
        w = _id_z(dane.get(k))
        if w:
            return w
    return None


def wgraj(slug, sciezka):
    """Wgrywa lokalny plik do biblioteki yapper (bilet -> PUT -> complete). Zwraca assetId (cache per rozmiar+mtime)."""
    z_cache = _z_cache(slug, sciezka) if slug else None
    if z_cache:
        return z_cache
    typ = _typ_pliku(sciezka)
    nazwa = os.path.basename(sciezka)
    bilet = _wywolaj("POST", "/assets/uploads", {
        "type": typ, "name": nazwa,
        "mimeType": mimetypes.guess_type(nazwa)[0] or "application/octet-stream",
        "contentType": mimetypes.guess_type(nazwa)[0] or "application/octet-stream",
        "size": os.path.getsize(sciezka),
    })
    if not isinstance(bilet, dict):
        raise BladDostawcy(f"yapper: POST /assets/uploads zwrocil cos dziwnego: {str(bilet)[:200]}")
    upload_url = bilet.get("uploadUrl") or bilet.get("url")
    if not upload_url:
        raise BladDostawcy(f"yapper: bilet uploadu bez uploadUrl: {json.dumps(bilet)[:300]}")
    naglowki = bilet.get("headers") if isinstance(bilet.get("headers"), dict) else {}
    try:
        http.wyslij_plik(upload_url, sciezka, naglowki=naglowki, metoda=str(bilet.get("method") or "PUT"))
    except http.BladHTTP as e:
        raise BladDostawcy(f"yapper: upload {nazwa} nie wyszedl: {e}")
    complete = bilet.get("completeUrl")
    aid = _id_z(bilet)
    if complete:
        if complete.startswith("/"):
            complete = "https://yapper.so" + complete if complete.startswith("/api/") else BAZA_URL + complete
        wynik = _wywolaj("POST", complete, {})
        aid = _id_z(wynik) or aid
    if not aid:
        raise BladDostawcy(f"yapper: upload {nazwa} bez assetId w odpowiedzi: {json.dumps(bilet)[:300]}")
    if slug:
        _do_cache(slug, sciezka, aid)
    return aid


def _referencja(slug, plik_lub_url):
    if isinstance(plik_lub_url, str) and plik_lub_url.startswith("http"):
        return {"url": plik_lub_url}
    return {"assetId": wgraj(slug, plik_lub_url)}


# ---------------- zlecenie ----------------

def _wysokosc(rozdzielczosc):
    """'720p' -> 720, 1080 -> 1080."""
    if isinstance(rozdzielczosc, int):
        return rozdzielczosc
    cyfry = "".join(ch for ch in str(rozdzielczosc or "") if ch.isdigit())
    return int(cyfry) if cyfry else 720


def _cialo(z, uploady=True):
    """Zlecenie generyczne -> body POST /processes. uploady=False: zamiast assetId sciezki (podglad)."""
    y = z.get("yapper") or {}
    model = (y.get("model") or "").strip()
    if not model:
        raise BladDostawcy("yapper: nie wybrano modelu (ustawienia modelki -> yapper.model, np. wan-3.0)")
    slug = z.get("slug")
    prompt = (y.get("prompt") or "").strip() or z.get("prompt") or ""
    wejscie = {"prompt": prompt}
    if z.get("aspect_ratio"):
        wejscie["aspectRatio"] = z["aspect_ratio"]
    wejscie["resolution"] = _wysokosc(y.get("resolution") or z.get("resolution"))
    dlugosc = z.get("duration") or y.get("duration")
    if dlugosc and not model.endswith("-edit"):
        wejscie["videoLength"] = int(dlugosc)
    obrazy = [o for o in (z.get("images") or []) if o]
    if obrazy:
        wejscie["referenceImages"] = [_referencja(slug, o) if uploady else {"file": o} for o in obrazy]
    if z.get("video"):
        wejscie["referenceVideos"] = [_referencja(slug, z["video"]) if uploady else {"file": z["video"]}]
    if z.get("generate_audio") is not None:
        wejscie["generateAudio"] = bool(z["generate_audio"])
    wejscie.update(y.get("parametry") or {})
    return {"type": "video-generation", "model": model, "input": wejscie}


def _koszt_z(dane):
    if isinstance(dane, (int, float)) and not isinstance(dane, bool):
        return int(dane)
    if isinstance(dane, dict):
        for k in ("creditsUsed", "estimatedCredits", "creditCost", "credits", "cost", "estimatedCost", "price"):
            v = dane.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return int(round(v))
        for k in ("quote", "estimate", "dryRun", "data", "pricing"):
            w = _koszt_z(dane.get(k))
            if w is not None:
                return w
    return None


def koszt(z):
    """dryRun: dokladny koszt bez generacji (uploaduje referencje, zeby policzyc naprawde)."""
    cialo = dict(_cialo(z), dryRun=True)
    dane = _wywolaj("POST", "/processes", cialo, timeout=180)
    return _koszt_z(dane)


def podglad(z):
    return "POST " + BAZA_URL + "/processes " + json.dumps(_cialo(z, uploady=False), ensure_ascii=False)


def _status(proc):
    return str((proc or {}).get("status") or "").lower()


def _urls(proc):
    wynik = []
    for o in (proc or {}).get("outputs") or []:
        if isinstance(o, dict) and isinstance(o.get("url"), str):
            wynik.append(o["url"])
    return wynik


def generuj(z, timeout="30m", log=None):
    """POST /processes + odpytywanie do konca. Zwraca {"job_id","status","urls","blad","surowe"}."""
    cialo = _cialo(z)
    proc = _wywolaj("POST", "/processes", cialo, timeout=180, idempotency=f"rolki-{uuid.uuid4().hex}")
    pid = (proc or {}).get("id") or (proc or {}).get("processId")
    if not pid:
        raise BladDostawcy(f"yapper: POST /processes bez id: {json.dumps(proc)[:300]}")
    koniec = time.time() + dostawcy.sekundy(timeout)
    while _status(proc) in ("", "queued", "processing", "pending", "running") and time.time() < koniec:
        time.sleep(ODSTEP_ODPYTYWANIA)
        proc = _wywolaj("GET", f"/processes/{pid}")
    stan = _status(proc)
    if stan in ("queued", "processing", "pending", "running"):
        raise BladDostawcy(f"yapper: job {pid} nie skonczyl sie w {timeout}")
    blad = ""
    err = (proc or {}).get("error")
    if isinstance(err, dict):
        blad = f"{err.get('code') or ''}: {err.get('message') or ''}".strip(": ")
    elif isinstance(err, str):
        blad = err
    return {"job_id": str(pid), "status": stan, "urls": _urls(proc), "blad": blad, "surowe": proc,
            "kredyty": _koszt_z(proc)}


def pobierz(url, sciezka):
    return http.pobierz(url, sciezka)


def udany(status):
    return status == "completed"


def nieudany(status):
    return status in ("failed", "cancelled", "canceled", "rejected")
