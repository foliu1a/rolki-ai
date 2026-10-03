# -*- coding: utf-8 -*-
"""Zdjecia persony: model obrazu (Higgsfield, np. nano_banana_2 / seedream) + referencje -> plik w folderze zdjec.

    generuj(slug, ile=1, prompt=None, dry_run=False, log=None, stop=None) -> {"zrobione": n, "stop": powod|None}

Prompty: modelki/<slug>/prompty/zdjecia.txt (jedna linia = jeden prompt, '#' = komentarz) - autopilot bierze po kolei.
Model: ustawienie `zdjecia_model` (job_type z `python fabryka.py modele --typ image`), parametry `zdjecia_parametry`.
Bezpiecznik: ten sam min_kredyty / limit dzienny Higgsfield co rolki; `zdjecia_dziennie` dla autopilota.
Zdjecia NIE przechodza przez Media Tool (user ma do tego osobna apke).
"""
import os
import time

import baza
import dostawcy


def _log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def _zdarzenie(log, slug, typ, tekst, **dane):
    (log or _log)(tekst)
    try:
        baza.dziennik_zapisz(typ, tekst, modelka=slug, **dane)
    except OSError:
        pass


def zlecenie(slug, prompt, ust=None):
    ust = ust or baza.ustawienia_modelki(slug)
    model = (ust.get("zdjecia_model") or "").strip()
    if not model:
        raise ValueError("Brak modelu zdjec: ustaw zdjecia_model (panel -> Persona -> Zdjecia, lista z `modele --typ image`).")
    params = dict(ust.get("zdjecia_parametry") or {})
    soul = (ust.get("soul_id") or "").strip()
    # Soul (text2image_soul_v2 / soul_cinematic) = wytrenowana postac: wtedy --soul-id ZAMIAST zdjec referencyjnych
    uzyj_soul = bool(soul) and ("soul" in model)
    return {
        "slug": slug, "prompt": prompt, "video": None,
        "images": [] if uzyj_soul else list(baza.sciezki_referencji(slug)),
        "duration": None, "aspect_ratio": params.pop("aspect_ratio", None), "resolution": params.pop("resolution", None),
        "model": model, "mode": params.pop("mode", None), "generate_audio": None, "soul_id": soul if uzyj_soul else "",
        "parametry": params, "dostawca": "higgsfield",
    }


def generuj(slug, ile=1, prompt=None, dry_run=False, log=None, stop=None):
    log = log or _log
    wynik = {"zrobione": 0, "stop": None, "pliki": []}
    ust = baza.ustawienia_modelki(slug)
    d = dostawcy.dostawca("higgsfield")
    if not baza.sciezki_referencji(slug):
        log("Brak referencji persony - zdjecia bez twarzy nie maja sensu.")
        wynik["stop"] = "brak referencji"
        return wynik
    try:
        saldo = d.saldo() if not dry_run else 0
    except dostawcy.BladDostawcy as e:
        _zdarzenie(log, slug, "blad", f"[BLAD] saldo: {e}")
        wynik["stop"] = f"saldo: {e}"
        return wynik
    limit_dnia = baza.limit_dzienny("higgsfield")
    wydano = baza.wydano_dzis("higgsfield")
    for i in range(int(ile)):
        if stop is not None and stop.is_set():
            wynik["stop"] = "stop"
            break
        if prompt:
            tekst = prompt
        else:
            tekst, _ = baza.nastepny_prompt_zdjecia(slug)
            if not tekst:
                log("Brak promptow zdjec (prompty/zdjecia.txt pusty) - podaj --prompt albo dopisz linie w pliku.")
                wynik["stop"] = "brak promptow"
                break
        try:
            z = zlecenie(slug, tekst, ust)
        except ValueError as e:
            log(f"[BLAD] {e}")
            wynik["stop"] = str(e)
            break
        if dry_run:
            log(d.podglad(z))
            continue
        try:
            k = d.koszt(z)
        except dostawcy.BladDostawcy as e:
            _zdarzenie(log, slug, "blad", f"zdjecie: koszt nieznany ({e})")
            wynik["stop"] = f"koszt: {e}"
            break
        if k is None:
            k = 10
        if saldo - k < ust["min_kredyty"]:
            _zdarzenie(log, slug, "uwaga", f"zdjecie: {k} kr zostawiloby {saldo - k} < min_kredyty - STOP")
            wynik["stop"] = "min_kredyty"
            break
        if limit_dnia and wydano + k > limit_dnia:
            _zdarzenie(log, slug, "uwaga", f"zdjecie: limit dzienny ({wydano}+{k} > {limit_dnia}) - STOP")
            wynik["stop"] = "limit dzienny"
            break
        _zdarzenie(log, slug, "info", f"zdjecie: start ({z['model']}, ~{k} kr) - {tekst[:80]}")
        try:
            job = d.generuj(z, timeout="15m", log=log)
        except dostawcy.BladDostawcy as e:
            _zdarzenie(log, slug, "blad", f"zdjecie: nie wyszlo ({e})")
            baza.dodaj_zdjecie(slug, tekst, status="blad", notatki=str(e)[:500])
            continue
        try:
            nowe_saldo = d.saldo()
            zuzyte = max(0, saldo - nowe_saldo)
            saldo = nowe_saldo
        except dostawcy.BladDostawcy:
            zuzyte = k if job.get("urls") else 0
            saldo -= zuzyte
        wydano = baza.dopisz_wydatek(zuzyte, "higgsfield")
        urls = job.get("urls") or []
        if not urls:
            _zdarzenie(log, slug, "blad", f"zdjecie: job {job.get('job_id')} bez URL ({job.get('status')}; {job.get('blad')})")
            baza.dodaj_zdjecie(slug, tekst, job_id=job.get("job_id"), koszt=zuzyte, status="blad", notatki=(job.get("blad") or "")[:500])
            continue
        zid = baza.dodaj_zdjecie(slug, tekst, job_id=job.get("job_id"), koszt=zuzyte, status="pobieranie")
        rozsz = os.path.splitext(urls[0].split("?")[0])[1].lower() or ".png"
        if rozsz not in baza.ROZSZERZENIA_OBRAZU:
            rozsz = ".png"
        cel = os.path.join(baza.folder_zdjec(slug), f"{zid:03d}_{time.strftime('%Y%m%d')}{rozsz}")
        try:
            d.pobierz(urls[0], cel)
        except Exception as e:
            _zdarzenie(log, slug, "blad", f"zdjecie #{zid}: pobranie nie wyszlo ({e})")
            _ustaw(slug, zid, status="blad", notatki=f"pobranie: {e}")
            continue
        _ustaw(slug, zid, status="gotowe", plik=cel)
        wynik["zrobione"] += 1
        wynik["pliki"].append(cel)
        _zdarzenie(log, slug, "ok", f"zdjecie #{zid}: GOTOWE ({zuzyte} kr) -> {cel}", plik=cel)
    return wynik


def _ustaw(slug, zid, **pola):
    plik = baza._plik_zdjec(slug)
    lista = baza._wczytaj_json(plik, [])
    for z in lista:
        if z["id"] == zid:
            z.update(pola)
    baza._zapisz_json(plik, lista)
