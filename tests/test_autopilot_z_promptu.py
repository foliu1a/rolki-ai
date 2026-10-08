# -*- coding: utf-8 -*-
"""Autopilot rolek z promptu (3.3, udawane CLI Higgsfield - zero kredytow, bez sieci: asystent na regulach, bez ElevenLabs):
kwota dzienna lacznie dla person, persony na zmiane, godzina startu, max 2 nieudane proby dziennie, bezpieczniki budzetu z jasnym
wpisem, nic przy 0, dzien lokalny, blad po wysylce bez ponownej wysylki, STOP, ta sama sciezka co reczne "Zrob rolke", osobny
licznik od rolek ze swapu, panel (ustawienia + linijka na Starcie)."""
import os
import threading
from datetime import datetime, timedelta, timezone

import pytest

import app as panel
import asystent
import autopilot
import baza
import fabryka
import higgsfield_cli


@pytest.fixture(autouse=True)
def czysto(monkeypatch):
    autopilot._Z_PROMPTU.update(pominiete_do=0.0, powod="", dzien="", wpisy=set())
    autopilot.STAN.update(etap="", modelka=None, opis="", trwa=False)
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 6.0, "szer": 720, "wys": 1280, "fps": 30.0})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    monkeypatch.setattr(fabryka, "_plik_sie_zmienia", lambda p, odstep=0: False)
    yield
    autopilot._Z_PROMPTU.update(pominiete_do=0.0, powod="", dzien="", wpisy=set())
    autopilot.STAN.update(etap="", modelka=None, opis="", trwa=False)


@pytest.fixture
def slug(modelka):
    baza.zapisz_ustawienia(modelka, mediatool=False)
    return modelka


def _wlacz(**pola):
    baza.zapisz_ustawienia_globalne(autopilot_z_promptu=dict(
        {"dziennie": 1, "model": "seedance_2_5", "persony": [], "od_godziny": "10:00"}, **pola))


def _poludnie():
    return datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def _persona(nazwa, zdjecia=True):
    s = baza.utworz_modelke(nazwa)
    baza.zapisz_prompt(s, "stroj_z_filmu.txt", "PROMPT A @[Image 1](image_1) @[Image 2](image_2)")
    if zdjecia:
        for n in ("01_twarz.png", "02_sylwetka.jpg"):
            with open(os.path.join(baza.folder_referencji(s), n), "wb") as f:
                f.write(b"img")
    baza.zapisz_ustawienia(s, mediatool=False)
    return s


def _wpisy(ile=100):
    return [w["tekst"] for w in baza.dziennik_ostatnie(ile)]


# ---------------- podstawy ----------------

def test_zero_dziennie_nic_nie_robi(slug, cli, monkeypatch):
    _wlacz(dziennie=0)
    wyceny = []
    monkeypatch.setattr(higgsfield_cli, "koszt", lambda *a, **k: wyceny.append(a) or 45)
    assert autopilot.krok_z_promptu(teraz=_poludnie())["stan"] == "wylaczone"
    assert cli.generacje == [] and wyceny == [] and baza.lista_pomyslow(slug) == []
    assert autopilot.stan_z_promptu()["tekst"] == "Rolki z promptu: wyłączone (Ustawienia → Autopilot)."


def test_robi_rolke_z_promptu_ta_sama_sciezka_co_reczna(slug, cli, monkeypatch):
    _wlacz()
    wyslane = []
    monkeypatch.setattr(autopilot, "wyslij_gotowe", lambda s, log=None: wyslane.append(s) or 1)
    w = autopilot.krok_z_promptu(teraz=_poludnie())
    assert w["stan"] == "zrobiona" and w["slug"] == slug and wyslane == [slug]          # gotowa -> na Telegram (jesli wlaczony)
    p = baza.pomysl(slug, w["pid"])
    zp = p["z_promptu"]
    assert p["typ"] == "prompt" and p["autopilot_z_promptu"] is True and p["status"] == "gotowe" and p["w_toku"] is None
    assert zp["model"] == "seedance_2_5" and zp["dlugosc"] == 10 and zp["rozdzielczosc"] == "720p"
    assert zp["asystent"]["dlaczego"] and zp["wycena"] == 45 and zp["glos"] == "tts" and zp["komentarz"]
    assert os.path.dirname(p["plik_wynikowy"]) == baza.folder_gotowych(slug)          # "tu rolki zrobione\<Persona>"
    model, params, media = cli.generacje[0]
    assert len(cli.generacje) == 1 and model == "seedance_2_5" and params["mode"] == "omni_reference"
    assert params["duration"] == 10 and params["resolution"] == "720p" and "video" not in media
    assert baza.wydano_dzis("higgsfield") == 45 and p["job_id"] == "job1"
    teksty = _wpisy()
    assert any(t.startswith(f"autopilot z promptu: Noemi #{w['pid']} - ") and "rolka 1 z 1 dzis" in t for t in teksty)
    assert any(t.startswith(f"autopilot z promptu: Noemi #{w['pid']} gotowa") for t in teksty)
    assert autopilot.STAN["opis"].startswith("robię rolkę z promptu: Noemi, ")      # widget Pierdolkomat
    # kwota dzienna: 1 z 1 -> dzis nic wiecej
    assert autopilot.krok_z_promptu(teraz=_poludnie())["stan"] == "gotowe" and len(cli.generacje) == 1
    assert autopilot.stan_z_promptu(wlaczony=True, teraz=_poludnie())["tekst"] == "Rolki z promptu: dziś 1 z 1 (gotowe)"
    assert "Rolki z promptu: dziś 1 z 1" in autopilot._status_tekst()                # /status z telefonu
    assert "autopilot" in [x for x in panel._pomysl_dla_panelu(p)["z_promptu_opis"].split(" · ")]


def test_nie_wczesniej_niz_o_godzinie(slug, cli):
    _wlacz(od_godziny="10:00")
    rano = _poludnie().replace(hour=9, minute=59)
    assert autopilot.krok_z_promptu(teraz=rano)["stan"] == "przed_godzina"
    assert cli.generacje == [] and baza.lista_pomyslow(slug) == []
    assert autopilot.stan_z_promptu(wlaczony=True, teraz=rano)["tekst"] == "Rolki z promptu: dziś 0 z 1 (następna po 10:00)"
    assert autopilot.krok_z_promptu(teraz=rano.replace(hour=10, minute=0))["stan"] == "zrobiona"


def test_model_wan_tanszy(slug, cli):
    _wlacz(model="wan3_0_prime")
    w = autopilot.krok_z_promptu(teraz=_poludnie())
    assert w["stan"] == "zrobiona" and cli.generacje[0][0] == "wan3_0_prime"
    zp = baza.pomysl(slug, w["pid"])["z_promptu"]
    assert zp["model"] == "wan3_0_prime" and zp["rozdzielczosc"] == "720p" and zp["dlugosc"] == 10


def test_model_seedance_480p_tanszy(slug, cli):
    # 3.5.2: "Seedance 2.5 · 480p · 10 s" = ten sam model Seedance, tylko 480p (twarz pewna, taniej, mniej ostre)
    _wlacz(model="seedance_2_5_480p")
    assert autopilot.ustawienia_z_promptu()["model"] == "seedance_2_5_480p"
    w = autopilot.krok_z_promptu(teraz=_poludnie())
    (m, par, _med), = cli.generacje
    assert w["stan"] == "zrobiona" and m == "seedance_2_5" and par["resolution"] == "480p" and par["duration"] == 10
    zp = baza.pomysl(slug, w["pid"])["z_promptu"]
    assert zp["model"] == "seedance_2_5" and zp["rozdzielczosc"] == "480p" and zp["dlugosc"] == 10
    assert autopilot.stan_z_promptu()["model_nazwa"].startswith("Seedance 2.5 · 480p · 10 s")


# ---------------- kwota, rotacja, pauza ----------------

def test_kwota_dzienna_lacznie_i_persony_na_zmiane(slug, cli):
    alicja, bianka = _persona("Alicja"), _persona("Bianka")
    _persona("Celina", zdjecia=False)                    # bez zdjec - pomijana
    _wlacz(dziennie=3)
    assert [autopilot.krok_z_promptu(teraz=_poludnie())["slug"] for _ in range(3)] == [alicja, bianka, slug]
    assert autopilot.krok_z_promptu(teraz=_poludnie())["stan"] == "gotowe" and len(cli.generacje) == 3   # 3 lacznie, nie na persone
    # wybrane persony: tylko one, w tej kolejnosci, dalej od ostatniej (Noemi)
    _wlacz(dziennie=5, persony=[slug, alicja])
    assert [autopilot.krok_z_promptu(teraz=_poludnie())["slug"] for _ in range(2)] == [alicja, slug]
    assert autopilot.krok_z_promptu(teraz=_poludnie())["stan"] == "gotowe" and len(cli.generacje) == 5


def test_persona_w_pauzie_pomijana(slug, cli):
    alicja = _persona("Alicja")
    _wlacz(dziennie=2)
    baza.autopilot_pauza(alicja, "zatrzymane z telefonu (/stop)")
    assert autopilot.krok_z_promptu(teraz=_poludnie())["slug"] == slug
    baza.autopilot_pauza(slug, "hamulec")
    assert autopilot.krok_z_promptu(teraz=_poludnie())["stan"] == "brak_person" and len(cli.generacje) == 1
    assert any("wszystkie persony sa w pauzie" in t for t in _wpisy())


# ---------------- pieniadze i bledy ----------------

def test_dwie_nieudane_proby_dziennie_i_koniec(slug, cli):
    _wlacz(dziennie=1)
    cli.wyniki = [{"status": "nsfw"}, {"status": "nsfw"}]
    w1 = autopilot.krok_z_promptu(teraz=_poludnie())
    w2 = autopilot.krok_z_promptu(teraz=_poludnie())
    assert w1["stan"] == w2["stan"] == "nie_wyszla" and w1["powod"] == "nsfw" and w1["pid"] != w2["pid"]
    assert autopilot.krok_z_promptu(teraz=_poludnie())["stan"] == "limit_prob"
    assert len(cli.generacje) == 2 and len(baza.lista_pomyslow(slug)) == 2 and baza.wydano_dzis("higgsfield") == 0
    teksty = _wpisy()
    assert any("proba 1 z 2 nieudanych dzis" in t for t in teksty) and any("kolejne jutro" in t for t in teksty)
    stroj = baza.pomysl(slug, w1["pid"])["z_promptu"].get("stroj_id")
    if stroj:
        assert stroj in asystent.nauka(slug)["nsfw_stroje"]     # asystent uczy sie z odrzucenia (omija ten stroj)
    assert "2 nie wyszły" in autopilot.stan_z_promptu(wlaczony=True, teraz=_poludnie())["tekst"]


def test_bezpieczniki_budzetu_pomijaja_z_jasnym_wpisem(slug, cli, monkeypatch):
    _wlacz()
    baza.dopisz_wydatek(290, "higgsfield", job_id="rano")    # wspolny limit 300: 290 + 45 > 300
    wyceny = []
    prawdziwy = cli.koszt
    monkeypatch.setattr(higgsfield_cli, "koszt", lambda m, p=None, me=None: wyceny.append(m) or prawdziwy(m, p, me))
    w = autopilot.krok_z_promptu(teraz=_poludnie())
    assert w["stan"] == "pominieta" and "limit" in w["powod"] and cli.generacje == [] and baza.lista_pomyslow(slug) == []
    wpisy = [x for x in baza.dziennik_ostatnie(50) if "rolka z promptu pominieta" in x["tekst"]]
    assert len(wpisy) == 1 and wpisy[0]["typ"] == "uwaga" and "Noemi" in wpisy[0]["tekst"]
    n = len(wyceny)
    assert autopilot.krok_z_promptu(teraz=_poludnie())["stan"] == "pominieta" and len(wyceny) == n    # bez zapytan co przebieg
    assert "pominięta" in autopilot.stan_z_promptu(wlaczony=True, teraz=_poludnie())["tekst"]
    # saldo ponizej minimum (min_kredyty 200)
    autopilot._Z_PROMPTU.update(pominiete_do=0.0)
    baza.zapisz_limit_dzienny(0)
    cli.saldo = 230
    w = autopilot.krok_z_promptu(teraz=_poludnie())
    assert w["stan"] == "pominieta" and "minimum" in w["powod"] and cli.generacje == [] and baza.lista_pomyslow(slug) == []
    assert baza.budzet()["max_kredyty_dziennie"] == 0 and baza.ustawienia_modelki(slug)["min_kredyty"] == 200


def test_blad_po_wysylce_bez_ponownej_wysylki(slug, cli, monkeypatch):
    _wlacz()

    def padl(*a, **k):
        cli.generacje.append(a)
        raise higgsfield_cli.HiggsfieldBlad("timeout po wyslaniu")
    monkeypatch.setattr(higgsfield_cli, "generuj", padl)
    w = autopilot.krok_z_promptu(teraz=_poludnie())
    assert w["stan"] == "w_toku" and len(cli.generacje) == 1
    # kolejne przebiegi tylko szukaja tego joba (0 kr) - nic nowego, nic drugi raz
    assert autopilot.krok_z_promptu(teraz=_poludnie())["stan"] == "w_toku"
    assert len(cli.generacje) == 1 and len(baza.lista_pomyslow(slug)) == 1
    assert "robi się: Noemi" in autopilot.stan_z_promptu(wlaczony=True, teraz=_poludnie())["tekst"]


def test_licznik_liczy_dzien_lokalny_i_tylko_rolki_autopilota(slug, cli):
    _wlacz()
    teraz = datetime.now().astimezone()
    dzis_0030 = teraz.replace(hour=0, minute=30, second=0, microsecond=0)

    def rolka(kiedy, autopilota=True):
        pid = baza.dodaj_pomysl(slug, "x", "p", typ="prompt", z_promptu={"model": "seedance_2_5"},
                                **({"autopilot_z_promptu": True} if autopilota else {}))
        baza.aktualizuj_pomysl(slug, pid, status="gotowe", utworzono=kiedy.astimezone(timezone.utc).isoformat())
        return pid
    rolka(dzis_0030 - timedelta(hours=1))                     # wczoraj 23:30 (lokalnie)
    rolka(dzis_0030, autopilota=False)                        # reczna rolka z promptu - nie liczy sie
    assert autopilot.rolki_z_promptu_z_dnia(teraz.strftime("%Y-%m-%d"))["zrobione"] == []
    pid = rolka(dzis_0030)                                     # dzis 00:30 lokalnie (w UTC to jeszcze wczoraj przy +01/+02)
    assert [p["id"] for _, p in autopilot.rolki_z_promptu_z_dnia(teraz.strftime("%Y-%m-%d"))["zrobione"]] == [pid]
    assert autopilot.krok_z_promptu(teraz=teraz.replace(hour=12, tzinfo=None))["stan"] == "gotowe" and cli.generacje == []


def test_stop_przerywa_a_ta_sama_rolka_rusza_pozniej(slug, cli):
    _wlacz()
    stop = threading.Event()
    stop.set()
    with pytest.raises(fabryka.Przerwano):
        autopilot.krok_z_promptu(teraz=_poludnie(), stop=stop)
    lista = baza.lista_pomyslow(slug)
    assert cli.generacje == [] and len(lista) == 1 and lista[0]["status"] == "nowy"
    # persona w pauzie (/stop z telefonu) - czekajaca rolka tez nie idzie
    baza.autopilot_pauza(slug, "zatrzymane z telefonu (/stop)")
    assert autopilot.krok_z_promptu(teraz=_poludnie())["stan"] == "brak_person" and cli.generacje == []
    baza.autopilot_wznow(slug)
    w = autopilot.krok_z_promptu(teraz=_poludnie())
    assert w["stan"] == "zrobiona" and w["pid"] == lista[0]["id"] and len(baza.lista_pomyslow(slug)) == 1


def test_rolki_z_promptu_nie_zjadaja_limitu_rolek_ze_swapu(slug, cli):
    """autopilot_max_rolek_dziennie liczy tylko rolki z filmikow - rolki z promptu maja osobny licznik."""
    _wlacz()
    assert autopilot.krok_z_promptu(teraz=_poludnie())["stan"] == "zrobiona"
    baza.zapisz_ustawienia(slug, autopilot_max_rolek_dziennie=1)
    with open(os.path.join(baza.folder_zrodel(slug), "klip.mp4"), "wb") as f:
        f.write(b"mp4")
    pods = autopilot.przebieg(slug)
    assert pods["wygenerowane"] == 1 and pods["stop"] != "max rolek dziennie" and len(cli.generacje) == 2


# ---------------- petla autopilota ----------------

def test_przebieg_wszystkich_robi_rolke_bez_person_z_autopilotem(slug, cli):
    _wlacz(od_godziny="00:00")
    assert not baza.ustawienia_modelki(slug)["autopilot"]
    autopilot.przebieg_wszystkich()
    assert autopilot.STAN["z_promptu"]["stan"] == "zrobiona" and len(cli.generacje) == 1
    assert autopilot.STAN["opis"] == "" and autopilot.STAN["etap"] == "" and autopilot.STAN["modelka"] is None
    # przebieg dla jednej persony (--modelka) nie robi rolek z promptu (wspolna pula)
    autopilot.przebieg_wszystkich(tylko=slug)
    assert len(cli.generacje) == 1


def test_petla_kreci_sie_tylko_dla_rolek_z_promptu(slug):
    wywolania = []
    stop = threading.Event()

    def przebieg_fn(log, s):
        wywolania.append(1)
        stop.set()
    _wlacz()
    autopilot.petla(stop=stop, przebieg_fn=przebieg_fn, log=lambda m: None)
    assert wywolania == [1]
    # bez rolek z promptu, bez person z autopilotem i bez telefonu - petla czeka (nic nie odpala)
    _wlacz(dziennie=0)
    stop2 = threading.Event()
    t = threading.Thread(target=autopilot.petla, kwargs={"stop": stop2, "przebieg_fn": przebieg_fn, "log": lambda m: None})
    t.start()
    threading.Event().wait(0.2)
    stop2.set()
    t.join(5)
    assert wywolania == [1]


# ---------------- panel ----------------

@pytest.fixture
def klient(slug, cli):
    panel._saldo.clear()
    panel.konsola.__init__()
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        yield c


def test_api_ustawienia_rolek_z_promptu_i_linijka_na_starcie(klient, slug):
    _wlacz()
    d = klient.get("/api/ustawienia/globalne").get_json()
    assert d["ok"] and [m["id"] for m in d["modele_z_promptu"]] == ["seedance_2_5", "seedance_2_5_480p", "wan3_0_prime"]
    assert d["persony"] == [{"slug": slug, "nazwa": "Noemi", "referencje": 2}]
    for zle in ({"dziennie": -1}, {"dziennie": 99}, {"model": "gemini_omni_flash_1_1"}, {"od_godziny": "25:00"},
                {"persony": ["nie_ma"]}, {"cos": 1}):
        assert klient.post("/api/ustawienia/globalne", json={"autopilot_z_promptu": zle}).status_code == 400, zle
    d = klient.post("/api/ustawienia/globalne", json={"autopilot_z_promptu": {
        "dziennie": 2, "model": "wan3_0_prime", "persony": [slug], "od_godziny": "9:30"}}).get_json()
    assert d["ok"] and d["ustawienia"]["autopilot_z_promptu"] == {"dziennie": 2, "model": "wan3_0_prime", "persony": [slug],
                                                                  "od_godziny": "09:30"}
    s = klient.get("/api/stan").get_json()["autopilot_z_promptu"]
    assert s["dziennie"] == 2 and s["tekst"].startswith("Rolki z promptu: dziś 0 z 2 (")
    assert s["model_nazwa"].startswith("Wan 3.0 Premium")
    assert baza.budzet()["max_kredyty_dziennie"] == 300            # limity budzetu nietkniete


# ---------------- 3.5.1: wybor modelu na Starcie przy przelaczniku + potwierdzenie wlaczenia ----------------

def test_start_wybor_modelu_z_cena_i_zapis_od_razu(klient, slug):
    _wlacz()
    baza.zapisz_ustawienia_globalne(pierwsza_klatka={"wlaczona": True})
    s = klient.get("/api/stan").get_json()["autopilot_z_promptu"]
    assert [(m["id"], m["nazwa"], m["kr"]) for m in s["modele"]] == [("seedance_2_5", "Seedance 2.5 · 720p", 73),
                                                                        ("seedance_2_5_480p", "Seedance 2.5 · 480p", 33),
                                                                        ("wan3_0_prime", "Wan 3.0 Premium", 33)]
    # 3.5.2: opisy - Seedance 720p twarz pewna i najlepsza jakosc, 480p tanio i mniej ostre, Wan twarz ze zdjec + tlo z referencji
    assert "Twarz pewna, najlepsza jakość" in s["modele"][0]["opis"] and "mniej ostre (480p)" in s["modele"][1]["opis"]
    assert "twarz ze zdjęć persony" in s["modele"][2]["opis"] and "tło z referencji" in s["modele"][2]["opis"]
    assert s["kr_rolki"] == 73 and s["limit_dzienny"] == baza.limit_dzienny("higgsfield")
    # chip "Wan 3.0 Premium" na Starcie = ten sam zapis co Ustawienia -> Autopilot; odpowiedz niesie nowy stan dla Startu
    d = klient.post("/api/ustawienia/globalne", json={"autopilot_z_promptu": {"model": "wan3_0_prime"}}).get_json()
    assert d["ustawienia"]["autopilot_z_promptu"]["model"] == "wan3_0_prime" and d["z_promptu"]["kr_rolki"] == 33
    assert d["ustawienia"]["autopilot_z_promptu"]["dziennie"] == 1                 # reszta bez zmian
    # bez pierwszej klatki - sama cena wideo
    baza.zapisz_ustawienia_globalne(pierwsza_klatka={"wlaczona": False})
    s = klient.get("/api/stan").get_json()["autopilot_z_promptu"]
    assert [m["kr"] for m in s["modele"]] == [70, 30, 30] and s["kr_rolki"] == 30


def test_panel_ma_potwierdzenie_wlaczenia_autopilota_bez_confirm():
    folder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(folder, "templates", "index.html"), encoding="utf-8").read()
    js = open(os.path.join(folder, "static", "app.js"), encoding="utf-8").read()
    assert 'id="autopilot-potwierdz"' in html and 'id="autopilot-wybor"' in html
    for kawalek in ("autopilot-potwierdz-wlacz", "autopilot-potwierdz-anuluj", "pokazPotwierdzenieAutopilota",
                    "if (wlacz && !potwierdzone) { pokazPotwierdzenieAutopilota(); return; }", "kosztPotwierdzenia"):
        assert kawalek in js, kawalek
    assert "confirm(" not in js.split("function pokazPotwierdzenieAutopilota")[1].split("function renderWpisy")[0]
