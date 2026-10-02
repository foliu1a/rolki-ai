# -*- coding: utf-8 -*-
"""
fabryka.py - automat: filmik zrodlowy -> Seedance 2.5 Edit (Higgsfield CLI) -> rolka.

Obieg:
  1. Wrzucasz filmiki do  modelki/<slug>/zrodla/
  2. python fabryka.py skanuj          -> kazdy nowy filmik dostaje pomysl (status: nowy) + klatki podgladu
  3. agent oglada klatki i wpisuje prompt (na bazie prompt_bazowy z ustawien)
  4. python fabryka.py koszt           -> ile kredytow zjedza pozycje z promptem
  5. python fabryka.py generuj         -> bezpiecznik budzetu, generacja, pobranie do wyniki/ (status: wygenerowany)
  6. python fabryka.py ocen <id>       -> Virality Predictor (opcjonalnie, kosztuje kredyty)
  7. python fabryka.py warianty <id>   -> VideoRemixer (status: gotowe)
  8. python fabryka.py podpis <id>     -> podpis z banku tekstow obok pliku

Wszystko czyta/zapisuje przez baza.py. Bez zaleznosci poza stdlib + ffmpeg + CLI Higgsfield.
"""
import argparse
import json
import os
import re
import sys
import time

import baza
import higgsfield_cli as hf
import klatki

if sys.platform == "win32":
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")

ROZSZERZENIA_WIDEO = (".mp4", ".mov", ".webm", ".m4v")


def _slug(arg):
    slug = arg or baza.aktywna_modelka()
    if not slug or slug not in baza.lista_modelek():
        raise SystemExit("Brak aktywnej modelki. Podaj --modelka <slug> albo ustaw aktywna w panelu.")
    return slug


def _log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


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


# ---------------- status ----------------

def cmd_status(args):
    slug = _slug(args.modelka)
    ust = baza.ustawienia_modelki(slug)
    st = baza.statystyki_pomyslow(slug)
    print(f"modelka: {slug}   model: {ust['model']} / {ust['mode']} / {ust['aspect_ratio']} / {ust['resolution']}")
    print(f"wrzutnia: {baza.folder_zrodel(slug)}")
    print(f"gotowe:   {baza.folder_gotowych(slug)}   (Media Tool: {'tak' if ust.get('mediatool') else 'nie'})")
    print("pomysly: " + ", ".join(f"{s}={st.get(s, 0)}" for s in baza.STATUSY))
    bud = baza.budzet()
    print(f"budzet dzienny: wydano {baza.wydano_dzis()}/{bud.get('max_kredyty_dziennie')} kr (wspolny dla wszystkich modelek)")
    nowe_bez_promptu = [p for p in baza.lista_pomyslow(slug, "nowy") if not p.get("prompt_higgsfield")]
    nowe_z_promptem = [p for p in baza.lista_pomyslow(slug, "nowy") if p.get("prompt_higgsfield")]
    if nowe_bez_promptu:
        print(f"czekaja na prompt ({len(nowe_bez_promptu)}): " + ", ".join(f"#{p['id']}" for p in nowe_bez_promptu))
    if nowe_z_promptem:
        print(f"gotowe do generacji ({len(nowe_z_promptem)}): " + ", ".join(f"#{p['id']}" for p in nowe_z_promptem))
    niezeskanowane = _nowe_zrodla(slug)
    if niezeskanowane:
        print(f"filmiki w zrodla/ bez pomyslu ({len(niezeskanowane)}): " + ", ".join(os.path.basename(z) for z in niezeskanowane))
        print("  -> python fabryka.py skanuj")
    refs = baza.sciezki_referencji(slug)
    print(f"referencje persony: {len(refs)} zdjec" + ("" if refs else "  (wrzuc zdjecia do referencje/ !)"))
    if not ust.get("prompt_bazowy"):
        print("UWAGA: brak prompt_bazowy w ustawieniach - agent nie ma na czym oprzec promptow")
    try:
        kr = hf.kredyty()
        print(f"kredyty Higgsfield: {kr}  (min_kredyty={ust['min_kredyty']}, max/rolka={ust['max_kredyty_na_rolke']})")
    except hf.HiggsfieldBlad as e:
        print(f"kredyty Higgsfield: niedostepne ({e})")
    return 0


# ---------------- skanowanie wrzutni ----------------

def _nowe_zrodla(slug):
    folder = baza.folder_zrodel(slug)
    wynik = []
    for n in sorted(os.listdir(folder)):
        p = os.path.join(folder, n)
        if os.path.isfile(p) and n.lower().endswith(ROZSZERZENIA_WIDEO) and not baza.pomysl_po_zrodle(slug, p):
            wynik.append(p)
    return wynik


def cmd_skanuj(args):
    slug = _slug(args.modelka)
    nowe = _nowe_zrodla(slug)
    if not nowe:
        print("Brak nowych filmikow w " + baza.folder_zrodel(slug))
        return 0
    folder_klatek = baza.folder_klatek(slug)
    ust = baza.ustawienia_modelki(slug)
    prompt_a = baza.prompt_bazowy(slug) if ust.get("prompt_auto") else ""
    prompt_b = baza.prompt_stroj(slug) if ust.get("prompt_auto") else ""
    stroj_dom = baza.stroj_domyslny(slug)
    if ust.get("prompt_auto") and not prompt_a:
        print("UWAGA: prompt_auto=true, ale prompt_bazowy (wariant A) jest pusty.")
    bez_promptu = []
    for zrodlo in nowe:
        nazwa = os.path.splitext(os.path.basename(zrodlo))[0]
        try:
            inf = klatki.info(zrodlo)
        except Exception as e:
            print(f"[POMIJAM] {os.path.basename(zrodlo)}: {e}")
            continue
        folder = os.path.join(folder_klatek, _bezpieczna_nazwa(nazwa))
        try:
            klatki.wytnij(zrodlo, folder, ile=args.ile)
            klatki.arkusz(zrodlo, os.path.join(folder, "arkusz.jpg"), ile=6)
        except Exception as e:
            print(f"[UWAGA] klatki dla {nazwa}: {e}")

        stroj = _stroj_dla(zrodlo) or stroj_dom
        if stroj:
            prompt = prompt_b
            wariant = "B: stroj ze zdjecia " + os.path.basename(stroj)
            if ust.get("prompt_auto") and not prompt_b:
                print(f"[UWAGA] {nazwa}: jest zdjecie stroju, ale prompt_stroj (wariant B) jest pusty.")
        else:
            prompt = prompt_a
            wariant = "A: stroj z filmu"
        opis = f"{os.path.basename(zrodlo)} ({inf['czas']}s, {inf['szer']}x{inf['wys']})"
        pid = baza.dodaj_pomysl(slug, opis, prompt, zrodlo=zrodlo, klatki=folder, info_zrodla=inf, stroj=stroj)
        if not prompt:
            bez_promptu.append(pid)
        print(f"#{pid}  {opis}   [{wariant}]" + ("" if prompt else "   (BEZ PROMPTU)"))
        print(f"      klatki: {os.path.join(folder, 'arkusz.jpg')}")
    if bez_promptu:
        print("\nBez promptu: " + ", ".join(f"#{i}" for i in bez_promptu)
              + " -> obejrzyj arkusz.jpg i wpisz: python fabryka.py prompt <id> \"...\"")
    print("Dalej: python fabryka.py koszt, potem python fabryka.py generuj")
    return 0


def _stroj_dla(zrodlo):
    """Zdjecie stroju sparowane z klipem: <nazwa>.stroj.<ext> albo <nazwa>_stroj.<ext> obok filmiku."""
    folder, plik = os.path.split(zrodlo)
    stem = os.path.splitext(plik)[0]
    for wzor in (f"{stem}.stroj", f"{stem}_stroj"):
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
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

def _zlecenie(slug, p, ust):
    """Sklada (model, params, media) dla pomyslu wg ustawien modelki."""
    params = {
        "prompt": p["prompt_higgsfield"],
        "mode": ust.get("mode"),
        "aspect_ratio": ust.get("aspect_ratio"),
        "resolution": ust.get("resolution"),
    }
    dur = ust.get("duration")
    if dur is None and p.get("info_zrodla"):
        dur = int(round(p["info_zrodla"].get("czas") or 0)) or None
    if dur:
        # Seedance 2.5 przyjmuje 4-30 s; dluzsze zrodlo = utnij albo potnij przed wrzuceniem
        params["duration"] = max(4, min(30, int(dur)))
    if ust.get("generate_audio") is not None:
        params["generate_audio"] = bool(ust["generate_audio"])
    if ust.get("soul_id"):
        params["soul-id"] = ust["soul_id"]
    params.update(ust.get("dodatkowe_parametry") or {})

    media = {}
    if p.get("zrodlo"):
        media["video"] = p["zrodlo"]
    # kolejnosc --image = numeracja @[Image N] w prompcie: najpierw referencje persony, strój jako OSTATNI
    obrazy = list(baza.sciezki_referencji(slug))
    if p.get("stroj") and os.path.isfile(p["stroj"]):
        obrazy.append(p["stroj"])
    if obrazy:
        media["image"] = baza.media_do_cli(slug, obrazy)   # UUID z cache zamiast ponownego uploadu
    return ust["model"], params, media


def cmd_wgraj(args):
    """Wgrywa referencje (i stroje) raz; potem koszt/generuj uzywaja UUID-ow zamiast slac 30 MB za kazdym razem."""
    slug = _slug(args.modelka)
    pliki = list(baza.sciezki_referencji(slug))
    stroje = baza.folder_strojow(slug)
    pliki += [os.path.join(stroje, n) for n in sorted(os.listdir(stroje)) if n.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
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


def _kandydaci(slug, args):
    ust = baza.ustawienia_modelki(slug)
    wymaga_wideo = ust.get("mode") in ("video_edit", "video_extension")
    if getattr(args, "id", None):
        p = baza.pomysl(slug, args.id)
        if p["status"] not in ("nowy", "blad"):
            raise SystemExit(f"#{p['id']} ma status {p['status']} - generuje tylko nowy/blad.")
        if wymaga_wideo and not p.get("zrodlo"):
            raise SystemExit(f"#{p['id']} nie ma filmiku zrodlowego, a tryb {ust['mode']} go wymaga "
                             f"(wrzuc plik do zrodla/ i zrob skanuj, albo zmien mode).")
        return [p]
    lista, pominiete = [], []
    for p in baza.lista_pomyslow(slug, "nowy"):
        if not p.get("prompt_higgsfield"):
            continue
        if wymaga_wideo and not p.get("zrodlo"):
            pominiete.append(p["id"])
            continue
        lista.append(p)
    if pominiete:
        print(f"pomijam bez filmiku zrodlowego (tryb {ust['mode']}): " + ", ".join(f"#{i}" for i in pominiete))
    limit = getattr(args, "limit", None)
    return lista[:limit] if limit else lista


# ---------------- koszt ----------------

def cmd_koszt(args):
    slug = _slug(args.modelka)
    ust = baza.ustawienia_modelki(slug)
    kandydaci = _kandydaci(slug, args)
    if not kandydaci:
        print("Nic do policzenia (brak pomyslow 'nowy' z promptem).")
        return 0
    suma = 0
    for p in kandydaci:
        model, params, media = _zlecenie(slug, p, ust)
        try:
            k = hf.koszt(model, params, media)
        except hf.HiggsfieldBlad as e:
            print(f"#{p['id']}: [BLAD] {e}")
            continue
        suma += k or 0
        baza.aktualizuj_pomysl(slug, p["id"], koszt=k)
        print(f"#{p['id']}: {k if k is not None else '?'} kr   {p['opis']}")
    print(f"razem: {suma} kr")
    return 0


# ---------------- generacja ----------------

def cmd_generuj(args):
    slug = _slug(args.modelka)
    ust = baza.ustawienia_modelki(slug)
    kandydaci = _kandydaci(slug, args)
    if not kandydaci:
        print("Nic do generacji (brak pomyslow 'nowy' z promptem).")
        return 0
    if not baza.sciezki_referencji(slug) and not args.bez_referencji:
        print("Brak zdjec persony w referencje/ - bez tego Seedance nie wie, kogo wstawic. "
              "Wrzuc zdjecia albo dodaj --bez-referencji, jesli tak ma byc.")
        return 1

    if args.dry_run:
        for p in kandydaci:
            model, params, media = _zlecenie(slug, p, ust)
            print(f"#{p['id']}: " + hf.komenda_podglad(model, params, media))
        return 0

    try:
        saldo = hf.kredyty()
    except hf.HiggsfieldBlad as e:
        print(f"[BLAD] {e}")
        return 1
    bud = baza.budzet()
    limit_dnia = int(bud.get("max_kredyty_dziennie") or 0)
    wydano = baza.wydano_dzis()
    _log(f"saldo: {saldo} kr | dzis wydano {wydano}/{limit_dnia} | min_kredyty={ust['min_kredyty']} "
         f"max/rolka={ust['max_kredyty_na_rolke']} powtorki={ust.get('powtorki', 0)}")

    zrobione = 0
    for p in kandydaci:
        model, params, media = _zlecenie(slug, p, ust)
        try:
            k = hf.koszt(model, params, media)
        except hf.HiggsfieldBlad as e:
            _log(f"#{p['id']}: koszt nieznany ({e}) - pomijam")
            baza.aktualizuj_pomysl(slug, p["id"], status="blad", notatki=f"koszt: {e}")
            continue
        if k is None:
            k = ust["max_kredyty_na_rolke"]
            _log(f"#{p['id']}: CLI nie podalo kosztu, zakladam {k} kr")
        if k > ust["max_kredyty_na_rolke"]:
            _log(f"#{p['id']}: {k} kr > max/rolka {ust['max_kredyty_na_rolke']} - POMIJAM (zmien ustawienia albo skroc zrodlo)")
            continue
        if saldo - k < ust["min_kredyty"]:
            _log(f"#{p['id']}: {k} kr zostawiloby {saldo - k} < min_kredyty {ust['min_kredyty']} - STOP")
            break
        if limit_dnia and wydano + k > limit_dnia:
            _log(f"#{p['id']}: {k} kr przekroczyloby limit dzienny ({wydano}+{k} > {limit_dnia}) - STOP na dzis")
            break
        if not args.tak:
            odp = input(f"#{p['id']}: {k} kr, saldo po: {saldo - k}, dzis po: {wydano + k}/{limit_dnia}. Generowac? [t/N] ").strip().lower()
            if odp not in ("t", "tak", "y"):
                _log("pominieto")
                continue

        job, urls, jid, blad = None, [], None, None
        proby = 1 + max(0, int(ust.get("powtorki") or 0))
        saldo_przed = saldo
        for proba in range(1, proby + 1):
            _log(f"#{p['id']}: start ({model}, ~{k} kr, proba {proba}/{proby}) - {p['opis']}")
            try:
                job = hf.generuj(model, params, media, wait=True, wait_timeout=args.timeout)
                jid = hf.job_id_z(job)
                urls = hf.wyniki_url(job)
                if urls:
                    blad = None
                    break
                stan = hf.status_joba(job) or ""
                blad = f"job {jid} status={stan}, brak URL wyniku: {json.dumps(job, ensure_ascii=False)[:600]}"
                if stan in ("completed", "succeeded", "success", "done", "finished"):
                    # job sie udal, tylko nie umiem odczytac linku - powtorka by palila kredyty. Stop, do naprawy w wyniki_url().
                    _log(f"#{p['id']}: job {jid} zakonczony, ale nie znajduje URL - NIE powtarzam; sprawdz `higgsfield generate get {jid} --json`")
                    break
            except hf.HiggsfieldBlad as e:
                blad = str(e)
            _log(f"#{p['id']}: nie wyszlo ({blad[:200]})")
            # ile naprawde zeszlo? Seedance przy odrzuceniu oddaje kredyty
            try:
                saldo = hf.kredyty()
            except hf.HiggsfieldBlad:
                pass
            if proba < proby:
                time.sleep(10)

        zuzyte = None
        try:
            saldo = hf.kredyty()
            zuzyte = max(0, saldo_przed - saldo)
        except hf.HiggsfieldBlad:
            saldo = saldo_przed - (k if urls else 0)
            zuzyte = k if urls else 0
        wydano = baza.dopisz_wydatek(zuzyte)

        if not urls:
            baza.aktualizuj_pomysl(slug, p["id"], status="blad", job_id=jid, koszt=zuzyte, notatki=(blad or "")[:2000])
            _log(f"#{p['id']}: BLAD po {proby} probach (zuzyte {zuzyte} kr) - status blad, zostaje w kolejce")
            continue

        nazwa = _bezpieczna_nazwa(os.path.splitext(os.path.basename(p.get("zrodlo") or f"pomysl_{p['id']}"))[0])
        rozsz = os.path.splitext(urls[0].split("?")[0])[1] or ".mp4"
        surowy = os.path.join(baza.folder_wynikow(slug), f"{p['id']:03d}_{nazwa}.raw{rozsz}")
        try:
            hf.pobierz(urls[0], surowy)
        except Exception as e:
            _log(f"#{p['id']}: pobranie nie wyszlo ({e}), URL: {urls[0]}")
            baza.aktualizuj_pomysl(slug, p["id"], status="blad", job_id=jid, koszt=zuzyte, wynik_url=urls[0],
                                   notatki=f"pobranie: {e}")
            continue
        zrobione += 1
        baza.aktualizuj_pomysl(slug, p["id"], status="wygenerowany", job_id=jid, koszt=zuzyte,
                               wynik_url=urls[0], plik_wynikowy=surowy)
        _log(f"#{p['id']}: WYGENEROWANE ({zuzyte} kr, dzis {wydano}/{limit_dnia}) -> {surowy}")

        gotowy = _postprodukcja(slug, p["id"], surowy, nazwa, ust)
        if gotowy:
            _log(f"#{p['id']}: GOTOWE -> {gotowy}")

    _log(f"koniec: {zrobione} wygenerowanych, dzis wydano {baza.wydano_dzis()}/{limit_dnia} kr")
    return 0


def _postprodukcja(slug, pid, surowy, nazwa, ust):
    """Media Tool (pranie) -> folder gotowych; opcjonalnie warianty VideoRemixer. Zwraca sciezke gotowego pliku."""
    gotowe_dir = baza.folder_gotowych(slug)
    cel = os.path.join(gotowe_dir, f"{pid:03d}_{nazwa}.mp4")
    if ust.get("mediatool"):
        try:
            import mediatool
            cel = mediatool.pierz_wideo(surowy, gotowe_dir, nazwa_wyniku=os.path.basename(cel))
            baza.aktualizuj_pomysl(slug, pid, status="gotowe", plik_wynikowy=cel)
        except Exception as e:
            _log(f"#{pid}: Media Tool nie wyszedl ({e}) - zostawiam surowy plik w wyniki/, status wygenerowany")
            return None
    else:
        import shutil
        shutil.copy2(surowy, cel)
        baza.aktualizuj_pomysl(slug, pid, status="gotowe", plik_wynikowy=cel)
    if ust.get("warianty"):
        try:
            _warianty(slug, pid, cel, int(ust["warianty"]))
        except Exception as e:
            _log(f"#{pid}: warianty nie wyszly: {e}")
    return cel


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


def cmd_podpis(args):
    slug = _slug(args.modelka)
    p = baza.pomysl(slug, args.id)
    tekst = baza.losuj_tekst(slug)
    if not tekst:
        print("Bank tekstow pusty albo wszystko uzyte - dopisz teksty w panelu.")
        return 1
    cel = os.path.join(baza.folder_wynikow(slug), f"{p['id']:03d}_podpis.txt")
    with open(cel, "w", encoding="utf-8") as f:
        f.write(tekst + "\n")
    print(tekst)
    print(f"-> {cel}")
    return 0


# ---------------- pranie reczne ----------------

def cmd_pierz(args):
    """Media Tool na gotowym pliku (po generacji, gdy mediatool=false, albo na dowolnym mp4)."""
    slug = _slug(args.modelka)
    import mediatool
    if args.plik:
        plik = args.plik
        nazwa = _bezpieczna_nazwa(os.path.splitext(os.path.basename(plik))[0])
        cel = mediatool.pierz_wideo(plik, baza.folder_gotowych(slug), nazwa_wyniku=f"{nazwa}.mp4", log=_log)
        print(cel)
        return 0
    p = baza.pomysl(slug, args.id)
    plik = p.get("plik_wynikowy")
    if not plik or not os.path.isfile(plik):
        print(f"#{p['id']} nie ma pliku wynikowego.")
        return 1
    nazwa = _bezpieczna_nazwa(os.path.splitext(os.path.basename(p.get("zrodlo") or f"pomysl_{p['id']}"))[0])
    ust = dict(baza.ustawienia_modelki(slug), mediatool=True)
    cel = _postprodukcja(slug, p["id"], plik, nazwa, ust)
    print(cel or "nie wyszlo")
    return 0 if cel else 1


# ---------------- ustawienia ----------------

def cmd_budzet(args):
    if not args.pary:
        print(json.dumps(baza.budzet(), ensure_ascii=False, indent=2))
        return 0
    zmiany = {}
    for para in args.pary:
        k, v = para.split("=", 1)
        zmiany[k] = int(v)
    print(json.dumps(baza.zapisz_budzet(**zmiany), ensure_ascii=False, indent=2))
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
    ap = argparse.ArgumentParser(description="rolki-ai: fabryka rolek (Higgsfield CLI + Seedance 2.5 Edit)")
    ap.add_argument("--modelka", "-m", help="slug modelki (domyslnie aktywna)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("konto", help="saldo kredytow / plan"); s.add_argument("--json", action="store_true"); s.set_defaults(f=cmd_konto)
    s = sub.add_parser("model", help="schema modelu z CLI (parametry, media)"); s.add_argument("jst", nargs="?", default="seedance_2_5"); s.set_defaults(f=cmd_model)
    s = sub.add_parser("status", help="co w kolejce, co czeka na prompt, saldo"); s.set_defaults(f=cmd_status)
    s = sub.add_parser("skanuj", help="nowe filmiki z zrodla/ -> pomysly + klatki"); s.add_argument("--ile", type=int, default=4); s.set_defaults(f=cmd_skanuj)
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
    s = sub.add_parser("budzet", help="limit dzienny kredytow (wspolny): max_kredyty_dziennie=300"); s.add_argument("pary", nargs="*"); s.set_defaults(f=cmd_budzet)
    s = sub.add_parser("ustaw", help="pokaz/zmien ustawienia: klucz=wartosc ..."); s.add_argument("pary", nargs="*"); s.set_defaults(f=cmd_ustaw)

    args = ap.parse_args(argv)
    try:
        return args.f(args) or 0
    except (ValueError, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code in (0, None):
            return 0
        print(f"[BLAD] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
