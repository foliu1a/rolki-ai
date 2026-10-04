# -*- coding: utf-8 -*-
"""Poprawki po niezaleznym przegladzie (2026-10-04) - po jednym tescie regresji na punkt. Scenariusze A-E przegladu
(udawane CLI) z poprawnym, bezpiecznym oczekiwaniem: Higgsfield NIGDY nie dostaje drugiego `generate create` dla tej samej
proby, okno wysylania liczy sie od wyslania, limit dnia liczy rolki w toku."""
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone

import pytest

import autopilot
import baza
import fabryka
import higgsfield_cli
import sekrety
from test_dostawcy import MODEL_WAN, SCHEMAT_WAN, Y, _bilety, _dry, udawany_http  # noqa: F401 - fixtura


@pytest.fixture(autouse=True)
def bez_ffmpeg(monkeypatch):
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 6.0, "szer": 720, "wys": 1280, "fps": 30.0})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    monkeypatch.setattr(fabryka, "_plik_sie_zmienia", lambda p, odstep=0: False)
    monkeypatch.setattr(fabryka.time, "sleep", lambda s: None)


@pytest.fixture
def slug(modelka):
    baza.zapisz_ustawienia(modelka, mediatool=False)
    return modelka


def _wrzuc(slug, nazwa="a.mp4"):
    p = os.path.join(baza.folder_zrodel(slug), nazwa)
    open(p, "wb").write(b"mp4")
    return p


def _create_potem_blad(cli, monkeypatch, blad="request failed (no response received)"):
    """CLI tworzy job na serwerze, a potem konczy sie bledem - tylko przy pierwszym wywolaniu."""
    prawdziwe = cli.generuj
    n = {"i": 0}

    def generuj(m, p=None, media=None, wait=True, **k):
        n["i"] += 1
        wynik = prawdziwe(m, p, media, wait=wait)
        if n["i"] == 1:
            raise higgsfield_cli.HiggsfieldBlad(blad)
        return wynik
    monkeypatch.setattr(higgsfield_cli, "generuj", generuj)


# ---------------- 1. Higgsfield: po 'wysylam' nigdy drugie wysylanie ----------------

def test_A_job_na_liscie_od_razu(slug, cli, monkeypatch):
    _wrzuc(slug)
    fabryka.skanuj(slug)
    _create_potem_blad(cli, monkeypatch)
    w = fabryka.generuj(slug)
    assert len(cli.generacje) == 1 and w["wygenerowane"] == 1 and baza.wydano_dzis() == 45


def test_B_lista_spozniona_ponad_20s_jeden_job(slug, cli, monkeypatch):
    """Przeglad: job pojawia sie na `generate list` dopiero przy 3. zapytaniu (> ~20 s) - kiedys szedl drugi, platny job."""
    _wrzuc(slug)
    fabryka.skanuj(slug)
    _create_potem_blad(cli, monkeypatch)
    prawdziwe_joby = cli.joby
    n = {"i": 0}

    def joby(typ=None, ile=20):
        n["i"] += 1
        return [] if n["i"] <= 2 else prawdziwe_joby(typ, ile)
    monkeypatch.setattr(higgsfield_cli, "joby", joby)
    w = fabryka.generuj(slug)
    assert len(cli.generacje) == 1 and w["w_toku"] == [1]
    assert baza.pomysl(slug, 1)["status"] == "w_toku"
    w = fabryka.generuj(slug)                                  # nastepny przebieg: job juz widac -> TEN job
    assert len(cli.generacje) == 1 and w["wygenerowane"] == 1
    assert baza.pomysl(slug, 1)["job_id"] == "job1" and baza.wydano_dzis() == 45


def test_C_create_bez_id_ale_job_jest(slug, cli, monkeypatch):
    _wrzuc(slug)
    fabryka.skanuj(slug)
    prawdziwe = cli.generuj
    monkeypatch.setattr(higgsfield_cli, "generuj", lambda m, p=None, media=None, wait=True, **k:
                        {"job_ids": [prawdziwe(m, p, media, wait=wait)["id"]]})
    w = fabryka.generuj(slug)
    assert len(cli.generacje) == 1 and w["wygenerowane"] == 1


def test_blad_trwaly_po_wyslaniu_bez_czekania(slug, cli, monkeypatch):
    """Serwer odrzucil zlecenie (brak kredytow / walidacja) - job nie powstal: bez czekania 60 min i bez powtorek."""
    _wrzuc(slug)
    fabryka.skanuj(slug)
    cli.wyniki = [higgsfield_cli.HiggsfieldBlad("Error: insufficient credits")]
    w = fabryka.generuj(slug)
    p = baza.pomysl(slug, 1)
    assert len(cli.generacje) == 1 and w["bledy"] == [1] and p["status"] == "blad" and p["w_toku"] is None


# ---------------- 2. okno od wyslania, wszystko wgrane przed 'wysylam', dopasowanie po filmiku bez czasu ----------------

def test_D_okno_od_wyslania_nie_od_startu_proby(slug, cli):
    """Upload trwal 200 s, create poszedl przed chwila, proces padl przed zapisem job_id: rolka NIE wraca od razu do
    kolejki (kiedys okno 180 s liczylo sie od startu proby -> natychmiastowe drugie wysylanie)."""
    _wrzuc(slug)
    fabryka.skanuj(slug)
    od = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
    baza.zacznij_w_toku(slug, 1, dostawca="higgsfield", model="seedance_2_5", krok=0, klucz="k", koszt=45, od=od)
    baza.ustaw_w_toku(slug, 1, wysylam=True, wideo_id="uuid-a.mp4", wysylam_od=datetime.now(timezone.utc).isoformat())
    w = fabryka.wznow_w_toku(slug)
    assert w["w_toku"] == [1] and baza.pomysl(slug, 1)["status"] == "w_toku" and cli.generacje == []


def test_wszystkie_pliki_wgrane_przed_wysylam(slug, cli, monkeypatch):
    """Filmik i zdjecia bez UUID w cache sa wgrywane PRZED znacznikiem 'wysylam'; create dostaje same UUID-y."""
    _wrzuc(slug)
    fabryka.skanuj(slug)
    zdarzenia = []
    prawdziwy_upload, prawdziwe_ustaw = cli.upload, baza.ustaw_w_toku
    monkeypatch.setattr(higgsfield_cli, "upload", lambda plik: (zdarzenia.append(("upload", os.path.basename(plik))),
                                                               prawdziwy_upload(plik))[1])
    monkeypatch.setattr(baza, "ustaw_w_toku", lambda s, pid, **pola: (zdarzenia.append(("znacznik", sorted(pola))),
                                                                       prawdziwe_ustaw(s, pid, **pola))[1])
    assert fabryka.generuj(slug)["wygenerowane"] == 1
    i_wysylam = next(i for i, z in enumerate(zdarzenia) if z[0] == "znacznik" and "wysylam" in z[1])
    wgrane = [z[1] for z in zdarzenia[:i_wysylam] if z[0] == "upload"]
    assert sorted(wgrane) == ["01_twarz.png", "02_sylwetka.jpg", "a.mp4"]
    assert not [z for z in zdarzenia[i_wysylam:] if z[0] == "upload"]
    _, _, media = cli.generacje[0]
    assert media["video"] == "uuid-a.mp4" and media["image"] == ["uuid-01_twarz.png", "uuid-02_sylwetka.jpg"]
    assert baza.upload_id(slug, baza.sciezki_referencji(slug)[0]) == "uuid-01_twarz.png"     # referencje trafily do cache


def test_znajdz_po_filmiku_bez_filtra_czasu(dane, monkeypatch):
    """Zegar serwera spozniony o godziny: job z tym samym (swiezym) id filmiku i tak jest odnaleziony."""
    from dostawcy import higgsfield as dh
    monkeypatch.setattr(higgsfield_cli, "joby", lambda *a, **k: [
        {"id": "j1", "job_type": "seedance_2_5", "status": "completed", "created_at": "2020-01-01T00:00:00Z",
         "params": {"medias": [{"role": "video", "data": {"id": "uuid-film"}}]}}])
    assert dh.znajdz("seedance_2_5", wideo_id="uuid-film", od=datetime.now(timezone.utc).isoformat())["job_id"] == "j1"
    assert dh.znajdz("seedance_2_5", wideo_id="uuid-inny", od=datetime.now(timezone.utc).isoformat()) is None


# ---------------- 3. limit dnia liczy rolki w toku ----------------

def test_E_limit_dnia_liczy_rolki_w_toku(slug, cli):
    """3 klipy po 45 kr, limit 100/dzien, joby wolniejsze niz czekanie: ida 2 (90 kr zarezerwowane), trzeci czeka do jutra."""
    for n in ("a.mp4", "b.mp4", "c.mp4"):
        _wrzuc(slug, n)
    fabryka.skanuj(slug)
    baza.zapisz_limit_dzienny(100)
    cli.wyniki = [{"status": "in_progress"}] * 3
    w = fabryka.generuj(slug, timeout="0s")
    assert len(cli.generacje) == 2 and w["w_toku"] == [1, 2] and w["stop"] == "limit dzienny"
    assert baza.koszt_w_toku("higgsfield") == 90 and baza.wydano_z_rezerwa("higgsfield") == 90


def test_autopilot_max_rolek_liczy_rolki_w_toku(slug, cli):
    baza.zapisz_ustawienia(slug, autopilot=True, autopilot_max_rolek_dziennie=2)
    for n in ("a.mp4", "b.mp4", "c.mp4"):
        _wrzuc(slug, n)
    cli.wyniki = [{"status": "in_progress"}] * 3
    w = autopilot.przebieg(slug)
    assert len(cli.generacje) == 2 and w["stop"] == "limit rolek w tym przebiegu (2)"
    w = autopilot.przebieg(slug)                       # obie dalej w toku: nic nowego
    assert len(cli.generacje) == 2 and w["stop"] == "max rolek dziennie"


def test_zapas_yappera_liczy_procesy_w_toku(modelka, cli, udawany_http):
    """Inna rolka ma proces yappera w toku (450 kr zarezerwowane) - zapas za 250 przebilby limit 500 -> pominiety."""
    slug = modelka
    sekrety.zapisz_klucz("yapper", "yk")
    baza.zapisz_ustawienia(slug, mediatool=False, zapas_nsfw=[{"dostawca": "yapper", "model": "wan-3.0"}])
    baza.zapisz_prompt(slug, "wan.txt", "Replace the woman with the woman from the reference photos.")
    baza.zapisz_limit_dzienny(500, "yapper")
    inny = baza.dodaj_pomysl(slug, "inna", "p", zrodlo=_wrzuc(slug, "inna.mp4"), info_zrodla={"czas": 6.0})
    baza.zacznij_w_toku(slug, inny, dostawca="yapper", model="wan-3.0", krok=1, klucz="k", koszt=450)
    baza.ustaw_w_toku(slug, inny, job_id="proc_x", etap="czeka")
    udawany_http.ustaw("GET", Y + "/processes/proc_x", {"id": "proc_x", "status": "processing"})
    udawany_http.ustaw("GET", Y + "/credits", {"availableCredits": 7000})
    udawany_http.ustaw("GET", Y + "/models", [MODEL_WAN])
    udawany_http.ustaw("GET", Y + "/models/wan-3.0/schema.json", SCHEMAT_WAN)
    _bilety(udawany_http, "i1", "i2", "v1")
    udawany_http.ustaw("POST", Y + "/processes", _dry(250))
    _wrzuc(slug, "a.mp4")
    fabryka.skanuj(slug)
    cli.wyniki = [{"id": "hf1", "status": "nsfw"}]
    fabryka.generuj(slug, timeout="0s")
    p = baza.pomysl(slug, 2)
    assert p["status"] == "blad" and p["proby"][-1]["powod"] == "limit"
    assert not [w for w in udawany_http.posty(Y + "/processes") if not w[2].get("dryRun")]


# ---------------- 4. eskalacja i wyjscie dla rolki, ktora utknela ----------------

def test_job_trwa_ponad_24h_blad_z_rezerwa(slug, cli):
    """Job z numerem, ktory po 24 h dalej 'trwa' -> blad z prosba o sprawdzenie w apce, wycena wliczona raz, nic nie wyslane."""
    _wrzuc(slug)
    fabryka.skanuj(slug)
    stare = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    baza.zacznij_w_toku(slug, 1, dostawca="higgsfield", model="seedance_2_5", krok=0, klucz="k", koszt=45, od=stare)
    baza.ustaw_w_toku(slug, 1, job_id="jobZ", etap="czeka")
    cli.serwer["jobZ"] = {"id": "jobZ", "status": "in_progress"}
    w = fabryka.wznow_w_toku(slug)
    p = baza.pomysl(slug, 1)
    assert w["bledy"] == [1] and p["status"] == "blad" and "Sprawdz w apce" in p["notatki"] and p["koszt"] == 45
    assert baza.wydano_dzis() == 45 and cli.generacje == []
    fabryka.wznow_w_toku(slug)
    assert baza.wydano_dzis() == 45

def test_eskalacja_24h_gdy_lista_jobow_nie_odpowiada(slug, cli, monkeypatch):
    _wrzuc(slug)
    fabryka.skanuj(slug)
    stare = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    baza.zacznij_w_toku(slug, 1, dostawca="higgsfield", model="seedance_2_5", krok=0, klucz="k", koszt=45, od=stare)
    baza.ustaw_w_toku(slug, 1, wysylam=True, wideo_id="uuid-a.mp4", wysylam_od=stare)
    monkeypatch.setattr(higgsfield_cli, "joby", lambda *a, **k: (_ for _ in ()).throw(higgsfield_cli.HiggsfieldBlad("offline")))
    w = fabryka.wznow_w_toku(slug)
    p = baza.pomysl(slug, 1)
    assert w["bledy"] == [1] and p["status"] == "blad" and "Sprawdz w apce Higgsfield" in p["notatki"]
    assert cli.generacje == []


def test_api_przestan_czekac(slug, cli):
    import app as panel
    panel.konsola.__init__()
    panel.app.config["TESTING"] = True
    _wrzuc(slug)
    fabryka.skanuj(slug)
    baza.zacznij_w_toku(slug, 1, dostawca="higgsfield", model="seedance_2_5", krok=0, klucz="k", koszt=45)
    baza.ustaw_w_toku(slug, 1, wysylam=True, wideo_id="uuid-a.mp4")
    with panel.app.test_client() as c:
        r = c.delete("/api/pomysly/1?wymus=1")                       # zadnej ukrytej furtki
        assert r.status_code == 409 and "Przestan czekac" in r.get_json()["blad"]
        assert c.post("/api/pomysly/1/przerwij", json={}).status_code == 400          # bez potwierdzenia nic
        d = c.post("/api/pomysly/1/przerwij", json={"potwierdzam": True}).get_json()
        assert d["ok"] and d["pomysl"]["status"] == "blad" and "Sprawdz w apce" in d["pomysl"]["notatki"]
        assert c.post("/api/pomysly/1/przerwij", json={"potwierdzam": True}).status_code == 400
        assert c.post("/api/pomysly/1/ponow").get_json()["pomysl"]["status"] == "nowy"
        assert c.delete("/api/pomysly/1").status_code == 200
    assert cli.generacje == []


# ---------------- 5. zapas nie dla rolek ze strojem ze zdjecia ----------------

def test_wariant_b_bez_zapasu(modelka, cli, udawany_http):
    slug = modelka
    sekrety.zapisz_klucz("yapper", "yk")
    baza.zapisz_ustawienia(slug, mediatool=False, zapas_nsfw=[{"dostawca": "yapper", "model": "wan-3.0-prime"}])
    baza.zapisz_limit_dzienny(500, "yapper")
    _wrzuc(slug, "klip.mp4")
    _wrzuc(slug, "klip.stroj.png")
    fabryka.skanuj(slug)
    assert baza.pomysl(slug, 1)["stroj"]
    cli.wyniki = [{"id": "hf1", "status": "nsfw"}]
    w = fabryka.generuj(slug)
    p = baza.pomysl(slug, 1)
    assert udawany_http.wywolania == [] and w["odrzucone"] == [1]
    assert p["status"] == "blad" and "wariant B" in p["notatki"]
    import app as panel
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        d = c.post("/api/pomysly/1/ponow").get_json()
        assert d["od_zapasu"] is False and d["pomysl"].get("krok_startowy") is None


# ---------------- 6. zdjecia i lipsync Higgsfield ----------------

def test_zdjecie_niepewne_nie_robi_drugiego(slug, cli, monkeypatch):
    import zdjecia
    baza.zapisz_ustawienia(slug, zdjecia_model="nano_banana_2", zdjecia_dziennie=1, autopilot=True)
    baza.zapisz_prompt(slug, "zdjecia.txt", "portret\nkawa\nplaza\n")
    cli.cena = 10
    cli.wyniki = [higgsfield_cli.HiggsfieldBlad("Error: timed out waiting for job 11111111-2222-3333-4444-555555555555")]
    w = zdjecia.generuj(slug, ile=3)
    z = baza.lista_zdjec(slug)
    assert w["zrobione"] == 0 and w["stop"] == "niepewne" and len(cli.generacje) == 1 and len(z) == 1
    assert z[0]["status"] == "niepewne" and z[0]["job_id"] == "11111111-2222-3333-4444-555555555555"
    assert baza.wydano_dzis() == 10                                   # koszt zarezerwowany w limicie
    assert len(baza.zdjecia_z_dnia(slug, z_niepewnymi=True)) == 1 and baza.zdjecia_z_dnia(slug) == []
    autopilot.przebieg(slug)                                          # autopilot: dzis "zrobione" - nic nowego
    assert len(cli.generacje) == 1
    # odrzucenie filtra (kredyty wracaja) - mozna isc dalej, kolejny prompt
    baza.zapisz_ustawienia(slug, autopilot=False)
    cli.wyniki = [higgsfield_cli.HiggsfieldBlad("Error: job x ended with status \"nsfw\"")]
    w = zdjecia.generuj(slug, ile=2)
    assert w["zrobione"] == 1 and len(cli.generacje) == 3


def test_lipsync_higgsfield_koszt_z_wyceny_i_limit(slug, cli, monkeypatch):
    import lipsync
    baza.zapisz_ustawienia(slug, lipsync_dostawca="higgsfield", lipsync_model="lip_hf", lipsync_glos_styl="brak")
    wideo = os.path.join(baza.folder_gotowych(slug), "001_a.mp4"); open(wideo, "wb").write(b"v")
    audio = os.path.join(baza.folder_audio(slug), "g.mp3"); open(audio, "wb").write(b"a")
    cli.cena = 20
    prawdziwe = cli.generuj
    monkeypatch.setattr(higgsfield_cli, "generuj", lambda *a, **k: (setattr(cli, "saldo", cli.saldo - 300), prawdziwe(*a, **k))[1])
    lipsync.zrob(slug, wideo, audio)
    assert baza.lista_lipsync(slug)[-1]["koszt"] == 20 and baza.wydano_dzis() == 20     # nie 320 z roznicy salda
    baza.zapisz_limit_dzienny(30)
    with pytest.raises(ValueError, match="limit dzienny"):
        lipsync.zrob(slug, wideo, audio)


# ---------------- 7. blokada zapisu JSON ----------------

def test_blokada_zapisu_watki(slug):
    pid = baza.dodaj_pomysl(slug, "x", "p")
    watki = [threading.Thread(target=baza.zapisz_probe, args=(slug, pid, {"job_id": f"j{i}", "status": "x"})) for i in range(20)]
    for t in watki:
        t.start()
    for t in watki:
        t.join(10)
    assert sorted(w["job_id"] for w in baza.pomysl(slug, pid)["proby"]) == sorted(f"j{i}" for i in range(20))


def test_blokada_zapisu_miedzy_procesami(slug):
    """Drugi proces trzyma blokade pomysly.json i zapisuje - zapis panelu czeka i nie gubi jego zmiany."""
    pid = baza.dodaj_pomysl(slug, "x", "p")
    korzen = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    kod = ("import sys, os, time; sys.path.insert(0, r'%s'); os.environ['ROLKI_MODELKI'] = r'%s'; import baza\n"
           "with baza._rmw(baza._plik_pomyslow('%s')):\n"
           "    print('MAM', flush=True); time.sleep(1.5); baza.aktualizuj_pomysl('%s', %d, notatki='z procesu')\n"
           % (korzen, baza.KATALOG_MODELEK, slug, slug, pid))
    proc = subprocess.Popen([sys.executable, "-c", kod], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "MAM"
        baza.aktualizuj_pomysl(slug, pid, opis="z panelu")
    finally:
        proc.wait(20)
    p = baza.pomysl(slug, pid)
    assert p["notatki"] == "z procesu" and p["opis"] == "z panelu"


# ---------------- 8. drobne ----------------

def test_bledy_trwale_i_powod():
    from dostawcy import yapper
    assert fabryka._blad_trwaly(yapper.BladYappera("yapper 402 insufficient_credits: brak", status=402, kod="insufficient_credits"))
    assert fabryka._blad_trwaly(yapper.BladYappera("yapper 400 invalid_request: zle pole", status=400, kod="invalid_request"))
    assert fabryka._blad_trwaly(fabryka.dostawcy.BladDostawcy("Error: insufficient credits"))
    assert fabryka._blad_trwaly(fabryka.dostawcy.BladDostawcy("validation failed: duration"))
    assert not fabryka._blad_trwaly(fabryka.dostawcy.BladDostawcy("request failed (no response received)"))
    assert not fabryka._blad_trwaly(yapper.BladYappera("yapper 503: upstream", status=503))
    assert fabryka.powod_odrzucenia("failed", "Your plan is not eligible for this model") == "inny"     # plan, nie IP
    assert fabryka.powod_odrzucenia("ip_detected") == "ip"


def test_okno_wysylania_trwa_do_zapisu_job_id(slug, cli, monkeypatch):
    _wrzuc(slug)
    fabryka.skanuj(slug)
    widziane = []
    prawdziwe = baza.ustaw_w_toku

    def ustaw(s, pid, **pola):
        if pola.get("job_id"):
            widziane.append(fabryka.trwa_wysylanie())
        return prawdziwe(s, pid, **pola)
    monkeypatch.setattr(baza, "ustaw_w_toku", ustaw)
    fabryka.generuj(slug)
    assert widziane == [True] and fabryka.trwa_wysylanie() is False


def test_wan_szkice_zasady():
    """Szkice prompt Wan (dane usera, poza gitem) - gdy sa: <= 5000 znakow, bez @[Image], stroj zawsze z filmu."""
    import re
    katalog = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modelki")
    pliki = [os.path.join(katalog, s, "prompty", "wan.txt") for s in ("noemi", "alicja", "bianka")]
    pliki = [p for p in pliki if os.path.isfile(p)]
    if not pliki:
        pytest.skip("brak danych person (np. kopia w chmurze)")
    for p in pliki:
        t = open(p, encoding="utf-8").read()
        assert len(t.strip()) <= 5000 and not re.search(r"@\[Image|@Image", t)
        assert "Never use the reference photos as a source for clothing" in t
