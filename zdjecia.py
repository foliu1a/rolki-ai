# -*- coding: utf-8 -*-
"""Zdjecia persony: model obrazu (Higgsfield, np. nano_banana_2 / seedream) + referencje -> plik w folderze zdjec.

    generuj(slug, ile=1, prompt=None, dry_run=False, log=None, stop=None, stroj=None) -> {"zrobione": n, "stop": powod|None, "pliki": [...]}

Prompty: modelki/<slug>/prompty/zdjecia.txt (jedna linia = jeden prompt, '#' = komentarz) - autopilot bierze po kolei.
Model: ustawienie `zdjecia_model` (job_type z `python fabryka.py modele --typ image`), parametry `zdjecia_parametry`.
Stroje (character elements): zdjecia w modelki/<slug>/stroje/ - `stroj`:
    None  = wg ustawienia zdjecia_stroje (co drugie zdjecie w kolejnym stroju, gdy stroje sa),
    "bez" = bez stroju, "auto" = kolejny stroj po kolei, albo nazwa pliku / sciezka.
  Zdjecie stroju idzie jako OSTATNI obraz, a do promptu doklejany jest `zdjecia_prompt_stroj`.
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


def stroje(slug):
    """Zdjecia strojow persony (modelki/<slug>/stroje/), posortowane."""
    folder = baza.folder_strojow(slug)
    return [os.path.join(folder, n) for n in sorted(os.listdir(folder)) if n.lower().endswith(baza.ROZSZERZENIA_OBRAZU)]


def _nastepny_stroj(slug):
    """Kolejny stroj po kolei (w kolko); licznik w zdjecia_stan.json obok licznika promptow."""
    lista = stroje(slug)
    if not lista:
        return None
    plik = os.path.join(baza.folder_modelki(slug), "zdjecia_stan.json")
    stan = baza._wczytaj_json(plik, {})
    i = int(stan.get("stroj", 0)) % len(lista)
    stan["stroj"] = i + 1
    baza._zapisz_json(plik, stan)
    return lista[i]


def wybierz_stroj(slug, stroj=None, ust=None):
    """Sciezka do zdjecia stroju dla tego zdjecia albo None. Patrz docstring modulu."""
    ust = ust or baza.ustawienia_modelki(slug)
    if stroj is None:
        if not ust.get("zdjecia_stroje") or "soul" in (ust.get("zdjecia_model") or ""):
            return None
        # co drugie zdjecie w stroju (liczac wszystkie zdjecia persony), zeby autopilot robil na przemian
        return _nastepny_stroj(slug) if len(baza.lista_zdjec(slug)) % 2 == 1 else None
    s = str(stroj).strip()
    if not s or s.lower() in ("bez", "none", "0", "false", "brak"):
        return None
    if s.lower() in ("auto", "kolejny", "next", "1", "true"):
        return _nastepny_stroj(slug)
    kandydat = s if os.path.isabs(s) else os.path.join(baza.folder_strojow(slug), s)
    if os.path.isfile(kandydat):
        return kandydat
    for p in stroje(slug):
        if os.path.basename(p).lower() == os.path.basename(s).lower():
            return p
    raise ValueError(f"Nie ma takiego stroju: {s} (folder stroje/ persony).")


def zlecenie(slug, prompt, ust=None, stroj=None):
    ust = ust or baza.ustawienia_modelki(slug)
    model = (ust.get("zdjecia_model") or "").strip()
    if not model:
        raise ValueError("Brak modelu zdjec: ustaw zdjecia_model (panel -> Persona -> Zdjecia, lista z `modele --typ image`).")
    params = dict(ust.get("zdjecia_parametry") or {})
    soul = (ust.get("soul_id") or "").strip()
    # Soul (text2image_soul_v2 / soul_cinematic) = wytrenowana postac: wtedy --soul-id ZAMIAST zdjec referencyjnych
    uzyj_soul = bool(soul) and ("soul" in model)
    obrazy = [] if uzyj_soul else list(baza.sciezki_referencji(slug))
    if stroj:
        obrazy.append(stroj)      # stroj jako OSTATNI obraz - prompt odwoluje sie do "the last reference image"
        dopisek = (ust.get("zdjecia_prompt_stroj") or "").strip()
        if dopisek:
            prompt = f"{(prompt or '').strip()}\n{dopisek}".strip()
    return {
        "slug": slug, "prompt": prompt, "video": None,
        "images": obrazy,
        "duration": None, "aspect_ratio": params.pop("aspect_ratio", None), "resolution": params.pop("resolution", None),
        "model": model, "mode": params.pop("mode", None), "generate_audio": None, "soul_id": soul if uzyj_soul else "",
        "parametry": params, "dostawca": "higgsfield",
    }


def generuj(slug, ile=1, prompt=None, dry_run=False, log=None, stop=None, stroj=None):
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
            plik_stroju = wybierz_stroj(slug, stroj, ust)
            z = zlecenie(slug, tekst, ust, stroj=plik_stroju)
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
        opis_stroju = f", strój {os.path.basename(plik_stroju)}" if plik_stroju else ""
        _zdarzenie(log, slug, "info", f"zdjecie: start ({z['model']}, ~{k} kr{opis_stroju}) - {tekst[:80]}")
        try:
            job = d.generuj(z, timeout="15m", log=log)
        except dostawcy.BladDostawcy as e:
            _zdarzenie(log, slug, "blad", f"zdjecie: nie wyszlo ({e})")
            baza.dodaj_zdjecie(slug, tekst, status="blad", notatki=str(e)[:500], stroj=plik_stroju)
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
            baza.dodaj_zdjecie(slug, tekst, job_id=job.get("job_id"), koszt=zuzyte, status="blad", notatki=(job.get("blad") or "")[:500],
                               stroj=plik_stroju)
            continue
        zid = baza.dodaj_zdjecie(slug, tekst, job_id=job.get("job_id"), koszt=zuzyte, status="pobieranie", stroj=plik_stroju)
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
        _zdarzenie(log, slug, "ok", f"zdjecie #{zid}: GOTOWE ({zuzyte} kr{opis_stroju}) -> {cel}", plik=cel)
    return wynik


def _ustaw(slug, zid, **pola):
    plik = baza._plik_zdjec(slug)
    lista = baza._wczytaj_json(plik, [])
    for z in lista:
        if z["id"] == zid:
            z.update(pola)
    baza._zapisz_json(plik, lista)
