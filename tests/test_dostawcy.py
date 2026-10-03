# -*- coding: utf-8 -*-
"""Dostawcy yapper.so i sync.so na zamockowanym HTTP, sekrety, lipsync, zdjecia, autopilot."""
import json
import os

import pytest

import baza
import fabryka
import lipsync
import sekrety
import zdjecia
import autopilot
import dostawcy
from dostawcy import http, sync_so, yapper


# ---------------- sekrety ----------------

def test_sekrety_plik_i_env(dane, monkeypatch):
    assert sekrety.klucz("yapper") is None
    assert sekrety.zapisz_klucz("yapper", "yk_1234567890abcdef") is True
    assert sekrety.klucz("yapper") == "yk_1234567890abcdef"
    assert sekrety.zamaskuj(sekrety.klucz("yapper")) == "yk_1…cdef"
    assert sekrety.stan()["yapper"]["jest"] and not sekrety.stan()["sync"]["jest"]
    monkeypatch.setenv("SYNC_API_KEY", "ze_srodowiska")
    assert sekrety.klucz("sync") == "ze_srodowiska" and sekrety.stan()["sync"]["z_env"]
    assert sekrety.zapisz_klucz("yapper", "") is False
    assert sekrety.klucz("yapper") is None
    with pytest.raises(ValueError):
        sekrety.zapisz_klucz("nieznany", "x")
    # plik nigdy nie trafia do repo
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".gitignore")) as f:
        assert "klucze.json" in f.read()


# ---------------- udawany HTTP ----------------

class UdawanyHTTP:
    """Zbiera wywolania i odpowiada wg prostych regul (lista odpowiedzi per (metoda, koncowka sciezki))."""

    def __init__(self):
        self.wywolania = []
        self.odpowiedzi = {}
        self.pobrane = []

    def ustaw(self, metoda, koncowka, *odpowiedzi):
        self.odpowiedzi[(metoda, koncowka)] = list(odpowiedzi)

    def _odp(self, metoda, url):
        for (m, k), lista in self.odpowiedzi.items():
            if m == metoda and url.endswith(k) and lista:
                return lista.pop(0) if len(lista) > 1 else lista[0]
        raise http.BladHTTP(404, json.dumps({"error": {"code": "not_found", "message": url}}), url)

    def zapytanie(self, metoda, url, dane=None, naglowki=None, timeout=60, surowe_cialo=None, typ_ciala=None, powtorki=3):
        self.wywolania.append((metoda, url, dane, naglowki))
        odp = self._odp(metoda, url)
        if isinstance(odp, Exception):
            raise odp
        return odp

    def multipart(self, url, pola=None, pliki=None, naglowki=None, timeout=900):
        self.wywolania.append(("MULTIPART", url, {"pola": pola, "pliki": pliki}, naglowki))
        return self._odp("POST", url)

    def wyslij_plik(self, url, sciezka, naglowki=None, metoda="PUT", timeout=900):
        self.wywolania.append((metoda, url, sciezka, naglowki))
        return ""

    def pobierz(self, url, sciezka, naglowki=None, timeout=600):
        os.makedirs(os.path.dirname(sciezka), exist_ok=True)
        with open(sciezka, "wb") as f:
            f.write(b"plik")
        self.pobrane.append((url, sciezka))
        return sciezka


@pytest.fixture
def udawany_http(monkeypatch):
    u = UdawanyHTTP()
    for nazwa in ("zapytanie", "multipart", "wyslij_plik", "pobierz"):
        monkeypatch.setattr(http, nazwa, getattr(u, nazwa))
    return u


# ---------------- yapper ----------------

def test_yapper_bez_klucza(dane):
    with pytest.raises(dostawcy.BrakKlucza):
        yapper.saldo()
    assert yapper.gotowy()[0] is False


def test_yapper_saldo_modele_naglowki(dane, udawany_http):
    sekrety.zapisz_klucz("yapper", "yk_test")
    udawany_http.ustaw("GET", "/credits", {"totalCredits": 5000, "usedCredits": 1240, "availableCredits": 3760})
    udawany_http.ustaw("GET", "/models", {"models": [{"id": "wan-3.0", "name": "WAN 3.0", "processType": "video-generation"},
                                                      {"id": "gpt-image-2", "name": "GPT Image", "processType": "image-generation"}]})
    assert yapper.saldo() == 3760
    assert yapper.gotowy() == (True, "3760 kr dostepnych")
    assert udawany_http.wywolania[0][3]["Authorization"] == "Bearer yk_test"
    assert [m["id"] for m in yapper.modele_wideo()] == ["wan-3.0"]


def test_yapper_koszt_generuj_z_uploadem_i_cache(modelka, udawany_http):
    sekrety.zapisz_klucz("yapper", "yk_test")
    baza.zapisz_ustawienia(modelka, dostawca="yapper", yapper={"model": "wan-3.0", "resolution": "1080p"})
    zrodlo = os.path.join(baza.folder_zrodel(modelka), "klip.mp4")
    open(zrodlo, "wb").write(b"mp4")
    p = {"id": 1, "prompt_higgsfield": "tancz", "zrodlo": zrodlo, "info_zrodla": {"czas": 6.0}}
    z = fabryka.zlecenie(modelka, p)
    udawany_http.ustaw("POST", "/assets/uploads", {"uploadUrl": "https://s3/put", "headers": {"x-a": "1"}, "completeUrl": "/api/v1/assets/uploads/u1/complete"})
    udawany_http.ustaw("POST", "/complete", {"asset": {"id": "asset_1"}})
    udawany_http.ustaw("POST", "/processes", {"creditsUsed": 300},                       # dryRun
                       {"id": "proc_1", "status": "queued"})                               # prawdziwy
    udawany_http.ustaw("GET", "/processes/proc_1", {"id": "proc_1", "status": "processing"},
                       {"id": "proc_1", "status": "completed", "creditsUsed": 300,
                        "outputs": [{"type": "video", "url": "https://cdn/wynik.mp4"}]})
    assert yapper.koszt(z) == 300
    # 3 pliki (2 referencje + zrodlo) wgrane raz, dryRun z assetId
    dry = [w for w in udawany_http.wywolania if w[0] == "POST" and w[1].endswith("/processes")][0]
    assert dry[2]["dryRun"] is True and dry[2]["model"] == "wan-3.0"
    assert dry[2]["input"]["referenceVideos"] == [{"assetId": "asset_1"}]
    assert len(dry[2]["input"]["referenceImages"]) == 2
    assert dry[2]["input"]["resolution"] == 1080 and dry[2]["input"]["videoLength"] == 6
    uploady = [w for w in udawany_http.wywolania if w[0] == "PUT"]
    assert len(uploady) == 3
    wynik = yapper.generuj(z, timeout="1m")
    assert wynik["status"] == "completed" and wynik["urls"] == ["https://cdn/wynik.mp4"] and wynik["job_id"] == "proc_1"
    # cache: zadnych nowych uploadow
    assert len([w for w in udawany_http.wywolania if w[0] == "PUT"]) == 3
    realny = [w for w in udawany_http.wywolania if w[0] == "POST" and w[1].endswith("/processes")][1]
    assert "dryRun" not in realny[2] and realny[3]["Idempotency-Key"].startswith("rolki-")


def test_yapper_blad_kredytow(dane, udawany_http):
    sekrety.zapisz_klucz("yapper", "yk_test")
    udawany_http.ustaw("POST", "/processes", http.BladHTTP(402, json.dumps({"error": {"code": "insufficient_credits", "message": "no credits"}})))
    z = {"slug": None, "prompt": "x", "images": [], "video": None, "yapper": {"model": "wan-3.0"}, "resolution": "720p", "duration": 5}
    with pytest.raises(dostawcy.BladDostawcy, match="insufficient_credits"):
        yapper.koszt(z)


def test_fabryka_generuje_przez_yapper(modelka, monkeypatch):
    """Caly obieg fabryki z dostawca=yapper na udawanym module yapper (bez HTTP)."""
    baza.zapisz_ustawienia(modelka, dostawca="yapper", mediatool=False, yapper={"model": "wan-3.0", "min_kredyty": 500, "max_kredyty_na_rolke": 600})
    baza.zapisz_limit_dzienny(1000, "yapper")
    stan = {"saldo": 2000, "generacje": []}
    monkeypatch.setattr(yapper, "saldo", lambda: stan["saldo"])
    monkeypatch.setattr(yapper, "koszt", lambda z: 300)

    def generuj(z, timeout="30m", log=None):
        stan["generacje"].append(z)
        stan["saldo"] -= 300
        return {"job_id": "proc_9", "status": "completed", "urls": ["https://cdn/w.mp4"], "blad": "", "surowe": {}}
    monkeypatch.setattr(yapper, "generuj", generuj)
    monkeypatch.setattr(yapper, "pobierz", lambda url, sciezka: (open(sciezka, "wb").write(b"x"), sciezka)[1])
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 5.0, "szer": 720, "wys": 1280, "fps": 30})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    open(os.path.join(baza.folder_zrodel(modelka), "a.mp4"), "wb").write(b"mp4")
    fabryka.skanuj(modelka)
    w = fabryka.generuj(modelka)
    assert w["wygenerowane"] == 1
    p = baza.pomysl(modelka, 1)
    assert p["status"] == "gotowe" and p["dostawca"] == "yapper" and p["koszt"] == 300
    assert baza.wydano_dzis("yapper") == 300 and baza.wydano_dzis("higgsfield") == 0
    assert stan["generacje"][0]["mode"] == "video_edit" and stan["generacje"][0]["video"].endswith("a.mp4")
    # bezpiecznik yappera (nie Higgsfielda): druga rolka zostawilaby 1400 >= 500, ale 300 > max 250 -> pominieta
    baza.zapisz_ustawienia(modelka, yapper={"max_kredyty_na_rolke": 250})
    open(os.path.join(baza.folder_zrodel(modelka), "b.mp4"), "wb").write(b"mp4")
    fabryka.skanuj(modelka)
    assert fabryka.generuj(modelka)["pominiete"] == [2]


def test_pomysl_tekstowy_z_mode_bez_zrodla(bez_mediatool_modelka, cli):
    slug = bez_mediatool_modelka
    pid = baza.dodaj_pomysl(slug, "spacer po plazy", "prompt tekstowy")
    assert fabryka.kandydaci(slug) == []                      # video_edit wymaga zrodla
    baza.zapisz_ustawienia(slug, mode_bez_zrodla="omni_reference")
    assert [p["id"] for p in fabryka.kandydaci(slug)] == [pid]
    w = fabryka.generuj(slug)
    assert w["wygenerowane"] == 1
    model, params, media = cli.generacje[0]
    assert params["mode"] == "omni_reference" and "video" not in media and len(media["image"]) == 2


@pytest.fixture
def bez_mediatool_modelka(modelka):
    baza.zapisz_ustawienia(modelka, mediatool=False)
    return modelka


# ---------------- sync.so ----------------

def test_sync_bez_klucza(dane):
    assert sync_so.gotowy()[0] is False
    with pytest.raises(dostawcy.BrakKlucza):
        sync_so.modele()


def test_sync_generuj_multipart_i_poll(dane, udawany_http, tmp_path):
    sekrety.zapisz_klucz("sync", "sk_test")
    wideo, audio = tmp_path / "w.mp4", tmp_path / "a.mp3"
    wideo.write_bytes(b"v"); audio.write_bytes(b"a")
    udawany_http.ustaw("POST", "/generate", {"id": "gen_1", "status": "PENDING"})
    udawany_http.ustaw("GET", "/generate/gen_1", {"id": "gen_1", "status": "PROCESSING"},
                       {"id": "gen_1", "status": "COMPLETED", "outputUrl": "https://cdn/out.mp4", "outputDuration": 6.0})
    w = sync_so.generuj(str(wideo), str(audio), model="lipsync-2", opcje={"sync_mode": "loop"})
    assert w["status"] == "completed" and w["url"] == "https://cdn/out.mp4" and w["sekundy"] == 6.0
    mp = [x for x in udawany_http.wywolania if x[0] == "MULTIPART"][0]
    assert mp[2]["pliki"] == {"video": str(wideo), "audio": str(audio)}
    assert mp[2]["pola"]["model"] == "lipsync-2" and json.loads(mp[2]["pola"]["options"]) == {"sync_mode": "loop"}
    assert mp[3]["x-api-key"] == "sk_test"
    assert sync_so.koszt_szacunkowy(10, "lipsync-2") == 50


def test_sync_generuj_url_json_i_blad(dane, udawany_http):
    sekrety.zapisz_klucz("sync", "sk_test")
    udawany_http.ustaw("POST", "/generate", {"id": "gen_2", "status": "PENDING"})
    udawany_http.ustaw("GET", "/generate/gen_2", {"id": "gen_2", "status": "FAILED", "error": "no face", "errorCode": "face_not_found"})
    w = sync_so.generuj("https://x/w.mp4", "https://x/a.mp3")
    assert w["status"] == "failed" and "face_not_found" in w["blad"] and w["url"] is None
    post = [x for x in udawany_http.wywolania if x[0] == "POST"][0]
    assert post[2]["input"] == [{"type": "video", "url": "https://x/w.mp4"}, {"type": "audio", "url": "https://x/a.mp3"}]
    udawany_http.ustaw("POST", "/analyze/cost", [{"estimatedFrameCount": 150, "estimatedGenerationCost": 0.3}])
    assert sync_so.koszt("https://x/w.mp4", "https://x/a.mp3") == 30
    udawany_http.ustaw("POST", "/tts", {"id": "t1", "url": "https://cdn/t.mp3", "duration": 2.5})
    assert sync_so.tts("czesc", "voice1")["url"] == "https://cdn/t.mp3"


def test_sync_opis_bledu_401(dane, udawany_http):
    sekrety.zapisz_klucz("sync", "zly")
    udawany_http.ustaw("GET", "/models", http.BladHTTP(401, "Unauthorized"))
    ok, kom = sync_so.gotowy()
    assert ok is False and "401" in kom


# ---------------- lipsync.zrob ----------------

def test_lipsync_zrob_sync(bez_mediatool_modelka, monkeypatch, tmp_path):
    slug = bez_mediatool_modelka
    sekrety.zapisz_klucz("sync", "sk")
    wideo = os.path.join(baza.folder_gotowych(slug), "001_a.mp4")
    open(wideo, "wb").write(b"v")
    audio = os.path.join(baza.folder_audio(slug), "glos.mp3")
    open(audio, "wb").write(b"a")
    monkeypatch.setattr(sync_so, "generuj", lambda w, a, model, opcje, log=None: {"job_id": "g1", "status": "completed", "url": "https://cdn/o.mp4", "blad": "", "sekundy": 8.0})
    monkeypatch.setattr(sync_so, "pobierz", lambda url, sciezka: (open(sciezka, "wb").write(b"o"), sciezka)[1])
    pid = baza.dodaj_pomysl(slug, "x", "p")
    cel = lipsync.zrob(slug, wideo, audio, pomysl_id=pid)
    assert cel.endswith("001_a_lipsync.mp4") and os.path.isfile(cel)
    l = baza.lista_lipsync(slug)[0]
    assert l["status"] == "gotowe" and l["koszt"] == 40 and l["job_id"] == "g1"
    assert baza.pomysl(slug, pid)["lipsync_plik"] == cel
    assert baza.wydano_dzis("sync") == 40


def test_lipsync_blad_zapisany(bez_mediatool_modelka, monkeypatch):
    slug = bez_mediatool_modelka
    wideo = os.path.join(baza.folder_gotowych(slug), "001_a.mp4"); open(wideo, "wb").write(b"v")
    audio = os.path.join(baza.folder_audio(slug), "g.mp3"); open(audio, "wb").write(b"a")

    def padl(*a, **k):
        raise dostawcy.BladDostawcy("sync.so 402: plan")
    monkeypatch.setattr(sync_so, "generuj", padl)
    with pytest.raises(dostawcy.BladDostawcy):
        lipsync.zrob(slug, wideo, audio)
    assert baza.lista_lipsync(slug)[0]["status"] == "blad"


def test_lipsync_auto_po_generacji(bez_mediatool_modelka, cli, monkeypatch):
    """<nazwa>.audio.mp3 obok zrodla + lipsync_auto=true -> po RECZNEJ generacji automatyczny lipsync.
    Domyslnie lipsync_auto jest wylaczone, a autopilot (generuj(lipsync=False)) nigdy go nie robi."""
    slug = bez_mediatool_modelka
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 5.0, "szer": 720, "wys": 1280, "fps": 30})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    assert baza.USTAWIENIA_DOMYSLNE["lipsync_auto"] is False
    baza.zapisz_ustawienia(slug, lipsync_auto=True)
    zr = baza.folder_zrodel(slug)
    open(os.path.join(zr, "mowa.mp4"), "wb").write(b"v")
    open(os.path.join(zr, "mowa.audio.mp3"), "wb").write(b"a")
    wywolania = []
    monkeypatch.setattr(lipsync, "zrob", lambda s, w, a, pomysl_id=None, log=None, **k: wywolania.append((w, a)) or "/x/lip.mp4")
    fabryka.skanuj(slug)
    assert baza.pomysl(slug, 1)["audio"].endswith("mowa.audio.mp3")
    fabryka.generuj(slug)
    assert len(wywolania) == 1 and wywolania[0][0].endswith("001_mowa.mp4") and wywolania[0][1].endswith("mowa.audio.mp3")
    # autopilot: lipsync_auto wlaczone, glos jest - i tak bez lipsyncu
    open(os.path.join(zr, "mowa2.mp4"), "wb").write(b"v"); open(os.path.join(zr, "mowa2.audio.mp3"), "wb").write(b"a")
    fabryka.skanuj(slug); fabryka.generuj(slug, lipsync=False)
    assert len(wywolania) == 1 and baza.pomysl(slug, 2)["status"] == "gotowe"
    import autopilot
    monkeypatch.setattr(fabryka, "_plik_sie_zmienia", lambda p, odstep=0: False)
    open(os.path.join(zr, "mowa3.mp4"), "wb").write(b"v"); open(os.path.join(zr, "mowa3.audio.mp3"), "wb").write(b"a")
    assert autopilot.przebieg(slug)["wygenerowane"] == 1 and len(wywolania) == 1
    baza.zapisz_ustawienia(slug, lipsync_auto=False)
    open(os.path.join(zr, "mowa4.mp4"), "wb").write(b"v"); open(os.path.join(zr, "mowa4.audio.mp3"), "wb").write(b"a")
    fabryka.skanuj(slug); fabryka.generuj(slug)
    assert len(wywolania) == 1


# ---------------- zdjecia ----------------

def test_zdjecia_generuj(modelka, cli):
    baza.zapisz_ustawienia(modelka, zdjecia_model="nano_banana_2", zdjecia_parametry={"aspect_ratio": "3:4"})
    baza.zapisz_prompt(modelka, "zdjecia.txt", "# komentarz\nselfie na plazy\nkawa w kawiarni\n")
    cli.cena = 10
    w = zdjecia.generuj(modelka, ile=3)
    assert w["zrobione"] == 3 and len(w["pliki"]) == 3
    model, params, media = cli.generacje[0]
    assert model == "nano_banana_2" and params["prompt"] == "selfie na plazy" and params["aspect_ratio"] == "3:4"
    assert len(media["image"]) == 2
    assert [g[1]["prompt"] for g in cli.generacje] == ["selfie na plazy", "kawa w kawiarni", "selfie na plazy"]   # w kolko
    assert len(baza.zdjecia_z_dnia(modelka)) == 3 and baza.wydano_dzis() == 30
    assert all(os.path.isfile(z["plik"]) for z in baza.lista_zdjec(modelka))


def test_zdjecia_bez_modelu_i_bezpiecznik(modelka, cli):
    w = zdjecia.generuj(modelka, ile=1, prompt="x")
    assert w["zrobione"] == 0 and "zdjecia_model" in w["stop"]
    baza.zapisz_ustawienia(modelka, zdjecia_model="nano_banana_2")
    cli.saldo = 205; cli.cena = 10
    w = zdjecia.generuj(modelka, ile=1, prompt="x")
    assert w["stop"] == "min_kredyty" and cli.generacje == []


# ---------------- autopilot ----------------

def test_autopilot_przebieg(bez_mediatool_modelka, cli, monkeypatch):
    slug = bez_mediatool_modelka
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 5.0, "szer": 720, "wys": 1280, "fps": 30})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    monkeypatch.setattr(fabryka, "_plik_sie_zmienia", lambda p, odstep=0: False)
    baza.zapisz_ustawienia(slug, autopilot=True, autopilot_max_rolek_dziennie=2, zdjecia_model="nano_banana_2", zdjecia_dziennie=1)
    baza.zapisz_prompt(slug, "zdjecia.txt", "portret\n")
    baza.dodaj_teksty(slug, ["podpis 1", "podpis 2"])
    for n in ("a.mp4", "b.mp4", "c.mp4"):
        open(os.path.join(baza.folder_zrodel(slug), n), "wb").write(b"v")
    assert autopilot.modelki_z_autopilotem() == [slug]
    w = autopilot.przebieg_wszystkich()[0]
    assert w["nowe"] == 3 and w["wygenerowane"] == 2 and w["zdjecia"] == 1
    assert w["stop"] == "limit rolek w tym przebiegu (2)"
    assert baza.pomysl(slug, 3)["status"] == "nowy"
    assert all(baza.pomysl(slug, i).get("podpis") for i in (1, 2))
    # drugi przebieg tego samego dnia: limit rolek wyczerpany, zdjecie juz jest
    w2 = autopilot.przebieg_wszystkich()[0]
    assert w2["wygenerowane"] == 0 and w2["stop"] == "max rolek dziennie" and w2["zdjecia"] == 0
    assert autopilot.odstep_sekund([slug]) == 15 * 60


def test_autopilot_bez_modelek(dane):
    assert autopilot.modelki_z_autopilotem() == []
    assert autopilot.przebieg_wszystkich() == []
