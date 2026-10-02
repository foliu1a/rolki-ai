# -*- coding: utf-8 -*-
"""Dostawca: Higgsfield (Seedance 2.5 Edit i inne modele) przez oficjalne CLI - higgsfield_cli.py.

Wszystko woluje `higgsfield_cli` przez atrybuty modulu (hf.koszt itd.), zeby testy mogly je podmienic."""
import re

import baza
import higgsfield_cli as hf
from dostawcy import BladDostawcy

NAZWA = "higgsfield"
JEDNOSTKA = "kr"


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
    return hf.komenda_podglad(model, params, media)


def generuj(z, timeout="30m", log=None):
    """Jedna proba generacji (CLI --wait). Zwraca dict; nie powtarza - o powtorkach decyduje fabryka."""
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
