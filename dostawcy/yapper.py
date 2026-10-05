# -*- coding: utf-8 -*-
"""Dostawca: yapper.so (Wan 3.0 / Wan 3.0 Prime, Seedance, Kling... przez Public API).

API (docs.yapper.so, openapi: https://yapper.so/api/v1/openapi.json): https://yapper.so/api/v1, `Authorization: Bearer <klucz>`.
  GET  /credits                      -> {"availableCredits": n, ...}
  GET  /models                       -> [{id, type, capabilities{maxPromptLength, referenceVideos{maxCombinedDurationSeconds}...},
                                          pricing, schemaUrl}]
  GET  /models/{id}/schema.json      -> JSON Schema pola `input` (additionalProperties: false - nadmiarowe pola = invalid_request)
  POST /processes                    -> {"type": "video-generation", "model", "input", "metadata", "dryRun"} + naglowek Idempotency-Key
                                        dryRun -> DryRunEstimate {creditsEstimated, canStart, blockedBy, credits{available}}
                                        bez dryRun -> Process {id, status, creditsUsed, refunded, outputs[].url, error}
  GET  /processes/{id}               -> Process (status queued|processing|completed|failed)
  POST /assets/uploads {type, mimeType, name} -> bilet {assetId, uploadUrl, method PUT, headers{...}, completeUrl}:
                                        PUT bajtow na uploadUrl z naglowkami biletu 1:1, potem POST completeUrl -> Asset {id}. 0 kredytow.

Rolki: zlec() (POST /processes ze STALYM Idempotency-Key rolki-{slug}-{id}-{model}-{proba}: powtorka tego samego zlecenia
oddaje ten sam proces, bez drugiej oplaty) -> fabryka zapisuje id -> sprawdz() az do konca. Koszt procesu = creditsUsed,
a gdy refunded (nieudany = zwrot automatyczny) - 0. Cialo zapytania budujemy per model ze schematu (np. Wan nie ma generateAudio).
Klucz: panel Konta (klucze.json) albo zmienna YAPPER_API_KEY. Wymaga platnego planu yapper.
"""
import json
import os
import re
import time
from urllib.parse import urlparse

import baza
import dostawcy
import sekrety
from dostawcy import BladDostawcy, BrakKlucza
from dostawcy import http

NAZWA = "yapper"
JEDNOSTKA = "kr"
IDEMPOTENTNY = True      # ten sam Idempotency-Key + to samo cialo = ten sam proces (bez drugiej oplaty)
BAZA_URL = "https://yapper.so/api/v1"
HOST = "yapper.so"
ODSTEP_ODPYTYWANIA = 10
CACHE_MODELI_S = 3600
TYPY_PLIKOW = {"image": baza.ROZSZERZENIA_OBRAZU, "video": (".mp4", ".mov", ".webm", ".m4v"), "audio": baza.ROZSZERZENIA_AUDIO}
# mimeType z enum w POST /assets/uploads (m4v -> mp4: yapper nie zna video/x-m4v)
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
        ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
        ".mp3": "audio/mpeg", ".wav": "audio/wav"}
STATUSY_W_TOKU = ("", "queued", "processing", "pending", "running")

# Gdy GET /models albo schemat nie odpowiada: znane zasady modeli Wan (z /models i schema.json, 2026-10-04).
_POLA_WAN = ("prompt", "aspectRatio", "resolution", "videoLength", "startingFrameImageUrl", "endingFrameImageUrl", "durationMode",
             "referenceImages", "referenceVideos", "referenceAudios", "disableAutoRetries", "outputName")
ZNANE_MODELE = {
    m: {"pola": _POLA_WAN, "max_prompt": 5000, "max_obrazow": 10, "max_wideo_s": 15, "max_wideo": 5,
        "aspect": ("16:9", "4:3", "1:1", "3:4", "9:16"), "rozdzielczosci": (480, 720, 1080), "dlugosci": tuple(range(2, 31)),
        "duration_mode": ("fixed", "auto")}
    for m in ("wan-3.0", "wan-3.0-prime")
}
_WZORZEC_HIGGSFIELD = re.compile(r"@\[Image\s*\d+\]\(image_\d+\)|@Image\s*\d+", re.I)

_cache = {"modele": None, "czas": 0.0, "schematy": {}}


def wyczysc_cache():
    """Zapomina liste modeli i schematy (testy, zmiana klucza)."""
    _cache.update(modele=None, czas=0.0, schematy={})


def _naglowki(idempotency=None):
    klucz = sekrety.klucz("yapper")
    if not klucz:
        raise BrakKlucza("Brak klucza API yapper.so - wpisz go w panelu (Konta) albo ustaw YAPPER_API_KEY.")
    n = {"Authorization": f"Bearer {klucz}"}
    if idempotency:
        n["Idempotency-Key"] = idempotency
    return n


def _url(sciezka_lub_url):
    """'/processes' -> https://yapper.so/api/v1/processes; '/api/v1/x' -> https://yapper.so/api/v1/x; pelny adres https://yapper.so/...
    bez zmian. Pelny adres na INNY host -> BladDostawcy (klucz API idzie tylko do yapper.so)."""
    s = str(sciezka_lub_url or "")
    if s.startswith(("http://", "https://")):
        host = (urlparse(s).hostname or "").lower()
        if host != HOST and not host.endswith("." + HOST):
            raise BladDostawcy(f"yapper: adres spoza yapper.so ({host}) - nie wysylam tam klucza API")
        return s
    if s.startswith("/api/"):
        return "https://" + HOST + s
    return BAZA_URL + (s if s.startswith("/") else "/" + s)


def _wywolaj(metoda, sciezka, dane=None, timeout=120, idempotency=None, powtorki=http.POWTORKI):
    try:
        return http.zapytanie(metoda, _url(sciezka), dane=dane, naglowki=_naglowki(idempotency), timeout=timeout,
                              powtorki=powtorki)
    except http.BladHTTP as e:
        raise BladYappera(_opis_bledu(e), status=e.status, kod=_kod_bledu(e))


class BladYappera(BladDostawcy):
    def __init__(self, tekst, status=None, kod=""):
        super().__init__(tekst)
        self.status = status
        self.kod = kod


def _kod_bledu(e):
    try:
        d = json.loads(e.tekst)
        err = d.get("error") if isinstance(d, dict) else None
        return (err.get("code") or "") if isinstance(err, dict) else ""
    except (ValueError, AttributeError):
        return ""


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
    dane = _wywolaj("GET", "/credits", timeout=20, powtorki=1)
    if isinstance(dane, dict):
        for k in ("availableCredits", "available", "credits", "balance"):
            if isinstance(dane.get(k), (int, float)) and not isinstance(dane.get(k), bool):
                return int(dane[k])
    raise BladDostawcy(f"GET /credits bez pola availableCredits: {str(dane)[:200]}")


def modele():
    if _cache["modele"] is not None and time.time() - _cache["czas"] < CACHE_MODELI_S:
        return _cache["modele"]
    dane = _wywolaj("GET", "/models", timeout=20, powtorki=1)
    lista = []
    if isinstance(dane, dict):
        for k in ("models", "items", "data"):
            if isinstance(dane.get(k), list):
                lista = dane[k]
                break
    elif isinstance(dane, list):
        lista = dane
    _cache.update(modele=lista, czas=time.time())
    return lista


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


def _schemat(model):
    """JSON Schema `input` modelu (GET /models/{id}/schema.json), z cache. None, gdy nie da sie pobrac."""
    if model in _cache["schematy"]:
        return _cache["schematy"][model]
    try:
        dane = _wywolaj("GET", f"/models/{model}/schema.json", timeout=20, powtorki=1)
    except BrakKlucza:
        raise
    except BladDostawcy:
        dane = None
    dane = dane if isinstance(dane, dict) and isinstance(dane.get("properties"), dict) else None
    _cache["schematy"][model] = dane
    return dane


def zasady_modelu(model):
    """Co model przyjmuje: {"pola", "max_prompt", "max_obrazow", "max_wideo_s", "max_wideo", "aspect", "rozdzielczosci",
    "dlugosci", "duration_mode", "aspect_const", "schemat"} - z GET /models + schema.json, a gdy API milczy - ZNANE_MODELE (Wan).
    Pola, ktorych nie wiadomo, maja None (= nie pilnujemy)."""
    znane = dict(ZNANE_MODELE.get(model) or {})
    z = {"pola": znane.get("pola"), "max_prompt": znane.get("max_prompt"), "max_obrazow": znane.get("max_obrazow"),
         "max_wideo_s": znane.get("max_wideo_s"), "max_wideo": znane.get("max_wideo"), "aspect": znane.get("aspect"),
         "rozdzielczosci": znane.get("rozdzielczosci"), "dlugosci": znane.get("dlugosci"),
         "duration_mode": znane.get("duration_mode"), "aspect_const": None, "schemat": False}
    try:
        info = next((m for m in modele() if isinstance(m, dict) and m.get("id") == model), None)
    except BrakKlucza:
        raise
    except BladDostawcy:
        info = None
    if info:
        kap = info.get("capabilities") or {}
        if isinstance(kap.get("maxPromptLength"), (int, float)):
            z["max_prompt"] = int(kap["maxPromptLength"])
        if isinstance(kap.get("maxReferenceImages"), (int, float)):
            z["max_obrazow"] = int(kap["maxReferenceImages"])
        rv = kap.get("referenceVideos") if isinstance(kap.get("referenceVideos"), dict) else {}
        if isinstance(rv.get("maxCombinedDurationSeconds"), (int, float)):
            z["max_wideo_s"] = float(rv["maxCombinedDurationSeconds"])
        if isinstance(rv.get("maxCount"), (int, float)):
            z["max_wideo"] = int(rv["maxCount"])
        for klucz, pole in (("aspect", "aspectRatios"), ("rozdzielczosci", "resolutions"), ("dlugosci", "videoLengths")):
            if isinstance(kap.get(pole), list) and kap[pole]:
                z[klucz] = tuple(kap[pole])
    sch = _schemat(model)
    if sch:
        props = sch["properties"]
        z["pola"] = tuple(props)
        z["schemat"] = True
        ar = props.get("aspectRatio") or {}
        if "const" in ar:
            z["aspect_const"] = ar["const"]
        elif isinstance(ar.get("enum"), list):
            z["aspect"] = tuple(ar["enum"])
        dm = props.get("durationMode") or {}
        if "const" in dm:
            z["duration_mode"] = (dm["const"],)
        elif isinstance(dm.get("enum"), list):
            z["duration_mode"] = tuple(dm["enum"])
        res = props.get("resolution") or {}
        if isinstance(res.get("enum"), list):
            z["rozdzielczosci"] = tuple(res["enum"])
        vl = props.get("videoLength") or {}
        if isinstance(vl.get("enum"), list):
            z["dlugosci"] = tuple(vl["enum"])
    return z


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
    """Wgrywa lokalny plik do biblioteki yapper (bilet -> PUT -> complete; 0 kredytow). Zwraca assetId (cache per rozmiar+mtime).
    Naglowki z biletu (Content-Type, x-goog-content-length-range) ida na PUT dokladnie tak, jak przyszly - sa czescia podpisu."""
    z_cache = _z_cache(slug, sciezka) if slug else None
    if z_cache:
        return z_cache
    typ = _typ_pliku(sciezka)
    nazwa = os.path.basename(sciezka)
    mime = MIME.get(os.path.splitext(nazwa)[1].lower())
    if not mime:
        raise BladDostawcy(f"yapper: format {os.path.splitext(nazwa)[1]} nie jest przyjmowany (jpg/png/webp, mp4/mov/webm, mp3/wav)")
    bilet = _wywolaj("POST", "/assets/uploads", {"type": typ, "mimeType": mime, "name": nazwa})
    if not isinstance(bilet, dict):
        raise BladDostawcy(f"yapper: POST /assets/uploads zwrocil cos dziwnego: {str(bilet)[:200]}")
    upload_url = bilet.get("uploadUrl")
    if not upload_url:
        raise BladDostawcy(f"yapper: bilet uploadu bez uploadUrl: {json.dumps(bilet)[:300]}")
    naglowki = {str(k): str(v) for k, v in bilet["headers"].items()} if isinstance(bilet.get("headers"), dict) else {}
    try:
        http.wyslij_plik(upload_url, sciezka, naglowki=naglowki, metoda=str(bilet.get("method") or "PUT"))
    except http.BladHTTP as e:
        raise BladDostawcy(f"yapper: upload {nazwa} nie wyszedl: {e}")
    aid = _id_z(bilet)
    complete = bilet.get("completeUrl") or (f"/assets/uploads/{aid}/complete" if aid else None)
    if complete:
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


def prompt_dla(z):
    """Prompt, ktory pojdzie do yappera: yapper.prompt (dla Wan - prompty/wan.txt persony), a gdy pusty - prompt rolki."""
    y = z.get("yapper") or {}
    return ((y.get("prompt") or "").strip() or (z.get("prompt") or "").strip())


def sprawdz_prompt(prompt, zasady):
    """Lista problemow promptu dla modelu yapper (pusta = ok)."""
    problemy = []
    if not prompt:
        problemy.append("brak promptu (Wan: plik prompty/wan.txt persony albo yapper.prompt)")
    if prompt and _WZORZEC_HIGGSFIELD.search(prompt):
        problemy.append("prompt ma skladnie @[Image N](image_N) z Higgsfielda - yapper jej nie zna (pisz 'the reference photos')")
    if prompt and zasady.get("max_prompt") and len(prompt) > zasady["max_prompt"]:
        problemy.append(f"prompt ma {len(prompt)} znakow, a model przyjmuje max {zasady['max_prompt']}")
    return problemy


def _cialo(z, uploady=True):
    """Zlecenie generyczne -> body POST /processes, zbudowane per model wg GET /models + schema.json:
    tylko pola, ktore model zna (Wan: bez generateAudio), prompt bez @[Image] i w limicie znakow, filmik referencyjny w limicie
    sekund, dlugosc = dlugosc klipu (durationMode auto), rozdzielczosc rolki (z["resolution"]), proporcje z ustawien albo 'auto',
    gdy model zna tylko 'auto' (seedance-2.5-edit, genjutsu). uploady=False: zamiast assetId sciezki (podglad)."""
    y = z.get("yapper") or {}
    model = (y.get("model") or "").strip()
    if not model:
        raise BladDostawcy("yapper: nie wybrano modelu (ustawienia modelki -> yapper.model, np. wan-3.0)")
    zas = zasady_modelu(model)
    slug = z.get("slug")
    prompt = prompt_dla(z)
    problemy = sprawdz_prompt(prompt, zas)
    if problemy:
        raise BladDostawcy(f"yapper {model}: " + "; ".join(problemy))
    pola = set(zas["pola"]) if zas.get("pola") else None

    def wolno(pole):
        return pola is None or pole in pola

    wejscie = {"prompt": prompt}
    if zas.get("aspect_const") is not None:
        wejscie["aspectRatio"] = zas["aspect_const"]
    elif z.get("aspect_ratio") and wolno("aspectRatio"):
        if not zas.get("aspect") or z["aspect_ratio"] in zas["aspect"]:
            wejscie["aspectRatio"] = z["aspect_ratio"]
    if wolno("resolution"):
        wys = _wysokosc(z.get("resolution") or y.get("resolution"))
        dozwolone = zas.get("rozdzielczosci")
        if dozwolone and wys not in dozwolone:
            nizsze = [r for r in dozwolone if isinstance(r, (int, float)) and r <= wys]
            wys = int(max(nizsze)) if nizsze else int(min(dozwolone))
        wejscie["resolution"] = wys
    wideo = z.get("video")
    tryby = zas.get("duration_mode") or ()
    if wideo and "auto" in tryby and wolno("durationMode"):
        wejscie["durationMode"] = "auto"           # dlugosc rolki = dlugosc klipu referencyjnego
        czas = z.get("video_czas")
        if czas and wolno("videoLength"):
            # bez videoLength yapper wycenia "auto" jak 5 s, a placi sie za cala dlugosc (sprawdzone 2026-10-06)
            dlugosc = max(1, int(round(float(czas))))
            if zas.get("dlugosci"):
                dlugosc = max(min(zas["dlugosci"]), min(max(zas["dlugosci"]), dlugosc))
            wejscie["videoLength"] = dlugosc
    elif wolno("videoLength") and not model.endswith("-edit"):
        dlugosc = z.get("duration") or y.get("duration")
        if dlugosc:
            dlugosc = int(round(float(dlugosc)))
            if zas.get("dlugosci"):
                dlugosc = max(min(zas["dlugosci"]), min(max(zas["dlugosci"]), dlugosc))
            wejscie["videoLength"] = dlugosc
    obrazy = [o for o in (z.get("images") or []) if o]
    if zas.get("max_obrazow") and len(obrazy) > zas["max_obrazow"]:
        obrazy = obrazy[:zas["max_obrazow"]]
    if obrazy and wolno("referenceImages"):
        wejscie["referenceImages"] = [_referencja(slug, o) if uploady else {"file": o} for o in obrazy]
    if wideo and wolno("referenceVideos"):
        czas = z.get("video_czas")
        if czas and zas.get("max_wideo_s") and float(czas) > float(zas["max_wideo_s"]) + 0.05:
            raise BladDostawcy(f"yapper {model}: filmik ma {float(czas):.1f} s, a model przyjmuje max {zas['max_wideo_s']:g} s "
                               f"filmiku referencyjnego (przytnij go albo ustaw krotsza dlugosc rolki)")
        wejscie["referenceVideos"] = [_referencja(slug, wideo) if uploady else {"file": wideo}]
    if z.get("generate_audio") is not None and wolno("generateAudio"):
        wejscie["generateAudio"] = bool(z["generate_audio"])
    for k, v in (y.get("parametry") or {}).items():
        if wolno(k):
            wejscie[k] = v
    return {"type": "video-generation", "model": model, "input": wejscie}


def wycena(z):
    """Darmowa wycena (dryRun; wgrywa referencje - 0 kr). Zwraca {"kr", "can_start", "blocked_by", "dostepne", "surowe"}."""
    cialo = dict(_cialo(z), dryRun=True)
    dane = _wywolaj("POST", "/processes", cialo, timeout=180)
    if not isinstance(dane, dict):
        raise BladDostawcy(f"yapper: dryRun zwrocil cos dziwnego: {str(dane)[:200]}")
    kr = dane.get("creditsEstimated")
    kredyty = dane.get("credits") if isinstance(dane.get("credits"), dict) else {}
    return {"kr": int(round(kr)) if isinstance(kr, (int, float)) and not isinstance(kr, bool) else None,
            "can_start": dane.get("canStart"), "blocked_by": dane.get("blockedBy"),
            "dostepne": kredyty.get("available"), "surowe": dane}


def koszt(z):
    """Dokladny koszt bez generacji (dryRun -> creditsEstimated). Odmawia (BladDostawcy), gdy yapper mowi, ze tego nie wystartuje
    (canStart=false / blockedBy: limit zespolu, czlonka, portfel) albo nie podal ceny."""
    w = wycena(z)
    if w["blocked_by"] or w["can_start"] is False:
        powod = w["blocked_by"] or "canStart=false"
        dost = f", dostepne {w['dostepne']:g} kr" if isinstance(w.get("dostepne"), (int, float)) else ""
        raise BladDostawcy(f"yapper odmawia startu ({powod}{dost}) - wycena {w['kr']} kr. Sprawdz kredyty/limity na yapper.so.")
    if w["kr"] is None:
        raise BladDostawcy(f"yapper: dryRun bez creditsEstimated: {json.dumps(w['surowe'])[:300]}")
    return w["kr"]


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


def _blad(proc):
    err = (proc or {}).get("error")
    if isinstance(err, dict):
        return f"{err.get('code') or ''}: {err.get('message') or ''}".strip(": ")
    return err if isinstance(err, str) else ""


def _normalizuj(proc, pid=None):
    proc = proc if isinstance(proc, dict) else {}
    return {"job_id": str(proc.get("id") or proc.get("processId") or pid or ""), "status": _status(proc), "urls": _urls(proc),
            "blad": _blad(proc), "surowe": proc, "kredyty": koszt_joba({"surowe": proc, "status": _status(proc)})}


def koszt_joba(wynik, wycena=None):
    """Ile naprawde zeszlo za proces: creditsUsed minus zwrot (refunded=true -> 0; nieudany proces yapper zwraca sam).
    wycena = gdy proces nie podal creditsUsed (zakonczony) - bierzemy wycene z dryRun."""
    proc = wynik.get("surowe") if isinstance(wynik.get("surowe"), dict) else {}
    status = (wynik.get("status") or _status(proc)).lower()
    if status in ("failed", "cancelled", "canceled", "rejected"):
        return 0
    uzyte = proc.get("creditsUsed")
    if not isinstance(uzyte, (int, float)) or isinstance(uzyte, bool):
        return int(wycena or 0) if status == "completed" else 0
    zwrot = proc.get("refunded")
    if zwrot is True:
        return 0
    if isinstance(zwrot, (int, float)) and not isinstance(zwrot, bool):
        return max(0, int(round(uzyte - zwrot)))
    return max(0, int(round(uzyte)))


def zlec(z, klucz=None, znacznik=None, log=None):
    """POST /processes BEZ czekania; Idempotency-Key = klucz (staly per pomysl/model/proba - powtorka zwraca ten sam proces,
    bez drugiej oplaty). Zwraca {"job_id", "status", "surowe"}. Konflikt klucza (ten sam klucz, inne cialo - np. nowy upload)
    -> szukamy procesu po metadanych zamiast wysylac drugi."""
    cialo = _cialo(z)
    if klucz:
        cialo["metadata"] = {"rolki_klucz": klucz[:200]}
    if znacznik:
        znacznik(wysylam=True)      # od tej chwili proces MOZE powstac (ten sam klucz przy powtorce = ten sam proces)
    try:
        proc = _wywolaj("POST", "/processes", cialo, timeout=180, idempotency=klucz)
    except BladYappera as e:
        if e.kod == "idempotency_conflict" and klucz:
            znaleziony = znajdz(cialo["model"], klucz=klucz)
            if znaleziony:
                return znaleziony
        raise
    wynik = _normalizuj(proc)
    if not wynik["job_id"]:
        raise BladDostawcy(f"yapper: POST /processes bez id: {json.dumps(proc)[:300]}")
    if wynik["status"] not in STATUSY_W_TOKU:
        wynik["gotowy"] = dict(wynik)
    return wynik


def sprawdz(job_id):
    """GET /processes/{id} (0 kr) -> {"job_id", "status", "urls", "blad", "surowe", "kredyty"}."""
    return _normalizuj(_wywolaj("GET", f"/processes/{job_id}", timeout=60), pid=job_id)


def koncowy(status):
    return status not in STATUSY_W_TOKU


def znajdz(model, klucz=None, od=None, **_):
    """Proces wyslany wczesniej z tym Idempotency-Key (metadata.rolki_klucz) - GET /processes?model=... Zwraca wynik albo None."""
    if not klucz:
        return None
    dane = _wywolaj("GET", f"/processes?model={model}&limit=50", timeout=60, powtorki=1)
    lista = dane.get("items") or dane.get("processes") or dane.get("data") if isinstance(dane, dict) else dane
    for proc in lista if isinstance(lista, list) else []:
        meta = (proc or {}).get("metadata") if isinstance(proc, dict) else None
        if isinstance(meta, dict) and meta.get("rolki_klucz") == klucz[:200]:
            return _normalizuj(proc)
    return None


def generuj(z, timeout="30m", log=None, klucz=None):
    """POST /processes + odpytywanie do konca (bez zapisu stanu - rolki ida przez fabryke: zlec + sprawdz)."""
    proc = zlec(z, klucz=klucz, log=log)
    pid = proc["job_id"]
    koniec = time.time() + dostawcy.sekundy(timeout)
    wynik = proc.get("gotowy") or proc
    while wynik["status"] in STATUSY_W_TOKU and time.time() < koniec:
        time.sleep(ODSTEP_ODPYTYWANIA)
        wynik = sprawdz(pid)
    if wynik["status"] in STATUSY_W_TOKU:
        raise BladDostawcy(f"yapper: job {pid} nie skonczyl sie w {timeout}")
    return wynik


def pobierz(url, sciezka):
    return http.pobierz(url, sciezka)


def udany(status):
    return status == "completed"


def nieudany(status):
    return status in ("failed", "cancelled", "canceled", "rejected")
