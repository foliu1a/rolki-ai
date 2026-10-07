# -*- coding: utf-8 -*-
"""Dostawcy generacji wideo (i lipsyncu) ze wspolnym, prostym interfejsem.

Kazdy dostawca to modul z funkcjami:
    gotowy()                 -> (bool, komunikat)   zalogowany / ma klucz?
    saldo()                  -> int | None          kredyty na koncie (None = dostawca nie podaje)
    koszt(zlecenie)          -> int | None          szacunek bez generacji
    podglad(zlecenie)        -> str                 co zostanie wyslane (--dry-run)
    generuj(zlecenie, ...)   -> {"job_id", "status", "urls", "blad", "surowe"}   JEDNA proba
    pobierz(url, sciezka)    -> sciezka

`zlecenie` to zwykly slownik budowany w fabryka.zlecenie():
    slug, prompt, video (sciezka albo None), images [sciezki], duration, aspect_ratio, resolution,
    model, mode, generate_audio, soul_id, parametry {...}

Bledy dostawcy (CLI/API/siec) to BladDostawcy - fabryka je lapie i decyduje o powtorce.

Rolki (fabryka._wyslij/_czekaj): zlec(z, klucz, znacznik, log) -> sprawdz(job_id) -> koncowy/udany/nieudany(status),
koszt_joba(wynik, wycena), znajdz(model, ...) (zadanie z przerwanego wysylania), IDEMPOTENTNY, JEDNOSTKA ("kr" kredyty,
"c" centy USD - WaveSpeed), WYMAGA_LIMITU (True = bez dziennego limitu fabryka nic u tego dostawcy nie wyda).
"""
import importlib
import re

NAZWY = ("higgsfield", "yapper", "wavespeed")    # robia rolki (pelny interfejs)
NAZWY_SALDA = NAZWY + ("elevenlabs",)            # maja saldo do paska w panelu (elevenlabs: tylko gotowy/saldo)
NAZWY_ZAPASU = ("yapper", "wavespeed")           # dozwolone kroki zapas_nsfw
JEDNOSTKI = {"higgsfield": "kr", "yapper": "kr", "wavespeed": "c", "sync": "c", "elevenlabs": "zn"}
NAZWY_LUDZKIE = {"higgsfield": "Higgsfield", "yapper": "yapper.so", "wavespeed": "WaveSpeed", "sync": "sync.so",
                 "elevenlabs": "ElevenLabs"}


def jednostka(nazwa):
    """Jednostka kwot dostawcy w budzecie: 'kr' (kredyty), 'c' (centy USD), 'zn' (znaki)."""
    return JEDNOSTKI.get((nazwa or "higgsfield").strip().lower(), "kr")


def kwota(k, nazwa="higgsfield"):
    """Kwota do logow i dziennika: kredyty '46 kr', centy USD (WaveSpeed, sync.so) '$2.60'; None -> '? kr' / '$?'."""
    if jednostka(nazwa) == "c":
        return "$?" if k is None else f"${int(k) / 100:.2f}"
    return f"{k if k is not None else '?'} kr"


def sekundy(timeout, domyslnie=1800):
    """'30m' / '90s' / '2h' / 600 -> sekundy."""
    if isinstance(timeout, (int, float)):
        return int(timeout)
    m = re.fullmatch(r"\s*(\d+)\s*([smh]?)\s*", str(timeout))
    if not m:
        return domyslnie
    n, j = int(m.group(1)), m.group(2)
    return n * {"": 1, "s": 1, "m": 60, "h": 3600}[j]


class BladDostawcy(Exception):
    pass


class BrakKlucza(BladDostawcy):
    pass


def dostawca(nazwa):
    nazwa = (nazwa or "higgsfield").strip().lower()
    if nazwa not in NAZWY_SALDA:
        raise BladDostawcy(f"Nieznany dostawca '{nazwa}'. Znam: {', '.join(NAZWY_SALDA)}")
    return importlib.import_module(f"dostawcy.{nazwa}")
