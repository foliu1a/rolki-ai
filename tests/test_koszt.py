# -*- coding: utf-8 -*-
"""Oszczedzanie kredytow: dlugosc rolki (max_sekund_rolki), zestawy 'Jakosc i koszt', szacunek kosztu, 'ile rolek zostalo dzis'."""
import os

import baza
import fabryka
from test_telegram_autopilot import bez_ffmpeg  # noqa: F401 - fixtura


def _wrzuc(slug, nazwa, czas):
    p = os.path.join(baza.folder_zrodel(slug), nazwa)
    open(p, "wb").write(b"v")
    return p


def test_szacunek_kosztu_i_presety():
    # rozdzielczosc wybiera dlugosc: <= 8 s -> 1080p (12 kr/s), dluzej -> 720p (7,5 kr/s) - ustawienie resolution nie gra roli
    assert fabryka.szacunek_kosztu_rolki({"resolution": "720p", "max_sekund_rolki": 15}) == 112
    assert fabryka.szacunek_kosztu_rolki({"resolution": "1080p", "max_sekund_rolki": 10}) == 75
    assert fabryka.szacunek_kosztu_rolki({"resolution": "720p"}, 6) == 72           # zmierzone: 6,04 s 1080p = 73 kr
    assert fabryka.szacunek_kosztu_rolki({"resolution": "1080p", "max_sekund_rolki": 8}) == 96
    assert fabryka.szacunek_kosztu_rolki({"resolution": "dziwne", "max_sekund_rolki": 4}) == 48
    assert fabryka.max_sekund_rolki({"max_sekund_rolki": 99}) == 30 and fabryka.max_sekund_rolki({"max_sekund_rolki": 1}) == 4
    assert fabryka.max_sekund_rolki({"max_sekund_rolki": "zle"}) == 30 and fabryka.max_sekund_rolki({}) == 30
    assert fabryka.preset_jakosci({"resolution": "720p", "max_sekund_rolki": 10}) == "oszczednie"
    assert fabryka.preset_jakosci({"resolution": "1080p", "max_sekund_rolki": 8}) == "najlepiej"
    assert fabryka.preset_jakosci({"resolution": "1080p", "max_sekund_rolki": 15}) == "wlasne"
    assert fabryka.preset_jakosci({"resolution": "480p", "max_sekund_rolki": 15}) == "wlasne"
    assert baza.USTAWIENIA_DOMYSLNE["max_sekund_rolki"] == 15 and fabryka.preset_jakosci(baza.USTAWIENIA_DOMYSLNE) == "normalnie"


def test_jakosc_i_koszt_persony(modelka):
    j = fabryka.jakosc_i_koszt(modelka)
    assert j["preset"] == "normalnie" and j["koszt_rolki"] == 112 and j["za_drogo"] is False and j["max_kredyty_na_rolke"] == 150
    assert j["resolution"] == "720p (≤8 s → 1080p)" and j["zasada_rozdzielczosci"] == "≤8 s → 1080p, dłuższe → 720p"
    assert j["koszt_sekundy_1080p"] == 12.0 and j["koszt_sekundy_720p"] == 7.5 and j["prog_1080p_s"] == 8.0
    assert j["presety"]["oszczednie"]["koszt_rolki"] == 75 and j["presety"]["najlepiej"]["koszt_rolki"] == 96
    assert j["presety"]["najlepiej"]["resolution"] == "1080p"
    fabryka.ustaw_preset_jakosci(modelka, "najlepiej")
    u = baza.ustawienia_modelki(modelka)
    assert u["resolution"] == "1080p" and u["max_sekund_rolki"] == 8
    assert fabryka.jakosc_i_koszt(modelka)["za_drogo"] is False       # 1080p/8 s ~ 96 kr < max_kredyty_na_rolke 150
    baza.zapisz_ustawienia(modelka, max_sekund_rolki=15, max_kredyty_na_rolke=100)
    assert fabryka.jakosc_i_koszt(modelka)["za_drogo"] is True        # 15 s (720p) ~ 112 kr > 100 - panel ostrzega
    baza.zapisz_ustawienia(modelka, max_kredyty_na_rolke=150)
    fabryka.ustaw_preset_jakosci(modelka, "oszczednie")
    assert fabryka.jakosc_i_koszt(modelka)["preset"] == "oszczednie"
    try:
        fabryka.ustaw_preset_jakosci(modelka, "cos")
        assert False, "nieznany zestaw przeszedl"
    except ValueError:
        pass


def test_zmiana_rozdzielczosci_uniewaznia_koszty(modelka):
    import app as panel
    panel.app.config["TESTING"] = True
    a = baza.dodaj_pomysl(modelka, "a", "p"); baza.aktualizuj_pomysl(modelka, a, koszt=45)
    b = baza.dodaj_pomysl(modelka, "b", "p"); baza.aktualizuj_pomysl(modelka, b, koszt=45, status="gotowe")
    fabryka.ustaw_preset_jakosci(modelka, "normalnie")                    # ta sama rozdzielczosc -> koszty zostaja
    assert baza.pomysl(modelka, a)["koszt"] == 45
    fabryka.ustaw_preset_jakosci(modelka, "najlepiej")                    # 1080p -> koszt 'nowy' wyczyszczony, 'gotowe' nie
    assert baza.pomysl(modelka, a)["koszt"] is None and baza.pomysl(modelka, b)["koszt"] == 45
    baza.aktualizuj_pomysl(modelka, a, koszt=72)
    with panel.app.test_client() as c:
        assert c.post("/api/ustawienia", json={"max_sekund_rolki": 12}).status_code == 200
        assert baza.pomysl(modelka, a)["koszt"] == 72
        assert c.post("/api/ustawienia", json={"resolution": "720p"}).status_code == 200
        assert baza.pomysl(modelka, a)["koszt"] is None


def test_zapis_json_atomowy(modelka, monkeypatch):
    """Przerwany zapis nie psuje pliku: stara wersja zostaje, plik tymczasowy znika."""
    plik = baza._plik_pomyslow(modelka)
    baza.dodaj_pomysl(modelka, "a", "p")
    przed = open(plik, encoding="utf-8").read()
    prawdziwy = baza.json.dump

    def padnij(*a, **k):
        raise OSError("dysk pelny")
    monkeypatch.setattr(baza.json, "dump", padnij)
    try:
        baza.dodaj_pomysl(modelka, "b", "p")
        assert False, "zapis mial sie nie udac"
    except OSError:
        pass
    monkeypatch.setattr(baza.json, "dump", prawdziwy)
    assert open(plik, encoding="utf-8").read() == przed
    assert not [n for n in os.listdir(os.path.dirname(plik)) if n.endswith(".tmp")]
    assert len(baza.lista_pomyslow(modelka)) == 1


def test_skanuj_tnie_wg_max_sekund_rolki(modelka, cli, bez_ffmpeg, monkeypatch):
    czasy = {}
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": czasy.get(p, 10.0), "szer": 720, "wys": 1280, "fps": 30.0})
    wywolania = []

    def potnij(plik, folder, max_s=30, min_s=4):
        wywolania.append(max_s)
        os.makedirs(folder, exist_ok=True)
        out = []
        for i in range(1, 3):
            p = os.path.join(folder, f"{os.path.splitext(os.path.basename(plik))[0]}_cz{i:02d}.mp4")
            open(p, "wb").write(b"v")
            out.append(p)
        return out
    monkeypatch.setattr(fabryka.klatki, "potnij", potnij)
    # 20 s przy domyslnych 15 s -> ciete (kiedys: cale, bo limit byl 30)
    czasy[_wrzuc(modelka, "a.mp4", 20)] = 20.0
    assert len(fabryka.skanuj(modelka)["nowe"]) == 2 and wywolania == [15]
    # 12 s przy 15 s -> w calosci
    czasy[_wrzuc(modelka, "b.mp4", 12)] = 12.0
    assert len(fabryka.skanuj(modelka)["nowe"]) == 1 and wywolania == [15]
    # oszczednie (10 s): 12 s -> ciete na 10
    fabryka.ustaw_preset_jakosci(modelka, "oszczednie")
    czasy[_wrzuc(modelka, "c.mp4", 12)] = 12.0
    assert len(fabryka.skanuj(modelka)["nowe"]) == 2 and wywolania == [15, 10]
    # dziel_dlugie wylaczone: nie tnie wcale
    baza.zapisz_ustawienia(modelka, dziel_dlugie=False)
    czasy[_wrzuc(modelka, "d.mp4", 25)] = 25.0
    assert len(fabryka.skanuj(modelka)["nowe"]) == 1 and wywolania == [15, 10]


def test_api_stan_salda_higgsfield_yapper_elevenlabs(modelka, cli, monkeypatch):
    """Pasek u gory: Higgsfield zawsze, yapper i ElevenLabs tylko gdy jest klucz (z jednostka i szczegolami)."""
    import sekrety
    import app as panel
    from dostawcy import elevenlabs, yapper
    panel._saldo.clear(); panel._konta_test.clear()
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        s = c.get("/api/stan?saldo=1").get_json()["saldo"]
        assert set(s) == {"higgsfield"} and s["higgsfield"]["kredyty"] == 1000 and s["higgsfield"]["jednostka"] == "kr"
        sekrety.zapisz_klucz("elevenlabs", "el-1")
        sekrety.zapisz_klucz("yapper", "y-1")
        monkeypatch.setattr(elevenlabs, "saldo_szczegoly", lambda: {"kredyty": 28800, "limit": 30000, "plan": "starter", "jednostka": "zn"})
        monkeypatch.setattr(yapper, "saldo", lambda: 7000)
        panel._saldo.clear()
        s = c.get("/api/stan?saldo=1").get_json()["saldo"]
        assert s["yapper"]["kredyty"] == 7000 and s["yapper"]["jednostka"] == "kr"
        assert s["elevenlabs"] == {"kredyty": 28800, "limit": 30000, "plan": "starter", "jednostka": "zn", "blad": None, "czas": s["elevenlabs"]["czas"]}
        monkeypatch.setattr(elevenlabs, "gotowy", lambda: (True, "klucz dziala"))
        assert c.post("/api/konta/test", json={"dostawca": "elevenlabs"}).get_json()["dziala"] is True
        # bez klucza ElevenLabs znika z paska; zly klucz = blad w saldzie, panel sie nie wywala
        sekrety.zapisz_klucz("elevenlabs", "")
        panel._saldo.clear()
        assert "elevenlabs" not in c.get("/api/stan?saldo=1").get_json()["saldo"]
        sekrety.zapisz_klucz("elevenlabs", "el-2")
        monkeypatch.setattr(elevenlabs, "saldo_szczegoly", lambda: (_ for _ in ()).throw(dostawcy_blad("ElevenLabs 401: zly klucz API")))
        panel._saldo.clear()
        s = c.get("/api/stan?saldo=1").get_json()["saldo"]["elevenlabs"]
        assert s["kredyty"] is None and "401" in s["blad"] and s["jednostka"] == "zn"


def dostawca_blad_klasa():
    import dostawcy
    return dostawcy.BladDostawcy


def dostawcy_blad(tekst):
    return dostawca_blad_klasa()(tekst)


def test_api_jakosc_i_zostalo(modelka, cli, bez_ffmpeg):
    import app as panel
    panel._saldo.clear()
    panel.app.config["TESTING"] = True
    cli.saldo = 1000
    baza.zapisz_limit_dzienny(300)
    with panel.app.test_client() as c:
        d = c.get("/api/stan?saldo=1").get_json()
        assert d["jakosc"]["preset"] == "normalnie" and d["jakosc"]["koszt_rolki"] == 112
        assert d["dzis"]["rolek_zostalo"] == 2          # limit dzienny 300 // 112 = 2 (saldo 1000-200 min -> 7)
        r = c.post("/api/ustawienia/preset", json={"nazwa": "oszczednie"}).get_json()
        assert r["ok"] and r["ustawienia"]["max_sekund_rolki"] == 10 and r["jakosc"]["preset"] == "oszczednie"
        d = c.get("/api/stan").get_json()
        assert d["dzis"]["rolek_zostalo"] == 4          # 300 // 75
        assert c.post("/api/ustawienia/preset", json={"nazwa": "x"}).status_code == 400
        baza.zapisz_limit_dzienny(0)
        cli.saldo = 350
        panel._saldo.clear()
        d = c.get("/api/stan?saldo=1").get_json()
        assert d["dzis"]["rolek_zostalo"] == 2          # bez limitu: (350 - min 200) // 75
