# -*- coding: utf-8 -*-
"""3.1 (feedback usera 2026-10-07), zero kredytow i zero internetu: wspolna biblioteka strojow (losowanie wazone + rotacja,
w character swap tylko stroje ze zdjeciem -> wariant B, zmiana stroju przy klipie), numer obrazu stroju per persona, sylwetka
persony (doklejka A/B, Z promptu, limit Wan), model wideo nigdy nie mowi, komentarz pod osobe nagrywajaca (chlopak/dziewczyna)."""
import collections
import os
import random
import re

import pytest

import app as panel
import asystent
import baza
import fabryka
import scenariusz as sc
import sekrety

SYLWETKA = ("petite hourglass figure with a large, full natural bust; a narrow waist; wide hips and a big round bottom. "
            "Never smaller or flatter than in the reference photos.")


@pytest.fixture(autouse=True)
def bez_ffmpeg(monkeypatch):
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 6.0, "szer": 720, "wys": 1280, "fps": 30.0})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    monkeypatch.setattr(fabryka.time, "sleep", lambda s: None)
    asystent._cache_modeli.update(czas=0.0, modele=None)


@pytest.fixture
def slug(modelka, biblioteka):
    baza.zapisz_ustawienia(modelka, mediatool=False)
    baza.zapisz_profil(modelka, wzrost_cm="158-160")
    return modelka


def _wrzuc(slug, nazwa):
    sciezka = os.path.join(baza.folder_zrodel(slug), nazwa)
    with open(sciezka, "wb") as f:
        f.write(b"mp4")
    return sciezka


# ---------------- biblioteka: wczytanie, wagi, rotacja ----------------

def test_biblioteka_wczytanie_i_tylko_ze_zdjeciem(slug, biblioteka):
    wszystkie = baza.stroje_biblioteki()
    assert [s["id"] for s in wszystkie] == ["ulub_a", "ulub_b", "zwykly_c", "zwykly_d", "opis_e"]
    assert wszystkie[0]["plik"] == os.path.join(biblioteka, "ulub_a.png") and wszystkie[-1]["plik"] is None
    assert [s["id"] for s in baza.stroje_biblioteki(tylko_ze_zdjeciem=True)] == ["ulub_a", "ulub_b", "zwykly_c", "zwykly_d"]
    os.remove(os.path.join(biblioteka, "zwykly_d.png"))           # brak pliku na dysku = stroj tylko z opisu
    assert baza.stroj_biblioteki("zwykly_d")["plik"] is None and baza.stroj_biblioteki("nie_ma") is None


def test_losowanie_wazone_ulubione_czesciej(slug):
    los = random.Random(7)
    licz = collections.Counter(baza.losuj_stroj_biblioteki(slug, tylko_ze_zdjeciem=True, los=los, uzycia={})["id"]
                               for _ in range(4000))
    assert set(licz) == {"ulub_a", "ulub_b", "zwykly_c", "zwykly_d"}                # w swapie nigdy stroj bez zdjecia
    assert licz["ulub_a"] > 2 * licz["zwykly_c"] and licz["ulub_b"] > 2 * licz["zwykly_d"]
    # z promptu (wszystkie): stroj tylko z opisu tez wypada, waga 2
    licz2 = collections.Counter(baza.losuj_stroj_biblioteki(slug, los=los, uzycia={})["id"] for _ in range(3000))
    assert licz2["opis_e"] > licz2["zwykly_c"] and licz2["ulub_a"] > licz2["opis_e"]
    # unikaj (np. NSFW) i mnozniki (nauka)
    assert all(baza.losuj_stroj_biblioteki(slug, los=los, uzycia={}, unikaj={"ulub_a", "ulub_b"})["id"] not in ("ulub_a", "ulub_b")
               for _ in range(200))
    tylko_c = {s["id"]: 0 for s in baza.stroje_biblioteki()}
    tylko_c["zwykly_c"] = 1
    assert {baza.losuj_stroj_biblioteki(slug, los=los, uzycia={}, mnozniki=tylko_c)["id"] for _ in range(50)} == {"zwykly_c"}


def test_rotacja_ostatnio_uzyte_odpadaja_najdawniejsze_czesciej(slug):
    los = random.Random(3)
    uzycia = {"ulub_a": "2026-10-07T12:00:00+00:00", "ulub_b": "2026-10-01T12:00:00+00:00"}
    wybory = collections.Counter(baza.losuj_stroj_biblioteki(slug, tylko_ze_zdjeciem=True, los=los, uzycia=uzycia)["id"]
                                 for _ in range(3000))
    assert "ulub_a" not in wybory                                   # ostatnio uzyty nie wraca od razu
    assert wybory["zwykly_c"] and wybory["zwykly_d"] and wybory["ulub_b"]
    # nigdy nieuzyte maja wieksza szanse niz dawno uzyte o tej samej wadze
    uzycia2 = {"zwykly_c": "2026-10-01T00:00:00+00:00", "ulub_a": "2026-10-07T00:00:00+00:00"}
    w2 = collections.Counter(baza.losuj_stroj_biblioteki(slug, tylko_ze_zdjeciem=True, los=los, uzycia=uzycia2)["id"]
                             for _ in range(4000))
    assert w2["zwykly_d"] > w2["zwykly_c"]
    # uzycia liczone z pomysly.json (rolki z filmu i z promptu)
    baza.dodaj_pomysl(slug, "x", "p", stroj_bib="zwykly_c")
    baza.dodaj_pomysl(slug, "y", "p", typ="prompt", z_promptu={"stroj_id": "ulub_b", "stroj_tryb": "biblioteka"})
    baza.dodaj_pomysl(slug, "z", "p", typ="prompt", z_promptu={"stroj_id": "krata_futerko", "stroj_tryb": "odwazny"})
    assert set(baza.uzycia_strojow(slug)) == {"zwykly_c", "ulub_b"}
    # pusta biblioteka = None
    os.remove(os.path.join(baza.KATALOG_BIBLIOTEKI, "stroje.json"))
    assert baza.losuj_stroj_biblioteki(slug) is None


# ---------------- character swap: stroj_swap = biblioteka -> wariant B ----------------

def test_skanuj_biblioteka_wariant_b_i_rotacja(slug, cli):
    assert baza.ustawienia_modelki(slug)["stroj_swap"] == "biblioteka"           # domyslnie
    for i in range(4):
        _wrzuc(slug, f"klip{i}.mp4")
    w = fabryka.skanuj(slug)
    assert len(w["nowe"]) == 4
    pomysly = baza.lista_pomyslow(slug)
    for p in pomysly:
        assert p["stroj_bib"] in ("ulub_a", "ulub_b", "zwykly_c", "zwykly_d")      # tylko ze zdjeciem
        assert p["stroj"] == baza.stroj_biblioteki(p["stroj_bib"])["plik"]
        assert p["prompt_higgsfield"].startswith("PROMPT B")
    # rotacja: dwa kolejne klipy nie dostaja tego samego stroju
    ids = [p["stroj_bib"] for p in pomysly]
    assert all(a != b for a, b in zip(ids, ids[1:]))
    # zdjecie stroju idzie jako OSTATNI obraz (po referencjach)
    z = fabryka.zlecenie(slug, pomysly[0])
    assert [os.path.basename(o) for o in z["images"]][:2] == ["01_twarz.png", "02_sylwetka.jpg"]
    assert z["images"][-1] == pomysly[0]["stroj"] and len(z["images"]) == 3
    # generacja: wgranie stroju przez istniejacy upload + cache uploady.json (udawane CLI, 0 kr)
    assert fabryka.generuj(slug, ids=[pomysly[0]["id"]])["wygenerowane"] == 1
    assert pomysly[0]["stroj"] in cli.uploady and baza.upload_id(slug, pomysly[0]["stroj"])


def test_skanuj_pierwszenstwo_i_z_filmu(slug):
    wlasny = _wrzuc(slug, "a.stroj.png")
    _wrzuc(slug, "a.mp4")
    fabryka.skanuj(slug)
    p = baza.pomysl(slug, 1)
    assert p["stroj"] == wlasny and not p.get("stroj_bib")                        # <nazwa>.stroj.png wygrywa
    baza.zapisz_ustawienia(slug, stroj_swap="z_filmu")
    _wrzuc(slug, "b.mp4")
    fabryka.skanuj(slug)
    p = baza.pomysl(slug, 2)
    assert p["stroj"] is None and p["prompt_higgsfield"].startswith("PROMPT A")
    # klipy, ktore juz czekaja, zostaja jak byly po wlaczeniu biblioteki
    baza.zapisz_ustawienia(slug, stroj_swap="biblioteka")
    _wrzuc(slug, "c.mp4")
    fabryka.skanuj(slug)
    assert baza.pomysl(slug, 2)["stroj"] is None and baza.pomysl(slug, 3).get("stroj_bib")


def test_skanuj_bez_promptu_b_idzie_wariantem_a(slug):
    baza.zapisz_prompt(slug, "stroj_ze_zdjecia.txt", "")
    _wrzuc(slug, "a.mp4")
    logi = []
    fabryka.skanuj(slug, log=logi.append)
    p = baza.pomysl(slug, 1)
    assert p["stroj"] is None and p["prompt_higgsfield"].startswith("PROMPT A")
    assert any("nie ma promptu B" in str(l) for l in logi)
    assert any("biblioteki wymagaja promptu B" in u for u in fabryka.sprawdz_prompt(slug))


def test_skanuj_dlugi_filmik_kawalki_z_biblioteki(slug, monkeypatch):
    dlugi = _wrzuc(slug, "dlugi.mp4")
    czasy = {dlugi: 50.0}
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": czasy.get(p, 15.0), "szer": 720, "wys": 1280, "fps": 30.0})

    def potnij(plik, folder, max_s=30, min_s=4):
        os.makedirs(folder, exist_ok=True)
        out = [os.path.join(folder, f"dlugi_cz{i}.mp4") for i in (1, 2, 3)]
        for o in out:
            open(o, "wb").write(b"v")
        return out
    monkeypatch.setattr(fabryka.klatki, "potnij", potnij)
    assert fabryka.skanuj(slug)["nowe"] == [1, 2, 3]
    assert all(baza.pomysl(slug, i).get("stroj_bib") and baza.pomysl(slug, i)["prompt_higgsfield"].startswith("PROMPT B")
               for i in (1, 2, 3))


@pytest.mark.parametrize("ile_ref", [4, 5, 6])
def test_numer_obrazu_stroju_per_persona(dane, biblioteka, ile_ref):
    """Alicja/Lilianna 4 zdjecia -> stroj = @[Image 5], Noemi 5 -> 6, Bianka 6 -> 7 (ostatni --image)."""
    slug = baza.utworz_modelke(f"Persona{ile_ref}")
    for i in range(1, ile_ref + 1):
        open(os.path.join(baza.folder_referencji(slug), f"{i:02d}_ref.png"), "wb").write(b"img")
    n = ile_ref + 1
    baza.zapisz_prompt(slug, "stroj_z_filmu.txt", " ".join(f"@[Image {i}](image_{i})" for i in range(1, n)))
    baza.zapisz_prompt(slug, "stroj_ze_zdjecia.txt", " ".join(f"@[Image {i}](image_{i})" for i in range(1, n + 1))
                       + f" @[Image {n}](image_{n}) shows only the clothing")
    assert not [u for u in fabryka.sprawdz_prompt(slug) if "@Image" in u or "odwoluje" in u]
    _wrzuc(slug, "klip.mp4")
    fabryka.skanuj(slug)
    z = fabryka.zlecenie(slug, baza.pomysl(slug, 1))
    assert len(z["images"]) == n and z["images"][-1] == baza.pomysl(slug, 1)["stroj"]
    assert os.path.dirname(z["images"][-1]) == biblioteka


# ---------------- panel: stroj przy klipie ----------------

@pytest.fixture
def klient(slug, cli):
    panel._saldo.clear()
    panel.konsola.__init__()
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        yield c


def test_api_zmiana_stroju_klipu(klient, slug):
    baza.zapisz_ustawienia(slug, stroj_swap="z_filmu")
    _wrzuc(slug, "a.mp4")
    fabryka.skanuj(slug)
    d = klient.get("/api/pomysly").get_json()
    assert d["ma_prompt_b"] and [s["id"] for s in d["biblioteka"]][:2] == ["ulub_a", "ulub_b"]      # ulubione na gorze
    assert all(s["url"] for s in d["biblioteka"])                                                   # tylko ze zdjeciem
    karta = d["pomysly"][0]
    assert karta["mozna_zmienic_stroj"] and karta["wariant"] == "A"
    r = klient.post("/api/pomysly/1/stroj", json={"stroj": "zwykly_c"}).get_json()
    p = baza.pomysl(slug, 1)
    assert r["ok"] and p["stroj_bib"] == "zwykly_c" and p["prompt_higgsfield"].startswith("PROMPT B")
    assert r["pomysl"]["stroj_nazwa"] == "Zwykły C" and r["pomysl"]["stroj_url"] and r["pomysl"]["wariant"] == "B"
    assert klient.get(r["pomysl"]["stroj_url"]).status_code == 200                               # miniatura z biblioteki
    assert klient.post("/api/pomysly/1/stroj", json={"stroj": "opis_e"}).status_code == 400      # bez zdjecia - nie w swapie
    r = klient.post("/api/pomysly/1/stroj", json={"stroj": "z_filmu"}).get_json()
    p = baza.pomysl(slug, 1)
    assert r["ok"] and p["stroj"] is None and p["prompt_higgsfield"].startswith("PROMPT A")
    # wlasny prompt rolki zostaje (z uwaga), rolka w toku / zrobiona - nie
    baza.aktualizuj_pomysl(slug, 1, prompt_higgsfield="MOJ PROMPT")
    r = klient.post("/api/pomysly/1/stroj", json={"stroj": "ulub_a"}).get_json()
    assert r["uwaga"] and baza.pomysl(slug, 1)["prompt_higgsfield"] == "MOJ PROMPT"
    baza.aktualizuj_pomysl(slug, 1, status="w_toku", w_toku={"dostawca": "higgsfield"})
    assert klient.post("/api/pomysly/1/stroj", json={"stroj": "z_filmu"}).status_code == 409
    baza.aktualizuj_pomysl(slug, 1, status="gotowe", w_toku=None)
    assert klient.post("/api/pomysly/1/stroj", json={"stroj": "z_filmu"}).status_code == 400


def test_api_profil_sylwetka_i_katalog(klient, slug):
    d = klient.post("/api/profil", json={"sylwetka": "  " + SYLWETKA + "  "}).get_json()
    assert d["ok"] and d["profil"]["sylwetka"] == SYLWETKA
    kat = klient.get("/api/z-promptu").get_json()
    assert kat["persona"]["sylwetka"] == SYLWETKA and kat["stroje_biblioteka"][0]["ulubiony"]
    assert [s["id"] for s in kat["stroje_biblioteka"] if not s["ma_zdjecie"]] == ["opis_e"]
    u = klient.get("/api/ustawienia").get_json()
    assert len(u["biblioteka"]) == 5 and u["ustawienia"]["stroj_swap"] == "biblioteka"


# ---------------- sylwetka: doklejka w swapie (A, B, Wan) ----------------

def test_sylwetka_doklejana_w_swapie_a_i_b(slug):
    baza.zapisz_profil(slug, sylwetka=SYLWETKA)
    baza.zapisz_ustawienia(slug, stroj_swap="z_filmu")
    _wrzuc(slug, "a.mp4")
    _wrzuc(slug, "b.mp4")
    _wrzuc(slug, "b.stroj.png")
    fabryka.skanuj(slug)
    for pid, prefiks in ((1, "PROMPT A"), (2, "PROMPT B")):
        p = baza.pomysl(slug, pid)
        z = fabryka.zlecenie(slug, p)
        assert z["prompt"].startswith(prefiks) and z["prompt"].endswith(
            "BODY SHAPE (highest priority after face): " + SYLWETKA)
        assert p["prompt_higgsfield"] == prefiks + (" @[Image 1](image_1) @[Image 2](image_2)" if pid == 1
                                                    else " @[Image 1](image_1) @[Image 3](image_3)")   # pomysl bez zmian
    # plik promptu usera nietkniety
    assert "BODY SHAPE" not in baza.prompt_bazowy(slug) and "BODY SHAPE" not in baza.prompt_stroj(slug)
    # doklejka idzie tez do generate (udawane CLI nie potrzebne - przygotuj)
    import dostawcy.higgsfield as dh
    _, params, _ = dh.przygotuj(fabryka.zlecenie(slug, baza.pomysl(slug, 1)))
    assert "BODY SHAPE (highest priority after face)" in params["prompt"]
    # bez sylwetki - prompt jak dawniej
    baza.zapisz_profil(slug, sylwetka="")
    assert fabryka.zlecenie(slug, baza.pomysl(slug, 1))["prompt"] == baza.pomysl(slug, 1)["prompt_higgsfield"]


def test_sylwetka_wan_limit_5000(slug):
    baza.zapisz_profil(slug, sylwetka=SYLWETKA)
    p = {"id": 1, "prompt_higgsfield": "PROMPT A", "zrodlo": None, "stroj": None}
    pelny = len(fabryka.doklej_sylwetke("x", SYLWETKA)[0]) - 1
    krotki = len(fabryka.doklej_sylwetke("x", SYLWETKA.split(". ")[0] + ".")[0]) - 1
    assert krotki < pelny
    for dl, oczekiwane in ((3000, "pelna"), (5000 - (krotki + pelny) // 2, "krotka"), (4990, "pominieta")):
        baza.zapisz_prompt(slug, "wan.txt", "w" * dl)
        z = fabryka.zlecenie(slug, p)
        wan = z["yapper"]["prompt"]
        assert len(wan) <= fabryka.LIMIT_PROMPTU_WAN and z["wavespeed"]["prompt_wan"] == wan
        assert fabryka.doklej_sylwetke("w" * dl, SYLWETKA, fabryka.LIMIT_PROMPTU_WAN)[1] == oczekiwane
        if oczekiwane == "pominieta":
            assert "BODY SHAPE" not in wan
        else:
            assert wan.startswith("w" * dl) and "BODY SHAPE (highest priority after face)" in wan
    baza.zapisz_ustawienia(slug, zapas_nsfw=[{"dostawca": "yapper", "model": "wan-3.0-prime"}])
    assert any("sylwetka persony nie miesci sie" in u for u in fabryka.sprawdz_prompt_wan(slug))
    # dwa razy nie dokleja
    raz = fabryka.doklej_sylwetke("abc", SYLWETKA)[0]
    assert fabryka.doklej_sylwetke(raz, SYLWETKA) == (raz, "jest")


# ---------------- Z promptu: stroj z biblioteki, sylwetka, glos ----------------

NOWE = {"pomysl_id": "galeria_fastfood", "dlugosc": 10, "reakcja": "para_kreci_glowa", "nazwy": "opisowe", "pora": "popoludnie"}


def test_z_promptu_stroj_z_biblioteki_seedance(slug):
    w = sc.zbuduj(slug, dict(NOWE, stroj="biblioteka:ulub_a"))
    p = w["prompt"]
    assert w["stroj_id"] == "ulub_a" and w["stroj_nazwa"] == "Ulubiony A" and w["stroj_tryb"] == "biblioteka"
    assert len(w["obrazy"]) == 3 and w["obrazy"][-1].endswith("ulub_a.png")
    assert "a black corset top and a short black pleated skirt" in p                   # opis_en zawsze w prompcie
    assert "<<<image_3>>> shows ONLY the outfit" in p and "ignore the hair, face, skin, tattoos and body shape" in p
    assert "come only from <<<image_1>>> and <<<image_2>>>" in p
    # losowy z biblioteki: ten sam przy "Zrob rolke" (ustalone)
    w1 = sc.zbuduj(slug, dict(NOWE, stroj="biblioteka"))
    w2 = sc.zbuduj(slug, dict(NOWE, stroj="biblioteka", ustalone=w1["ustalone"]))
    assert w1["stroj_id"] and w2["prompt"] == w1["prompt"] and w1["ustalone"]["stroj_tryb"] == "biblioteka"
    # stroj tylko z opisu: bez zdjecia
    w = sc.zbuduj(slug, dict(NOWE, stroj="biblioteka:opis_e"))
    assert len(w["obrazy"]) == 2 and "purple velvet corset" in w["prompt"] and "<<<image_3>>>" not in w["prompt"]
    with pytest.raises(ValueError):
        sc.zbuduj(slug, dict(NOWE, stroj="biblioteka:nie_ma"))


def test_z_promptu_stroj_wan_gemini_i_limit_zdjec(slug):
    for model in ("wan3_0_prime", "gemini_omni_flash_1_1"):
        w = sc.zbuduj(slug, dict(NOWE, stroj="biblioteka:ulub_b", model=model))
        assert len(w["obrazy"]) == 3 and "<<<image" not in w["prompt"]
        assert "the last reference photo" in w["prompt"] and "person or mannequin" in w["prompt"]
        assert "the young woman from the first 2 reference photos" in w["prompt"]
    # Gemini max 7 zdjec: 7 referencji + stroj sie nie miesci -> stroj tylko z opisu (z ostrzezeniem), bez bledu
    for i in range(3, 8):
        open(os.path.join(baza.folder_referencji(slug), f"{i:02d}_x.png"), "wb").write(b"img")
    w = sc.zbuduj(slug, dict(NOWE, stroj="biblioteka:ulub_b", model="gemini_omni_flash_1_1"))
    assert len(w["obrazy"]) == 7 and "burgundy corset" in w["prompt"] and any("tylko z opisu" in u for u in w["ostrzezenia"])


def test_z_promptu_pusta_biblioteka_wraca_do_odwaznych(modelka):
    w = sc.zbuduj(modelka, dict(NOWE, stroj="biblioteka", sezon="jesien"))
    assert w["stroj_tryb"] == "odwazny" and w["stroj_id"] in sc.STROJE_ODWAZNE and any("pusta" in u for u in w["ostrzezenia"])


def test_z_promptu_sylwetka_dla_kazdego_modelu(slug):
    baza.zapisz_profil(slug, sylwetka=SYLWETKA)
    for model in sc.MODELE:
        w = sc.zbuduj(slug, dict(NOWE, model=model, stroj="biblioteka:ulub_a"))
        p = w["prompt"]
        assert w["sylwetka"] == "pelna"
        i_wlosy, i_syl, i_stroj = p.index("Hair:"), p.index("Body shape (highest priority after her face)"), p.index("Outfit:")
        assert i_wlosy < i_syl < i_stroj, model                      # tuz po wlosach/wzroscie, przed strojem
        assert "a big round bottom" in p
    # za dlugo dla modelu -> pierwsze zdanie, potem bez sylwetki (zawsze w limicie)
    baza.zapisz_profil(slug, sylwetka=SYLWETKA + " " + "very " * 900 + "long.")
    w = sc.zbuduj(slug, dict(NOWE, model="gemini_omni_flash_1_1", stroj="biblioteka:ulub_a"))
    assert w["sylwetka"] == "krotka" and w["znaki"] <= sc.MODELE["gemini_omni_flash_1_1"]["limit_znakow"]
    baza.zapisz_profil(slug, sylwetka="very " * 900 + "long.")
    w = sc.zbuduj(slug, dict(NOWE, model="gemini_omni_flash_1_1"))
    assert w["sylwetka"] == "pominieta" and "Body shape" not in w["prompt"]


def test_z_promptu_model_nigdy_nie_mowi(slug):
    for p in sc.POMYSLY:
        for model in sc.MODELE:
            if 10 not in sc.MODELE[model]["dlugosci"]:
                continue
            w = sc.zbuduj(slug, {"pomysl_id": p["id"], "model": model, "dlugosc": 10, "glos": "auto"})
            t = w["prompt"]
            assert "{" not in t and "Dialogue language" not in t and "says quietly" not in t, (p["id"], model)
            assert "says nothing" in t and "silent" in t and w["glos"] in ("tts", "bez")
            assert w["komentarz"] not in t


def test_z_promptu_bez_klucza_rolka_bez_komentarza_nie_model(slug, cli):
    """Brak klucza ElevenLabs: wycena mowi to wprost, rolka generuje sie z samym otoczeniem, komentarz NIE przechodzi na model."""
    w = fabryka.wycena_z_promptu(slug, dict(NOWE, glos="auto", stroj="biblioteka:ulub_a"))
    assert w["glos"] == "tts" and w["ustalone"]["glos"] == "tts" and "{" not in w["prompt"]
    assert any("bez komentarza" in u for u in w["ostrzezenia"]) and w["stroj_nazwa"] == "Ulubiony A"
    pid = fabryka.dodaj_z_promptu(slug, dict(NOWE, glos="auto", stroj="biblioteka:ulub_a", ustalone=w["ustalone"]), kr=w["kr"])
    p = baza.pomysl(slug, pid)
    assert p["stroj_bib"] == "ulub_a" and p["z_promptu"]["stroj_nazwa"] == "Ulubiony A" and p["z_promptu"]["nagrywa"] == "chlopak"
    assert fabryka.generuj(slug, ids=[pid])["wygenerowane"] == 1
    p = baza.pomysl(slug, pid)
    assert p["status"] == "gotowe" and p["glos_dograny"] is False and "klucza" in p["glos_blad"]
    assert "{" not in cli.generacje[0][1]["prompt"] and cli.generacje[0][2]["image"][-1].startswith("uuid-ulub_a")
    assert "ulub_a" in baza.uzycia_strojow(slug)                       # rotacja widzi tez rolki z promptu


# ---------------- komentarz pod osobe nagrywajaca ----------------

def test_komentarze_pasuja_do_mowiacego():
    for kto in sc.NAGRYWA:
        for linia in sc.komentarze_dla(kto) + sc.KOMENTARZE_COSPLAY:
            assert sc.pasuje_do_mowiacego(linia, kto), (kto, linia)
    for linia in sc.KOMENTARZE + sum(sc.LINIE_REAKCJI.values(), []) + [p["komentarz"] for p in sc.POMYSLY]:
        assert sc.pasuje_do_mowiacego(linia, "chlopak") and sc.pasuje_do_mowiacego(linia, "dziewczyna"), linia    # neutralne
    assert not sc.pasuje_do_mowiacego("Ja bym tak nie wyszła.", "chlopak")
    assert not sc.pasuje_do_mowiacego("Pierwszy raz widziałem coś takiego.", "dziewczyna")
    assert sc.dopasuj_do_mowiacego("Ja bym się tak nie odważyła.", "chlopak") == "Ja bym się tak nie odważył."
    assert sc.dopasuj_do_mowiacego("Ja bym tak nie wyszedł.", "dziewczyna") == "Ja bym tak nie wyszła."
    assert "Ja bym tak nie wyszła." not in sc.komentarze_dla("chlopak")


def test_zbuduj_dopasowuje_komentarz_do_nagrywajacego(slug):
    w = sc.zbuduj(slug, dict(NOWE, komentarz="Ja bym tak nie wyszła."))
    assert w["nagrywa"] == "chlopak" and w["komentarz"] == "Ja bym tak nie wyszedł."
    w = sc.zbuduj(slug, dict(NOWE, komentarz="Ja bym tak nie wyszła.", nagrywa="dziewczyna"))
    assert w["nagrywa"] == "dziewczyna" and w["komentarz"] == "Ja bym tak nie wyszła."
    baza.zapisz_ustawienia(slug, nagrywa="dziewczyna")
    for i in range(30):                                         # losowe linie tez pasuja do dziewczyny
        w = sc.zbuduj(slug, dict(NOWE, komentarz="losowy", pomysl_id="", tekst="stoi na przystanku"),
                      los=random.Random(i))
        assert w["nagrywa"] == "dziewczyna" and sc.pasuje_do_mowiacego(w["komentarz"], "dziewczyna")


# ---------------- asystent: biblioteka + nauka + plec mowiacego ----------------

def test_asystent_dobiera_stroj_z_biblioteki(slug):
    w = asystent.dobierz(slug, "zamawia w galerii", los=random.Random(1))
    o = w["opcje"]
    assert o["stroj"].startswith("biblioteka:") and o["nagrywa"] == "chlopak"
    assert baza.stroj_biblioteki(o["stroj"].split(":", 1)[1])["nazwa"] in w["podsumowanie"]
    assert "chłopak" in w["podsumowanie"]
    licz = collections.Counter(asystent.dobierz(slug, "zamawia w galerii", los=random.Random(i))["opcje"]["stroj"]
                               for i in range(300))
    ulub = licz["biblioteka:ulub_a"] + licz["biblioteka:ulub_b"]
    assert ulub > licz["biblioteka:zwykly_c"] + licz["biblioteka:zwykly_d"]       # ulubione czesciej
    # NSFW na stroju z biblioteki -> asystent go omija; ocena "dobra" dziala dalej
    pid = fabryka.dodaj_z_promptu(slug, dict(NOWE, stroj="biblioteka:ulub_a"), kr=45)
    baza.aktualizuj_pomysl(slug, pid, status="blad", powod="nsfw")
    pid2 = fabryka.dodaj_z_promptu(slug, dict(NOWE, stroj="biblioteka:zwykly_d"), kr=45)
    baza.aktualizuj_pomysl(slug, pid2, status="gotowe")
    asystent.ocen(slug, pid2, "dobra")
    n = asystent.nauka(slug)
    assert "ulub_a" in n["nsfw_stroje"] and n["punkty"]["stroj"]["zwykly_d"] == 3
    assert "Zwykły D" in asystent.opis_nauki(n)
    for i in range(40):
        assert asystent.dobierz(slug, "zamawia w galerii", los=random.Random(i))["opcje"]["stroj"] != "biblioteka:ulub_a"
    # recznie wybrany stroj zostaje
    assert asystent.dobierz(slug, "x", zablokowane={"stroj": "odwazny:moro"})["opcje"]["stroj"] == "odwazny:moro"


def test_asystent_llm_komentarz_i_stroj_z_biblioteki(slug, monkeypatch):
    sekrety.zapisz_klucz("openrouter", "sk-or-v1-test")
    zapytania = []

    def http_json(metoda, url, cialo=None, timeout=25):
        zapytania.append(cialo)
        if url.endswith("/models"):
            return {"data": [{"id": m} for m in asystent.MODELE_LLM]}
        return {"choices": [{"message": {"content": '{"miejsce": "metro", "stroj": "*ulub_b", "kamera": "zza_filaru", '
                                                    '"reakcja": "dwa_razy", "komentarz": "Ja bym tak nie wyszła.", '
                                                    '"dlaczego": "Ulubiony strój."}'}}]}
    monkeypatch.setattr(asystent, "_http_json", http_json)
    baza.zapisz_ustawienia(slug, nagrywa="chlopak")
    w = asystent.dobierz(slug, "", zablokowane={"sezon": "jesien"})
    o = w["opcje"]
    assert o["stroj"] == "biblioteka:ulub_b" and o["miejsce"] == "metro"
    assert o["komentarz"] != "Ja bym tak nie wyszła." and sc.pasuje_do_mowiacego(o["komentarz"], "chlopak")   # zla plec = odrzucone
    tresc = [z for z in zapytania if z and "messages" in z][0]["messages"][1]["content"]
    assert "*Ulubiony A" in tresc and "SPEAKER (the person filming, never visible): a young man" in tresc
    assert "krata_futerko" not in tresc                                   # odwazne nie sa juz domyslne


def test_prawdziwa_biblioteka_bez_slow_ryzykownych():
    """Opisy strojow z repo (stroje_biblioteka/stroje.json) ida do kazdej rolki z promptu - zero slow z SLOWA_RYZYKOWNE
    (lace/mesh/fishnet/sheer/bra/mini skirt...), wyglad trzyma zdjecie stroju + slowa typu openwork, diamond-net."""
    import json
    plik = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stroje_biblioteka", "stroje.json")
    stroje = json.load(open(plik, encoding="utf-8"))["stroje"]
    assert len(stroje) >= 19 and sum(1 for s in stroje if s.get("ulubiony")) == 3
    for s in stroje:
        t = " " + re.sub(r"[^a-z0-9 -]+", " ", s["opis_en"].lower()) + " "
        zle = [w for w in fabryka.SLOWA_RYZYKOWNE if f" {w} " in t or f" {w}s " in t]
        assert not zle, (s["id"], zle)
        if s.get("plik"):
            assert os.path.isfile(os.path.join(os.path.dirname(plik), s["plik"])), s["plik"]
