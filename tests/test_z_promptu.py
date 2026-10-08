# -*- coding: utf-8 -*-
"""Rolka z promptu w fabryce i panelu (udawane CLI Higgsfield - zero kredytow): darmowa wycena nic nie tworzy, bezpieczniki,
zamrozony prompt, zawsze Higgsfield (takze gdy persona robi rolki gdzie indziej), nigdy drugi create (wznowienie szuka
joba po prompcie i pomija joby innych pomyslow), cena wyzsza niz zatwierdzona = nic nie idzie, bez zapasu po NSFW,
Media Tool / folder gotowych jak kazda rolka, endpointy /api/z-promptu*."""
import os
import threading

import pytest

import app as panel
import baza
import fabryka
import higgsfield_cli
import scenariusz


@pytest.fixture(autouse=True)
def bez_ffmpeg(monkeypatch):
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 6.0, "szer": 720, "wys": 1280, "fps": 30.0})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    monkeypatch.setattr(fabryka.time, "sleep", lambda s: None)


@pytest.fixture
def slug(modelka):
    baza.zapisz_ustawienia(modelka, mediatool=False)
    baza.zapisz_profil(modelka, wzrost_cm="158-160")
    return modelka


@pytest.fixture
def ceny(cli, monkeypatch):
    """Zapisuje kazde `generate cost` (model, params, media) - wycena jest darmowa i niczego nie tworzy."""
    zapytania = []
    prawdziwy = cli.koszt

    def koszt(model, params=None, media=None):
        zapytania.append((model, dict(params or {}), dict(media or {})))
        return prawdziwy(model, params, media)
    monkeypatch.setattr(higgsfield_cli, "koszt", koszt)
    return zapytania


OPCJE = {"pomysl_id": "galeria_fastfood", "dlugosc": 10, "model": "seedance_2_5", "pora": "popoludnie"}


def test_wycena_darmowa_nic_nie_tworzy(slug, cli, ceny):
    w = fabryka.wycena_z_promptu(slug, OPCJE)
    assert w["kr"] == 45 and w["mozna"] and w["saldo"] == 1000 and w["rozdzielczosc"] == "720p"
    assert cli.generacje == [] and baza.lista_pomyslow(slug) == []
    model, params, media = ceny[0]
    assert model == "seedance_2_5"
    assert params["mode"] == "omni_reference" and params["duration"] == 10 and params["resolution"] == "720p"
    assert params["aspect_ratio"] == "9:16" and params["bitrate_mode"] == "high" and params["generate_audio"] is True
    assert len(media["image"]) == 2 and "video" not in media
    assert "<<<image_1>>>" in params["prompt"] and "<<<image_2>>>" in params["prompt"]
    # bez ceny: sam prompt, zero zapytan do Higgsfield
    n = len(ceny)
    w = fabryka.wycena_z_promptu(slug, OPCJE, z_cena=False)
    assert w["kr"] is None and w["prompt"] and len(ceny) == n
    # 8 s -> 1080p (zasada fabryki)
    assert fabryka.wycena_z_promptu(slug, dict(OPCJE, dlugosc=8))["rozdzielczosc"] == "1080p"
    assert ceny[-1][1]["resolution"] == "1080p" and ceny[-1][1]["duration"] == 8


def test_wycena_bezpieczniki(slug, cli):
    cli.cena = 160
    w = fabryka.wycena_z_promptu(slug, OPCJE)
    assert not w["mozna"] and any("bezpiecznik" in p for p in w["powody"])
    cli.cena, cli.saldo = 70, 250
    w = fabryka.wycena_z_promptu(slug, OPCJE)
    assert not w["mozna"] and any("minimum" in p for p in w["powody"])
    cli.saldo = 5000
    baza.dopisz_wydatek(260, "higgsfield", job_id="inny")
    w = fabryka.wycena_z_promptu(slug, OPCJE)
    assert not w["mozna"] and any("limit" in p for p in w["powody"]) and w["dzis"] == {"wydano": 260, "limit": 300}


def test_pelna_sciezka_zamrozony_prompt_i_gotowy_plik(slug, cli):
    w = fabryka.wycena_z_promptu(slug, OPCJE)
    pid = fabryka.dodaj_z_promptu(slug, dict(OPCJE, ustalone=w["ustalone"]), kr=w["kr"])
    p = baza.pomysl(slug, pid)
    assert p["typ"] == "prompt" and p["status"] == "nowy" and p["prompt_higgsfield"] == w["prompt"] and p["koszt"] == 45
    assert p["z_promptu"]["model"] == "seedance_2_5" and len(p["z_promptu"]["obrazy"]) == 2 and p["zrodlo"] is None
    wynik = fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: k <= 45)
    assert wynik["wygenerowane"] == 1 and len(cli.generacje) == 1
    model, params, media = cli.generacje[0]
    assert params["prompt"] == w["prompt"] and params["mode"] == "omni_reference" and "video" not in media
    p = baza.pomysl(slug, pid)
    assert p["status"] == "gotowe" and p["job_id"] == "job1" and p["w_toku"] is None and p["dostawca"] == "higgsfield"
    assert os.path.basename(p["plik_wynikowy"]) == f"{pid:03d}_prompt_galeria_foodcourt.mp4"
    assert os.path.dirname(p["plik_wynikowy"]) == baza.folder_gotowych(slug) and os.path.isfile(p["plik_wynikowy"])
    assert baza.wydano_dzis("higgsfield") == 45
    # drugi raz ta sama rolka nie pojdzie (gotowa)
    with pytest.raises(ValueError):
        fabryka.generuj(slug, ids=[pid])
    assert len(cli.generacje) == 1


def test_zbiorcze_generuj_i_autopilot_nie_ruszaja_rolek_z_promptu(slug, cli):
    pid = fabryka.dodaj_z_promptu(slug, OPCJE, kr=45)
    assert fabryka.generuj(slug)["wygenerowane"] == 0 and cli.generacje == []
    s = fabryka.stan_modelki(slug)
    assert pid not in s["do_generacji"] and s["z_promptu_czeka"] == [pid]
    assert fabryka.kandydaci(slug) == []
    assert [p["id"] for p in fabryka.kandydaci(slug, ids=[pid])] == [pid]


def test_persona_na_innym_dostawcy_rolka_z_promptu_idzie_przez_higgsfield(slug, cli):
    baza.zapisz_ustawienia(slug, dostawca="wavespeed", mode="video_edit", mode_bez_zrodla="")
    pid = fabryka.dodaj_z_promptu(slug, OPCJE, kr=45)
    k = fabryka.koszt(slug, ids=[pid])
    assert k["pozycje"] == [(pid, 45, "higgsfield")]
    wynik = fabryka.generuj(slug, ids=[pid])
    assert wynik["wygenerowane"] == 1 and len(cli.generacje) == 1          # zero zapytan do WaveSpeed (brak limitu by stopowal)
    assert baza.pomysl(slug, pid)["dostawca"] == "higgsfield"


def test_cena_wyzsza_niz_zatwierdzona_nic_nie_wysyla(slug, cli):
    pid = fabryka.dodaj_z_promptu(slug, OPCJE, kr=40)
    wynik = fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: k <= 40)
    assert wynik["pominiete"] == [pid] and cli.generacje == []
    assert baza.pomysl(slug, pid)["status"] == "nowy"


def test_przerwane_wysylanie_znajduje_swoj_job_i_pomija_cudze(slug, cli, monkeypatch):
    """Dwie rolki z tym samym promptem. Druga: create dotarl do Higgsfielda, ale CLI zwrocilo blad -> fabryka NIE wysyla
    drugi raz, szuka joba po prompcie na `generate list` i pomija job pierwszej rolki (znany fabryce)."""
    w = fabryka.wycena_z_promptu(slug, OPCJE)
    opcje = dict(OPCJE, ustalone=w["ustalone"])
    a = fabryka.dodaj_z_promptu(slug, opcje, kr=45)
    b = fabryka.dodaj_z_promptu(slug, opcje, kr=45)
    assert baza.pomysl(slug, a)["prompt_higgsfield"] == baza.pomysl(slug, b)["prompt_higgsfield"]
    assert fabryka.generuj(slug, ids=[a])["wygenerowane"] == 1
    prawdziwe = cli.generuj

    def generuj_z_bledem(model, params=None, media=None, wait=True, **k):
        prawdziwe(model, params, media, wait=wait)            # job POWSTAL na serwerze...
        raise higgsfield_cli.HiggsfieldBlad("socket hang up")  # ...ale odpowiedz nie dotarla
    monkeypatch.setattr(higgsfield_cli, "generuj", generuj_z_bledem)
    wynik = fabryka.generuj(slug, ids=[b])
    assert len(cli.generacje) == 2 and wynik["wygenerowane"] == 1
    pa, pb = baza.pomysl(slug, a), baza.pomysl(slug, b)
    assert pa["job_id"] == "job1" and pb["job_id"] == "job2" and pb["status"] == "gotowe"


def test_przerwane_wysylanie_bez_joba_czeka_i_nie_wysyla_drugi_raz(slug, cli, monkeypatch):
    pid = fabryka.dodaj_z_promptu(slug, OPCJE, kr=45)

    def padl(*a, **k):
        cli.generacje.append(a)
        raise higgsfield_cli.HiggsfieldBlad("timeout po wyslaniu")
    monkeypatch.setattr(higgsfield_cli, "generuj", padl)
    wynik = fabryka.generuj(slug, ids=[pid])
    assert wynik["w_toku"] == [pid] and len(cli.generacje) == 1
    p = baza.pomysl(slug, pid)
    assert p["status"] == "w_toku" and p["w_toku"]["wysylam"] is True and not p["w_toku"].get("job_id")
    # kolejne przebiegi (restart panelu) tylko szukaja - zero nowych create
    fabryka.wznow_w_toku(slug)
    fabryka.generuj(slug, ids=None)
    assert len(cli.generacje) == 1 and baza.pomysl(slug, pid)["status"] == "w_toku"


def test_nsfw_bez_zapasu_i_bez_powtorki(slug, cli):
    baza.zapisz_ustawienia(slug, zapas_nsfw=[{"dostawca": "yapper", "model": "wan-3.0-prime"}])
    baza.zapisz_limit_dzienny(500, "yapper")
    pid = fabryka.dodaj_z_promptu(slug, OPCJE, kr=45)
    cli.wyniki = [{"status": "nsfw"}]
    wynik = fabryka.generuj(slug, ids=[pid])
    p = baza.pomysl(slug, pid)
    assert p["status"] == "blad" and p["powod"] == "nsfw" and "nie idzie na zapas" in p["notatki"]
    assert len(cli.generacje) == 1 and wynik["odrzucone"] == [pid]
    assert fabryka._krok_startowy(p, baza.ustawienia_modelki(slug)) == 0


def test_brak_zdjec_przy_generacji_to_blad_bez_wysylania(slug, cli):
    pid = fabryka.dodaj_z_promptu(slug, OPCJE, kr=45)
    for o in baza.pomysl(slug, pid)["z_promptu"]["obrazy"]:
        os.remove(o)
    wynik = fabryka.generuj(slug, ids=[pid])
    assert wynik["bledy"] == [pid] and cli.generacje == [] and baza.pomysl(slug, pid)["status"] == "blad"


def test_reczna_poprawka_promptu_sprawdzana(slug, cli):
    with pytest.raises(ValueError):
        fabryka.dodaj_z_promptu(slug, OPCJE, prompt="zly prompt <<<image_9>>>", kr=45)
    pid = fabryka.dodaj_z_promptu(slug, OPCJE, prompt="Moj prompt <<<image_1>>> i <<<image_2>>>.", kr=45)
    p = baza.pomysl(slug, pid)
    assert p["prompt_higgsfield"] == "Moj prompt <<<image_1>>> i <<<image_2>>>." and p["z_promptu"]["prompt_reczny"] is True


def test_cli_z_promptu_sucho(slug, cli, capsys):
    assert fabryka.main(["--modelka", slug, "z-promptu", "--gotowy", "dworzec", "--dlugosc", "8", "--sucho"]) == 0
    out = capsys.readouterr().out
    assert "cena: 45 kr" in out and "--sucho" in out and "1080p" in out
    assert cli.generacje == [] and baza.lista_pomyslow(slug) == []


# ---------------- panel ----------------

@pytest.fixture
def klient(slug, cli):
    panel._saldo.clear()
    panel.konsola.__init__()
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        yield c


def _czekaj():
    w = panel.konsola.watek
    if w:
        w.join(10)
    assert not panel.konsola.stan["trwa"]


def test_api_katalog(klient, slug):
    d = klient.get("/api/z-promptu").get_json()
    assert d["ok"] and len(d["miejsca"]) >= 40 and d["persona"]["slug"] == slug and d["persona"]["wzrost_cm"] == "158-160"
    # 3.5.2: + gotowy wariant Seedance 480p 10 s zaraz za Seedance
    assert [m["id"] for m in d["modele"]] == ["seedance_2_5", "seedance_2_5_480p", "wan3_0_prime", "gemini_omni_flash_1_1"]
    assert d["domyslne"]["model"] == "seedance_2_5"
    assert ["miku", "Turkusowe długie kucyki z grzywką (jak Miku)"] in d["wlosy"]["kolory"]
    assert klient.get("/api/z-promptu?slug=nie_ma").status_code == 404


def test_api_losuj_i_wycena(klient, slug, cli):
    d = klient.post("/api/z-promptu/losuj", json={"bez": "dworzec"}).get_json()
    assert d["ok"] and d["pomysl"]["id"] != "dworzec" and d["pomysl"]["miejsce"] in scenariusz.MIEJSCA
    d = klient.post("/api/z-promptu/wycena", json=OPCJE).get_json()
    assert d["ok"] and d["kr"] == 45 and d["mozna"] and d["obrazy"] == ["01_twarz.png", "02_sylwetka.jpg"]
    assert d["slug"] == slug and baza.lista_pomyslow(slug) == [] and cli.generacje == []
    d2 = klient.post("/api/z-promptu/wycena", json=dict(OPCJE, ustalone=d["ustalone"], bez_ceny=True)).get_json()
    assert d2["prompt"] == d["prompt"] and d2["kr"] is None
    r = klient.post("/api/z-promptu/wycena", json=dict(OPCJE, model="gemini_omni_flash_1_1", dlugosc=15))
    assert r.status_code == 400 and "15 s" in r.get_json()["blad"]


def test_api_zrob_rolke(klient, slug, cli):
    r = klient.post("/api/z-promptu", json=OPCJE)
    assert r.status_code == 400 and "cene" in r.get_json()["blad"] and baza.lista_pomyslow(slug) == []
    w = klient.post("/api/z-promptu/wycena", json=OPCJE).get_json()
    d = klient.post("/api/z-promptu", json=dict(OPCJE, ustalone=w["ustalone"], kr=w["kr"])).get_json()
    assert d["ok"] and d["zadanie"]["typ"] == "generuj"
    _czekaj()
    p = baza.pomysl(slug, d["id"])
    assert p["status"] == "gotowe" and p["prompt_higgsfield"] == w["prompt"] and len(cli.generacje) == 1
    lista = klient.get("/api/pomysly").get_json()["pomysly"]
    karta = [x for x in lista if x["id"] == d["id"]][0]
    assert karta["wariant"] == "prompt" and "Galeria handlowa" in karta["z_promptu_opis"] and karta["wideo_url"]


def test_api_zrob_cena_wzrosla_nic_nie_idzie(klient, slug, cli):
    w = klient.post("/api/z-promptu/wycena", json=OPCJE).get_json()
    cli.cena = 90
    d = klient.post("/api/z-promptu", json=dict(OPCJE, ustalone=w["ustalone"], kr=45)).get_json()
    _czekaj()
    assert cli.generacje == [] and baza.pomysl(slug, d["id"])["status"] == "nowy"
    assert panel.konsola.stan["wynik"]["pominiete"] == [d["id"]]
    assert any("cena wzrosla" in linia for linia in panel.konsola.log)


def test_api_zrob_gdy_cos_trwa_409_bez_tworzenia(klient, slug, cli):
    panel.konsola._start("skanuj", slug)
    try:
        r = klient.post("/api/z-promptu", json=dict(OPCJE, kr=45))
        assert r.status_code == 409 and baza.lista_pomyslow(slug) == []
    finally:
        panel.konsola._koniec()


def test_api_akcja_generuj_max_kr(klient, slug, cli):
    pid = fabryka.dodaj_z_promptu(slug, OPCJE, kr=45)
    cli.cena = 60
    assert klient.post("/api/akcja", json={"typ": "generuj", "ids": [pid], "max_kr": 45}).get_json()["ok"]
    _czekaj()
    assert cli.generacje == [] and panel.konsola.stan["wynik"]["pominiete"] == [pid]


def test_api_profil_wzrost_i_wlosy(klient, slug):
    d = klient.post("/api/profil", json={"wzrost_cm": "170 – 172 cm", "wlosy": "long black hair"}).get_json()
    assert d["ok"] and d["profil"]["wzrost_cm"] == "170-172" and d["profil"]["wlosy"] == "long black hair"
    r = klient.post("/api/profil", json={"wzrost_cm": "wysoka"})
    assert r.status_code == 400
    assert baza.profil_modelki(slug)["wzrost_cm"] == "170-172"


def test_api_ponow_rolki_z_promptu_bez_zapasu(klient, slug, cli):
    baza.zapisz_ustawienia(slug, zapas_nsfw=[{"dostawca": "yapper", "model": "wan-3.0-prime"}])
    pid = fabryka.dodaj_z_promptu(slug, OPCJE, kr=45)
    baza.aktualizuj_pomysl(slug, pid, status="blad", powod="nsfw")
    d = klient.post(f"/api/pomysly/{pid}/ponow").get_json()
    assert d["ok"] and d["od_zapasu"] is False and baza.pomysl(slug, pid)["status"] == "nowy"
