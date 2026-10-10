# -*- coding: utf-8 -*-
"""3.6.1: telefon (Telegram) niezalezny od autopilota + dodatkowe konta. Wszystko na udawanym HTTP - zero prawdziwych wywolan
api.telegram.org (UdawanyTelegram z test_telegram_autopilot)."""
import os
import threading
import time

import pytest

import autopilot
import baza
from dostawcy import http, telegram
from test_telegram_autopilot import bez_ffmpeg, tg  # noqa: F401 - fixtury (udawany Telegram, bez ffmpeg)


@pytest.fixture(autouse=True)
def bez_raportu_dnia(monkeypatch):
    """Raport dnia idzie po 20:00 lokalnie - w testach watku nie moze dorzucac wiadomosci zaleznie od godziny
    (testy padaly wieczorem: o jedna wiadomosc wiecej). Raport ma wlasne testy."""
    monkeypatch.setattr(autopilot, "RAPORT_GODZINA", 99)


def _wiad(tg, chat_id, username, **msg):
    uid = len(tg.updates) + 1
    tg.updates.append({"update_id": uid, "message": dict({"chat": {"id": chat_id, "username": username},
                                                          "from": {"username": username}}, **msg)})


def _czekaj_az(warunek, max_s=5.0):
    """Czeka (prawdziwym czasem - time.sleep jest w testach wylaczony) az warunek bedzie spelniony."""
    koniec = time.monotonic() + max_s
    e = threading.Event()
    while time.monotonic() < koniec:
        if warunek():
            return True
        e.wait(0.02)
    return warunek()


def _teksty(tg, chat_id=None):
    return [d["text"] for m, d in tg.wyslane if m == "sendMessage" and (chat_id is None or d["chat_id"] == chat_id)]


def _wideo_do(tg):
    return [p["chat_id"] for m, p, _ in tg.pliki if m == "sendVideo"]


def _gotowa_rolka(slug, nazwa="a"):
    pid = baza.dodaj_pomysl(slug, nazwa, "p")
    plik = os.path.join(baza.folder_gotowych(slug), f"{pid:03d}_{nazwa}.mp4")
    with open(plik, "wb") as f:
        f.write(b"v")
    baza.aktualizuj_pomysl(slug, pid, status="gotowe", plik_wynikowy=plik, podpis="hej")
    return pid


@pytest.fixture
def watek(tg, monkeypatch):
    """Watek telefonu panelu (app.start_telefonu) z krotkim odstepem; konczy sie PRZED cofnieciem monkeypatchy."""
    import app as panel
    monkeypatch.setattr(autopilot, "ODSTEP_TELEFONU_W_TLE_S", 0.03)
    yield panel
    panel.stop_telefonu(czekaj_s=5)
    assert not panel.telefon_dziala()


# ---------------- watek odbioru niezalezny od autopilota ----------------

def test_watek_odbiera_przy_wylaczonym_autopilocie(watek, tg, modelka):
    panel = watek
    assert not panel._autopilot_wlaczony() and not autopilot.STAN.get("petla")
    tg.wiadomosc(text="/start")
    tg.wiadomosc(video={"file_id": "f1", "file_name": "z_fona.mp4", "file_size": 100})
    tg.wiadomosc(text="/status")
    panel.start_telefonu(pierwsza_pauza=0.01)
    assert panel.telefon_dziala()
    assert _czekaj_az(lambda: len(_teksty(tg, 777)) >= 3)
    t = _teksty(tg, 777)
    assert t[0] == "Polaczono - tu beda gotowe rolki, alarmy i raport dnia. /pomoc = komendy"
    assert t[1].startswith("Mam: z_fona.mp4 -> noemi") and "Autopilot jest wylaczony" in t[1]
    assert "noemi: czeka 0" in t[2]
    assert os.path.isfile(os.path.join(baza.folder_zrodel(modelka), "z_fona.mp4"))
    assert telegram.stan()["chat_id"] == 777 and telegram.stan()["offset"] == 4
    # nic sie nie wygenerowalo samo (autopilot wylaczony) - filmik czeka we wrzutni
    assert baza.lista_pomyslow(modelka) == []
    # gotowa rolka zrobiona recznie -> watek wysyla ja na telefon (raz)
    pid = _gotowa_rolka(modelka)
    assert _czekaj_az(lambda: _wideo_do(tg) == ["777"])
    assert _czekaj_az(lambda: baza.pomysl(modelka, pid).get("telegram_do") == ["777"])
    e = threading.Event()
    e.wait(0.2)
    assert _wideo_do(tg) == ["777"]
    # zamkniecie panelu konczy watek
    panel.stop_telefonu(czekaj_s=5)
    assert not panel.telefon_dziala()


def test_watek_bez_tokena_nic_nie_robi(dane, monkeypatch):
    import app as panel
    monkeypatch.setattr(autopilot, "ODSTEP_TELEFONU_W_TLE_S", 0.03)
    assert autopilot.telefon_w_tle() is None
    wolania = []
    monkeypatch.setattr(http, "zapytanie", lambda *a, **k: wolania.append(a) or {})
    try:
        panel.start_telefonu(pierwsza_pauza=0.01)
        threading.Event().wait(0.2)
    finally:
        panel.stop_telefonu(czekaj_s=5)
    assert wolania == []


def test_watek_nie_dubluje_sie_z_autopilotem(tg, modelka, monkeypatch):
    """Gdy autopilot robi swoj krok telefonu (blokada), watek panelu nic nie robi - i odwrotnie: zero drugiego getUpdates."""
    monkeypatch.setattr(autopilot, "CZEKAJ_NA_TELEFON_S", 0.2)
    getupdates = []
    oryginal = http.zapytanie
    w_srodku, pusc = threading.Event(), threading.Event()

    def zapytanie(metoda, url, dane=None, **k):
        if url.endswith("/getUpdates"):
            getupdates.append(int(dane.get("offset") or 0))
            if blokuj["tak"]:
                w_srodku.set()
                pusc.wait(5)
        return oryginal(metoda, url, dane=dane, **k)
    blokuj = {"tak": False}
    monkeypatch.setattr(http, "zapytanie", zapytanie)
    tg.wiadomosc(text="/start")

    # 1) autopilot trzyma blokade telefonu -> krok watku panelu pomija (bez getUpdates)
    with telegram.blokada() as moge:
        assert moge
        wynik = []
        t = threading.Thread(target=lambda: wynik.append(autopilot.telefon_w_tle()))
        t.start()
        t.join(5)
        assert wynik == [None] and getupdates == []

    # 2) watek panelu jest w trakcie getUpdates -> autopilot czeka krotko i pomija swoj odbior (zero getUpdates)
    blokuj["tak"] = True
    wynik = []
    t = threading.Thread(target=lambda: wynik.append(autopilot.telefon_w_tle()))
    t.start()
    assert w_srodku.wait(5)
    assert autopilot.obsluz_telegram() == []
    assert getupdates == [0]
    pusc.set()
    t.join(5)
    assert [z["tekst"] for z in wynik[0]] == ["/start"]
    blokuj["tak"] = False
    # wiadomosc obsluzona raz: jedna odpowiedz, offset przesuniety; nastepny odbior autopilota juz jej nie widzi
    assert len(_teksty(tg)) == 1
    assert autopilot.obsluz_telegram() == [] and getupdates == [0, 2]


def test_watek_i_przebiegi_autopilota_naraz_bez_duplikatow(watek, tg, modelka, monkeypatch):
    panel = watek
    monkeypatch.setattr(autopilot, "CZEKAJ_NA_TELEFON_S", 0.5)
    tg.wiadomosc(text="/start")
    for i in range(6):
        tg.wiadomosc(text="/status")
    panel.start_telefonu(pierwsza_pauza=0.0)
    for _ in range(5):
        autopilot.przebieg_wszystkich()
    assert _czekaj_az(lambda: telegram.stan()["offset"] == 8)
    threading.Event().wait(0.2)
    assert len(_teksty(tg)) == 7            # kazda wiadomosc dokladnie raz (1x /start + 6x /status)


def test_watek_przy_dzialajacej_petli_przekazuje_filmik_autopilotowi(tg, modelka, cli, bez_ffmpeg, monkeypatch):
    """Petla autopilota dziala, a filmik odebral watek panelu: najblizszy przebieg i tak go robi (persona bez autopilota)."""
    baza.zapisz_ustawienia(modelka, mediatool=False, autopilot=False)
    tg.wiadomosc(text="/start")
    tg.wiadomosc(video={"file_id": "f1", "file_name": "z_fona.mp4", "file_size": 100})
    monkeypatch.setitem(autopilot.STAN, "petla", True)
    z = autopilot.telefon_w_tle()
    assert [x["typ"] for x in z] == ["komenda", "wideo"]
    assert "Zrobie rolke i odesle" in _teksty(tg, 777)[-1]
    wyniki = autopilot.przebieg_wszystkich()
    assert [w["modelka"] for w in wyniki] == [modelka] and wyniki[0]["wygenerowane"] == 1
    assert _wideo_do(tg) == ["777"]
    assert autopilot._wez_odebrane_w_tle() == []


def test_watek_blad_sieci_cicha_pauza(watek, tg, modelka, monkeypatch):
    panel = watek
    oryginal = http.zapytanie
    siec = {"padla": True, "proby": 0}

    def zapytanie(metoda, url, dane=None, **k):
        if siec["padla"]:
            siec["proby"] += 1
            raise http.BladHTTP(0, "blad sieci: timed out", url)
        return oryginal(metoda, url, dane=dane, **k)
    monkeypatch.setattr(http, "zapytanie", zapytanie)
    monkeypatch.setattr(panel, "PAUZA_TELEFONU_MAX_S", 0.05)
    tg.wiadomosc(text="/start")
    panel.start_telefonu(pierwsza_pauza=0.0)
    assert _czekaj_az(lambda: siec["proby"] >= 3)
    assert panel._telefon["blad"] and "123:ABC" not in panel._telefon["blad"]
    assert [w for w in baza.dziennik_ostatnie(100) if "telegram" in w["tekst"]] == []     # bez zasmiecania dziennika
    siec["padla"] = False
    assert _czekaj_az(lambda: telegram.sparowany() and len(_teksty(tg, 777)) == 1)
    assert _czekaj_az(lambda: panel._telefon["blad"] is None)


def test_watek_inny_blad_jeden_wpis(watek, tg, modelka, monkeypatch):
    panel = watek
    oryginal = http.zapytanie

    def zapytanie(metoda, url, dane=None, **k):
        if url.endswith("/getUpdates"):
            raise http.BladHTTP(401, '{"ok": false, "description": "Unauthorized"}', url)
        return oryginal(metoda, url, dane=dane, **k)
    monkeypatch.setattr(http, "zapytanie", zapytanie)
    monkeypatch.setattr(panel, "PAUZA_TELEFONU_MAX_S", 0.05)
    panel.start_telefonu(pierwsza_pauza=0.0)
    assert _czekaj_az(lambda: panel._telefon["bledy_z_rzedu"] >= 3)
    wpisy = [w["tekst"] for w in baza.dziennik_ostatnie(100) if "odbior w tle" in w["tekst"]]
    assert len(wpisy) == 1 and "Unauthorized" in wpisy[0] and "123:ABC" not in wpisy[0]


# ---------------- dodatkowe konta: parowanie, odpowiedzi po /start, obce czaty ----------------

def test_parowanie_konta_dodatkowego_i_odpowiedzi(tg, modelka):
    baza.zapisz_ustawienia_globalne(telegram_dodatkowe=["drugie", "999000"])
    baza.zapisz_ustawienia(modelka, telegram_czat="@huy7128")
    # konto dodatkowe pisze PIERWSZE - nie zostaje czatem glownym
    _wiad(tg, 888, "Drugie", text="/start")
    tg.wiadomosc(text="/start")                            # 777 yux - czat glowny (pierwszy spoza list)
    _wiad(tg, 4242, "obcy", text="/start")                 # obcy (po czacie glownym) - zero odpowiedzi
    _wiad(tg, 555, "huy7128", text="/start")               # konto persony
    _wiad(tg, 999000, "", text="/start")                   # dodatkowe po id liczbowym (bez nazwy)
    z = autopilot.obsluz_telegram()
    assert len(z) == 4 and telegram.stan()["chat_id"] == 777
    assert sorted(telegram.czaty()) == ["555", "777", "888", "999000"]
    assert _teksty(tg, 888) == ["Polaczono jako dodatkowe konto - dostaniesz gotowe rolki i alarmy"]
    assert "Polaczono - tu beda gotowe rolki, alarmy i raport dnia. /pomoc = komendy" in _teksty(tg, 777)
    assert _teksty(tg, 555) == ["Polaczono z persona Noemi"]
    assert _teksty(tg, 999000) == ["Polaczono jako dodatkowe konto - dostaniesz gotowe rolki i alarmy"]
    assert _teksty(tg, 4242) == [] and "4242" not in telegram.czaty()
    # info dla wlasciciela o nowych kontach (czat glowny sparowal sie w tej samej paczce wiadomosci)
    info = _teksty(tg, 777)
    assert len(info) == 4 and any("@Drugie sparowane jako dodatkowe" in t for t in info)
    assert any("huy7128 sparowane z persona Noemi" in t for t in info) and any("999000 sparowane jako dodatkowe" in t for t in info)
    s = telegram.status_kont()
    assert s["glowny"]["nazwa"] == "yux"
    assert [(d["konto"], d["polaczone"]) for d in s["dodatkowe"]] == [("drugie", True), ("999000", True)]
    assert s["persony"] == [{"slug": "noemi", "persona": "Noemi", "konto": "huy7128", "polaczone": True}]
    assert "dodatkowe konta: @Drugie" in telegram.gotowy()[1]
    # obcy pisze dalej - ignorowany; konto usuniete z listy dodatkowych - tez ignorowane
    _wiad(tg, 4242, "obcy", text="/status")
    baza.zapisz_ustawienia_globalne(telegram_dodatkowe=["999000"])
    _wiad(tg, 888, "Drugie", text="/status")
    assert autopilot.obsluz_telegram() == []
    assert _teksty(tg, 4242) == [] and len(_teksty(tg, 888)) == 1


def test_dodatkowe_konto_bez_komend_wlasciciela(tg, modelka):
    baza.zapisz_ustawienia_globalne(telegram_dodatkowe=["drugie"])
    tg.wiadomosc(text="/start")
    _wiad(tg, 888, "drugie", text="/stop")
    _wiad(tg, 888, "drugie", text="/zdjecie")
    _wiad(tg, 888, "drugie", text="/status")
    _wiad(tg, 888, "drugie", text="/pomoc")
    z = autopilot.obsluz_telegram()
    assert z[1].get("odmowa") and z[2].get("odmowa")
    assert baza.autopilot_stan(modelka)["pauza"] is None
    t = _teksty(tg, 888)
    assert "tylko czat glowny" in t[0] and "tylko czat glowny albo konto persony" in t[1]
    assert "noemi:" in t[2] and "/status" in t[3]
    # /raport z dodatkowego: odpowiedz tylko do pytajacego (nie do wszystkich)
    ile_777 = len(_teksty(tg, 777))
    _wiad(tg, 888, "drugie", text="/raport")
    autopilot.obsluz_telegram()
    assert _teksty(tg, 888)[-1].startswith("Raport ") and len(_teksty(tg, 777)) == ile_777


def test_normalizuj_konta():
    assert telegram.normalizuj_konta("@Ala_1\n https://t.me/Bob123 , @ala_1;  -1001234 ") == ["ala_1", "bob123", "-1001234"]
    assert telegram.normalizuj_konta(["@x_y_z", ""]) == ["x_y_z"]
    assert telegram.normalizuj_konta("@aaa @bbb\r\n@ccc") == ["aaa", "bbb", "ccc"]
    assert telegram.normalizuj_konta("") == []
    with pytest.raises(ValueError) as e:
        telegram.normalizuj_konta("@ok_konto\nzle konto!")
    assert '"zle konto!"' in str(e.value)
    with pytest.raises(ValueError):
        telegram.normalizuj_konta("@a")


# ---------------- wysylka: glowny + dodatkowe + konto persony, bez duplikatow, blad jednego ----------------

@pytest.fixture
def trzy_konta(tg, modelka):
    """777 = czat glowny (yux) i POTEM dopisany tez do dodatkowych, 888 = dodatkowe, 555 = konto persony noemi."""
    baza.zapisz_ustawienia(modelka, mediatool=False, telegram_czat="@huy7128")
    tg.wiadomosc(text="/start")
    autopilot.obsluz_telegram()
    baza.zapisz_ustawienia_globalne(telegram_dodatkowe=["yux", "drugie", "nie_napisal"])
    _wiad(tg, 888, "drugie", text="/start")
    _wiad(tg, 555, "huy7128", text="/start")
    autopilot.obsluz_telegram()
    tg.wyslane.clear()
    return tg


def test_wysylka_rolki_do_wszystkich_bez_duplikatow(trzy_konta, modelka, cli, bez_ffmpeg):
    tg = trzy_konta
    open(os.path.join(baza.folder_zrodel(modelka), "a.mp4"), "wb").write(b"v")
    w = autopilot.przebieg(modelka)
    assert w["wygenerowane"] == 1 and w["wyslane"] == 1
    assert sorted(_wideo_do(tg)) == ["555", "777", "888"]          # 777 jest glowny i dodatkowy - jedna wiadomosc
    p = baza.pomysl(modelka, 1)
    assert p["telegram_wyslano"] is True and sorted(p["telegram_do"]) == ["555", "777", "888"]
    assert autopilot.przebieg(modelka)["wyslane"] == 0 and len(tg.pliki) == 3
    # druga persona bez wlasnego konta: glowny + dodatkowe
    slug2 = baza.utworz_modelke("Alicja")
    _gotowa_rolka(slug2)
    assert autopilot.wyslij_gotowe(slug2) == 1 and sorted(_wideo_do(tg)[3:]) == ["777", "888"]
    # alarmy i raport: glowny + dodatkowe (nie konto persony), kazde raz
    assert autopilot.wyslij_na_telefon("STOP test") is True
    assert sorted(d["chat_id"] for m, d in tg.wyslane if d.get("text") == "STOP test") == [777, 888]
    tekst = autopilot.raport_dnia(wymus=True)
    assert sorted(d["chat_id"] for m, d in tg.wyslane if d.get("text") == tekst) == [777, 888]
    # zdjecia tez do wszystkich trzech
    plik = os.path.join(baza.folder_zdjec(modelka), "001_z.png")
    open(plik, "wb").write(b"png")
    baza.dodaj_zdjecie(modelka, "portret", plik=plik)
    assert autopilot.wyslij_zdjecia(modelka) == 1
    assert sorted(p["chat_id"] for m, p, _ in tg.pliki if m == "sendPhoto") == ["555", "777", "888"]
    assert autopilot.wyslij_zdjecia(modelka) == 0


def test_blad_jednego_konta_nie_blokuje_reszty(trzy_konta, modelka, monkeypatch):
    tg = trzy_konta
    oryginal = http.multipart
    zle = {"888": "blad"}

    def multipart(url, pola=None, pliki=None, **k):
        rodzaj = zle.get(pola.get("chat_id"))
        if rodzaj == "blad":
            raise http.BladHTTP(403, '{"ok": false, "description": "Forbidden: bot was blocked by the user"}', url)
        if rodzaj == "siec":
            raise http.BladHTTP(0, "blad sieci: timed out", url)
        return oryginal(url, pola=pola, pliki=pliki, **k)
    monkeypatch.setattr(http, "multipart", multipart)
    pid = _gotowa_rolka(modelka)
    assert autopilot.wyslij_gotowe(modelka) == 1
    assert sorted(_wideo_do(tg)) == ["555", "777"]
    p = baza.pomysl(modelka, pid)
    assert sorted(p["telegram_do"]) == ["555", "777"] and p["telegram_bledy"] == {"888": 1}
    wpisy = [w["tekst"] for w in baza.dziennik_ostatnie(50) if "nie wyslalem rolki" in w["tekst"]]
    assert wpisy == [f"telegram: nie wyslalem rolki #{pid} do @drugie (Telegram sendVideo: Forbidden: bot was blocked by the user)"]
    # kolejne przebiegi probuja juz tylko 888, max 3 razy - potem spokoj
    autopilot.wyslij_gotowe(modelka)
    autopilot.wyslij_gotowe(modelka)
    autopilot.wyslij_gotowe(modelka)
    assert baza.pomysl(modelka, pid)["telegram_bledy"] == {"888": 3}
    assert len([w for w in baza.dziennik_ostatnie(50) if "nie wyslalem rolki" in w["tekst"]]) == 3
    assert sorted(_wideo_do(tg)) == ["555", "777"]
    # blad sieci: nic nie liczy, nic w dzienniku, nastepny raz wysyla
    pid2 = _gotowa_rolka(modelka, "b")
    zle.update({"888": None, "555": "siec"})
    with pytest.raises(telegram.BladSieci):
        autopilot.wyslij_gotowe(modelka)
    p2 = baza.pomysl(modelka, pid2)
    assert p2.get("telegram_bledy") is None and "555" not in (p2.get("telegram_do") or [])
    assert len([w for w in baza.dziennik_ostatnie(50) if "nie wyslalem rolki" in w["tekst"]]) == 3
    zle["555"] = None
    autopilot.wyslij_gotowe(modelka)
    assert sorted(baza.pomysl(modelka, pid2)["telegram_do"]) == ["555", "777", "888"]


def test_blad_tekstu_do_jednego_konta(trzy_konta, monkeypatch):
    tg = trzy_konta
    oryginal = http.zapytanie

    def zapytanie(metoda, url, dane=None, **k):
        if url.endswith("/sendMessage") and dane.get("chat_id") == 777:
            raise http.BladHTTP(400, '{"ok": false, "description": "Bad Request: chat not found"}', url)
        return oryginal(metoda, url, dane=dane, **k)
    monkeypatch.setattr(http, "zapytanie", zapytanie)
    assert autopilot.wyslij_na_telefon("alarm 1") is True
    assert autopilot.wyslij_na_telefon("alarm 2") is True
    assert [d["chat_id"] for m, d in tg.wyslane] == [888, 888]
    wpisy = [w["tekst"] for w in baza.dziennik_ostatnie(50) if "nie wyslalem wiadomosci" in w["tekst"]]
    assert wpisy == ["telegram: nie wyslalem wiadomosci do @yux (Telegram sendMessage: Bad Request: chat not found)"]


def test_watek_nie_wysyla_swiezo_wygenerowanej_przed_praniem(tg, modelka):
    tg.wiadomosc(text="/start")
    autopilot.obsluz_telegram()
    pid = baza.dodaj_pomysl(modelka, "x", "p")
    surowy = os.path.join(baza.folder_wynikow(modelka), "001_x.raw.mp4")
    open(surowy, "wb").write(b"v")
    baza.aktualizuj_pomysl(modelka, pid, status="wygenerowany", plik_wynikowy=surowy)
    assert autopilot.wyslij_gotowe(modelka, w_tle=True) == 0        # moze byc tuz przed Media Tool
    assert autopilot.wyslij_gotowe(modelka) == 1                    # autopilot (po praniu w tym samym przebiegu) - jak dawniej
    assert _wideo_do(tg) == ["777"]


def test_stare_wyslane_rolki_nie_ida_drugi_raz(tg, modelka):
    """Rolka wyslana przed 3.6.1 (telegram_wyslano bez telegram_do) nie leci do nowych kont."""
    baza.zapisz_ustawienia_globalne(telegram_dodatkowe=["drugie"])
    tg.wiadomosc(text="/start")
    _wiad(tg, 888, "drugie", text="/start")
    autopilot.obsluz_telegram()
    pid = _gotowa_rolka(modelka)
    baza.aktualizuj_pomysl(modelka, pid, telegram_wyslano=True)
    assert autopilot.wyslij_gotowe(modelka) == 0 and tg.pliki == []


# ---------------- API panelu ----------------

@pytest.fixture
def klient(tg, modelka):
    import app as panel
    panel._konta_test.clear()
    panel.konsola.__init__()
    telegram._bot_cache.clear()
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        yield c


def test_api_telegram_status_zapis_test(klient, tg, modelka):
    d = klient.get("/api/telegram").get_json()["telegram"]
    assert d["bot"] == {"username": "rolki_bot", "link": "https://t.me/rolki_bot", "imie": ""}
    assert d["glowny"] is None and d["dodatkowe"] == [] and d["persony"] == []
    r = klient.post("/api/telegram", json={"dodatkowe": "@drugie\nzle konto!"})
    assert r.status_code == 400 and '"zle konto!"' in r.get_json()["blad"]
    d = klient.post("/api/telegram", json={"dodatkowe": "@Drugie\n@trzecie"}).get_json()["telegram"]
    assert baza.ustawienia_globalne()["telegram_dodatkowe"] == ["drugie", "trzecie"]
    assert [(x["konto"], x["polaczone"]) for x in d["dodatkowe"]] == [("drugie", False), ("trzecie", False)]
    # przez ustawienia wspolne tez mozna (te same zasady)
    assert klient.post("/api/ustawienia/globalne", json={"telegram_dodatkowe": ["zle konto!"]}).status_code == 400
    assert klient.post("/api/ustawienia/globalne", json={"telegram_dodatkowe": ["@drugie"]}).get_json()["ok"]
    # test bez sparowanych kont = jasny blad
    r = klient.post("/api/telegram/test", json={})
    assert r.status_code == 400 and "Start" in r.get_json()["blad"]
    baza.zapisz_ustawienia(modelka, telegram_czat="@huy7128")
    tg.wiadomosc(text="/start")
    _wiad(tg, 888, "drugie", text="/start")
    _wiad(tg, 555, "huy7128", text="/start")
    autopilot.obsluz_telegram()
    tg.wyslane.clear()
    d = klient.get("/api/telegram").get_json()["telegram"]
    assert d["glowny"] == {"nazwa": "yux", "polaczone": True}
    assert d["dodatkowe"] == [{"konto": "drugie", "polaczone": True, "glowny": False}]
    assert d["persony"][0]["polaczone"] is True
    w = klient.post("/api/telegram/test", json={}).get_json()
    assert w["wyslane"] == 3 and sorted(d["chat_id"] for m, d in tg.wyslane) == [555, 777, 888]
    assert [x["rola"] for x in w["wyniki"]] == ["glowny", "dodatkowe", "persona"]
    # odlaczenie czatu glownego (wymaga potwierdzenia); konta z list zostaja
    assert klient.post("/api/telegram/rozparuj", json={}).status_code == 400
    d = klient.post("/api/telegram/rozparuj", json={"potwierdzam": True}).get_json()["telegram"]
    assert d["glowny"] is None and d["dodatkowe"][0]["polaczone"] is True
    assert "777" not in telegram.czaty()


def test_api_stan_autopilot_zostaje_wylaczony(klient):
    import app as panel
    d = klient.get("/api/stan").get_json()
    assert d["wersja"] == "3.6.1" and d["autopilot"]["wlaczony"] is False and not panel.telefon_dziala()


def test_glowne_konto_na_liscie_dodatkowych_przed_parowaniem(tg, modelka):
    """Konto z listy dodatkowych nie zostaje czatem glownym (nawet gdy pisze pierwsze) - ale dostaje rolki, alarmy i raport."""
    baza.zapisz_ustawienia_globalne(telegram_dodatkowe=["yux"])
    tg.wiadomosc(text="/start")
    autopilot.obsluz_telegram()
    assert not telegram.sparowany() and telegram.status_kont()["dodatkowe"][0]["polaczone"] is True
    assert _teksty(tg, 777) == ["Polaczono jako dodatkowe konto - dostaniesz gotowe rolki i alarmy"]
    _gotowa_rolka(modelka)
    assert autopilot.wyslij_gotowe(modelka) == 1 and _wideo_do(tg) == ["777"]
    assert autopilot.wyslij_na_telefon("alarm") is True
    tekst = autopilot.raport_dnia(wymus=True)
    assert tekst and _teksty(tg, 777)[-1] == tekst
