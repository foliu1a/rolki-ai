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

Y = "https://yapper.so/api/v1"        # yapper - adresy w testach sa PELNE i porownywane dokladnie (endswith ukryl kiedys
S = "https://api.sync.so/v2"          # sklejony adres https://yapper.so/api/v1https://...)
E = "https://api.elevenlabs.io/v1"


class UdawanyHTTP:
    """Zbiera wywolania i odpowiada wg regul: lista odpowiedzi per (metoda, DOKLADNY url). Nieznany adres = 404."""

    def __init__(self):
        self.wywolania = []
        self.odpowiedzi = {}
        self.pobrane = []

    def ustaw(self, metoda, url, *odpowiedzi):
        assert url.startswith("http"), "w testach podawaj pelny adres"
        self.odpowiedzi[(metoda, url)] = list(odpowiedzi)

    def _odp(self, metoda, url):
        lista = self.odpowiedzi.get((metoda, url))
        if lista:
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
        odp = self.odpowiedzi.get((metoda, url))
        if odp and isinstance(odp[0], Exception):
            raise odp[0]
        return ""

    def pobierz(self, url, sciezka, naglowki=None, timeout=600):
        os.makedirs(os.path.dirname(sciezka), exist_ok=True)
        with open(sciezka, "wb") as f:
            f.write(b"plik")
        self.pobrane.append((url, sciezka))
        return sciezka

    def posty(self, url):
        return [w for w in self.wywolania if w[0] == "POST" and w[1] == url]


@pytest.fixture
def udawany_http(monkeypatch):
    u = UdawanyHTTP()
    for nazwa in ("zapytanie", "multipart", "wyslij_plik", "pobierz"):
        monkeypatch.setattr(http, nazwa, getattr(u, nazwa))
    yapper.wyczysc_cache()
    yield u
    yapper.wyczysc_cache()


# prawdziwe ksztalty z yapper.so (GET /models, /models/wan-3.0/schema.json, 2026-10-04)
MODEL_WAN = {"id": "wan-3.0", "type": "video-generation", "displayName": "WAN 3.0",
             "capabilities": {"aspectRatios": ["16:9", "4:3", "1:1", "3:4", "9:16"], "resolutions": [480, 720, 1080],
                              "videoLengths": list(range(2, 31)), "maxReferenceImages": 10,
                              "referenceVideos": {"maxCount": 5, "maxCombinedDurationSeconds": 15}, "maxPromptLength": 5000},
             "pricing": {"unit": "video", "creditsByLength": {"10": 490}, "pricedResolution": 1080}}
SCHEMAT_WAN = {"type": "object", "additionalProperties": False, "required": ["prompt"], "properties": {
    "prompt": {"type": "string"}, "aspectRatio": {"type": "string", "enum": ["16:9", "4:3", "1:1", "3:4", "9:16", "auto"]},
    "resolution": {"type": "number", "enum": [480, 720, 1080]}, "videoLength": {"type": "number", "enum": list(range(2, 31))},
    "durationMode": {"type": "string", "enum": ["fixed", "auto"]}, "referenceImages": {"type": "array"},
    "referenceVideos": {"type": "array"}, "referenceAudios": {"type": "array"}, "disableAutoRetries": {"type": "boolean"}}}
SCHEMAT_EDIT = {"type": "object", "properties": {"prompt": {"type": "string"}, "aspectRatio": {"const": "auto"},
                                                 "durationMode": {"const": "auto"}, "referenceVideos": {"type": "array"},
                                                 "referenceImages": {"type": "array"}, "generateAudio": {"type": "boolean"}}}


def _dry(kr, can_start=True, blocked=None, model="wan-3.0"):
    return {"dryRun": True, "type": "video-generation", "model": model, "creditsEstimated": kr, "canStart": can_start,
            "blockedBy": blocked, "credits": {"available": 7000}}


def _bilety(u, *ids):
    """POST /assets/uploads -> kolejne bilety (assetId, podpisany PUT, naglowki, completeUrl ABSOLUTNY) + complete per asset."""
    u.ustaw("POST", Y + "/assets/uploads", *[{
        "assetId": a, "uploadUrl": f"https://storage.googleapis.com/yapper-up/{a}?X-Goog-Signature=abc", "method": "PUT",
        "headers": {"Content-Type": "video/mp4" if a.startswith("v") else "image/png", "x-goog-content-length-range": "0,104857600"},
        "maxBytes": 104857600, "expiresAt": "2026-10-04T12:00:00Z", "completeUrl": f"{Y}/assets/uploads/{a}/complete"} for a in ids])
    for a in ids:
        u.ustaw("POST", f"{Y}/assets/uploads/{a}/complete", {"id": a, "type": "video" if a.startswith("v") else "image",
                                                              "createdAt": "2026-10-04T10:00:00Z"})


def _modele(u, model=MODEL_WAN, schemat=SCHEMAT_WAN):
    u.ustaw("GET", Y + "/models", [model])
    u.ustaw("GET", f"{Y}/models/{model['id']}/schema.json", schemat)


# ---------------- yapper ----------------

def test_yapper_bez_klucza(dane):
    with pytest.raises(dostawcy.BrakKlucza):
        yapper.saldo()
    assert yapper.gotowy()[0] is False


def test_yapper_saldo_modele_naglowki(dane, udawany_http):
    sekrety.zapisz_klucz("yapper", "yk_test")
    udawany_http.ustaw("GET", Y + "/credits", {"totalCredits": 5000, "usedCredits": 1240, "availableCredits": 3760})
    udawany_http.ustaw("GET", Y + "/models", {"models": [{"id": "wan-3.0", "name": "WAN 3.0", "processType": "video-generation"},
                                                         {"id": "gpt-image-2", "name": "GPT Image", "processType": "image-generation"}]})
    assert yapper.saldo() == 3760
    assert yapper.gotowy() == (True, "3760 kr dostepnych")
    assert udawany_http.wywolania[0][1] == Y + "/credits" and udawany_http.wywolania[0][3]["Authorization"] == "Bearer yk_test"
    assert [m["id"] for m in yapper.modele_wideo()] == ["wan-3.0"]


def _zlecenie_wan(modelka, czas=6.0, nazwa="klip.mp4"):
    sekrety.zapisz_klucz("yapper", "yk_test")
    baza.zapisz_ustawienia(modelka, dostawca="yapper", yapper={"model": "wan-3.0", "resolution": "720p"})
    baza.zapisz_prompt(modelka, "wan.txt", "Replace the woman with the woman from the reference photos.")
    zrodlo = os.path.join(baza.folder_zrodel(modelka), nazwa)
    open(zrodlo, "wb").write(b"mp4")
    p = {"id": 1, "prompt_higgsfield": "PROMPT A @[Image 1](image_1)", "zrodlo": zrodlo, "info_zrodla": {"czas": czas}}
    return fabryka.zlecenie(modelka, p), zrodlo


def test_yapper_wgraj_dokladne_adresy_i_naglowki_biletu(modelka, udawany_http):
    """Bilet: PUT na uploadUrl z naglowkami 1:1 (bez nadpisanego Content-Type), completeUrl ABSOLUTNY wolany bez doklejania
    https://yapper.so/api/v1 drugi raz, cialo biletu tylko {type, mimeType, name}; drugi raz z cache (zero wywolan)."""
    z, zrodlo = _zlecenie_wan(modelka)
    _bilety(udawany_http, "v_asset")
    assert yapper.wgraj(modelka, zrodlo) == "v_asset"
    w = udawany_http.wywolania
    assert w[0][:2] == ("POST", Y + "/assets/uploads") and w[0][2] == {"type": "video", "mimeType": "video/mp4", "name": "klip.mp4"}
    assert w[1][0] == "PUT" and w[1][1] == "https://storage.googleapis.com/yapper-up/v_asset?X-Goog-Signature=abc"
    assert w[1][3] == {"Content-Type": "video/mp4", "x-goog-content-length-range": "0,104857600"}   # dokladnie z biletu
    assert w[2][:2] == ("POST", Y + "/assets/uploads/v_asset/complete")
    assert not any("api/v1https" in x[1] for x in w)
    ile = len(w)
    assert yapper.wgraj(modelka, zrodlo) == "v_asset" and len(udawany_http.wywolania) == ile
    # m4v -> video/mp4 (yapper nie zna video/x-m4v); obcy host w completeUrl -> klucz API tam NIE idzie
    with pytest.raises(dostawcy.BladDostawcy, match="spoza yapper.so"):
        yapper._url("https://zly.example/api/v1/assets/uploads/x/complete")
    assert yapper._url("/api/v1/assets/uploads/x/complete") == Y + "/assets/uploads/x/complete"
    assert yapper._url("/processes") == Y + "/processes"


def test_http_wyslij_plik_nie_nadpisuje_content_type(monkeypatch, tmp_path):
    plik = tmp_path / "a.m4v"
    plik.write_bytes(b"v")
    zlapane = {}

    def zapytanie(metoda, url, dane=None, naglowki=None, timeout=60, surowe_cialo=None, typ_ciala=None, powtorki=3):
        zlapane.update(naglowki=naglowki, typ_ciala=typ_ciala)
        return ""
    monkeypatch.setattr(http, "zapytanie", zapytanie)
    http.wyslij_plik("https://s/put", str(plik), naglowki={"Content-Type": "video/mp4", "x-goog-content-length-range": "0,9"})
    assert zlapane["typ_ciala"] is None and zlapane["naglowki"]["Content-Type"] == "video/mp4"
    http.wyslij_plik("https://s/put", str(plik))           # bilet bez Content-Type -> zgadujemy
    assert zlapane["typ_ciala"]


def test_yapper_wycena_dryrun_i_cialo_wan(modelka, udawany_http):
    """dryRun w prawdziwym ksztalcie (creditsEstimated); cialo Wan wg schematu: bez generateAudio, durationMode auto RAZEM
    z videoLength = dlugosc klipu (bez niej yapper wycenia jak 5 s), rozdzielczosc rolki (6 s -> 1080p), prompt z wan.txt
    (bez @[Image]), filmik i referencje jako assetId."""
    z, _ = _zlecenie_wan(modelka, czas=6.0)
    z["generate_audio"] = True
    _modele(udawany_http)
    _bilety(udawany_http, "i1", "i2", "v_asset")
    udawany_http.ustaw("POST", Y + "/processes", _dry(250))
    assert yapper.koszt(z) == 250
    dry = udawany_http.posty(Y + "/processes")[0][2]
    assert dry["dryRun"] is True and dry["model"] == "wan-3.0" and dry["type"] == "video-generation"
    wej = dry["input"]
    assert "generateAudio" not in wej and wej["durationMode"] == "auto" and wej["videoLength"] == 6
    assert wej["resolution"] == 1080 and wej["aspectRatio"] == "9:16"
    assert wej["prompt"] == "Replace the woman with the woman from the reference photos."
    assert wej["referenceImages"] == [{"assetId": "i1"}, {"assetId": "i2"}] and wej["referenceVideos"] == [{"assetId": "v_asset"}]
    # 10 s klip -> 720p (zasada <= 8 s -> 1080p)
    z10, _ = _zlecenie_wan(modelka, czas=10.0, nazwa="dlugi.mp4")
    assert yapper._cialo(z10, uploady=False)["input"]["resolution"] == 720


def test_yapper_wycena_odmawia_canstart_false(modelka, udawany_http):
    z, _ = _zlecenie_wan(modelka)
    _modele(udawany_http)
    _bilety(udawany_http, "i1", "i2", "v_asset")
    udawany_http.ustaw("POST", Y + "/processes", _dry(250, can_start=False, blocked="team_limit"))
    with pytest.raises(dostawcy.BladDostawcy, match="odmawia startu \\(team_limit"):
        yapper.koszt(z)
    udawany_http.ustaw("POST", Y + "/processes", _dry(250, can_start=False))
    with pytest.raises(dostawcy.BladDostawcy, match="canStart=false"):
        yapper.koszt(z)
    udawany_http.ustaw("POST", Y + "/processes", {"dryRun": True, "canStart": True})
    with pytest.raises(dostawcy.BladDostawcy, match="bez creditsEstimated"):
        yapper.koszt(z)


def test_yapper_zasady_wan_prompt_i_filmik(modelka, udawany_http):
    """Wan: prompt max 5000 znakow i bez @[Image N] (blad PRZED jakimkolwiek POST), filmik referencyjny max 15 s."""
    z, _ = _zlecenie_wan(modelka)
    _modele(udawany_http)
    z["yapper"]["prompt"] = "Ona z @[Image 1](image_1) tanczy"
    with pytest.raises(dostawcy.BladDostawcy, match="@\\[Image N\\]"):
        yapper._cialo(z, uploady=False)
    z["yapper"]["prompt"] = "x" * 5001
    with pytest.raises(dostawcy.BladDostawcy, match="5001 znakow.*max 5000"):
        yapper._cialo(z, uploady=False)
    z["yapper"]["prompt"] = ""
    z["prompt"] = "PROMPT A @[Image 1](image_1)"            # pusty wan.txt -> prompt Higgsfielda -> odmowa
    with pytest.raises(dostawcy.BladDostawcy, match="Higgsfielda"):
        yapper._cialo(z, uploady=False)
    z["yapper"]["prompt"] = "ok prompt"
    z["video_czas"] = 16.0
    with pytest.raises(dostawcy.BladDostawcy, match="max 15 s"):
        yapper._cialo(z, uploady=False)
    assert not udawany_http.posty(Y + "/processes")
    # bez /models i schematu (API milczy) - znane zasady Wan dalej pilnuja
    yapper.wyczysc_cache()
    udawany_http.odpowiedzi.clear()
    z["video_czas"] = 6.0
    wej = yapper._cialo(dict(z, generate_audio=False), uploady=False)["input"]
    assert "generateAudio" not in wej and wej["durationMode"] == "auto"


def test_yapper_seedance_edit_aspect_auto(modelka, udawany_http):
    z, _ = _zlecenie_wan(modelka)
    z["yapper"]["model"] = "seedance-2.5-edit"
    _modele(udawany_http, model={"id": "seedance-2.5-edit", "type": "video-generation", "capabilities": {}}, schemat=SCHEMAT_EDIT)
    wej = yapper._cialo(dict(z, generate_audio=False), uploady=False)["input"]
    assert wej["aspectRatio"] == "auto" and wej["durationMode"] == "auto" and wej["generateAudio"] is False
    assert "resolution" not in wej


def test_yapper_zlec_sprawdz_koszt_procesu(modelka, udawany_http):
    """POST /processes ze stalym Idempotency-Key + metadata; GET /processes/{id}; koszt = creditsUsed - zwrot."""
    z, _ = _zlecenie_wan(modelka)
    _modele(udawany_http)
    _bilety(udawany_http, "i1", "i2", "v_asset")
    udawany_http.ustaw("POST", Y + "/processes", {"id": "proc_1", "status": "queued", "model": "wan-3.0", "creditsEstimated": 250})
    znaczniki = []
    w = yapper.zlec(z, klucz="rolki-noemi-1-wan-3.0-1", znacznik=lambda **k: znaczniki.append(k))
    assert w["job_id"] == "proc_1" and w["status"] == "queued" and "gotowy" not in w and znaczniki == [{"wysylam": True}]
    post = udawany_http.posty(Y + "/processes")[0]
    assert post[3]["Idempotency-Key"] == "rolki-noemi-1-wan-3.0-1" and post[2]["metadata"] == {"rolki_klucz": "rolki-noemi-1-wan-3.0-1"}
    assert "dryRun" not in post[2]
    udawany_http.ustaw("GET", Y + "/processes/proc_1", {"id": "proc_1", "status": "processing"},
                       {"id": "proc_1", "status": "completed", "creditsUsed": 250, "refunded": False,
                        "outputs": [{"type": "video", "assetId": "o1", "url": "https://cdn/wynik.mp4"}]})
    assert yapper.sprawdz("proc_1")["status"] == "processing"
    k = yapper.sprawdz("proc_1")
    assert k["status"] == "completed" and k["urls"] == ["https://cdn/wynik.mp4"] and yapper.koszt_joba(k, 999) == 250
    assert yapper.koszt_joba({"status": "completed", "surowe": {"creditsUsed": 250, "refunded": True}}) == 0
    assert yapper.koszt_joba({"status": "failed", "surowe": {"creditsUsed": 250, "refunded": False}}) == 0   # zwrot automatyczny
    assert yapper.koszt_joba({"status": "completed", "surowe": {"creditsUsed": 300, "refunded": 50}}) == 250
    assert yapper.koszt_joba({"status": "completed", "surowe": {}}, 250) == 250


def test_yapper_konflikt_klucza_szuka_po_metadanych(modelka, udawany_http):
    z, _ = _zlecenie_wan(modelka)
    _modele(udawany_http)
    _bilety(udawany_http, "i1", "i2", "v_asset")
    udawany_http.ustaw("POST", Y + "/processes", http.BladHTTP(409, json.dumps({"error": {"code": "idempotency_conflict",
                                                                                        "message": "same key, other body"}})))
    udawany_http.ustaw("GET", Y + "/processes?model=wan-3.0&limit=50", {"data": [
        {"id": "obcy", "status": "completed", "metadata": {"rolki_klucz": "inny"}},
        {"id": "proc_7", "status": "processing", "metadata": {"rolki_klucz": "rolki-noemi-1-wan-3.0-1"}}], "nextCursor": None})
    assert yapper.zlec(z, klucz="rolki-noemi-1-wan-3.0-1")["job_id"] == "proc_7"


def test_yapper_blad_kredytow(dane, udawany_http):
    sekrety.zapisz_klucz("yapper", "yk_test")
    udawany_http.ustaw("POST", Y + "/processes", http.BladHTTP(402, json.dumps({"error": {"code": "insufficient_credits", "message": "no credits"}})))
    z = {"slug": None, "prompt": "x", "images": [], "video": None, "yapper": {"model": "wan-3.0"}, "resolution": "720p", "duration": 5}
    with pytest.raises(dostawcy.BladDostawcy, match="insufficient_credits"):
        yapper.koszt(z)


def test_fabryka_generuje_przez_yapper(modelka, monkeypatch):
    """Caly obieg fabryki z dostawca=yapper na udawanym module yapper (bez HTTP): koszt z procesu, nie z salda."""
    baza.zapisz_ustawienia(modelka, dostawca="yapper", mediatool=False, yapper={"model": "wan-3.0", "min_kredyty": 500, "max_kredyty_na_rolke": 600})
    baza.zapisz_limit_dzienny(1000, "yapper")
    stan = {"saldo": 2000, "zlecenia": []}
    monkeypatch.setattr(yapper, "saldo", lambda: stan["saldo"])
    monkeypatch.setattr(yapper, "koszt", lambda z: 300)

    def zlec(z, klucz=None, znacznik=None, log=None):
        stan["zlecenia"].append((z, klucz))
        stan["saldo"] -= 777            # saldo spada inaczej (np. reczna generacja na koncie) - nie wplywa na rozliczenie
        return {"job_id": "proc_9", "status": "queued", "surowe": {}}
    monkeypatch.setattr(yapper, "zlec", zlec)
    monkeypatch.setattr(yapper, "sprawdz", lambda jid: {"job_id": jid, "status": "completed", "urls": ["https://cdn/w.mp4"], "blad": "",
                                                        "surowe": {"id": jid, "status": "completed", "creditsUsed": 300, "refunded": False}})
    monkeypatch.setattr(yapper, "pobierz", lambda url, sciezka: (open(sciezka, "wb").write(b"x"), sciezka)[1])
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 5.0, "szer": 720, "wys": 1280, "fps": 30})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    open(os.path.join(baza.folder_zrodel(modelka), "a.mp4"), "wb").write(b"mp4")
    fabryka.skanuj(modelka)
    w = fabryka.generuj(modelka)
    assert w["wygenerowane"] == 1
    p = baza.pomysl(modelka, 1)
    assert p["status"] == "gotowe" and p["dostawca"] == "yapper" and p["koszt"] == 300 and p["model"] == "wan-3.0"
    assert p["resolution"] == "1080p" and p["proby"][0]["job_id"] == "proc_9" and p["proby"][0]["kr"] == 300
    assert baza.wydano_dzis("yapper") == 300 and baza.wydano_dzis("higgsfield") == 0
    z, klucz = stan["zlecenia"][0]
    assert z["mode"] == "video_edit" and z["video"].endswith("a.mp4") and z["resolution"] == "1080p"
    assert klucz == f"rolki-{modelka}-1-wan-3.0-1"
    # bezpiecznik yappera (nie Higgsfielda): druga rolka zostawilaby >= 500, ale 300 > max 250 -> pominieta
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
    udawany_http.ustaw("POST", S + "/generate", {"id": "gen_1", "status": "PENDING"})
    udawany_http.ustaw("GET", S + "/generate/gen_1", {"id": "gen_1", "status": "PROCESSING"},
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
    udawany_http.ustaw("POST", S + "/generate", {"id": "gen_2", "status": "PENDING"})
    udawany_http.ustaw("GET", S + "/generate/gen_2", {"id": "gen_2", "status": "FAILED", "error": "no face", "errorCode": "face_not_found"})
    w = sync_so.generuj("https://x/w.mp4", "https://x/a.mp3")
    assert w["status"] == "failed" and "face_not_found" in w["blad"] and w["url"] is None
    post = [x for x in udawany_http.wywolania if x[0] == "POST"][0]
    assert post[2]["input"] == [{"type": "video", "url": "https://x/w.mp4"}, {"type": "audio", "url": "https://x/a.mp3"}]
    udawany_http.ustaw("POST", S + "/analyze/cost", [{"estimatedFrameCount": 150, "estimatedGenerationCost": 0.3}])
    assert sync_so.koszt("https://x/w.mp4", "https://x/a.mp3") == 30
    udawany_http.ustaw("POST", S + "/tts", {"id": "t1", "url": "https://cdn/t.mp3", "duration": 2.5})
    assert sync_so.tts("czesc", "voice1")["url"] == "https://cdn/t.mp3"


def test_sync_opis_bledu_401(dane, udawany_http):
    sekrety.zapisz_klucz("sync", "zly")
    udawany_http.ustaw("GET", S + "/models", http.BladHTTP(401, "Unauthorized"))
    ok, kom = sync_so.gotowy()
    assert ok is False and "401" in kom


# ---------------- elevenlabs (tylko saldo) ----------------

def test_elevenlabs_saldo_i_gotowy(dane, udawany_http):
    from dostawcy import elevenlabs
    assert elevenlabs.gotowy() == (False, "brak klucza API ElevenLabs (panel -> Konta)")
    sekrety.zapisz_klucz("elevenlabs", "el-123")
    udawany_http.ustaw("GET", E + "/user/subscription", {"tier": "starter", "character_count": 1200, "character_limit": 30000})
    assert elevenlabs.saldo() == 28800
    s = elevenlabs.saldo_szczegoly()
    assert s == {"kredyty": 28800, "limit": 30000, "plan": "starter", "jednostka": "zn"}
    assert udawany_http.wywolania[-1][3]["xi-api-key"] == "el-123"
    assert elevenlabs.gotowy() == (True, "klucz dziala, plan starter: zostalo 28800 z 30000 znakow w tym miesiacu")
    udawany_http.ustaw("GET", E + "/user/subscription", http.BladHTTP(401, json.dumps({"detail": {"status": "invalid_api_key", "message": "Invalid API key"}}), "u"))
    with pytest.raises(dostawcy.BladDostawcy, match="ElevenLabs 401: Invalid API key"):
        elevenlabs.saldo()
    assert elevenlabs.gotowy()[0] is False
    assert dostawcy.dostawca("elevenlabs") is elevenlabs and "elevenlabs" not in dostawcy.NAZWY


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
