# -*- coding: utf-8 -*-
"""Rolka z promptu 3.0 (feedback usera 2026-10-07), zero kredytow i zero internetu:
odwazne stroje, kamera z ukrycia, prawdziwe nazwy galerii/dworcow + polskie napisy, reakcje zdziwienia z polskimi liniami,
zapis fonetyczny ą/ę dla modelu wideo, komentarz ElevenLabs dogrywany po generacji (komentarz_glos), asystent (reguly +
udawany OpenRouter) i jego nauka (oceny, NSFW, IP), endpointy panelu."""
import json
import os
import random
import re
import shutil

import pytest

import app as panel
import asystent
import baza
import fabryka
import komentarz_glos
import scenariusz as sc
import sekrety
from dostawcy import elevenlabs, http


@pytest.fixture(autouse=True)
def bez_ffmpeg_fabryki(monkeypatch):
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 6.0, "szer": 720, "wys": 1280, "fps": 30.0})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    monkeypatch.setattr(fabryka.time, "sleep", lambda s: None)
    asystent._cache_modeli.update(czas=0.0, modele=None)


@pytest.fixture
def slug(modelka):
    baza.zapisz_ustawienia(modelka, mediatool=False)
    baza.zapisz_profil(modelka, wzrost_cm="158-160")
    return modelka


NOWE = {"pomysl_id": "galeria_fastfood", "dlugosc": 10, "stroj": "odwazny:krata_futerko", "reakcja": "para_kreci_glowa",
        "komentarz": "Widziałaś to? Jak ona wygląda…", "wymowa": "fonetyczna", "nazwy": "prawdziwe", "obiekt": "posnania",
        "pora": "popoludnie", "glos": "model"}


def _slowa_ryzykowne(tekst):
    t = " " + re.sub(r"[^a-z0-9 -]+", " ", sc._bez_ogonkow(tekst)) + " "
    return [s for s in fabryka.SLOWA_RYZYKOWNE if f" {s} " in t or f" {s}s " in t]


# ---------------- katalog i prompt ----------------

def test_odwazne_stroje_bez_slow_ryzykownych_i_wg_pory_roku(slug):
    assert len(sc.STROJE_ODWAZNE) >= 15
    for sid, (pl, en, pory) in sc.STROJE_ODWAZNE.items():
        assert pl and en and pory and set(pory) <= set(sc.SEZONY), sid
        assert not _slowa_ryzykowne(en), (sid, _slowa_ryzykowne(en))
        assert not any(m in en.lower() for m in sc.MARKI), sid
    for sezon in sc.SEZONY:
        assert all(sezon in sc.STROJE_ODWAZNE[s][2] for s in sc.stroje_odwazne_na(sezon))
    w = sc.zbuduj(slug, dict(NOWE, stroj="odwazny", sezon="zima"))
    assert w["stroj_id"] in sc.stroje_odwazne_na("zima") and "bold, eye-catching street look" in w["prompt"]
    assert "the same outfit she wears in the reference photos" not in w["prompt"]
    w2 = sc.zbuduj(slug, dict(NOWE, stroj="odwazny", sezon="zima", ustalone=w["ustalone"]))
    assert w2["prompt"] == w["prompt"]                     # ten sam losowy stroj przy "Zrob rolke"
    with pytest.raises(ValueError):
        sc.zbuduj(slug, dict(NOWE, stroj="odwazny:bikini"))


def test_kamera_z_ukrycia_domyslnie(slug):
    for p in sc.POMYSLY:
        w = sc.zbuduj(slug, {"pomysl_id": p["id"]})
        assert w["kamera"] in sc.KAMERY_UKRYTE, p["id"]
        assert "never walk up to her" in w["prompt"] and "pretends not to" in w["prompt"]
        assert "walks slowly closer" not in w["prompt"]
    stara = sc.zbuduj(slug, {"pomysl_id": "galeria_fastfood", "kamera": "idzie_za"})
    assert "walks slowly closer" in stara["prompt"] and "never walk up to her" not in stara["prompt"]
    assert sc.kamera_ukryta("tramwaj") == "siedzi_naprzeciw" and sc.kamera_ukryta("galeria_foodcourt") == "zza_filaru"
    assert sc.kamera_ukryta("rynek_krakow") == "ukradkiem" and sc.kamera_ukryta("przystanek") == "z_biodra"


def test_prawdziwe_nazwy_i_polskie_napisy(slug):
    w = sc.zbuduj(slug, NOWE)
    p = w["prompt"]
    assert "the food court of the Posnania shopping centre in Poznań, Poland" in p
    assert "'19,99 zł'" in p and "'ZAMÓW TUTAJ'" in p and "real name Posnania" in p and "no brand logos" not in p
    assert w["obiekt"] == "posnania" and "Posnania" in w["miejsce_nazwa"] and w["ustalone"]["obiekt"] == "posnania"
    bez = sc.zbuduj(slug, dict(NOWE, nazwy="opisowe"))
    assert "Posnania" not in bez["prompt"] and "no brand logos" in bez["prompt"] and bez["obiekt"] is None
    # miasto z pomyslu wybiera obiekt; samo miasto nie przebija slowa "galeria"
    assert sc.miasto_z_tekstu("zamawia jedzenie w galerii we Wrocławiu") == "wroclaw"
    assert sc.pomysl_z_tekstu("zamawia jedzenie w galerii we Wrocławiu")["miejsce"] == "galeria_foodcourt"
    assert sc.pomysl_z_tekstu("je obwarzanka na Rynku w Krakowie")["miejsce"] == "rynek_krakow"
    w = sc.zbuduj(slug, {"tekst": "zamawia jedzenie w galerii we Wrocławiu", "nazwy": "prawdziwe"})
    assert w["obiekt"] == "wroclavia" and "Wroclavia shopping centre in Wrocław" in w["prompt"]
    w = sc.zbuduj(slug, {"pomysl_id": "market_kasa", "nazwy": "prawdziwe", "obiekt": "jezyce"})
    assert "a discount supermarket in Poznań's Jeżyce district" in w["prompt"]
    assert sc.zbuduj(slug, {"pomysl_id": "rynek_obwarzanek"})["obiekt"] is None      # Rynek ma juz swoja nazwe
    for mid in sc.OBIEKTY_MIEJSC:
        assert mid in sc.MIEJSCA and sc.obiekty_miejsca(mid)


def test_reakcje_zdziwienia_subtelne_z_polskimi_liniami(slug):
    for r in sc.REAKCJE_ZDZIWIENIE:
        assert r in sc.REAKCJE and sc.LINIE_REAKCJI[r]
        assert all(l in sc.KOMENTARZE for l in sc.LINIE_REAKCJI[r])
        assert not _slowa_ryzykowne(sc.REAKCJE[r][1])
        w = sc.zbuduj(slug, dict(NOWE, reakcja=r))
        assert sc.REAKCJE[r][1] in w["prompt"] and "nobody points, laughs out loud or speaks to her" in w["prompt"]
        assert "Nobody in the clip speaks clearly" in w["prompt"]          # 3.1: komentarz tylko z ElevenLabs
    zwykla = sc.zbuduj(slug, {"pomysl_id": "galeria_fastfood", "reakcja": "smiech"})
    assert "nobody points" not in zwykla["prompt"] and "says nothing at all" in zwykla["prompt"]
    assert asystent.reakcje_dla_miejsca("dyskont")[0] == "kasjerka_zamiera"
    assert set(asystent.reakcje_dla_miejsca("park")) <= set(sc.REAKCJE_ZDZIWIENIE)


def test_fonetycznie_i_wymowa_w_klamrach(slug):
    assert sc.fonetycznie("Jak ona wygląda…") == "Jak ona wyglonda…"
    assert sc.fonetycznie("Idą, mogę, się, zęby, ręka, wzięli, kąpie, Mają") == "Idom, moge, sie, zemby, renka, wzieli, kompie, Majom"
    assert sc.fonetycznie("Widziałaś to?") == "Widziałaś to?"
    # 3.1: komentarz nigdy nie trafia do promptu wideo (zapis fonetyczny juz niepotrzebny); ElevenLabs dostaje poprawna pisownie
    for wymowa in ("fonetyczna", "zwykla"):
        w = sc.zbuduj(slug, dict(NOWE, wymowa=wymowa))
        assert "{" not in w["prompt"] and "wyglonda" not in w["prompt"] and w["komentarz"] == "Widziałaś to? Jak ona wygląda…"


def test_glos_tts_wideo_bez_mowy_a_komentarz_osobno(slug):
    w = sc.zbuduj(slug, dict(NOWE, glos="tts"))
    p = w["prompt"]
    assert "{" not in p and "the person filming stays completely silent" in p and "Dialogue language" not in p
    assert "Noemi says nothing at all" in p and "nobody talks to her or to the camera" in p and "whisper indistinctly" in p
    assert w["glos"] == "tts" and w["komentarz"] == "Widziałaś to? Jak ona wygląda…" and w["komentarz_t"] == 5
    for model in ("wan3_0_prime", "gemini_omni_flash_1_1"):
        k = sc.zbuduj(slug, dict(NOWE, glos="tts", model=model))
        assert "{" not in k["prompt"] and "person filming stays silent" in k["prompt"] and "she says nothing" in k["prompt"]
    bez = sc.zbuduj(slug, dict(NOWE, komentarz="bez", glos="tts"))
    assert bez["glos"] == "bez" and bez["komentarz_t"] is None and "Dialogue language" not in bez["prompt"]
    assert "says nothing at all" in bez["prompt"]
    # stare "model" (np. z zapisanych opcji) = tez bez mowy w wideo, z ostrzezeniem
    stary = sc.zbuduj(slug, NOWE)
    assert stary["glos"] == "tts" and "{" not in stary["prompt"] and any("wylaczona" in u for u in stary["ostrzezenia"])
    with pytest.raises(ValueError):
        sc.zbuduj(slug, dict(NOWE, glos="robot"))


def test_dlugosc_promptow_z_nowymi_ustawieniami(slug):
    for p in sc.POMYSLY:
        for opcje in ({"stroj": "odwazny", "reakcja": "dwa_razy", "komentarz": "Jak ona może tak chodzić?", "wymowa": "fonetyczna"},
                      {"stroj": "odwazny", "reakcja": "kasjerka_zamiera", "glos": "tts", "dlugosc": 15}):
            w = sc.zbuduj(slug, dict(opcje, pomysl_id=p["id"]))
            uwagi = " ".join(w["ostrzezenia"])
            assert "filtr NSFW" not in uwagi and "marek" not in uwagi, (p["id"], uwagi)
            assert w["znaki"] <= sc.MODELE["seedance_2_5"]["zalecane_znaki"], (p["id"], w["znaki"])
        for model in ("wan3_0_prime", "gemini_omni_flash_1_1"):
            w = sc.zbuduj(slug, {"pomysl_id": p["id"], "model": model, "stroj": "odwazny", "reakcja": "dwa_razy"})
            assert w["znaki"] <= sc.MODELE[model]["limit_znakow"] and "<<<image" not in w["prompt"]


def test_katalog_ma_nowe_pola(slug):
    k = sc.katalog(slug)
    assert k["stroje"][0][0] == "biblioteka" and "odwazny" in dict(k["stroje"]) and len(k["stroje_odwazne"]) == len(sc.STROJE_ODWAZNE)
    assert "zza_filaru" in k["kamery_ukryte"] and k["obiekty"]["galeria_foodcourt"][0][0] == "posnania"
    assert {g[0] for g in k["glosy"]} == {"auto", "tts"} and k["linie_reakcji"]["dwa_razy"]      # "model" zniknal z wyboru
    assert dict(k["nagrywa"]) == {"chlopak": "Chłopak", "dziewczyna": "Dziewczyna"} and k["persona"]["nagrywa"] == "chlopak"


# ---------------- asystent: reguly i nauka ----------------

def test_asystent_regulami_bez_klucza(slug):
    w = asystent.dobierz(slug, "stoi w kolejce w dyskoncie w Poznaniu", los=random.Random(3))
    o = w["opcje"]
    assert w["zrodlo"] == "reguly" and "OpenRouter" in w["uwaga"] and w["dlaczego"].endswith(".")
    assert o["miejsce"] == "dyskont" and o["obiekt"] == "jezyce" and o["nazwy"] == "prawdziwe"
    assert o["stroj"].startswith("odwazny:") and o["kamera"] in sc.KAMERY_UKRYTE and o["reakcja"] in sc.REAKCJE_ZDZIWIENIE
    assert o["komentarz"] in sc.LINIE_REAKCJI[o["reakcja"]] and o["glos"] == "auto" and o["wymowa"] == "fonetyczna"
    assert "Jeżyce" in w["podsumowanie"] and "Seedance 2.5" in w["podsumowanie"]
    zb = sc.zbuduj(slug, dict(o, glos="model"))                 # opcje asystenta przechodza przez scenariusz
    assert "Jeżyce" in zb["prompt"]
    # pomysl z wlasna reakcja (smiech) - asystent jej nie zmienia; reczne pola zostaja
    w = asystent.dobierz(slug, "w tramwaju ludzie się śmieją", zablokowane={"stroj": "zdjecia", "dlugosc": "8", "kamera": "auto"})
    assert w["opcje"]["reakcja"] == "smiech" and w["opcje"]["stroj"] == "zdjecia" and w["opcje"]["dlugosc"] == 8
    assert w["opcje"]["kamera"] == "siedzi_naprzeciw"
    # pusty pomysl = miejsce "z ludzmi"
    for i in range(5):
        assert asystent.dobierz(slug, "", los=random.Random(i))["opcje"]["miejsce"] in asystent.MIEJSCA_REAKCJI


def _rolka(slug, opcje, **pola):
    pid = fabryka.dodaj_z_promptu(slug, opcje, kr=70)
    if pola:
        baza.aktualizuj_pomysl(slug, pid, **pola)
    return pid


def test_asystent_uczy_sie_z_ocen_nsfw_i_ip(slug):
    a = _rolka(slug, dict(NOWE, stroj="odwazny:panterka"), status="blad", powod="nsfw")
    b = _rolka(slug, dict(NOWE, stroj="odwazny:krowie_laty"), status="gotowe")
    asystent.ocen(slug, b, "dobra")
    n = asystent.nauka(slug)
    assert "panterka" in n["nsfw_stroje"] and n["punkty"]["stroj"]["krowie_laty"] == 3
    assert "Kurtka w krowie łaty" in asystent.opis_nauki(n) and "krowie_laty" in asystent.opis_nauki(n, dla_llm=True)
    for i in range(25):
        o = asystent.dobierz(slug, "zamawia w galerii", los=random.Random(i), zablokowane={"sezon": "jesien"})["opcje"]
        assert o["stroj"] != "odwazny:panterka"
    # IP: obiekt z odrzucenia jest omijany, dwa odrzucenia z nazwami = bez nazw
    _rolka(slug, NOWE, status="blad", powod="ip")
    n = asystent.nauka(slug)
    assert "posnania" in n["ip_obiekty"] and "galeria_foodcourt" in n["ip_miejsca"]
    o = asystent.dobierz(slug, "zamawia w galerii w Poznaniu", los=random.Random(1))["opcje"]
    assert o["nazwy"] == "opisowe" and o["obiekt"] == ""                    # miejsce odrzucone przez IP -> opis bez nazw
    o = asystent.dobierz(slug, "czeka na dworcu w Poznaniu", los=random.Random(1))["opcje"]
    assert o["nazwy"] == "prawdziwe" and o["obiekt"] == "poznan_glowny"    # inne miejsce dalej z nazwa
    _rolka(slug, dict(NOWE, pomysl_id="dworzec", obiekt="poznan_glowny"), status="blad", powod="ip")
    assert asystent.dobierz(slug, "czeka na dworcu w Poznaniu")["opcje"]["nazwy"] == "opisowe"
    # usunieta gotowa rolka zostaje w nauce jako slaba
    c = _rolka(slug, dict(NOWE, stroj="odwazny:moro"), status="gotowe")
    asystent.archiwizuj_usuniety(slug, baza.pomysl(slug, c))
    baza.usun_pomysl(slug, c)
    assert asystent.nauka(slug)["punkty"]["stroj"]["moro"] == -3
    with pytest.raises(ValueError):
        asystent.ocen(slug, b, "super")


# ---------------- asystent: darmowy model OpenRouter (udawany) ----------------

class UdawanyOpenRouter:
    def __init__(self, odpowiedzi):
        self.odpowiedzi = list(odpowiedzi)      # tresc odpowiedzi modelu albo wyjatek
        self.zapytania = []

    def __call__(self, metoda, url, cialo=None, timeout=25):
        self.zapytania.append((metoda, url, cialo))
        if url.endswith("/models"):
            return {"data": [{"id": m} for m in asystent.MODELE_LLM]}
        if url.endswith("/key"):
            return {"data": {"label": "x", "is_free_tier": True}}
        o = self.odpowiedzi.pop(0)
        if isinstance(o, Exception):
            raise o
        return {"choices": [{"message": {"content": o}}]}


def test_asystent_z_openrouter_waliduje_pola(slug, monkeypatch):
    sekrety.zapisz_klucz("openrouter", "sk-or-v1-test")
    odp = '```json\n{"miejsce": "metro", "stroj": "neon", "kamera": "zza_filaru", "reakcja": "szturcha_kolege", ' \
          '"komentarz": "Widziałeś to?", "dlugosc": 8, "dlaczego": "Metro jest pełne ludzi, neon przyciąga wzrok."}\n```'
    u = UdawanyOpenRouter([odp])
    monkeypatch.setattr(asystent, "_http_json", u)
    w = asystent.dobierz(slug, "", zablokowane={"sezon": "jesien"})
    o = w["opcje"]
    assert w["zrodlo"] == "openrouter:" + asystent.MODELE_LLM[0] and w["dlaczego"].startswith("Metro jest pełne")
    assert o["miejsce"] == "metro" and o["obiekt"] in sc.STACJE_METRA and o["stroj"] == "odwazny:neon"
    assert o["kamera"] == "zza_filaru" and o["reakcja"] == "szturcha_kolege" and o["komentarz"] == "Widziałeś to?" and o["dlugosc"] == 8
    zapytanie = [z for z in u.zapytania if z[1].endswith("/chat/completions")][0][2]
    assert zapytanie["model"] == asystent.MODELE_LLM[0] and len(json.dumps(zapytanie)) < 9000     # male zapytanie
    # smieci od modelu: zle id, za dlugi komentarz, miejsce wbrew pomyslowi -> zostaja wybory regul
    u2 = UdawanyOpenRouter(['{"miejsce": "ksiezyc", "stroj": "bikini", "kamera": "dron", "reakcja": "smiech", '
                            '"komentarz": "To jest bardzo dlugi komentarz ktory ma duzo za duzo slow naprawde", "dlaczego": ""}'])
    monkeypatch.setattr(asystent, "_http_json", u2)
    w = asystent.dobierz(slug, "czeka na tramwaj na przystanku", los=random.Random(2))
    o = w["opcje"]
    assert o["miejsce"] == "przystanek" and o["stroj"].startswith("odwazny:") and o["kamera"] in sc.KAMERY_UKRYTE
    assert o["reakcja"] == "smiech" and o["komentarz"] in sum(sc.LINIE_REAKCJI.values(), [])
    assert w["zrodlo"].startswith("openrouter:") and w["dlaczego"]        # reakcja przyjeta, reszta z regul
    # model nie odpowiada (limit darmowych) -> reguly + uwaga, nic sie nie sypie
    u3 = UdawanyOpenRouter([RuntimeError("darmowe modele OpenRouter przeciazone albo dzienny limit")] * 3)
    monkeypatch.setattr(asystent, "_http_json", u3)
    w = asystent.dobierz(slug, "zamawia w galerii")
    assert w["zrodlo"] == "reguly" and "nie odpowiedział" in w["uwaga"] and w["opcje"]["miejsce"] == "galeria_foodcourt"


def test_openrouter_test_klucza(slug, monkeypatch):
    assert asystent.test_klucza()[0] is False
    sekrety.zapisz_klucz("openrouter", "sk-or-v1-test")
    monkeypatch.setattr(asystent, "_http_json", UdawanyOpenRouter([]))
    ok, kom = asystent.test_klucza()
    assert ok and "klucz dziala" in kom


# ---------------- ElevenLabs + miks komentarza ----------------

def test_elevenlabs_stan_klucza_i_tts(dane, monkeypatch):
    assert elevenlabs.stan_klucza()[0] == "brak"
    sekrety.zapisz_klucz("elevenlabs", "sk_" + "a" * 40)
    odpowiedzi = []

    def zapytanie(metoda, url, **k):
        odpowiedzi.append(url)
        raise http.BladHTTP(401, json.dumps({"detail": {"status": "missing_permissions", "message": "missing user_read"}}), url)
    monkeypatch.setattr(http, "zapytanie", zapytanie)
    assert elevenlabs.stan_klucza(odswiez=True)[0] == "ok"            # klucz prawdziwy, tylko bez user_read
    assert elevenlabs.stan_klucza()[0] == "ok" and len(odpowiedzi) == 1  # cache 10 min
    monkeypatch.setattr(http, "zapytanie", lambda *a, **k: (_ for _ in ()).throw(
        http.BladHTTP(401, json.dumps({"detail": {"status": "invalid_api_key", "message": "Invalid API key"}}), "u")))
    stan, kom = elevenlabs.stan_klucza(odswiez=True)
    assert stan == "zly" and "Invalid API key" in kom
    monkeypatch.setattr(http, "zapytanie", lambda *a, **k: (_ for _ in ()).throw(http.BladHTTP(400, json.dumps({"detail": {
        "status": "invalid_api_key", "message": "API key ID used as API key - only valid API keys can be used."}}), "u")))
    stan, kom = elevenlabs.stan_klucza(odswiez=True)
    assert stan == "zly" and "ID klucza" in kom                      # user wkleil ID klucza zamiast klucza (2026-10-07)
    sekrety.zapisz_klucz("elevenlabs", "zly-klucz-123")
    stan, kom = elevenlabs.stan_klucza(odswiez=True)
    assert stan == "zly" and "sk_" in kom
    sekrety.zapisz_klucz("elevenlabs", "sk_" + "b" * 40)
    wyslane = []

    def bajty(metoda, url, dane=None, naglowki=None, **k):
        wyslane.append((url, dane, naglowki))
        return b"ID3" + b"\x00" * 2000, "audio/mpeg"
    monkeypatch.setattr(http, "zapytanie_bajty", bajty)
    cel = elevenlabs.tts("[whispers] Widziałaś to?", "v123", os.path.join(str(dane), "k.mp3"))
    assert os.path.getsize(cel) > 1000
    url, cialo, nagl = wyslane[0]
    assert url == "https://api.elevenlabs.io/v1/text-to-speech/v123?output_format=mp3_44100_128"
    assert cialo == {"text": "[whispers] Widziałaś to?", "model_id": "eleven_v3"} and nagl["xi-api-key"].startswith("sk_")
    monkeypatch.setattr(http, "zapytanie_bajty", lambda *a, **k: (b'{"detail": "x"}', "application/json"))
    with pytest.raises(Exception):
        elevenlabs.tts("x", "v1", os.path.join(str(dane), "k2.mp3"))


def test_wybor_glosu_polski_nie_persona():
    """3.1: tylko premade/professional, polski, wlasciwa plec; nigdy cloned (klony person/testy) ani o imieniu persony."""
    lista = [{"voice_id": "1", "name": "Noemi", "category": "professional", "labels": {"language": "pl", "gender": "female"}},
             {"voice_id": "2", "name": "Sarah", "category": "premade", "labels": {"gender": "female", "accent": "american"}},
             {"voice_id": "3", "name": "Ola", "category": "professional", "labels": {"accent": "polish", "gender": "female"}},
             {"voice_id": "4", "name": "Adam PL", "category": "professional", "labels": {"language": "pl", "gender": "male"}},
             {"voice_id": "5", "name": "Mój klon", "category": "cloned", "labels": {"language": "pl", "gender": "male"}},
             {"voice_id": "6", "name": "Kuba", "category": "generated", "labels": {"language": "pl", "gender": "male"}},
             {"voice_id": "7", "name": "Bianka test", "category": "professional", "labels": {"language": "pl", "gender": "female"}},
             {"voice_id": "8", "name": "Marek", "category": "premade", "labels": {"gender": "male"}, "jezyki": ["pl"]}]
    assert elevenlabs.wybierz_glos(lista, ["Noemi", "Bianka"], plec="female")["voice_id"] == "3"
    assert elevenlabs.wybierz_glos(lista, ["Noemi", "Bianka"], plec="male")["voice_id"] == "4"     # professional przed premade
    assert elevenlabs.wybierz_glos([v for v in lista if v["voice_id"] != "4"], ["Noemi"], plec="male")["voice_id"] == "8"
    # nie ma polskiego glosu tej plci (tylko klon / generated / angielski) -> None, nic nie zgadujemy
    assert elevenlabs.wybierz_glos([lista[1], lista[4], lista[5]], [], plec="male") is None
    assert elevenlabs.wybierz_glos([lista[1]], [], plec="female") is None
    assert elevenlabs.wybierz_glos([], []) is None


def test_glos_id_osoby_nagrywajacej(slug, monkeypatch):
    """komentarz_glos.glos_id: Voice ID z ustawien persony (glos_chlopak / glos_dziewczyna) > GLOSY_DOMYSLNE > dobor z konta
    (plec wg `nagrywa`, pomija imiona WSZYSTKICH person i klony)."""
    baza.utworz_modelke("Bianka")
    lista = [{"voice_id": "bianka", "name": "Bianka", "category": "professional", "labels": {"language": "pl", "gender": "male"}},
             {"voice_id": "klon", "name": "Ja", "category": "cloned", "labels": {"language": "pl", "gender": "male"}},
             {"voice_id": "on", "name": "Tomek", "category": "professional", "labels": {"language": "pl", "gender": "male"}},
             {"voice_id": "ona", "name": "Ola", "category": "professional", "labels": {"language": "pl", "gender": "female"}}]
    monkeypatch.setattr(elevenlabs, "glosy", lambda: lista)
    assert baza.ustawienia_modelki(slug)["nagrywa"] == "chlopak"
    # domyslne glosy wybrane przez usera: chlopak = Max, dziewczyna = Jessica
    assert komentarz_glos.glos_id(slug) == "wJmRkw9W1EUa95AGkMrg" and komentarz_glos.glos_id(slug, "dziewczyna") == "cgSgspJ2msm6clMCkdW9"
    baza.zapisz_ustawienia(slug, nagrywa="dziewczyna", glos_dziewczyna="moja_ona")
    assert komentarz_glos.glos_id(slug) == "moja_ona" and komentarz_glos.glos_id(slug, "chlopak") == "wJmRkw9W1EUa95AGkMrg"
    # bez ustawionych ID: dobor z konta (plec wg `nagrywa`, bez imion person i klonow)
    monkeypatch.setitem(komentarz_glos.GLOSY_DOMYSLNE, "chlopak", "")
    monkeypatch.setitem(komentarz_glos.GLOSY_DOMYSLNE, "dziewczyna", "")
    baza.zapisz_ustawienia(slug, glos_dziewczyna="")
    assert komentarz_glos.glos_id(slug, "chlopak") == "on" and komentarz_glos.glos_id(slug, "dziewczyna") == "ona"
    monkeypatch.setattr(elevenlabs, "glosy", lambda: lista[:2])           # tylko glos o imieniu persony i klon -> blad
    with pytest.raises(komentarz_glos.BladGlosu, match="meskiego"):
        komentarz_glos.glos_id(slug, "chlopak")


def test_tts_osoby_zapas_gdy_id_nie_dziala(slug, monkeypatch):
    """Ustawiony / domyslny Voice ID nie dziala (glos zniknal z konta) -> zapas: glos z konta tej plci. Zly klucz -> bez prob."""
    from dostawcy import BladDostawcy
    lista = [{"voice_id": "zapas_on", "name": "Tomek", "category": "professional", "labels": {"language": "pl", "gender": "male"}}]
    monkeypatch.setattr(elevenlabs, "glosy", lambda: lista)
    proby = []

    def tts(tekst, vid, cel, **k):
        proby.append(vid)
        if vid != "zapas_on":
            raise BladDostawcy("ElevenLabs 404: A voice with the voice_id was not found")
        open(cel, "wb").write(b"ID3")
        return cel
    monkeypatch.setattr(elevenlabs, "tts", tts)
    baza.zapisz_ustawienia(slug, glos_chlopak="stary_id")
    cel = os.path.join(baza.folder_audio(slug), "k.mp3")
    assert komentarz_glos.tts_osoby(slug, "[whispers] Widziałeś to?", cel, "chlopak") == "zapas_on"
    assert proby == ["stary_id", "wJmRkw9W1EUa95AGkMrg", "zapas_on"]
    monkeypatch.setattr(elevenlabs, "tts", lambda *a, **k: (_ for _ in ()).throw(BladDostawcy("ElevenLabs 401: zly klucz API")))
    with pytest.raises(BladDostawcy, match="401"):
        komentarz_glos.tts_osoby(slug, "x", cel, "chlopak")


def test_glos_auto_i_filtr_miksu(dane, monkeypatch):
    # 3.1: model wideo NIGDY nie mowi - bez klucza tez "tts" (rolka wyjdzie bez komentarza, nie z mowa modelu)
    assert komentarz_glos.rozstrzygnij_glos("auto") == "tts" and komentarz_glos.rozstrzygnij_glos("model") == "tts"
    monkeypatch.setattr(elevenlabs, "stan_klucza", lambda odswiez=False: ("ok", "klucz dziala"))
    assert komentarz_glos.rozstrzygnij_glos("auto") == "tts"
    f = komentarz_glos.filtr_miksu(5, -21)
    assert "adelay=5000|5000" in f and "loudnorm=I=-21.0" in f and "sidechaincompress" in f and "[out]" in f
    # brzmienie telefonu, ktory filmuje: stromo przyciete doly (~250 Hz) i gora (~6,8 kHz), nacisk ~3 kHz, AGC, odbicia, szum toru
    assert f.count("highpass=f=250") == 2 and f.count("lowpass=f=6800") == 2 and "equalizer=f=3000" in f
    assert "acompressor=" in f and "aecho=" in f and "anoisesrc=" in f and "amix=inputs=3" in f
    assert 200 <= komentarz_glos.TELEFON_DOLY_HZ <= 300 and 6000 <= komentarz_glos.TELEFON_GORA_HZ <= 7000
    assert komentarz_glos.docelowa_glosnosc(None) == -21.0 and komentarz_glos.docelowa_glosnosc(-40) == -27.0
    assert komentarz_glos.docelowa_glosnosc(-10) == -15.0 and komentarz_glos.docelowa_glosnosc(-22) == -19.0
    assert komentarz_glos.tekst_dla_tts("Widziałaś to?") == "[whispers] Widziałaś to?"
    assert komentarz_glos.tekst_dla_tts("[laughs] ") == ""


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="brak ffmpeg")
def test_miks_ffmpeg_naprawde(tmp_path):
    import subprocess
    w, g, w2 = str(tmp_path / "w.mp4"), str(tmp_path / "g.mp3"), str(tmp_path / "cichy.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=180x320:rate=15:duration=4", "-f", "lavfi",
                    "-i", "anoisesrc=color=pink:amplitude=0.05:duration=4:sample_rate=48000", "-c:v", "libx264", "-pix_fmt",
                    "yuv420p", "-c:a", "aac", "-shortest", w], check=True, timeout=120)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=1", "-c:a", "libmp3lame", g],
                   check=True, timeout=120)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=180x320:rate=15:duration=4", "-c:v",
                    "libx264", "-pix_fmt", "yuv420p", w2], check=True, timeout=120)
    cel, otoczenie, lufs = komentarz_glos.zmiksuj(w, g, str(tmp_path / "out.mp4"), 2)
    assert os.path.isfile(cel) and otoczenie is not None and komentarz_glos.ma_dzwiek(cel)
    assert abs(komentarz_glos.czas_wideo(cel) - 4.0) < 0.3
    cel2, otoczenie2, _ = komentarz_glos.zmiksuj(w2, g, str(tmp_path / "out2.mp4"), 1)     # wideo bez dzwieku -> cisza + glos
    assert otoczenie2 is None and komentarz_glos.ma_dzwiek(cel2)
    # darmowe demo brzmienia (ten sam miks, bez TTS): cisza + glos od 0,5 s
    pr = komentarz_glos.probka(g, str(tmp_path / "probka.mp3"), t_s=0.5)
    assert os.path.isfile(pr) and abs(komentarz_glos.czas_wideo(pr) - (1.0 + 0.5 + 1.2)) < 0.3
    assert komentarz_glos.glosnosc_lufs(pr) is not None


# ---------------- fabryka: glos tts po generacji, dogranie recznie ----------------

def _udawane_dogranie(monkeypatch, blad=None):
    wywolania = []

    def dograj(slug, pid, wideo, komentarz, t_s, log=None):
        wywolania.append((pid, wideo, komentarz, t_s))
        if blad:
            raise komentarz_glos.BladGlosu(blad)
        cel = wideo.replace(".raw.mp4", ".glos.mp4")
        with open(cel, "wb") as f:
            f.write(b"mp4+glos")
        return cel
    monkeypatch.setattr(komentarz_glos, "dograj", dograj)
    return wywolania


def test_rolka_z_glosem_tts_dogrywa_komentarz_przed_media_tool(slug, cli, monkeypatch):
    monkeypatch.setattr(elevenlabs, "stan_klucza", lambda odswiez=False: ("ok", "klucz dziala"))
    wywolania = _udawane_dogranie(monkeypatch)
    opcje = dict(NOWE, glos="auto")
    w = fabryka.wycena_z_promptu(slug, opcje)
    assert w["glos"] == "tts" and w["ustalone"]["glos"] == "tts" and "{" not in w["prompt"]
    pid = fabryka.dodaj_z_promptu(slug, dict(opcje, ustalone=w["ustalone"], asystent={"dlaczego": "bo tak", "zrodlo": "reguly"}),
                                  kr=w["kr"])
    p = baza.pomysl(slug, pid)
    assert p["prompt_higgsfield"] == w["prompt"] and p["z_promptu"]["glos"] == "tts" and p["z_promptu"]["komentarz_t"] == 5
    assert p["z_promptu"]["asystent"]["dlaczego"] == "bo tak" and "asystent" not in p["z_promptu"]["opcje"]
    assert fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: k <= 45)["wygenerowane"] == 1
    p = baza.pomysl(slug, pid)
    assert len(wywolania) == 1 and wywolania[0][2] == "Widziałaś to? Jak ona wygląda…" and wywolania[0][3] == 5
    assert p["status"] == "gotowe" and p["glos_dograny"] is True and open(p["plik_wynikowy"], "rb").read() == b"mp4+glos"
    assert len(cli.generacje) == 1
    # klucz pozniej przestal dzialac: "auto" z ustalonych daje ten sam prompt (glos zamrozony)
    monkeypatch.setattr(elevenlabs, "stan_klucza", lambda odswiez=False: ("zly", "x"))
    w2 = fabryka.wycena_z_promptu(slug, dict(opcje, ustalone=w["ustalone"]), z_cena=False)
    assert w2["prompt"] == w["prompt"]


def test_blad_glosu_nie_psuje_oplaconej_rolki_i_dogranie_recznie(slug, cli, monkeypatch):
    monkeypatch.setattr(elevenlabs, "stan_klucza", lambda odswiez=False: ("ok", "klucz dziala"))
    _udawane_dogranie(monkeypatch, blad="ElevenLabs 401: zly klucz API")
    pid = fabryka.dodaj_z_promptu(slug, dict(NOWE, glos="tts"), kr=45)
    assert fabryka.generuj(slug, ids=[pid])["wygenerowane"] == 1
    p = baza.pomysl(slug, pid)
    assert p["status"] == "gotowe" and p["glos_dograny"] is False and "401" in p["glos_blad"]
    assert open(p["plik_wynikowy"], "rb").read() == b"mp4"          # sam dzwiek otoczenia, ale rolka gotowa
    # user wkleja dobry klucz -> "Dograj glos": zero nowych generacji
    wywolania = _udawane_dogranie(monkeypatch)
    gotowy = fabryka.dograj_glos(slug, pid)
    p = baza.pomysl(slug, pid)
    assert p["glos_dograny"] is True and open(gotowy, "rb").read() == b"mp4+glos" and len(cli.generacje) == 1
    assert wywolania[0][1].endswith(".raw.mp4")
    # 3.1: "model" z opcji = i tak glos tts (wideo bez mowy, komentarz ElevenLabs)
    pid2 = fabryka.dodaj_z_promptu(slug, dict(NOWE, glos="model"), kr=45)
    assert baza.pomysl(slug, pid2)["z_promptu"]["glos"] == "tts" and "{" not in baza.pomysl(slug, pid2)["prompt_higgsfield"]
    fabryka.generuj(slug, ids=[pid2])
    # STARA rolka (sprzed 3.1) z glosem modelu: dogranie odmawia (zdublowalby glos)
    zp = dict(baza.pomysl(slug, pid2)["z_promptu"], glos="model")
    baza.aktualizuj_pomysl(slug, pid2, z_promptu=zp)
    with pytest.raises(ValueError, match="zdublowal"):
        fabryka.dograj_glos(slug, pid2)


def test_cli_z_promptu_z_asystentem_sucho(slug, cli, capsys):
    assert fabryka.main(["--modelka", slug, "z-promptu", "zamawia w galerii we Wrocławiu", "--asystent", "--sucho"]) == 0
    out = capsys.readouterr().out
    assert "asystent (reguly)" in out and "Wroclavia" in out and "cena: 45 kr" in out
    assert cli.generacje == [] and baza.lista_pomyslow(slug) == []


# ---------------- panel ----------------

@pytest.fixture
def klient(slug, cli):
    panel._saldo.clear()
    panel.konsola.__init__()
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        yield c


def test_api_asystent_ocena_usuniecie(klient, slug, cli):
    d = klient.post("/api/z-promptu/asystent", json={"tekst": "kupuje kawę na dworcu we Wrocławiu"}).get_json()
    assert d["ok"] and d["opcje"]["miejsce"] == "dworzec" and d["opcje"]["obiekt"] == "wroclaw_glowny"
    # bez klucza ElevenLabs: NIE "mowi model" - jasno, ze rolka wyjdzie bez komentarza
    assert d["zrodlo"] == "reguly" and d["glos_tts"]["ok"] is False and "ElevenLabs nie działa" in d["podsumowanie"]
    assert "bez komentarza" in d["glos_tts"]["komunikat"] and "mówi model" not in d["podsumowanie"]
    assert cli.generacje == [] and baza.lista_pomyslow(slug) == []
    kat = klient.get("/api/z-promptu").get_json()
    assert kat["domyslne"]["stroj"] == "biblioteka" and kat["glos_tts"]["ok"] is False and kat["asystent_llm"] is False
    w = klient.post("/api/z-promptu/wycena", json=dict(d["opcje"], pora="popoludnie")).get_json()
    assert w["ok"] and w["glos"] == "tts" and w["obiekt"] == "wroclaw_glowny" and "Wrocław Główny" in w["prompt"]
    assert "{" not in w["prompt"] and any("bez komentarza" in u for u in w["ostrzezenia"])
    r = klient.post("/api/z-promptu", json=dict(d["opcje"], pora="popoludnie", ustalone=w["ustalone"], kr=w["kr"],
                                                asystent={"dlaczego": d["dlaczego"], "zrodlo": d["zrodlo"]})).get_json()
    panel.konsola.watek.join(10)
    karta = [x for x in klient.get("/api/pomysly").get_json()["pomysly"] if x["id"] == r["id"]][0]
    assert karta["z_promptu_dlaczego"] == d["dlaczego"] and "głos ElevenLabs" in karta["z_promptu_opis"]
    # klucza nie bylo: rolka gotowa BEZ komentarza, wpis w dzienniku, "Dograj glos" dostepne
    p = baza.pomysl(slug, r["id"])
    assert p["status"] == "gotowe" and p["glos_dograny"] is False and "ElevenLabs" in p["glos_blad"]
    assert karta["mozna_dograc_glos"] is True and len(cli.generacje) == 1
    assert any("BEZ komentarza" in w_["tekst"] for w_ in baza.dziennik_ostatnie(50, modelka=slug))
    o = klient.post(f"/api/pomysly/{r['id']}/ocena", json={"ocena": "dobra"}).get_json()
    assert o["ok"] and o["pomysl"]["ocena"] == "dobra"
    assert klient.post(f"/api/pomysly/{r['id']}/ocena", json={"ocena": "zla"}).status_code == 400
    assert klient.delete(f"/api/pomysly/{r['id']}").get_json()["ok"]
    arch = json.load(open(os.path.join(baza.folder_modelki(slug), asystent.PLIK_ARCHIWUM), encoding="utf-8"))
    assert arch["wyniki"][-1]["wynik"] == "dobra" and arch["wyniki"][-1]["wybory"]["miejsce"] == "dworzec"


def test_api_klucze_openrouter_i_elevenlabs(klient, monkeypatch):
    r = klient.post("/api/konta", json={"dostawca": "elevenlabs", "klucz": "21m00Tcm4TlvDq8ikWAM"})
    assert r.status_code == 400 and "sk_" in r.get_json()["blad"] and not sekrety.klucz("elevenlabs")
    assert klient.post("/api/konta", json={"dostawca": "elevenlabs", "klucz": "sk_" + "c" * 40}).get_json()["ok"]
    assert klient.post("/api/konta", json={"dostawca": "openrouter", "klucz": "abc"}).status_code == 400
    d = klient.post("/api/konta", json={"dostawca": "openrouter", "klucz": "sk-or-v1-" + "d" * 30}).get_json()
    maska = d["konta"]["openrouter"]["maska"]
    assert d["ok"] and d["konta"]["openrouter"]["jest"] and "d" * 30 not in maska and len(maska) < 15
    monkeypatch.setattr(asystent, "test_klucza", lambda: (True, "klucz dziala"))
    assert klient.post("/api/konta/test", json={"dostawca": "openrouter"}).get_json()["dziala"] is True
    u = klient.post("/api/ustawienia", json={"nagrywa": "dziewczyna", "glos_dziewczyna": "v123"}).get_json()["ustawienia"]
    assert u["nagrywa"] == "dziewczyna" and u["glos_dziewczyna"] == "v123"
    assert klient.get("/api/z-promptu").get_json()["persona"]["nagrywa"] == "dziewczyna"
    assert klient.post("/api/ustawienia", json={"nagrywa": "kot"}).status_code == 400
    assert klient.post("/api/ustawienia", json={"stroj_swap": "z_filmu"}).get_json()["ustawienia"]["stroj_swap"] == "z_filmu"
    assert klient.post("/api/ustawienia", json={"stroj_swap": "cokolwiek"}).status_code == 400


def test_api_akcja_dograj_glos(klient, slug, cli, monkeypatch):
    monkeypatch.setattr(elevenlabs, "stan_klucza", lambda odswiez=False: ("ok", "klucz dziala"))
    _udawane_dogranie(monkeypatch, blad="chwilowy blad")
    pid = fabryka.dodaj_z_promptu(slug, dict(NOWE, glos="tts"), kr=45)
    fabryka.generuj(slug, ids=[pid])
    karta = [x for x in klient.get("/api/pomysly").get_json()["pomysly"] if x["id"] == pid][0]
    assert karta["mozna_dograc_glos"] is True and "do dogrania" in karta["z_promptu_opis"]
    _udawane_dogranie(monkeypatch)
    assert klient.post("/api/akcja", json={"typ": "dograj_glos", "id": pid}).get_json()["ok"]
    panel.konsola.watek.join(10)
    assert baza.pomysl(slug, pid)["glos_dograny"] is True and len(cli.generacje) == 1


def test_saldo_elevenlabs_bez_prawa_odczytu_konta_to_dziala_nie_blad(monkeypatch):
    """Klucz ElevenLabs z ograniczonymi uprawnieniami (bez user_read): saldo znakow niewidoczne, ale TTS dziala ->
    pastylka w panelu "dziala" (zielona), a nie czerwone "nie widze znakow". Zly klucz dalej jest bledem."""
    import app as panel
    import dostawcy
    import sekrety

    class D:
        JEDNOSTKA = "zn"
        stan = ("ok", "klucz dziala (bez uprawnienia do odczytu konta)")

        def saldo_szczegoly(self):
            raise dostawcy.BladDostawcy("ElevenLabs: missing_permissions (user_read)")

        def stan_klucza(self, odswiez=False):
            return self.stan

    d = D()
    monkeypatch.setattr(panel, "_saldo", {})
    monkeypatch.setattr(dostawcy, "dostawca", lambda n: d)
    monkeypatch.setattr(sekrety, "klucz", lambda n: "sk_test")
    w = panel._pobierz_saldo("elevenlabs")
    assert w.get("dziala") is True and w["blad"] is None and w["kredyty"] is None
    D.stan = ("zly", "zly klucz")
    w = panel._pobierz_saldo("elevenlabs")
    assert not w.get("dziala") and w["blad"]
