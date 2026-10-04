# -*- coding: utf-8 -*-
"""Dostawca: Higgsfield (Seedance 2.5 Edit i inne modele) przez oficjalne CLI - higgsfield_cli.py.

Wszystko woluje `higgsfield_cli` przez atrybuty modulu (hf.koszt itd.), zeby testy mogly je podmienic.
Rolki: zlec() (generate create BEZ --wait) -> fabryka zapisuje job_id -> sprawdz() (generate get) az do konca;
po bledzie/restarcie odpytujemy TEN SAM job (znajdz() odnajduje go po wgranym filmiku, gdy id nie zdazylo sie zapisac)."""
import os
import re

import baza
import higgsfield_cli as hf
from dostawcy import BladDostawcy

NAZWA = "higgsfield"
JEDNOSTKA = "kr"
IDEMPOTENTNY = False     # CLI nie ma Idempotency-Key: przed ponownym wyslaniem fabryka sprawdza `generate list` (znajdz)


def gotowy():
    try:
        hf.sciezka_cli()
    except hf.HiggsfieldBlad as e:
        return False, str(e)
    try:
        hf.konto()
    except hf.NieZalogowany as e:
        return False, str(e)
    except hf.HiggsfieldBlad as e:
        return False, f"CLI odpowiada, ale account status nie dziala: {e}"
    return True, "zalogowany"


def saldo():
    try:
        return hf.kredyty()
    except hf.HiggsfieldBlad as e:
        raise BladDostawcy(str(e))


def _prompt_na_drut(prompt):
    """Issue higgsfield-ai/cli#94: prompt z pusta linia bywa ucinany na pierwszym akapicie.
    Sklejamy akapity w jeden ciag linii (tresc bez zmian, znika tylko pusta linia)."""
    return re.sub(r"\n[ \t]*\n+", "\n", (prompt or "").strip())


def przygotuj(z):
    """Zlecenie -> (model, params, media) dla CLI. Kolejnosc --image = numeracja @[Image N] w prompcie."""
    params = {
        "prompt": _prompt_na_drut(z.get("prompt")),
        "mode": z.get("mode"),
        "aspect_ratio": z.get("aspect_ratio"),
        "resolution": z.get("resolution"),
    }
    if z.get("duration"):
        # Seedance 2.5 przyjmuje 4-30 s; dluzsze zrodlo = utnij albo potnij przed wrzuceniem
        params["duration"] = max(4, min(30, int(z["duration"])))
    if z.get("generate_audio") is not None:
        params["generate_audio"] = bool(z["generate_audio"])
    if z.get("soul_id"):
        params["soul-id"] = z["soul_id"]
    params.update(z.get("parametry") or {})

    media = {}
    if z.get("video"):
        media["video"] = z["video"]
    obrazy = [o for o in (z.get("images") or []) if o]
    if obrazy:
        slug = z.get("slug")
        media["image"] = baza.media_do_cli(slug, obrazy) if slug else obrazy   # UUID z cache zamiast ponownego uploadu
    for rola in ("audio", "start_image", "end_image"):
        if z.get(rola):
            media[rola] = z[rola]
    return z.get("model") or "seedance_2_5", params, media


def koszt(z):
    model, params, media = przygotuj(z)
    try:
        return hf.koszt(model, params, media)
    except hf.HiggsfieldBlad as e:
        raise BladDostawcy(str(e))


def podglad(z):
    model, params, media = przygotuj(z)
    return hf.komenda_podglad(model, params, media, wait=False)


# ---------------- rolki: wyslij BEZ czekania, potem odpytuj ten sam job ----------------

def _normalizuj(job):
    """Obiekt joba z CLI -> {"job_id", "status", "urls", "blad", "surowe"} (bez doczytywania URL)."""
    job = job if isinstance(job, dict) else {"surowe": job}
    return {"job_id": hf.job_id_z(job), "status": hf.status_joba(job) or "", "urls": hf.wyniki_url(job),
            "blad": hf.blad_joba(job), "surowe": job}


def zlec(z, klucz=None, znacznik=None, log=None):
    """Wysyla rolke BEZ --wait i od razu zwraca {"job_id", "status", "surowe"} (+ "gotowy": pelny wynik, gdy CLI oddal juz
    koncowy job). Filmik zrodlowy jest najpierw wgrywany osobno (`upload create`), a jego id trafia do znacznik(wideo_id=...)
    PRZED wyslaniem - po przerwaniu (zamkniety panel) fabryka znajdzie job po tym id na `generate list` zamiast wysylac drugi.
    klucz: Higgsfield nie ma Idempotency-Key - ignorowany. Rzuca BladDostawcy, gdy wyslanie sie nie udalo.
    WSZYSTKIE lokalne pliki (filmik, zdjecia bez UUID w cache, audio) sa wgrywane PRZED znacznikiem 'wysylam': sam
    `generate create` jest wtedy szybki, a okno, w ktorym job moze powstac bez zapisanego id, mozliwie krotkie."""
    model, params, media = przygotuj(z)
    slug = z.get("slug")

    def wgraj(sciezka, cache=False):
        try:
            dane = hf.upload(sciezka)
        except hf.HiggsfieldBlad as e:
            raise BladDostawcy(f"wgranie {os.path.basename(str(sciezka))} nie wyszlo: {e}")
        if cache and slug:
            try:
                baza.zapisz_upload_id(slug, sciezka, dane["id"])     # referencje/stroje: nastepnym razem z cache
            except (OSError, ValueError):
                pass
        return dane["id"]

    wideo = media.get("video")
    wideo_id = None
    if wideo and os.path.isfile(str(wideo)):
        wideo_id = media["video"] = wgraj(wideo)        # swiezy upload per proba = unikalne id do odnalezienia joba
    elif wideo:
        wideo_id = str(wideo)
    if media.get("image"):
        media["image"] = [wgraj(o, cache=True) if os.path.isfile(str(o)) else o for o in media["image"]]
    for rola in ("audio", "start_image", "end_image"):
        if media.get(rola) and os.path.isfile(str(media[rola])):
            media[rola] = wgraj(media[rola])
    if znacznik:
        # od tej chwili job MOZE powstac (wszystko juz wgrane) - po przerwaniu szukamy go po wideo_id, zamiast wysylac drugi
        znacznik(wysylam=True, wideo_id=wideo_id)
    try:
        job = hf.generuj(model, params, media, wait=False)
    except hf.HiggsfieldBlad as e:
        raise BladDostawcy(str(e))
    wynik = _normalizuj(job)
    if not wynik["job_id"]:
        raise BladDostawcy(f"generate create nie zwrocil id joba: {str(job)[:300]}")
    if wynik["status"] in hf.STATUSY_OK and not wynik["urls"]:
        job, urls = hf.doczytaj_url(job)
        wynik = dict(_normalizuj(job), job_id=wynik["job_id"], urls=urls)
    if wynik["status"] in hf.STATUSY_OK or wynik["status"] in hf.STATUSY_BLAD:
        wynik["gotowy"] = dict(wynik)      # CLI oddal juz koncowy job (np. starsza wersja z --wait) - nie trzeba odpytywac
    return wynik


def sprawdz(job_id):
    """Jeden rzut oka na job (`generate get`, 0 kr) -> {"job_id", "status", "urls", "blad", "surowe"}.
    Job zakonczony bez result_url jest doczytywany kilka razy (backend dopisuje link chwile po zakonczeniu)."""
    try:
        job = hf.job(job_id)
    except hf.HiggsfieldBlad as e:
        raise BladDostawcy(str(e))
    wynik = _normalizuj(job)
    wynik["job_id"] = wynik["job_id"] or str(job_id)
    if not wynik["urls"] and hf.job_udany(job):
        job, urls = hf.doczytaj_url(job)
        wynik = dict(_normalizuj(job), job_id=wynik["job_id"], urls=urls)
    return wynik


def koncowy(status):
    return status in hf.STATUSY_OK or status in hf.STATUSY_BLAD


def koszt_joba(wynik, wycena=None):
    """Ile zjadl job: pole kosztu z joba (gdyby CLI je kiedys podawalo), inaczej wycena z `generate cost` - ale tylko za udany job
    (odrzucony/nieudany = kredyty wracaja = 0). NIE liczymy z roznicy salda: reczne generacje w apce nie zjadaja limitu fabryki."""
    if not udany(wynik.get("status") or ""):
        return 0
    job = wynik.get("surowe") if isinstance(wynik.get("surowe"), dict) else {}
    for k in ("credits_used", "credits_spent", "cost", "credits"):
        v = job.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
            return int(round(v))
    return int(wycena or 0)


def znajdz(model, wideo_id=None, prompt=None, od=None, pomin=(), **_):
    """Szuka na `generate list` joba wyslanego przez przerwane wysylanie: ten sam model i ten sam wgrany filmik (media
    role=video, data.id == wideo_id - id jest swiezy dla kazdej proby, wiec BEZ filtra czasu: zegar komputera i serwera
    moze sie rozjechac) albo - bez filmiku - ten sam prompt i utworzony nie wczesniej niz `od` - 2 min.
    Zwraca znormalizowany job albo None. Rzuca BladDostawcy, gdy listy nie da sie pobrac (wtedy NIE wolno wysylac ponownie)."""
    from datetime import datetime, timedelta, timezone
    try:
        lista = hf.joby("video", 50)
    except hf.HiggsfieldBlad as e:
        raise BladDostawcy(f"generate list: {e}")
    granica = None
    if od and not wideo_id:
        try:
            granica = datetime.fromisoformat(str(od).replace("Z", "+00:00")) - timedelta(minutes=2)
            if granica.tzinfo is None:
                granica = granica.replace(tzinfo=timezone.utc)
        except ValueError:
            granica = None
    drut = _prompt_na_drut(prompt) if prompt else None
    for job in lista if isinstance(lista, list) else []:
        if not isinstance(job, dict) or hf.job_id_z(job) in pomin:
            continue
        if model and job.get("job_type") and job.get("job_type") != model:
            continue
        if granica and job.get("created_at"):
            try:
                kiedy = datetime.fromisoformat(str(job["created_at"]).replace("Z", "+00:00"))
                if kiedy.tzinfo is None:
                    kiedy = kiedy.replace(tzinfo=timezone.utc)
                if kiedy < granica:
                    continue
            except ValueError:
                pass
        params = job.get("params") if isinstance(job.get("params"), dict) else {}
        media = params.get("medias") if isinstance(params.get("medias"), list) else []
        if wideo_id:
            ids = {str((m.get("data") or {}).get("id")) for m in media if isinstance(m, dict) and m.get("role") == "video"}
            if str(wideo_id) in ids:
                return _normalizuj(job)
        elif drut is not None and (params.get("prompt") or "").strip() == drut.strip():
            return _normalizuj(job)
    return None


def generuj(z, timeout="30m", log=None):
    """Jedna proba generacji z czekaniem (CLI --wait) - zdjecia, tani podglad, lipsync. Rolki ida przez zlec()+sprawdz()."""
    model, params, media = przygotuj(z)
    try:
        job = hf.generuj(model, params, media, wait=True, wait_timeout=timeout)
    except hf.HiggsfieldBlad as e:
        raise BladDostawcy(str(e))
    urls = hf.wyniki_url(job)
    if not urls and hf.job_udany(job):
        # completed bez result_url: doczytaj `generate get` kilka razy (bez kredytow), zanim fabryka uzna blad
        if log:
            log(f"job {hf.job_id_z(job)} completed bez result_url - doczytuje generate get...")
        job, urls = hf.doczytaj_url(job)
    return {
        "job_id": hf.job_id_z(job),
        "status": hf.status_joba(job) or "",
        "urls": urls,
        "blad": hf.blad_joba(job),
        "surowe": job,
    }


def pobierz(url, sciezka):
    return hf.pobierz(url, sciezka)


def udany(status):
    return status in hf.STATUSY_OK


def nieudany(status):
    return status in hf.STATUSY_BLAD


# --- pomocnicze dla panelu: lista modeli/glosow (wymaga zalogowanego CLI) ---

def modele(typ=None):
    try:
        return hf.modele(typ)
    except hf.HiggsfieldBlad as e:
        raise BladDostawcy(str(e))


def glosy():
    try:
        return hf.glosy()
    except hf.HiggsfieldBlad as e:
        raise BladDostawcy(str(e))


def upload_url(plik):
    """Wgrywa plik przez CLI i zwraca jego publiczny URL (do podania innym API, np. sync.so) albo None."""
    try:
        dane = hf.upload(plik)
    except hf.HiggsfieldBlad as e:
        raise BladDostawcy(str(e))
    for k in ("url", "file_url", "media_url", "public_url"):
        if isinstance(dane.get(k), str) and dane[k].startswith("http"):
            return dane[k]
    return None
