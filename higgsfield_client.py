# -*- coding: utf-8 -*-
"""
Cienki klient REST do Higgsfield API.

Nie zgaduje konkretnego kontraktu API (endpointy/pola roznia sie zaleznie
od planu/konta) - wszystko jest parametryzowane przez klucze.py. Uzupelnij
tam prawdziwe wartosci zgodnie z dokumentacja swojego konta, zanim uzyjesz
tego klienta.
"""
import time

try:
    import requests
except ImportError:
    requests = None

try:
    from klucze import (
        HIGGSFIELD_API_KEY,
        HIGGSFIELD_BASE_URL,
        HIGGSFIELD_GENERATE_PATH,
        HIGGSFIELD_STATUS_PATH,
        HIGGSFIELD_AUTH_HEADER,
        HIGGSFIELD_AUTH_PREFIX,
    )
except ImportError:
    HIGGSFIELD_API_KEY = ""
    HIGGSFIELD_BASE_URL = ""
    HIGGSFIELD_GENERATE_PATH = "/v1/generations"
    HIGGSFIELD_STATUS_PATH = "/v1/generations/{job_id}"
    HIGGSFIELD_AUTH_HEADER = "Authorization"
    HIGGSFIELD_AUTH_PREFIX = "Bearer "


class BrakKonfiguracji(Exception):
    pass


def _sprawdz_konfiguracje():
    if requests is None:
        raise BrakKonfiguracji(
            "Brak biblioteki 'requests'. Zainstaluj: pip install requests"
        )
    if not HIGGSFIELD_API_KEY or not HIGGSFIELD_BASE_URL:
        raise BrakKonfiguracji(
            "Higgsfield nie skonfigurowany. Skopiuj klucze.py.przyklad -> klucze.py "
            "i uzupelnij HIGGSFIELD_API_KEY oraz HIGGSFIELD_BASE_URL (patrz README.md)."
        )


def _naglowki():
    return {HIGGSFIELD_AUTH_HEADER: f"{HIGGSFIELD_AUTH_PREFIX}{HIGGSFIELD_API_KEY}"}


def wygeneruj(prompt, faceswap_source=None, dodatkowe_pola=None):
    """Wysyla zlecenie generacji. Zwraca job_id (string).

    faceswap_source: opcjonalna sciezka/URL zrodla twarzy do podmiany -
        pole `dodatkowe_pola` pozwala dopasowac nazwe klucza do faktycznego
        kontraktu API (np. {"face_image_url": ...}).
    """
    _sprawdz_konfiguracje()
    payload = {"prompt": prompt}
    if faceswap_source:
        payload["faceswap_source"] = faceswap_source
    if dodatkowe_pola:
        payload.update(dodatkowe_pola)

    url = HIGGSFIELD_BASE_URL.rstrip("/") + HIGGSFIELD_GENERATE_PATH
    odp = requests.post(url, json=payload, headers=_naglowki(), timeout=60)
    odp.raise_for_status()
    dane = odp.json()
    job_id = dane.get("id") or dane.get("job_id")
    if not job_id:
        raise BrakKonfiguracji(
            f"Odpowiedz API nie zawiera pola 'id'/'job_id' - dopasuj parsowanie "
            f"w higgsfield_client.py do faktycznej odpowiedzi: {dane}"
        )
    return job_id


def status(job_id):
    _sprawdz_konfiguracje()
    url = HIGGSFIELD_BASE_URL.rstrip("/") + HIGGSFIELD_STATUS_PATH.format(job_id=job_id)
    odp = requests.get(url, headers=_naglowki(), timeout=30)
    odp.raise_for_status()
    return odp.json()


def czekaj_na_wynik(job_id, interwal=5, limit_prob=120):
    """Odpytuje status co `interwal` sekund az do ukonczenia albo bledu."""
    for _ in range(limit_prob):
        dane = status(job_id)
        stan = dane.get("status")
        if stan in ("completed", "done", "succeeded"):
            return dane
        if stan in ("failed", "error"):
            raise RuntimeError(f"Generacja {job_id} nie powiodla sie: {dane}")
        time.sleep(interwal)
    raise TimeoutError(f"Przekroczono limit oczekiwania na wynik {job_id}")
