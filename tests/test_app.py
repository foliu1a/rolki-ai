# -*- coding: utf-8 -*-
"""API panelu (Flask test client) na katalogu tymczasowym i udawanym CLI."""
import io
import os
import threading

import pytest

import app as panel
import baza
import fabryka
import sekrety


@pytest.fixture
def klient(modelka, cli, monkeypatch):
    """Klient HTTP panelu z wyczyszczonymi cache'ami i konsola; bez ffmpeg; Media Tool wylaczony."""
    panel._saldo.clear()
    panel._modele_cache.clear()
    panel._konta_test.clear()
    panel.konsola.__init__()
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 6.0, "szer": 720, "wys": 1280, "fps": 30.0})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda zrodlo, cel, ile=6: (os.makedirs(os.path.dirname(cel), exist_ok=True), open(cel, "wb").write(b"jpg")))
    baza.zapisz_ustawienia(modelka, mediatool=False)
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        yield c
    if panel._autopilot_wlaczony():
        panel.autopilot_stop()
        panel._autopilot["watek"].join(5)


def _json(odp):
    dane = odp.get_json()
    assert dane is not None, odp.data
    return dane


def _czekaj_na_zadanie():
    w = panel.konsola.watek
    if w:
        w.join(10)
    assert not panel.konsola.stan["trwa"]
    return panel.konsola.opis()


def _wrzuc(slug, nazwa, tresc=b"mp4"):
    p = os.path.join(baza.folder_zrodel(slug), nazwa)
    with open(p, "wb") as f:
        f.write(tresc)
    return p


# ---------------- stan ----------------

def test_stan_bez_modelki(dane, cli):
    panel._saldo.clear()
    with panel.app.test_client() as c:
        d = _json(c.get("/api/stan"))
    assert d["ok"] and d["aktywna"] is None and d["stan"] is None and d["modelki"] == []
    assert d["saldo"]["higgsfield"]["kredyty"] == 1000


def test_stan_z_modelka(klient, modelka, cli):
    _wrzuc(modelka, "nowy.mp4")
    d = _json(klient.get("/api/stan"))
    assert d["aktywna"] == modelka
    assert d["modelki"][0]["slug"] == modelka and d["modelki"][0]["autopilot"] is False
    s = d["stan"]
    assert s["niezeskanowane"] == ["nowy.mp4"] and s["referencje"] == ["01_twarz.png", "02_sylwetka.jpg"]
    assert s["budzet"]["limit_dzienny"] == 300 and s["budzet"]["min_kredyty"] == 200
    assert d["konta"]["higgsfield"]["ok"] is True and d["konta"]["yapper"]["jest"] is False
    assert d["autopilot"]["wlaczony"] is False and d["zadanie"]["trwa"] is False
    # saldo z cache: zly klucz nie psuje odpowiedzi, wymuszenie odswieza
    cli.saldo = 555
    assert _json(klient.get("/api/stan"))["saldo"]["higgsfield"]["kredyty"] == 1000
    assert _json(klient.get("/api/stan?saldo=1"))["saldo"]["higgsfield"]["kredyty"] == 555


def test_saldo_blad_nie_wywala(klient, cli):
    cli.blad_kredyty = True
    d = _json(klient.get("/api/stan?saldo=1"))
    assert d["saldo"]["higgsfield"]["kredyty"] is None and "padl" in d["saldo"]["higgsfield"]["blad"]
    assert d["konta"]["higgsfield"]["ok"] is False


# ---------------- modelki / pomysly ----------------

def test_nowa_modelka_i_profil(klient):
    d = _json(klient.post("/api/modelki", json={"nazwa": "Alicja", "instagram": "@ala"}))
    assert d["slug"] == "alicja" and baza.aktywna_modelka() == "alicja"
    d = _json(klient.post("/api/profil", json={"opis_stylu": "elegancko", "cechy": "blond, fitness"}))
    assert d["profil"]["cechy"] == ["blond", "fitness"] and d["profil"]["instagram"] == "@ala"
    assert klient.post("/api/modelki", json={"nazwa": ""}).status_code == 400
    assert klient.post("/api/modelki/aktywna", json={"slug": "nie_ma"}).status_code == 400


def test_pomysly_lista_i_edycja(klient, modelka):
    _wrzuc(modelka, "klip.mp4")
    _wrzuc(modelka, "klip.stroj.png")
    _wrzuc(modelka, "tekst.audio.mp3")
    fabryka.skanuj(modelka)
    d = _json(klient.get("/api/pomysly"))
    p = d["pomysly"][0]
    assert p["wariant"] == "B" and p["miniatura_url"].startswith("/api/plik?s=") and p["stroj_url"] and p["wideo_url"] is None
    assert klient.get(p["miniatura_url"]).status_code == 200
    d = _json(klient.patch(f"/api/pomysly/{p['id']}", json={"prompt_higgsfield": "nowy", "status": "blad", "zly_klucz": 1}))
    assert d["pomysl"]["prompt_higgsfield"] == "nowy" and d["pomysl"]["status"] == "blad"
    assert _json(klient.post(f"/api/pomysly/{p['id']}/ponow"))["pomysl"]["status"] == "nowy"
    d = _json(klient.post("/api/pomysly", json={"opis": "pomysl tekstowy", "prompt": "p"}))
    assert _json(klient.get("/api/pomysly"))["pomysly"][1]["wariant"] == "tekst"
    assert klient.delete(f"/api/pomysly/{d['id']}").status_code == 200
    assert klient.delete("/api/pomysly/999").status_code == 400
    assert klient.patch(f"/api/pomysly/{p['id']}", json={"status": "zly"}).status_code == 400


# ---------------- akcje w tle ----------------

def test_akcja_skanuj_i_generuj(klient, modelka, cli):
    _wrzuc(modelka, "a.mp4")
    d = _json(klient.post("/api/akcja", json={"typ": "skanuj"}))
    assert d["zadanie"]["typ"] == "skanuj" and d["zadanie"]["trwa"] in (True, False)
    z = _czekaj_na_zadanie()
    assert z["blad"] is None and z["wynik"]["nowe"] == [1]
    d = _json(klient.get("/api/zadanie?od=0"))
    assert any("a.mp4" in l for l in d["log"]) and d["log_dlugosc"] == len(d["log"])
    d = _json(klient.post("/api/akcja", json={"typ": "koszt"}))
    z = _czekaj_na_zadanie()
    assert z["wynik"]["razem"] == 45
    d = _json(klient.post("/api/akcja", json={"typ": "generuj", "ids": [1]}))
    z = _czekaj_na_zadanie()
    assert z["wynik"]["wygenerowane"] == 1
    p = _json(klient.get("/api/pomysly"))["pomysly"][0]
    assert p["status"] == "gotowe" and p["wideo_url"]
    assert klient.get(p["wideo_url"]).status_code == 200
    assert len(cli.generacje) == 1


def test_akcja_409_gdy_zajete(klient):
    assert panel.konsola.lock.acquire(blocking=False)
    panel.konsola.stan.update({"trwa": True, "typ": "generuj"})
    try:
        odp = klient.post("/api/akcja", json={"typ": "skanuj"})
        assert odp.status_code == 409 and "trwa" in _json(odp)["blad"]
    finally:
        panel.konsola.stan.update({"trwa": False, "typ": None})
        panel.konsola.lock.release()
    assert klient.post("/api/akcja", json={"typ": "nie_ma"}).status_code == 400
    assert klient.post("/api/akcja", json={"typ": "lipsync", "id": 99}).status_code == 400


def test_akcja_blad_zwalnia_konsole(klient, modelka, cli):
    """Pomysl tekstowy bez mode_bez_zrodla: generuj konczy sie bledem, a konsola NIE zostaje zablokowana."""
    pid = baza.dodaj_pomysl(modelka, "tekst", "prompt")
    _json(klient.post("/api/akcja", json={"typ": "generuj", "ids": [pid]}))
    z = _czekaj_na_zadanie()
    assert z["blad"] and "mode_bez_zrodla" in z["blad"]
    assert not panel.konsola.lock.locked()
    d = _json(klient.post("/api/akcja", json={"typ": "skanuj"}))    # nie 409
    assert d["zadanie"]["typ"] == "skanuj"
    _czekaj_na_zadanie()


def test_akcja_stop_i_blad(klient, modelka, cli, monkeypatch):
    for n in ("a.mp4", "b.mp4", "c.mp4"):
        _wrzuc(modelka, n)
    fabryka.skanuj(modelka)
    start = threading.Event()

    def wolne_generuj(model, params=None, media=None, **k):
        start.set()
        panel.konsola.stop.wait(5)
        return {"id": "j", "status": "completed", "result_url": "https://cdn/x.mp4"}
    monkeypatch.setattr(panel.fabryka.hf, "generuj", wolne_generuj)
    import higgsfield_cli
    monkeypatch.setattr(higgsfield_cli, "generuj", wolne_generuj)
    klient.post("/api/akcja", json={"typ": "generuj"})
    assert start.wait(5)
    klient.post("/api/zadanie/stop")
    z = _czekaj_na_zadanie()
    assert z["blad"] and "zatrzymane" in z["blad"]
    assert sum(1 for p in baza.lista_pomyslow(modelka) if p["status"] == "nowy") == 2


# ---------------- ustawienia / pliki ----------------

def test_ustawienia_get_post(klient, modelka):
    d = _json(klient.get("/api/ustawienia"))
    assert d["prompty"]["a"].startswith("PROMPT A") and len(d["referencje"]) == 2 and d["foldery"]["wrzutnia"]
    d = _json(klient.post("/api/ustawienia", json={
        "resolution": "1080p", "autopilot": "true", "autopilot_co_minut": "30", "duration": "",
        "yapper": {"model": "wan-3.0"}, "prompt_a_tekst": "NOWY A", "zdjecia_prompty_tekst": "p1\np2",
        "zdjecia_parametry": {"aspect_ratio": "3:4"}, "generate_audio": "false", "mode_bez_zrodla": "omni_reference"}))
    u = d["ustawienia"]
    assert u["resolution"] == "1080p" and u["autopilot"] is True and u["autopilot_co_minut"] == 30 and u["duration"] is None
    assert u["yapper"]["model"] == "wan-3.0" and u["yapper"]["resolution"] == "720p"      # scalanie slownika
    assert u["generate_audio"] is False and u["mode_bez_zrodla"] == "omni_reference"
    assert baza.prompt_bazowy(modelka) == "NOWY A" and baza.prompt_stroj(modelka).startswith("PROMPT B")
    assert baza.prompty_zdjec(modelka) == ["p1", "p2"]
    assert klient.post("/api/ustawienia", json={"nie_ma": 1}).status_code == 400
    assert klient.post("/api/ustawienia", json={"powtorki": "abc"}).status_code == 400


def test_upload_i_usun(klient, modelka):
    dane = {"typ": "referencja", "pliki": [(io.BytesIO(b"png"), "twarz3.png"), (io.BytesIO(b"x"), "notatka.txt")]}
    d = _json(klient.post("/api/upload", data=dane, content_type="multipart/form-data"))
    assert d["zapisane"] == ["03_twarz3.png"] and d["pominiete"] == ["notatka.txt"]
    assert os.path.isfile(os.path.join(baza.folder_referencji(modelka), "03_twarz3.png"))
    d = _json(klient.post("/api/upload", data={"typ": "zrodlo", "pliki": [(io.BytesIO(b"v"), "nowy klip.mp4")]}, content_type="multipart/form-data"))
    assert d["zapisane"] == ["nowy klip.mp4"] and fabryka.nowe_zrodla(modelka)
    d = _json(klient.post("/api/upload", data={"typ": "audio", "pliki": [(io.BytesIO(b"a"), "../../glos.mp3")]}, content_type="multipart/form-data"))
    assert d["zapisane"] == ["glos.mp3"] and baza.pliki_audio(modelka)
    assert klient.post("/api/upload", data={"typ": "inne"}, content_type="multipart/form-data").status_code == 400
    assert klient.post("/api/pliki/usun", json={"typ": "referencja", "nazwa": "03_twarz3.png"}).status_code == 200
    assert not os.path.isfile(os.path.join(baza.folder_referencji(modelka), "03_twarz3.png"))
    assert klient.post("/api/pliki/usun", json={"typ": "referencja", "nazwa": "03_twarz3.png"}).status_code == 400


def test_plik_tylko_z_dozwolonych_folderow(klient, modelka, tmp_path):
    obcy = tmp_path / "obcy.txt"
    obcy.write_text("tajne")
    assert klient.get(f"/api/plik?s={obcy}").status_code == 404
    assert klient.get("/api/plik?s=/etc/passwd").status_code == 404
    ref = baza.sciezki_referencji(modelka)[0]
    assert klient.get(f"/api/plik?s={ref}").status_code == 200
    # wrzutnia poza projektem tez dozwolona
    przed = tmp_path / "przed"
    przed.mkdir()
    (przed / "k.mp4").write_bytes(b"v")
    assert klient.get(f"/api/plik?s={przed / 'k.mp4'}").status_code == 404
    baza.zapisz_ustawienia(modelka, zrodla_dir=str(przed))
    assert klient.get(f"/api/plik?s={przed / 'k.mp4'}").status_code == 200


# ---------------- konta / modele / glosy ----------------

def test_konta_klucze_i_test(klient, monkeypatch):
    d = _json(klient.get("/api/konta"))
    assert d["konta"]["higgsfield"]["ok"] is True and d["konta"]["sync"]["jest"] is False and d["konta"]["sync"]["jak"]
    d = _json(klient.post("/api/konta", json={"dostawca": "sync", "klucz": "sk_abcdefghijkl"}))
    assert d["konta"]["sync"]["jest"] and d["konta"]["sync"]["maska"] == "sk_a…ijkl"
    assert sekrety.klucz("sync") == "sk_abcdefghijkl"
    assert klient.post("/api/konta", json={"dostawca": "zly", "klucz": "x"}).status_code == 400
    from dostawcy import sync_so, yapper
    monkeypatch.setattr(sync_so, "gotowy", lambda: (True, "dziala"))
    d = _json(klient.post("/api/konta/test", json={"dostawca": "sync"}))
    assert d["dziala"] is True and d["komunikat"] == "dziala"
    assert _json(klient.get("/api/konta"))["konta"]["sync"]["ok"] is True
    monkeypatch.setattr(yapper, "gotowy", lambda: (False, "brak klucza"))
    assert _json(klient.post("/api/konta/test", json={"dostawca": "yapper"}))["dziala"] is False
    d = _json(klient.post("/api/konta", json={"dostawca": "sync", "klucz": ""}))
    assert d["konta"]["sync"]["jest"] is False


def test_modele_i_glosy(klient, monkeypatch):
    import higgsfield_cli
    from dostawcy import sync_so, yapper
    monkeypatch.setattr(higgsfield_cli, "modele", lambda typ=None: [
        {"job_type": "nano_banana_2", "display_name": "Nano Banana Pro", "type": "image"},
        {"job_type": "seedance_2_5", "display_name": "Seedance 2.5", "type": "video"}])
    d = _json(klient.get("/api/modele?dostawca=higgsfield&typ=image"))
    assert d["modele"] == [{"id": "nano_banana_2", "nazwa": "Nano Banana Pro", "typ": "image", "opis": ""}]
    monkeypatch.setattr(yapper, "modele_wideo", lambda: [{"id": "wan-3.0", "name": "WAN 3.0", "processType": "video-generation"}])
    assert _json(klient.get("/api/modele?dostawca=yapper"))["modele"][0]["id"] == "wan-3.0"
    monkeypatch.setattr(sync_so, "modele", lambda: [{"id": "lipsync-2", "name": "lipsync-2", "type": "lipsync"}])
    assert _json(klient.get("/api/modele?dostawca=sync"))["modele"][0]["typ"] == "lipsync"

    def brak():
        from dostawcy import BrakKlucza
        raise BrakKlucza("brak klucza")
    monkeypatch.setattr(sync_so, "glosy", brak)
    odp = klient.get("/api/glosy?dostawca=sync")
    assert odp.status_code == 400 and "brak klucza" in _json(odp)["blad"]
    monkeypatch.setattr(sync_so, "glosy", lambda: [{"id": "v1", "name": "Rachel", "gender": "female"}])
    assert _json(klient.get("/api/glosy?dostawca=sync"))["glosy"] == [{"id": "v1", "nazwa": "Rachel", "typ": "", "opis": "female"}]


# ---------------- zdjecia / lipsync / dziennik / budzet / autopilot ----------------

def test_zdjecia_lipsync_listy(klient, modelka):
    zid = baza.dodaj_zdjecie(modelka, "portret", plik=baza.sciezki_referencji(modelka)[0], koszt=2)
    d = _json(klient.get("/api/zdjecia"))
    assert d["zdjecia"][0]["url"] and d["zdjecia"][0]["prompt"] == "portret"
    assert klient.delete(f"/api/zdjecia/{zid}").status_code == 200 and baza.lista_zdjec(modelka) == []
    lid = baza.dodaj_lipsync(modelka, "/w.mp4", "/a.mp3", "sync", "lipsync-2")
    assert _json(klient.get("/api/lipsync"))["lipsync"][0]["status"] == "nowy"
    assert klient.delete(f"/api/lipsync/{lid}").status_code == 200
    assert klient.delete("/api/lipsync/5").status_code == 400


def test_dziennik_i_budzet(klient, modelka):
    baza.dziennik_zapisz("ok", "cos sie udalo", modelka=modelka)
    baza.dziennik_zapisz("blad", "cos padlo")
    d = _json(klient.get("/api/dziennik?ile=10&typ=blad"))
    assert [w["tekst"] for w in d["wpisy"]] == ["cos padlo"]
    assert len(_json(klient.get("/api/dziennik"))["wpisy"]) >= 2
    d = _json(klient.post("/api/budzet", json={"dostawca": "yapper", "max_kredyty_dziennie": 2000}))
    assert d["dzis"]["yapper"]["limit"] == 2000 and d["dzis"]["higgsfield"]["limit"] == 300
    assert baza.limit_dzienny("yapper") == 2000
    assert klient.post("/api/budzet", json={"max_kredyty_dziennie": "abc"}).status_code == 400


def test_autopilot_wlacz_wylacz(klient):
    d = _json(klient.post("/api/autopilot", json={"wlacz": True}))
    assert d["autopilot"]["wlaczony"] is True
    assert _json(klient.get("/api/stan"))["autopilot"]["wlaczony"] is True
    d = _json(klient.post("/api/autopilot", json={"wlacz": False}))
    panel._autopilot["watek"].join(5)
    assert _json(klient.get("/api/stan"))["autopilot"]["wlaczony"] is False


def test_autopilot_raz_z_panelu(klient, modelka, cli):
    _wrzuc(modelka, "a.mp4")
    klient.post("/api/akcja", json={"typ": "autopilot_raz"})
    z = _czekaj_na_zadanie()
    assert z["blad"] is None and z["wynik"]["nowe"] == 1 and z["wynik"]["wygenerowane"] == 1


def test_strony(klient):
    assert klient.get("/").status_code == 200
    assert klient.get("/widget").status_code == 200


def test_zamknij_konczy_proces(klient, monkeypatch):
    """POST /api/zamknij odpowiada ok i po chwili konczy proces (tu: os._exit podmieniony)."""
    import threading
    wywolane = threading.Event()
    monkeypatch.setattr(panel.os, "_exit", lambda kod: wywolane.set())
    d = _json(klient.post("/api/zamknij"))
    assert d["zamykam"] is True
    assert wywolane.wait(3)


def test_statystyki_i_avatar(klient, modelka, cli):
    _wrzuc(modelka, "a.mp4")
    fabryka.skanuj(modelka)
    klient.post("/api/akcja", json={"typ": "generuj"})
    _czekaj_na_zadanie()
    d = _json(klient.get("/api/statystyki?dni=7"))
    assert len(d["dni"]) == 7 and d["dni"][-1]["rolki"] == 1 and d["razem"]["kredyty"]["higgsfield"] == 45
    s = _json(klient.get("/api/stan"))
    m = s["modelki"][0]
    assert m["rolki_dzis"] == 1 and m["autopilot_stan"]["pauza"] is None and m["avatar_url"].startswith("/api/plik")
    d = _json(klient.post("/api/akcja", json={"typ": "podglad", "id": 1}))
    _czekaj_na_zadanie()
