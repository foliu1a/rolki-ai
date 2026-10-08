# -*- coding: utf-8 -*-
"""Zrodlo klipow z Instagrama przez Apify (3.4) - wszystko na mockach, ZERO wywolan na zywo do IG/Apify/OpenRouter:
parsowanie odpowiedzi Apify, dedup, heurystyki, AI filtr (z i bez OpenRouter), krok autopilota (round-robin person,
limit dzienny, 0 = nie pobiera, brak klucza = nie pobiera + jasny log), pobieranie pliku (blad CDN = zrozumialy wyjatek,
bez polpliku), endpointy panelu + konto Apify."""
import os
import urllib.error

import pytest

import app as panel
import autopilot
import baza
import dostawcy
import instagram_rolki
import klatki
import sekrety
from dostawcy import http, instagram


@pytest.fixture(autouse=True)
def czysto():
    autopilot._Z_PROMPTU.update(pominiete_do=0.0, powod="", dzien="", wpisy=set())
    autopilot.STAN.update(etap="", modelka=None, opis="", trwa=False)
    instagram._stan_klucza.clear()
    instagram_rolki._cache_modeli.update(czas=0.0, modele=None)
    yield
    autopilot._Z_PROMPTU.update(pominiete_do=0.0, powod="", dzien="", wpisy=set())


# ---------------- udawany HTTP Apify ----------------

A = "https://api.apify.com/v2"


class ApifyHTTP:
    def __init__(self):
        self.wywolania = []
        self.items = []
        self.uzytkownik = {"data": {"username": "ja", "plan": {"id": "FREE"}}}

    def zapytanie(self, metoda, url, dane=None, naglowki=None, timeout=60, powtorki=3, **k):
        self.wywolania.append((metoda, url, dane, naglowki))
        if url.endswith("/users/me"):
            return self.uzytkownik
        return self.items


@pytest.fixture
def apify(dane, monkeypatch):
    sekrety.zapisz_klucz("apify", "apify_api_tajne123")
    h = ApifyHTTP()
    monkeypatch.setattr(http, "zapytanie", h.zapytanie)
    return h


def _item(shortcode="AAA", autor="ktosik", **pola):
    d = {"type": "Video", "shortCode": shortcode, "url": f"https://www.instagram.com/reel/{shortcode}/",
         "videoUrl": f"https://scontent.cdninstagram.com/{shortcode}.mp4", "ownerUsername": autor,
         "caption": "opis " + shortcode, "videoDuration": 12.3, "likesCount": 321, "timestamp": "2026-10-08T10:00:00.000Z"}
    d.update(pola)
    return d


# ---------------- parsowanie odpowiedzi Apify ----------------

def test_rolki_z_profili_parsuje(apify):
    apify.items = [
        _item("AAA"),
        {"type": "Image", "shortCode": "IMG", "displayUrl": "https://cdn/img.jpg", "ownerUsername": "ktosik"},  # nie wideo
        {"type": "Video", "shortCode": "NOV", "ownerUsername": "ktosik"},   # wideo bez adresu pliku -> pomijamy
        {"error": "not_found", "errorDescription": "profil prywatny"},      # item bledu -> pomijamy
    ]
    rolki = instagram.rolki_z_profili(["@Ktosik", "https://instagram.com/inna/"], na_profil=5)
    assert len(rolki) == 1
    r = rolki[0]
    assert r["shortcode"] == "AAA" and r["autor"] == "ktosik" and r["czas_s"] == 12.3 and r["polubienia"] == 321
    assert r["video_url"].endswith("AAA.mp4") and r["url"].endswith("/reel/AAA/")
    # token idzie w naglowku Bearer, NIGDY w URL; wolanie to POST run-sync-get-dataset-items
    metoda, url, _, naglowki = apify.wywolania[0]
    assert metoda == "POST" and "run-sync-get-dataset-items" in url
    assert "apify_api_tajne123" not in url and naglowki.get("Authorization", "").startswith("Bearer ")


def test_rolki_z_profili_bez_klucza(dane):
    with pytest.raises(dostawcy.BrakKlucza):
        instagram.rolki_z_profili(["ktosik"])


def test_gotowy_i_obserwowani(apify):
    assert instagram.gotowy()[0] is True
    # lista obserwowanych ukryta bez logowania -> jasny komunikat "wklej recznie"
    with pytest.raises(dostawcy.BladDostawcy) as e:
        instagram.obserwowani("@ktosik")
    assert "recznie" in str(e.value)


# ---------------- pobieranie pliku z CDN ----------------

def test_pobierz_cdn_blad_bez_polpliku(dane, monkeypatch):
    def pada(url, sciezka, naglowki=None, timeout=600):
        with open(sciezka, "wb") as f:
            f.write(b"polowa pliku")          # CDN zaczal oddawac, potem padl
        raise urllib.error.URLError("blocked by vpn")
    monkeypatch.setattr(http, "pobierz", pada)
    cel = os.path.join(str(dane), "out", "x.mp4")
    with pytest.raises(dostawcy.BladDostawcy) as e:
        instagram.pobierz("https://scontent.cdninstagram.com/x.mp4", cel)
    assert "CDN IG" in str(e.value) and "Apify" in str(e.value)
    assert not os.path.exists(cel) and not os.path.exists(cel + ".part")      # bez polpliku


def test_pobierz_ok(dane, monkeypatch):
    def daj(url, sciezka, naglowki=None, timeout=600):
        with open(sciezka, "wb") as f:
            f.write(b"\x00\x00mp4dane")
        return sciezka
    monkeypatch.setattr(http, "pobierz", daj)
    cel = os.path.join(str(dane), "out", "x.mp4")
    assert instagram.pobierz("https://cdn/x.mp4", cel) == os.path.abspath(cel)
    assert os.path.isfile(cel) and not os.path.exists(cel + ".part")


# ---------------- heurystyki ----------------

def test_heurystyki_meta():
    assert instagram_rolki.heurystyka_meta({"czas_s": 1}).startswith("za krotka")
    assert instagram_rolki.heurystyka_meta({"czas_s": 120}).startswith("za dluga")
    assert instagram_rolki.heurystyka_meta({"czas_s": 10}) is None
    assert instagram_rolki.heurystyka_meta({"czas_s": None}) is None


def test_heurystyki_ffprobe():
    assert instagram_rolki.filtr_heurystyki({"szer": 720, "wys": 1280, "czas": 10}) == (True, "")
    ok, powod = instagram_rolki.filtr_heurystyki({"szer": 1280, "wys": 720, "czas": 10})   # poziomy
    assert not ok and "pionowy" in powod
    ok, powod = instagram_rolki.filtr_heurystyki({"szer": 720, "wys": 1280, "czas": 1.5})  # za krotki
    assert not ok and "dlugosc" in powod
    ok, powod = instagram_rolki.filtr_heurystyki({"szer": 200, "wys": 360, "czas": 10})    # za mala rozdzielczosc
    assert not ok and "rozdzielczosc" in powod


# ---------------- AI filtr (OpenRouter multimodalny) ----------------

def _fejk_jpg(dane):
    p = os.path.join(str(dane), "arkusz.jpg")
    with open(p, "wb") as f:
        f.write(b"\xff\xd8\xff\xe0jpeg")
    return p


def test_filtr_ai_z_openrouter(dane, monkeypatch):
    sekrety.zapisz_klucz("openrouter", "sk-or-test")
    monkeypatch.setattr(instagram_rolki, "modele_vision", lambda: ["model-a:free"])
    jpg = _fejk_jpg(dane)
    monkeypatch.setattr(instagram_rolki, "_zapytaj_vision", lambda m, d, timeout=30: {"ok": False, "powod": "dwie osoby"})
    w = instagram_rolki.filtr_ai(jpg)
    assert w and w["ok"] is False and "dwie osoby" in w["powod"] and w["zrodlo"].startswith("openrouter:")
    monkeypatch.setattr(instagram_rolki, "_zapytaj_vision", lambda m, d, timeout=30: {"ok": True, "powod": ""})
    assert instagram_rolki.filtr_ai(jpg)["ok"] is True


def test_filtr_ai_bez_openrouter(dane):
    jpg = _fejk_jpg(dane)
    assert instagram_rolki.filtr_ai(jpg) is None            # brak klucza -> decyduja heurystyki


def test_filtr_ai_blad_modelu_to_heurystyki(dane, monkeypatch):
    sekrety.zapisz_klucz("openrouter", "sk-or-test")
    monkeypatch.setattr(instagram_rolki, "modele_vision", lambda: ["m:free"])
    monkeypatch.setattr(instagram_rolki, "_zapytaj_vision",
                        lambda m, d, timeout=30: (_ for _ in ()).throw(RuntimeError("przeciazony")))
    assert instagram_rolki.filtr_ai(_fejk_jpg(dane)) is None


# ---------------- krok autopilota: round-robin, limit, dedup, brak klucza ----------------

def _persona(nazwa):
    s = baza.utworz_modelke(nazwa)
    for n in ("01_twarz.png", "02_sylwetka.jpg"):
        with open(os.path.join(baza.folder_referencji(s), n), "wb") as f:
            f.write(b"img")
    baza.zapisz_ustawienia(s, mediatool=False)
    return s


def _wlacz_ig(**pola):
    baza.zapisz_ustawienia_globalne(autopilot_rolki_ig=dict(
        {"wlaczone": True, "profile": ["ktosik"], "konto_obserwowanych": "", "dziennie": 3,
         "kandydatow_na_profil": 5, "do_person": "round-robin", "pobieranie_przez_apify": False}, **pola))


def _rolki(n):
    return [{"shortcode": f"R{i}", "url": f"https://instagram.com/reel/R{i}/", "video_url": f"https://cdn/R{i}.mp4",
             "autor": "ktosik", "opis": "", "czas_s": 10, "polubienia": 10, "data": f"2026-10-08T0{i}:00:00+00:00"}
            for i in range(n)]


@pytest.fixture
def swap(dane, monkeypatch):
    """Persony noemi+alicja (ze zdjeciami), klucz Apify, udawane pobieranie + ffprobe (pionowy klip), licznik pobran."""
    sekrety.zapisz_klucz("apify", "apify_api_tajne123")
    _persona("Noemi")
    _persona("Alicja")
    licznik = []

    def pobierz(video_url, cel, timeout=120):
        os.makedirs(os.path.dirname(cel), exist_ok=True)
        with open(cel, "wb") as f:
            f.write(b"mp4")
        licznik.append(video_url)
        return cel
    monkeypatch.setattr(instagram, "pobierz", pobierz)
    monkeypatch.setattr(klatki, "info", lambda p: {"czas": 10.0, "szer": 720, "wys": 1280, "fps": 30.0})
    return licznik


def _ile_w_zrodlach(slug):
    folder = baza.folder_zrodel(slug)
    return len([n for n in os.listdir(folder) if n.lower().endswith(".mp4")])


def test_krok_round_robin(swap, monkeypatch):
    _wlacz_ig(dziennie=3)
    monkeypatch.setattr(instagram, "rolki_z_profili", lambda profile, na_profil=5, timeout=300: _rolki(3))
    w = autopilot.krok_rolki_ig()
    assert w["stan"] == "pobrane" and w["nowe"] == 3
    # lista_modelek() sortuje: alicja, noemi -> round-robin: alicja, noemi, alicja
    assert _ile_w_zrodlach("alicja") == 2 and _ile_w_zrodlach("noemi") == 1
    assert len(swap) == 3 and instagram_rolki.pobrane_z_dnia() == 3


def test_krok_limit_dzienny(swap, monkeypatch):
    _wlacz_ig(dziennie=2)
    monkeypatch.setattr(instagram, "rolki_z_profili", lambda profile, na_profil=5, timeout=300: _rolki(3))
    autopilot.krok_rolki_ig()
    assert instagram_rolki.pobrane_z_dnia() == 2 and len(swap) == 2
    # drugi przebieg tego samego dnia: limit wyczerpany -> nic nowego
    w = autopilot.krok_rolki_ig()
    assert w["stan"] == "gotowe" and len(swap) == 2


def test_krok_dedup(swap, monkeypatch):
    _wlacz_ig(dziennie=10)
    monkeypatch.setattr(instagram, "rolki_z_profili", lambda profile, na_profil=5, timeout=300: _rolki(3))
    autopilot.krok_rolki_ig()
    assert len(swap) == 3
    w = autopilot.krok_rolki_ig()        # te same shortcode'y -> juz widziane, nie pobiera drugi raz
    assert w["nowe"] == 0 and w["pominiete"] == 3 and len(swap) == 3


def test_krok_zero_nie_pobiera(swap, monkeypatch):
    _wlacz_ig(dziennie=0)
    monkeypatch.setattr(instagram, "rolki_z_profili", lambda *a, **k: _rolki(3))
    w = autopilot.krok_rolki_ig()
    assert w["stan"] == "wylaczone" and len(swap) == 0


def test_krok_bez_klucza_nie_pobiera(swap, monkeypatch):
    sekrety.zapisz_klucz("apify", "")        # brak klucza
    _wlacz_ig(dziennie=3)
    monkeypatch.setattr(instagram, "rolki_z_profili", lambda *a, **k: _rolki(3))
    w = autopilot.krok_rolki_ig()
    assert w["stan"] == "brak_klucza" and len(swap) == 0
    wpisy = baza.dziennik_ostatnie(50, typ="uwaga")
    assert any("Apify" in x["tekst"] for x in wpisy)        # jasny log


def test_krok_blad_cdn_odrzuca_bez_wywalania(swap, monkeypatch):
    _wlacz_ig(dziennie=3)
    monkeypatch.setattr(instagram, "rolki_z_profili", lambda *a, **k: _rolki(1))
    monkeypatch.setattr(instagram, "pobierz",
                        lambda u, c, timeout=120: (_ for _ in ()).throw(dostawcy.BladDostawcy("CDN IG blokada")))
    w = autopilot.krok_rolki_ig()
    assert w["nowe"] == 0 and w["odrzucone"] == 1
    assert _ile_w_zrodlach("noemi") == 0 and _ile_w_zrodlach("alicja") == 0
    assert instagram_rolki.widziane()["R0"]["akcja"] == "odrzucona"


def test_krok_do_konkretnej_persony(swap, monkeypatch):
    _wlacz_ig(dziennie=3, do_person="noemi")
    monkeypatch.setattr(instagram, "rolki_z_profili", lambda *a, **k: _rolki(3))
    autopilot.krok_rolki_ig()
    assert _ile_w_zrodlach("noemi") == 3 and _ile_w_zrodlach("alicja") == 0


# ---------------- panel: ustawienia globalne + konto Apify ----------------

@pytest.fixture
def klient(dane):
    _persona("Noemi")
    with panel.app.test_client() as c:
        yield c


def test_api_ustawienia_ig(klient):
    d = klient.get("/api/ustawienia/globalne").get_json()
    assert d["ok"] and "rolki_ig" in d and d["ma_klucz_apify"] is False
    for zle in ({"dziennie": -1}, {"dziennie": 999}, {"kandydatow_na_profil": 0}, {"do_person": "nie_ma"}, {"cos": 1}):
        assert klient.post("/api/ustawienia/globalne", json={"autopilot_rolki_ig": zle}).status_code == 400, zle
    d = klient.post("/api/ustawienia/globalne", json={"autopilot_rolki_ig": {
        "wlaczone": True, "profile": "ktosik\n@Inna, trzecia", "dziennie": 2, "do_person": "noemi"}}).get_json()
    ig = d["ustawienia"]["autopilot_rolki_ig"]
    assert d["ok"] and ig["profile"] == ["ktosik", "inna", "trzecia"] and ig["dziennie"] == 2 and ig["do_person"] == "noemi"
    assert baza.budzet()["max_kredyty_dziennie"] == 300        # limity budzetu nietkniete
    s = klient.get("/api/stan").get_json()["rolki_ig"]
    assert "Instagrama" in s["tekst"]


def test_api_konto_apify(klient):
    konta = klient.get("/api/konta").get_json()["konta"]
    assert "apify" in konta and konta["apify"]["jest"] is False and konta["apify"]["typ"] == "klucz"
    d = klient.post("/api/konta", json={"dostawca": "apify", "klucz": "apify_api_xyz"}).get_json()
    assert d["ok"] and d["konta"]["apify"]["jest"] is True
    assert sekrety.klucz("apify") == "apify_api_xyz"
