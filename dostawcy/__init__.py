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
"""
import importlib
import re

NAZWY = ("higgsfield", "yapper")


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
    if nazwa not in NAZWY:
        raise BladDostawcy(f"Nieznany dostawca '{nazwa}'. Znam: {', '.join(NAZWY)}")
    return importlib.import_module(f"dostawcy.{nazwa}")
