# -*- coding: utf-8 -*-
"""Autopilot: w petli, dla kazdej modelki z `autopilot: true`:

    telefon (Telegram) -> wrzutnia  |  skanuj -> generuj (Higgsfield albo yapper; bezpiecznik kredytow + max rolek
    dziennie + hamulec) -> Media Tool -> zdjecia (zdjecia_dziennie) -> podpisy -> gotowa rolka na telefon (konto persony
    z `telegram_czat` albo czat glowny) + raport dnia na telefon.
    Autopilot NIE robi lipsyncu (dopasowanie ust jest tylko recznie: panel -> Lipsync).

Uzycie:  python autopilot.py            petla (co `autopilot_co_minut` z ustawien; z Telegramem co minute; Ctrl+C konczy)
         python autopilot.py --raz      jeden przebieg i koniec (np. z Harmonogramu zadan Windows)
         python autopilot.py --modelka noemi --raz
Panel (app.py) odpala to samo w watku - przycisk Autopilot ON/OFF; autostart.bat = start razem z Windows.

Hamulec: `autopilot_stop_po_bledach` nieudanych rolek z rzedu -> pauza persony (modelki/<slug>/autopilot_stan.json),
alarm na telefon; wznowienie w panelu (Wznow) albo /wznow z Telegrama.
Nic nie robi, gdy modelka nie ma referencji/promptu - tylko loguje do dziennika.
"""
import argparse
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone

import baza
import dostawcy
import fabryka
import sekrety

if sys.platform == "win32":
    sys.stdout.reconfigure(errors="replace")

STAN = {"trwa": False, "ostatni": None, "nastepny": None, "modelka": None, "etap": "", "przebiegi": 0,
        "telegram_wiadomosci": 0, "opis": ""}   # opis: co dokladnie robi (widget Pierdolkomat), np. "robię rolkę z promptu: Noemi, ..."
_OSTRZEZENIA = set()            # ostrzezenia wyslane raz na uruchomienie (np. konto persony bez /start)
ODSTEP_TELEGRAM_S = 60          # z telefonem sprawdzamy wiadomosci co minute
RAPORT_GODZINA = 20             # raport dnia na telefon po tej godzinie (lokalnie)
POMOC = ("Jestem fabryka rolek.\n"
         "- Wyslij mi filmik (mp4) - zrobie z niego rolke i odesle gotowa. W podpisie mozesz wpisac nazwe persony.\n"
         "- Nagranie glosu z podpisem = nazwa filmiku zapisze przy tej rolce (usta dopasujesz w panelu -> Lipsync).\n"
         "- /status - co w kolejce i ile wydane\n- /raport - podsumowanie dnia\n- /zdjecie [persona] - zrob jedno zdjecie teraz\n"
         "- /stop - zatrzymaj robienie rolek\n- /wznow - wznow\n- /pomoc - ta lista")


def _log(msg):
    print(time.strftime("%H:%M:%S"), "[autopilot]", msg, flush=True)


def modelki_z_autopilotem(tylko=None):
    if tylko:
        return [tylko]
    return [m for m in baza.lista_modelek() if baza.ustawienia_modelki(m).get("autopilot")]


# ---------------- Telegram (telefon) ----------------

def _telegram():
    """Modul dostawcy telegram, gdy jest token; inaczej None."""
    try:
        from dostawcy import telegram
    except ImportError:
        return None
    return telegram if telegram.skonfigurowany() else None


def wyslij_na_telefon(tekst):
    """Tekst na sparowany czat (po cichu, gdy Telegram nie jest skonfigurowany/sparowany). Zwraca bool."""
    tg = _telegram()
    if not tg or not tg.sparowany():
        return False
    try:
        tg.wyslij_tekst(tekst)
        return True
    except Exception as e:
        baza.dziennik_zapisz("uwaga", f"telegram: nie wyslalem wiadomosci ({e})")
        return False


def _dozwolone_czaty():
    """Konta Telegram person z ustawien telegram_czat -> {"huy7128": "noemi"} (bot paruje tylko te i czat glowny)."""
    wynik = {}
    for slug in baza.lista_modelek():
        konto = (baza.ustawienia_modelki(slug).get("telegram_czat") or "").strip().lstrip("@").lower()
        if konto:
            wynik[konto] = slug
    return wynik


def persona_z_tekstu(tekst, domyslna=None):
    """'noemi' / '@Noemi' / 'Noemi dance' w podpisie -> slug; bez trafienia: `domyslna` (persona czatu, z ktorego
    przyszla wiadomosc), potem aktywna, potem pierwsza z autopilotem, potem pierwsza."""
    modelki = baza.lista_modelek()
    if not modelki:
        return None
    slowa = [w.strip("@#:,.!").lower() for w in (tekst or "").split()]
    for slug in modelki:
        nazwa = (baza.profil_modelki(slug).get("nazwa") or "").lower()
        if slug.lower() in slowa or (nazwa and nazwa in slowa):
            return slug
    if domyslna in modelki:
        return domyslna
    aktywna = baza.aktywna_modelka()
    if aktywna in modelki:
        return aktywna
    z_autopilotem = modelki_z_autopilotem()
    return z_autopilotem[0] if z_autopilotem else modelki[0]


def _unikalna(sciezka):
    if not os.path.exists(sciezka):
        return sciezka
    stem, ext = os.path.splitext(sciezka)
    for i in range(2, 1000):
        kandydat = f"{stem}_{i}{ext}"
        if not os.path.exists(kandydat):
            return kandydat
    return sciezka


def _nazwa_pliku(nazwa, domyslny_ext):
    nazwa = re.sub(r"[^\w.\- ]+", "_", os.path.basename(nazwa or ""), flags=re.UNICODE).strip(" ._")
    if not nazwa:
        nazwa = f"telefon_{time.strftime('%Y%m%d_%H%M%S')}{domyslny_ext}"
    if not os.path.splitext(nazwa)[1]:
        nazwa += domyslny_ext
    return nazwa


def _status_tekst():
    linie = []
    for slug in baza.lista_modelek():
        st = baza.statystyki_pomyslow(slug)
        ust = baza.ustawienia_modelki(slug)
        ap = baza.autopilot_stan(slug)
        d = ust.get("dostawca") or "higgsfield"
        if dostawcy.jednostka(d) == "c":
            wydane = (f"{dostawcy.kwota(baza.wydano_dzis(d), d)}/"
                      f"{dostawcy.kwota(baza.limit_dzienny(d), d) if baza.limit_dzienny(d) else '-'} ({d})")
        else:
            wydane = f"{baza.wydano_dzis(d)}/{baza.limit_dzienny(d) or '-'} kr"
        linie.append(f"{slug}: czeka {st.get('nowy', 0)}, " + (f"robi sie {st['w_toku']}, " if st.get("w_toku") else "")
                     + f"gotowe {st.get('gotowe', 0)}, nie wyszlo {st.get('blad', 0)}; "
                     f"dzis {len(baza.pomysly_z_dnia(slug))} rolek, {wydane}"
                     + (" | AUTOPILOT: " + ("PAUZA - " + ap["pauza"] if ap.get("pauza") else ("wlaczony" if ust.get("autopilot") else "wylaczony"))))
    try:
        linie.append(stan_z_promptu()["tekst"])
    except Exception:
        pass
    return "\n".join(linie) or "Brak person."


def raport_dnia(wymus=False):
    """Podsumowanie dnia na telefon (raz dziennie po RAPORT_GODZINA, albo na /raport). Zwraca tekst albo None."""
    tg = _telegram()
    if not tg or not tg.sparowany():
        return None
    dzis = datetime.now().strftime("%Y-%m-%d")
    s = tg.stan()
    if not wymus:
        if s.get("ostatni_raport") == dzis or datetime.now().hour < int(s.get("raport_godzina") or RAPORT_GODZINA):
            return None
    linie = [f"Raport {dzis}:"]
    for slug in baza.lista_modelek():
        rolki = baza.pomysly_z_dnia(slug)
        d = baza.ustawienia_modelki(slug).get("dostawca") or "higgsfield"
        linie.append(f"- {slug}: {len(rolki)} rolek, {len(baza.zdjecia_z_dnia(slug))} zdjec, {dostawcy.kwota(baza.wydano_dzis(d), d)} ({d})")
    try:
        zp = stan_z_promptu()
        if zp["dziennie"]:
            linie.append(f"Rolki z promptu (autopilot): {zp['dzis']} z {zp['dziennie']}"
                         + (f", nie wyszlo {zp['nieudane']}" if zp["nieudane"] else ""))
    except Exception:
        pass
    bledy = [w for w in baza.dziennik_ostatnie(500, typ="blad") if baza.dzien_lokalny(w.get("czas")) == dzis]
    if bledy:
        linie.append(f"Problemy dzis: {len(bledy)} (szczegoly w panelu -> Historia)")
    tekst = "\n".join(linie)
    if wyslij_na_telefon(tekst):
        tg.zapisz_stan(ostatni_raport=dzis)
    return tekst


def _obsluz_wiadomosc(tg, w, log):
    typ, tekst = w["typ"], (w.get("tekst") or "").strip()
    cid = w.get("chat_id")
    glowny = w.get("glowny", True)
    persona_czatu = w.get("persona")

    def odp(t):
        tg.wyslij_tekst(t, chat_id=cid)     # odpowiadamy tam, skad przyszla wiadomosc (czat glowny albo konto persony)

    if typ == "tekst":
        kom = tekst.split()[0].lower() if tekst else ""
        if kom in ("/start", "/pomoc", "/help", "/menu"):
            if glowny:
                odp("Sparowane - od teraz wysylam tu gotowe rolki.\n\n" + POMOC)
            else:
                odp(f"Sparowane - tu beda przychodzic gotowe rolki persony {persona_czatu or '?'}.\n\n" + POMOC)
                if w.get("nowy"):
                    wyslij_na_telefon(f"Konto @{w.get('od') or cid} sparowane - bedzie dostawac rolki persony {persona_czatu or '?'}.")
        elif kom == "/status":
            odp(_status_tekst())
        elif kom == "/raport":
            odp(raport_dnia(wymus=True) or "Brak danych.")
        elif kom == "/stop":
            if not glowny:
                odp("Zatrzymac moze tylko czat glowny (telefon wlasciciela).")
                return {"typ": "komenda", "tekst": kom, "odmowa": True}
            for slug in baza.lista_modelek():
                baza.autopilot_pauza(slug, "zatrzymane z telefonu (/stop)")
            baza.dziennik_zapisz("uwaga", "autopilot zatrzymany z telefonu (/stop)")
            odp("Zatrzymane. Filmiki nadal zbieram, ale nie robie rolek. /wznow - zeby wznowic.")
        elif kom in ("/wznow", "/dalej", "/go"):
            if not glowny:
                odp("Wznowic moze tylko czat glowny (telefon wlasciciela).")
                return {"typ": "komenda", "tekst": kom, "odmowa": True}
            for slug in baza.lista_modelek():
                baza.autopilot_wznow(slug)
            baza.dziennik_zapisz("info", "autopilot wznowiony z telefonu (/wznow)")
            odp("Wznowione. Robie dalej.")
        elif kom in ("/zdjecie", "/foto"):
            slug = persona_z_tekstu(" ".join(tekst.split()[1:]), domyslna=persona_czatu)
            ust = baza.ustawienia_modelki(slug) if slug else {}
            if not slug or not ust.get("zdjecia_model"):
                odp("Najpierw wybierz model zdjec w panelu (Ustawienia -> Zdjecia).")
            else:
                import zdjecia
                odp(f"Robie zdjecie ({slug})...")
                w = zdjecia.generuj(slug, ile=1, log=log)
                if w["zrobione"]:
                    wyslij_zdjecia(slug, log=log)
                else:
                    odp(f"Nie wyszlo: {w.get('stop') or 'blad generacji'}")
            return {"typ": "komenda", "tekst": kom, "modelka": slug}
        else:
            odp("Nie rozumiem. Wyslij filmik albo /pomoc.")
        return {"typ": "komenda", "tekst": kom}

    if typ == "wideo":
        slug = persona_z_tekstu(tekst, domyslna=persona_czatu)
        if not slug:
            odp("Nie mam zadnej persony - dodaj ja w panelu.")
            return {"typ": "wideo", "blad": "brak persony"}
        if (w.get("rozmiar") or 0) > tg.LIMIT_POBIERANIA:
            odp("Ten filmik ma ponad 20 MB - Telegram nie pozwala botom go pobrac. Wrzuc go do folderu na komputerze.")
            return {"typ": "wideo", "blad": "za duzy"}
        nazwa = _nazwa_pliku(w.get("nazwa"), ".mp4")
        cel = _unikalna(os.path.join(baza.folder_zrodel(slug), nazwa))
        tg.pobierz_plik(w["file_id"], cel)
        baza.dziennik_zapisz("info", f"z telefonu: {os.path.basename(cel)} -> wrzutnia {slug}", modelka=slug)
        log(f"telegram: {os.path.basename(cel)} -> {slug}")
        odp(f"Mam: {os.path.basename(cel)} -> {slug}. Zrobie rolke i odesle, jak bedzie gotowa.")
        return {"typ": "wideo", "plik": cel, "modelka": slug}

    if typ == "audio":
        slug = persona_z_tekstu(tekst, domyslna=persona_czatu)
        if not slug:
            odp("Nie mam zadnej persony - dodaj ja w panelu.")
            return {"typ": "audio", "blad": "brak persony"}
        ext = os.path.splitext(w.get("nazwa") or "")[1].lower() or ".mp3"
        if ext not in baza.ROZSZERZENIA_AUDIO:
            ext = ".mp3"
        # podpis = nazwa filmiku we wrzutni -> glos zapisany obok klipu (<nazwa>.audio.<ext>) i przy rolce (pole audio);
        # usta dopasowuje user recznie w panelu -> Lipsync (autopilot nie robi lipsyncu)
        wrzutnia = baza.folder_zrodel(slug)
        cel, para = None, None
        for slowo in [tekst] + tekst.split():
            stem = os.path.splitext(slowo.strip())[0]
            if stem and any(os.path.isfile(os.path.join(wrzutnia, stem + e)) for e in fabryka.ROZSZERZENIA_WIDEO):
                para = stem
                cel = os.path.join(wrzutnia, f"{stem}.audio{ext}")
                break
        if not cel:
            cel = _unikalna(os.path.join(baza.folder_audio(slug), _nazwa_pliku(w.get("nazwa"), ext)))
        tg.pobierz_plik(w["file_id"], cel)
        if para:
            p = baza.pomysl_po_zrodle(slug, next(os.path.join(wrzutnia, para + e) for e in fabryka.ROZSZERZENIA_WIDEO
                                                   if os.path.isfile(os.path.join(wrzutnia, para + e))))
            if p:
                baza.aktualizuj_pomysl(slug, p["id"], audio=cel)
            odp(f"Mam glos do {para} - zapisany przy tej rolce. Usta dopasujesz w panelu -> Lipsync (jednym kliknieciem).")
        else:
            odp(f"Mam nagranie ({os.path.basename(cel)}) - lezy w folderze audio persony. Usta dopasujesz w panelu -> Lipsync; "
                f"jesli to glos do konkretnego filmiku, wyslij je z podpisem = nazwa tego filmiku.")
        baza.dziennik_zapisz("info", f"z telefonu: glos {os.path.basename(cel)} ({slug})", modelka=slug)
        return {"typ": "audio", "plik": cel, "modelka": slug}

    if typ == "zdjecie":
        odp("Zdjecia persony i strojow dodaje sie w panelu (Ustawienia -> Persona). Filmiki moge brac stad.")
        return {"typ": "zdjecie"}
    odp("Nie wiem, co z tym zrobic. Wyslij filmik (mp4) albo /pomoc.")
    return {"typ": typ}


def obsluz_telegram(log=None):
    """Odbiera wiadomosci z telefonu: filmiki -> wrzutnia, glos -> lipsync, komendy. Zwraca liste obsluzonych."""
    log = log or _log
    tg = _telegram()
    if not tg:
        return []
    try:
        wiadomosci = tg.odbierz(dozwolone=_dozwolone_czaty())
    except Exception as e:
        log(f"telegram: nie moge odebrac ({e})")
        return []
    zrobione = []
    for w in wiadomosci:
        STAN["telegram_wiadomosci"] += 1
        try:
            zrobione.append(_obsluz_wiadomosc(tg, w, log))
        except Exception as e:
            log(f"telegram: {e}")
            baza.dziennik_zapisz("blad", f"telegram: {e}")
            try:
                tg.wyslij_tekst(f"Nie udalo sie: {e}", chat_id=w.get("chat_id"))
            except Exception:
                pass
    return zrobione


def czat_persony(tg, slug, ust=None, log=None):
    """Czat, na ktory leca gotowe rolki/zdjecia persony: konto z `telegram_czat` albo czat glowny.
    Zwraca chat_id albo None (konto persony nie napisalo jeszcze /start - ostrzezenie raz na uruchomienie)."""
    ust = ust or baza.ustawienia_modelki(slug)
    cid, opis = tg.czat_dla(ust.get("telegram_czat"))
    if cid:
        return cid
    klucz = f"czat:{slug}:{(ust.get('telegram_czat') or '').strip().lower()}"
    if klucz not in _OSTRZEZENIA:
        _OSTRZEZENIA.add(klucz)
        tekst = f"{slug}: rolki czekaja - {opis}. Z tego konta napisz /start do bota, wtedy wysle."
        baza.dziennik_zapisz("uwaga", "telegram: " + tekst, modelka=slug)
        (log or _log)("telegram: " + tekst)
        wyslij_na_telefon(tekst)
    return None


def _swiezy(p, godzin=24, pole="wygenerowano"):
    """Rolka wygenerowana (albo zmieniona - `pole`) w ciagu ostatnich `godzin`, zeby po sparowaniu nie wysylac calej historii."""
    try:
        t = datetime.fromisoformat(p.get(pole) or "")
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() < godzin * 3600


def wyslij_gotowe(slug, log=None):
    """Nowe gotowe rolki (jeszcze nie wyslane) -> telefon, z podpisem. Zwraca liczbe wyslanych."""
    log = log or _log
    tg = _telegram()
    ust = baza.ustawienia_modelki(slug)
    if not tg or not tg.sparowany() or not ust.get("telegram_wysylaj"):
        return 0
    def _ma_lipsync(p):
        return bool(p.get("lipsync_plik")) and os.path.isfile(p["lipsync_plik"])

    # nowa gotowa rolka albo rolka, ktora dostala wersje z dopasowanymi ustami (lipsync robiony recznie, pozniej)
    do_wyslania = [p for p in baza.lista_pomyslow(slug)
                   if p["status"] in ("gotowe", "wygenerowany")
                   and ((not p.get("telegram_wyslano") and _swiezy(p))
                        or (_ma_lipsync(p) and not p.get("telegram_wyslano_lipsync") and _swiezy(p, pole="zaktualizowano")))]
    if not do_wyslania:
        return 0
    cid = czat_persony(tg, slug, ust, log)
    if not cid:
        return 0
    ile = 0
    for p in do_wyslania:
        z_lipsynciem = _ma_lipsync(p)
        plik = p["lipsync_plik"] if z_lipsynciem else p.get("plik_wynikowy")
        if not plik or not os.path.isfile(plik):
            continue
        podpis = (p.get("podpis") or "").strip()
        tekst = f"{slug} · rolka #{p['id']}" + (" · z dopasowanymi ustami" if z_lipsynciem else "") + f" · {os.path.basename(plik)}" \
            + (f"\n\n{podpis}" if podpis else "")
        try:
            tg.wyslij_wideo(plik, tekst, chat_id=cid)
            baza.aktualizuj_pomysl(slug, p["id"], telegram_wyslano=True, **({"telegram_wyslano_lipsync": True} if z_lipsynciem else {}))
            ile += 1
            log(f"telegram: wyslalem #{p['id']} ({os.path.basename(plik)})")
        except Exception as e:
            log(f"telegram: nie wyslalem #{p['id']}: {e}")
            baza.dziennik_zapisz("uwaga", f"telegram: nie wyslalem rolki #{p['id']} ({e})", modelka=slug)
            break
    return ile


def porzadki(log=None):
    """Raz dziennie: kasuje surowe .raw.mp4 starsze niz sprzataj_po_dniach (gdy gotowy plik istnieje) i robi kopie
    plikow .json persony do modelki/_kopie/<data>/ (7 dni). Zwraca {"usuniete": n, "kopie": n}."""
    import shutil
    log = log or _log
    wynik = {"usuniete": 0, "kopie": 0}
    dzis = datetime.now().strftime("%Y-%m-%d")
    kopie_dir = os.path.join(baza.KATALOG_MODELEK, "_kopie")
    for slug in baza.lista_modelek():
        ust = baza.ustawienia_modelki(slug)
        dni = int(ust.get("sprzataj_po_dniach") or 0)
        if dni:
            granica = time.time() - dni * 86400
            for p in baza.lista_pomyslow(slug):
                if p["status"] != "gotowe":
                    continue
                gotowy = p.get("plik_wynikowy")
                for kandydat in {os.path.join(baza.folder_wynikow(slug), n) for n in os.listdir(baza.folder_wynikow(slug))
                                 if n.startswith(f"{p['id']:03d}_") and n.endswith(".raw.mp4")}:
                    if gotowy and os.path.isfile(gotowy) and os.path.abspath(gotowy) != os.path.abspath(kandydat) \
                            and os.path.getmtime(kandydat) < granica:
                        try:
                            os.remove(kandydat)
                            wynik["usuniete"] += 1
                        except OSError as e:
                            log(f"porzadki: nie usunalem {kandydat}: {e}")
        # kopia zapasowa json-ow (kolejka, ustawienia, teksty...)
        cel = os.path.join(kopie_dir, dzis, slug)
        try:
            os.makedirs(cel, exist_ok=True)
            folder = baza.folder_modelki(slug)
            for n in os.listdir(folder):
                if n.endswith(".json"):
                    shutil.copy2(os.path.join(folder, n), os.path.join(cel, n))
                    wynik["kopie"] += 1
        except OSError as e:
            log(f"porzadki: kopia {slug}: {e}")
    # stare kopie (> 7 dni) won
    if os.path.isdir(kopie_dir):
        for n in sorted(os.listdir(kopie_dir))[:-7]:
            shutil.rmtree(os.path.join(kopie_dir, n), ignore_errors=True)
    if wynik["usuniete"]:
        baza.dziennik_zapisz("info", f"porzadki: usunieto {wynik['usuniete']} starych surowych plikow, kopia json: {wynik['kopie']}")
    return wynik


def wyslij_zdjecia(slug, log=None):
    """Nowe gotowe zdjecia (dzisiejsze, nie wyslane) -> telefon. Zwraca liczbe wyslanych."""
    log = log or _log
    tg = _telegram()
    ust = baza.ustawienia_modelki(slug)
    if not tg or not tg.sparowany() or not ust.get("telegram_wysylaj"):
        return 0
    do_wyslania = [z for z in baza.zdjecia_z_dnia(slug) if not z.get("telegram_wyslano") and z.get("plik") and os.path.isfile(z["plik"])]
    if not do_wyslania:
        return 0
    cid = czat_persony(tg, slug, ust, log)
    if not cid:
        return 0
    ile = 0
    for z in do_wyslania:
        try:
            # podmiana postaci (swap): krotki opis zamiast dlugiego angielskiego promptu
            opis = z.get("opis") if z.get("typ") == "swap" else z.get("prompt")
            tg.wyslij_zdjecie(z["plik"], f"{slug} · zdjecie #{z['id']}" + (" · strój" if z.get("stroj") else "") + f"\n{opis or ''}".rstrip(),
                              chat_id=cid)
            import zdjecia as _zdj
            _zdj._ustaw(slug, z["id"], telegram_wyslano=True)
            ile += 1
        except Exception as e:
            log(f"telegram: nie wyslalem zdjecia #{z['id']}: {e}")
            break
    return ile


# ---------------- rolki z promptu (3.3): autopilot sam robi rolki bez filmikow ----------------
# Raz na przebieg (co 15 min / co minute z Telegramem), po rolkach ze swapu: gdy dzis jest mniej niz `dziennie` rolek z promptu
# zrobionych przez autopilota (licznik osobny od rolek ze swapu; dzien lokalny), jest juz `od_godziny` i nie bylo 2 nieudanych
# prob -> nastepna persona na zmiane (ze zdjeciami, bez pauzy) -> losowy gotowy pomysl + asystent (jak "Losuj" w panelu) ->
# darmowa wycena (`generate cost`) i bezpieczniki (limit dnia wspolny, min_kredyty, max na rolke) -> ta sama bezpieczna sciezka co
# reczne "Zrob rolke" (fabryka.generuj po id: znacznik w_toku, create bez --wait, job_id od razu, nigdy drugi create) ->
# komentarz ElevenLabs, Media Tool, folder "tu rolki zrobione", Telegram. Jedna rolka naraz; w toku = czekamy (wznowienie 0 kr).

MODELE_Z_PROMPTU = {
    "seedance_2_5": {"nazwa": "Seedance 2.5 · 720p · 10 s (ok. 70 kr)", "szacunek": 70},
    "wan3_0_prime": {"nazwa": "Wan 3.0 Prime · 720p · 10 s (ok. 30 kr)", "szacunek": 30},
}
DLUGOSC_Z_PROMPTU = 10
ROZDZIELCZOSC_Z_PROMPTU = "720p"
MAX_NIEUDANYCH_Z_PROMPTU = 2        # tyle nieudanych prob dziennie (NSFW/IP/blad) na cala pule person - potem koniec na dzis
MAX_DZIENNIE_Z_PROMPTU = 20
PONOW_PO_POMINIECIU_S = 15 * 60     # pominieta (limit dnia, saldo): nastepne sprawdzenie najwczesniej po tylu s (bez spamu CLI/dziennika)
_Z_PROMPTU = {"pominiete_do": 0.0, "powod": "", "dzien": "", "wpisy": set()}

# rolki z Instagrama (zrodlo klipow do swapa przez Apify, 3.4)
MAX_DZIENNIE_IG = 50


def _godzina(t):
    """'10:00' / '9.30' -> '10:00' / '09:30'; zla -> None."""
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})\s*$", str(t or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"


def ustawienia_z_promptu():
    """Ustawienia autopilota rolek z promptu (globalne, Ustawienia -> Autopilot): dziennie 0-20 (0 = wylaczone), model,
    persony (lista slugow; [] = wszystkie ze zdjeciami), od_godziny HH:MM (czas lokalny)."""
    u = dict(baza.ustawienia_globalne().get("autopilot_z_promptu") or {})
    dom = baza.USTAWIENIA_GLOBALNE_DOMYSLNE["autopilot_z_promptu"]
    try:
        dziennie = int(u["dziennie"]) if u.get("dziennie") not in (None, "") else dom["dziennie"]
    except (TypeError, ValueError):
        dziennie = dom["dziennie"]
    persony = u.get("persony") if isinstance(u.get("persony"), list) else []
    return {"dziennie": max(0, min(MAX_DZIENNIE_Z_PROMPTU, dziennie)),
            "model": u.get("model") if u.get("model") in MODELE_Z_PROMPTU else dom["model"],
            "persony": [str(s).strip() for s in persony if str(s).strip()],
            "od_godziny": _godzina(u.get("od_godziny")) or dom["od_godziny"]}


def sprawdz_ustawienia_z_promptu(v):
    """Zmiany z panelu (dowolne z pol: dziennie, model, persony, od_godziny) -> sprawdzone wartosci. ValueError po polsku."""
    if not isinstance(v, dict):
        raise ValueError("autopilot_z_promptu musi byc slownikiem.")
    wynik = {}
    for k, x in v.items():
        if k == "dziennie":
            try:
                n = int(x)
            except (TypeError, ValueError):
                raise ValueError("Rolki z promptu dziennie: podaj liczbe (0 = wylaczone).")
            if not 0 <= n <= MAX_DZIENNIE_Z_PROMPTU:
                raise ValueError(f"Rolki z promptu dziennie: od 0 do {MAX_DZIENNIE_Z_PROMPTU}.")
            wynik[k] = n
        elif k == "model":
            if x not in MODELE_Z_PROMPTU:
                raise ValueError(f"Model rolek z promptu: {' albo '.join(MODELE_Z_PROMPTU)}.")
            wynik[k] = x
        elif k == "persony":
            lista = x if isinstance(x, list) else str(x or "").split(",")
            lista = [str(s).strip() for s in lista if str(s).strip()]
            nieznane = [s for s in lista if s not in baza.lista_modelek()]
            if nieznane:
                raise ValueError(f"Nie ma person: {', '.join(nieznane)}.")
            wynik[k] = lista
        elif k == "od_godziny":
            g = _godzina(x)
            if not g:
                raise ValueError("Godzina w formacie GG:MM, np. 10:00.")
            wynik[k] = g
        else:
            raise ValueError(f"Nieznane ustawienie autopilot_z_promptu.{k}.")
    return wynik


def rolki_z_promptu_z_dnia(dzien=None):
    """Rolki z promptu zrobione przez AUTOPILOTA danego dnia (lokalnego, wg utworzono) - wszystkie persony:
    {"zrobione": [(slug, p)] (w toku albo gotowe), "w_toku", "nieudane" (blad: NSFW/IP/techniczny), "czeka" (nowy - np. po
    awarii miedzy dodaniem a wyslaniem)}. Reczne rolki z promptu i rolki ze swapu sie nie licza."""
    dzien = dzien or baza._dzis()
    w = {"zrobione": [], "w_toku": [], "nieudane": [], "czeka": []}
    for slug in baza.lista_modelek():
        for p in baza.lista_pomyslow(slug):
            if not p.get("autopilot_z_promptu") or baza.dzien_lokalny(p.get("utworzono")) != dzien:
                continue
            st = p.get("status")
            if st == "blad":
                w["nieudane"].append((slug, p))
            elif st == "nowy":
                w["czeka"].append((slug, p))
            else:
                w["zrobione"].append((slug, p))
                if st == "w_toku":
                    w["w_toku"].append((slug, p))
    return w


def persony_z_promptu(u=None):
    """Persony do rolek z promptu: wybrane w ustawieniach (puste = wszystkie) i majace zdjecia w referencje/ - w tej kolejnosci."""
    u = u or ustawienia_z_promptu()
    wszystkie = baza.lista_modelek()
    return [s for s in (u["persony"] or wszystkie) if s in wszystkie and baza.sciezki_referencji(s)]


def nastepna_persona(kandydaci):
    """Na zmiane po kolei: persona po tej, ktora miala ostatnia rolke z promptu autopilota (najnowsza w ogole); pierwszy raz -
    pierwsza z listy. Persony w pauzie (hamulec, /stop z telefonu) pomijamy. None = zadna."""
    if not kandydaci:
        return None
    ostatnia, czas = None, ""
    for slug in baza.lista_modelek():
        for p in baza.lista_pomyslow(slug):
            if p.get("autopilot_z_promptu") and str(p.get("utworzono") or "") > czas:
                ostatnia, czas = slug, str(p.get("utworzono") or "")
    if ostatnia in kandydaci:
        i = kandydaci.index(ostatnia)
        kandydaci = kandydaci[i + 1:] + kandydaci[:i + 1]
    return next((s for s in kandydaci if not baza.autopilot_stan(s).get("pauza")), None)


def _nazwa(slug):
    return (baza.profil_modelki(slug).get("nazwa") or slug).strip() or slug


def _wpis_raz(klucz, typ, tekst, modelka=None):
    """Wpis w dzienniku raz dziennie dla danego klucza (przebieg co minute nie zasypie Historii tym samym)."""
    dzien = baza._dzis()
    if _Z_PROMPTU["dzien"] != dzien:
        _Z_PROMPTU.update(dzien=dzien, wpisy=set())
    if klucz in _Z_PROMPTU["wpisy"]:
        return False
    _Z_PROMPTU["wpisy"].add(klucz)
    baza.dziennik_zapisz(typ, tekst, modelka=modelka)
    return True


def _pomin(klucz, powod, log, modelka=None):
    """Rolka z promptu pominieta (limit dnia, saldo, cena...): jasny wpis raz dziennie, nastepna proba za PONOW_PO_POMINIECIU_S."""
    _Z_PROMPTU.update(pominiete_do=time.time() + PONOW_PO_POMINIECIU_S, powod=powod)
    tekst = f"Autopilot: rolka z promptu pominieta - {powod}"
    log(tekst)
    _wpis_raz(klucz, "uwaga", tekst, modelka=modelka)
    return {"stan": "pominieta", "powod": powod}


def krok_z_promptu(log=None, stop=None, teraz=None):
    """Jeden krok autopilota rolek z promptu (patrz opis sekcji). Zwraca {"stan": wylaczone | gotowe | limit_prob | przed_godzina |
    w_toku | brak_person | pominieta | zrobiona | nie_wyszla | ..., ...}. STOP (Przerwano) przechodzi dalej jak w innych krokach."""
    log = log or _log
    teraz = teraz or datetime.now()
    u = ustawienia_z_promptu()
    n = u["dziennie"]
    if n <= 0:
        return {"stan": "wylaczone"}
    dzien = teraz.strftime("%Y-%m-%d")
    d = rolki_z_promptu_z_dnia(dzien)
    # rolka autopilota z wyslanym jobem (STOP, limit czasu, restart): dokanczamy TEN job (0 kr), zanim cokolwiek nowego
    for slug in sorted({s for s, _ in d["w_toku"]}):
        STAN["etap"], STAN["modelka"], STAN["opis"] = "z_promptu", slug, f"kończę rolkę z promptu: {_nazwa(slug)}"
        fabryka.wznow_w_toku(slug, log=log, stop=stop, lipsync=False)
        wyslij_gotowe(slug, log=log)
    if d["w_toku"]:
        d = rolki_z_promptu_z_dnia(dzien)
    if d["w_toku"]:
        return {"stan": "w_toku"}                   # jedna naraz - nic nowego, dopoki tamta sie nie wyjasni
    if len(d["zrobione"]) >= n:
        return {"stan": "gotowe"}
    if len(d["nieudane"]) >= MAX_NIEUDANYCH_Z_PROMPTU:
        _wpis_raz("limit_prob", "uwaga", f"Autopilot: {len(d['nieudane'])} rolki z promptu dzis nie wyszly - kolejne jutro (zeby nie "
                  f"palic kredytow w petli).")
        return {"stan": "limit_prob"}
    if teraz.strftime("%H:%M") < u["od_godziny"]:
        return {"stan": "przed_godzina"}
    if time.time() < _Z_PROMPTU["pominiete_do"]:
        return {"stan": "pominieta", "powod": _Z_PROMPTU["powod"]}
    czeka = [(s, p) for s, p in d["czeka"] if not baza.autopilot_stan(s).get("pauza")]     # persona w pauzie (/stop) - nie
    if czeka:
        # rolka dodana, ale nie wyslana (awaria panelu, persona zajeta) - ta sama, bez nowego losowania
        slug, p = czeka[0]
        kr = (p.get("z_promptu") or {}).get("wycena") or p.get("koszt")
        opis = (p.get("z_promptu") or {}).get("obiekt_nazwa") or (p.get("z_promptu") or {}).get("miejsce_nazwa") or p.get("opis")
        return _zrob_z_promptu(slug, p["id"], kr, opis, log, stop, len(d["zrobione"]), n, len(d["nieudane"]))
    kandydaci = persony_z_promptu(u)
    slug = nastepna_persona(kandydaci)
    if not slug:
        powod = ("zadna persona nie ma zdjec w referencje/" if not kandydaci else "wszystkie persony sa w pauzie (hamulec / /stop)")
        _wpis_raz("brak_person", "uwaga", f"Autopilot: rolki z promptu czekaja - {powod}.")
        return {"stan": "brak_person"}
    import asystent
    import scenariusz
    STAN["etap"], STAN["modelka"], STAN["opis"] = "z_promptu", slug, f"dobieram rolkę z promptu: {_nazwa(slug)}"
    pomysl = scenariusz.losuj_pomysl(slug)
    try:
        import komentarz_glos
        tts = komentarz_glos.tts_dostepne()[0]
    except Exception:
        tts = False
    a = asystent.dobierz(slug, pomysl["pl"], pomysl_id=pomysl["id"], zablokowane={
        "model": u["model"], "dlugosc": DLUGOSC_Z_PROMPTU, "rozdzielczosc": ROZDZIELCZOSC_Z_PROMPTU},
        glos_efektywny="tts" if tts else "brak")
    opcje = dict(a["opcje"], model=u["model"], dlugosc=DLUGOSC_Z_PROMPTU, rozdzielczosc=ROZDZIELCZOSC_Z_PROMPTU)
    try:
        w = fabryka.wycena_z_promptu(slug, opcje, z_cena=True)
    except ValueError as e:
        return _pomin("zle_opcje", f"{_nazwa(slug)}: {e}", log, modelka=slug)
    if not w["mozna"] or w.get("kr") is None:
        powody = "; ".join(w["powody"]) or "Higgsfield nie podal ceny"
        klucz = ("limit" if "limit" in powody else "saldo" if "minimum" in powody or "salda" in powody
                 else "max" if "bezpiecznik" in powody else "cena")
        return _pomin(klucz, f"{_nazwa(slug)} ({MODELE_Z_PROMPTU[u['model']]['nazwa']}): {powody}", log, modelka=slug)
    pid = fabryka.dodaj_z_promptu(slug, dict(opcje, ustalone=w["ustalone"], asystent=a), kr=w["kr"], autopilot_z_promptu=True)
    opis = w.get("obiekt_nazwa") or w.get("miejsce_nazwa") or pomysl["pl"]
    baza.dziennik_zapisz("info", f"autopilot z promptu: {_nazwa(slug)} #{pid} - {opis} ({w['model']} {w['dlugosc']} s "
                         f"{w['rozdzielczosc']}, ~{w['kr']} kr; rolka {len(d['zrobione']) + 1} z {n} dzis). {a['podsumowanie']}",
                         modelka=slug, pomysl=pid)
    return _zrob_z_promptu(slug, pid, w["kr"], opis, log, stop, len(d["zrobione"]), n, len(d["nieudane"]))


def _zrob_z_promptu(slug, pid, kr, opis, log, stop, zrobione, dziennie, nieudane):
    """Generacja rolki z promptu po id - ta sama sciezka co reczne "Zrob rolke" (cena jeszcze raz tuz przed wyslaniem: wyzsza niz
    kr = nic nie idzie), potem Telegram. Wynik w dzienniku."""
    STAN["etap"], STAN["modelka"] = "z_promptu", slug
    STAN["opis"] = f"robię rolkę z promptu: {_nazwa(slug)}, {opis}"

    def cena_ok(p, k, *_):
        if kr is not None and k is not None and k > kr:
            log(f"#{p['id']}: cena wzrosla z {kr} do {k} kr - NIE wysylam")
            return False
        return True
    try:
        wynik = fabryka.generuj(slug, ids=[pid], potwierdz=cena_ok, log=log, stop=stop, lipsync=False)
    except ValueError as e:              # rolka juz nie do zrobienia (np. usunieta w panelu)
        log(f"rolka z promptu #{pid}: {e}")
        return {"stan": "nie_do_zrobienia", "slug": slug, "pid": pid}
    p = baza.pomysl(slug, pid)
    st = p.get("status")
    if st in ("gotowe", "wygenerowany", "postprodukcja"):
        baza.dziennik_zapisz("ok", f"autopilot z promptu: {_nazwa(slug)} #{pid} gotowa ({p.get('koszt')} kr) - rolka "
                             f"{zrobione + 1} z {dziennie} dzis", modelka=slug, pomysl=pid)
        try:
            wyslij_gotowe(slug, log=log)
        except Exception as e:
            log(f"telegram: {e}")
        return {"stan": "zrobiona", "slug": slug, "pid": pid}
    if st == "w_toku":
        baza.dziennik_zapisz("info", f"autopilot z promptu: {_nazwa(slug)} #{pid} jeszcze sie robi - dokoncze przy nastepnym "
                             f"przebiegu (bez wysylania drugi raz)", modelka=slug, pomysl=pid)
        return {"stan": "w_toku", "slug": slug, "pid": pid}
    if st == "nowy" and pid in (wynik.get("pominiete") or []):
        # cena wyzsza niz zatwierdzona / ponad max na rolke - nic nie poszlo; liczy sie jak nieudana proba (bez petli)
        baza.aktualizuj_pomysl(slug, pid, status="blad", powod="inny",
                               notatki="Autopilot: nic nie wyslane (cena wyzsza niz z wyceny albo ponad max na rolke) - 0 kr.")
        st = "blad"
    elif st == "nowy":
        # bezpiecznik (limit dnia, saldo) albo persona zajeta - rolka czeka, sprobujemy pozniej (ta sama rolka)
        return _pomin("generuj_" + str(wynik.get("stop") or "?"), f"{_nazwa(slug)} #{pid}: {wynik.get('stop') or 'nie ruszyla'} - "
                      f"sprobuje pozniej", log, modelka=slug)
    if st == "blad":
        p = baza.pomysl(slug, pid)
        powod = {"nsfw": "filtr NSFW", "ip": "filtr IP (znana marka/postac)"}.get(p.get("powod"), "blad")
        baza.dziennik_zapisz("uwaga", f"autopilot z promptu: {_nazwa(slug)} #{pid} nie wyszla ({powod}) - proba {nieudane + 1} z "
                             f"{MAX_NIEUDANYCH_Z_PROMPTU} nieudanych dzis; asystent uczy sie z tego (inny stroj/miejsce nastepnym "
                             f"razem), nic nie wysylam drugi raz", modelka=slug, pomysl=pid)
        return {"stan": "nie_wyszla", "slug": slug, "pid": pid, "powod": p.get("powod")}
    return {"stan": st or "?", "slug": slug, "pid": pid}


def stan_z_promptu(wlaczony=None, teraz=None):
    """Dla panelu (Start -> autopilot) i telefonu: {"dziennie", "dzis", "nieudane", "model", "od_godziny", "persony", "stan",
    "tekst": "Rolki z promptu: dziś X z N (następna po 10:00 / gotowe)"}. wlaczony = czy petla autopilota dziala."""
    u = ustawienia_z_promptu()
    teraz = teraz or datetime.now()
    d = rolki_z_promptu_z_dnia(teraz.strftime("%Y-%m-%d"))
    n, x = u["dziennie"], len(d["zrobione"])
    persony = persony_z_promptu(u)
    wynik = {"dziennie": n, "dzis": x, "nieudane": len(d["nieudane"]), "model": u["model"], "od_godziny": u["od_godziny"],
             "persony": persony, "model_nazwa": MODELE_Z_PROMPTU[u["model"]]["nazwa"]}
    if n <= 0:
        wynik.update(stan="wylaczone", tekst="Rolki z promptu: wyłączone (Ustawienia → Autopilot).")
        return wynik
    if d["w_toku"] or (STAN.get("trwa") and STAN.get("etap") == "z_promptu"):
        slug = (d["w_toku"][0][0] if d["w_toku"] else STAN.get("modelka")) or ""
        stan, dopisek = "w_toku", f"robi się{': ' + _nazwa(slug) if slug in baza.lista_modelek() else ''}"
    elif x >= n:
        stan, dopisek = "gotowe", "gotowe"
    elif len(d["nieudane"]) >= MAX_NIEUDANYCH_Z_PROMPTU:
        stan, dopisek = "limit_prob", f"{len(d['nieudane'])} nie wyszły – następne jutro"
    elif wlaczony is False:
        stan, dopisek = "autopilot_wylaczony", "autopilot wyłączony"
    elif not persony:
        stan, dopisek = "brak_person", "żadna persona nie ma zdjęć"
    elif teraz.strftime("%H:%M") < u["od_godziny"]:
        stan, dopisek = "przed_godzina", f"następna po {u['od_godziny']}"
    elif time.time() < _Z_PROMPTU["pominiete_do"]:
        stan, dopisek = "pominieta", "pominięta: " + (_Z_PROMPTU["powod"] or "bezpiecznik")[:120]
    else:
        stan, dopisek = "czeka", "następna przy najbliższym sprawdzeniu"
    wynik.update(stan=stan, tekst=f"Rolki z promptu: dziś {x} z {n} ({dopisek})")
    return wynik


# ---------------- rolki z Instagrama (zrodlo klipow do swapa, 3.4) ----------------

def _handle_ig(h):
    """'@Noemi' / 'instagram.com/noemi/' / 'noemi' -> 'noemi'."""
    s = str(h or "").strip()
    m = re.search(r"instagram\.com/([^/?#]+)", s, re.I)
    if m:
        s = m.group(1)
    return s.lstrip("@").strip().strip("/").lower()


def ustawienia_rolki_ig():
    """Ustawienia pobierania rolek z IG (globalne, Ustawienia -> Autopilot -> Rolki z Instagrama)."""
    u = dict(baza.ustawienia_globalne().get("autopilot_rolki_ig") or {})
    dom = baza.USTAWIENIA_GLOBALNE_DOMYSLNE["autopilot_rolki_ig"]
    def _int(klucz, mini, maxi):
        try:
            v = int(u[klucz]) if u.get(klucz) not in (None, "") else dom[klucz]
        except (TypeError, ValueError):
            v = dom[klucz]
        return max(mini, min(maxi, v))
    profile = [_handle_ig(p) for p in (u.get("profile") if isinstance(u.get("profile"), list) else [])]
    do_person = str(u.get("do_person") or dom["do_person"]).strip() or dom["do_person"]
    return {"wlaczone": bool(u.get("wlaczone")),
            "profile": [p for p in dict.fromkeys(profile) if p],
            "konto_obserwowanych": _handle_ig(u.get("konto_obserwowanych") or ""),
            "dziennie": _int("dziennie", 0, MAX_DZIENNIE_IG),
            "kandydatow_na_profil": _int("kandydatow_na_profil", 1, 50),
            "do_person": do_person,
            "pobieranie_przez_apify": bool(u.get("pobieranie_przez_apify"))}


def sprawdz_ustawienia_rolki_ig(v):
    """Zmiany z panelu (dowolne pola) -> sprawdzone wartosci. ValueError po polsku. `profile` przyjmuje liste albo tekst
    (po jednym @ w linii / po przecinku)."""
    if not isinstance(v, dict):
        raise ValueError("autopilot_rolki_ig musi byc slownikiem.")
    wynik = {}
    for k, x in v.items():
        if k in ("wlaczone", "pobieranie_przez_apify"):
            wynik[k] = bool(x)
        elif k == "dziennie":
            try:
                n = int(x)
            except (TypeError, ValueError):
                raise ValueError("Rolek z IG dziennie: podaj liczbe (0 = nie pobieraj).")
            if not 0 <= n <= MAX_DZIENNIE_IG:
                raise ValueError(f"Rolek z IG dziennie: od 0 do {MAX_DZIENNIE_IG}.")
            wynik[k] = n
        elif k == "kandydatow_na_profil":
            try:
                n = int(x)
            except (TypeError, ValueError):
                raise ValueError("Kandydatow na profil: podaj liczbe.")
            if not 1 <= n <= 50:
                raise ValueError("Kandydatow na profil: od 1 do 50.")
            wynik[k] = n
        elif k == "profile":
            lista = x if isinstance(x, list) else re.split(r"[\n,]+", str(x or ""))
            wynik[k] = [h for h in dict.fromkeys(_handle_ig(s) for s in lista) if h]
        elif k == "konto_obserwowanych":
            wynik[k] = _handle_ig(x)
        elif k == "do_person":
            s = str(x or "round-robin").strip() or "round-robin"
            if s != "round-robin" and s not in baza.lista_modelek():
                raise ValueError(f"Nie ma persony '{s}'.")
            wynik[k] = s
        else:
            raise ValueError(f"Nieznane ustawienie autopilot_rolki_ig.{k}.")
    return wynik


def persony_ig(u=None):
    """Persony, do ktorych lecą pobrane rolki: 'round-robin' = wszystkie z referencjami; konkretny slug = tylko ta (gdy ma zdjecia)."""
    u = u or ustawienia_rolki_ig()
    wszystkie = baza.lista_modelek()
    kand = [u["do_person"]] if (u["do_person"] != "round-robin" and u["do_person"] in wszystkie) else list(wszystkie)
    return [s for s in kand if baza.sciezki_referencji(s)]


def krok_rolki_ig(log=None, stop=None, teraz=None):
    """Jeden krok autopilota: pobierz najnowsze rolki z profili IG (Apify), odsiej AI/heurystykami, dobre zapisz do
    wrzutni person (skanuj je potem podejmie). Dzienny limit `dziennie` (osobny od generacji). STOP/wylaczenie konczy krok.
    Zwraca {"stan": wylaczone|brak_klucza|gotowe|brak_person|brak_profili|pobrane|nic_nowego|blad, ...}."""
    log = log or _log
    u = ustawienia_rolki_ig()
    if not u["wlaczone"] or u["dziennie"] <= 0:
        return {"stan": "wylaczone"}
    if not sekrety.klucz("apify"):
        _wpis_raz("ig_brak_klucza", "uwaga", "Autopilot IG: pobieranie rolek wlaczone, ale brak klucza Apify - "
                  "wklej go w Ustawienia -> Konta -> Apify.")
        return {"stan": "brak_klucza"}
    import instagram_rolki
    pobrane = instagram_rolki.pobrane_z_dnia()
    zostalo = u["dziennie"] - pobrane
    if zostalo <= 0:
        return {"stan": "gotowe", "pobrane": pobrane}
    persony = persony_ig(u)
    if not persony:
        _wpis_raz("ig_brak_person", "uwaga", "Autopilot IG: nie ma do kogo zapisac rolek - zadna persona nie ma zdjec w referencje/.")
        return {"stan": "brak_person"}
    profile = list(u["profile"])
    if u["konto_obserwowanych"]:
        try:
            from dostawcy import instagram
            profile = list(dict.fromkeys(profile + instagram.obserwowani(u["konto_obserwowanych"])))
        except Exception as e:
            _wpis_raz("ig_obserwowani", "uwaga", f"Autopilot IG: {e}")
    if not profile:
        _wpis_raz("ig_brak_profili", "uwaga", "Autopilot IG: wklej @ profile tworczyn (Ustawienia -> Autopilot -> Rolki z Instagrama).")
        return {"stan": "brak_profili"}
    STAN["etap"], STAN["modelka"], STAN["opis"] = "rolki_ig", None, "pobieram rolki z IG"
    try:
        w = instagram_rolki.pobierz_filtruj_zapisz(profile, persony, limit=zostalo, na_profil=u["kandydatow_na_profil"],
                                                   przez_apify=u["pobieranie_przez_apify"], uzyj_ai=True, log=log, stop=stop)
    except dostawcy.BrakKlucza:
        _wpis_raz("ig_brak_klucza", "uwaga", "Autopilot IG: brak klucza Apify.")
        return {"stan": "brak_klucza"}
    except dostawcy.BladDostawcy as e:
        STAN["opis"] = ""
        _wpis_raz("ig_blad", "uwaga", f"Autopilot IG: {e}")
        return {"stan": "blad", "blad": str(e)}
    n = len(w["zapisane"])
    if n:
        per = {}
        for slug, _, _ in w["zapisane"]:
            per[slug] = per.get(slug, 0) + 1
        baza.dziennik_zapisz("ok", f"Autopilot IG: pobrano {n} nowych rolek ({', '.join(f'{_nazwa(s)}: {c}' for s, c in per.items())}); "
                             f"odrzucone {len(w['odrzucone'])} z {w['kandydaci']} kandydatow. "
                             f"AI: {'tak' if w['ai'] else 'tylko heurystyki'}.")
    else:
        log(f"Autopilot IG: nic nowego (kandydaci {w['kandydaci']}, odrzucone {len(w['odrzucone'])}, pominiete {w['pominiete']})")
    STAN["opis"] = f"pobieram rolki z IG: {n} nowych" if n else "IG: nic nowego"    # dla widgetu (claudzik/jarvis/widget.py)
    return {"stan": "pobrane" if n else "nic_nowego", "nowe": n, "odrzucone": len(w["odrzucone"]),
            "kandydaci": w["kandydaci"], "pominiete": w["pominiete"], "ai": w["ai"]}


def stan_rolki_ig(wlaczony=None):
    """Dla panelu (Start / Ustawienia -> Autopilot) i widgetu: {wlaczone, dziennie, dzis, profile, persony, stan, tekst}."""
    u = ustawienia_rolki_ig()
    import instagram_rolki
    pobrane = instagram_rolki.pobrane_z_dnia()
    persony = persony_ig(u)
    wynik = {"wlaczone": u["wlaczone"], "dziennie": u["dziennie"], "dzis": pobrane, "profile": u["profile"],
             "konto_obserwowanych": u["konto_obserwowanych"], "do_person": u["do_person"], "persony": persony,
             "kandydatow_na_profil": u["kandydatow_na_profil"], "ma_klucz": bool(sekrety.klucz("apify")),
             "pobieranie_przez_apify": u["pobieranie_przez_apify"]}
    if not u["wlaczone"] or u["dziennie"] <= 0:
        wynik.update(stan="wylaczone", tekst="Rolki z Instagrama: wyłączone (Ustawienia → Autopilot).")
    elif not sekrety.klucz("apify"):
        wynik.update(stan="brak_klucza", tekst="Rolki z Instagrama: wklej klucz Apify (Ustawienia → Konta).")
    elif not u["profile"] and not u["konto_obserwowanych"]:
        wynik.update(stan="brak_profili", tekst="Rolki z Instagrama: wklej @ profile twórczyń.")
    elif not persony:
        wynik.update(stan="brak_person", tekst="Rolki z Instagrama: żadna persona nie ma zdjęć.")
    elif pobrane >= u["dziennie"]:
        wynik.update(stan="gotowe", tekst=f"Rolki z Instagrama: dziś {pobrane} z {u['dziennie']} (gotowe)")
    else:
        wynik.update(stan="czeka", tekst=f"Rolki z Instagrama: dziś {pobrane} z {u['dziennie']}")
    return wynik


# ---------------- przebieg ----------------

def przebieg(slug, log=None, stop=None):
    """Jeden pelny przebieg dla modelki. Zwraca podsumowanie."""
    log = log or _log
    ust = baza.ustawienia_modelki(slug)
    pods = {"modelka": slug, "nowe": 0, "wygenerowane": 0, "zdjecia": 0, "wyslane": 0, "stop": None, "bledy": []}
    STAN["modelka"], STAN["etap"] = slug, "skanuj"

    try:
        sk = fabryka.skanuj(slug, log=log, stop=stop, czekaj_na_kopiowanie=True)
        pods["nowe"] = len(sk["nowe"])
    except fabryka.Przerwano:
        raise
    except Exception as e:
        pods["bledy"].append(f"skanuj: {e}")
        log(f"skanuj nie wyszlo: {e}")

    ap = baza.autopilot_stan(slug)
    STAN["etap"] = "generuj"
    if baza.pomysly_w_toku(slug):
        # job wyslany przed restartem/timeoutem: dokonczyc (0 kr, ten sam job) - takze w pauzie i po limicie rolek
        try:
            w = fabryka.wznow_w_toku(slug, log=log, stop=stop, lipsync=False)
            pods["wygenerowane"] += w["wygenerowane"]
            pods["bledy"] += [f"#{i}" for i in w.get("bledy", [])]
        except fabryka.Przerwano:
            raise
        except Exception as e:
            pods["bledy"].append(f"wznow: {e}")
            log(f"wznowienie nie wyszlo: {e}")
    if baza.zdjecia_w_toku(slug):
        # zdjecia z podmiana postaci (strona Zdjecia), ktorych job juz poszedl - dokonczyc (0 kr, ten sam job)
        try:
            import zdjecia_swap
            w = zdjecia_swap.wznow_w_toku(slug, log=log, stop=stop)
            pods["zdjecia"] += w["zrobione"]
        except fabryka.Przerwano:
            raise
        except Exception as e:
            pods["bledy"].append(f"wznow zdjec: {e}")
            log(f"wznowienie zdjec nie wyszlo: {e}")
    max_dzis = int(ust.get("autopilot_max_rolek_dziennie") or 0)
    # rolki w toku tez sie licza; rolki z promptu maja wlasny licznik (Ustawienia -> Autopilot -> Rolki z promptu)
    zrobione_dzis = len([p for p in baza.pomysly_z_dnia(slug) + baza.pomysly_w_toku(slug) if not fabryka.z_promptu(p)])
    zostalo = (max_dzis - zrobione_dzis) if max_dzis else None
    if ap.get("pauza"):
        log(f"{slug}: autopilot w pauzie ({ap['pauza']}) - nie robie rolek, tylko zbieram filmiki")
        pods["stop"] = f"pauza: {ap['pauza']}"
    elif zostalo is not None and zostalo <= 0:
        log(f"{slug}: limit rolek na dzis ({zrobione_dzis}/{max_dzis}) - generacja czeka do jutra")
        pods["stop"] = "max rolek dziennie"
    else:
        try:
            # lipsync=False: autopilot nigdy nie dopasowuje ust (to tylko recznie w panelu -> Lipsync)
            w = fabryka.generuj(slug, potwierdz=None, log=log, stop=stop, max_rolek=zostalo, lipsync=False, wznow=False)
            pods["wygenerowane"] += w["wygenerowane"]
            pods["stop"] = w.get("stop")
            pods["bledy"] += [f"#{i}" for i in w.get("bledy", [])]
            _hamulec(slug, ust, w, log, pods)
        except fabryka.Przerwano:
            raise
        except Exception as e:
            pods["bledy"].append(f"generuj: {e}")
            baza.dziennik_zapisz("blad", f"autopilot generuj: {e}", modelka=slug)
            log(f"generuj nie wyszlo: {e}")

    STAN["etap"] = "podpisy"
    for p in baza.lista_pomyslow(slug, "gotowe"):
        if not p.get("podpis") and (baza.statystyki_tekstow(slug)[0] > 0):
            try:
                fabryka.podpis(slug, p["id"])
            except Exception as e:
                log(f"podpis #{p['id']}: {e}")

    STAN["etap"] = "zdjecia"
    ile_zdjec = int(ust.get("zdjecia_dziennie") or 0)
    if ile_zdjec and ust.get("zdjecia_model") and not ap.get("pauza"):
        # 'niepewne' = job mogl powstac - nie dublujemy; reczne podmiany postaci (swap) nie zjadaja dziennej puli autopilota
        brakuje = ile_zdjec - len(baza.zdjecia_z_dnia(slug, z_niepewnymi=True, bez_swap=True))
        if brakuje > 0:
            try:
                import zdjecia
                w = zdjecia.generuj(slug, ile=brakuje, log=log, stop=stop)
                pods["zdjecia"] += w["zrobione"]
            except fabryka.Przerwano:
                raise
            except Exception as e:
                pods["bledy"].append(f"zdjecia: {e}")
                log(f"zdjecia nie wyszly: {e}")

    STAN["etap"] = "telefon"
    try:
        pods["wyslane"] = wyslij_gotowe(slug, log=log) + wyslij_zdjecia(slug, log=log)
    except Exception as e:
        log(f"telegram: {e}")
    STAN["etap"] = ""
    baza.dziennik_zapisz("info", f"autopilot {slug}: nowe {pods['nowe']}, wygenerowane {pods['wygenerowane']}, "
                         f"zdjecia {pods['zdjecia']}" + (f", na telefon {pods['wyslane']}" if pods["wyslane"] else "")
                         + (f", stop: {pods['stop']}" if pods["stop"] else "")
                         + (f", bledy: {', '.join(pods['bledy'])}" if pods["bledy"] else ""), modelka=slug)
    return pods


def _hamulec(slug, ust, w, log, pods):
    """Liczy nieudane rolki z rzedu; po `autopilot_stop_po_bledach` zatrzymuje persone i alarmuje na telefon.
    Odrzucenia przez filtr tresci (NSFW/IP, takze po zapasie) to nie awaria - nie licza sie do hamulca (kredyty wracaja)."""
    if w.get("wygenerowane"):
        baza.zapisz_autopilot_stan(slug, bledy_z_rzedu=0)
        return
    odrzucone = set(w.get("odrzucone") or [])
    techniczne = [i for i in (w.get("bledy") or []) if i not in odrzucone]
    if odrzucone:
        log(f"{slug}: filtr tresci odrzucil {len(odrzucone)} (NSFW/IP) - to nie awaria, hamulec tego nie liczy")
    if not techniczne:
        return
    n = int(baza.autopilot_stan(slug).get("bledy_z_rzedu") or 0) + len(techniczne)
    baza.zapisz_autopilot_stan(slug, bledy_z_rzedu=n)
    limit = int(ust.get("autopilot_stop_po_bledach") or 0)
    if limit and n >= limit:
        powod = f"{n} rolek z rzedu nie wyszlo"
        baza.autopilot_pauza(slug, powod)
        pods["stop"] = "hamulec"
        baza.dziennik_zapisz("uwaga", f"HAMULEC: autopilot {slug} zatrzymany - {powod}. Sprawdz w panelu i kliknij Wznow.", modelka=slug)
        log(f"HAMULEC: {slug} - {powod}")
        wyslij_na_telefon(f"STOP {slug}: {powod}. Nie robie dalej, zeby nie palic kredytow. Sprawdz w panelu (Rolki) i kliknij Wznow, albo wyslij /wznow.")


def przebieg_wszystkich(tylko=None, log=None, stop=None):
    wyniki = []
    STAN["trwa"] = True
    try:
        STAN["etap"] = "telefon"
        z_telefonu = obsluz_telegram(log)
        if not tylko and not (stop is not None and stop.is_set()):
            # rolki z IG (3.4): pobierz NAJPIERW, zeby skanuj w ponizszym przebiegu od razu je podjal; osobny dzienny licznik
            try:
                STAN["ig"] = krok_rolki_ig(log=log or _log, stop=stop)
            except fabryka.Przerwano:
                raise
            except Exception as e:
                (log or _log)(f"rolki z IG: {e}")
                baza.dziennik_zapisz("blad", f"autopilot rolki z IG: {type(e).__name__}: {e}")
        do_zrobienia = list(modelki_z_autopilotem(tylko))
        # filmik przyslany z telefonu = "zrob to", nawet gdy ta persona nie ma wlaczonego autopilota
        for z in z_telefonu:
            if z.get("typ") == "wideo" and z.get("modelka") and z["modelka"] not in do_zrobienia and (not tylko or tylko == z["modelka"]):
                do_zrobienia.append(z["modelka"])
        for slug in do_zrobienia:
            if stop is not None and stop.is_set():
                break
            wyniki.append(przebieg(slug, log=log, stop=stop))
        if not tylko and not (stop is not None and stop.is_set()):
            # rolki z promptu (3.3): wspolna pula person, osobny licznik dzienny - po rolkach ze swapu
            try:
                STAN["z_promptu"] = krok_z_promptu(log=log or _log, stop=stop)
            except fabryka.Przerwano:
                raise
            except Exception as e:
                (log or _log)(f"rolki z promptu: {e}")
                baza.dziennik_zapisz("blad", f"autopilot rolki z promptu: {type(e).__name__}: {e}")
        try:
            raport_dnia()
        except Exception as e:
            (log or _log)(f"raport dnia: {e}")
        if STAN.get("porzadki_dnia") != datetime.now().strftime("%Y-%m-%d"):
            try:
                porzadki(log)
            except Exception as e:
                (log or _log)(f"porzadki: {e}")
            STAN["porzadki_dnia"] = datetime.now().strftime("%Y-%m-%d")
        STAN["przebiegi"] += 1
        STAN["ostatni"] = time.time()
    finally:
        STAN["trwa"] = False
        STAN["modelka"], STAN["etap"], STAN["opis"] = None, "", ""
    return wyniki


def odstep_sekund(modelki, co_minut=None):
    """Ile czekac do nastepnego przebiegu: min z autopilot_co_minut modelek (albo co_minut); z Telegramem max 60 s."""
    if co_minut:
        odstep = max(1, int(co_minut)) * 60
    elif not modelki:
        odstep = 5 * 60
    else:
        odstep = max(1, min(int(baza.ustawienia_modelki(m).get("autopilot_co_minut") or 15) for m in modelki)) * 60
    if _telegram():
        odstep = min(odstep, ODSTEP_TELEGRAM_S)
    return odstep


def petla(tylko=None, log=None, stop=None, co_minut=None, przebieg_fn=None):
    """Petla bez konca (do stop.set()). `przebieg_fn(log, stop)` pozwala panelowi opakowac przebieg
    (wspolna konsola/blokada z zadaniami recznymi); domyslnie przebieg_wszystkich."""
    log = log or _log
    stop = stop or threading.Event()
    przebieg_fn = przebieg_fn or (lambda log, stop: przebieg_wszystkich(tylko, log=log, stop=stop))
    while not stop.is_set():
        modelki = modelki_z_autopilotem(tylko)
        z_promptu = not tylko and ustawienia_z_promptu()["dziennie"] > 0      # rolki z promptu nie potrzebuja filmikow ani person z autopilot
        u_ig = ustawienia_rolki_ig()
        ig = not tylko and u_ig["wlaczone"] and u_ig["dziennie"] > 0          # pobieranie rolek z IG tez nie potrzebuje person z autopilot
        if not modelki and not _telegram() and not z_promptu and not ig:
            log("zadna modelka nie ma autopilot=true - czekam 5 min")
        else:
            try:
                przebieg_fn(log, stop)
            except fabryka.Przerwano:
                log("zatrzymano")
                break
            except Exception as e:
                log(f"przebieg nie wyszedl: {e}")
                baza.dziennik_zapisz("blad", f"autopilot: {e}")
        odstep = odstep_sekund(modelki, co_minut)
        STAN["nastepny"] = time.time() + odstep
        if stop.wait(odstep):
            break
    STAN["nastepny"] = None


def main(argv=None):
    ap = argparse.ArgumentParser(description="rolki-ai autopilot")
    ap.add_argument("--modelka", "-m")
    ap.add_argument("--raz", action="store_true", help="jeden przebieg i koniec")
    ap.add_argument("--co-minut", type=int)
    args = ap.parse_args(argv)
    if args.raz:
        for w in przebieg_wszystkich(args.modelka):
            print(w)
        return 0
    try:
        baza.przygotuj_foldery_pulpitu_wszystkich()     # Pulpit\ROLKI AI\tu wrzucasz rolki\<persona> itd. (jak panel)
    except Exception as e:
        _log(f"foldery na pulpicie: {e}")
    fabryka.zapisz_diagnoze_w_dzienniku("start autopilota")
    try:
        petla(args.modelka, co_minut=args.co_minut)
    except KeyboardInterrupt:
        print("\n(przerwano)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
