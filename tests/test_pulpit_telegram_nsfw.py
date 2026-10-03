# -*- coding: utf-8 -*-
"""Foldery na pulpicie, osobne konto Telegram per persona, filtr NSFW (powod + wskazowki), zdjecia ze strojow, nowe API."""
import os

import autopilot
import baza
import fabryka
import zdjecia
from dostawcy import telegram
from test_telegram_autopilot import bez_ffmpeg, tg  # noqa: F401 - fixtury (udawany Telegram, bez ffmpeg)


# ---------------- foldery na pulpicie ----------------

def test_foldery_pulpitu_tworzy_i_wpisuje(modelka):
    w = baza.przygotuj_foldery_pulpitu(modelka)
    pulpit = baza.pulpit()
    assert w["foldery"]["zrodla_dir"] == os.path.join(pulpit, "tu wrzucasz rolki", "Noemi")
    assert w["foldery"]["wyniki_dir"] == os.path.join(pulpit, "tu rolki zrobione", "Noemi")
    assert w["foldery"]["zdjecia_dir"] == os.path.join(pulpit, "tu zdjecia zrobione", "Noemi")
    assert set(w["zmienione"]) == {"zrodla_dir", "wyniki_dir", "zdjecia_dir"}
    for f in w["foldery"].values():
        assert os.path.isdir(f)
    assert baza.folder_zrodel(modelka) == w["foldery"]["zrodla_dir"]
    assert baza.folder_gotowych(modelka) == w["foldery"]["wyniki_dir"]
    assert baza.folder_zdjec(modelka) == w["foldery"]["zdjecia_dir"]
    # drugi raz: nic nie zmienia
    assert baza.przygotuj_foldery_pulpitu(modelka)["zmienione"] == {}


def test_foldery_pulpitu_przenosi_stare_przed_po(modelka, bez_ffmpeg):
    pulpit = baza.pulpit()
    stary = os.path.join(pulpit, "przed", "noemi")
    os.makedirs(stary)
    open(os.path.join(stary, "klip.mp4"), "wb").write(b"v")
    baza.zapisz_ustawienia(modelka, zrodla_dir=stary, wyniki_dir=os.path.join(pulpit, "po", "noemi"))
    fabryka.skanuj(modelka)
    assert baza.pomysl(modelka, 1)["zrodlo"] == os.path.join(stary, "klip.mp4")
    w = baza.przygotuj_foldery_pulpitu(modelka)
    nowy = os.path.join(pulpit, "tu wrzucasz rolki", "Noemi")
    assert w["zmienione"]["zrodla_dir"] == nowy and os.path.isfile(os.path.join(nowy, "klip.mp4")) and not os.path.exists(stary)
    assert not os.path.exists(os.path.join(pulpit, "przed"))          # puste "przed" sprzatniete
    assert baza.pomysl(modelka, 1)["zrodlo"] == os.path.join(nowy, "klip.mp4")   # sciezka w kolejce przepisana
    assert baza.ustawienia_modelki(modelka)["wyniki_dir"] == os.path.join(pulpit, "tu rolki zrobione", "Noemi")


def test_foldery_pulpitu_nie_rusza_wlasnego_folderu(modelka, tmp_path):
    wlasny = str(tmp_path / "moje_filmy")
    baza.zapisz_ustawienia(modelka, zrodla_dir=wlasny)
    w = baza.przygotuj_foldery_pulpitu(modelka)
    assert "zrodla_dir" not in w["zmienione"] and w["foldery"]["zrodla_dir"] == wlasny
    assert "wyniki_dir" in w["zmienione"]
    assert baza.ustawienia_modelki(modelka)["zrodla_dir"] == wlasny


def test_nazwa_folderu_persony_bez_dziwnych_znakow(dane):
    slug = baza.utworz_modelke("Ala")
    baza.zapisz_profil(slug, nazwa='Ala: "Mała"/x')
    assert baza.foldery_pulpitu(slug)["zrodla_dir"].endswith(os.path.join("tu wrzucasz rolki", "Ala_ _Mała_x"))


def test_api_nowa_modelka_tworzy_foldery_i_otwieranie(dane, cli):
    import app as panel
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        d = c.post("/api/modelki", json={"nazwa": "Bianka"}).get_json()
        assert d["ok"] and os.path.isdir(d["foldery"]["zrodla_dir"]) and "tu wrzucasz rolki" in d["foldery"]["zrodla_dir"]
        s = c.get("/api/stan").get_json()
        assert s["modelki"][0]["foldery"]["wrzutnia"] == d["foldery"]["zrodla_dir"]
        assert s["foldery"]["gotowe"] == d["foldery"]["wyniki_dir"]
        o = c.post("/api/folder/otworz", json={"co": "wrzutnia"})
        if hasattr(os, "startfile"):
            assert o.get_json()["ok"]
        else:
            assert o.status_code == 400 and d["foldery"]["zrodla_dir"] in o.get_json()["blad"]
        assert c.post("/api/folder/otworz", json={"co": "cos"}).status_code == 400


def test_cli_foldery(modelka, capsys):
    assert fabryka.main(["--modelka", modelka, "foldery"]) == 0
    out = capsys.readouterr().out
    assert "wrzucasz tu" in out and "tu wrzucasz rolki" in out and "(nowe)" in out


# ---------------- Telegram: konto persony ----------------

def _wiad(tg, chat_id, username, **msg):
    uid = len(tg.updates) + 1
    tg.updates.append({"update_id": uid, "message": dict({"chat": {"id": chat_id, "username": username}, "from": {"username": username}}, **msg)})


def test_telegram_konto_persony(tg, modelka, cli, bez_ffmpeg):
    baza.zapisz_ustawienia(modelka, mediatool=False, telegram_czat="@huy7128")
    tg.wiadomosc(text="/start")                       # 777 yux = czat glowny
    _wiad(tg, 999, "obcy", text="/start")             # nikt - ignorowany
    _wiad(tg, 555, "huy7128", text="/start")          # konto persony noemi - paruje sie
    z = autopilot.obsluz_telegram()
    assert [w[1]["chat_id"] for w in tg.wyslane] == [777, 555, 777]   # powitanie glownego, powitanie persony, info dla glownego
    assert "persony noemi" in tg.wyslane[1][1]["text"] and "huy7128 sparowane" in tg.wyslane[2][1]["text"]
    assert len(z) == 2 and telegram.stan()["chat_id"] == 777
    assert telegram.czaty() == {"777": {"nazwa": "yux", "glowny": True}, "555": {"nazwa": "huy7128", "glowny": False}}
    assert telegram.czat_dla("@HUY7128") == (555, "huy7128") and telegram.czat_dla("") == (777, "yux")
    assert telegram.czat_dla("@nikt")[0] is None
    assert "konta person: @huy7128" in telegram.gotowy()[1]
    # gotowa rolka noemi -> czat persony (555), nie glowny
    open(os.path.join(baza.folder_zrodel(modelka), "a.mp4"), "wb").write(b"v")
    w = autopilot.przebieg(modelka)
    assert w["wygenerowane"] == 1 and w["wyslane"] == 1
    assert tg.pliki[-1][0] == "sendVideo" and tg.pliki[-1][1]["chat_id"] == "555"
    # /stop z konta persony - odmowa; /status - dziala i odpowiada na ten czat
    _wiad(tg, 555, "huy7128", text="/stop")
    _wiad(tg, 555, "huy7128", text="/status")
    z = autopilot.obsluz_telegram()
    assert z[0].get("odmowa") and baza.autopilot_stan(modelka)["pauza"] is None
    assert tg.wyslane[-1][1]["chat_id"] == 555 and "noemi:" in tg.wyslane[-1][1]["text"]
    # filmik z konta persony bez podpisu -> wrzutnia tej persony
    baza.utworz_modelke("Alicja"); baza.ustaw_aktywna_modelke("alicja")
    _wiad(tg, 555, "huy7128", video={"file_id": "f9", "file_name": "nowy.mp4", "file_size": 10})
    z = autopilot.obsluz_telegram()
    assert z[0]["modelka"] == modelka and z[0]["plik"].startswith(baza.folder_zrodel(modelka))


def test_telegram_konto_persony_bez_start_czeka(tg, modelka, cli, bez_ffmpeg):
    baza.zapisz_ustawienia(modelka, mediatool=False, telegram_czat="@huy7128")
    tg.wiadomosc(text="/start")
    autopilot.obsluz_telegram()
    open(os.path.join(baza.folder_zrodel(modelka), "a.mp4"), "wb").write(b"v")
    autopilot._OSTRZEZENIA.clear()
    w = autopilot.przebieg(modelka)
    assert w["wygenerowane"] == 1 and w["wyslane"] == 0 and tg.pliki == []
    assert "nie napisal jeszcze /start" in tg.wyslane[-1][1]["text"] and tg.wyslane[-1][1]["chat_id"] == 777
    assert baza.pomysl(modelka, 1).get("telegram_wyslano") is None
    ile = len(tg.wyslane)
    autopilot.przebieg(modelka)
    assert len(tg.wyslane) == ile                      # ostrzezenie tylko raz
    # konto pisze /start -> kolejny przebieg wysyla zalegla rolke
    _wiad(tg, 555, "huy7128", text="/start")
    autopilot.obsluz_telegram()
    assert autopilot.przebieg(modelka)["wyslane"] == 1 and tg.pliki[-1][1]["chat_id"] == "555"
    d = {w["co"]: w for w in fabryka.diagnoza()}
    assert d[f"telefon {modelka}"]["ok"] is True and d[f"foldery {modelka}"]["ok"] is True


def test_api_telegram_wyslij_na_konto_persony(tg, modelka, cli, bez_ffmpeg):
    import app as panel
    panel.konsola.__init__()
    panel.app.config["TESTING"] = True
    baza.zapisz_ustawienia(modelka, mediatool=False, telegram_czat="huy7128")
    tg.wiadomosc(text="/start")
    autopilot.obsluz_telegram()
    pid = baza.dodaj_pomysl(modelka, "x", "p")
    plik = os.path.join(baza.folder_gotowych(modelka), "001_x.mp4")
    open(plik, "wb").write(b"v")
    baza.aktualizuj_pomysl(modelka, pid, status="gotowe", plik_wynikowy=plik)
    with panel.app.test_client() as c:
        r = c.post("/api/akcja", json={"typ": "telegram_wyslij", "id": pid})
        assert r.status_code == 400 and "/start" in r.get_json()["blad"]
        _wiad(tg, 555, "huy7128", text="/start")
        autopilot.obsluz_telegram()
        assert c.post("/api/akcja", json={"typ": "telegram_wyslij", "id": pid}).status_code == 200
        panel.konsola.watek.join(5)
        assert tg.pliki[-1][1]["chat_id"] == "555"
        assert [x["nazwa"] for x in c.get("/api/stan").get_json()["telegram"]["czaty"]] == ["yux", "huy7128"]


# ---------------- NSFW ----------------

def test_powod_odrzucenia():
    assert fabryka.powod_odrzucenia("nsfw") == "nsfw"
    assert fabryka.powod_odrzucenia("failed", "rejected: NSFW content") == "nsfw"
    assert fabryka.powod_odrzucenia("ip_detected") == "ip"
    assert fabryka.powod_odrzucenia("failed", "timeout") == "inny"
    assert fabryka.powod_odrzucenia("", "") is None


def test_nsfw_dwa_razy_z_rzedu_konczy_proby(modelka, cli, bez_ffmpeg):
    baza.zapisz_ustawienia(modelka, mediatool=False, powtorki=2)
    open(os.path.join(baza.folder_zrodel(modelka), "a.mp4"), "wb").write(b"v")
    fabryka.skanuj(modelka)
    nsfw = {"id": "j1", "status": "nsfw", "result_url": None, "fail_reason": "nsfw"}
    cli.wyniki = [dict(nsfw), dict(nsfw), None]
    w = fabryka.generuj(modelka)
    assert w["bledy"] == [1] and len(cli.generacje) == 2       # trzecia proba sie nie odbyla
    p = baza.pomysl(modelka, 1)
    assert p["status"] == "blad" and p["powod"] == "nsfw"
    wpisy = [x for x in baza.dziennik_ostatnie(50) if x.get("dane", {}).get("powod") == "nsfw"]
    assert wpisy and "filtr tresci" in wpisy[-1]["tekst"]
    # jedno odrzucenie, potem sukces -> powtorka ma sens
    open(os.path.join(baza.folder_zrodel(modelka), "b.mp4"), "wb").write(b"v")
    fabryka.skanuj(modelka)
    cli.wyniki = [dict(nsfw), None]
    assert fabryka.generuj(modelka)["wygenerowane"] == 1 and baza.pomysl(modelka, 2)["status"] == "gotowe"


def test_wskazowki_nsfw(modelka, cli, bez_ffmpeg):
    baza.zapisz_prompt(modelka, "stroj_z_filmu.txt", "Complete replacement, black MESH top and lace skirt @[Image 1](image_1) @[Image 2](image_2)")
    open(os.path.join(baza.folder_strojow(modelka), "siatka.png"), "wb").write(b"img")
    w = fabryka.wskazowki_nsfw(modelka)
    assert w["odrzucone"] == 0 and w["slowa"]["A"] == ["mesh", "lace"] and w["slowa"]["B"] == []
    assert any("mesh, lace" in x for x in w["wskazowki"]) and any("strojow" in x or "stroju" in x for x in w["wskazowki"])
    open(os.path.join(baza.folder_zrodel(modelka), "a.mp4"), "wb").write(b"v")
    fabryka.skanuj(modelka)
    cli.wyniki = [{"id": "j1", "status": "nsfw", "result_url": None}] * 3
    baza.zapisz_ustawienia(modelka, mediatool=False)
    fabryka.generuj(modelka)
    w = fabryka.wskazowki_nsfw(modelka)
    assert w["odrzucone"] == 1 and w["odrzucone_ostatnio"] == 1
    import app as panel
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        d = c.get("/api/nsfw").get_json()
        assert d["ok"] and d["odrzucone"] == 1 and d["slowa"]["A"] == ["mesh", "lace"]
        assert c.get("/api/statystyki").get_json()["razem"]["nsfw"] == 1
        assert c.get("/api/pomysly").get_json()["pomysly"][0]["powod"] == "nsfw"
    assert fabryka.main(["--modelka", modelka, "nsfw"]) == 0


# ---------------- zdjecia ze strojow ----------------

def test_zdjecia_ze_strojami(modelka, cli):
    baza.zapisz_ustawienia(modelka, zdjecia_model="nano_banana_2")
    baza.zapisz_prompt(modelka, "zdjecia.txt", "portret\nstreet\n")
    stroje = baza.folder_strojow(modelka)
    open(os.path.join(stroje, "01_mesh.png"), "wb").write(b"img")
    open(os.path.join(stroje, "02_skora.png"), "wb").write(b"img")
    cli.cena = 2
    assert zdjecia.generuj(modelka, ile=2)["zrobione"] == 2
    lista = baza.lista_zdjec(modelka)
    assert lista[0]["stroj"] is None                                   # pierwsze: bez stroju
    assert lista[1]["stroj"].endswith("01_mesh.png")                   # drugie: w stroju (po kolei)
    model, params, media = cli.generacje[1]
    assert media["image"][-1].endswith("01_mesh.png") and len(media["image"]) == 3
    assert params["prompt"].startswith("street") and "outfit from the last reference image" in params["prompt"]
    assert "outfit" not in cli.generacje[0][1]["prompt"]
    # jawnie: auto = kolejny stroj (02), bez = brak, nazwa pliku
    zdjecia.generuj(modelka, ile=1, stroj="auto")
    assert baza.lista_zdjec(modelka)[-1]["stroj"].endswith("02_skora.png")
    zdjecia.generuj(modelka, ile=1, stroj="bez")
    assert baza.lista_zdjec(modelka)[-1]["stroj"] is None
    zdjecia.generuj(modelka, ile=1, stroj="01_mesh.png")
    assert baza.lista_zdjec(modelka)[-1]["stroj"].endswith("01_mesh.png")
    w = zdjecia.generuj(modelka, ile=1, stroj="nie_ma.png")
    assert w["zrobione"] == 0 and "Nie ma takiego stroju" in w["stop"]
    # wylaczone zdjecia_stroje -> nigdy automatycznie
    baza.zapisz_ustawienia(modelka, zdjecia_stroje=False)
    zdjecia.generuj(modelka, ile=2)
    assert all(z["stroj"] is None for z in baza.lista_zdjec(modelka)[-2:])


def test_zdjecia_bez_strojow_jak_dawniej(modelka, cli):
    baza.zapisz_ustawienia(modelka, zdjecia_model="nano_banana_2")
    cli.cena = 2
    assert zdjecia.generuj(modelka, ile=3, prompt="x")["zrobione"] == 3
    assert all(z["stroj"] is None for z in baza.lista_zdjec(modelka))
    assert all(len(m["image"]) == 2 for _, _, m in cli.generacje)


def test_api_zdjecia_ze_strojem(modelka, cli):
    import app as panel
    panel.konsola.__init__()
    panel.app.config["TESTING"] = True
    baza.zapisz_ustawienia(modelka, zdjecia_model="nano_banana_2")
    open(os.path.join(baza.folder_strojow(modelka), "goth.png"), "wb").write(b"img")
    cli.cena = 2
    with panel.app.test_client() as c:
        assert c.post("/api/akcja", json={"typ": "zdjecia", "ile": 1, "prompt": "x", "stroj": "goth.png"}).status_code == 200
        panel.konsola.watek.join(5)
    assert baza.lista_zdjec(modelka)[-1]["stroj"].endswith("goth.png")


# ---------------- drobiazgi ----------------

def test_index_bez_cache_i_ikona(dane):
    import app as panel
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        html = c.get("/").data.decode()
        assert f"/static/app.js?v={panel.WERSJA}" in html and f"/static/style.css?v={panel.WERSJA}" in html
        assert c.get("/static/rolki.ico").status_code == 200


def test_pliki_startowe_bez_schtasks():
    katalog = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for n in ("skroty.vbs", "rolki.vbs", "start-cicho.vbs", "skrot-na-pulpit.bat", "autostart.bat", "autostart-usun.bat", "static/rolki.ico"):
        assert os.path.isfile(os.path.join(katalog, n)), n
    tekst = open(os.path.join(katalog, "autostart.bat"), encoding="utf-8", errors="replace").read()
    assert "schtasks /Create" not in tekst and "skroty.vbs" in tekst
    assert "pulpit" in open(os.path.join(katalog, "aktualizuj.bat"), encoding="utf-8", errors="replace").read()
