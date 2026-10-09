# -*- coding: utf-8 -*-
"""
fabryka.py - automat: filmik zrodlowy -> Seedance 2.5 Edit (Higgsfield CLI) albo Wan (yapper.so) -> rolka.

Obieg:
  1. Wrzucasz filmiki do wrzutni (zrodla_dir albo modelki/<slug>/zrodla/)
  2. python fabryka.py skanuj          -> kazdy nowy filmik dostaje pomysl (status: nowy) + klatki podgladu + prompt usera
  3. python fabryka.py koszt           -> ile kredytow zjedza pozycje z promptem
  4. python fabryka.py generuj         -> bezpiecznik budzetu, generacja, pobranie, Media Tool, lipsync (status: gotowe)
  5. python fabryka.py zdjecia         -> zdjecia persony (model obrazu z referencjami)
     python fabryka.py zdjecie-swap x.jpg -> persona w miejsce osoby ze zdjecia (zdjecia_swap.py, --sucho = prompt + cena)
  6. python fabryka.py lipsync ...     -> wideo + glos -> sync.so
  7. python fabryka.py autopilot       -> wszystko powyzsze w petli (albo z panelu)

Logika siedzi w funkcjach (skanuj, koszt, generuj, ...) wolanych z CLI, panelu (app.py) i autopilota.
Wszystko czyta/zapisuje przez baza.py. Dostawcy generacji w dostawcy/ (higgsfield = CLI, yapper = API).
"""
import argparse
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone

import baza
import dostawcy
import higgsfield_cli as hf
import klatki

if sys.platform == "win32":
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")

ROZSZERZENIA_WIDEO = (".mp4", ".mov", ".webm", ".m4v")


class Przerwano(Exception):
    """Uzytkownik zatrzymal zadanie (przycisk STOP w panelu)."""


def _slug(arg):
    slug = arg or baza.aktywna_modelka()
    if not slug or slug not in baza.lista_modelek():
        raise SystemExit("Brak aktywnej modelki. Podaj --modelka <slug> albo ustaw aktywna w panelu.")
    return slug


def _log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def _zdarzenie(log, slug, typ, tekst, **dane):
    """Log na konsole/panel + wpis do dziennika (typ: info|ok|uwaga|blad|kredyty)."""
    (log or _log)(tekst)
    try:
        baza.dziennik_zapisz(typ, tekst, modelka=slug, **dane)
    except OSError:
        pass


def _sprawdz_stop(stop):
    if stop is not None and stop.is_set():
        raise Przerwano("zatrzymane przez uzytkownika")


def _bezpieczna_nazwa(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_") or "plik"


# ---------------- konto / model ----------------

def cmd_konto(args):
    try:
        k = hf.konto()
    except hf.HiggsfieldBlad as e:
        print(f"[BLAD] {e}")
        return 1
    kr = hf._wyciagnij_kredyty(k)
    print(f"kredyty: {kr if kr is not None else '?'}")
    for klucz in ("email", "plan", "subscription", "workspace"):
        if klucz in k:
            print(f"{klucz}: {k[klucz]}")
    if args.json:
        print(json.dumps(k, ensure_ascii=False, indent=2))
    return 0


def cmd_model(args):
    try:
        dane = hf.model(args.jst)
    except hf.HiggsfieldBlad as e:
        print(f"[BLAD] {e}")
        return 1
    print(json.dumps(dane, ensure_ascii=False, indent=2))
    return 0


def cmd_modele(args):
    """Lista modeli dostawcy (Higgsfield: `model list`, yapper: GET /models)."""
    try:
        d = dostawcy.dostawca(args.dostawca)
        lista = d.modele(args.typ) if args.dostawca == "higgsfield" else d.modele()
    except dostawcy.BladDostawcy as e:
        print(f"[BLAD] {e}")
        return 1
    if args.json:
        print(json.dumps(lista, ensure_ascii=False, indent=2))
        return 0
    for m in lista:
        if isinstance(m, dict):
            ident = m.get("job_type") or m.get("id") or m.get("slug") or m.get("name")
            print(f"{ident:40} {m.get('type') or m.get('media_type') or m.get('processType') or ''}  {m.get('name') or m.get('display_name') or ''}")
        else:
            print(m)
    return 0


def cmd_glosy(args):
    try:
        lista = hf.glosy()
    except hf.HiggsfieldBlad as e:
        print(f"[BLAD] {e}")
        return 1
    if args.json:
        print(json.dumps(lista, ensure_ascii=False, indent=2))
        return 0
    for g in lista:
        if isinstance(g, dict):
            print(f"{g.get('id') or g.get('voice_id')}  [{g.get('voice_type') or g.get('type') or '?'}]  "
                  f"{g.get('name') or g.get('display_name') or ''}  {g.get('gender') or ''}")
    return 0


# ---------------- sprawdzanie promptow ----------------

_WZORZEC_IMAGE = re.compile(r"@\[Image\s*(\d+)\]\(image_\d+\)|@Image\s*(\d+)", re.I)


def sprawdz_prompt(slug, ust=None):
    """Ostrzezenia o promptach persony (nie blokuja generacji): liczba @[Image N] vs liczba zdjec,
    brak promptu B przy strojach, pusty prompt. Zwraca liste zdan po polsku."""
    ust = ust or baza.ustawienia_modelki(slug)
    uwagi = []
    refs = len(baza.sciezki_referencji(slug))
    a, b = baza.prompt_bazowy(slug), baza.prompt_stroj(slug)
    if not a:
        uwagi.append("brak promptu A (stroj z filmu) - rolki z filmiku beda bez promptu")
    for nazwa, prompt, oczekiwane in (("A", a, refs), ("B", b, refs + 1)):
        if not prompt:
            continue
        numery = sorted({int(m.group(1) or m.group(2)) for m in _WZORZEC_IMAGE.finditer(prompt)})
        if not numery:
            continue
        # najwyzszy numer ma byc rowny liczbie zdjec: wyzszy = zdjecia nie ma, nizszy = ostatnie zdjecie (np. stroj) nieuzyte
        if max(numery) != oczekiwane:
            uwagi.append(f"prompt {nazwa}: odwoluje sie do @Image {numery}, a zdjec jest {oczekiwane} "
                         f"({'referencje' if nazwa == 'A' else 'referencje + stroj'}) - najwyzszy numer musi byc rowny liczbie zdjec")
    stroje = [n for n in os.listdir(baza.folder_strojow(slug)) if n.lower().endswith(baza.ROZSZERZENIA_OBRAZU)]
    if (stroje or baza.stroj_domyslny(slug)) and not b:
        uwagi.append("sa zdjecia strojow, ale prompt B (stroj ze zdjecia) jest pusty")
    if (ust.get("stroj_swap") or "biblioteka") == "biblioteka" and not b and baza.stroje_biblioteki(tylko_ze_zdjeciem=True):
        uwagi.append("stroje z biblioteki wymagaja promptu B (stroj ze zdjecia) - bez niego nowe klipy ida ze strojem z filmu")
    uwagi += sprawdz_prompt_wan(slug, ust)
    return uwagi


LIMIT_PROMPTU_WAN = 5000

# Sylwetka persony (profil.sylwetka, EN) - fabryka dokleja ja na KONCU promptu persony w character swap (A i B, Seedance i Wan);
# pliki promptow usera zostaja nietkniete. Feedback usera 2026-10-07: model robi Noemi za maly biust i posladki.
NAGLOWEK_SYLWETKI = "BODY SHAPE (highest priority after face):"


def sylwetka_persony(slug):
    """profil.sylwetka (EN) jedna linijka albo ''."""
    return re.sub(r"\s+", " ", str(baza.profil_modelki(slug).get("sylwetka") or "")).strip()


def doklej_sylwetke(prompt, sylwetka, limit=None):
    """Prompt persony + blok 'BODY SHAPE (highest priority after face): ...' na koncu. limit (Wan: 5000 znakow): gdy pelny opis
    sie nie miesci - tylko pierwsze zdanie, a gdy i to nie - prompt bez zmian. Zwraca (prompt, 'pelna'|'krotka'|'pominieta'|
    'brak'|'jest')."""
    prompt = prompt or ""
    if not sylwetka or not prompt.strip():
        return prompt, "brak"
    if NAGLOWEK_SYLWETKI in prompt:
        return prompt, "jest"
    m = re.match(r"(.+?[.!?])(\s|$)", sylwetka)
    for wersja, tekst in (("pelna", sylwetka), ("krotka", m.group(1) if m else sylwetka)):
        tekst = tekst.strip()
        nowy = f"{prompt.rstrip()}\n\n{NAGLOWEK_SYLWETKI} {tekst}" + ("" if tekst.endswith((".", "!", "?")) else ".")
        if limit is None or len(nowy) <= limit:
            return nowy, wersja
    return prompt, "pominieta"


def _krok_uzywa_wan(dostawca, model):
    """Czy krok (dostawca, model) dostaje prompt Wan (prompty/wan.txt): yapper zawsze, WaveSpeed - modele Wan (nie Seedance)."""
    dostawca = (dostawca or "").strip().lower()
    if dostawca == "yapper":
        return True
    if dostawca == "wavespeed":
        from dostawcy import wavespeed
        return not wavespeed.uzywa_promptu_persony(model)
    return False


def uzywa_promptu_wan(ust):
    """Czy persona gdziekolwiek uzywa promptu Wan: dostawca rolek (yapper / WaveSpeed Wan) albo krok zapas_nsfw."""
    d = (ust.get("dostawca") or "higgsfield").strip().lower()
    if d == "yapper" or (d == "wavespeed" and _krok_uzywa_wan(d, (ust.get("wavespeed") or {}).get("model"))):
        return True
    return any(isinstance(k, dict) and _krok_uzywa_wan(k.get("dostawca"), k.get("model")) for k in (ust.get("zapas_nsfw") or []))


def zapas_dla_stroju(kroki):
    """Czy ktorykolwiek krok zapas_nsfw zachowa stroj ze zdjecia (wariant B): tylko kroki z promptem persony (WaveSpeed Seedance)."""
    return any(isinstance(k, dict) and k.get("dostawca") and not _krok_uzywa_wan(k.get("dostawca"), k.get("model"))
               and (k.get("dostawca") or "").strip().lower() in dostawcy.NAZWY_ZAPASU for k in (kroki or []))


def sprawdz_prompt_wan(slug, ust=None):
    """Prompt Wan (yapper.prompt albo prompty/wan.txt) - sprawdzany tylko, gdy persona go uzywa (dostawca yapper / WaveSpeed Wan
    albo krok zapas_nsfw z Wan): max 5000 znakow, bez skladni @[Image N](image_N) z Higgsfielda."""
    ust = ust or baza.ustawienia_modelki(slug)
    if not uzywa_promptu_wan(ust):
        return []
    wan = baza.prompt_wan(slug)
    if not wan:
        return ["brak promptu Wan (prompty/wan.txt albo yapper.prompt) - modele Wan (yapper, WaveSpeed Wan, zapas po NSFW) nie rusza"]
    uwagi = []
    if len(wan) > LIMIT_PROMPTU_WAN:
        uwagi.append(f"prompt Wan ma {len(wan)} znakow, a Wan przyjmuje max {LIMIT_PROMPTU_WAN}")
    if _WZORZEC_IMAGE.search(wan):
        uwagi.append("prompt Wan ma skladnie @[Image N] z Higgsfielda - Wan jej nie zna (pisz 'the reference photos')")
    _, syl = doklej_sylwetke(wan, sylwetka_persony(slug), LIMIT_PROMPTU_WAN)
    if syl == "pominieta":
        uwagi.append(f"sylwetka persony nie miesci sie w prompcie Wan (max {LIMIT_PROMPTU_WAN} znakow) - Wan dostaje prompt bez niej")
    elif syl == "krotka":
        uwagi.append("prompt Wan dostaje tylko pierwsze zdanie sylwetki (pelna nie miesci sie w 5000 znakow)")
    return uwagi


# ---------------- diagnoza ----------------

def diagnoza():
    """Szybki przeglad: ffmpeg, Higgsfield, Media Tool, Telegram, persony. Lista {co, ok, info} dla panelu i dziennika."""
    import shutil
    wynik = []
    wynik.append({"co": "ffmpeg", "ok": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
                  "info": "jest" if shutil.which("ffmpeg") else "brak w PATH - zainstaluj ffmpeg (winget install Gyan.FFmpeg)"})
    try:
        import dostawcy.higgsfield as dh
        ok, info = dh.gotowy()
    except Exception as e:
        ok, info = False, str(e)
    wynik.append({"co": "higgsfield", "ok": ok, "info": info})
    try:
        import mediatool
        ok = mediatool.dostepny()
        wynik.append({"co": "mediatool", "ok": ok, "info": "jest" if ok else f"nie zainstalowany (szukam w {mediatool.MT_DIR}) - rolki beda zapisywane bez prania"})
    except Exception as e:
        wynik.append({"co": "mediatool", "ok": False, "info": str(e)})
    try:
        from dostawcy import telegram
        if telegram.skonfigurowany():
            wynik.append({"co": "telegram", "ok": telegram.sparowany(), "info": "sparowany" if telegram.sparowany() else "token jest, napisz /start do bota"})
        else:
            wynik.append({"co": "telegram", "ok": None, "info": "nie podlaczony (opcjonalnie)"})
    except Exception as e:
        wynik.append({"co": "telegram", "ok": False, "info": str(e)})
    wynik += _diagnoza_yappera()
    wynik += _diagnoza_wavespeed()
    for slug in baza.lista_modelek():
        braki = []
        if not baza.sciezki_referencji(slug):
            braki.append("brak zdjec persony")
        if not baza.prompt_bazowy(slug):
            braki.append("brak promptu A")
        ust = baza.ustawienia_modelki(slug)
        if ust.get("zdjecia_dziennie") and not ust.get("zdjecia_model"):
            braki.append("zdjecia_dziennie bez modelu zdjec")
        braki += [u for u in sprawdz_prompt(slug, ust) if not u.startswith("brak promptu A")]
        wynik.append({"co": f"persona {slug}", "ok": not braki, "info": ", ".join(braki) or "gotowa"})
        # foldery usera (pulpit): gdzie wrzuca, gdzie wychodzi
        try:
            wrzutnia, gotowe = baza.folder_zrodel(slug), baza.folder_gotowych(slug)
            wynik.append({"co": f"foldery {slug}", "ok": os.path.isdir(wrzutnia) and os.path.isdir(gotowe),
                          "info": f"wrzucasz: {wrzutnia} | gotowe: {gotowe}", "wrzutnia": wrzutnia, "gotowe": gotowe})
        except OSError as e:
            wynik.append({"co": f"foldery {slug}", "ok": False, "info": f"nie moge utworzyc folderow: {e}"})
        # osobne konto Telegram persony - musi napisac /start do bota
        konto = (ust.get("telegram_czat") or "").strip()
        if konto:
            try:
                from dostawcy import telegram
                cid, opis = telegram.czat_dla(konto) if telegram.skonfigurowany() else (None, "bot Telegram nie jest podlaczony")
                wynik.append({"co": f"telefon {slug}", "ok": bool(cid), "info": f"rolki {slug} -> {konto}" if cid else opis})
            except Exception as e:
                wynik.append({"co": f"telefon {slug}", "ok": False, "info": str(e)})
    return wynik


def _diagnoza_yappera():
    """yapper: czy klucz dziala (GET /credits) i czy jest dzienny limit - bez niego zapas po NSFW nic nie wyda.
    Tylko gdy jest klucz albo ktoras persona robi rolki na yapperze / ma zapas_nsfw."""
    import sekrety
    uzywa = []
    for s in baza.lista_modelek():
        u = baza.ustawienia_modelki(s)
        if (u.get("dostawca") or "higgsfield") == "yapper" or any(
                isinstance(k, dict) and (k.get("dostawca") or "").strip().lower() == "yapper" for k in (u.get("zapas_nsfw") or [])):
            uzywa.append(s)
    if not sekrety.klucz("yapper") and not uzywa:
        return []
    try:
        from dostawcy import yapper
        ok, info = yapper.gotowy()
    except Exception as e:
        ok, info = False, str(e)
    wynik = [{"co": "yapper", "ok": ok, "info": info}]
    limit = baza.limit_dzienny("yapper")
    if limit:
        wynik.append({"co": "limit yappera", "ok": True, "info": f"dzis {baza.wydano_dzis('yapper')}/{limit} kr"})
    else:
        wynik.append({"co": "limit yappera", "ok": False if uzywa else None,
                      "info": "nie ustawiony - zapas po NSFW (yapper) nic nie wyda, dopoki go nie ustawisz (Ustawienia -> Limity)"})
    return wynik


def _uzywa_wavespeed(ust):
    return (ust.get("dostawca") or "higgsfield") == "wavespeed" or any(
        isinstance(k, dict) and (k.get("dostawca") or "").strip().lower() == "wavespeed" for k in (ust.get("zapas_nsfw") or []))


def _diagnoza_wavespeed():
    """WaveSpeed: czy klucz dziala (GET /balance) i czy jest dzienny limit - bez niego fabryka nic tam nie wyda.
    Tylko gdy jest klucz albo ktoras persona robi rolki na WaveSpeed / ma go w zapas_nsfw."""
    import sekrety
    uzywa = [s for s in baza.lista_modelek() if _uzywa_wavespeed(baza.ustawienia_modelki(s))]
    if not sekrety.klucz("wavespeed") and not uzywa:
        return []
    try:
        from dostawcy import wavespeed
        ok, info = wavespeed.gotowy()
    except Exception as e:
        ok, info = False, str(e)
    wynik = [{"co": "wavespeed", "ok": ok, "info": info}]
    limit = baza.limit_dzienny("wavespeed")
    if limit:
        wynik.append({"co": "limit wavespeed", "ok": True,
                      "info": f"dzis {dostawcy.kwota(baza.wydano_dzis('wavespeed'), 'wavespeed')}/{dostawcy.kwota(limit, 'wavespeed')}"})
    else:
        wynik.append({"co": "limit wavespeed", "ok": False if uzywa else None,
                      "info": "nie ustawiony - fabryka nic nie wyda na WaveSpeed, dopoki go nie ustawisz (Ustawienia -> Limity)"})
    return wynik


def zapisz_diagnoze_w_dzienniku(skad="start"):
    """Jedna linia w dzienniku przy starcie panelu/autopilota: co dziala, czego brakuje."""
    try:
        d = diagnoza()
    except Exception as e:
        baza.dziennik_zapisz("uwaga", f"{skad}: diagnoza nie wyszla ({e})")
        return None
    zle = [f"{w['co']}: {w['info']}" for w in d if w["ok"] is False]
    ok = [w["co"] for w in d if w["ok"]]
    baza.dziennik_zapisz("uwaga" if zle else "info", f"{skad}: " + (("brakuje -> " + "; ".join(zle) + " | ") if zle else "")
                         + "ok: " + (", ".join(ok) or "nic"))
    return d


def cmd_diagnoza(args):
    for w in diagnoza():
        print(f"{'OK ' if w['ok'] else ('-- ' if w['ok'] is None else 'ZLE')} {w['co']:18} {w['info']}")
    return 0


# ---------------- status ----------------

def stan_modelki(slug):
    """Zbiorczy stan dla panelu/statusu: kolejka, budzet, wrzutnia, referencje, prompty, dostawca."""
    ust = baza.ustawienia_modelki(slug)
    st = baza.statystyki_pomyslow(slug)
    nowe = baza.lista_pomyslow(slug, "nowy")
    refs = baza.sciezki_referencji(slug)
    dostawca = ust.get("dostawca") or "higgsfield"
    return {
        "modelka": slug,
        "ustawienia": ust,
        "statystyki": st,
        "bez_promptu": [p["id"] for p in nowe if not p.get("prompt_higgsfield")],
        "do_generacji": [p["id"] for p in nowe if p.get("prompt_higgsfield") and not z_promptu(p)],
        "z_promptu_czeka": [p["id"] for p in nowe if z_promptu(p)],    # rolki z promptu robi sie po id (zakladka / Rolki)
        "w_toku": [p["id"] for p in baza.pomysly_w_toku(slug)],
        "zapas_nsfw": [f"{k.get('dostawca')} {k.get('model')}" for k in (ust.get("zapas_nsfw") or []) if isinstance(k, dict)],
        "niezeskanowane": [os.path.basename(z) for z in nowe_zrodla(slug)],
        "wrzutnia": baza.folder_zrodel(slug),
        "gotowe_dir": baza.folder_gotowych(slug),
        "referencje": [os.path.basename(r) for r in refs],
        "prompt_a": bool(baza.prompt_bazowy(slug)),
        "prompt_b": bool(baza.prompt_stroj(slug)),
        "dostawca": dostawca,
        "budzet": {
            "dostawca": dostawca,
            "jednostka": dostawcy.jednostka(dostawca),       # kr | c (centy USD - WaveSpeed)
            "wydano_dzis": baza.wydano_dzis(dostawca),
            "limit_dzienny": baza.limit_dzienny(dostawca),
            "min_kredyty": bezpiecznik(ust, dostawca)[0],
            "max_kredyty_na_rolke": bezpiecznik(ust, dostawca)[1],
            "rolki_dzis": len(baza.pomysly_z_dnia(slug)),
            "max_rolek_dziennie": ust.get("autopilot_max_rolek_dziennie"),
        },
        "zdjecia_dzis": len(baza.zdjecia_z_dnia(slug)),
        "audio": [os.path.basename(a) for a in baza.pliki_audio(slug)],
    }


def cmd_status(args):
    slug = _slug(args.modelka)
    s = stan_modelki(slug)
    ust = s["ustawienia"]
    print(f"modelka: {slug}   dostawca: {s['dostawca']}   model: {ust['model']} / {ust['mode']} / {ust['aspect_ratio']} / "
          f"rozdzielczosc: {OPIS_ROZDZIELCZOSCI}")
    if s.get("w_toku"):
        print("w toku (job wyslany, dokoncze bez wysylania drugi raz): " + ", ".join(f"#{i}" for i in s["w_toku"]))
    print(f"wrzutnia: {s['wrzutnia']}")
    print(f"gotowe:   {s['gotowe_dir']}   (Media Tool: {'tak' if ust.get('mediatool') else 'nie'})")
    print("pomysly: " + ", ".join(f"{k}={s['statystyki'].get(k, 0)}" for k in baza.STATUSY))
    b = s["budzet"]
    print(f"budzet dzienny ({b['dostawca']}): wydano {dostawcy.kwota(b['wydano_dzis'], b['dostawca'])}/"
          f"{dostawcy.kwota(b['limit_dzienny'], b['dostawca'])}, rolek dzis {b['rolki_dzis']}/{b['max_rolek_dziennie']}")
    if s["bez_promptu"]:
        print(f"czekaja na prompt ({len(s['bez_promptu'])}): " + ", ".join(f"#{i}" for i in s["bez_promptu"]))
    if s["do_generacji"]:
        print(f"gotowe do generacji ({len(s['do_generacji'])}): " + ", ".join(f"#{i}" for i in s["do_generacji"]))
    if s["niezeskanowane"]:
        print(f"filmiki w zrodla/ bez pomyslu ({len(s['niezeskanowane'])}): " + ", ".join(s["niezeskanowane"]))
        print("  -> python fabryka.py skanuj")
    print(f"referencje persony: {len(s['referencje'])} zdjec" + ("" if s["referencje"] else "  (wrzuc zdjecia do referencje/ !)"))
    if not ust.get("prompt_bazowy"):
        print("UWAGA: brak prompt_bazowy w ustawieniach - agent nie ma na czym oprzec promptow")
    print(f"autopilot: {'wlaczony' if ust.get('autopilot') else 'wylaczony'} (co {ust.get('autopilot_co_minut')} min), "
          f"zdjecia dziennie: {ust.get('zdjecia_dziennie')} (dzis {s['zdjecia_dzis']})")
    try:
        d = dostawcy.dostawca(s["dostawca"])
        print(f"saldo {s['dostawca']}: {dostawcy.kwota(d.saldo(), s['dostawca'])}  (min={dostawcy.kwota(b['min_kredyty'], s['dostawca'])}, "
              f"max/rolka={dostawcy.kwota(b['max_kredyty_na_rolke'], s['dostawca'])})")
    except dostawcy.BladDostawcy as e:
        print(f"kredyty {s['dostawca']}: niedostepne ({e})")
    return 0


# ---------------- skanowanie wrzutni ----------------

MAX_SEKUND_ZRODLA = 30   # Seedance 2.5 edit: twardy limit 30 s; user tnie krocej (max_sekund_rolki), bo koszt rosnie z dlugoscia

# Ile kredytow Higgsfield kosztuje sekunda rolki (video_edit = wejscie + wyjscie). 720p i 1080p zmierzone (6,04 s: 46 / 73 kr,
# 10,03 s: 76 / 121 kr - `generate cost` 2026-10-04), 480p szacunek z cennika apki. Tylko do podpowiedzi w panelu - prawdziwa
# cene mowi `generate cost` przed generacja.
KR_NA_SEKUNDE = {"480p": 3.5, "720p": 7.5, "1080p": 12.0}

# Rozdzielczosc wybiera dlugosc klipu (zasada usera 2026-10-04, Higgsfield Seedance i yapper Wan): klip <= 8 s -> 1080p,
# dluzszy -> 720p. Liczy sie dlugosc (pocietego) klipu w chwili generacji; ustawienie persony `resolution` dziala tylko dla
# pomyslow bez filmiku. 1080p/8 s to ok. 100 kr - miesci sie w max_kredyty_na_rolke 150.
PROG_1080P_S = 8.0
OPIS_ROZDZIELCZOSCI = "≤8 s → 1080p, dłuższe → 720p"

# Gotowe zestawy "Jakosc i koszt" (panel -> Ustawienia): dlugosc rolki (ciecie) i rozdzielczosc dla pomyslow bez filmiku.
# Rozdzielczosc rolki z filmiku wybiera zasada PROG_1080P_S, dlatego "najlepiej" = rolki do 8 s (zawsze 1080p).
PRESETY_JAKOSCI = {
    "oszczednie": {"resolution": "720p", "max_sekund_rolki": 10},
    "normalnie": {"resolution": "720p", "max_sekund_rolki": 15},
    "najlepiej": {"resolution": "1080p", "max_sekund_rolki": 8},
}


def rozdzielczosc_dla_czasu(sekundy):
    """Zasada usera: klip <= 8 s -> '1080p', dluzszy -> '720p'."""
    return "1080p" if float(sekundy) <= PROG_1080P_S + 1e-9 else "720p"


def czas_klipu(p):
    """Dlugosc (pocietego) filmiku zrodlowego pomyslu w sekundach albo None (pomysl bez filmiku / nieznana)."""
    if not p.get("zrodlo"):
        return None
    try:
        czas = float((p.get("info_zrodla") or {}).get("czas") or 0)
    except (TypeError, ValueError):
        return None
    return czas if czas > 0 else None


def rozdzielczosc_rolki(p, ust):
    """Rozdzielczosc tej rolki: z dlugosci klipu (<= 8 s -> 1080p, dluzszy -> 720p); bez filmiku - ustawienie persony."""
    czas = czas_klipu(p)
    if czas:
        return rozdzielczosc_dla_czasu(czas)
    return ust.get("resolution") or "720p"


def max_sekund_rolki(ust):
    """Dlugosc kawalka/rolki z ustawien, przycieta do 4-30 s (limit Seedance)."""
    try:
        n = int(ust.get("max_sekund_rolki") or MAX_SEKUND_ZRODLA)
    except (TypeError, ValueError):
        n = MAX_SEKUND_ZRODLA
    return max(4, min(MAX_SEKUND_ZRODLA, n))


def stawki_rolki(ust):
    """Stawki za sekunde klipu u dostawcy rolek persony: Higgsfield (i yapper - panel pokazuje skale Higgsfielda) =
    KR_NA_SEKUNDE w kredytach; WaveSpeed = centy USD z cennika wybranego modelu (wejscie + wyjscie, np. Turbo 1080p 26 c/s)."""
    if (ust.get("dostawca") or "higgsfield") == "wavespeed":
        from dostawcy import wavespeed
        try:
            return wavespeed.stawki_za_sekunde((ust.get("wavespeed") or {}).get("model"))
        except dostawcy.BladDostawcy:
            return wavespeed.stawki_za_sekunde(wavespeed.MODEL_DOMYSLNY)
    return KR_NA_SEKUNDE


def szacunek_kosztu_rolki(ust, sekundy=None, stawki=None):
    """Orientacyjny koszt jednej rolki (domyslnie w kredytach Higgsfield; stawki=stawki_rolki(ust) - u dostawcy persony):
    dlugosc x stawka za sekunde rozdzielczosci, ktora wybierze zasada <= 8 s -> 1080p (bez dlugosci - typowa rolka
    max_sekund_rolki)."""
    stawki = stawki or KR_NA_SEKUNDE
    sek = float(sekundy) if sekundy else max_sekund_rolki(ust)
    return int(round(sek * stawki[rozdzielczosc_dla_czasu(sek)]))


def preset_jakosci(ust):
    """Ktory zestaw 'Jakosc i koszt' odpowiada ustawieniom persony ('oszczednie'|'normalnie'|'najlepiej'|'wlasne')."""
    for nazwa, pola in PRESETY_JAKOSCI.items():
        if all(str(ust.get(k)) == str(v) for k, v in pola.items()):
            return nazwa
    return "wlasne"


def _opis_rozdzielczosci(max_s):
    """Co wyjdzie z rolek do max_s sekund: '1080p' (wszystkie <= 8 s) albo '720p (≤8 s → 1080p)'."""
    return "1080p" if max_s <= PROG_1080P_S else "720p (≤8 s → 1080p)"


def jakosc_i_koszt(slug, ust=None):
    """Dla panelu: aktualny zestaw, szacunek kosztu rolki i tabela zestawow z kosztami. Rozdzielczosc = zasada dlugosci klipu.
    Persona na WaveSpeed: kwoty w centach USD (jednostka "c") z cennika modelu i jej bezpiecznik wavespeed.max_kredyty_na_rolke."""
    ust = ust or baza.ustawienia_modelki(slug)
    dost = ust.get("dostawca") or "higgsfield"
    stawki = stawki_rolki(ust)
    max_s = max_sekund_rolki(ust)
    koszt = szacunek_kosztu_rolki(ust, stawki=stawki)
    _, max_na_rolke = bezpiecznik(ust, "wavespeed" if dost == "wavespeed" else "higgsfield")
    return {
        "preset": preset_jakosci(ust), "resolution": _opis_rozdzielczosci(max_s), "max_sekund_rolki": max_s,
        "koszt_rolki": koszt, "koszt_sekundy": stawki[rozdzielczosc_dla_czasu(max_s)],
        "koszt_sekundy_1080p": stawki["1080p"], "koszt_sekundy_720p": stawki["720p"],
        "prog_1080p_s": PROG_1080P_S, "zasada_rozdzielczosci": OPIS_ROZDZIELCZOSCI,
        "za_drogo": koszt > max_na_rolke, "max_kredyty_na_rolke": max_na_rolke,
        "dostawca": dost, "jednostka": "c" if dost == "wavespeed" else "kr",
        "presety": {n: dict(p, resolution=_opis_rozdzielczosci(p["max_sekund_rolki"]),
                            koszt_rolki=szacunek_kosztu_rolki(p, p["max_sekund_rolki"], stawki=stawki))
                    for n, p in PRESETY_JAKOSCI.items()},
    }


def uniewaznij_koszty(slug):
    """Po zmianie rozdzielczosci policzone wczesniej koszty rolek 'nowy' sa nieaktualne - czyscimy, panel policzy od nowa."""
    ile = 0
    for p in baza.lista_pomyslow(slug, "nowy"):
        if p.get("koszt") is not None:
            baza.aktualizuj_pomysl(slug, p["id"], koszt=None)
            ile += 1
    return ile


def ustaw_preset_jakosci(slug, nazwa):
    """Zapisuje zestaw 'Jakosc i koszt' (resolution + max_sekund_rolki) w ustawieniach persony."""
    if nazwa not in PRESETY_JAKOSCI:
        raise ValueError(f"Nieznany zestaw '{nazwa}'. Dozwolone: {', '.join(PRESETY_JAKOSCI)}")
    przed = baza.ustawienia_modelki(slug).get("resolution")
    ust = baza.zapisz_ustawienia(slug, **PRESETY_JAKOSCI[nazwa])
    if ust.get("resolution") != przed:
        uniewaznij_koszty(slug)
    return ust


def nowe_zrodla(slug):
    folder = baza.folder_zrodel(slug)
    wynik = []
    for n in sorted(os.listdir(folder)):
        p = os.path.join(folder, n)
        if (os.path.isfile(p) and n.lower().endswith(ROZSZERZENIA_WIDEO) and not baza.pomysl_po_zrodle(slug, p)
                and not baza.jest_pociete(slug, p)):
            wynik.append(p)
    return wynik


def _potnij_dlugi(slug, zrodlo, inf, log, max_s=MAX_SEKUND_ZRODLA):
    """Filmik dluzszy niz max_s -> kawalki w modelki/<slug>/zrodla_ciete/ (oryginal zostaje, skanuj go pomija)."""
    folder = os.path.join(baza.folder_modelki(slug), "zrodla_ciete")
    kawalki = klatki.potnij(zrodlo, folder, max_s=max_s)
    baza.oznacz_pociete(slug, zrodlo, kawalki)
    _zdarzenie(log, slug, "info", f"{os.path.basename(zrodlo)} ma {inf['czas']} s (max {max_s}) - pociety na {len(kawalki)} kawalkow")
    return kawalki


_nowe_zrodla = nowe_zrodla   # stara nazwa


def _plik_sie_zmienia(sciezka, odstep=1.5):
    """Plik jeszcze kopiowany (rosnie)? Autopilot nie ma skanowac polowy filmiku."""
    try:
        a = os.path.getsize(sciezka)
        time.sleep(odstep)
        return os.path.getsize(sciezka) != a
    except OSError:
        return True


def skanuj(slug, ile_klatek=4, log=None, stop=None, czekaj_na_kopiowanie=False):
    """Nowe filmiki z wrzutni -> pomysly (z promptem usera, wariant A/B) + klatki podgladu.
    Zwraca {"nowe": [id...], "bez_promptu": [id...], "pominiete": [nazwa...]}."""
    log = log or _log
    wynik = {"nowe": [], "bez_promptu": [], "pominiete": []}
    nowe = nowe_zrodla(slug)
    if not nowe:
        log("Brak nowych filmikow w " + baza.folder_zrodel(slug))
        return wynik
    folder_klatek = baza.folder_klatek(slug)
    ust = baza.ustawienia_modelki(slug)
    prompt_a = baza.prompt_bazowy(slug) if ust.get("prompt_auto") else ""
    prompt_b = baza.prompt_stroj(slug) if ust.get("prompt_auto") else ""
    stroj_dom = baza.stroj_domyslny(slug)
    if ust.get("prompt_auto") and not prompt_a:
        log("UWAGA: prompt_auto=true, ale prompt_bazowy (wariant A) jest pusty.")
    uwaga_biblioteki = []

    def stroj_klipu(zrodlo):
        """(sciezka zdjecia stroju albo None, stroj z biblioteki albo None): <nazwa>.stroj.png > stroj_domyslny > biblioteka."""
        wlasny = _stroj_dla(zrodlo) or stroj_dom
        if wlasny:
            return wlasny, None
        bib = _stroj_z_biblioteki(slug, ust, log, uwaga_biblioteki)
        return (bib["plik"], bib) if bib else (None, None)

    for zrodlo in nowe:
        _sprawdz_stop(stop)
        nazwa = os.path.splitext(os.path.basename(zrodlo))[0]
        if czekaj_na_kopiowanie and _plik_sie_zmienia(zrodlo):
            log(f"[CZEKAM] {os.path.basename(zrodlo)} jeszcze sie kopiuje - nastepnym razem")
            wynik["pominiete"].append(os.path.basename(zrodlo))
            continue
        try:
            inf = klatki.info(zrodlo)
        except Exception as e:
            log(f"[POMIJAM] {os.path.basename(zrodlo)}: {e}")
            wynik["pominiete"].append(os.path.basename(zrodlo))
            continue
        max_s = max_sekund_rolki(ust)
        if ust.get("dziel_dlugie") and inf["czas"] > max_s + 0.5:
            try:
                kawalki = _potnij_dlugi(slug, zrodlo, inf, log, max_s=max_s)
            except Exception as e:
                log(f"[UWAGA] {nazwa}: nie udalo sie pociac ({e}) - robie z pierwszych {MAX_SEKUND_ZRODLA} s")
                kawalki = []
            if kawalki:
                audio_oryg = baza.audio_dla_zrodla(zrodlo)
                for i, kawalek in enumerate(kawalki, 1):
                    try:
                        inf_k = klatki.info(kawalek)
                    except Exception:
                        inf_k = dict(inf, czas=max_s)
                    folder_k = os.path.join(folder_klatek, _bezpieczna_nazwa(f"{nazwa}_cz{i:02d}"))
                    try:
                        klatki.wytnij(kawalek, folder_k, ile=ile_klatek)
                        klatki.arkusz(kawalek, os.path.join(folder_k, "arkusz.jpg"), ile=6)
                    except Exception as e:
                        log(f"[UWAGA] klatki dla {nazwa} cz.{i}: {e}")
                    stroj_k, bib_k = stroj_klipu(zrodlo)       # kazdy kawalek = osobna rolka (z biblioteki: kolejny stroj)
                    prompt_k = prompt_b if stroj_k else prompt_a
                    opis = f"{os.path.basename(zrodlo)} cz. {i}/{len(kawalki)} ({inf_k['czas']}s, {inf_k['szer']}x{inf_k['wys']})"
                    pid = baza.dodaj_pomysl(slug, opis, prompt_k, zrodlo=kawalek, klatki=folder_k, info_zrodla=inf_k, stroj=stroj_k,
                                            **({"stroj_bib": bib_k["id"]} if bib_k else {}))
                    if audio_oryg and i == 1:
                        baza.aktualizuj_pomysl(slug, pid, audio=audio_oryg)
                    wynik["nowe"].append(pid)
                    if not prompt_k:
                        wynik["bez_promptu"].append(pid)
                    _zdarzenie(log, slug, "info", f"#{pid}  {opis}" + (f"   [B: stroj z biblioteki: {bib_k['nazwa']}]" if bib_k else ""),
                               pomysl=pid)
                continue
        folder = os.path.join(folder_klatek, _bezpieczna_nazwa(nazwa))
        try:
            klatki.wytnij(zrodlo, folder, ile=ile_klatek)
            klatki.arkusz(zrodlo, os.path.join(folder, "arkusz.jpg"), ile=6)
        except Exception as e:
            log(f"[UWAGA] klatki dla {nazwa}: {e}")

        stroj, bib = stroj_klipu(zrodlo)
        if stroj:
            prompt = prompt_b
            wariant = (f"B: stroj z biblioteki: {bib['nazwa']}" if bib else "B: stroj ze zdjecia " + os.path.basename(stroj))
            if ust.get("prompt_auto") and not prompt_b:
                log(f"[UWAGA] {nazwa}: jest zdjecie stroju, ale prompt_stroj (wariant B) jest pusty.")
        else:
            prompt = prompt_a
            wariant = "A: stroj z filmu"
        opis = f"{os.path.basename(zrodlo)} ({inf['czas']}s, {inf['szer']}x{inf['wys']})"
        pid = baza.dodaj_pomysl(slug, opis, prompt, zrodlo=zrodlo, klatki=folder, info_zrodla=inf, stroj=stroj,
                                **({"stroj_bib": bib["id"]} if bib else {}))
        wynik["nowe"].append(pid)
        if not prompt:
            wynik["bez_promptu"].append(pid)
        audio = baza.audio_dla_zrodla(zrodlo)
        _zdarzenie(log, slug, "info", f"#{pid}  {opis}   [{wariant}]" + ("" if prompt else "   (BEZ PROMPTU)")
                   + (f"   + glos {os.path.basename(audio)}" if audio else ""), pomysl=pid)
        log(f"      klatki: {os.path.join(folder, 'arkusz.jpg')}")
    if wynik["bez_promptu"]:
        log("\nBez promptu: " + ", ".join(f"#{i}" for i in wynik["bez_promptu"])
            + " -> obejrzyj arkusz.jpg i wpisz: python fabryka.py prompt <id> \"...\"")
    log("Dalej: python fabryka.py koszt, potem python fabryka.py generuj")
    return wynik


def cmd_skanuj(args):
    skanuj(_slug(args.modelka), ile_klatek=args.ile)
    return 0


def _stroj_dla(zrodlo):
    """Zdjecie stroju sparowane z klipem: <nazwa>.stroj.<ext> albo <nazwa>_stroj.<ext> obok filmiku."""
    folder, plik = os.path.split(zrodlo)
    stem = os.path.splitext(plik)[0]
    for wzor in (f"{stem}.stroj", f"{stem}_stroj"):
        for ext in baza.ROZSZERZENIA_OBRAZU:
            p = os.path.join(folder, wzor + ext)
            if os.path.isfile(p):
                return p
    return None


def _stroj_z_biblioteki(slug, ust, log, uwaga=None):
    """stroj_swap="biblioteka": stroj ze stroje_biblioteka/ dla NOWEGO klipu (tylko ze zdjeciem - wariant B bierze stroj ze zdjecia;
    wazone losowanie + rotacja, baza.losuj_stroj_biblioteki). None = "z_filmu", pusta biblioteka albo persona bez promptu B
    (wtedy klip idzie wariantem A - jedna uwaga w logu na przebieg)."""
    if (ust.get("stroj_swap") or "biblioteka") != "biblioteka":
        return None
    if not baza.prompt_stroj(slug):
        if uwaga is not None and not uwaga:
            uwaga.append(1)
            log("[UWAGA] stroje z biblioteki: persona nie ma promptu B (stroj ze zdjecia) - nowe klipy ida ze strojem z filmu")
        return None
    return baza.losuj_stroj_biblioteki(slug, tylko_ze_zdjeciem=True)


# ---------------- prompt ----------------

def cmd_prompt(args):
    slug = _slug(args.modelka)
    tekst = args.tekst
    if tekst == "-":
        tekst = sys.stdin.read().strip()
    baza.aktualizuj_pomysl(slug, args.id, prompt_higgsfield=tekst)
    print(f"#{args.id} prompt zapisany ({len(tekst)} znakow).")
    return 0


# ---------------- budowanie zlecenia ----------------

DOSTAWCA_Z_PROMPTU = "higgsfield"     # rolki z promptu (scenariusz.py) ida zawsze przez CLI Higgsfield, niezaleznie od dostawcy persony


def z_promptu(p):
    """Rolka z promptu (zakladka 'Z promptu', scenariusz.py): bez filmiku, prompt i lista zdjec zamrozone w pomysle."""
    return isinstance(p, dict) and p.get("typ") == "prompt"


def _zlecenie_z_promptu(slug, p, do_wyceny=False):
    """Zlecenie rolki z promptu: model/tryb/dlugosc/rozdzielczosc/zdjecia z pomyslu (p['z_promptu']), nie z ustawien persony.
    3.5: z pierwsza klatka (z_promptu.klatka) - start_image = gotowa klatka (p['klatka']['plik']), tryb wideo z klatka (Seedance
    omni_reference + zdjecia persony; stare rolki Wan/Gemini - sama klatka, bez zdjec). 3.5.2 tryb tla (Wan/Gemini): BEZ
    start_image - image_references = zdjecia persony (+ stroj) + gotowe zdjecie tla jako OSTATNI obraz (swiezy upload, jego id
    = klatka_id do odnalezienia joba). do_wyceny=True: bez klatki/tla (cena ta sama - `generate cost` 2026-10-08: 70 kr z
    start_image i bez, Wan 30 kr z tlem i bez; Gemini image-to-video bez klatki by nie przeszedl walidacji)."""
    zp = p.get("z_promptu") or {}
    z = {
        "slug": slug, "pomysl": p.get("id"), "prompt": p.get("prompt_higgsfield") or "", "video": None, "video_czas": None,
        "images": [o for o in (zp.get("obrazy") or []) if o], "duration": int(zp.get("dlugosc") or 10),
        "aspect_ratio": "9:16", "resolution": zp.get("rozdzielczosc") or "720p", "model": zp.get("model") or "seedance_2_5",
        "mode": zp.get("mode"), "generate_audio": zp.get("generate_audio"), "soul_id": "",
        "parametry": dict(zp.get("parametry") or {}), "dostawca": DOSTAWCA_Z_PROMPTU, "yapper": {}, "wavespeed": {},
    }
    kl = zp.get("klatka") if isinstance(zp.get("klatka"), dict) else None
    if kl and not do_wyceny:
        import pierwsza_klatka
        plik = pierwsza_klatka.gotowa(p)
        if plik and pierwsza_klatka.tryb_tla(kl):
            z["images"] = z["images"] + [plik]          # tlo = ostatni obraz (prompt: "the last reference image")
            z["tlo_swieze"] = plik
            z["mode"] = kl.get("mode_wideo")
        elif plik:
            z["start_image"] = plik
            z["mode"] = kl.get("mode_wideo")
            if not kl.get("refy_w_wideo"):
                z["images"] = []
    return z


def zlecenie(slug, p, ust=None, do_wyceny=False):
    """Generyczne zlecenie dla dostawcy (dostawcy/__init__.py opisuje pola)."""
    if z_promptu(p):
        return _zlecenie_z_promptu(slug, p, do_wyceny=do_wyceny)
    ust = ust or baza.ustawienia_modelki(slug)
    ma_zrodlo = bool(p.get("zrodlo"))
    dur = ust.get("duration")
    if dur is None and p.get("info_zrodla"):
        dur = int(round(p["info_zrodla"].get("czas") or 0)) or None
    # kolejnosc obrazow = numeracja @[Image N] w prompcie: najpierw referencje persony, strój jako OSTATNI
    obrazy = list(baza.sciezki_referencji(slug))
    if p.get("stroj") and os.path.isfile(p["stroj"]):
        obrazy.append(p["stroj"])
    z = {
        "slug": slug,
        "pomysl": p.get("id"),
        "prompt": p.get("prompt_higgsfield") or "",
        "video": p["zrodlo"] if ma_zrodlo else None,
        "video_czas": czas_klipu(p),
        "images": obrazy,
        "duration": int(dur) if dur else None,
        "aspect_ratio": ust.get("aspect_ratio"),
        "resolution": rozdzielczosc_rolki(p, ust),      # <= 8 s -> 1080p, dluzszy -> 720p (oba dostawcy)
        "model": ust.get("model"),
        "mode": ust.get("mode") if ma_zrodlo else (ust.get("mode_bez_zrodla") or ust.get("mode")),
        "generate_audio": ust.get("generate_audio"),
        "soul_id": ust.get("soul_id") or "",
        "parametry": dict(ust.get("dodatkowe_parametry") or {}),
        "dostawca": ust.get("dostawca") or "higgsfield",
        "yapper": dict(ust.get("yapper") or {}),
        "wavespeed": dict(ust.get("wavespeed") or {}),
    }
    # sylwetka persony (profil.sylwetka) doklejana na koncu promptu persony - pliki promptow usera zostaja nietkniete
    syl = sylwetka_persony(slug)
    z["prompt"] = doklej_sylwetke(z["prompt"], syl)[0]
    # yapper (Wan): wlasny krotki prompt persony (yapper.prompt albo prompty/wan.txt) - bez @[Image N], max 5000 znakow
    # (sylwetka tylko gdy sie miesci - skrocona do 1. zdania albo wcale; sprawdz_prompt_wan o tym mowi)
    z["yapper"]["prompt"] = doklej_sylwetke(baza.prompt_wan(slug), syl, LIMIT_PROMPTU_WAN)[0]
    # WaveSpeed: Seedance dostaje prompt persony (z["prompt"], @[Image N] -> @Image N), modele Wan - ten sam prompt Wan
    z["wavespeed"]["prompt_wan"] = z["yapper"]["prompt"]
    return z


def _zlecenie(slug, p, ust):
    """(model, params, media) dla CLI Higgsfield - zachowane dla testow i --dry-run."""
    import dostawcy.higgsfield as dh
    return dh.przygotuj(zlecenie(slug, p, ust))


def cmd_wgraj(args):
    """Wgrywa referencje (i stroje) raz; potem koszt/generuj uzywaja UUID-ow zamiast slac 30 MB za kazdym razem."""
    slug = _slug(args.modelka)
    pliki = list(baza.sciezki_referencji(slug))
    stroje = baza.folder_strojow(slug)
    pliki += [os.path.join(stroje, n) for n in sorted(os.listdir(stroje)) if n.lower().endswith(baza.ROZSZERZENIA_OBRAZU)]
    pliki += [s["plik"] for s in baza.stroje_biblioteki(tylko_ze_zdjeciem=True)]     # wspolna biblioteka strojow (cache per persona)
    if not pliki:
        print("Brak referencji/strojow do wgrania.")
        return 1
    nowe = 0
    for pl in pliki:
        if baza.upload_id(slug, pl) and not args.od_nowa:
            print(f"  ok   {os.path.basename(pl)} (juz wgrane)")
            continue
        try:
            dane = hf.upload(pl)
        except hf.HiggsfieldBlad as e:
            print(f"  BLAD {os.path.basename(pl)}: {e}")
            continue
        baza.zapisz_upload_id(slug, pl, dane["id"])
        nowe += 1
        print(f"  +    {os.path.basename(pl)} -> {dane['id']}")
    print(f"wgrane: {nowe} nowych, {len(pliki)} razem")
    return 0


def kandydaci(slug, ids=None, limit=None, log=None):
    """Pomysly do policzenia/generacji: 'nowy' z promptem (albo wskazane id - takze 'blad'). Rolki z promptu (typ 'prompt')
    tylko wskazane po id - zbiorcze 'Zrob rolki', CLI bez --id i autopilot ich nie ruszaja (kazda ma wlasna, potwierdzona cene)."""
    log = log or _log
    ust = baza.ustawienia_modelki(slug)
    wymaga_wideo = ust.get("mode") in ("video_edit", "video_extension") and not ust.get("mode_bez_zrodla")
    if ids:
        lista = []
        for pid in ids:
            p = baza.pomysl(slug, int(pid))
            # ValueError (nie SystemExit): panel i autopilot lapia to jak zwykly blad, CLI drukuje [BLAD]
            if p["status"] not in ("nowy", "blad"):
                raise ValueError(f"#{p['id']} ma status {p['status']} - generuje tylko nowy/blad.")
            if wymaga_wideo and not p.get("zrodlo") and not z_promptu(p):
                raise ValueError(f"#{p['id']} nie ma filmiku zrodlowego, a tryb {ust['mode']} go wymaga "
                                 f"(wrzuc plik do wrzutni i zrob skanuj, zmien mode albo ustaw mode_bez_zrodla w Persona -> Generowanie).")
            if not p.get("prompt_higgsfield"):
                raise ValueError(f"#{p['id']} nie ma promptu.")
            lista.append(p)
        return lista
    lista, pominiete = [], []
    for p in baza.lista_pomyslow(slug, "nowy"):
        if not p.get("prompt_higgsfield") or z_promptu(p):
            continue
        if wymaga_wideo and not p.get("zrodlo"):
            pominiete.append(p["id"])
            continue
        lista.append(p)
    if pominiete:
        log(f"pomijam bez filmiku zrodlowego (tryb {ust['mode']}, mode_bez_zrodla puste): " + ", ".join(f"#{i}" for i in pominiete))
    return lista[:limit] if limit else lista


def _kandydaci(slug, args):
    pid = getattr(args, "id", None)
    return kandydaci(slug, ids=[pid] if pid else None, limit=getattr(args, "limit", None))


# ---------------- koszt ----------------

def koszt(slug, ids=None, limit=None, log=None):
    """Szacunek kredytow (zapisuje p['koszt']). Zwraca {"razem": n, "pozycje": [(id, koszt|None, dostawca)]}.
    Rolka, ktora po NSFW zaczyna od zapasu (krok_startowy > 0, "Ponow"), jest wyceniana u dostawcy zapasu (darmowy dryRun yappera)."""
    log = log or _log
    ust = baza.ustawienia_modelki(slug)
    d = dostawcy.dostawca(ust.get("dostawca"))
    lista = kandydaci(slug, ids, limit, log)
    wynik = {"razem": 0, "pozycje": [], "dostawca": d.NAZWA}
    if not lista:
        log("Nic do policzenia (brak pomyslow 'nowy' z promptem).")
        return wynik
    for p in lista:
        krok = _krok_startowy(p, ust)
        if krok:
            try:
                zapas = _przygotuj_zapas(slug, p, ust, krok, log, tylko_wycena=True)
            except _BezZapasu as e:
                log(f"#{p['id']}: zapas po NSFW - {e}")
                zapas = None
            if not zapas:
                wynik["pozycje"].append((p["id"], None, _dostawca_kroku(ust, krok)))
                continue
            dk, z, k = zapas
            log(f"#{p['id']}: {dostawcy.kwota(k, dk.NAZWA)} ({dk.NAZWA} {_model(dk, z)}, zapas po NSFW)   {p['opis']}")
            wynik["pozycje"].append((p["id"], k, dk.NAZWA))
            wynik["dostawca"] = dk.NAZWA
            wynik["razem"] += k or 0
            continue
        dp = dostawcy.dostawca(DOSTAWCA_Z_PROMPTU) if z_promptu(p) else d     # rolka z promptu: zawsze Higgsfield
        try:
            z = zlecenie(slug, p, ust, do_wyceny=True)
            k = dp.koszt(z)
            if z_promptu(p) and k is not None:
                import pierwsza_klatka          # 3.5: + pierwsza klatka, gdy jeszcze jej nie ma
                k = pierwsza_klatka.wycena_rolki(p, k)[0]
        except dostawcy.BladDostawcy as e:
            log(f"#{p['id']}: [BLAD] {e}")
            wynik["pozycje"].append((p["id"], None, dp.NAZWA))
            continue
        wynik["razem"] += k or 0
        wynik["pozycje"].append((p["id"], k, dp.NAZWA))
        baza.aktualizuj_pomysl(slug, p["id"], koszt=k, resolution=z["resolution"])
        skad = dp.opis_wyceny() if hasattr(dp, "opis_wyceny") else ""
        log(f"#{p['id']}: {dostawcy.kwota(k, dp.NAZWA)} ({z['resolution']}{', ' + skad if skad else ''})   {p['opis']}")
    log(f"razem: {dostawcy.kwota(wynik['razem'], wynik['dostawca'])}")
    return wynik


def _dostawca_kroku(ust, krok):
    """Nazwa dostawcy kroku zapas_nsfw nr `krok` (1..) - do pozycji wyceny panelu."""
    kroki = ust.get("zapas_nsfw") or []
    opis = kroki[krok - 1] if 0 < krok <= len(kroki) and isinstance(kroki[krok - 1], dict) else {}
    return (opis.get("dostawca") or "yapper").strip().lower()


def cmd_koszt(args):
    slug = _slug(args.modelka)
    koszt(slug, ids=[args.id] if args.id else None, limit=args.limit)
    return 0


# ---------------- generacja ----------------
# Jedna rolka = proba (albo kilka - zapas po NSFW). Proba: znacznik w_toku w pomysle -> wyslanie BEZ czekania (generate create /
# POST /processes) -> job_id zapisany od razu -> odpytywanie TEGO joba (0 kr). Blad sieci, timeout, STOP, zamkniety panel = job
# dalej sie robi i jest dokanczany pozniej (wznow_w_toku) - nigdy nie wysylamy drugiego. Ponowne WYSLANIE (powtorki) tylko gdy
# job na pewno nie powstal. Koszt = z joba (wycena / creditsUsed), nie z roznicy salda.

ODSTEP_ODPYTYWANIA_S = 10    # co ile sprawdzamy job (generate get / GET /processes/{id}) - 0 kr
MAX_GODZIN_W_TOKU = 24       # job, ktory po tylu godzinach dalej "trwa", konczymy jako blad (bez wysylania nowego)
CZAS_NA_WYSLANIE_S = 180     # yapper (Idempotency-Key): po tylu s bez procesu wraca do kolejki - ten sam klucz = ten sam proces
OKNO_NIEPEWNEGO_WYSLANIA_S = 60 * 60   # Higgsfield (bez klucza): create zwrocil blad PO wyslaniu / wysylanie przerwane -
                                       # tyle czekamy, az job pojawi sie na `generate list` (dluzej niz najwolniejszy Seedance);
                                       # potem NIE wysylamy drugi raz, tylko rolka 'nie wyszla' z prosba o sprawdzenie w apce
POWODY_ZAPASU = ("nsfw", "ip")
SPRAWDZ_W_APCE = ("Sprawdz w apce Higgsfield (lista generacji), czy ta rolka nie powstala - jesli tak, pobierz ja stamtad; "
                  "jesli nie - kliknij 'Sprobuj jeszcze raz'.")
_SPRAWDZ_W_APCE_DOSTAWCY = {
    "yapper": ("Sprawdz w apce yapper.so (lista procesow), czy ta rolka nie powstala - jesli tak, pobierz ja stamtad; "
               "jesli nie - kliknij 'Sprobuj jeszcze raz'."),
    "wavespeed": ("Sprawdz w apce WaveSpeed (wavespeed.ai -> dashboard -> historia zadan), czy ta rolka nie powstala - jesli tak, "
                  "pobierz ja stamtad; jesli nie - kliknij 'Sprobuj jeszcze raz'."),
}


def sprawdz_w_apce(dostawca=None):
    """Prosba 'sprawdz w apce, czy rolka nie powstala' dla dostawcy (Higgsfield - SPRAWDZ_W_APCE)."""
    return _SPRAWDZ_W_APCE_DOSTAWCY.get((dostawca or "higgsfield").strip().lower(), SPRAWDZ_W_APCE)


BRAK_LIMITU_WAVESPEED = ("dzienny limit WaveSpeed nie jest ustawiony - bez niego fabryka nic tam nie wyda. Ustaw go: panel -> "
                         "Ustawienia -> Limity kredytow (tryb pelny) -> 'WaveSpeed: nie wiecej niz ... $ dziennie' albo "
                         "`python fabryka.py budzet max_kredyty_dziennie=1000 --dostawca wavespeed` (w centach: 1000 = $10)")
_WYSYLANIE = set()           # (slug, pid) w trakcie wysylania - wtedy panelu nie wolno zamknac (osierocony job = podwojna oplata)
_WYSYLANIE_LOCK = threading.Lock()


class JobTrwa(Exception):
    """Czekanie przerwane (limit czasu albo nie wiadomo, czy job powstal) - pomysl zostaje w_toku, dokonczymy go pozniej."""


class _BezZapasu(Exception):
    """Zapas u tego dostawcy jest teraz niemozliwy (brak/wyczerpany limit dzienny, saldo, odmowa) - pomijamy jego kroki
    (inny dostawca w zapas_nsfw dalej moze sprobowac). wszystkie=True: zaden krok nie ma sensu (np. stroj ze zdjecia)."""

    def __init__(self, tekst, wszystkie=False):
        super().__init__(tekst)
        self.wszystkie = wszystkie


def trwa_wysylanie():
    """Czy fabryka wlasnie wysyla rolke do dostawcy (upload + create). Panel nie zamyka sie w tym oknie."""
    with _WYSYLANIE_LOCK:
        return bool(_WYSYLANIE)


def bezpiecznik(ust, dostawca="higgsfield"):
    """(min_kredyty, max_kredyty_na_rolke) dla dostawcy. yapper ma wlasne (kredyty yapper to inna skala), WaveSpeed tez
    (centy USD: wavespeed.min_kredyty / wavespeed.max_kredyty_na_rolke, domyslnie 0 / 400 = $4.00)."""
    if dostawca in ("yapper", "wavespeed"):
        y = ust.get(dostawca) or {}
        return int(y.get("min_kredyty") or 0), int(y.get("max_kredyty_na_rolke") or 400)
    return int(ust["min_kredyty"]), int(ust["max_kredyty_na_rolke"])


def powod_odrzucenia(status, blad=""):
    """Klasa niepowodzenia generacji: 'nsfw' (filtr tresci Higgsfield/Seedance), 'ip' (znana postac/marka),
    'inny' albo None (nic nie wiadomo)."""
    s, b = (status or "").lower(), (blad or "").lower()
    if s in ("nsfw", "moderated") or any(x in b for x in ("nsfw", "moderat", "content policy", "content_policy", "policy_violation",
                                                          "safety", "visual restriction", "flagged")):
        return "nsfw"
    if s == "ip_detected" or any(x in b for x in ("ip_detected", "copyright", "celebrity", "public figure")):
        return "ip"
    return "inny" if (s or b) else None


PODPOWIEDZ_NSFW = ("Filtr tresci Higgsfield/Seedance sprawdza WSZYSTKO naraz: filmik zrodlowy, zdjecia persony, zdjecie stroju "
                   "i prompt - niewinny filmik odpada, gdy np. zdjecie stroju ma przeswitujaca siatke/koronke, bielizne albo duzo skory. "
                   "Panel -> Pomoc -> 'Filtr NSFW' pokazuje, co u Ciebie moze go uruchamiac.")

# Slowa w promptach, ktore filtr tresci (Higgsfield + Seedance) blokuje najczesciej - nawet przy niewinnym filmiku.
SLOWA_RYZYKOWNE = ("sexy", "seductive", "sensual", "erotic", "erotica", "lingerie", "underwear", "bikini", "swimsuit", "nude", "naked",
                   "topless", "see-through", "see through", "sheer", "transparent", "mesh", "fishnet", "cleavage", "bra", "panties",
                   "thong", "breast", "breasts", "boobs", "nipple", "nipples", "butt", "ass", "booty", "twerk", "twerking", "provocative",
                   "wet t-shirt", "lace", "latex", "bodysuit", "strip", "stripper", "lick", "licking", "moan", "kiss", "bedroom",
                   "shower", "bath", "lap dance", "pole dance", "hot girl", "curvy", "curves", "tight dress", "mini skirt", "skimpy")


def _odmiana(n, jeden, kilka, duzo):
    """'1 rolke', '3 rolki', '7 rolek' - polska liczba mnoga."""
    n = int(n)
    if n == 1:
        forma = jeden
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        forma = kilka
    else:
        forma = duzo
    return f"{n} {forma}"


def wskazowki_nsfw(slug, dni=14):
    """Czemu Higgsfield odrzuca rolki persony jako NSFW: ile odrzucen (w ogole / ostatnie `dni`), ryzykowne slowa w promptach
    A/B/zdjec i proste wskazowki po polsku. Zwraca {"odrzucone", "odrzucone_ostatnio", "slowa": {A,B,zdjecia}, "wskazowki": [...]}."""
    from datetime import datetime, timedelta
    granica = (datetime.now() - timedelta(days=dni)).strftime("%Y-%m-%d")
    odrzucone = [p for p in baza.lista_pomyslow(slug)
                 if p.get("powod") == "nsfw" or (p.get("status") == "blad" and "nsfw" in (p.get("notatki") or "").lower())]
    ostatnio = [p for p in odrzucone if baza.dzien_lokalny(p.get("zaktualizowano") or p.get("utworzono")) >= granica]
    ust = baza.ustawienia_modelki(slug)
    teksty = {"A": baza.prompt_bazowy(slug), "B": baza.prompt_stroj(slug), "zdjecia": "\n".join(baza.prompty_zdjec(slug)),
              "sylwetka": sylwetka_persony(slug)}
    slowa = {}
    for nazwa, tekst in teksty.items():
        t = f" {re.sub(r'[^a-z0-9 -]+', ' ', (tekst or '').lower())} "
        slowa[nazwa] = [s for s in SLOWA_RYZYKOWNE if f" {s} " in t or f" {s}s " in t]
    wskazowki = []
    if ostatnio:
        wskazowki.append(f"Filtr odrzucil {_odmiana(len(ostatnio), 'rolke', 'rolki', 'rolek')} w ostatnich {dni} dniach "
                         f"(razem {_odmiana(len(odrzucone), 'rolke', 'rolki', 'rolek')}). Kredyty za odrzucone wracaja.")
    for nazwa, lista in slowa.items():
        if lista:
            gdzie = {"A": "prompcie A (stroj z filmu)", "B": "prompcie B (stroj ze zdjecia)", "zdjecia": "promptach zdjec",
                     "sylwetka": "sylwetce persony (doklejana do kazdej rolki)"}[nazwa]
            wskazowki.append(f"W {gdzie} sa slowa, ktore filtr lubi blokowac: {', '.join(lista)}. Zamien je na neutralne opisy "
                             f"(np. 'black top' zamiast 'mesh top', 'outfit from the image' zamiast opisu materialu).")
    stroje = [n for n in os.listdir(baza.folder_strojow(slug)) if n.lower().endswith(baza.ROZSZERZENIA_OBRAZU)]
    if stroje or ust.get("stroj_domyslny"):
        wskazowki.append("Zdjecia strojow lecą do modelu razem z filmikiem - siatka, koronka, przeswity, bielizna albo duzo skory na "
                         "zdjeciu stroju odrzucaja CALA rolke. Do rolek dawaj stroje 'bezpieczne', a odwazniejsze zostaw na zdjecia.")
    wskazowki.append("Zdjecia persony w referencje/: najlepiej twarz + sylwetka w zwyklym ubraniu, bez bielizny/kostiumu kapielowego "
                     "- te same zdjecia ida do kazdej rolki, wiec jedno ryzykowne psuje wszystkie.")
    wskazowki.append("Filmik zrodlowy: taniec z bliskim kontaktem, skapy stroj, prysznic/lozko, bron lub krew w kadrze - filtr nie patrzy "
                     "na kontekst. Sprobuj innego fragmentu albo krotszego ujecia (potnij w panelu: dziel_dlugie).")
    wskazowki.append("Fabryka nie powtarza odrzuconej rolki na tym samym modelu (filtr dalby to samo). Z wlaczonym zapasem po NSFW "
                     "(yapper, Wan 3.0) probuje tam - inny model, inny filtr. Recznie: 'Sprobuj jeszcze raz'.")
    wskazowki.append("Jesli masz pewnosc, ze to pomylka filtra: Higgsfield -> Help Center -> zglos false positive (oddaja kredyty, "
                     "ale decyzji filtra nie cofaja).")
    return {"odrzucone": len(odrzucone), "odrzucone_ostatnio": len(ostatnio), "dni": dni, "slowa": slowa, "wskazowki": wskazowki}


def _model(d, z):
    """Nazwa modelu proby: Higgsfield - job_type (seedance_2_5), yapper - yapper.model (wan-3.0-prime), WaveSpeed -
    wavespeed.model (bytedance/seedance-2.5/video-edit-turbo)."""
    if d.NAZWA == "yapper":
        return (z.get("yapper") or {}).get("model")
    if d.NAZWA == "wavespeed":
        return (z.get("wavespeed") or {}).get("model") or getattr(d, "MODEL_DOMYSLNY", "")
    return z.get("model") or "seedance_2_5"


def _teraz_iso():
    return datetime.now(timezone.utc).isoformat()


def _wiek_s(iso):
    """Ile sekund temu (czas ISO z markera); None, gdy nie da sie odczytac."""
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds()


def _spij(sekundy, stop):
    """Pauza miedzy odpytaniami; STOP przerywa ja od razu."""
    for _ in range(max(1, int(sekundy))):
        if stop is not None and stop.is_set():
            return
        time.sleep(1)


_KODY_TRWALE = ("insufficient_credits", "invalid_request", "validation_error", "missing_scope", "idempotency_conflict",
                "unsupported_filter_combination", "not_found")
_TEKSTY_TRWALE = ("nie jest zalogowane", "workspace", "nie wybrano modelu", "insufficient", "not enough credits", "za malo kredytow",
                  "invalid_request", "invalid request", "validation", "invalid param", "invalid value", "unknown flag",
                  "required flag", "brak klucza", "odmawia startu", "skladnie @[image", "znakow, a model przyjmuje")


def _blad_trwaly(e):
    """Blad, ktory znaczy, ze job NIE powstal i powtorka nic nie da (klucz, logowanie, brak kredytow, zle zapytanie,
    walidacja) - bez powtorek i bez czekania na job."""
    if e is None:
        return False
    if isinstance(e, dostawcy.BrakKlucza):
        return True
    if getattr(e, "status", None) in (400, 401, 402, 403, 404, 409, 422):
        return True
    if getattr(e, "kod", "") in _KODY_TRWALE:
        return True
    t = str(e).lower()
    return any(x in t for x in _TEKSTY_TRWALE)


def _krok_startowy(p, ust):
    """Od ktorego kroku zaczac rolke: 0 = dostawca persony; 1.. = kroki zapas_nsfw (np. 'Ponow' po NSFW).
    Rolki z promptu nie maja zapasu (prompt Seedance z <<<image_N>>> nie pasuje do Wan)."""
    if z_promptu(p):
        return 0
    try:
        k = int(p.get("krok_startowy") or 0)
    except (TypeError, ValueError):
        k = 0
    return k if 0 < k <= len(ust.get("zapas_nsfw") or []) else 0


def _numer_proby(p, dostawca, model):
    """Kolejny numer proby tego modelu dla pomyslu (do Idempotency-Key) - licza sie tylko proby, ktore dostaly job."""
    return 1 + sum(1 for w in (p.get("proby") or []) if w.get("dostawca") == dostawca and w.get("model") == model and w.get("job_id"))


def _wyslij(slug, p, d, z, k, krok, ust, log):
    """Wysyla jedna probe i zapisuje job_id w pomysle (status w_toku). Ponowne wyslanie TYLKO gdy job na pewno nie powstal:
    yapper - ten sam Idempotency-Key oddaje ten sam proces; Higgsfield - najpierw szukamy joba na `generate list` po wgranym
    filmiku. Zwraca wynik zlec() z job_id (albo pseudo-wynik odrzucenia NSFW/IP przy wysylaniu). Rzuca BladDostawcy
    (nie wyslano mimo powtorek) albo JobTrwa (nie wiadomo, czy job powstal - sprawdzimy przy nastepnym przebiegu)."""
    pid = p["id"]
    model = _model(d, z)
    klucz = f"rolki-{slug}-{pid}-{model}-{_numer_proby(p, d.NAZWA, model)}"
    ile = 1 + max(0, int(ust.get("powtorki") or 0))
    for proba in range(1, ile + 1):
        baza.zacznij_w_toku(slug, pid, dostawca=d.NAZWA, model=model, krok=krok, klucz=klucz, koszt=k,
                            resolution=z.get("resolution"))

        def znacznik(**pola):
            # dostawca wola to tuz PRZED nieodwracalnym wyslaniem (wszystkie pliki juz wgrane): od tej chwili job MOZE powstac
            if pola.get("wysylam"):
                pola.setdefault("wysylam_od", _teraz_iso())
            baza.ustaw_w_toku(slug, pid, **pola)
        with _WYSYLANIE_LOCK:
            _WYSYLANIE.add((slug, pid))
        try:                                    # okno "wysylania" (panel sie nie zamyka) trwa az do zapisu job_id
            try:
                job = d.zlec(z, klucz=klucz, znacznik=znacznik, log=log)
                blad = None
            except dostawcy.BladDostawcy as e:
                job, blad = None, e
            if job is None:
                powod = powod_odrzucenia("", str(blad))
                if powod in POWODY_ZAPASU:
                    # odrzucone juz przy wysylaniu (np. prompt) - powtorka da to samo
                    return {"job_id": None, "status": "nsfw" if powod == "nsfw" else "ip_detected", "urls": [], "blad": str(blad),
                            "surowe": {}}
                marker = baza.pomysl(slug, pid).get("w_toku") or {}
                if marker.get("wysylam") and not getattr(d, "IDEMPOTENTNY", False) and not _blad_trwaly(blad):
                    # Higgsfield: create MOGL dotrzec mimo bledu - szukamy joba; nie ma -> JobTrwa (NIGDY drugie wysylanie)
                    job = _szukaj_wyslanego(slug, p, d, z, model, klucz, marker, blad, log)
            if job is not None:
                baza.ustaw_w_toku(slug, pid, job_id=job["job_id"], etap="czeka", wyslano=_teraz_iso())
                return job
        finally:
            with _WYSYLANIE_LOCK:
                _WYSYLANIE.discard((slug, pid))
        # job nie powstal (wyslanie nie ruszylo albo blad trwaly): znacznik won, pomysl wraca do stanu sprzed proby
        baza.aktualizuj_pomysl(slug, pid, status="nowy", w_toku=None)
        log(f"#{pid}: wyslanie nie wyszlo ({str(blad)[:200]})")
        if _blad_trwaly(blad) or proba >= ile:
            raise blad
        log(f"#{pid}: job nie powstal - wysylam jeszcze raz za 10 s (proba {proba + 1}/{ile})")
        time.sleep(10)
    raise dostawcy.BladDostawcy("wyslanie nie wyszlo")


def _prompt_wyslany(slug, p, ust):
    """Prompt, ktory poszedl do dostawcy (prompt pomyslu + doklejka sylwetki) - do szukania joba po tresci promptu."""
    try:
        return zlecenie(slug, p, ust).get("prompt") or p.get("prompt_higgsfield")
    except Exception:
        return p.get("prompt_higgsfield")


def _pomin_przy_szukaniu(p, d, marker):
    """Joby, ktorych `znajdz` nie moze uznac za job tej proby: wczesniejsze proby pomyslu, a gdy nie ma wgranego filmiku
    (rolka z promptu - szukamy po tresci promptu i czasie) - takze wszystkie joby znane fabryce (inny pomysl z tym samym
    promptem nie podepnie cudzego joba)."""
    pomin = [w.get("job_id") for w in (p.get("proby") or []) if w.get("job_id")]
    if not (marker or {}).get("wideo_id"):
        pomin += sorted(baza.znane_job_id(d.NAZWA))
    return pomin


def _szukaj_wyslanego(slug, p, d, z, model, klucz, marker, blad, log):
    """Higgsfield: `generate create` zwrocil blad, ale znacznik 'wysylam' juz byl - job MOGL powstac. Sprawdzamy liste
    (po 5 s i po kolejnych 15 s); znaleziony = TEN job. Nie ma go -> JobTrwa: NIE wysylamy drugi raz (lista bywa opozniona),
    rolka zostaje w toku i wznow_w_toku szuka dalej przez OKNO_NIEPEWNEGO_WYSLANIA_S, potem prosi o sprawdzenie w apce."""
    pid = p["id"]
    for pauza in (5, 15):
        time.sleep(pauza)
        try:
            znaleziony = d.znajdz(model, wideo_id=marker.get("wideo_id"), prompt=z.get("prompt"),
                                  od=marker.get("wysylam_od") or marker.get("od"), klucz=klucz,
                                  pomin=_pomin_przy_szukaniu(p, d, marker), klatka_id=marker.get("klatka_id"))
        except dostawcy.BladDostawcy as e:
            log(f"#{pid}: nie moge sprawdzic listy jobow ({e})")
            break
        if znaleziony:
            _zdarzenie(log, slug, "info", f"#{pid}: job {znaleziony['job_id']} jednak powstal - czekam na niego (bez drugiego wysylania)",
                       pomysl=pid)
            return znaleziony
    _zdarzenie(log, slug, "uwaga", f"#{pid}: wysylanie zwrocilo blad ({str(blad)[:200]}), a joba (jeszcze) nie widac na liscie "
               f"Higgsfield - NIE wysylam drugi raz. Rolka czeka w toku; sprawdzam przy kolejnych przebiegach przez "
               f"{OKNO_NIEPEWNEGO_WYSLANIA_S // 60} min.", pomysl=pid)
    raise JobTrwa("nie wiadomo, czy job powstal")


def _niepewne_wyslanie(slug, p, d, marker, przyczyna, log, wynik):
    """Nie wiadomo, czy przerwane wysylanie utworzylo job, i nie ma juz sensu czekac: rolka 'nie wyszla' z prosba o sprawdzenie
    w apce - BEZ automatycznego drugiego wysylania. Koszt (wycena) wliczamy do limitu dnia na wszelki wypadek."""
    pid = p["id"]
    k = int(marker.get("koszt") or 0)
    if k:
        baza.dopisz_wydatek(k, d.NAZWA, job_id=f"niepewne:{marker.get('klucz') or pid}")
    notatki = (f"Wysylanie przerwane ({przyczyna}) - nie wiadomo, czy rolka powstala. {sprawdz_w_apce(d.NAZWA)}"
               + (f" {dostawcy.kwota(k, d.NAZWA)} wliczone do dzisiejszego limitu na wszelki wypadek." if k else ""))
    baza.aktualizuj_pomysl(slug, pid, status="blad", w_toku=None, krok_startowy=None, dostawca=d.NAZWA, powod="inny",
                           notatki=notatki[:2000])
    baza.zapisz_probe(slug, pid, {"dostawca": d.NAZWA, "model": marker.get("model"), "krok": marker.get("krok") or 0,
                                  "job_id": None, "status": "niepewne", "powod": None, "kr": k, "info": przyczyna[:300]})
    wynik["bledy"].append(pid)
    _zdarzenie(log, slug, "blad", f"#{pid}: {notatki}", pomysl=pid)


def _czekaj(slug, pid, d, job_id, timeout, log, stop, gotowy=None):
    """Odpytuje job az do konca (0 kr). Zwraca wynik koncowy albo rzuca JobTrwa (limit czasu) / Przerwano (STOP) - w obu
    przypadkach job zostaje w_toku i dokonczymy go pozniej. NIGDY nie wysyla nowego joba."""
    if gotowy and d.koncowy(gotowy.get("status") or ""):
        return gotowy
    odpytan = max(1, dostawcy.sekundy(timeout) // ODSTEP_ODPYTYWANIA_S)
    bledy = 0
    for i in range(odpytan + 1):
        _sprawdz_stop(stop)
        try:
            w = d.sprawdz(job_id)
            bledy = 0
        except dostawcy.BladDostawcy as e:
            w = None
            bledy += 1
            if bledy in (1, 5) or bledy % 30 == 0:
                log(f"#{pid}: nie moge sprawdzic joba {job_id} ({str(e)[:150]}) - probuje dalej, nic nie wysylam")
        if w is not None and d.koncowy(w.get("status") or ""):
            return w
        if i and i % 6 == 0:
            log(f"#{pid}: job {job_id} jeszcze sie robi ({(w or {}).get('status') or '?'})...")
        if i < odpytan:
            _spij(ODSTEP_ODPYTYWANIA_S, stop)
    raise JobTrwa(f"job {job_id} jeszcze sie robi")


def _rozlicz(slug, pid, d, w, k, krok, model, log):
    """Koszt zakonczonego joba (z joba / wyceny - nie z roznicy salda), raz na job (budzet pamieta rozliczone job_id),
    + wpis w p['proby']. Zwraca (kr, powod)."""
    kr = int(d.koszt_joba(w, k) or 0)
    powod = None if d.udany(w.get("status") or "") else powod_odrzucenia(w.get("status"), w.get("blad"))
    jid = w.get("job_id")
    if kr:
        juz = baza.rozliczony(jid, d.NAZWA)
        wydano = baza.dopisz_wydatek(kr, d.NAZWA, job_id=jid)
        if not juz:
            if dostawcy.jednostka(d.NAZWA) == "c":
                tekst = (f"#{pid}: {dostawcy.kwota(kr, d.NAZWA)} ({d.NAZWA} {model}"
                         f"{', odrzucone - liczone na wszelki wypadek' if powod else ''}), dzis {dostawcy.kwota(wydano, d.NAZWA)}/"
                         f"{dostawcy.kwota(baza.limit_dzienny(d.NAZWA), d.NAZWA)}")
            else:
                tekst = f"#{pid}: {kr} kr ({d.NAZWA} {model}), dzis {wydano}/{baza.limit_dzienny(d.NAZWA)}"
            baza.dziennik_zapisz("kredyty", tekst, modelka=slug, pomysl=pid, kredyty=kr, dostawca=d.NAZWA)
    baza.zapisz_probe(slug, pid, {"dostawca": d.NAZWA, "model": model, "krok": krok, "job_id": jid, "status": w.get("status"),
                                  "powod": powod, "kr": kr})
    return kr, powod


def _przytnij_do(slug, p, z, max_s, log):
    """Wan: filmik referencyjny max `max_s` s - przycinamy KOPIE (zrodla_ciete/<nazwa>_max15s.mp4), oryginal bez zmian."""
    czas = z.get("video_czas")
    if not (z.get("video") and max_s and czas and float(czas) > float(max_s) + 0.05):
        return z
    stem = os.path.splitext(os.path.basename(z["video"]))[0]
    cel = os.path.join(baza.folder_modelki(slug), "zrodla_ciete", f"{_bezpieczna_nazwa(stem)}_max{int(max_s)}s.mp4")
    if not os.path.isfile(cel):
        klatki.przytnij(z["video"], cel, float(max_s) - 0.1)
        log(f"#{p['id']}: filmik ma {float(czas):.1f} s - do zapasu ida pierwsze {float(max_s) - 0.1:.1f} s (kopia)")
    return dict(z, video=cel, video_czas=round(float(max_s) - 0.1, 2))


def _nastepny_krok_innego_dostawcy(ust, krok):
    """Pierwszy krok zapas_nsfw po `krok` u INNEGO dostawcy (1..) albo None - gdy u jednego dostawcy zapas jest niemozliwy
    (brak limitu, saldo), jego pozostale kroki pomijamy, ale inny dostawca dalej moze sprobowac."""
    kroki = ust.get("zapas_nsfw") or []
    ten = (kroki[krok - 1].get("dostawca") if 0 < krok <= len(kroki) and isinstance(kroki[krok - 1], dict) else "") or ""
    for j in range(krok + 1, len(kroki) + 1):
        k = kroki[j - 1] if isinstance(kroki[j - 1], dict) else {}
        if (k.get("dostawca") or "").strip().lower() != ten.strip().lower():
            return j
    return None


def _przygotuj_zapas(slug, p, ust, krok, log, potwierdz=None, tylko_wycena=False):
    """Krok zapasu nr `krok` (1 = pierwszy z zapas_nsfw): bezpiecznik dostawcy zapasu + wycena. Zwraca (d, z, kr) albo None
    (krok pominiety - wpis w p['proby']). Rzuca _BezZapasu, gdy zapas u tego dostawcy jest teraz niemozliwy: dzienny limit
    dostawcy (yapper / WaveSpeed) nieustawiony/wyczerpany (wtedy ZERO zapytan do niego), saldo, odmowa startu."""
    kroki = ust.get("zapas_nsfw") or []
    opis = kroki[krok - 1] if 0 < krok <= len(kroki) and isinstance(kroki[krok - 1], dict) else {}
    nazwa = (opis.get("dostawca") or "").strip().lower()
    model = (opis.get("model") or "").strip()
    yapper = nazwa == "yapper"

    def pomin(powod, tekst):
        _zdarzenie(log, slug, "uwaga", f"#{p['id']}: zapas {nazwa or '?'} {model or '?'} pominiety - {tekst}", pomysl=p["id"])
        if not tylko_wycena:
            baza.zapisz_probe(slug, p["id"], {"dostawca": nazwa, "model": model, "krok": krok, "job_id": None,
                                              "status": "pominiete", "powod": powod, "kr": 0, "info": tekst[:300]})
        return None

    def kw(x):
        return dostawcy.kwota(x, nazwa)

    if p.get("stroj") and _krok_uzywa_wan(nazwa, model):
        # wariant B: stroj ma byc ze zdjecia, a prompt Wan (wan.txt) bierze stroj z filmu i traktuje wszystkie zdjecia jak twarz
        # persony - ten krok dalby inna rolke niz chciales (zero zapytan do niego). Krok z promptem persony (WaveSpeed Seedance)
        # stroj zachowa - wtedy probujemy dalej.
        if zapas_dla_stroju(kroki[krok:]):
            return pomin("stroj", "rolka ze strojem ze zdjecia (wariant B) - ten krok bierze prompt Wan (stroj z filmu), probuje dalej")
        raise _BezZapasu("rolka ze strojem ze zdjecia (wariant B, takze stroj z biblioteki) - prompt Wan bierze stroj z filmu, wiec "
                         "zapas Wan zgubilby stroj i jest dla niej wylaczony; zrob ja na Higgsfield (inny stroj / inny fragment) albo "
                         "zmien przy klipie 'Stroj: z filmu'", wszystkie=True)
    if nazwa not in dostawcy.NAZWY_ZAPASU or not model:
        return pomin("nieobslugiwany", "zapas obsluguje kroki {\"dostawca\": \"yapper\" albo \"wavespeed\", \"model\": ...}")
    if nazwa == "wavespeed":
        from dostawcy import wavespeed
        if model not in wavespeed.MODELE:
            return pomin("nieobslugiwany", f"WaveSpeed: nie znam modelu {model} (znam: {', '.join(wavespeed.MODELE)})")
    limit = baza.limit_dzienny(nazwa)
    if not limit:
        if yapper:
            raise _BezZapasu("dzienny limit yappera nie jest ustawiony - bez niego zapas nic nie wyda. Ustaw go: panel -> "
                             "Ustawienia -> Limity kredytow (tryb pelny) -> 'yapper.so: nie wiecej niz ... kredytow dziennie' albo "
                             "`python fabryka.py budzet max_kredyty_dziennie=500 --dostawca yapper`")
        raise _BezZapasu(BRAK_LIMITU_WAVESPEED)
    wydano = baza.wydano_z_rezerwa(nazwa)      # z rezerwa procesow w toku
    if wydano >= limit:
        if yapper:
            raise _BezZapasu(f"dzienny limit yappera wyczerpany ({wydano}/{limit} kr) - zapas jutro albo podnies limit")
        raise _BezZapasu(f"dzienny limit WaveSpeed wyczerpany ({kw(wydano)}/{kw(limit)}) - zapas jutro albo podnies limit")
    d = dostawcy.dostawca(nazwa)
    z = zlecenie(slug, p, ust)
    z["dostawca"] = nazwa
    z[nazwa] = dict(z.get(nazwa) or {}, model=model)
    try:
        zasady = d.zasady_modelu(model)
        z = _przytnij_do(slug, p, z, zasady.get("max_wideo_s"), log)
        saldo = d.saldo()
    except dostawcy.BladDostawcy as e:
        raise _BezZapasu(f"{dostawcy.NAZWY_LUDZKIE.get(nazwa, nazwa)} nie odpowiada ({e})")
    except Exception as e:      # ffmpeg (przycinanie)
        return pomin("blad", f"nie moge przygotowac filmiku ({e})")
    try:
        k = d.koszt(z)            # darmowa wycena: yapper dryRun (creditsEstimated, odmowa przy canStart=false), WaveSpeed cennik/API
    except dostawcy.BladDostawcy as e:
        return pomin("wycena", f"wycena nie wyszla: {e}")
    if tylko_wycena:
        return d, z, k
    min_k, max_k = bezpiecznik(ust, nazwa)
    if k > max_k:
        return pomin("za_drogo", f"{k} kr > yapper max/rolka {max_k}" if yapper else f"{kw(k)} > WaveSpeed max/rolka {kw(max_k)}")
    if saldo - k < min_k:
        raise _BezZapasu(f"{k} kr zostawiloby na yapper {saldo - k} < min {min_k}" if yapper
                         else f"{kw(k)} zostawiloby na WaveSpeed {kw(saldo - k)} < min {kw(min_k)}")
    if wydano + k > limit:
        return pomin("limit", f"{k} kr przekroczyloby dzienny limit yappera ({wydano}+{k} > {limit})" if yapper
                     else f"{kw(k)} przekroczyloby dzienny limit WaveSpeed ({kw(wydano)}+{kw(k)} > {kw(limit)})")
    if potwierdz is not None and not potwierdz(p, k, saldo - k, wydano + k, limit):
        return pomin("odmowa", "pominiety na zyczenie")
    return d, z, k


def _nazwa_wyniku(p):
    """Rdzen nazwy pliku rolki: nazwa filmiku zrodlowego, 'prompt_<miejsce>' (rolka z promptu) albo 'pomysl_<id>'."""
    if z_promptu(p):
        return _bezpieczna_nazwa("prompt_" + str((p.get("z_promptu") or {}).get("miejsce") or "wlasny"))
    return _bezpieczna_nazwa(os.path.splitext(os.path.basename(p.get("zrodlo") or f"pomysl_{p['id']}"))[0])


def _sukces(slug, p, d, w, kr, krok, ust, log, lipsync, wynik):
    """Job sie udal: pobranie -> wygenerowany -> Media Tool -> gotowe (+ lipsync recznego 'Zrob rolke')."""
    pid = p["id"]
    urls = w.get("urls") or []
    model = (p.get("w_toku") or {}).get("model") or ""
    nazwa = _nazwa_wyniku(p)
    rozsz = os.path.splitext(urls[0].split("?")[0])[1] or ".mp4"
    if rozsz.lower() not in ROZSZERZENIA_WIDEO:
        rozsz = ".mp4"
    surowy = os.path.join(baza.folder_wynikow(slug), f"{pid:03d}_{nazwa}.raw{rozsz}")
    try:
        d.pobierz(urls[0], surowy)
    except Exception as e:
        wiek = _wiek_s((p.get("w_toku") or {}).get("od"))
        if wiek is not None and wiek > MAX_GODZIN_W_TOKU * 3600:
            baza.aktualizuj_pomysl(slug, pid, status="blad", w_toku=None, job_id=w.get("job_id"), koszt=kr, dostawca=d.NAZWA,
                                   wynik_url=urls[0], notatki=f"pobranie: {e}", powod="inny")
            _zdarzenie(log, slug, "blad", f"#{pid}: pobranie nie wychodzi od {MAX_GODZIN_W_TOKU} h ({e}) - pobierz recznie: {urls[0]}",
                       pomysl=pid)
            wynik["bledy"].append(pid)
            return False
        # job zaplacony i gotowy - zostaje w_toku: nastepny przebieg pobierze go jeszcze raz (bez nowego joba)
        _zdarzenie(log, slug, "blad", f"#{pid}: pobranie nie wyszlo ({e}) - sprobuje jeszcze raz przy nastepnym przebiegu, URL: {urls[0]}",
                   pomysl=pid)
        wynik["w_toku"].append(pid)
        return False
    zapas = krok > 0
    kr_klatek = int(((p.get("klatka") or {}).get("kr") or 0)) if z_promptu(p) and isinstance(p.get("klatka"), dict) else 0
    baza.aktualizuj_pomysl(slug, pid, status="wygenerowany", w_toku=None, krok_startowy=None, job_id=w.get("job_id"),
                           koszt=kr + kr_klatek,
                           dostawca=d.NAZWA, model=model, zapas=zapas, wynik_url=urls[0], plik_wynikowy=surowy)
    wynik["wygenerowane"] += 1
    limit_dnia = baza.limit_dzienny(d.NAZWA)
    if dostawcy.jednostka(d.NAZWA) == "c":
        ile = f"{dostawcy.kwota(kr, d.NAZWA)} {d.NAZWA}"
        dzis = f"{dostawcy.kwota(baza.wydano_dzis(d.NAZWA), d.NAZWA)}/{dostawcy.kwota(limit_dnia, d.NAZWA)}"
    else:
        ile, dzis = f"{kr} kr" + (f" {d.NAZWA}" if zapas else ""), f"{baza.wydano_dzis(d.NAZWA)}/{limit_dnia}"
    if zapas:
        _zdarzenie(log, slug, "ok", f"#{pid}: NSFW -> zapas {model}: WYGENEROWANE ({ile}, dzis {dzis}) -> {surowy}", pomysl=pid,
                   zapas=model)
    else:
        _zdarzenie(log, slug, "ok", f"#{pid}: WYGENEROWANE ({ile}, dzis {dzis}) -> {surowy}", pomysl=pid)
    do_prania = _komentarz_po_generacji(slug, baza.pomysl(slug, pid), surowy, log) or surowy
    gotowy = _postprodukcja(slug, pid, do_prania, nazwa, ust, log=log)
    if gotowy:
        _zdarzenie(log, slug, "ok", f"#{pid}: GOTOWE -> {gotowy}", pomysl=pid, plik=gotowy)
    if lipsync is not False:
        _lipsync_po_generacji(slug, baza.pomysl(slug, pid), gotowy or surowy, ust, log)
    return True


def _komentarz_po_generacji(slug, p, surowy, log):
    """Rolka z promptu z glosem "tts": komentarz zza kamery z ElevenLabs dogrywany do wideo z samym otoczeniem (komentarz_glos).
    Zwraca sciezke wideo z komentarzem albo None (wtedy rolka idzie dalej bez komentarza - nigdy nie psuje oplaconej rolki)."""
    zp = (p or {}).get("z_promptu") or {}
    if not (z_promptu(p) and zp.get("glos") == "tts" and zp.get("komentarz")):
        return None
    try:
        import komentarz_glos
        plik = komentarz_glos.dograj(slug, p["id"], surowy, zp["komentarz"], zp.get("komentarz_t") or 4, log=log)
        baza.aktualizuj_pomysl(slug, p["id"], glos_dograny=True, glos_plik=plik, glos_blad=None)
        return plik
    except Exception as e:
        tekst = (f"#{p['id']}: komentarz ElevenLabs nie dograny ({e}) - rolka wyszla BEZ komentarza zza kamery (tylko dzwiek "
                 f"otoczenia; model wideo nic nie mowi). Napraw ElevenLabs (Ustawienia -> Konta) i kliknij 'Dograj glos' w panelu")
        _zdarzenie(log, slug, "uwaga", tekst, pomysl=p["id"])
        baza.aktualizuj_pomysl(slug, p["id"], glos_dograny=False, glos_blad=str(e)[:300])
        return None


def plik_surowy(slug, p):
    """Surowy wynik rolki (modelki/<slug>/wyniki/NNN_<nazwa>.raw.*) albo None."""
    folder = baza.folder_wynikow(slug)
    pref = f"{int(p['id']):03d}_{_nazwa_wyniku(p)}.raw"
    for n in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if n.startswith(pref) and n.lower().endswith(ROZSZERZENIA_WIDEO):
            return os.path.join(folder, n)
    return None


def dograj_glos(slug, pid, log=None):
    """Dogranie komentarza ElevenLabs do GOTOWEJ rolki z promptu z glosem "tts" (np. gdy przy generacji nie bylo dobrego klucza):
    surowy plik (sam dzwiek otoczenia) + glos -> Media Tool -> ten sam gotowy plik. Kosztuje tylko znaki ElevenLabs, zero
    kredytow Higgsfield, nic nie wysyla do generacji. Zwraca sciezke gotowego pliku."""
    log = log or _log
    p = baza.pomysl(slug, int(pid))
    zp = p.get("z_promptu") or {}
    if not z_promptu(p):
        raise ValueError("Glos dogrywam tylko do rolek z promptu.")
    if p.get("status") not in ("gotowe", "wygenerowany", "postprodukcja"):
        raise ValueError(f"#{pid} nie jest jeszcze gotowa (status {p.get('status')}).")
    if zp.get("glos") != "tts":
        raise ValueError("Ta rolka ma komentarz mowiony przez model wideo - drugi glos by go zdublowal. Zrob nowa rolke "
                         "(z dobrym kluczem ElevenLabs komentarz dogrywa sie sam).")
    if not zp.get("komentarz"):
        raise ValueError("Ta rolka nie ma komentarza zza kamery.")
    surowy = plik_surowy(slug, p)
    if not surowy:
        raise ValueError(f"Nie znajduje surowego pliku rolki #{pid} w modelki/{slug}/wyniki/.")
    import komentarz_glos
    try:
        plik = komentarz_glos.dograj(slug, p["id"], surowy, zp["komentarz"], zp.get("komentarz_t") or 4, log=log)
    except (komentarz_glos.BladGlosu, dostawcy.BladDostawcy) as e:
        baza.aktualizuj_pomysl(slug, p["id"], glos_dograny=False, glos_blad=str(e)[:300])
        raise ValueError(f"Nie dogralem glosu: {e}")
    baza.aktualizuj_pomysl(slug, p["id"], glos_dograny=True, glos_plik=plik, glos_blad=None)
    gotowy = _postprodukcja(slug, p["id"], plik, _nazwa_wyniku(p), baza.ustawienia_modelki(slug), log=log)
    _zdarzenie(log, slug, "ok", f"#{pid}: komentarz dograny -> {gotowy or plik}", pomysl=p["id"])
    return gotowy or plik


def cmd_dograj_glos(args):
    slug = _slug(args.modelka)
    print(dograj_glos(slug, args.id))
    return 0


def _niepowodzenie(slug, p, d, w, kr, powod, ust, log, wynik, zapas_info=""):
    """Rolka nie wyszla (po wszystkich krokach): status blad z powodem; NSFW/IP osobno w wynik['odrzucone'] (hamulec ich nie liczy)."""
    pid = p["id"]
    blad = (w or {}).get("blad") or ""
    if w:
        notatki = f"job {w.get('job_id')} status={w.get('status')}" + (f", powod: {blad}" if blad else "")
        if w.get("surowe"):
            notatki += f": {json.dumps(w['surowe'], ensure_ascii=False)[:600]}"
    else:
        notatki = "zapas po NSFW: zaden krok nie ruszyl (szczegoly w 'proby')"
    baza.aktualizuj_pomysl(slug, pid, status="blad", w_toku=None, krok_startowy=None, job_id=(w or {}).get("job_id"), koszt=kr,
                           dostawca=d.NAZWA if d else None, notatki=(notatki + zapas_info)[:2000], powod=powod)
    wynik["bledy"].append(pid)
    if powod == "nsfw":
        wynik["odrzucone"].append(pid)
        _zdarzenie(log, slug, "blad", f"#{pid}: ODRZUCONE przez filtr tresci (NSFW){zapas_info}. {PODPOWIEDZ_NSFW}", pomysl=pid, powod="nsfw")
    elif powod == "ip":
        wynik["odrzucone"].append(pid)
        _zdarzenie(log, slug, "blad", f"#{pid}: ODRZUCONE - model wykryl znana postac/marke (ip_detected){zapas_info}. "
                   f"Sprawdz, czy w filmiku/zdjeciach nie ma logo, celebryty albo postaci z filmu.", pomysl=pid, powod="ip")
    elif w is not None and d is not None and d.udany(w.get("status") or ""):
        gdzie = (f"`higgsfield generate get {w.get('job_id')} --json`" if d.NAZWA == "higgsfield"
                 else f"zadanie {w.get('job_id')} w apce {dostawcy.NAZWY_LUDZKIE.get(d.NAZWA, d.NAZWA)}")
        _zdarzenie(log, slug, "blad", f"#{pid}: job {w.get('job_id')} zakonczony, ale nie znajduje URL - NIE powtarzam; sprawdz "
                   f"{gdzie}", pomysl=pid)
    else:
        _zdarzenie(log, slug, "blad", f"#{pid}: BLAD ({(blad or (w or {}).get('status') or '?')[:200]}) - status blad, "
                   f"kliknij 'Sprobuj jeszcze raz', gdy poprawisz przyczyne", pomysl=pid)


def _rolka(slug, p, ust, log, stop, timeout, lipsync, wynik, d0=None, k0=None, krok_start=0, potwierdz=None):
    """Cala rolka: krok 0 = dostawca persony (d0, wycena k0), po odrzuceniu NSFW/IP kolejne kroki zapas_nsfw (po jednej probie).
    Pomysl w_toku (marker) jest WZNAWIANY: odpytujemy jego job zamiast wysylac nowy. Aktualizuje `wynik` generuj()."""
    pid = p["id"]
    kroki = [] if z_promptu(p) else list(ust.get("zapas_nsfw") or [])      # rolki z promptu: bez zapasu po NSFW
    marker = p.get("w_toku") if p.get("status") == "w_toku" else None
    if p.get("status") == "w_toku" and not marker:
        baza.aktualizuj_pomysl(slug, pid, status="nowy", w_toku=None)
        log(f"#{pid}: rolka w toku bez znacznika generacji - wraca do kolejki")
        return
    krok = int((marker or {}).get("krok") or 0) if marker else krok_start
    powod, w, kr_razem, d, zapas_info = None, None, 0, d0, ""
    if z_promptu(p) and (p.get("z_promptu") or {}).get("klatka") and (not marker or marker.get("faza") == "klatka"):
        # 3.5: najpierw pierwsza klatka (gotowa = od razu; znacznik klatki = TEN job; inaczej nowa, z cena i bezpiecznikami),
        # dopiero potem wideo od tej klatki. Zla klatka / filtr / bezpiecznik = blad BEZ wideo (0 kr na wideo).
        import pierwsza_klatka
        k_wideo = k0 if k0 is not None else int((p.get("z_promptu") or {}).get("wycena_wideo") or 0)
        try:
            plik_klatki = pierwsza_klatka.przygotuj(slug, pid, log=log, stop=stop, timeout=timeout, k_wideo=k_wideo)
        except JobTrwa as e:
            _zdarzenie(log, slug, "info", f"#{pid}: pierwsza klatka - {e}; zostaje w toku, dokoncze przy nastepnym przebiegu (nic nie "
                       f"wysylam drugi raz)", pomysl=pid)
            wynik["w_toku"].append(pid)
            return
        except pierwsza_klatka.WrocDoKolejki:
            return
        except pierwsza_klatka.NieWyszla as e:
            q = baza.pomysl(slug, pid)
            _niepowodzenie(slug, q, dostawcy.dostawca(DOSTAWCA_Z_PROMPTU), {"job_id": e.job_id, "status": e.status, "blad": e.tekst},
                           int(pierwsza_klatka.stan(q).get("kr") or 0), e.powod, ust, log, wynik)
            return
        if d0 is None:
            # wznowienie (start panelu, autopilot, `wznow`, STOP wczesniej): dokonczylismy TYLKO klatke (0 kr ponad nia) - wideo
            # (~70 kr) nie rusza samo bez swiezej zgody: rolka czeka jako 'nowy' z gotowa klatka ("Zrob te rolke" / autopilot)
            baza.aktualizuj_pomysl(slug, pid, status="nowy", w_toku=None)
            _zdarzenie(log, slug, "info", f"#{pid}: pierwsza klatka gotowa ({os.path.basename(plik_klatki)}) - wideo nie rusza samo po "
                       f"wznowieniu; 'Zrob te rolke' wezmie TE klatke (bez nowej oplaty za klatke)", pomysl=pid)
            return
        p, marker, krok = baza.pomysl(slug, pid), None, 0
    while krok <= len(kroki):
        _sprawdz_stop(stop)
        if marker:
            # --- wznowienie proby sprzed restartu/timeoutu/STOP: ten sam job ---
            d = dostawcy.dostawca(marker.get("dostawca"))
            model = marker.get("model") or ""
            k = marker.get("koszt")
            jid = marker.get("job_id")
            wiek = _wiek_s(marker.get("od"))
            if not jid:
                if not marker.get("wysylam"):
                    baza.aktualizuj_pomysl(slug, pid, status="nowy", w_toku=None, krok_startowy=krok or None)
                    log(f"#{pid}: wysylanie nie zaczelo sie przed przerwaniem - rolka wraca do kolejki")
                    return
                # okno liczymy od chwili wyslania (wysylam_od), nie od startu proby - upload potrafi trwac minuty
                od_wyslania = marker.get("wysylam_od") or marker.get("od")
                wiek = _wiek_s(od_wyslania)
                idem = getattr(d, "IDEMPOTENTNY", False)
                try:
                    znaleziony = d.znajdz(model, wideo_id=marker.get("wideo_id"), prompt=_prompt_wyslany(slug, p, ust),
                                          od=od_wyslania, klucz=marker.get("klucz"),
                                          pomin=_pomin_przy_szukaniu(p, d, marker), klatka_id=marker.get("klatka_id"))
                except dostawcy.BladDostawcy as e:
                    if wiek is not None and wiek > MAX_GODZIN_W_TOKU * 3600:
                        _niepewne_wyslanie(slug, p, d, marker, f"od {MAX_GODZIN_W_TOKU} h nie da sie sprawdzic listy jobow: {e}", log, wynik)
                        return
                    log(f"#{pid}: nie moge sprawdzic, czy przerwane wysylanie utworzylo job ({e}) - sprobuje pozniej, nic nie wysylam")
                    wynik["w_toku"].append(pid)
                    return
                if not znaleziony:
                    okno = CZAS_NA_WYSLANIE_S if idem else OKNO_NIEPEWNEGO_WYSLANIA_S
                    if wiek is None or wiek < okno:
                        log(f"#{pid}: wysylanie przerwane {int(wiek or 0)} s temu, joba nie widac na liscie - czekam (do "
                            f"{okno // 60} min), nic nie wysylam drugi raz")
                        wynik["w_toku"].append(pid)
                        return
                    if idem:
                        # yapper: kolejne wyslanie pojdzie z TYM SAMYM Idempotency-Key - jesli proces jednak jest, dostaniemy go
                        baza.aktualizuj_pomysl(slug, pid, status="nowy", w_toku=None, krok_startowy=krok or None)
                        _zdarzenie(log, slug, "info", f"#{pid}: przerwane wysylanie nie utworzylo procesu - rolka wraca do kolejki "
                                   f"(ten sam klucz idempotencji)", pomysl=pid)
                        return
                    _niepewne_wyslanie(slug, p, d, marker, f"po {okno // 60} min joba dalej nie widac na liscie", log, wynik)
                    return
                jid = znaleziony["job_id"]
                baza.ustaw_w_toku(slug, pid, job_id=jid, etap="czeka")
                _zdarzenie(log, slug, "info", f"#{pid}: odnaleziony job {jid} z przerwanego wysylania - czekam na niego", pomysl=pid)
                job = znaleziony
            else:
                job = None
                _zdarzenie(log, slug, "info", f"#{pid}: wznawiam - job {jid} ({d.NAZWA} {model}) byl juz wyslany, sprawdzam go "
                           f"(bez wysylania nowego)", pomysl=pid)
            if wiek is not None and wiek > MAX_GODZIN_W_TOKU * 3600 and not (job and d.koncowy(job.get("status") or "")):
                try:
                    teraz = d.sprawdz(jid)
                except dostawcy.BladDostawcy:
                    teraz = {"job_id": jid, "status": "", "blad": "nie odpowiada"}
                if not d.koncowy(teraz.get("status") or ""):
                    kr_rez = int(k or 0)
                    if kr_rez:      # job byl wyslany - na wszelki wypadek wliczamy wycene (raz na job)
                        baza.dopisz_wydatek(kr_rez, d.NAZWA, job_id=jid)
                    _niepowodzenie(slug, baza.pomysl(slug, pid), d, dict(teraz, blad=f"job nie skonczyl sie w {MAX_GODZIN_W_TOKU} h - "
                                   f"{sprawdz_w_apce(d.NAZWA)}"), kr_rez, "inny", ust, log, wynik)
                    return
                job = teraz
            marker = None
        else:
            # --- nowa proba ---
            if krok == 0:
                d, z, k = d0, zlecenie(slug, p, ust), k0
            else:
                try:
                    przyg = _przygotuj_zapas(slug, baza.pomysl(slug, pid), ust, krok, log, potwierdz=potwierdz)
                except _BezZapasu as e:
                    zapas_info = f" | zapas pominiety: {e}"
                    _zdarzenie(log, slug, "uwaga", f"#{pid}: zapas po NSFW pominiety - {e}", pomysl=pid)
                    nastepny = None if e.wszystkie else _nastepny_krok_innego_dostawcy(ust, krok)
                    if nastepny is None:
                        break
                    krok = nastepny          # u tego dostawcy sie nie da - probuje kroku innego dostawcy
                    continue
                if not przyg:
                    krok += 1
                    continue
                d, z, k = przyg
            model = _model(d, z)
            if krok > 0:
                _zdarzenie(log, slug, "info", f"#{pid}: NSFW -> zapas {model} ({d.NAZWA}, ~{dostawcy.kwota(k, d.NAZWA)}, "
                           f"{z.get('resolution')})", pomysl=pid)
            else:
                _zdarzenie(log, slug, "info", f"#{pid}: start ({d.NAZWA} {model}, {z.get('resolution')}, ~{dostawcy.kwota(k, d.NAZWA)}) "
                           f"- {p['opis']}", pomysl=pid)
            try:
                job = _wyslij(slug, baza.pomysl(slug, pid), d, z, k, krok, ust, log)
            except JobTrwa:
                wynik["w_toku"].append(pid)
                return
            except dostawcy.BladDostawcy as e:
                _niepowodzenie(slug, baza.pomysl(slug, pid), d, {"job_id": None, "status": "", "blad": str(e)}, kr_razem,
                               powod_odrzucenia("", str(e)) or "inny", ust, log, wynik, zapas_info)
                return
            jid = job.get("job_id")
            if jid is None:          # odrzucone juz przy wysylaniu
                w = job
                powod = powod_odrzucenia(job.get("status"), job.get("blad"))
                baza.zapisz_probe(slug, pid, {"dostawca": d.NAZWA, "model": model, "krok": krok, "job_id": None,
                                              "status": job.get("status"), "powod": powod, "kr": 0, "info": (job.get("blad") or "")[:300]})
                if powod in POWODY_ZAPASU and krok < len(kroki):
                    # miedzy krokami: 'nowy' + krok_startowy - po awarii w tym miejscu rolka ruszy od zapasu, nie od Seedance
                    baza.aktualizuj_pomysl(slug, pid, status="nowy", w_toku=None, krok_startowy=krok + 1)
                    krok += 1
                    continue
                _niepowodzenie(slug, baza.pomysl(slug, pid), d, w, kr_razem, powod, ust, log, wynik, zapas_info)
                return
            job = job.get("gotowy") or None
        # --- czekanie na TEN job ---
        try:
            w = _czekaj(slug, pid, d, jid, timeout, log, stop, gotowy=job)
        except JobTrwa as e:
            _zdarzenie(log, slug, "info", f"#{pid}: {e} - zostaje w toku, dokoncze przy nastepnym przebiegu (nic nie wysylam drugi raz)",
                       pomysl=pid)
            wynik["w_toku"].append(pid)
            return
        kr, powod = _rozlicz(slug, pid, d, w, k, krok, model, log)
        kr_razem += kr
        if d.udany(w.get("status") or "") and w.get("urls"):
            _sukces(slug, baza.pomysl(slug, pid), d, w, kr, krok, ust, log, lipsync, wynik)
            return
        if powod in POWODY_ZAPASU and krok < len(kroki):
            _zdarzenie(log, slug, "uwaga", f"#{pid}: {model} odrzucil ({powod}) - nie powtarzam tego modelu, probuje zapas", pomysl=pid,
                       powod=powod)
            # miedzy krokami: 'nowy' + krok_startowy - po awarii w tym miejscu rolka ruszy od zapasu, nie od Seedance
            baza.aktualizuj_pomysl(slug, pid, status="nowy", w_toku=None, krok_startowy=krok + 1)
            krok += 1
            continue
        if powod in POWODY_ZAPASU and krok == 0 and not kroki:
            zapas_info = (" | rolka z promptu nie idzie na zapas - zmien stroj, miejsce albo slowa pomyslu" if z_promptu(p)
                          else " | zapas po NSFW wylaczony (zapas_nsfw = [])")
        _niepowodzenie(slug, baza.pomysl(slug, pid), d, w, kr_razem, powod or "inny", ust, log, wynik, zapas_info)
        return
    # wszystkie kroki zapasu pominiete albo wyczerpane
    _niepowodzenie(slug, baza.pomysl(slug, pid), d, w, kr_razem, powod or "nsfw", ust, log, wynik, zapas_info)


def _nowy_wynik():
    return {"wygenerowane": 0, "bledy": [], "odrzucone": [], "pominiete": [], "w_toku": [], "stop": None}


def wznow_w_toku(slug, log=None, stop=None, timeout="30m", lipsync=None, wynik=None):
    """Dokancza rolki persony, ktore maja juz wyslany job (status w_toku: restart panelu, timeout, STOP, przerwane wysylanie):
    odpytuje TEN SAM job i pobiera wynik. Nigdy nie wysyla nowego joba dla tej samej proby. Zwraca wynik jak generuj()."""
    log = log or _log
    wynik = wynik if wynik is not None else _nowy_wynik()
    lista = baza.pomysly_w_toku(slug)
    if not lista:
        return wynik
    with baza.blokada_generacji(slug) as moge:
        if not moge:
            log(f"{slug}: inny proces juz dokancza rolki tej persony - pomijam")
            wynik["stop"] = "zajete"
            return wynik
        ust = baza.ustawienia_modelki(slug)
        for p in baza.pomysly_w_toku(slug):
            _rolka(slug, p, ust, log, stop, timeout, lipsync, wynik)
    return wynik


def wznow_wszystkie(log=None, stop=None, timeout="30m"):
    """Start panelu: dokoncz rolki w toku wszystkich person. Zwraca {slug: wynik} (tylko persony, ktore cos mialy)."""
    wyniki = {}
    for slug in baza.lista_modelek():
        if baza.pomysly_w_toku(slug):
            wyniki[slug] = wznow_w_toku(slug, log=log, stop=stop, timeout=timeout, lipsync=False)
    return wyniki


def generuj(slug, ids=None, limit=None, potwierdz=None, dry_run=False, bez_referencji=False,
            timeout="30m", log=None, stop=None, max_rolek=None, lipsync=None, wznow=True):
    """Generacja pozycji 'nowy' z promptem (albo wskazanych id). Najpierw dokancza rolki w toku (job wyslany wczesniej;
    wznow=False - autopilot zrobil to juz sam).

    potwierdz(p, koszt, saldo_po, dzis_po, limit) -> bool; None = bez pytania.
    stop = threading.Event (panel: STOP - job w toku zostaje i jest dokanczany pozniej). max_rolek = ile rolek max w tym
    przebiegu (autopilot). lipsync: None = wg ustawienia lipsync_auto (reczne "Zrob rolke"); False = nigdy (autopilot).
    Zwraca {"wygenerowane": n, "bledy": [id], "odrzucone": [id] (NSFW/IP - podzbior bledow), "pominiete": [id],
            "w_toku": [id], "stop": powod|None}.
    """
    log = log or _log
    wynik = _nowy_wynik()
    if dry_run:
        ust = baza.ustawienia_modelki(slug)
        d = dostawcy.dostawca(ust.get("dostawca") or "higgsfield")
        for uwaga in sprawdz_prompt(slug, ust):
            log(f"[UWAGA] {uwaga}")
        for p in kandydaci(slug, ids, limit, log):
            dp = dostawcy.dostawca(DOSTAWCA_Z_PROMPTU) if z_promptu(p) else d
            log(f"#{p['id']}: " + dp.podglad(zlecenie(slug, p, ust)))
        return wynik
    with baza.blokada_generacji(slug) as moge:
        if not moge:
            log("Inny proces (panel/autopilot albo konsola) robi wlasnie rolki tej persony - nie wysylam rownolegle, sprobuj za chwile.")
            wynik["stop"] = "zajete"
            return wynik
        return _generuj(slug, ids, limit, potwierdz, bez_referencji, timeout, log, stop, max_rolek, lipsync, wynik, wznow)


def _generuj(slug, ids, limit, potwierdz, bez_referencji, timeout, log, stop, max_rolek, lipsync, wynik, wznow=True):
    ust = baza.ustawienia_modelki(slug)
    nazwa_dostawcy = ust.get("dostawca") or "higgsfield"
    d = dostawcy.dostawca(nazwa_dostawcy)
    # 1) rolki w toku (job wyslany przed restartem/timeoutem) - dokonczyc, zanim cokolwiek nowego pojdzie
    if wznow and baza.pomysly_w_toku(slug):
        wznow_w_toku(slug, log=log, stop=stop, timeout=timeout, lipsync=lipsync, wynik=wynik)
    lista = kandydaci(slug, ids, limit, log)
    if not lista:
        if not wynik["wygenerowane"] and not wynik["w_toku"]:
            log("Nic do generacji (brak pomyslow 'nowy' z promptem).")
        return wynik
    promptowe = [p for p in lista if z_promptu(p)]
    if promptowe:
        # rolki z promptu: zawsze Higgsfield, wlasny model/dlugosc/zdjecia z pomyslu, te same bezpieczniki i wznawianie
        _generuj_z_promptu(slug, promptowe, ust, potwierdz, timeout, log, stop, max_rolek, lipsync, wynik)
        lista = [p for p in lista if not z_promptu(p)]
        if not lista:
            return wynik
    if not baza.sciezki_referencji(slug) and not bez_referencji:
        log("Brak zdjec persony w referencje/ - bez tego model nie wie, kogo wstawic. "
            "Wrzuc zdjecia albo dodaj --bez-referencji, jesli tak ma byc.")
        wynik["stop"] = "brak referencji"
        return wynik

    for uwaga in sprawdz_prompt(slug, ust):
        log(f"[UWAGA] {uwaga}")

    limit_dnia = baza.limit_dzienny(nazwa_dostawcy)
    if getattr(d, "WYMAGA_LIMITU", False) and not limit_dnia:
        # WaveSpeed placi prawdziwymi dolarami: bez dziennego limitu ZERO zapytan (rolki po NSFW z krok_startowy ida do zapasu)
        zapasowe = [p for p in lista if _krok_startowy(p, ust)]
        if len(zapasowe) < len(lista):
            _zdarzenie(log, slug, "uwaga", f"[STOP] {BRAK_LIMITU_WAVESPEED}")
            wynik["stop"] = f"brak limitu dziennego {nazwa_dostawcy}"
        if not zapasowe:
            return wynik
        lista = zapasowe
    try:
        saldo = d.saldo()
    except dostawcy.BladDostawcy as e:
        _zdarzenie(log, slug, "blad", f"[BLAD] saldo {nazwa_dostawcy}: {e}")
        wynik["stop"] = f"saldo: {e}"
        return wynik
    if saldo is None:
        saldo = 10 ** 9   # dostawca nie podaje salda - pilnuje tylko limit dzienny
    min_kredyty, max_na_rolke = bezpiecznik(ust, nazwa_dostawcy)

    def kw(x):
        return dostawcy.kwota(x, nazwa_dostawcy)

    if dostawcy.jednostka(nazwa_dostawcy) == "c":
        log(f"saldo {nazwa_dostawcy}: {kw(saldo)} | dzis wydano {kw(baza.wydano_dzis(nazwa_dostawcy))}/{kw(limit_dnia)} "
            f"(+{kw(baza.koszt_w_toku(nazwa_dostawcy))} w toku) | zostaw min {kw(min_kredyty)} | max/rolka {kw(max_na_rolke)} | "
            f"rozdzielczosc: {OPIS_ROZDZIELCZOSCI}")
    else:
        log(f"saldo {nazwa_dostawcy}: {saldo} kr | dzis wydano {baza.wydano_dzis(nazwa_dostawcy)}/{limit_dnia} "
            f"(+{baza.koszt_w_toku(nazwa_dostawcy)} w toku) | min_kredyty={min_kredyty} "
            f"max/rolka={max_na_rolke} | rozdzielczosc: {OPIS_ROZDZIELCZOSCI}")

    for p in lista:
        _sprawdz_stop(stop)
        if max_rolek is not None and wynik["wygenerowane"] + len(wynik["w_toku"]) >= max_rolek:
            wynik["stop"] = f"limit rolek w tym przebiegu ({max_rolek})"
            break
        p = baza.pomysl(slug, p["id"])
        if p.get("status") not in ("nowy", "blad"):
            continue        # w miedzyczasie wznowiona / zrobiona
        krok = _krok_startowy(p, ust)
        if krok:
            # "Ponow" po NSFW: od razu zapas (Seedance i tak odrzuci te same wejscia)
            _rolka(slug, p, ust, log, stop, timeout, lipsync, wynik, krok_start=krok, potwierdz=potwierdz)
            continue
        z = zlecenie(slug, p, ust)
        try:
            k = d.koszt(z)
        except dostawcy.BladDostawcy as e:
            _zdarzenie(log, slug, "blad", f"#{p['id']}: koszt nieznany ({e}) - pomijam", pomysl=p["id"])
            baza.aktualizuj_pomysl(slug, p["id"], status="blad", notatki=f"koszt: {e}")
            wynik["bledy"].append(p["id"])
            continue
        if k is None:
            k = max_na_rolke
            log(f"#{p['id']}: dostawca nie podal kosztu, zakladam {kw(k)}")
        baza.aktualizuj_pomysl(slug, p["id"], koszt=k, resolution=z["resolution"])
        wydano = baza.wydano_z_rezerwa(nazwa_dostawcy)     # wydane + zarezerwowane przez rolki w toku (wolne joby)
        try:
            saldo = d.saldo() or saldo
        except dostawcy.BladDostawcy:
            pass
        if k > max_na_rolke:
            _zdarzenie(log, slug, "uwaga", f"#{p['id']}: {kw(k)} ({z['resolution']}) > max/rolka {kw(max_na_rolke)} - POMIJAM "
                       f"(zmien ustawienia albo skroc zrodlo)", pomysl=p["id"])
            wynik["pominiete"].append(p["id"])
            continue
        if saldo - k < min_kredyty:
            _zdarzenie(log, slug, "uwaga", f"#{p['id']}: {kw(k)} zostawiloby {kw(saldo - k)} < min_kredyty {kw(min_kredyty)} - STOP",
                       pomysl=p["id"])
            wynik["stop"] = "min_kredyty"
            break
        if limit_dnia and wydano + k > limit_dnia:
            _zdarzenie(log, slug, "uwaga", f"#{p['id']}: {kw(k)} przekroczyloby limit dzienny ({kw(wydano)}+{kw(k)} > "
                       f"{kw(limit_dnia)}) - STOP na dzis", pomysl=p["id"])
            wynik["stop"] = "limit dzienny"
            break
        if potwierdz is not None and not potwierdz(p, k, saldo - k, wydano + k, limit_dnia):
            log("pominieto")
            wynik["pominiete"].append(p["id"])
            continue
        _rolka(slug, p, ust, log, stop, timeout, lipsync, wynik, d0=d, k0=k, potwierdz=potwierdz)

    log(f"koniec: {wynik['wygenerowane']} wygenerowanych, dzis wydano {kw(baza.wydano_dzis(nazwa_dostawcy))}/{kw(limit_dnia)}"
        + (f", w toku: {', '.join('#%s' % i for i in wynik['w_toku'])}" if wynik["w_toku"] else ""))
    return wynik


def _generuj_z_promptu(slug, lista, ust, potwierdz, timeout, log, stop, max_rolek, lipsync, wynik):
    """Rolki z promptu (typ 'prompt'): darmowa wycena `generate cost` TUZ przed wyslaniem (jak kazda rolka), bezpieczniki
    Higgsfielda (min_kredyty, max_kredyty_na_rolke, dzienny limit z rezerwa rolek w toku), potwierdz() (panel: cena nie wyzsza
    niz ta, ktora user zatwierdzil), potem _rolka (znacznik w_toku -> create bez --wait -> job_id -> ten sam job do konca)."""
    d = dostawcy.dostawca(DOSTAWCA_Z_PROMPTU)
    nazwa = d.NAZWA
    try:
        saldo = d.saldo()
    except dostawcy.BladDostawcy as e:
        _zdarzenie(log, slug, "blad", f"[BLAD] saldo {nazwa}: {e}")
        wynik["stop"] = f"saldo: {e}"
        return
    if saldo is None:
        saldo = 10 ** 9
    min_kredyty, max_na_rolke = bezpiecznik(ust, nazwa)
    limit_dnia = baza.limit_dzienny(nazwa)
    log(f"rolki z promptu - saldo {nazwa}: {saldo} kr | dzis wydano {baza.wydano_dzis(nazwa)}/{limit_dnia} "
        f"(+{baza.koszt_w_toku(nazwa)} w toku) | min_kredyty={min_kredyty} max/rolka={max_na_rolke}")
    for p in lista:
        _sprawdz_stop(stop)
        if max_rolek is not None and wynik["wygenerowane"] + len(wynik["w_toku"]) >= max_rolek:
            wynik["stop"] = f"limit rolek w tym przebiegu ({max_rolek})"
            break
        p = baza.pomysl(slug, p["id"])
        if p.get("status") not in ("nowy", "blad"):
            continue
        brak = [os.path.basename(o) for o in ((p.get("z_promptu") or {}).get("obrazy") or []) if not os.path.isfile(o)]
        if brak or not (p.get("z_promptu") or {}).get("obrazy"):
            tekst = (f"brakuje zdjec: {', '.join(brak)}" if brak else "rolka nie ma zdjec persony") + " - zrob ja jeszcze raz w 'Z promptu'"
            _zdarzenie(log, slug, "blad", f"#{p['id']}: {tekst}", pomysl=p["id"])
            baza.aktualizuj_pomysl(slug, p["id"], status="blad", notatki=tekst, powod="inny")
            wynik["bledy"].append(p["id"])
            continue
        z = zlecenie(slug, p, ust)
        try:
            k = d.koszt(zlecenie(slug, p, ust, do_wyceny=True))
            if k is None:
                k = max_na_rolke
                log(f"#{p['id']}: Higgsfield nie podal kosztu, zakladam {k} kr")
            k_wideo = k
            # 3.5: pierwsza klatka (gdy jeszcze jej nie ma) - cena razem = wideo + klatka (w gore); bezpieczniki i potwierdz()
            # patrza na sume, a gotowa klatka (wznowienie, "Sprobuj jeszcze raz" po bledzie wideo) nie kosztuje drugi raz
            import pierwsza_klatka
            if pierwsza_klatka.potrzebna(p):
                k, _k_kl, _k_max = pierwsza_klatka.wycena_rolki(p, k_wideo)
                if k is None:
                    raise dostawcy.BladDostawcy("Higgsfield nie podal ceny pierwszej klatki")
        except dostawcy.BladDostawcy as e:
            _zdarzenie(log, slug, "blad", f"#{p['id']}: koszt nieznany ({e}) - pomijam", pomysl=p["id"])
            baza.aktualizuj_pomysl(slug, p["id"], status="blad", notatki=f"koszt: {e}")
            wynik["bledy"].append(p["id"])
            continue
        baza.aktualizuj_pomysl(slug, p["id"], koszt=k, resolution=z["resolution"])
        wydano = baza.wydano_z_rezerwa(nazwa)
        try:
            saldo = d.saldo() or saldo
        except dostawcy.BladDostawcy:
            pass
        if k > max_na_rolke:
            _zdarzenie(log, slug, "uwaga", f"#{p['id']}: {k} kr ({z['resolution']}, {z['duration']} s) > max/rolka {max_na_rolke} - "
                       f"POMIJAM (krotsza rolka albo nizsza rozdzielczosc)", pomysl=p["id"])
            wynik["pominiete"].append(p["id"])
            continue
        if saldo - k < min_kredyty:
            _zdarzenie(log, slug, "uwaga", f"#{p['id']}: {k} kr zostawiloby {saldo - k} < min_kredyty {min_kredyty} - STOP",
                       pomysl=p["id"])
            wynik["stop"] = "min_kredyty"
            break
        if limit_dnia and wydano + k > limit_dnia:
            _zdarzenie(log, slug, "uwaga", f"#{p['id']}: {k} kr przekroczyloby limit dzienny ({wydano}+{k} > {limit_dnia}) - "
                       f"STOP na dzis", pomysl=p["id"])
            wynik["stop"] = "limit dzienny"
            break
        if potwierdz is not None and not potwierdz(p, k, saldo - k, wydano + k, limit_dnia):
            log(f"#{p['id']}: pominieto (cena {k} kr nie zostala potwierdzona)")
            wynik["pominiete"].append(p["id"])
            continue
        _rolka(slug, p, ust, log, stop, timeout, lipsync, wynik, d0=d, k0=k_wideo, potwierdz=potwierdz)
    log(f"rolki z promptu: {wynik['wygenerowane']} wygenerowanych, dzis wydano {baza.wydano_dzis(nazwa)}/{limit_dnia} kr"
        + (f", w toku: {', '.join('#%s' % i for i in wynik['w_toku'])}" if wynik["w_toku"] else ""))


# ---------------- rolka z promptu (zakladka "Z promptu", scenariusz.py) ----------------

def _dane_z_promptu(sc):
    """Wynik scenariusz.zbuduj -> pole 'z_promptu' pomyslu (to, z czego zlecenie() buduje generacje i wznowienie)."""
    return {k: sc.get(k) for k in ("model", "mode", "dlugosc", "rozdzielczosc", "parametry", "generate_audio", "obrazy",
                                   "pomysl_id", "miejsce", "miejsce_nazwa", "wlosy_zmienione", "stroj_plik", "komentarz",
                                   "sezon", "pora", "kamera", "szablon", "ustalone", "znaki", "opcje", "glos", "wymowa",
                                   "komentarz_t", "obiekt", "obiekt_nazwa", "nazwy", "stroj_id", "stroj_tryb", "reakcja",
                                   "stroj_nazwa", "nagrywa", "sylwetka", "klatka")}


def pierwsza_klatka_potrzebna(p):
    """Rolka z promptu musi najpierw zrobic (i zaplacic) klatke albo zdjecie tla (3.5.2: zdjecie usera = nie)."""
    import pierwsza_klatka
    return pierwsza_klatka.potrzebna(p)


def _rozstrzygnij_glos(opcje):
    """Od 3.1 model wideo NIGDY nie mowi komentarza: "auto" (i stare "model") -> "tts" = wideo z samym otoczeniem, komentarz osoby
    nagrywajacej dogrywa ElevenLabs po generacji. Gdy ElevenLabs nie dziala, rolka wychodzi bez komentarza (wpis w dzienniku,
    "Dograj glos" w panelu) - nie wraca do mowy z modelu."""
    o = dict(opcje or {})
    if (o.get("glos") or "auto") in ("auto", "model"):
        o["glos"] = "tts"
    return o


def _zbuduj_z_promptu(slug, opcje):
    import scenariusz
    o = _rozstrzygnij_glos(opcje)
    sc = scenariusz.zbuduj(slug, o)
    sc["ustalone"]["glos"] = "tts"
    return sc


def wycena_z_promptu(slug, opcje, z_cena=True, log=None):
    """Buduje prompt rolki z promptu (scenariusz.zbuduj) i - z_cena=True - pyta Higgsfield o cene (`generate cost`, 0 kr,
    NIC nie tworzy). Zwraca slownik dla panelu/CLI: prompt, znaki, obrazy (nazwy), rozdzielczosc, dlugosc, model, ustalone,
    ostrzezenia + kr (wycena), saldo, dzis {wydano (z rezerwa w toku), limit}, min_kredyty, max_kredyty_na_rolke,
    mozna (bezpieczniki przepuszczaja), powody (czemu nie). ValueError przy zlych opcjach."""
    sc = _zbuduj_z_promptu(slug, opcje)
    ust = baza.ustawienia_modelki(slug)
    nazwa = DOSTAWCA_Z_PROMPTU
    min_k, max_k = bezpiecznik(ust, nazwa)
    wynik = {k: sc.get(k) for k in ("prompt", "znaki", "limit", "ostrzezenia", "ustalone", "model", "rozdzielczosc", "dlugosc",
                                    "tytul", "miejsce", "miejsce_nazwa", "pomysl_id", "wlosy_zmienione", "komentarz", "sezon",
                                    "pora", "kamera", "glos", "wymowa", "komentarz_t", "obiekt", "obiekt_nazwa", "nazwy",
                                    "stroj_id", "stroj_tryb", "stroj_nazwa", "reakcja", "nagrywa")}
    wynik["ostrzezenia"] = list(wynik.get("ostrzezenia") or [])
    if sc.get("komentarz"):
        try:
            import komentarz_glos
            ok, kom = komentarz_glos.tts_dostepne()
        except Exception as e:      # sprawdzenie klucza nie moze zepsuc wyceny
            ok, kom = False, str(e)
        if not ok:
            wynik["ostrzezenia"].append(f"ElevenLabs nie dziala ({kom}) - rolka wyjdzie bez komentarza zza kamery (model wideo "
                                        f"nic nie mowi); dograsz go potem przyciskiem 'Dograj glos'.")
    wynik.update({"obrazy": [os.path.basename(o) for o in sc["obrazy"]], "kr": None, "saldo": None,
                  "stroj_plik": os.path.basename(sc["stroj_plik"]) if sc.get("stroj_plik") else None,
                  "dzis": {"wydano": baza.wydano_z_rezerwa(nazwa), "limit": baza.limit_dzienny(nazwa)},
                  "min_kredyty": min_k, "max_kredyty_na_rolke": max_k, "mozna": False, "powody": [], "dostawca": nazwa,
                  "kr_wideo": None, "kr_klatka": None, "kr_max": None, "klatka": None})
    kl = sc.get("klatka")
    if kl:
        import pierwsza_klatka
        import sekrety
        kontrola = bool(kl.get("kontrola")) and bool(sekrety.klucz("openrouter"))
        wynik["klatka"] = {"tryb": kl.get("tryb") or "start", "model": kl["model"], "nazwa_modelu": kl.get("nazwa_modelu"),
                           "prompt": kl["prompt"],
                           "znaki": kl.get("znaki"), "obrazy": [os.path.basename(o) for o in kl["obrazy"]],
                           "tlo": os.path.basename(kl["tlo"]) if kl.get("tlo") else None,
                           "folder_tel": os.path.join(pierwsza_klatka.folder_tel(), sc["miejsce"]),
                           "kontrola": kontrola, "kontrola_ustawiona": bool(kl.get("kontrola")),
                           "max_dodatkowych": int(kl.get("max_dodatkowych") or 0) if kontrola else 0}
    if not z_cena:
        return wynik
    d = dostawcy.dostawca(nazwa)
    p = {"id": None, "typ": "prompt", "prompt_higgsfield": sc["prompt"], "z_promptu": _dane_z_promptu(sc)}
    try:
        k = d.koszt(zlecenie(slug, p, ust, do_wyceny=True))
    except dostawcy.BladDostawcy as e:
        wynik["powody"].append(f"Higgsfield nie podal ceny: {e}")
        return wynik
    wynik["kr_wideo"] = k
    if kl and k is not None and not pierwsza_klatka_potrzebna(p):
        wynik["kr_klatka"], wynik["kr_max"] = 0, k      # 3.5.2: tlo = zdjecie usera - nic do generowania (0 kr)
    elif kl and k is not None:
        # 3.5: cena = wideo + JEDNA klatka (w gore: 2,75 -> 3); z kontrola AI moze dojsc do max_dodatkowych klatek (kr_max)
        import pierwsza_klatka
        try:
            k, k_kl, k_max = pierwsza_klatka.wycena_rolki(p, k)
        except dostawcy.BladDostawcy as e:
            wynik["powody"].append(f"Higgsfield nie podal ceny pierwszej klatki: {e}")
            return wynik
        if k_kl is None:
            wynik["powody"].append("Higgsfield nie podal ceny pierwszej klatki - sprobuj jeszcze raz.")
            return wynik
        wynik["kr_klatka"], wynik["kr_max"] = k_kl, k_max
    try:
        saldo = d.saldo()
    except dostawcy.BladDostawcy as e:
        saldo = None
        wynik["powody"].append(f"nie moge sprawdzic salda Higgsfield: {e}")
    wynik["kr"], wynik["saldo"] = k, saldo
    wydano, limit = wynik["dzis"]["wydano"], wynik["dzis"]["limit"]
    if k is None:
        wynik["powody"].append("Higgsfield nie podal ceny - sprobuj jeszcze raz.")
    else:
        if k > max_k:
            wynik["powody"].append(f"{k} kr to wiecej niz bezpiecznik {max_k} kr na rolke - wybierz krotsza rolke albo 720p.")
        if saldo is not None and saldo - k < min_k:
            wynik["powody"].append(f"po tej rolce zostaloby {saldo - k} kr, a minimum to {min_k} kr.")
        if limit and wydano + k > limit:
            wynik["powody"].append(f"dzis wydano {wydano} z {limit} kr - ta rolka ({k} kr) przekroczylaby dzienny limit.")
    wynik["mozna"] = not wynik["powody"]
    if log:
        log(f"z promptu: {sc['model']} {sc['dlugosc']} s {sc['rozdzielczosc']}, {len(sc['obrazy'])} zdjec, "
            f"{sc['znaki']} znakow -> {k} kr" + (f" (wideo {wynik['kr_wideo']} + klatka {wynik['kr_klatka']})" if kl else "")
            + ("" if wynik["mozna"] else f" ({'; '.join(wynik['powody'])})"))
    return wynik


def dodaj_z_promptu(slug, opcje, prompt=None, kr=None, **pola):
    """Tworzy pomysl 'nowy' typu 'prompt' z ZAMROZONYM promptem i lista zdjec (bez wysylania). prompt = tekst po recznej
    poprawce (sprawdzany: limit znakow, numery zdjec); kr = wycena, ktora user widzial (zapis w pomysle). pola = dodatkowe pola
    pomyslu (autopilot 3.3: autopilot_z_promptu=True - jego dzienny licznik). Zwraca id."""
    import scenariusz
    sc = _zbuduj_z_promptu(slug, opcje)
    tekst = (prompt or "").strip() or sc["prompt"]
    if tekst != sc["prompt"]:
        bledy, _ = scenariusz.sprawdz(tekst, sc["model"], len(sc["obrazy"]))
        if bledy:
            raise ValueError(" ".join(bledy))
    zp = _dane_z_promptu(sc)
    if zp.get("klatka"):
        # 3.5: pierwsza klatka - zdjecie usera (tlo) jako KOPIA bez EXIF/GPS; zatwierdzona cena klatki (przed kazda klatka
        # cena jeszcze raz - wyzsza = nic nie idzie); cena samego wideo do wznowienia po restarcie
        import pierwsza_klatka
        kl = dict(zp["klatka"])
        tlo_usera = pierwsza_klatka.tryb_tla(kl) and bool(kl.get("tlo"))
        if kl.get("tlo"):
            kopia = pierwsza_klatka.kopia_tla(slug, kl["tlo"])
            kl["tlo_oryginal"], kl["tlo"] = kl["tlo"], kopia
            if not pierwsza_klatka.tryb_tla(kl):
                kl["obrazy"] = [kopia] + list(kl["obrazy"][1:])
        try:
            kl["wycena"] = pierwsza_klatka.cena(kl)
        except dostawcy.BladDostawcy:
            kl["wycena"] = None
        zp["klatka"] = kl
        if kr is not None and tlo_usera:
            zp["wycena_wideo"] = int(kr)        # 3.5.2: tlo = zdjecie usera (0 kr) - cala wycena to wideo
        elif kr is not None and kl["wycena"] is not None:
            zp["wycena_wideo"] = int(kr) - pierwsza_klatka.do_limitu(kl["wycena"])
    zp["opcje"] = {k: v for k, v in (opcje or {}).items() if k not in ("ustalone", "asystent")}
    if isinstance((opcje or {}).get("asystent"), dict):
        zp["asystent"] = {k: opcje["asystent"].get(k) for k in ("dlaczego", "zrodlo", "podsumowanie")}
    zp["wycena"] = kr
    zp["prompt_reczny"] = tekst != sc["prompt"]
    dodatki = {k: v for k, v in pola.items() if k not in ("typ", "z_promptu", "koszt", "resolution", "model", "stroj_bib")}
    pid = baza.dodaj_pomysl(slug, sc["tytul"] or f"z promptu: {sc['miejsce_nazwa']}", tekst, stroj=sc.get("stroj_plik"),
                            typ="prompt", z_promptu=zp, koszt=kr, resolution=sc["rozdzielczosc"], model=sc["model"],
                            **({"stroj_bib": sc["stroj_id"]} if sc.get("stroj_tryb") == "biblioteka" else {}), **dodatki)
    _zdarzenie(None, slug, "info", f"#{pid}: rolka z promptu{' (autopilot)' if dodatki.get('autopilot_z_promptu') else ''} - "
               f"{sc['miejsce_nazwa']}, {sc['model']} {sc['dlugosc']} s {sc['rozdzielczosc']}"
               + (f", wycena {kr} kr" if kr is not None else ""), pomysl=pid)
    return pid


def cmd_z_promptu(args):
    """python fabryka.py --modelka noemi z-promptu ["pomysl po polsku"] [--gotowy galeria_fastfood] [--dlugosc 10] [--sucho]"""
    slug = _slug(args.modelka)
    opcje = {"tekst": args.tekst or "", "pomysl_id": args.gotowy or "", "miejsce": args.miejsce or "", "model": args.model,
             "dlugosc": args.dlugosc, "rozdzielczosc": args.rozdzielczosc, "stroj": args.stroj, "komentarz": args.komentarz,
             "reakcja": args.reakcja, "sezon": args.sezon, "pora": args.pora, "kamera": args.kamera, "glos": args.glos,
             "wymowa": args.wymowa, "nazwy": args.nazwy, "obiekt": args.obiekt or "",
             "wlosy": {"kolor": args.wlosy, "fryzura": args.fryzura, "grzywka": args.grzywka}}
    if args.nagrywa:
        opcje["nagrywa"] = args.nagrywa
    # 3.5.1: pierwsza klatka z CLI (--klatka/--klatka-model/--tlo) - asystent ich nie dobiera, wiec musza przezyc --asystent
    # (test 2026-10-08: `--asystent --klatka-model nano_banana_pro` dalej robil GPT Image 2.5 i liczyl 2,75 kr)
    klatka_cli = {k: v for k, v in (("klatka", args.klatka), ("klatka_model", args.klatka_model), ("tlo", args.tlo)) if v}
    opcje.update(klatka_cli)
    if args.gotowy and not args.tekst:
        import scenariusz
        opcje["tekst"] = scenariusz.POMYSLY_PO_ID[args.gotowy]["pl"] if args.gotowy in scenariusz.POMYSLY_PO_ID else ""
    if args.asystent:
        import asystent
        reczne = {k: v for k, v in opcje.items() if k in ("miejsce", "kamera", "reakcja", "obiekt", "nagrywa")
                  and v not in ("", "auto", "losowa")}
        reczne.update(model=args.model, dlugosc=args.dlugosc)
        a = asystent.dobierz(slug, opcje["tekst"], pomysl_id=args.gotowy, zablokowane=reczne)
        opcje = dict(a["opcje"], asystent=a, **klatka_cli)
        print(f"asystent ({a['zrodlo']}): {a['podsumowanie']}\n  dlaczego: {a['dlaczego']}" + (f"\n  {a['uwaga']}" if a["uwaga"] else ""))
    w = wycena_z_promptu(slug, opcje, z_cena=True)
    print(w["prompt"])
    print(f"\n--- {w['znaki']} znakow, {len(w['obrazy'])} zdjec, {w['model']} {w['dlugosc']} s {w['rozdzielczosc']}, "
          f"miejsce: {w['miejsce_nazwa']}")
    for u in w["ostrzezenia"]:
        print(f"[UWAGA] {u}")
    if w.get("klatka"):
        kl = w["klatka"]
        jak = ("zdjecie tla - samo miejsce, ostatnia referencja wideo" if kl.get("tryb") == "tlo" else "pierwsza klatka")
        print(f"\n--- {jak} ({kl['nazwa_modelu']}, {kl['znaki']} znakow, zdjecia: {', '.join(kl['obrazy']) or 'brak'}; tlo: "
              f"{kl['tlo'] or 'generowane (brak zdjec w ' + kl['folder_tel'] + ')'}; kontrola AI: "
              f"{'tak' if kl['kontrola'] else 'nie'}):\n{kl['prompt']}")
        print(f"cena: wideo {w['kr_wideo']} kr + klatka {w['kr_klatka']} kr" + (f" (z dodatkowymi klatkami max {w['kr_max']} kr)"
                                                                               if w.get("kr_max") and w["kr_max"] != w["kr"] else ""))
    print(f"cena: {w['kr']} kr | saldo {w['saldo']} | dzis {w['dzis']['wydano']}/{w['dzis']['limit']} | "
          f"max/rolka {w['max_kredyty_na_rolke']} | min_kredyty {w['min_kredyty']}")
    if not w["mozna"]:
        print("NIE MOZNA: " + "; ".join(w["powody"]))
        return 1
    if args.sucho:
        print("(--sucho: nic nie wyslane, 0 kr)")
        return 0
    if not args.tak:
        odp = input(f"Zrobic te rolke za {w['kr']} kr? [t/N] ").strip().lower()
        if odp not in ("t", "tak", "y"):
            print("anulowano")
            return 0
    opcje["ustalone"] = w["ustalone"]
    pid = dodaj_z_promptu(slug, opcje, kr=w["kr"])
    cena = w["kr"]
    wynik = generuj(slug, ids=[pid], potwierdz=lambda p, k, *a: k <= cena, timeout=args.timeout)
    print(json.dumps(wynik, ensure_ascii=False))
    return 0 if wynik.get("wygenerowane") or wynik.get("w_toku") else 1


def podglad(slug, pid, log=None):
    """Tani podglad rolki (Seedance `draft`, ~21 kr zamiast 45-72): ten sam prompt i referencje, wynik w
    wyniki/NNN_nazwa.podglad.mp4, pomysl zostaje 'nowy' (pelna generacja dopiero, gdy user kliknie Zrob rolke).
    Zwraca sciezke pliku podgladu."""
    log = log or _log
    ust = baza.ustawienia_modelki(slug)
    p = baza.pomysl(slug, pid)
    nazwa_dostawcy = DOSTAWCA_Z_PROMPTU if z_promptu(p) else (ust.get("dostawca") or "higgsfield")
    if nazwa_dostawcy != "higgsfield":
        raise ValueError("Tani podglad dziala tylko dla Higgsfield (Seedance draft).")
    if z_promptu(p) and (p.get("z_promptu") or {}).get("model") != "seedance_2_5":
        raise ValueError("Tani podglad (draft) jest tylko dla Seedance 2.5.")
    if z_promptu(p) and (p.get("z_promptu") or {}).get("klatka"):
        import pierwsza_klatka          # 3.5: prompt "rusz od pierwszej klatki" bez klatki nie ma sensu
        if not pierwsza_klatka.gotowa(p):
            raise ValueError("Tani podglad rolki z pierwsza klatka dziala dopiero z gotowa klatka - zrob rolke (najpierw powstanie "
                             "zdjecie) albo zrob nowa rolke z wylaczona pierwsza klatka.")
    d = dostawcy.dostawca(nazwa_dostawcy)
    if not p.get("prompt_higgsfield"):
        raise ValueError(f"#{pid} nie ma promptu.")
    z = zlecenie(slug, p, ust)
    z["parametry"] = dict(z.get("parametry") or {}, draft=True)
    saldo = d.saldo()
    k = d.koszt(z)
    if k is None:
        k = 25
    min_kredyty, _ = bezpiecznik(ust, nazwa_dostawcy)
    limit_dnia, wydano = baza.limit_dzienny(nazwa_dostawcy), baza.wydano_z_rezerwa(nazwa_dostawcy)
    if saldo - k < min_kredyty:
        raise ValueError(f"Podglad ({k} kr) zostawilby {saldo - k} < min_kredyty {min_kredyty}.")
    if limit_dnia and wydano + k > limit_dnia:
        raise ValueError(f"Podglad ({k} kr) przekroczylby limit dzienny ({wydano}+{k} > {limit_dnia}).")
    _zdarzenie(log, slug, "info", f"#{pid}: tani podglad (draft, ~{k} kr)", pomysl=pid)
    job = d.generuj(z, timeout="20m", log=log)
    urls = job.get("urls") or []
    # koszt z wyceny joba (udany = k, odrzucony = 0), nie z roznicy salda - reczne generacje w apce nie zjadaja limitu fabryki
    zuzyte = d.koszt_joba(job, k) if hasattr(d, "koszt_joba") else (k if urls else 0)
    baza.dopisz_wydatek(zuzyte, nazwa_dostawcy, job_id=job.get("job_id"))
    if not urls:
        raise RuntimeError(job.get("blad") or f"brak URL podgladu (status {job.get('status')})")
    nazwa = _nazwa_wyniku(p)
    cel = os.path.join(baza.folder_wynikow(slug), f"{pid:03d}_{nazwa}.podglad.mp4")
    d.pobierz(urls[0], cel)
    baza.aktualizuj_pomysl(slug, pid, podglad_plik=cel, podglad_koszt=zuzyte)
    _klatki_podgladu = os.path.join(baza.folder_klatek(slug), f"{pid:03d}_podglad.jpg")
    try:
        klatki.arkusz(cel, _klatki_podgladu, ile=6)
        baza.aktualizuj_pomysl(slug, pid, klatki_podgladu=_klatki_podgladu)
    except Exception:
        pass
    _zdarzenie(log, slug, "ok", f"#{pid}: podglad gotowy ({zuzyte} kr, {z.get('resolution')}) -> {cel}", pomysl=pid, plik=cel)
    return cel


def _lipsync_po_generacji(slug, p, plik, ust, log):
    """lipsync_auto: filmik ma sparowany glos (<nazwa>.audio.mp3) -> lipsync po generacji."""
    audio = p.get("audio") or baza.audio_dla_zrodla(p.get("zrodlo"))
    if not (ust.get("lipsync_auto") and audio and os.path.isfile(audio) and plik and os.path.isfile(plik)):
        return None
    try:
        import lipsync
        return lipsync.zrob(slug, plik, audio, pomysl_id=p["id"], log=log)
    except Exception as e:
        _zdarzenie(log, slug, "blad", f"#{p['id']}: lipsync nie wyszedl: {e}", pomysl=p["id"])
        return None


def cmd_generuj(args):
    slug = _slug(args.modelka)
    def pytaj(p, k, saldo_po, dzis_po, limit):
        odp = input(f"#{p['id']}: {k} kr, saldo po: {saldo_po}, dzis po: {dzis_po}/{limit}. Generowac? [t/N] ").strip().lower()
        return odp in ("t", "tak", "y")
    potwierdz = None if args.tak else pytaj
    w = generuj(slug, ids=[args.id] if args.id else None, limit=args.limit, potwierdz=potwierdz,
                dry_run=args.dry_run, bez_referencji=args.bez_referencji, timeout=args.timeout)
    return 1 if w.get("stop") in ("brak referencji", "zajete") or (w.get("stop") or "").startswith("saldo") else 0


BEZ_MEDIA_TOOL = "Media Tool nie zainstalowany - rolka bez prania (zapisana w 'tu rolki zrobione')"


def _postprodukcja(slug, pid, surowy, nazwa, ust, log=None):
    """Media Tool (pranie) -> folder gotowych. Zwraca sciezke gotowego pliku."""
    log = log or _log
    gotowe_dir = baza.folder_gotowych(slug)
    cel = os.path.join(gotowe_dir, f"{pid:03d}_{nazwa}.mp4")
    import mediatool
    if ust.get("mediatool") and not mediatool.dostepny():
        # Media Tool nie zainstalowany (np. inny komputer): rolka i tak trafia do gotowych - nieuprana, z jasnym wpisem. Nie blad.
        import shutil
        shutil.copy2(surowy, cel)
        baza.aktualizuj_pomysl(slug, pid, status="gotowe", plik_wynikowy=cel, bez_prania=True)
        _zdarzenie(log, slug, "uwaga", f"#{pid}: {BEZ_MEDIA_TOOL} -> {cel}", pomysl=pid)
    elif ust.get("mediatool"):
        try:
            cel = mediatool.pierz_wideo(surowy, gotowe_dir, nazwa_wyniku=os.path.basename(cel))
            baza.aktualizuj_pomysl(slug, pid, status="gotowe", plik_wynikowy=cel, bez_prania=None)
        except Exception as e:
            _zdarzenie(log, slug, "uwaga", f"#{pid}: Media Tool nie wyszedl ({e}) - zostawiam surowy plik w wyniki/, status wygenerowany", pomysl=pid)
            return None
    else:
        import shutil
        shutil.copy2(surowy, cel)
        baza.aktualizuj_pomysl(slug, pid, status="gotowe", plik_wynikowy=cel)
    _klatki_wyniku(slug, pid, cel, log)
    return cel


def _klatki_wyniku(slug, pid, plik, log=None):
    """Siatka klatek GOTOWEJ rolki (modelki/<slug>/klatki/NNN_wynik.jpg) - podglad w panelu i na telefonie bez otwierania pliku."""
    try:
        cel = os.path.join(baza.folder_klatek(slug), f"{pid:03d}_wynik.jpg")
        klatki.arkusz(plik, cel, ile=6)
        baza.aktualizuj_pomysl(slug, pid, klatki_wyniku=cel)
        return cel
    except Exception as e:
        (log or _log)(f"#{pid}: podglad klatek wyniku nie wyszedl: {e}")
        return None


# ---------------- ocena (Virality Predictor) ----------------

def cmd_ocen(args):
    slug = _slug(args.modelka)
    p = baza.pomysl(slug, args.id)
    plik = p.get("plik_wynikowy")
    if not plik or not os.path.isfile(plik):
        print(f"#{p['id']} nie ma pobranego pliku wynikowego.")
        return 1
    try:
        job = hf.generuj("brain_activity", {}, {"video": plik}, wait=True, wait_timeout="15m")
    except hf.HiggsfieldBlad as e:
        print(f"[BLAD] {e}")
        return 1
    tekst = json.dumps(job, ensure_ascii=False)
    baza.aktualizuj_pomysl(slug, p["id"], ocena=tekst[:4000])
    print(tekst[:3000])
    return 0


def cmd_wznow(args):
    """Dokoncz rolki i zdjecia (podmiana postaci) w toku (wszystkie persony albo --modelka)."""
    import zdjecia_swap
    slugi = [_slug(args.modelka)] if args.modelka else baza.lista_modelek()
    for slug in slugi:
        w = wznow_w_toku(slug, timeout=args.timeout)
        if w["wygenerowane"] or w["bledy"] or w["w_toku"]:
            print(f"{slug}: gotowe {w['wygenerowane']}, nie wyszlo {len(w['bledy'])}, dalej w toku {len(w['w_toku'])}")
        z = zdjecia_swap.wznow_w_toku(slug)
        if z["zrobione"] or z["bledy"] or z["w_toku"]:
            print(f"{slug} zdjecia: gotowe {z['zrobione']}, nie wyszlo {len(z['bledy'])}, dalej w toku {len(z['w_toku'])}")
    return 0


# ---------------- postprodukcja ----------------

def cmd_gotowe(args):
    slug = _slug(args.modelka)
    baza.aktualizuj_pomysl(slug, args.id, status="gotowe")
    print(f"#{args.id} -> gotowe")
    return 0


def podpis(slug, pid):
    """Podpis z banku tekstow (+ hashtagi persony z profilu) -> wyniki/NNN_podpis.txt. Zwraca (tekst, sciezka) albo (None, None)."""
    p = baza.pomysl(slug, pid)
    tekst = baza.losuj_tekst(slug)
    if not tekst:
        return None, None
    hashtagi = (baza.profil_modelki(slug).get("hashtagi") or "").strip()
    if hashtagi and hashtagi not in tekst:
        tekst = f"{tekst}\n\n{hashtagi}"
    cel = os.path.join(baza.folder_wynikow(slug), f"{p['id']:03d}_podpis.txt")
    with open(cel, "w", encoding="utf-8") as f:
        f.write(tekst + "\n")
    baza.aktualizuj_pomysl(slug, pid, podpis=tekst)
    return tekst, cel


def cmd_podpis(args):
    slug = _slug(args.modelka)
    tekst, cel = podpis(slug, args.id)
    if not tekst:
        print("Bank tekstow pusty albo wszystko uzyte - dopisz teksty w panelu.")
        return 1
    print(tekst)
    print(f"-> {cel}")
    return 0


# ---------------- pranie reczne ----------------

def pierz(slug, pid=None, plik=None, log=None):
    """Media Tool na wyniku pomyslu albo dowolnym pliku. Zwraca sciezke gotowego pliku albo None."""
    log = log or _log
    import mediatool
    if plik:
        nazwa = _bezpieczna_nazwa(os.path.splitext(os.path.basename(plik))[0])
        return mediatool.pierz_wideo(plik, baza.folder_gotowych(slug), nazwa_wyniku=f"{nazwa}.mp4", log=log)
    p = baza.pomysl(slug, pid)
    plik = p.get("plik_wynikowy")
    if not plik or not os.path.isfile(plik):
        raise ValueError(f"#{p['id']} nie ma pliku wynikowego.")
    nazwa = _bezpieczna_nazwa(os.path.splitext(os.path.basename(p.get("zrodlo") or f"pomysl_{p['id']}"))[0])
    ust = dict(baza.ustawienia_modelki(slug), mediatool=True)
    return _postprodukcja(slug, p["id"], plik, nazwa, ust, log=log)


def cmd_pierz(args):
    slug = _slug(args.modelka)
    if not args.plik and not args.id:
        print("Podaj id pomyslu albo --plik x.mp4")
        return 1
    cel = pierz(slug, pid=args.id, plik=args.plik)
    print(cel or "nie wyszlo")
    return 0 if cel else 1


# ---------------- zdjecia / lipsync / autopilot (osobne moduly) ----------------

def cmd_zdjecia(args):
    import zdjecia
    slug = _slug(args.modelka)
    w = zdjecia.generuj(slug, ile=args.ile, prompt=args.prompt, dry_run=args.dry_run, stroj=args.stroj)
    return 0 if not w.get("stop") else 1


def cmd_zdjecie_swap(args):
    """python fabryka.py --modelka noemi zdjecie-swap foto.jpg [--model seedream_v5_pro] [--proporcje jak_zdjecie|9:16]
    [--jakosc high] [--rozdzielczosc 2k] [--ile 1] [--stroj ze_zdjecia|<id z biblioteki>] [--dopisek ".."] [--sucho] [--tak]
    Podmiana postaci na zdjeciu (zdjecia_swap.py): --sucho = tylko prompt i cena z `generate cost` (0 kr, nic nie wysyla)."""
    import zdjecia_swap
    slug = _slug(args.modelka)
    if not os.path.isfile(args.plik):
        print(f"[BLAD] Nie ma pliku {args.plik}")
        return 1
    opcje = {"model": args.model, "proporcje": args.proporcje, "jakosc": args.jakosc, "rozdzielczosc": args.rozdzielczosc,
             "ile": args.ile, "stroj": args.stroj, "dopisek": args.dopisek or ""}
    sw = zdjecia_swap.zbuduj(slug, args.plik, opcje)
    w = zdjecia_swap.wycena(slug, opcje, zrodlo=args.plik, swieza=True)
    print(sw["prompt"])
    ost = len(sw["obrazy"]) - 1 if sw["stroj_id"] else None
    print(f"\n--- {sw['znaki']} znakow, {len(sw['obrazy'])} zdjec (1 = wstawione, 2-{sw['referencje'] + 1} = persona"
          + (f", {ost + 1} = stroj {sw['stroj_nazwa']}" if ost else "") + f"), {sw['opis']}"
          + (" (proporcje jak zdjecie)" if sw["proporcje_jak_zdjecie"] else ""))
    for u in sw["ostrzezenia"]:
        print(f"[UWAGA] {u}")
    print(f"cena: {zdjecia_swap._kr(w['kr_sztuka'])} za zdjecie x {w['ile']} = {zdjecia_swap._kr(w['kr'])} (do limitu dnia: "
          f"{w['kr_limit']} kr) | saldo {w['saldo']} | dzis {w['dzis']['wydano']}/{w['dzis']['limit']} | min_kredyty {w['min_kredyty']}")
    if not w["mozna"]:
        print("NIE MOZNA: " + "; ".join(w["powody"]))
        return 1
    if args.sucho:
        print("(--sucho: nic nie wyslane, 0 kr)")
        return 0
    if not args.tak:
        odp = input(f"Zrobic {w['ile']} zdj. za {zdjecia_swap._kr(w['kr'])}? [t/N] ").strip().lower()
        if odp not in ("t", "tak", "y"):
            print("anulowano")
            return 0
    zrodlo = zdjecia_swap.zapisz_zrodlo(slug, args.plik)
    wynik = zdjecia_swap.generuj(slug, zrodlo, opcje, kr=w["kr_sztuka"], timeout=args.timeout)
    print(json.dumps(wynik, ensure_ascii=False))
    return 0 if wynik.get("zrobione") or wynik.get("w_toku") else 1


def cmd_foldery(args):
    """Tworzy foldery persony na pulpicie (tu wrzucasz rolki / tu rolki zrobione / tu zdjecia zrobione) i pokazuje sciezki."""
    slugi = [_slug(args.modelka)] if args.modelka else baza.lista_modelek()
    for slug in slugi:
        w = baza.przygotuj_foldery_pulpitu(slug)
        print(f"{slug}:")
        for klucz, opis in (("zrodla_dir", "wrzucasz tu"), ("wyniki_dir", "gotowe rolki"), ("zdjecia_dir", "gotowe zdjecia")):
            print(f"  {opis:14} {w['foldery'].get(klucz, '?')}" + ("   (nowe)" if klucz in w["zmienione"] else ""))
    return 0


def cmd_nsfw(args):
    w = wskazowki_nsfw(_slug(args.modelka))
    print(f"odrzucone przez filtr: {w['odrzucone']} (ostatnie {w['dni']} dni: {w['odrzucone_ostatnio']})")
    for k, v in w["slowa"].items():
        if v:
            print(f"ryzykowne slowa w prompcie {k}: {', '.join(v)}")
    for linia in w["wskazowki"]:
        print(f"- {linia}")
    return 0


def cmd_lipsync(args):
    import lipsync
    slug = _slug(args.modelka)
    if args.id and not args.wideo:
        p = baza.pomysl(slug, args.id)
        wideo = p.get("plik_wynikowy")
        if not wideo or not os.path.isfile(wideo):
            print(f"#{p['id']} nie ma pliku wynikowego.")
            return 1
    else:
        wideo = args.wideo
    if not wideo or not os.path.isfile(wideo):
        print("Podaj --wideo <plik.mp4> albo id pomyslu z wynikiem.")
        return 1
    audio = args.audio
    if not audio and args.id:
        audio = baza.pomysl(slug, args.id).get("audio")
    if not audio or not os.path.isfile(audio):
        print("Podaj --audio <glos.mp3> (albo wrzuc <nazwa>.audio.mp3 obok filmiku zrodlowego).")
        return 1
    wynik = lipsync.zrob(slug, wideo, audio, pomysl_id=args.id, styl=args.styl)
    print(wynik or "nie wyszlo")
    return 0 if wynik else 1


def cmd_autopilot(args):
    import autopilot
    argv = ["--raz"] if args.raz else []
    if args.modelka:
        argv += ["--modelka", args.modelka]
    return autopilot.main(argv)


# ---------------- ustawienia ----------------

def cmd_budzet(args):
    if not args.pary:
        print(json.dumps(baza.budzet(), ensure_ascii=False, indent=2))
        return 0
    for para in args.pary:
        k, v = para.split("=", 1)
        if k == "max_kredyty_dziennie":
            baza.zapisz_limit_dzienny(int(v), args.dostawca)
        else:
            baza.zapisz_budzet(**{k: int(v)})
    print(json.dumps(baza.budzet(), ensure_ascii=False, indent=2))
    return 0


def cmd_ustaw(args):
    slug = _slug(args.modelka)
    if not args.pary:
        print(json.dumps(baza.ustawienia_modelki(slug), ensure_ascii=False, indent=2))
        return 0
    zmiany = {}
    for para in args.pary:
        if "=" not in para:
            raise SystemExit(f"Oczekuje klucz=wartosc, dostalem: {para}")
        k, v = para.split("=", 1)
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            pass
        zmiany[k] = v
    print(json.dumps(baza.zapisz_ustawienia(slug, **zmiany), ensure_ascii=False, indent=2))
    return 0


# ---------------- main ----------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="rolki-ai: fabryka rolek (Higgsfield CLI / yapper.so + Media Tool + sync.so)")
    ap.add_argument("--modelka", "-m", help="slug modelki (domyslnie aktywna)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("konto", help="saldo kredytow Higgsfield / plan"); s.add_argument("--json", action="store_true"); s.set_defaults(f=cmd_konto)
    s = sub.add_parser("model", help="schema modelu z CLI (parametry, media)"); s.add_argument("jst", nargs="?", default="seedance_2_5"); s.set_defaults(f=cmd_model)
    s = sub.add_parser("modele", help="lista modeli dostawcy"); s.add_argument("--dostawca", default="higgsfield", choices=dostawcy.NAZWY); s.add_argument("--typ", choices=("image", "video", "audio", "text")); s.add_argument("--json", action="store_true"); s.set_defaults(f=cmd_modele)
    s = sub.add_parser("glosy", help="glosy Higgsfield do TTS (voices list)"); s.add_argument("--json", action="store_true"); s.set_defaults(f=cmd_glosy)
    s = sub.add_parser("status", help="co w kolejce, co czeka na prompt, saldo"); s.set_defaults(f=cmd_status)
    s = sub.add_parser("diagnoza", help="czy wszystko jest na miejscu (ffmpeg, Higgsfield, Media Tool, Telegram, persony)"); s.set_defaults(f=cmd_diagnoza)
    s = sub.add_parser("skanuj", help="nowe filmiki z wrzutni -> pomysly + klatki"); s.add_argument("--ile", type=int, default=4); s.set_defaults(f=cmd_skanuj)
    s = sub.add_parser("prompt", help="wpisz prompt do pomyslu ('-' = ze stdin)"); s.add_argument("id", type=int); s.add_argument("tekst"); s.set_defaults(f=cmd_prompt)
    s = sub.add_parser("koszt", help="szacunek kredytow (bez generacji)"); s.add_argument("--id", type=int); s.add_argument("--limit", type=int); s.set_defaults(f=cmd_koszt)
    s = sub.add_parser("generuj", help="generacja pozycji 'nowy' z promptem")
    s.add_argument("--id", type=int); s.add_argument("--limit", type=int)
    s.add_argument("--dry-run", action="store_true", help="tylko pokaz komendy")
    s.add_argument("--tak", "-y", action="store_true", help="bez pytania o kazda pozycje")
    s.add_argument("--bez-referencji", action="store_true")
    s.add_argument("--timeout", default="30m")
    s.set_defaults(f=cmd_generuj)
    s = sub.add_parser("z-promptu", help="rolka z promptu: pomysl po polsku -> prompt Seedance + wycena (--sucho = 0 kr) -> generacja")
    s.add_argument("tekst", nargs="?", help="pomysl po polsku (puste = --gotowy albo losowy)")
    s.add_argument("--gotowy", help="id gotowego pomyslu (scenariusz.POMYSLY), np. galeria_fastfood")
    s.add_argument("--miejsce", help="id miejsca (scenariusz.MIEJSCA) albo 'losowe'")
    s.add_argument("--model", default="seedance_2_5",
                   help="seedance_2_5 | seedance_2_5_480p (480p 10 s, ok. 30 kr) | wan3_0_prime (tlo jako referencja) | "
                        "gemini_omni_flash_1_1"); s.add_argument("--dlugosc", type=int, default=10)
    s.add_argument("--rozdzielczosc", default="auto")
    s.add_argument("--stroj", default="biblioteka", help="biblioteka | biblioteka:<id> | odwazny[:<id>] | zdjecia | codzienny | cosplay | plik:<nazwa>")
    s.add_argument("--komentarz", default="losowy"); s.add_argument("--reakcja", default="losowa")
    s.add_argument("--sezon", default="auto"); s.add_argument("--pora", default="auto")
    s.add_argument("--wlosy", default="wlasne"); s.add_argument("--fryzura", default="wlasna"); s.add_argument("--grzywka", default="wlasna")
    s.add_argument("--kamera", default="auto")
    s.add_argument("--glos", default="auto", choices=("auto", "tts"), help="komentarz zawsze ElevenLabs po generacji (model wideo nic nie mowi)")
    s.add_argument("--nagrywa", choices=("chlopak", "dziewczyna"), help="kto nagrywa zza kamery (domyslnie z ustawien persony)")
    s.add_argument("--wymowa", default="zwykla", choices=("zwykla", "fonetyczna"))
    s.add_argument("--nazwy", default="prawdziwe", choices=("prawdziwe", "opisowe")); s.add_argument("--obiekt", help="np. posnania")
    s.add_argument("--asystent", action="store_true", help="asystent dobiera miejsce/stroj/kamere/reakcje/komentarz (OpenRouter albo reguly)")
    s.add_argument("--klatka", choices=("wl", "wyl"), help="3.5: pierwsza klatka (zdjecie -> wideo od niego); domyslnie z ustawien")
    s.add_argument("--klatka-model", help="gpt_image_2_5 | nano_banana_pro | gpt_image_2 | seedream_v5_pro")
    s.add_argument("--tlo", help="auto (zdjecie z Pulpit/ROLKI AI/tla/<miejsce>, gdy jest) | bez | <nazwa pliku>")
    s.add_argument("--sucho", action="store_true", help="tylko prompt i darmowa wycena")
    s.add_argument("--tak", "-y", action="store_true", help="bez pytania o cene"); s.add_argument("--timeout", default="30m")
    s.set_defaults(f=cmd_z_promptu)
    s = sub.add_parser("dograj-glos", help="komentarz ElevenLabs do gotowej rolki z promptu (glos tts) - tylko znaki ElevenLabs")
    s.add_argument("id", type=int); s.set_defaults(f=cmd_dograj_glos)
    s = sub.add_parser("wznow", help="dokoncz rolki w toku (job wyslany przed restartem/timeoutem) - odpytuje ten sam job, nic nie wysyla")
    s.add_argument("--timeout", default="30m"); s.set_defaults(f=cmd_wznow)
    s = sub.add_parser("ocen", help="Virality Predictor na wyniku (kosztuje kredyty)"); s.add_argument("id", type=int); s.set_defaults(f=cmd_ocen)
    s = sub.add_parser("gotowe", help="oznacz pomysl jako gotowy"); s.add_argument("id", type=int); s.set_defaults(f=cmd_gotowe)
    s = sub.add_parser("podpis", help="podpis z banku tekstow -> wyniki/<id>_podpis.txt"); s.add_argument("id", type=int); s.set_defaults(f=cmd_podpis)
    s = sub.add_parser("wgraj", help="wgraj referencje/stroje raz (UUID w cache, szybsze koszt/generuj)"); s.add_argument("--od-nowa", action="store_true"); s.set_defaults(f=cmd_wgraj)
    s = sub.add_parser("pierz", help="Media Tool na wyniku pomyslu (albo --plik dowolny.mp4)"); s.add_argument("id", type=int, nargs="?"); s.add_argument("--plik"); s.set_defaults(f=cmd_pierz)
    s = sub.add_parser("zdjecia", help="zdjecia persony (model obrazu z referencjami; --stroj auto|bez|plik = strój ze stroje/)"); s.add_argument("--ile", type=int, default=1); s.add_argument("--prompt"); s.add_argument("--stroj"); s.add_argument("--dry-run", action="store_true"); s.set_defaults(f=cmd_zdjecia)
    s = sub.add_parser("zdjecie-swap", help="podmiana postaci na zdjeciu: persona w miejsce osoby ze zdjecia (--sucho = prompt + cena, 0 kr)")
    s.add_argument("plik", help="zdjecie, na ktore wstawiamy persone")
    s.add_argument("--model", default="seedream_v5_pro", help="seedream_v5_pro | nano_banana_pro | gpt_image_2_5")
    s.add_argument("--proporcje", default="jak_zdjecie", help="jak_zdjecie (najblizsze do zdjecia) albo np. 9:16, 3:4, 4:5, 1:1")
    s.add_argument("--jakosc", help="tylko GPT Image 2.5: low | medium | high (domyslnie) | xhigh | max")
    s.add_argument("--rozdzielczosc", help="1k | 1.5k | 2k (domyslnie) | 4k - co ma model")
    s.add_argument("--ile", type=int, default=1, help="1-4 zdjec (kazde osobne zlecenie)")
    s.add_argument("--stroj", default="ze_zdjecia", help="ze_zdjecia (ubranie z wstawionego zdjecia) albo id stroju z biblioteki")
    s.add_argument("--dopisek", help="opcjonalny dopisek do promptu")
    s.add_argument("--sucho", action="store_true", help="tylko prompt i darmowa wycena")
    s.add_argument("--tak", "-y", action="store_true", help="bez pytania o cene"); s.add_argument("--timeout", default="15m")
    s.set_defaults(f=cmd_zdjecie_swap)
    s = sub.add_parser("lipsync", help="wideo + glos -> lipsync (sync.so) - tylko recznie, autopilot tego nie robi"); s.add_argument("id", type=int, nargs="?"); s.add_argument("--wideo"); s.add_argument("--audio"); s.add_argument("--styl", choices=("telefon", "czysty", "brak"), help="brzmienie glosu (domyslnie z ustawien: telefon)"); s.set_defaults(f=cmd_lipsync)
    s = sub.add_parser("autopilot", help="petla: telefon -> skanuj -> generuj -> pranie -> zdjecia -> podpisy (--raz = jeden przebieg; bez lipsyncu)"); s.add_argument("--raz", action="store_true"); s.set_defaults(f=cmd_autopilot)
    s = sub.add_parser("foldery", help="foldery na pulpicie: tu wrzucasz rolki / tu rolki zrobione / tu zdjecia zrobione (per persona)"); s.set_defaults(f=cmd_foldery)
    s = sub.add_parser("nsfw", help="czemu filtr tresci odrzuca rolki tej persony (slowa w promptach, liczba odrzucen, wskazowki)"); s.set_defaults(f=cmd_nsfw)
    s = sub.add_parser("budzet", help="limit dzienny kredytow: max_kredyty_dziennie=300 [--dostawca yapper]"); s.add_argument("pary", nargs="*"); s.add_argument("--dostawca", default="higgsfield", choices=dostawcy.NAZWY); s.set_defaults(f=cmd_budzet)
    s = sub.add_parser("ustaw", help="pokaz/zmien ustawienia: klucz=wartosc ..."); s.add_argument("pary", nargs="*"); s.set_defaults(f=cmd_ustaw)

    args = ap.parse_args(argv)
    try:
        return args.f(args) or 0
    except (ValueError, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code in (0, None):
            return 0
        print(f"[BLAD] {e}")
        return 1
    except Przerwano as e:
        print(f"[STOP] {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
