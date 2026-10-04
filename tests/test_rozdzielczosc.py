# -*- coding: utf-8 -*-
"""Zasada usera (2026-10-04): klip <= 8 s -> 1080p, dluzszy -> 720p - dla Higgsfield (Seedance 2.5) i yapper (Wan 3.0).
Liczy sie dlugosc (pocietego) klipu w chwili generacji; rozdzielczosc trafia do wyceny, bezpiecznika, zapytania i do pomyslu."""
import os

import pytest

import baza
import fabryka
import higgsfield_cli
import sekrety
from dostawcy import yapper
from test_dostawcy import MODEL_WAN, SCHEMAT_WAN, Y, udawany_http  # noqa: F401 - fixtura

PRZYPADKI = [(7.9, "1080p"), (8.0, "1080p"), (8.1, "720p"), (14.9, "720p"), (29.5, "720p")]


@pytest.mark.parametrize("czas,oczekiwane", PRZYPADKI)
def test_zasada(czas, oczekiwane):
    assert fabryka.rozdzielczosc_dla_czasu(czas) == oczekiwane
    p = {"zrodlo": "/x.mp4", "info_zrodla": {"czas": czas}}
    assert fabryka.rozdzielczosc_rolki(p, {"resolution": "480p"}) == oczekiwane       # ustawienie persony nie gra roli


def test_bez_filmiku_ustawienie_persony():
    assert fabryka.rozdzielczosc_rolki({"zrodlo": None}, {"resolution": "480p"}) == "480p"
    assert fabryka.rozdzielczosc_rolki({"zrodlo": "/x.mp4", "info_zrodla": {}}, {"resolution": "1080p"}) == "1080p"
    assert fabryka.rozdzielczosc_rolki({"zrodlo": None}, {}) == "720p"


@pytest.fixture
def slug(modelka, monkeypatch):
    baza.zapisz_ustawienia(modelka, mediatool=False, resolution="720p")
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    return modelka


def _rolki(slug, monkeypatch, czasy):
    """Wrzuca klipy o podanych dlugosciach i skanuje (max_sekund_rolki 30 - bez ciecia)."""
    baza.zapisz_ustawienia(slug, max_sekund_rolki=30)
    dl = {}
    for i, czas in enumerate(czasy, 1):
        p = os.path.join(baza.folder_zrodel(slug), f"k{i}.mp4")
        open(p, "wb").write(b"v")
        dl[os.path.normcase(p)] = czas
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": dl.get(os.path.normcase(p), 5.0), "szer": 720, "wys": 1280, "fps": 30})
    fabryka.skanuj(slug)


def test_higgsfield_wycena_zapytanie_i_pomysl(slug, cli, monkeypatch):
    """Seedance: rozdzielczosc z dlugosci klipu w `generate cost` i `generate create`, zapisana w pomysle."""
    czasy = [c for c, _ in PRZYPADKI]
    _rolki(slug, monkeypatch, czasy)
    wyceny = []
    monkeypatch.setattr(higgsfield_cli, "koszt", lambda m, params=None, media=None: wyceny.append(params["resolution"]) or 45)
    baza.zapisz_limit_dzienny(0)
    w = fabryka.generuj(slug)
    assert w["wygenerowane"] == len(PRZYPADKI)
    oczekiwane = [r for _, r in PRZYPADKI]
    assert wyceny == oczekiwane
    assert [params["resolution"] for _, params, _ in cli.generacje] == oczekiwane
    assert [baza.pomysl(slug, i)["resolution"] for i in range(1, len(PRZYPADKI) + 1)] == oczekiwane


def test_higgsfield_bezpiecznik_liczy_wycene_wybranej_rozdzielczosci(slug, cli, monkeypatch):
    """max_kredyty_na_rolke patrzy na wycene TEJ rozdzielczosci: 1080p (7,9 s) za drogie -> pominiete, 720p (8,1 s) idzie."""
    _rolki(slug, monkeypatch, [7.9, 8.1])
    monkeypatch.setattr(higgsfield_cli, "koszt", lambda m, params=None, media=None: {"1080p": 130, "720p": 70}[params["resolution"]])
    baza.zapisz_ustawienia(slug, max_kredyty_na_rolke=100)
    w = fabryka.generuj(slug)
    assert w["pominiete"] == [1] and w["wygenerowane"] == 1
    assert baza.pomysl(slug, 1)["status"] == "nowy" and baza.pomysl(slug, 1)["resolution"] == "1080p"
    assert [params["resolution"] for _, params, _ in cli.generacje] == ["720p"]
    # koszt (panel "Ile kosztuje?") tez wycenia wybrana rozdzielczosc
    assert fabryka.koszt(slug, ids=[1])["pozycje"] == [(1, 130, "higgsfield")]


def test_ciecie_zostaje_a_kawalki_dostaja_rozdzielczosc_z_dlugosci(slug, cli, monkeypatch):
    """max_sekund_rolki dalej tnie (20 s -> 10 s + 10 s); kawalek 10 s = 720p, a krotka koncowka (6 s) = 1080p."""
    baza.zapisz_ustawienia(slug, max_sekund_rolki=10)
    dlugi = os.path.join(baza.folder_zrodel(slug), "dlugi.mp4")
    open(dlugi, "wb").write(b"v")
    czasy = {os.path.normcase(dlugi): 26.0}

    def potnij(plik, folder, max_s=30, min_s=4):
        os.makedirs(folder, exist_ok=True)
        out = []
        for i, c in enumerate((10.0, 10.0, 6.0), 1):
            p = os.path.join(folder, f"dlugi_cz{i:02d}.mp4")
            open(p, "wb").write(b"v")
            czasy[os.path.normcase(p)] = c
            out.append(p)
        return out
    monkeypatch.setattr(fabryka.klatki, "potnij", potnij)
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": czasy.get(os.path.normcase(p), 5.0), "szer": 720, "wys": 1280, "fps": 30})
    assert fabryka.skanuj(slug)["nowe"] == [1, 2, 3]
    baza.zapisz_limit_dzienny(0)
    fabryka.generuj(slug)
    assert [params["resolution"] for _, params, _ in cli.generacje] == ["720p", "720p", "1080p"]


@pytest.mark.parametrize("czas,oczekiwane", PRZYPADKI)
def test_yapper_wan_rozdzielczosc_z_dlugosci(modelka, udawany_http, czas, oczekiwane):
    sekrety.zapisz_klucz("yapper", "yk")
    baza.zapisz_ustawienia(modelka, dostawca="yapper", resolution="480p", yapper={"model": "wan-3.0", "resolution": "480p"})
    baza.zapisz_prompt(modelka, "wan.txt", "Replace the woman with the woman from the reference photos.")
    udawany_http.ustaw("GET", Y + "/models", [MODEL_WAN])
    udawany_http.ustaw("GET", Y + "/models/wan-3.0/schema.json", SCHEMAT_WAN)
    p = {"id": 1, "prompt_higgsfield": "A", "zrodlo": os.path.join(baza.folder_zrodel(modelka), "k.mp4"), "info_zrodla": {"czas": czas}}
    z = fabryka.zlecenie(modelka, p)
    assert z["resolution"] == oczekiwane
    if czas <= 15:
        assert yapper._cialo(z, uploady=False)["input"]["resolution"] == int(oczekiwane[:-1])


def test_panel_pokazuje_zasade(slug, cli, monkeypatch):
    import app as panel
    panel._saldo.clear()
    panel.app.config["TESTING"] = True
    _rolki(slug, monkeypatch, [6.0, 12.0])
    with panel.app.test_client() as c:
        s = c.get("/api/stan").get_json()
        assert s["jakosc"]["zasada_rozdzielczosci"] == "≤8 s → 1080p, dłuższe → 720p"
        assert [p["resolution"] for p in c.get("/api/pomysly").get_json()["pomysly"]] == ["1080p", "720p"]
        html = c.get("/").data.decode("utf-8")
        assert "≤8 s → 1080p" in html
