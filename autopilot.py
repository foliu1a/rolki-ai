# -*- coding: utf-8 -*-
"""Autopilot: w petli, dla kazdej modelki z `autopilot: true`:

    skanuj wrzutnie -> generuj (bezpiecznik kredytow + max rolek dziennie) -> Media Tool -> lipsync (jesli jest glos)
    -> zdjecia (zdjecia_dziennie) -> podpisy z banku tekstow

Uzycie:  python autopilot.py            petla (co `autopilot_co_minut` z ustawien; Ctrl+C konczy)
         python autopilot.py --raz      jeden przebieg i koniec (np. z Harmonogramu zadan Windows)
         python autopilot.py --modelka noemi --raz
Panel (app.py) odpala to samo w watku - przycisk Autopilot ON/OFF.
Nic nie robi, gdy modelka nie ma referencji/promptu - tylko loguje do dziennika.
"""
import argparse
import sys
import threading
import time

import baza
import fabryka

if sys.platform == "win32":
    sys.stdout.reconfigure(errors="replace")

STAN = {"trwa": False, "ostatni": None, "nastepny": None, "modelka": None, "etap": "", "przebiegi": 0}


def _log(msg):
    print(time.strftime("%H:%M:%S"), "[autopilot]", msg, flush=True)


def modelki_z_autopilotem(tylko=None):
    if tylko:
        return [tylko]
    return [m for m in baza.lista_modelek() if baza.ustawienia_modelki(m).get("autopilot")]


def przebieg(slug, log=None, stop=None):
    """Jeden pelny przebieg dla modelki. Zwraca podsumowanie."""
    log = log or _log
    ust = baza.ustawienia_modelki(slug)
    pods = {"modelka": slug, "nowe": 0, "wygenerowane": 0, "zdjecia": 0, "stop": None, "bledy": []}
    STAN["modelka"], STAN["etap"] = slug, "skanuj"

    try:
        sk = fabryka.skanuj(slug, log=log, stop=stop, czekaj_na_kopiowanie=True)
        pods["nowe"] = len(sk["nowe"])
    except fabryka.Przerwano:
        raise
    except Exception as e:
        pods["bledy"].append(f"skanuj: {e}")
        log(f"skanuj nie wyszlo: {e}")

    STAN["etap"] = "generuj"
    max_dzis = int(ust.get("autopilot_max_rolek_dziennie") or 0)
    zrobione_dzis = len(baza.pomysly_z_dnia(slug))
    zostalo = (max_dzis - zrobione_dzis) if max_dzis else None
    if zostalo is not None and zostalo <= 0:
        log(f"{slug}: limit rolek na dzis ({zrobione_dzis}/{max_dzis}) - generacja czeka do jutra")
        pods["stop"] = "max rolek dziennie"
    else:
        try:
            w = fabryka.generuj(slug, potwierdz=None, log=log, stop=stop, max_rolek=zostalo)
            pods["wygenerowane"] = w["wygenerowane"]
            pods["stop"] = w.get("stop")
            pods["bledy"] += [f"#{i}" for i in w.get("bledy", [])]
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
    if ile_zdjec and ust.get("zdjecia_model"):
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
    STAN["etap"] = ""
    baza.dziennik_zapisz("info", f"autopilot {slug}: nowe {pods['nowe']}, wygenerowane {pods['wygenerowane']}, "
                         f"zdjecia {pods['zdjecia']}" + (f", stop: {pods['stop']}" if pods["stop"] else "")
                         + (f", bledy: {', '.join(pods['bledy'])}" if pods["bledy"] else ""), modelka=slug)
    return pods


def przebieg_wszystkich(tylko=None, log=None, stop=None):
    wyniki = []
    STAN["trwa"] = True
    try:
        for slug in modelki_z_autopilotem(tylko):
            if stop is not None and stop.is_set():
                break
            wyniki.append(przebieg(slug, log=log, stop=stop))
        STAN["przebiegi"] += 1
        STAN["ostatni"] = time.time()
    finally:
        STAN["trwa"] = False
        STAN["modelka"], STAN["etap"] = None, ""
    return wyniki


def odstep_sekund(modelki, co_minut=None):
    """Ile czekac do nastepnego przebiegu: min z autopilot_co_minut modelek (albo co_minut)."""
    if co_minut:
        return max(1, int(co_minut)) * 60
    if not modelki:
        return 5 * 60
    return max(1, min(int(baza.ustawienia_modelki(m).get("autopilot_co_minut") or 15) for m in modelki)) * 60


def petla(tylko=None, log=None, stop=None, co_minut=None, przebieg_fn=None):
    """Petla bez konca (do stop.set()). `przebieg_fn(log, stop)` pozwala panelowi opakowac przebieg
    (wspolna konsola/blokada z zadaniami recznymi); domyslnie przebieg_wszystkich."""
    log = log or _log
    stop = stop or threading.Event()
    przebieg_fn = przebieg_fn or (lambda log, stop: przebieg_wszystkich(tylko, log=log, stop=stop))
    while not stop.is_set():
        modelki = modelki_z_autopilotem(tylko)
        if not modelki:
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
        petla(args.modelka, co_minut=args.co_minut)
    except KeyboardInterrupt:
        print("\n(przerwano)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
