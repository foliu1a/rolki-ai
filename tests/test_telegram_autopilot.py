# -*- coding: utf-8 -*-
"""Telegram (telefon jako pilot) na udawanym HTTP + hamulec autopilota + podglad wyniku + nowe API panelu."""
import json
import os

import pytest

import autopilot
import baza
import fabryka
import sekrety
from dostawcy import http, telegram


class UdawanyTelegram:
    """Odpowiada jak api.telegram.org: zbiera wyslane wiadomosci/pliki, oddaje zakolejkowane update'y."""

    def __init__(self):
        self.wyslane = []       # (metoda, dane)
        self.pliki = []         # (metoda, pola, pliki)
        self.updates = []
        self.pobrane = []

    def zapytanie(self, metoda, url, dane=None, naglowki=None, timeout=60, surowe_cialo=None, typ_ciala=None, powtorki=3):
        assert "bot123:ABC" in url
        koncowka = url.rsplit("/", 1)[1]
        if koncowka == "getMe":
            return {"ok": True, "result": {"username": "rolki_bot"}}
        if koncowka == "getUpdates":
            od = int(dane.get("offset") or 0)
            return {"ok": True, "result": [u for u in self.updates if u["update_id"] >= od]}
        if koncowka == "getFile":
            return {"ok": True, "result": {"file_path": f"videos/{dane['file_id']}.mp4"}}
        if koncowka == "sendMessage":
            self.wyslane.append((koncowka, dane))
            return {"ok": True, "result": {"message_id": len(self.wyslane)}}
        raise http.BladHTTP(404, json.dumps({"ok": False, "description": "Not Found"}), url)

    def multipart(self, url, pola=None, pliki=None, naglowki=None, timeout=900):
        self.pliki.append((url.rsplit("/", 1)[1], pola, pliki))
        return {"ok": True, "result": {"message_id": 1}}

    def pobierz(self, url, sciezka, naglowki=None, timeout=600):
        os.makedirs(os.path.dirname(sciezka), exist_ok=True)
        with open(sciezka, "wb") as f:
            f.write(b"wideo")
        self.pobrane.append((url, sciezka))
        return sciezka

    def wiadomosc(self, chat_id=777, **msg):
        uid = len(self.updates) + 1
        self.updates.append({"update_id": uid, "message": dict({"chat": {"id": chat_id, "username": "yux"}, "from": {"username": "yux"}}, **msg)})


@pytest.fixture
def tg(dane, monkeypatch):
    u = UdawanyTelegram()
    for n in ("zapytanie", "multipart", "pobierz"):
        monkeypatch.setattr(http, n, getattr(u, n))
    sekrety.zapisz_klucz("telegram", "123:ABC")
    return u


@pytest.fixture
def bez_ffmpeg(monkeypatch):
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 5.0, "szer": 720, "wys": 1280, "fps": 30})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda zrodlo, cel, ile=6: (os.makedirs(os.path.dirname(cel), exist_ok=True), open(cel, "wb").write(b"jpg")))
    monkeypatch.setattr(fabryka, "_plik_sie_zmienia", lambda p, odstep=0: False)


# ---------------- modul telegram ----------------

def test_telegram_bez_tokena(dane):
    assert telegram.skonfigurowany() is False
    assert telegram.gotowy()[0] is False
    assert autopilot.wyslij_na_telefon("x") is False


def test_telegram_parowanie_i_komendy(tg, modelka):
    assert telegram.gotowy() == (True, "bot @rolki_bot dziala - napisz do niego /start na telefonie, zeby sparowac")
    tg.wiadomosc(text="/start")
    tg.wiadomosc(chat_id=999, text="/status")           # obcy czat - ignorowany
    tg.wiadomosc(text="/status")
    zrobione = autopilot.obsluz_telegram()
    assert [z["tekst"] for z in zrobione] == ["/start", "/status"]
    assert telegram.sparowany() and telegram.stan()["chat_id"] == 777 and telegram.stan()["czat"] == "yux"
    assert "Sparowane" in tg.wyslane[0][1]["text"] and tg.wyslane[0][1]["chat_id"] == 777
    assert "noemi: czeka 0" in tg.wyslane[1][1]["text"]
    assert telegram.gotowy()[1].endswith("sparowany z czatem yux")
    # offset: drugi odbior nie powtarza
    assert autopilot.obsluz_telegram() == []
    assert telegram.stan()["offset"] == 4


def test_telegram_filmik_do_wrzutni(tg, modelka):
    baza.utworz_modelke("Alicja")
    tg.wiadomosc(text="/start")
    tg.wiadomosc(video={"file_id": "f1", "file_name": "taniec.mp4", "file_size": 1000}, caption="alicja")
    tg.wiadomosc(video={"file_id": "f2", "file_size": 1000})                     # bez podpisu -> aktywna (noemi)
    tg.wiadomosc(document={"file_id": "f3", "file_name": "duzy.mp4", "file_size": 30 * 1024 * 1024})
    z = autopilot.obsluz_telegram()
    assert z[1]["modelka"] == "alicja" and z[1]["plik"] == os.path.join(baza.folder_zrodel("alicja"), "taniec.mp4")
    assert z[2]["modelka"] == modelka and os.path.basename(z[2]["plik"]).startswith("telefon_") and z[2]["plik"].endswith(".mp4")
    assert z[3]["blad"] == "za duzy"
    assert os.path.isfile(z[1]["plik"]) and tg.pobrane[0][0].endswith("/file/bot123:ABC/videos/f1.mp4")
    assert "Mam: taniec.mp4 -> alicja" in tg.wyslane[1][1]["text"]
    assert "ponad 20 MB" in tg.wyslane[3][1]["text"]
    assert fabryka.nowe_zrodla("alicja") == [z[1]["plik"]]
    # ten sam filmik drugi raz -> nazwa_2
    tg.wiadomosc(video={"file_id": "f4", "file_name": "taniec.mp4", "file_size": 10}, caption="Alicja")
    z = autopilot.obsluz_telegram()
    assert z[0]["plik"].endswith("taniec_2.mp4")


def test_telegram_glos_paruje_z_filmikiem(tg, modelka, bez_ffmpeg):
    zr = baza.folder_zrodel(modelka)
    open(os.path.join(zr, "mowa.mp4"), "wb").write(b"v")
    fabryka.skanuj(modelka)
    tg.wiadomosc(text="/start")
    tg.wiadomosc(audio={"file_id": "a1", "file_name": "glos.mp3"}, caption="mowa")
    tg.wiadomosc(voice={"file_id": "a2"})
    z = autopilot.obsluz_telegram()
    assert z[1]["plik"] == os.path.join(zr, "mowa.audio.mp3")
    assert baza.pomysl(modelka, 1)["audio"] == z[1]["plik"]
    assert os.path.dirname(z[2]["plik"]) == baza.folder_audio(modelka)
    assert "Lipsync" in tg.wyslane[1][1]["text"] and "po zrobieniu rolki dopasuje" not in tg.wyslane[1][1]["text"]   # autopilot nie robi lipsyncu


def test_telegram_stop_wznow(tg, modelka):
    tg.wiadomosc(text="/stop")
    autopilot.obsluz_telegram()
    assert baza.autopilot_stan(modelka)["pauza"].startswith("zatrzymane z telefonu")
    tg.wiadomosc(text="/wznow")
    autopilot.obsluz_telegram()
    assert baza.autopilot_stan(modelka)["pauza"] is None
    tg.wiadomosc(text="cokolwiek")
    autopilot.obsluz_telegram()
    assert "Nie rozumiem" in tg.wyslane[-1][1]["text"]


def test_wyslij_gotowe_i_raport(tg, modelka, cli, bez_ffmpeg):
    baza.zapisz_ustawienia(modelka, mediatool=False)
    tg.wiadomosc(text="/start")
    autopilot.obsluz_telegram()
    open(os.path.join(baza.folder_zrodel(modelka), "a.mp4"), "wb").write(b"v")
    baza.dodaj_teksty(modelka, ["Sunset mood"])
    w = autopilot.przebieg(modelka)
    assert w["wygenerowane"] == 1 and w["wyslane"] == 1
    metoda, pola, pliki = tg.pliki[0]
    assert metoda == "sendVideo" and pliki["video"].endswith("001_a.mp4") and "Sunset mood" in pola["caption"]
    assert baza.pomysl(modelka, 1)["telegram_wyslano"] is True
    assert baza.pomysl(modelka, 1)["klatki_wyniku"].endswith("001_wynik.jpg")
    # drugi przebieg nie wysyla ponownie
    assert autopilot.przebieg(modelka)["wyslane"] == 0 and len(tg.pliki) == 1
    # recznie zrobiony lipsync (pozniej) -> wersja z dopasowanymi ustami leci na telefon raz
    lip = os.path.join(baza.folder_gotowych(modelka), "001_a_lipsync.mp4")
    open(lip, "wb").write(b"l")
    baza.aktualizuj_pomysl(modelka, 1, lipsync_plik=lip)
    assert autopilot.przebieg(modelka)["wyslane"] == 1 and tg.pliki[-1][2]["video"] == lip
    assert "z dopasowanymi ustami" in tg.pliki[-1][1]["caption"] and baza.pomysl(modelka, 1)["telegram_wyslano_lipsync"] is True
    assert autopilot.przebieg(modelka)["wyslane"] == 0 and len(tg.pliki) == 2
    # raport: wymuszony zawsze, automatyczny raz dziennie po godzinie raportu
    tekst = autopilot.raport_dnia(wymus=True)
    assert "noemi: 1 rolek" in tekst and telegram.stan()["ostatni_raport"]
    assert autopilot.raport_dnia() is None


def test_telegram_wysylaj_wylaczone(tg, modelka, cli, bez_ffmpeg):
    baza.zapisz_ustawienia(modelka, mediatool=False, telegram_wysylaj=False)
    tg.wiadomosc(text="/start")
    autopilot.obsluz_telegram()
    open(os.path.join(baza.folder_zrodel(modelka), "a.mp4"), "wb").write(b"v")
    assert autopilot.przebieg(modelka)["wyslane"] == 0 and tg.pliki == []


def test_odstep_z_telegramem(tg, modelka):
    baza.zapisz_ustawienia(modelka, autopilot=True, autopilot_co_minut=15)
    assert autopilot.odstep_sekund([modelka]) == 60
    sekrety.zapisz_klucz("telegram", "")
    assert autopilot.odstep_sekund([modelka]) == 15 * 60


# ---------------- hamulec ----------------

def test_hamulec_zatrzymuje_po_bledach(tg, modelka, cli, bez_ffmpeg, monkeypatch):
    import higgsfield_cli
    baza.zapisz_ustawienia(modelka, mediatool=False, autopilot=True, autopilot_stop_po_bledach=3, powtorki=0)
    tg.wiadomosc(text="/start")
    autopilot.obsluz_telegram()
    monkeypatch.setattr(higgsfield_cli, "generuj", lambda *a, **k: (_ for _ in ()).throw(higgsfield_cli.HiggsfieldBlad("nsfw")))
    for n in ("a.mp4", "b.mp4", "c.mp4", "d.mp4"):
        open(os.path.join(baza.folder_zrodel(modelka), n), "wb").write(b"v")
    w = autopilot.przebieg(modelka)
    assert w["stop"] == "hamulec" and len(w["bledy"]) >= 3
    ap = baza.autopilot_stan(modelka)
    assert ap["pauza"].endswith("rolek z rzedu nie wyszlo") and ap["bledy_z_rzedu"] >= 3
    assert any("STOP noemi" in m[1]["text"] for m in tg.wyslane)
    # w pauzie: skanuje, ale nie generuje
    open(os.path.join(baza.folder_zrodel(modelka), "e.mp4"), "wb").write(b"v")
    ile_generacji = len(cli.generacje)
    w = autopilot.przebieg(modelka)
    assert w["nowe"] == 1 and w["stop"].startswith("pauza") and len(cli.generacje) == ile_generacji
    # wznowienie zeruje licznik
    baza.autopilot_wznow(modelka)
    assert baza.autopilot_stan(modelka) == {"bledy_z_rzedu": 0, "pauza": None, "pauza_od": None}


def test_hamulec_sukces_zeruje_licznik(modelka, cli, bez_ffmpeg):
    baza.zapisz_ustawienia(modelka, mediatool=False)
    baza.zapisz_autopilot_stan(modelka, bledy_z_rzedu=2)
    open(os.path.join(baza.folder_zrodel(modelka), "a.mp4"), "wb").write(b"v")
    autopilot.przebieg(modelka)
    assert baza.autopilot_stan(modelka)["bledy_z_rzedu"] == 0


# ---------------- API panelu ----------------

@pytest.fixture
def klient(modelka, cli, bez_ffmpeg):
    import app as panel
    panel._saldo.clear(); panel._modele_cache.clear(); panel._konta_test.clear()
    panel.konsola.__init__()
    baza.zapisz_ustawienia(modelka, mediatool=False)
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        yield c


def test_api_stan_nowe_pola_i_wznow(klient, modelka, tg):
    baza.autopilot_pauza(modelka, "3 rolek z rzedu nie wyszlo")
    d = klient.get("/api/stan").get_json()
    assert d["autopilot_stan"]["pauza"] == "3 rolek z rzedu nie wyszlo"
    assert d["telegram"] == {"skonfigurowany": True, "sparowany": False, "czat": "", "czaty": []}
    assert d["foldery"]["wrzutnia"] == baza.folder_zrodel(modelka) and d["pulpit"].endswith("ROLKI AI")
    assert d["dzis"]["rolki"] == 0 and d["dzis"]["kredyty"]["higgsfield"] == 0
    d = klient.post("/api/autopilot/wznow", json={}).get_json()
    assert d["ok"] and d["autopilot_stan"]["pauza"] is None
    k = klient.get("/api/konta").get_json()["konta"]["telegram"]
    assert k["jest"] and k["sparowany"] is False and "/start" in k["komunikat"] and "BotFather" in k["jak"]


def test_api_test_telegram_i_wyslij(klient, modelka, tg):
    d = klient.post("/api/konta/test", json={"dostawca": "telegram"}).get_json()
    assert d["dziala"] is True and "napisz do niego /start" in d["komunikat"]
    tg.wiadomosc(text="/start")
    autopilot.obsluz_telegram()
    d = klient.post("/api/konta/test", json={"dostawca": "telegram"}).get_json()
    assert "wyslalem testowa wiadomosc" in d["komunikat"]
    pid = baza.dodaj_pomysl(modelka, "x", "p")
    assert klient.post("/api/akcja", json={"typ": "telegram_wyslij", "id": pid}).status_code == 400   # brak pliku
    plik = os.path.join(baza.folder_gotowych(modelka), "001_x.mp4")
    open(plik, "wb").write(b"v")
    baza.aktualizuj_pomysl(modelka, pid, status="gotowe", plik_wynikowy=plik, podpis="hej")
    klient.post("/api/akcja", json={"typ": "telegram_wyslij", "id": pid})
    import app as panel
    panel.konsola.watek.join(5)
    assert tg.pliki[-1][0] == "sendVideo" and "hej" in tg.pliki[-1][1]["caption"]
    assert baza.pomysl(modelka, pid)["telegram_wyslano"] is True
    p = klient.get("/api/pomysly").get_json()["pomysly"][0]
    assert p["telegram_wyslano"] is True and p["wynik_miniatura_url"] is None


def test_porzadki_usuwa_stare_raw_i_robi_kopie(modelka, cli, bez_ffmpeg):
    import time as _t
    baza.zapisz_ustawienia(modelka, mediatool=False, sprzataj_po_dniach=14)
    open(os.path.join(baza.folder_zrodel(modelka), "a.mp4"), "wb").write(b"v")
    autopilot.przebieg(modelka)
    p = baza.pomysl(modelka, 1)
    raw = os.path.join(baza.folder_wynikow(modelka), "001_a.raw.mp4")
    assert os.path.isfile(raw) and os.path.isfile(p["plik_wynikowy"])
    assert autopilot.porzadki()["usuniete"] == 0            # swiezy - zostaje
    stary = _t.time() - 20 * 86400
    os.utime(raw, (stary, stary))
    w = autopilot.porzadki()
    assert w["usuniete"] == 1 and not os.path.isfile(raw) and os.path.isfile(p["plik_wynikowy"])
    assert w["kopie"] >= 3
    kopie = os.path.join(baza.KATALOG_MODELEK, "_kopie")
    assert os.path.isfile(os.path.join(kopie, sorted(os.listdir(kopie))[-1], modelka, "pomysly.json"))
    assert modelka in baza.lista_modelek() and "_kopie" not in baza.lista_modelek()   # folder kopii to nie persona


def test_diagnoza(modelka, cli, monkeypatch):
    import higgsfield_cli
    monkeypatch.setattr(higgsfield_cli, "sciezka_cli", lambda: "/udawane/hf")
    monkeypatch.setattr(higgsfield_cli, "konto", lambda: {"credits": 1000})
    d = {w["co"]: w for w in fabryka.diagnoza()}
    assert d["higgsfield"]["ok"] is True and d["telegram"]["ok"] is None
    assert d[f"persona {modelka}"]["ok"] is True
    for n in os.listdir(baza.folder_referencji(modelka)):
        os.remove(os.path.join(baza.folder_referencji(modelka), n))
    d = {w["co"]: w for w in fabryka.diagnoza()}
    assert d[f"persona {modelka}"]["ok"] is False and "zdjec" in d[f"persona {modelka}"]["info"]


def test_api_diagnoza(klient):
    d = klient.get("/api/diagnoza").get_json()
    assert d["ok"] and any(w["co"] == "ffmpeg" for w in d["diagnoza"])


def test_filmik_z_telefonu_robi_sie_bez_autopilota(tg, modelka, cli, bez_ffmpeg):
    """Persona ma autopilot=false, ale filmik przyslany z telefonu i tak jest robiony (i odsylany)."""
    baza.zapisz_ustawienia(modelka, mediatool=False, autopilot=False)
    tg.wiadomosc(text="/start")
    tg.wiadomosc(video={"file_id": "f1", "file_name": "z_fona.mp4", "file_size": 100})
    wyniki = autopilot.przebieg_wszystkich()
    assert [w["modelka"] for w in wyniki] == [modelka]
    assert wyniki[0]["nowe"] == 1 and wyniki[0]["wygenerowane"] == 1 and wyniki[0]["wyslane"] == 1
    assert tg.pliki[-1][0] == "sendVideo"
    # bez nowych filmikow persona bez autopilota nie jest ruszana
    assert autopilot.przebieg_wszystkich() == []


def test_komenda_zdjecie(tg, modelka, cli, bez_ffmpeg):
    tg.wiadomosc(text="/start")
    tg.wiadomosc(text="/zdjecie")
    autopilot.obsluz_telegram()
    assert "wybierz model zdjec" in tg.wyslane[-1][1]["text"]
    baza.zapisz_ustawienia(modelka, zdjecia_model="nano_banana_2")
    baza.zapisz_prompt(modelka, "zdjecia.txt", "portret\n")
    cli.cena = 2
    tg.wiadomosc(text="/zdjecie noemi")
    autopilot.obsluz_telegram()
    assert tg.pliki[-1][0] == "sendPhoto" and len(baza.lista_zdjec(modelka)) == 1
