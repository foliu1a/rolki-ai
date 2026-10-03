# -*- coding: utf-8 -*-
"""
fabryka.py - automat: filmik zrodlowy -> Seedance 2.5 Edit (Higgsfield CLI) albo Wan (yapper.so) -> rolka.

Obieg:
  1. Wrzucasz filmiki do wrzutni (zrodla_dir albo modelki/<slug>/zrodla/)
  2. python fabryka.py skanuj          -> kazdy nowy filmik dostaje pomysl (status: nowy) + klatki podgladu + prompt usera
  3. python fabryka.py koszt           -> ile kredytow zjedza pozycje z promptem
  4. python fabryka.py generuj         -> bezpiecznik budzetu, generacja, pobranie, Media Tool, lipsync (status: gotowe)
  5. python fabryka.py zdjecia         -> zdjecia persony (model obrazu z referencjami)
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
import time

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
        wynik.append({"co": "mediatool", "ok": ok, "info": "jest" if ok else f"nie znaleziono w {mediatool.MT_DIR} (pranie wylaczone -> surowe pliki)"})
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
        "do_generacji": [p["id"] for p in nowe if p.get("prompt_higgsfield")],
        "niezeskanowane": [os.path.basename(z) for z in nowe_zrodla(slug)],
        "wrzutnia": baza.folder_zrodel(slug),
        "gotowe_dir": baza.folder_gotowych(slug),
        "referencje": [os.path.basename(r) for r in refs],
        "prompt_a": bool(baza.prompt_bazowy(slug)),
        "prompt_b": bool(baza.prompt_stroj(slug)),
        "dostawca": dostawca,
        "budzet": {
            "dostawca": dostawca,
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
    print(f"modelka: {slug}   dostawca: {s['dostawca']}   model: {ust['model']} / {ust['mode']} / {ust['aspect_ratio']} / {ust['resolution']}")
    print(f"wrzutnia: {s['wrzutnia']}")
    print(f"gotowe:   {s['gotowe_dir']}   (Media Tool: {'tak' if ust.get('mediatool') else 'nie'})")
    print("pomysly: " + ", ".join(f"{k}={s['statystyki'].get(k, 0)}" for k in baza.STATUSY))
    b = s["budzet"]
    print(f"budzet dzienny ({b['dostawca']}): wydano {b['wydano_dzis']}/{b['limit_dzienny']} kr, rolek dzis {b['rolki_dzis']}/{b['max_rolek_dziennie']}")
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
        print(f"kredyty {s['dostawca']}: {d.saldo()}  (min_kredyty={ust['min_kredyty']}, max/rolka={ust['max_kredyty_na_rolke']})")
    except dostawcy.BladDostawcy as e:
        print(f"kredyty {s['dostawca']}: niedostepne ({e})")
    return 0


# ---------------- skanowanie wrzutni ----------------

MAX_SEKUND_ZRODLA = 30   # Seedance 2.5 edit: twardy limit 30 s; user tnie krocej (max_sekund_rolki), bo koszt rosnie z dlugoscia

# Ile kredytow Higgsfield kosztuje sekunda rolki (video_edit = wejscie + wyjscie). 720p i 1080p zmierzone (6 s: 45 / 72 kr),
# 480p szacunek z cennika apki. Tylko do podpowiedzi w panelu - prawdziwa cene mowi `generate cost` przed generacja.
KR_NA_SEKUNDE = {"480p": 3.5, "720p": 7.5, "1080p": 12.0}

# Gotowe zestawy "Jakosc i koszt" (panel -> Ustawienia): co ustawiaja i ile mniej wiecej kosztuje rolka.
PRESETY_JAKOSCI = {
    "oszczednie": {"resolution": "720p", "max_sekund_rolki": 10},
    "normalnie": {"resolution": "720p", "max_sekund_rolki": 15},
    "najlepiej": {"resolution": "1080p", "max_sekund_rolki": 15},
}


def max_sekund_rolki(ust):
    """Dlugosc kawalka/rolki z ustawien, przycieta do 4-30 s (limit Seedance)."""
    try:
        n = int(ust.get("max_sekund_rolki") or MAX_SEKUND_ZRODLA)
    except (TypeError, ValueError):
        n = MAX_SEKUND_ZRODLA
    return max(4, min(MAX_SEKUND_ZRODLA, n))


def szacunek_kosztu_rolki(ust, sekundy=None):
    """Orientacyjny koszt jednej rolki w kredytach Higgsfield (dlugosc x stawka za sekunde dla rozdzielczosci)."""
    sek = float(sekundy) if sekundy else max_sekund_rolki(ust)
    stawka = KR_NA_SEKUNDE.get(str(ust.get("resolution") or "720p"), KR_NA_SEKUNDE["720p"])
    return int(round(sek * stawka))


def preset_jakosci(ust):
    """Ktory zestaw 'Jakosc i koszt' odpowiada ustawieniom persony ('oszczednie'|'normalnie'|'najlepiej'|'wlasne')."""
    for nazwa, pola in PRESETY_JAKOSCI.items():
        if all(str(ust.get(k)) == str(v) for k, v in pola.items()):
            return nazwa
    return "wlasne"


def jakosc_i_koszt(slug, ust=None):
    """Dla panelu: aktualny zestaw, szacunek kosztu rolki i tabela zestawow z kosztami."""
    ust = ust or baza.ustawienia_modelki(slug)
    koszt = szacunek_kosztu_rolki(ust)
    _, max_na_rolke = bezpiecznik(ust, "higgsfield")
    return {
        "preset": preset_jakosci(ust), "resolution": ust.get("resolution"), "max_sekund_rolki": max_sekund_rolki(ust),
        "koszt_rolki": koszt, "koszt_sekundy": KR_NA_SEKUNDE.get(str(ust.get("resolution") or "720p"), KR_NA_SEKUNDE["720p"]),
        "za_drogo": koszt > max_na_rolke, "max_kredyty_na_rolke": max_na_rolke,
        "presety": {n: dict(p, koszt_rolki=szacunek_kosztu_rolki(p, p["max_sekund_rolki"])) for n, p in PRESETY_JAKOSCI.items()},
    }


def ustaw_preset_jakosci(slug, nazwa):
    """Zapisuje zestaw 'Jakosc i koszt' (resolution + max_sekund_rolki) w ustawieniach persony."""
    if nazwa not in PRESETY_JAKOSCI:
        raise ValueError(f"Nieznany zestaw '{nazwa}'. Dozwolone: {', '.join(PRESETY_JAKOSCI)}")
    return baza.zapisz_ustawienia(slug, **PRESETY_JAKOSCI[nazwa])


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
                stroj_oryg = _stroj_dla(zrodlo)
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
                    stroj_k = stroj_oryg or stroj_dom
                    prompt_k = prompt_b if stroj_k else prompt_a
                    opis = f"{os.path.basename(zrodlo)} cz. {i}/{len(kawalki)} ({inf_k['czas']}s, {inf_k['szer']}x{inf_k['wys']})"
                    pid = baza.dodaj_pomysl(slug, opis, prompt_k, zrodlo=kawalek, klatki=folder_k, info_zrodla=inf_k, stroj=stroj_k)
                    if audio_oryg and i == 1:
                        baza.aktualizuj_pomysl(slug, pid, audio=audio_oryg)
                    wynik["nowe"].append(pid)
                    if not prompt_k:
                        wynik["bez_promptu"].append(pid)
                    _zdarzenie(log, slug, "info", f"#{pid}  {opis}", pomysl=pid)
                continue
        folder = os.path.join(folder_klatek, _bezpieczna_nazwa(nazwa))
        try:
            klatki.wytnij(zrodlo, folder, ile=ile_klatek)
            klatki.arkusz(zrodlo, os.path.join(folder, "arkusz.jpg"), ile=6)
        except Exception as e:
            log(f"[UWAGA] klatki dla {nazwa}: {e}")

        stroj = _stroj_dla(zrodlo) or stroj_dom
        if stroj:
            prompt = prompt_b
            wariant = "B: stroj ze zdjecia " + os.path.basename(stroj)
            if ust.get("prompt_auto") and not prompt_b:
                log(f"[UWAGA] {nazwa}: jest zdjecie stroju, ale prompt_stroj (wariant B) jest pusty.")
        else:
            prompt = prompt_a
            wariant = "A: stroj z filmu"
        opis = f"{os.path.basename(zrodlo)} ({inf['czas']}s, {inf['szer']}x{inf['wys']})"
        pid = baza.dodaj_pomysl(slug, opis, prompt, zrodlo=zrodlo, klatki=folder, info_zrodla=inf, stroj=stroj)
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

def zlecenie(slug, p, ust=None):
    """Generyczne zlecenie dla dostawcy (dostawcy/__init__.py opisuje pola)."""
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
        "images": obrazy,
        "duration": int(dur) if dur else None,
        "aspect_ratio": ust.get("aspect_ratio"),
        "resolution": ust.get("resolution"),
        "model": ust.get("model"),
        "mode": ust.get("mode") if ma_zrodlo else (ust.get("mode_bez_zrodla") or ust.get("mode")),
        "generate_audio": ust.get("generate_audio"),
        "soul_id": ust.get("soul_id") or "",
        "parametry": dict(ust.get("dodatkowe_parametry") or {}),
        "dostawca": ust.get("dostawca") or "higgsfield",
        "yapper": dict(ust.get("yapper") or {}),
    }
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
    """Pomysly do policzenia/generacji: 'nowy' z promptem (albo wskazane id - takze 'blad')."""
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
            if wymaga_wideo and not p.get("zrodlo"):
                raise ValueError(f"#{p['id']} nie ma filmiku zrodlowego, a tryb {ust['mode']} go wymaga "
                                 f"(wrzuc plik do wrzutni i zrob skanuj, zmien mode albo ustaw mode_bez_zrodla w Persona -> Generowanie).")
            if not p.get("prompt_higgsfield"):
                raise ValueError(f"#{p['id']} nie ma promptu.")
            lista.append(p)
        return lista
    lista, pominiete = [], []
    for p in baza.lista_pomyslow(slug, "nowy"):
        if not p.get("prompt_higgsfield"):
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
    """Szacunek kredytow (zapisuje p['koszt']). Zwraca {"razem": n, "pozycje": [(id, koszt|None)]}."""
    log = log or _log
    ust = baza.ustawienia_modelki(slug)
    d = dostawcy.dostawca(ust.get("dostawca"))
    lista = kandydaci(slug, ids, limit, log)
    wynik = {"razem": 0, "pozycje": [], "dostawca": d.NAZWA}
    if not lista:
        log("Nic do policzenia (brak pomyslow 'nowy' z promptem).")
        return wynik
    for p in lista:
        try:
            k = d.koszt(zlecenie(slug, p, ust))
        except dostawcy.BladDostawcy as e:
            log(f"#{p['id']}: [BLAD] {e}")
            wynik["pozycje"].append((p["id"], None))
            continue
        wynik["razem"] += k or 0
        wynik["pozycje"].append((p["id"], k))
        baza.aktualizuj_pomysl(slug, p["id"], koszt=k)
        log(f"#{p['id']}: {k if k is not None else '?'} kr   {p['opis']}")
    log(f"razem: {wynik['razem']} kr")
    return wynik


def cmd_koszt(args):
    slug = _slug(args.modelka)
    koszt(slug, ids=[args.id] if args.id else None, limit=args.limit)
    return 0


# ---------------- generacja ----------------

def bezpiecznik(ust, dostawca="higgsfield"):
    """(min_kredyty, max_kredyty_na_rolke) dla dostawcy. yapper ma wlasne (kredyty yapper to inna skala)."""
    if dostawca == "yapper":
        y = ust.get("yapper") or {}
        return int(y.get("min_kredyty") or 0), int(y.get("max_kredyty_na_rolke") or 1000)
    return int(ust["min_kredyty"]), int(ust["max_kredyty_na_rolke"])


def powod_odrzucenia(status, blad=""):
    """Klasa niepowodzenia generacji: 'nsfw' (filtr tresci Higgsfield/Seedance), 'ip' (znana postac/marka),
    'inny' albo None (nic nie wiadomo)."""
    s, b = (status or "").lower(), (blad or "").lower()
    if s in ("nsfw", "moderated") or "nsfw" in b or "moderat" in b or "content policy" in b or "safety" in b or "visual restriction" in b:
        return "nsfw"
    if s == "ip_detected" or "ip_detected" in b or "copyright" in b or "not eligible" in b:
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
    ostatnio = [p for p in odrzucone if (p.get("zaktualizowano") or p.get("utworzono") or "")[:10] >= granica]
    ust = baza.ustawienia_modelki(slug)
    teksty = {"A": baza.prompt_bazowy(slug), "B": baza.prompt_stroj(slug), "zdjecia": "\n".join(baza.prompty_zdjec(slug))}
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
            gdzie = {"A": "prompcie A (stroj z filmu)", "B": "prompcie B (stroj ze zdjecia)", "zdjecia": "promptach zdjec"}[nazwa]
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
    wskazowki.append("Gdy odrzuca tylko czasem: to filtr WYNIKU (losowy) - jedna powtorka ma sens, wiecej nie. Fabryka po dwoch "
                     "odrzuceniach z rzedu przestaje probowac.")
    wskazowki.append("Jesli masz pewnosc, ze to pomylka filtra: Higgsfield -> Help Center -> zglos false positive (oddaja kredyty, "
                     "ale decyzji filtra nie cofaja).")
    return {"odrzucone": len(odrzucone), "odrzucone_ostatnio": len(ostatnio), "dni": dni, "slowa": slowa, "wskazowki": wskazowki}


def generuj(slug, ids=None, limit=None, potwierdz=None, dry_run=False, bez_referencji=False,
            timeout="30m", log=None, stop=None, max_rolek=None, lipsync=None):
    """Generacja pozycji 'nowy' z promptem (albo wskazanych id).

    potwierdz(p, koszt, saldo_po, dzis_po, limit) -> bool; None = bez pytania.
    stop = threading.Event (panel: STOP). max_rolek = ile rolek max w tym przebiegu (autopilot).
    lipsync: None = wg ustawienia lipsync_auto (reczne "Zrob rolke"); False = nigdy (autopilot - lipsync tylko recznie).
    Zwraca {"wygenerowane": n, "bledy": [id], "pominiete": [id], "stop": powod|None}.
    """
    log = log or _log
    wynik = {"wygenerowane": 0, "bledy": [], "pominiete": [], "stop": None}
    ust = baza.ustawienia_modelki(slug)
    nazwa_dostawcy = ust.get("dostawca") or "higgsfield"
    d = dostawcy.dostawca(nazwa_dostawcy)
    lista = kandydaci(slug, ids, limit, log)
    if not lista:
        log("Nic do generacji (brak pomyslow 'nowy' z promptem).")
        return wynik
    if not baza.sciezki_referencji(slug) and not bez_referencji:
        log("Brak zdjec persony w referencje/ - bez tego model nie wie, kogo wstawic. "
            "Wrzuc zdjecia albo dodaj --bez-referencji, jesli tak ma byc.")
        wynik["stop"] = "brak referencji"
        return wynik

    for uwaga in sprawdz_prompt(slug, ust):
        log(f"[UWAGA] {uwaga}")

    if dry_run:
        for p in lista:
            log(f"#{p['id']}: " + d.podglad(zlecenie(slug, p, ust)))
        return wynik

    try:
        saldo = d.saldo()
    except dostawcy.BladDostawcy as e:
        _zdarzenie(log, slug, "blad", f"[BLAD] saldo {nazwa_dostawcy}: {e}")
        wynik["stop"] = f"saldo: {e}"
        return wynik
    if saldo is None:
        saldo = 10 ** 9   # dostawca nie podaje salda - pilnuje tylko limit dzienny
    limit_dnia = baza.limit_dzienny(nazwa_dostawcy)
    wydano = baza.wydano_dzis(nazwa_dostawcy)
    min_kredyty, max_na_rolke = bezpiecznik(ust, nazwa_dostawcy)
    log(f"saldo {nazwa_dostawcy}: {saldo} kr | dzis wydano {wydano}/{limit_dnia} | min_kredyty={min_kredyty} "
        f"max/rolka={max_na_rolke} powtorki={ust.get('powtorki', 0)}")

    for p in lista:
        _sprawdz_stop(stop)
        if max_rolek is not None and wynik["wygenerowane"] >= max_rolek:
            wynik["stop"] = f"limit rolek w tym przebiegu ({max_rolek})"
            break
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
            log(f"#{p['id']}: dostawca nie podal kosztu, zakladam {k} kr")
        if k > max_na_rolke:
            _zdarzenie(log, slug, "uwaga", f"#{p['id']}: {k} kr > max/rolka {max_na_rolke} - POMIJAM (zmien ustawienia albo skroc zrodlo)", pomysl=p["id"])
            wynik["pominiete"].append(p["id"])
            continue
        if saldo - k < min_kredyty:
            _zdarzenie(log, slug, "uwaga", f"#{p['id']}: {k} kr zostawiloby {saldo - k} < min_kredyty {min_kredyty} - STOP", pomysl=p["id"])
            wynik["stop"] = "min_kredyty"
            break
        if limit_dnia and wydano + k > limit_dnia:
            _zdarzenie(log, slug, "uwaga", f"#{p['id']}: {k} kr przekroczyloby limit dzienny ({wydano}+{k} > {limit_dnia}) - STOP na dzis", pomysl=p["id"])
            wynik["stop"] = "limit dzienny"
            break
        if potwierdz is not None and not potwierdz(p, k, saldo - k, wydano + k, limit_dnia):
            log("pominieto")
            wynik["pominiete"].append(p["id"])
            continue

        urls, jid, blad, powod = [], None, None, None
        proby = 1 + max(0, int(ust.get("powtorki") or 0))
        saldo_przed = saldo
        for proba in range(1, proby + 1):
            _sprawdz_stop(stop)
            _zdarzenie(log, slug, "info", f"#{p['id']}: start ({nazwa_dostawcy} {z['model'] if nazwa_dostawcy == 'higgsfield' else z['yapper'].get('model')}, ~{k} kr, proba {proba}/{proby}) - {p['opis']}", pomysl=p["id"])
            stan = ""
            try:
                job = d.generuj(z, timeout=timeout, log=log)
                jid = job.get("job_id")
                urls = job.get("urls") or []
                if urls:
                    blad = None
                    break
                stan = job.get("status") or ""
                blad = f"job {jid} status={stan}, brak URL wyniku" + (f", powod: {job['blad']}" if job.get("blad") else "") \
                    + f": {json.dumps(job.get('surowe'), ensure_ascii=False)[:600]}"
                if d.udany(stan):
                    # job sie udal, tylko nie umiem odczytac linku - powtorka by palila kredyty. Stop, do naprawy w wyniki_url().
                    _zdarzenie(log, slug, "blad", f"#{p['id']}: job {jid} zakonczony, ale nie znajduje URL - NIE powtarzam; sprawdz `higgsfield generate get {jid} --json`", pomysl=p["id"])
                    break
            except dostawcy.BladDostawcy as e:
                blad = str(e)
            log(f"#{p['id']}: nie wyszlo ({blad[:200]})")
            # ile naprawde zeszlo? Seedance przy odrzuceniu oddaje kredyty
            try:
                saldo = d.saldo() or saldo
            except dostawcy.BladDostawcy:
                pass
            nowy_powod = powod_odrzucenia(stan, blad)
            if nowy_powod == "nsfw" and powod == "nsfw":
                # filtr tresci dwa razy z rzedu na tych samych wejsciach = to nie przypadek; kolejna proba to tylko stracony czas
                _zdarzenie(log, slug, "uwaga", f"#{p['id']}: filtr tresci (NSFW) drugi raz z rzedu - nie probuje dalej", pomysl=p["id"])
                break
            powod = nowy_powod
            if proba < proby:
                time.sleep(10)

        zuzyte = None
        try:
            nowe_saldo = d.saldo()
            if nowe_saldo is None:
                raise dostawcy.BladDostawcy("dostawca nie podaje salda")
            saldo = nowe_saldo
            zuzyte = max(0, saldo_przed - saldo)
        except dostawcy.BladDostawcy:
            saldo = saldo_przed - (k if urls else 0)
            zuzyte = k if urls else 0
        wydano = baza.dopisz_wydatek(zuzyte, nazwa_dostawcy)
        if zuzyte:
            baza.dziennik_zapisz("kredyty", f"#{p['id']}: {zuzyte} kr ({nazwa_dostawcy}), dzis {wydano}/{limit_dnia}", modelka=slug, pomysl=p["id"], kredyty=zuzyte, dostawca=nazwa_dostawcy)

        if not urls:
            baza.aktualizuj_pomysl(slug, p["id"], status="blad", job_id=jid, koszt=zuzyte, dostawca=nazwa_dostawcy, notatki=(blad or "")[:2000],
                                   powod=powod)
            if powod == "nsfw":
                _zdarzenie(log, slug, "blad", f"#{p['id']}: ODRZUCONE przez filtr tresci (NSFW), zuzyte {zuzyte} kr. {PODPOWIEDZ_NSFW}", pomysl=p["id"], powod="nsfw")
            elif powod == "ip":
                _zdarzenie(log, slug, "blad", f"#{p['id']}: ODRZUCONE - model wykryl znana postac/marke (ip_detected), zuzyte {zuzyte} kr. "
                           f"Sprawdz, czy w filmiku/zdjeciach nie ma logo, celebryty albo postaci z filmu.", pomysl=p["id"], powod="ip")
            else:
                _zdarzenie(log, slug, "blad", f"#{p['id']}: BLAD po {proby} probach (zuzyte {zuzyte} kr) - status blad, zostaje w kolejce", pomysl=p["id"])
            wynik["bledy"].append(p["id"])
            continue

        nazwa = _bezpieczna_nazwa(os.path.splitext(os.path.basename(p.get("zrodlo") or f"pomysl_{p['id']}"))[0])
        rozsz = os.path.splitext(urls[0].split("?")[0])[1] or ".mp4"
        if rozsz.lower() not in ROZSZERZENIA_WIDEO:
            rozsz = ".mp4"
        surowy = os.path.join(baza.folder_wynikow(slug), f"{p['id']:03d}_{nazwa}.raw{rozsz}")
        try:
            d.pobierz(urls[0], surowy)
        except Exception as e:
            _zdarzenie(log, slug, "blad", f"#{p['id']}: pobranie nie wyszlo ({e}), URL: {urls[0]}", pomysl=p["id"])
            baza.aktualizuj_pomysl(slug, p["id"], status="blad", job_id=jid, koszt=zuzyte, wynik_url=urls[0], dostawca=nazwa_dostawcy,
                                   notatki=f"pobranie: {e}")
            wynik["bledy"].append(p["id"])
            continue
        wynik["wygenerowane"] += 1
        baza.aktualizuj_pomysl(slug, p["id"], status="wygenerowany", job_id=jid, koszt=zuzyte, dostawca=nazwa_dostawcy,
                               wynik_url=urls[0], plik_wynikowy=surowy)
        _zdarzenie(log, slug, "ok", f"#{p['id']}: WYGENEROWANE ({zuzyte} kr, dzis {wydano}/{limit_dnia}) -> {surowy}", pomysl=p["id"])

        gotowy = _postprodukcja(slug, p["id"], surowy, nazwa, ust, log=log)
        if gotowy:
            _zdarzenie(log, slug, "ok", f"#{p['id']}: GOTOWE -> {gotowy}", pomysl=p["id"], plik=gotowy)
        if lipsync is not False:
            _lipsync_po_generacji(slug, p, gotowy or surowy, ust, log)

    log(f"koniec: {wynik['wygenerowane']} wygenerowanych, dzis wydano {baza.wydano_dzis(nazwa_dostawcy)}/{limit_dnia} kr")
    return wynik


def podglad(slug, pid, log=None):
    """Tani podglad rolki (Seedance `draft`, ~21 kr zamiast 45-72): ten sam prompt i referencje, wynik w
    wyniki/NNN_nazwa.podglad.mp4, pomysl zostaje 'nowy' (pelna generacja dopiero, gdy user kliknie Zrob rolke).
    Zwraca sciezke pliku podgladu."""
    log = log or _log
    ust = baza.ustawienia_modelki(slug)
    nazwa_dostawcy = ust.get("dostawca") or "higgsfield"
    if nazwa_dostawcy != "higgsfield":
        raise ValueError("Tani podglad dziala tylko dla Higgsfield (Seedance draft).")
    d = dostawcy.dostawca(nazwa_dostawcy)
    p = baza.pomysl(slug, pid)
    if not p.get("prompt_higgsfield"):
        raise ValueError(f"#{pid} nie ma promptu.")
    z = zlecenie(slug, p, ust)
    z["parametry"] = dict(z.get("parametry") or {}, draft=True)
    saldo = d.saldo()
    k = d.koszt(z)
    if k is None:
        k = 25
    min_kredyty, _ = bezpiecznik(ust, nazwa_dostawcy)
    limit_dnia, wydano = baza.limit_dzienny(nazwa_dostawcy), baza.wydano_dzis(nazwa_dostawcy)
    if saldo - k < min_kredyty:
        raise ValueError(f"Podglad ({k} kr) zostawilby {saldo - k} < min_kredyty {min_kredyty}.")
    if limit_dnia and wydano + k > limit_dnia:
        raise ValueError(f"Podglad ({k} kr) przekroczylby limit dzienny ({wydano}+{k} > {limit_dnia}).")
    _zdarzenie(log, slug, "info", f"#{pid}: tani podglad (draft, ~{k} kr)", pomysl=pid)
    job = d.generuj(z, timeout="20m", log=log)
    try:
        zuzyte = max(0, saldo - d.saldo())
    except dostawcy.BladDostawcy:
        zuzyte = k
    baza.dopisz_wydatek(zuzyte, nazwa_dostawcy)
    urls = job.get("urls") or []
    if not urls:
        raise RuntimeError(job.get("blad") or f"brak URL podgladu (status {job.get('status')})")
    nazwa = _bezpieczna_nazwa(os.path.splitext(os.path.basename(p.get("zrodlo") or f"pomysl_{pid}"))[0])
    cel = os.path.join(baza.folder_wynikow(slug), f"{pid:03d}_{nazwa}.podglad.mp4")
    d.pobierz(urls[0], cel)
    baza.aktualizuj_pomysl(slug, pid, podglad_plik=cel, podglad_koszt=zuzyte)
    _klatki_podgladu = os.path.join(baza.folder_klatek(slug), f"{pid:03d}_podglad.jpg")
    try:
        klatki.arkusz(cel, _klatki_podgladu, ile=6)
        baza.aktualizuj_pomysl(slug, pid, klatki_podgladu=_klatki_podgladu)
    except Exception:
        pass
    _zdarzenie(log, slug, "ok", f"#{pid}: podglad gotowy ({zuzyte} kr) -> {cel}", pomysl=pid, plik=cel)
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
    return 1 if w.get("stop") in ("brak referencji",) or (w.get("stop") or "").startswith("saldo") else 0


def _postprodukcja(slug, pid, surowy, nazwa, ust, log=None):
    """Media Tool (pranie) -> folder gotowych; opcjonalnie warianty VideoRemixer. Zwraca sciezke gotowego pliku."""
    log = log or _log
    gotowe_dir = baza.folder_gotowych(slug)
    cel = os.path.join(gotowe_dir, f"{pid:03d}_{nazwa}.mp4")
    if ust.get("mediatool"):
        try:
            import mediatool
            cel = mediatool.pierz_wideo(surowy, gotowe_dir, nazwa_wyniku=os.path.basename(cel))
            baza.aktualizuj_pomysl(slug, pid, status="gotowe", plik_wynikowy=cel)
        except Exception as e:
            _zdarzenie(log, slug, "uwaga", f"#{pid}: Media Tool nie wyszedl ({e}) - zostawiam surowy plik w wyniki/, status wygenerowany", pomysl=pid)
            return None
    else:
        import shutil
        shutil.copy2(surowy, cel)
        baza.aktualizuj_pomysl(slug, pid, status="gotowe", plik_wynikowy=cel)
    _klatki_wyniku(slug, pid, cel, log)
    if ust.get("warianty"):
        try:
            _warianty(slug, pid, cel, int(ust["warianty"]))
        except Exception as e:
            log(f"#{pid}: warianty nie wyszly: {e}")
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


# ---------------- postprodukcja ----------------

def _warianty(slug, pid, plik, ile):
    import postprocess
    folder = os.path.join(baza.folder_wynikow(slug), f"{pid:03d}_warianty")
    os.makedirs(folder, exist_ok=True)
    pliki = [f for f in postprocess.wygeneruj_warianty(plik, folder, ile)
             if f.lower().endswith(ROZSZERZENIA_WIDEO)]
    baza.aktualizuj_pomysl(slug, pid, status="gotowe", plik_wynikowy=folder)
    _log(f"#{pid}: {len(pliki)} wariantow -> {folder}")
    return pliki


def cmd_warianty(args):
    slug = _slug(args.modelka)
    p = baza.pomysl(slug, args.id)
    plik = args.plik or p.get("plik_wynikowy")
    if not plik or not os.path.isfile(plik):
        print(f"#{p['id']}: podaj --plik (po faceswapie/edycji) albo najpierw wygeneruj.")
        return 1
    _warianty(slug, p["id"], plik, args.ile)
    return 0


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
    wynik = lipsync.zrob(slug, wideo, audio, pomysl_id=args.id)
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
    s = sub.add_parser("ocen", help="Virality Predictor na wyniku (kosztuje kredyty)"); s.add_argument("id", type=int); s.set_defaults(f=cmd_ocen)
    s = sub.add_parser("warianty", help="VideoRemixer: N unikalnych wersji"); s.add_argument("id", type=int); s.add_argument("--ile", type=int, default=10); s.add_argument("--plik"); s.set_defaults(f=cmd_warianty)
    s = sub.add_parser("gotowe", help="oznacz pomysl jako gotowy"); s.add_argument("id", type=int); s.set_defaults(f=cmd_gotowe)
    s = sub.add_parser("podpis", help="podpis z banku tekstow -> wyniki/<id>_podpis.txt"); s.add_argument("id", type=int); s.set_defaults(f=cmd_podpis)
    s = sub.add_parser("wgraj", help="wgraj referencje/stroje raz (UUID w cache, szybsze koszt/generuj)"); s.add_argument("--od-nowa", action="store_true"); s.set_defaults(f=cmd_wgraj)
    s = sub.add_parser("pierz", help="Media Tool na wyniku pomyslu (albo --plik dowolny.mp4)"); s.add_argument("id", type=int, nargs="?"); s.add_argument("--plik"); s.set_defaults(f=cmd_pierz)
    s = sub.add_parser("zdjecia", help="zdjecia persony (model obrazu z referencjami; --stroj auto|bez|plik = strój ze stroje/)"); s.add_argument("--ile", type=int, default=1); s.add_argument("--prompt"); s.add_argument("--stroj"); s.add_argument("--dry-run", action="store_true"); s.set_defaults(f=cmd_zdjecia)
    s = sub.add_parser("lipsync", help="wideo + glos -> lipsync (sync.so) - tylko recznie, autopilot tego nie robi"); s.add_argument("id", type=int, nargs="?"); s.add_argument("--wideo"); s.add_argument("--audio"); s.set_defaults(f=cmd_lipsync)
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
