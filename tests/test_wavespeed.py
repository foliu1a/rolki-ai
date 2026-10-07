# -*- coding: utf-8 -*-
"""WaveSpeedAI (dostawcy/wavespeed.py) na udawanym HTTP z DOKLADNYMI adresami - bez sieci, bez klucza, bez pieniedzy:
saldo w centach, upload (bilet -> PUT bez klucza, stary multipart), cennik + darmowa wycena API, cialo zapytania (prompt @Image N,
oryginalny dzwiek, rozdzielczosc wg dlugosci), zlec/sprawdz/pobierz, moderacja = NSFW, znajdz po przerwanym wysylaniu, fabryka:
odmowa bez dziennego limitu, jedno wyslanie mimo bledow, krok zapas_nsfw, panel (Konta, modele, budzet, diagnoza)."""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

import baza
import dostawcy
import fabryka
import sekrety
from dostawcy import http, wavespeed
from test_dostawcy import UdawanyHTTP

WS = "https://api.wavespeed.ai/api/v3"
TURBO = "bytedance/seedance-2.5/video-edit-turbo"
WAN = "alibaba/wan-3.0/reference-to-video"
WAN_PRIME = "alibaba/wan-3.0-prime/reference-to-video"
SUBMIT = f"{WS}/{TURBO}"
PROMPT_WAN = "Recreate the reference video, replacing the woman with the woman from the reference photos."


class HTTPWaveSpeed(UdawanyHTTP):
    """UdawanyHTTP + zapis `powtorki` kazdego zapytania + automatyczne bilety uploadu (download_url z nazwy pliku)."""

    def __init__(self):
        super().__init__()
        self.powtorki = []

    def zapytanie(self, metoda, url, dane=None, naglowki=None, timeout=60, surowe_cialo=None, typ_ciala=None, powtorki=3):
        self.powtorki.append((metoda, url, powtorki))
        if metoda == "POST" and url == WS + "/media/uploads" and (metoda, url) not in self.odpowiedzi:
            self.wywolania.append((metoda, url, dane, naglowki))
            n = dane["filename"]
            return {"code": 200, "message": "success", "data": {
                "type": "video" if n.endswith(".mp4") else "image", "download_url": f"https://media.wavespeed.example/{n}",
                "filename": n, "size": dane["size"], "upload": {
                    "method": "PUT", "url": f"https://storage.example/up/{n}?X-Sig=abc",
                    "headers": {"Content-Type": dane["content_type"], "If-None-Match": "*"}, "expires_at": "2026-10-14T00:00:00Z"}}}
        return super().zapytanie(metoda, url, dane, naglowki, timeout, surowe_cialo, typ_ciala, powtorki)

    def submity(self, model=TURBO):
        return [w for w in self.wywolania if w[0] == "POST" and w[1] == f"{WS}/{model}"]


@pytest.fixture
def ws(monkeypatch):
    u = HTTPWaveSpeed()
    for nazwa in ("zapytanie", "multipart", "wyslij_plik", "pobierz"):
        monkeypatch.setattr(http, nazwa, getattr(u, nazwa))
    return u


@pytest.fixture(autouse=True)
def bez_ffmpeg(monkeypatch):
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 6.0, "szer": 720, "wys": 1280, "fps": 30.0})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    monkeypatch.setattr(fabryka, "_plik_sie_zmienia", lambda p, odstep=0: False)


def _koperta(dane, code=200):
    return {"code": code, "message": "success", "data": dane}


def _saldo(u, usd=10.0):
    u.ustaw("GET", WS + "/balance", _koperta({"balance": usd}))


def _pred(pid, status="created", **pola):
    return _koperta(dict({"id": pid, "model": TURBO, "status": status, "outputs": [], "error": "",
                          "urls": {"get": f"{WS}/predictions/{pid}/result"}, "created_at": "2026-10-07T10:00:00.123456789Z"}, **pola))


def _gotowa(pid):
    return _pred(pid, "completed", outputs=[f"https://cdn.wavespeed.example/out/{pid}.mp4"], timings={"inference": 52000})


def _wrzuc(slug, nazwa="a.mp4"):
    p = os.path.join(baza.folder_zrodel(slug), nazwa)
    open(p, "wb").write(b"mp4-dane")
    return p


@pytest.fixture
def slug(modelka):
    """Persona robiaca rolki na WaveSpeed (Seedance 2.5 Edit Turbo): klucz, limit dzienny $10 (1000 c), bez Media Tool."""
    sekrety.zapisz_klucz("wavespeed", "ws_test_klucz_123456")
    baza.zapisz_ustawienia(modelka, dostawca="wavespeed", mediatool=False, wavespeed={"model": TURBO})
    baza.zapisz_limit_dzienny(1000, "wavespeed")
    return modelka


# ---------------- konto, klucz, adresy ----------------

def test_bez_klucza_saldo_odmawia_a_cennik_dziala(modelka, ws):
    with pytest.raises(dostawcy.BrakKlucza):
        wavespeed.saldo()
    assert wavespeed.gotowy()[0] is False and ws.wywolania == []
    z = {"slug": modelka, "prompt": "P @[Image 1](image_1)", "video": _wrzuc(modelka), "video_czas": 10.03, "images": [],
         "resolution": "1080p", "wavespeed": {"model": TURBO}}
    assert wavespeed.koszt(z) == 260 and ws.wywolania == []          # bez klucza: sam cennik, zero zapytan
    assert "cennika" in wavespeed.opis_wyceny()


def test_saldo_w_centach_i_naglowek(dane, ws, monkeypatch):
    sekrety.zapisz_klucz("wavespeed", "ws_test_klucz_123456")
    _saldo(ws, 12.34)
    assert wavespeed.saldo() == 1234
    metoda, url, _, naglowki = ws.wywolania[0]
    assert (metoda, url) == ("GET", WS + "/balance") and naglowki == {"Authorization": "Bearer ws_test_klucz_123456"}
    assert wavespeed.gotowy() == (True, "klucz dziala, saldo $12.34")
    _saldo(ws, 0)
    assert "doladuj" in wavespeed.gotowy()[1]
    ws.ustaw("GET", WS + "/balance", http.BladHTTP(401, json.dumps({"code": 401, "message": "Invalid API key", "data": None})))
    ok, info = wavespeed.gotowy()
    assert ok is False and "401" in info and "klucz" in info
    # zmienna srodowiskowa wygrywa z plikiem kluczy
    monkeypatch.setenv("WAVESPEED_API_KEY", "z_env_abcdefgh")
    assert sekrety.klucz("wavespeed") == "z_env_abcdefgh" and sekrety.stan()["wavespeed"]["z_env"]


def test_klucz_api_tylko_do_wavespeed():
    with pytest.raises(dostawcy.BladDostawcy, match="spoza api.wavespeed.ai"):
        wavespeed._url("https://zly.example/api/v3/balance")
    assert wavespeed._url("/balance") == WS + "/balance"
    assert wavespeed._url(f"/{TURBO}") == SUBMIT
    assert wavespeed._url("/api/v3/predictions/x/result") == WS + "/predictions/x/result"


# ---------------- upload ----------------

def test_upload_bilet_put_bez_klucza_i_cache(slug, ws):
    plik = _wrzuc(slug)
    url = wavespeed.wgraj(slug, plik)
    assert url == "https://media.wavespeed.example/a.mp4"
    bilet, put = ws.wywolania[0], ws.wywolania[1]
    assert bilet[:2] == ("POST", WS + "/media/uploads")
    assert bilet[2] == {"filename": "a.mp4", "size": os.path.getsize(plik), "content_type": "video/mp4"}
    assert put[:3] == ("PUT", "https://storage.example/up/a.mp4?X-Sig=abc", plik)
    assert put[3] == {"Content-Type": "video/mp4", "If-None-Match": "*"}                 # naglowki biletu 1:1, BEZ klucza API
    ile = len(ws.wywolania)
    assert wavespeed.wgraj(slug, plik) == url and len(ws.wywolania) == ile               # z cache
    # po 6 dniach (WaveSpeed trzyma pliki 7) - wgrywamy jeszcze raz
    cache_plik = os.path.join(baza.folder_modelki(slug), "uploady_wavespeed.json")
    cache = json.load(open(cache_plik, encoding="utf-8"))
    for wpis in cache.values():
        wpis["czas"] = time.time() - 7 * 24 * 3600
    json.dump(cache, open(cache_plik, "w", encoding="utf-8"))
    wavespeed.wgraj(slug, plik)
    assert len(ws.posty(WS + "/media/uploads")) == 2


def test_upload_stary_multipart_gdy_bilet_niedostepny(slug, ws):
    plik = _wrzuc(slug, "b.mp4")
    ws.ustaw("POST", WS + "/media/uploads", http.BladHTTP(404, json.dumps({"code": 404, "message": "not found"})))
    ws.ustaw("POST", WS + "/media/upload/binary", _koperta({"download_url": "https://media.wavespeed.example/legacy/b.mp4"}))
    assert wavespeed.wgraj(slug, plik) == "https://media.wavespeed.example/legacy/b.mp4"
    mp = [w for w in ws.wywolania if w[0] == "MULTIPART"][0]
    assert mp[1] == WS + "/media/upload/binary" and mp[2]["pliki"] == {"file": plik}
    assert mp[3]["Authorization"].startswith("Bearer ")
    with pytest.raises(dostawcy.BladDostawcy, match="format"):
        wavespeed.wgraj(slug, os.path.join(baza.folder_zrodel(slug), "x.txt"))


# ---------------- cennik i wycena ----------------

def _z(slug, czas=6.0, model=TURBO, res=None, **wav):
    p = {"id": 1, "prompt_higgsfield": "PROMPT A @[Image 1](image_1) @[Image 2](image_2)", "zrodlo": _wrzuc(slug),
         "info_zrodla": {"czas": czas}}
    baza.zapisz_ustawienia(slug, wavespeed=dict({"model": model}, **wav))
    z = fabryka.zlecenie(slug, p)
    if res:
        z["resolution"] = res
    return z


def test_cennik_modeli(slug):
    sz = wavespeed.szacunek
    assert sz(_z(slug, 10.03))["rozdzielczosc"] == "720p"              # zasada fabryki: > 8 s -> 720p ($2.40)
    z10 = _z(slug, 10.03, res="1080p")                                 # porownanie cen: 10 s klip 1080p = $2.60
    assert sz(z10) == {"c": 260, "wejscie_s": 10, "wyjscie_s": 10, "rozdzielczosc": "1080p", "model": TURBO}
    assert sz(_z(slug, 10.03, res="720p"))["c"] == 240
    assert sz(_z(slug, 6.04))["c"] == 156 and _z(slug, 6.04)["resolution"] == "1080p"   # 6 s -> 1080p: 12x11 + 6x4
    assert sz(_z(slug, 15.0))["c"] == 360                              # 15 s -> 720p: 30x11 + 15x2
    assert sz(_z(slug, 20.0))["c"] == 360                              # Turbo przyjmuje max 15 s (reszte przytniemy)
    assert sz(_z(slug, 4.0, res="480p"))["rozdzielczosc"] == "720p"     # Turbo nie ma 480p
    assert sz(_z(slug, 10.0, model="bytedance/seedance-2.5/video-edit", res="1080p"))["c"] == 1100
    assert sz(_z(slug, 10.0, model="bytedance/seedance-2.5/video-edit", res="480p"))["c"] == 220
    wan = sz(_z(slug, 6.04, model=WAN))                                # ref 7 s (w gore) + wyjscie 6 s, 1080p 20 c/s
    assert (wan["wejscie_s"], wan["wyjscie_s"], wan["c"]) == (7, 6, 260)
    assert sz(_z(slug, 15.0, model=WAN_PRIME))["c"] == 450               # (15 + 15) x 15 c (720p)
    z = _z(slug, 6.0)
    z["video_czas"] = None                                             # nieznana dlugosc -> najdrozszy przypadek
    assert sz(z)["c"] == 15 * 2 * 11 + 15 * 4
    assert wavespeed.stawki_za_sekunde(TURBO) == {"480p": 24, "720p": 24, "1080p": 26}
    with pytest.raises(dostawcy.BladDostawcy, match="nie znam modelu"):
        sz(_z(slug, 6.0, model="cos/innego"))


def test_wycena_api_jest_sprawdzana_ale_cennik_to_podloga(slug, ws):
    z = _z(slug, 6.0)                                                  # cennik: 156 c
    ws.ustaw("POST", WS + "/model/price", _koperta({"model_id": TURBO, "price": 1.56, "discounted_price": 1.40, "discount_rate": 90,
                                                   "currency": "USD"}))
    w = wavespeed.wycena(z)
    assert (w["c"], w["cennik"], w["api"], w["zrodlo"]) == (156, 156, 140, "cennik")
    cialo = ws.posty(WS + "/model/price")[0][2]
    assert cialo["model_id"] == TURBO and cialo["inputs"]["video"] == "https://media.wavespeed.example/a.mp4"
    assert cialo["inputs"]["reference_images"] == ["https://media.wavespeed.example/01_twarz.png",
                                                    "https://media.wavespeed.example/02_sylwetka.jpg"]
    ws.ustaw("POST", WS + "/model/price", _koperta({"model_id": TURBO, "price": 3.10, "discounted_price": 3.10, "discount_rate": 100}))
    assert wavespeed.koszt(z) == 310 and "wycena WaveSpeed $3.10" in wavespeed.opis_wyceny()
    ws.ustaw("POST", WS + "/model/price", _koperta({"model_id": TURBO, "price": 0.45, "discounted_price": 0.0, "discount_rate": 0}))
    assert wavespeed.koszt(z) == 156                                   # 0 z API nie obniza bezpiecznika
    ws.ustaw("POST", WS + "/model/price", http.BladHTTP(400, json.dumps({"code": 4006, "message": "Media Duration Unavailable"})))
    w = wavespeed.wycena(z)
    assert w["c"] == 156 and w["api"] is None and "4006" in w["api_blad"]
    assert not ws.submity()                                            # wycena nigdy nie wysyla zadania


# ---------------- cialo zapytania ----------------

def test_cialo_seedance_prompt_dzwiek_rozdzielczosc(slug):
    model, cialo, m, sz = wavespeed.przygotuj(_z(slug, 6.0))
    assert model == TURBO
    assert cialo["prompt"] == "PROMPT A @Image 1 @Image 2"            # @[Image N](image_N) -> @Image N
    assert cialo["generate_audio"] is False                            # oryginalny dzwiek filmiku zostaje
    assert cialo["resolution"] == "1080p" and cialo["video"].endswith("a.mp4")
    assert [os.path.basename(x) for x in cialo["reference_images"]] == ["01_twarz.png", "02_sylwetka.jpg"]
    assert "aspect_ratio" not in cialo and "duration" not in cialo     # edycja: proporcje i dlugosc z filmiku
    _, cialo, _, _ = wavespeed.przygotuj(_z(slug, 10.0, generate_audio=True, parametry={"enable_web_search": False, "prompt": "X"}))
    assert cialo["resolution"] == "720p" and cialo["generate_audio"] is True and cialo["enable_web_search"] is False
    assert cialo["prompt"].startswith("PROMPT A")                     # parametry nie nadpisza promptu
    assert wavespeed.prompt_na_wavespeed("a @[Image 12](image_12) b @image3 c @Image 4") == "a @Image 12 b @Image 3 c @Image 4"
    z = _z(slug, 6.0)
    z["video"] = None
    with pytest.raises(dostawcy.BladDostawcy, match="nie ma filmiku"):
        wavespeed.przygotuj(z)


def test_cialo_wan_prompt_z_wan_txt(slug):
    baza.zapisz_prompt(slug, "wan.txt", PROMPT_WAN)
    _, cialo, _, sz = wavespeed.przygotuj(_z(slug, 6.04, model=WAN))
    assert cialo["prompt"] == PROMPT_WAN and cialo["aspect_ratio"] == "9:16" and cialo["duration"] == 6
    assert cialo["resolution"] == "1080p" and cialo["reference_videos"][0].endswith("a.mp4") and "video" not in cialo
    assert cialo["enable_prompt_expansion"] is False and len(cialo["reference_images"]) == 2
    baza.zapisz_prompt(slug, "wan.txt", "Ona z @[Image 1](image_1)")
    with pytest.raises(dostawcy.BladDostawcy, match="Higgsfielda"):
        wavespeed.przygotuj(_z(slug, 6.0, model=WAN))
    baza.zapisz_prompt(slug, "wan.txt", "x" * 5001)
    with pytest.raises(dostawcy.BladDostawcy, match="5001 znakow"):
        wavespeed.przygotuj(_z(slug, 6.0, model=WAN))


def test_dlugi_filmik_przyciety_kopia(slug, monkeypatch):
    przyciete = []

    def przytnij(plik, cel, max_s):
        przyciete.append((plik, max_s))
        os.makedirs(os.path.dirname(cel), exist_ok=True)
        open(cel, "wb").write(b"krotszy")
        return cel
    monkeypatch.setattr(fabryka.klatki, "przytnij", przytnij)
    _, cialo, _, sz = wavespeed.przygotuj(_z(slug, 20.0))
    assert cialo["video"].endswith("a_max15s.mp4") and abs(przyciete[0][1] - 14.9) < 1e-6 and sz["c"] == 360
    wavespeed.przygotuj(_z(slug, 20.0))
    assert len(przyciete) == 1                                         # kopia jest - drugi raz bez ffmpeg
    assert "a.mp4" in wavespeed.podglad(_z(slug, 20.0)) and len(przyciete) == 1     # --dry-run nie tnie


# ---------------- zlec / sprawdz / koszt ----------------

def test_zlec_jeden_post_bez_powtorek_i_sprawdz(slug, ws):
    z = _z(slug, 6.0)
    ws.ustaw("POST", SUBMIT, _pred("pred_1"))
    znaczniki = []
    w = wavespeed.zlec(z, klucz="rolki-x", znacznik=lambda **k: znaczniki.append(k))
    assert w["job_id"] == "pred_1" and w["status"] == "created" and "gotowy" not in w
    assert znaczniki == [{"wysylam": True, "wideo_id": "https://media.wavespeed.example/a.mp4"}]
    post = ws.submity()[0]
    assert post[2]["video"] == "https://media.wavespeed.example/a.mp4" and post[2]["prompt"] == "PROMPT A @Image 1 @Image 2"
    assert ("POST", SUBMIT, 1) in ws.powtorki                          # POST zadania NIGDY nie jest powtarzany przez HTTP
    # wszystkie pliki wgrane PRZED wyslaniem zadania
    kolej = [x[1] for x in ws.wywolania if x[0] in ("POST", "PUT")]
    assert kolej.index(SUBMIT) == len(kolej) - 1
    ws.ustaw("GET", f"{WS}/predictions/pred_1/result", _pred("pred_1", "processing"), _gotowa("pred_1"))
    assert wavespeed.sprawdz("pred_1")["status"] == "processing" and not wavespeed.koncowy("processing")
    k = wavespeed.sprawdz("pred_1")
    assert k["status"] == "completed" and k["urls"] == ["https://cdn.wavespeed.example/out/pred_1.mp4"] and wavespeed.udany("completed")
    assert wavespeed.koszt_joba(k, 156) == 156
    assert wavespeed.koszt_joba({"status": "failed"}, 156) == 0        # nieudane: zwrot automatyczny (Refund Policy)
    assert wavespeed.koszt_joba({"status": "nsfw"}, 156) == 156        # moderacja: na wszelki wypadek liczymy
    assert not wavespeed.koncowy("cos_nowego")                         # nieznany status = dalej czekamy
    wavespeed.pobierz(k["urls"][0], os.path.join(baza.folder_wynikow(slug), "x.mp4"))
    assert ws.pobrane[0][0] == "https://cdn.wavespeed.example/out/pred_1.mp4"


def test_zlec_4xx_odznacza_wysylanie_a_moderacja_to_nsfw(slug, ws):
    z = _z(slug, 6.0)
    ws.ustaw("POST", SUBMIT, http.BladHTTP(400, json.dumps({"code": 1401, "message": "invalid parameter: resolution"})))
    znaczniki = []
    with pytest.raises(wavespeed.BladWaveSpeed) as e:
        wavespeed.zlec(z, znacznik=lambda **k: znaczniki.append(k))
    assert e.value.status == 400 and "1401" in str(e.value) and znaczniki[-1] == {"wysylam": False}
    assert fabryka._blad_trwaly(e.value)
    ws.ustaw("POST", SUBMIT, http.BladHTTP(400, json.dumps({"code": 1200, "message": "The content contains sensitive information."})))
    with pytest.raises(wavespeed.BladWaveSpeed) as e:
        wavespeed.zlec(z)
    assert fabryka.powod_odrzucenia("", str(e.value)) == "nsfw"
    ws.ustaw("POST", SUBMIT, http.BladHTTP(400, json.dumps({"code": 1407, "message": "The account does not have enough credits"})))
    with pytest.raises(wavespeed.BladWaveSpeed) as e:
        wavespeed.zlec(z)
    assert e.value.kod == "insufficient_credits" and fabryka._blad_trwaly(e.value)
    ws.ustaw("POST", SUBMIT, http.BladHTTP(0, "blad sieci: timed out"))   # nie wiadomo, czy powstalo - znacznik zostaje
    znaczniki.clear()
    with pytest.raises(wavespeed.BladWaveSpeed) as e:
        wavespeed.zlec(z, znacznik=lambda **k: znaczniki.append(k))
    assert znaczniki == [{"wysylam": True, "wideo_id": "https://media.wavespeed.example/a.mp4"}] and not fabryka._blad_trwaly(e.value)


def test_wynik_moderacja_i_has_nsfw(dane, ws):
    sekrety.zapisz_klucz("wavespeed", "k")
    ws.ustaw("GET", f"{WS}/predictions/p1/result",
             _pred("p1", "failed", error="The content contains sensitive information.", code=1200))
    w = wavespeed.sprawdz("p1")
    assert w["status"] == "nsfw" and fabryka.powod_odrzucenia(w["status"], w["blad"]) == "nsfw" and wavespeed.nieudany("nsfw")
    ws.ustaw("GET", f"{WS}/predictions/p2/result", _pred("p2", "failed", error="Model error"))
    w = wavespeed.sprawdz("p2")
    assert w["status"] == "failed" and fabryka.powod_odrzucenia(w["status"], w["blad"]) == "inny"
    ws.ustaw("GET", f"{WS}/predictions/p3/result", _pred("p3", "completed", outputs=["https://cdn/x.mp4"], has_nsfw_contents=[True]))
    assert wavespeed.sprawdz("p3")["status"] == "nsfw"
    ws.ustaw("GET", f"{WS}/predictions/p4/result", _pred("p4", "succeeded", outputs=["https://cdn/y.mp4"]))
    assert wavespeed.sprawdz("p4")["status"] == "completed"


def test_znajdz_po_czasie_tylko_jedno_nieznane(slug, ws):
    od = datetime(2026, 10, 7, 10, 0, 0, tzinfo=timezone.utc)

    def it(pid, sek, status="processing", model=TURBO):
        return {"id": pid, "model": model, "status": status, "outputs": [],
                "created_at": (od + timedelta(seconds=sek)).isoformat().replace("+00:00", ".123456789Z")}
    lista = WS + "/predictions"
    ws.ustaw("POST", lista, _koperta({"page": 1, "items": [it("stary", -3600), it("p_nowe", 3), it("inny_model", 5, model=WAN)]}))
    assert wavespeed.znajdz(TURBO, od=od.isoformat())["job_id"] == "p_nowe"
    assert ws.posty(lista)[0][2] == {"page": 1, "page_size": 50, "model": TURBO}
    ws.ustaw("POST", lista, _koperta({"page": 1, "items": [it("p_a", 3), it("p_b", 40)]}))
    assert wavespeed.znajdz(TURBO, od=od.isoformat()) is None          # dwa kandydaty - nie zgadujemy
    pid = baza.dodaj_pomysl(slug, "inna rolka", "p")
    baza.aktualizuj_pomysl(slug, pid, job_id="p_a", dostawca="wavespeed")   # p_a zna juz fabryka (inna rolka)
    assert wavespeed.znajdz(TURBO, od=od.isoformat())["job_id"] == "p_b"
    assert wavespeed.znajdz(TURBO, od=od.isoformat(), pomin=["p_b"]) is None
    assert wavespeed.znajdz(TURBO, od=None) is None
    ws.ustaw("POST", lista, http.BladHTTP(500, "oops"))
    with pytest.raises(dostawcy.BladDostawcy):
        wavespeed.znajdz(TURBO, od=od.isoformat())


# ---------------- fabryka ----------------

def test_bez_dziennego_limitu_zero_zapytan(slug, ws):
    baza.zapisz_limit_dzienny(0, "wavespeed")
    _wrzuc(slug)
    fabryka.skanuj(slug)
    w = fabryka.generuj(slug)
    assert ws.wywolania == [] and w["stop"] == "brak limitu dziennego wavespeed" and w["wygenerowane"] == 0
    assert baza.pomysl(slug, 1)["status"] == "nowy"
    assert any("dzienny limit WaveSpeed nie jest ustawiony" in x["tekst"] and "--dostawca wavespeed" in x["tekst"]
               for x in baza.dziennik_ostatnie(20))


def test_fabryka_generuje_przez_wavespeed(slug, ws):
    _saldo(ws, 10.0)
    ws.ustaw("POST", WS + "/model/price", _koperta({"model_id": TURBO, "price": 1.56, "discounted_price": 1.56, "discount_rate": 100}))
    ws.ustaw("POST", SUBMIT, _pred("pred_1"))
    ws.ustaw("GET", f"{WS}/predictions/pred_1/result", _pred("pred_1", "processing"), _gotowa("pred_1"))
    _wrzuc(slug)
    fabryka.skanuj(slug)
    w = fabryka.generuj(slug)
    assert w["wygenerowane"] == 1 and not w["bledy"]
    p = baza.pomysl(slug, 1)
    assert p["status"] == "gotowe" and p["dostawca"] == "wavespeed" and p["model"] == TURBO and p["koszt"] == 156
    assert p["resolution"] == "1080p" and p["job_id"] == "pred_1" and p["w_toku"] is None
    assert p["proby"][0]["job_id"] == "pred_1" and p["proby"][0]["kr"] == 156
    assert baza.wydano_dzis("wavespeed") == 156 and baza.wydano_dzis("higgsfield") == 0
    assert len(ws.submity()) == 1 and ws.submity()[0][2]["resolution"] == "1080p"
    assert len(ws.posty(WS + "/media/uploads")) == 3                   # filmik + 2 zdjecia, raz (wycena i wyslanie z cache)
    assert os.path.isfile(p["plik_wynikowy"])
    assert any("$1.56" in x["tekst"] and x["typ"] == "kredyty" for x in baza.dziennik_ostatnie(30))
    assert fabryka.generuj(slug)["wygenerowane"] == 0 and len(ws.submity()) == 1
    # bezpiecznik WaveSpeed (centy): druga rolka 156 c > max $1.00 -> pominieta
    baza.zapisz_ustawienia(slug, wavespeed={"max_kredyty_na_rolke": 100})
    _wrzuc(slug, "b.mp4")
    fabryka.skanuj(slug)
    assert fabryka.generuj(slug)["pominiete"] == [2] and len(ws.submity()) == 1


def test_limit_dzienny_wavespeed_zatrzymuje(slug, ws):
    _saldo(ws, 10.0)
    baza.zapisz_limit_dzienny(200, "wavespeed")
    baza.dopisz_wydatek(100, "wavespeed")
    _wrzuc(slug)
    fabryka.skanuj(slug)
    w = fabryka.generuj(slug)
    assert w["stop"] == "limit dzienny" and not ws.submity()            # 100 + 156 > 200
    assert any("$1.00+$1.56 > $2.00" in x["tekst"] for x in baza.dziennik_ostatnie(20))


def test_blad_sieci_przy_wysylaniu_nigdy_drugi_raz(slug, ws):
    """POST zadania padl bez odpowiedzi (zadanie MOGLO powstac): fabryka szuka go na liscie predykcji, rolka czeka w toku;
    kolejne przebiegi tez tylko szukaja; gdy zadanie sie pojawi - dokanczamy JE. Jeden POST przez caly czas."""
    _saldo(ws, 10.0)
    ws.ustaw("POST", SUBMIT, http.BladHTTP(0, "blad sieci: timed out"))
    ws.ustaw("POST", WS + "/predictions", _koperta({"page": 1, "items": []}))
    _wrzuc(slug)
    fabryka.skanuj(slug)
    w = fabryka.generuj(slug)
    p = baza.pomysl(slug, 1)
    assert w["w_toku"] == [1] and p["status"] == "w_toku" and p["w_toku"]["wysylam"] is True and not p["job_id"]
    assert len(ws.submity()) == 1 and len(ws.posty(WS + "/predictions")) == 2      # szukane po 5 s i 15 s
    assert baza.koszt_w_toku("wavespeed") == 156                       # rezerwa w limicie dnia
    fabryka.generuj(slug)                                              # nastepny przebieg: tylko szuka
    assert len(ws.submity()) == 1 and baza.pomysl(slug, 1)["status"] == "w_toku"
    od = baza.pomysl(slug, 1)["w_toku"]["wysylam_od"]
    kiedy = (datetime.fromisoformat(od) + timedelta(seconds=2)).isoformat().replace("+00:00", "Z")
    ws.ustaw("POST", WS + "/predictions", _koperta({"page": 1, "items": [
        {"id": "pred_9", "model": TURBO, "status": "processing", "created_at": kiedy}]}))
    ws.ustaw("GET", f"{WS}/predictions/pred_9/result", _gotowa("pred_9"))
    w = fabryka.wznow_w_toku(slug)
    p = baza.pomysl(slug, 1)
    assert w["wygenerowane"] == 1 and p["status"] == "gotowe" and p["job_id"] == "pred_9" and len(ws.submity()) == 1
    assert baza.wydano_dzis("wavespeed") == 156


def test_niepewne_wyslanie_po_godzinie_prosi_o_sprawdzenie(slug, ws):
    _wrzuc(slug)
    fabryka.skanuj(slug)
    stare = (datetime.now(timezone.utc) - timedelta(minutes=65)).isoformat()
    baza.zacznij_w_toku(slug, 1, dostawca="wavespeed", model=TURBO, krok=0, klucz="k", koszt=156, od=stare)
    baza.ustaw_w_toku(slug, 1, wysylam=True, wysylam_od=stare, wideo_id="https://media.wavespeed.example/a.mp4")
    ws.ustaw("POST", WS + "/predictions", _koperta({"page": 1, "items": []}))
    w = fabryka.wznow_w_toku(slug)
    p = baza.pomysl(slug, 1)
    assert w["bledy"] == [1] and p["status"] == "blad" and "Sprawdz w apce WaveSpeed" in p["notatki"] and "$1.56" in p["notatki"]
    assert not ws.submity() and baza.wydano_dzis("wavespeed") == 156


def test_5xx_i_timeout_czekania_to_wznowienie(slug, ws):
    _saldo(ws, 10.0)
    ws.ustaw("POST", SUBMIT, _pred("pred_2"))
    ws.ustaw("GET", f"{WS}/predictions/pred_2/result", _pred("pred_2", "processing"))
    _wrzuc(slug)
    fabryka.skanuj(slug)
    w = fabryka.generuj(slug, timeout="0s")
    p = baza.pomysl(slug, 1)
    assert w["w_toku"] == [1] and p["job_id"] == "pred_2" and p["w_toku"]["etap"] == "czeka"
    ws.ustaw("GET", f"{WS}/predictions/pred_2/result", http.BladHTTP(503, "upstream"), _gotowa("pred_2"))
    assert fabryka.wznow_w_toku(slug)["wygenerowane"] == 1 and len(ws.submity()) == 1


def test_4xx_przy_wysylaniu_bez_szukania_i_bez_powtorki(slug, ws):
    _saldo(ws, 10.0)
    ws.ustaw("POST", SUBMIT, http.BladHTTP(400, json.dumps({"code": 1401, "message": "invalid parameter"})))
    _wrzuc(slug)
    fabryka.skanuj(slug)
    w = fabryka.generuj(slug)
    p = baza.pomysl(slug, 1)
    assert w["bledy"] == [1] and p["status"] == "blad" and p["w_toku"] is None and len(ws.submity()) == 1
    assert not ws.posty(WS + "/predictions") and baza.wydano_dzis("wavespeed") == 0


def test_moderacja_wavespeed_odrzucona_i_liczona_na_wszelki_wypadek(slug, ws):
    _saldo(ws, 10.0)
    ws.ustaw("POST", SUBMIT, _pred("pred_3"))
    ws.ustaw("GET", f"{WS}/predictions/pred_3/result", _pred("pred_3", "failed", code=1200,
                                                           error="The content contains sensitive information."))
    _wrzuc(slug)
    fabryka.skanuj(slug)
    w = fabryka.generuj(slug)
    p = baza.pomysl(slug, 1)
    assert w["odrzucone"] == [1] and p["status"] == "blad" and p["powod"] == "nsfw" and len(ws.submity()) == 1
    assert baza.wydano_dzis("wavespeed") == 156


def test_moderacja_przy_wysylaniu_to_nsfw_bez_kosztu(slug, ws):
    _saldo(ws, 10.0)
    ws.ustaw("POST", SUBMIT, http.BladHTTP(400, json.dumps({"code": 1200, "message": "The content contains sensitive information."})))
    _wrzuc(slug)
    fabryka.skanuj(slug)
    w = fabryka.generuj(slug)
    p = baza.pomysl(slug, 1)
    assert w["odrzucone"] == [1] and p["powod"] == "nsfw" and baza.wydano_dzis("wavespeed") == 0 and len(ws.submity()) == 1


# ---------------- zapas po NSFW ----------------

@pytest.fixture
def hf_z_zapasem(modelka, cli):
    """Persona na Higgsfield z zapasem po NSFW na WaveSpeed Turbo (limit WaveSpeed $10)."""
    sekrety.zapisz_klucz("wavespeed", "ws_test_klucz_123456")
    baza.zapisz_ustawienia(modelka, mediatool=False, zapas_nsfw=[{"dostawca": "wavespeed", "model": TURBO}])
    baza.zapisz_limit_dzienny(1000, "wavespeed")
    return modelka


def test_zapas_nsfw_krok_wavespeed(hf_z_zapasem, cli, ws):
    slug = hf_z_zapasem
    _saldo(ws, 10.0)
    ws.ustaw("POST", SUBMIT, _pred("pred_z"))
    ws.ustaw("GET", f"{WS}/predictions/pred_z/result", _gotowa("pred_z"))
    _wrzuc(slug)
    fabryka.skanuj(slug)
    cli.wyniki = [{"id": "hf1", "status": "nsfw"}]
    w = fabryka.generuj(slug)
    assert w["wygenerowane"] == 1 and len(cli.generacje) == 1 and len(ws.submity()) == 1
    p = baza.pomysl(slug, 1)
    assert p["zapas"] is True and p["dostawca"] == "wavespeed" and p["model"] == TURBO and p["koszt"] == 156
    assert [(x["dostawca"], x["status"]) for x in p["proby"]] == [("higgsfield", "nsfw"), ("wavespeed", "completed")]
    assert baza.wydano_dzis("higgsfield") == 0 and baza.wydano_dzis("wavespeed") == 156
    assert any("NSFW -> zapas" in x["tekst"] and "$1.56" in x["tekst"] for x in baza.dziennik_ostatnie(40))


def test_zapas_wavespeed_bez_limitu_zero_zapytan(hf_z_zapasem, cli, ws):
    slug = hf_z_zapasem
    baza.zapisz_limit_dzienny(0, "wavespeed")
    _wrzuc(slug)
    fabryka.skanuj(slug)
    cli.wyniki = [{"id": "hf1", "status": "nsfw"}]
    w = fabryka.generuj(slug)
    p = baza.pomysl(slug, 1)
    assert ws.wywolania == [] and w["odrzucone"] == [1] and "dzienny limit WaveSpeed nie jest ustawiony" in p["notatki"]


def test_zapas_mieszany_yapper_bez_limitu_potem_wavespeed(hf_z_zapasem, cli, ws):
    """Kroki dwoch dostawcow: yapper bez limitu jest pomijany (zero zapytan), WaveSpeed dalej probuje."""
    slug = hf_z_zapasem
    baza.zapisz_ustawienia(slug, zapas_nsfw=[{"dostawca": "yapper", "model": "wan-3.0-prime"}, {"dostawca": "wavespeed", "model": TURBO}])
    baza.zapisz_prompt(slug, "wan.txt", PROMPT_WAN)
    _saldo(ws, 10.0)
    ws.ustaw("POST", SUBMIT, _pred("pred_m"))
    ws.ustaw("GET", f"{WS}/predictions/pred_m/result", _gotowa("pred_m"))
    _wrzuc(slug)
    fabryka.skanuj(slug)
    cli.wyniki = [{"id": "hf1", "status": "nsfw"}]
    assert fabryka.generuj(slug)["wygenerowane"] == 1
    assert not [x for x in ws.wywolania if "yapper.so" in x[1]]
    assert baza.pomysl(slug, 1)["model"] == TURBO


def test_wariant_b_stroj_zachowa_tylko_seedance(hf_z_zapasem, cli, ws):
    """Rolka ze strojem ze zdjecia: krok WaveSpeed Seedance dostaje prompt B (stroj = ostatnie @Image), krok Wan - nie rusza."""
    slug = hf_z_zapasem
    _saldo(ws, 10.0)
    ws.ustaw("POST", SUBMIT, _pred("pred_b"))
    ws.ustaw("GET", f"{WS}/predictions/pred_b/result", _gotowa("pred_b"))
    _wrzuc(slug, "klip.mp4")
    open(os.path.join(baza.folder_zrodel(slug), "klip.stroj.png"), "wb").write(b"png")
    fabryka.skanuj(slug)
    cli.wyniki = [{"id": "hf1", "status": "nsfw"}]
    assert fabryka.generuj(slug)["wygenerowane"] == 1
    cialo = ws.submity()[0][2]
    assert cialo["prompt"] == "PROMPT B @Image 1 @Image 3" and cialo["reference_images"][-1].endswith("klip.stroj.png")
    import app as panel
    panel.app.config["TESTING"] = True
    baza.aktualizuj_pomysl(slug, 1, status="blad", powod="nsfw")
    with panel.app.test_client() as c:
        assert c.post("/api/pomysly/1/ponow").get_json()["od_zapasu"] is True
    # zapas tylko na Wan -> stroj by zginal: zero zapytan, notatka jak przy yapperze
    baza.zapisz_ustawienia(slug, zapas_nsfw=[{"dostawca": "wavespeed", "model": WAN}])
    _wrzuc(slug, "klip2.mp4")
    open(os.path.join(baza.folder_zrodel(slug), "klip2.stroj.png"), "wb").write(b"png")
    fabryka.skanuj(slug)
    ile = len(ws.wywolania)
    cli.wyniki = [{"id": "hf2", "status": "nsfw"}]
    fabryka.generuj(slug, ids=[2])
    assert len(ws.wywolania) == ile and "wariant B" in baza.pomysl(slug, 2)["notatki"]


# ---------------- panel ----------------

def test_panel_konta_modele_budzet_diagnoza(slug, ws, cli):
    import app as panel
    panel._saldo.clear(); panel._konta_test.clear(); panel._modele_cache.clear()
    panel.app.config["TESTING"] = True
    _saldo(ws, 12.34)
    with panel.app.test_client() as c:
        k = c.get("/api/konta").get_json()["konta"]["wavespeed"]
        assert k["jest"] and k["maska"] == "ws_t…3456" and "https://wavespeed.ai/dashboard" in k["jak"]
        assert "ws_test_klucz_123456" not in json.dumps(c.get("/api/konta").get_json())     # klucz nigdy w odpowiedzi
        d = c.post("/api/konta/test", json={"dostawca": "wavespeed"}).get_json()
        assert d["dziala"] is True and "$12.34" in d["komunikat"]
        s = c.get("/api/stan?saldo=1").get_json()
        assert s["saldo"]["wavespeed"]["kredyty"] == 1234 and s["saldo"]["wavespeed"]["jednostka"] == "c"
        assert s["stan"]["budzet"]["jednostka"] == "c" and s["stan"]["budzet"]["limit_dzienny"] == 1000
        assert s["jakosc"]["jednostka"] == "c" and s["jakosc"]["koszt_rolki"] == 360        # 15 s 720p Turbo = $3.60
        assert s["jakosc"]["presety"]["najlepiej"]["koszt_rolki"] == 208                    # 8 s 1080p = $2.08
        assert s["dzis"]["rolek_zostalo"] == 2                                             # $10 limitu // $3.60
        m = c.get("/api/modele?dostawca=wavespeed").get_json()["modele"]
        assert [x["id"] for x in m] == list(wavespeed.MODELE) and m[0]["id"] == TURBO
        b = c.post("/api/budzet", json={"dostawca": "wavespeed", "max_kredyty_dziennie": 1500}).get_json()
        assert b["dzis"]["wavespeed"] == {"wydano": 0, "limit": 1500, "jednostka": "c"}
        assert c.post("/api/budzet", json={"dostawca": "zly", "max_kredyty_dziennie": 5}).status_code == 400
        r = c.post("/api/ustawienia", json={"zapas_nsfw": json.dumps([{"dostawca": "wavespeed", "model": TURBO}])})
        assert r.status_code == 200 and r.get_json()["ustawienia"]["zapas_nsfw"][0]["dostawca"] == "wavespeed"
        assert c.post("/api/ustawienia", json={"zapas_nsfw": '[{"dostawca": "fal", "model": "x"}]'}).status_code == 400
        r = c.post("/api/ustawienia", json={"dostawca": "wavespeed", "wavespeed": {"model": WAN, "max_kredyty_na_rolke": 500}})
        u = r.get_json()["ustawienia"]["wavespeed"]
        assert u["model"] == WAN and u["max_kredyty_na_rolke"] == 500 and u["generate_audio"] is False   # slownik scalony
        diag = {w["co"]: w for w in c.get("/api/diagnoza").get_json()["diagnoza"]}
        assert diag["wavespeed"]["ok"] is True and diag["limit wavespeed"]["ok"] is True and "$15.00" in diag["limit wavespeed"]["info"]
        baza.zapisz_limit_dzienny(0, "wavespeed")
        diag = {w["co"]: w for w in c.get("/api/diagnoza").get_json()["diagnoza"]}
        assert diag["limit wavespeed"]["ok"] is False and "nie ustawiony" in diag["limit wavespeed"]["info"]
    assert "yapper" not in diag                                        # persona bez yappera - bez jego pozycji


def test_ustawienia_domyslne_i_dostawcy():
    w = baza.USTAWIENIA_DOMYSLNE["wavespeed"]
    assert w["model"] == TURBO and w["generate_audio"] is False and w["max_kredyty_na_rolke"] == 400 and w["min_kredyty"] == 0
    assert "wavespeed" in dostawcy.NAZWY and "wavespeed" in dostawcy.NAZWY_ZAPASU and dostawcy.dostawca("wavespeed") is wavespeed
    assert dostawcy.kwota(260, "wavespeed") == "$2.60" and dostawcy.kwota(46) == "46 kr" and dostawcy.kwota(None, "wavespeed") == "$?"
    assert wavespeed.IDEMPOTENTNY is False and wavespeed.WYMAGA_LIMITU is True and wavespeed.JEDNOSTKA == "c"
    assert fabryka.bezpiecznik({"wavespeed": {"min_kredyty": 50, "max_kredyty_na_rolke": 300}}, "wavespeed") == (50, 300)
    assert fabryka.sprawdz_w_apce("wavespeed").startswith("Sprawdz w apce WaveSpeed")
    assert fabryka.sprawdz_w_apce("higgsfield") == fabryka.SPRAWDZ_W_APCE
