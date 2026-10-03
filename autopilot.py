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
import fabryka

if sys.platform == "win32":
    sys.stdout.reconfigure(errors="replace")

STAN = {"trwa": False, "ostatni": None, "nastepny": None, "modelka": None, "etap": "", "przebiegi": 0,
        "telegram_wiadomosci": 0}
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
        linie.append(f"{slug}: czeka {st.get('nowy', 0)}, gotowe {st.get('gotowe', 0)}, nie wyszlo {st.get('blad', 0)}; "
                     f"dzis {len(baza.pomysly_z_dnia(slug))} rolek, {baza.wydano_dzis(d)}/{baza.limit_dzienny(d) or '-'} kr"
                     + (" | AUTOPILOT: " + ("PAUZA - " + ap["pauza"] if ap.get("pauza") else ("wlaczony" if ust.get("autopilot") else "wylaczony"))))
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
        linie.append(f"- {slug}: {len(rolki)} rolek, {len(baza.zdjecia_z_dnia(slug))} zdjec, {baza.wydano_dzis(d)} kr ({d})")
    bledy = [w for w in baza.dziennik_ostatnie(500, typ="blad") if str(w.get("czas", "")).startswith(dzis)]
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


def _swiezy(p, godzin=24):
    """Rolka wygenerowana w ciagu ostatnich `godzin` (zeby po sparowaniu nie wysylac calej historii)."""
    try:
        t = datetime.fromisoformat(p.get("wygenerowano") or "")
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
    do_wyslania = [p for p in baza.lista_pomyslow(slug)
                   if p["status"] in ("gotowe", "wygenerowany") and not p.get("telegram_wyslano") and _swiezy(p)]
    if not do_wyslania:
        return 0
    cid = czat_persony(tg, slug, ust, log)
    if not cid:
        return 0
    ile = 0
    for p in do_wyslania:
        plik = p.get("lipsync_plik") if p.get("lipsync_plik") and os.path.isfile(p["lipsync_plik"]) else p.get("plik_wynikowy")
        if not plik or not os.path.isfile(plik):
            continue
        podpis = (p.get("podpis") or "").strip()
        tekst = f"{slug} · rolka #{p['id']} · {os.path.basename(plik)}" + (f"\n\n{podpis}" if podpis else "")
        try:
            tg.wyslij_wideo(plik, tekst, chat_id=cid)
            baza.aktualizuj_pomysl(slug, p["id"], telegram_wyslano=True)
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
            tg.wyslij_zdjecie(z["plik"], f"{slug} · zdjecie #{z['id']}" + (" · strój" if z.get("stroj") else "") + f"\n{z.get('prompt') or ''}".rstrip(),
                              chat_id=cid)
            import zdjecia as _zdj
            _zdj._ustaw(slug, z["id"], telegram_wyslano=True)
            ile += 1
        except Exception as e:
            log(f"telegram: nie wyslalem zdjecia #{z['id']}: {e}")
            break
    return ile


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
    max_dzis = int(ust.get("autopilot_max_rolek_dziennie") or 0)
    zrobione_dzis = len(baza.pomysly_z_dnia(slug))
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
            w = fabryka.generuj(slug, potwierdz=None, log=log, stop=stop, max_rolek=zostalo, lipsync=False)
            pods["wygenerowane"] = w["wygenerowane"]
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
        brakuje = ile_zdjec - len(baza.zdjecia_z_dnia(slug))
        if brakuje > 0:
            try:
                import zdjecia
                w = zdjecia.generuj(slug, ile=brakuje, log=log, stop=stop)
                pods["zdjecia"] = w["zrobione"]
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
    """Liczy nieudane rolki z rzedu; po `autopilot_stop_po_bledach` zatrzymuje persone i alarmuje na telefon."""
    if w.get("wygenerowane"):
        baza.zapisz_autopilot_stan(slug, bledy_z_rzedu=0)
        return
    if not w.get("bledy"):
        return
    n = int(baza.autopilot_stan(slug).get("bledy_z_rzedu") or 0) + len(w["bledy"])
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
        do_zrobienia = list(modelki_z_autopilotem(tylko))
        # filmik przyslany z telefonu = "zrob to", nawet gdy ta persona nie ma wlaczonego autopilota
        for z in z_telefonu:
            if z.get("typ") == "wideo" and z.get("modelka") and z["modelka"] not in do_zrobienia and (not tylko or tylko == z["modelka"]):
                do_zrobienia.append(z["modelka"])
        for slug in do_zrobienia:
            if stop is not None and stop.is_set():
                break
            wyniki.append(przebieg(slug, log=log, stop=stop))
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
        STAN["modelka"], STAN["etap"] = None, ""
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
        if not modelki and not _telegram():
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
    fabryka.zapisz_diagnoze_w_dzienniku("start autopilota")
    try:
        petla(args.modelka, co_minut=args.co_minut)
    except KeyboardInterrupt:
        print("\n(przerwano)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
