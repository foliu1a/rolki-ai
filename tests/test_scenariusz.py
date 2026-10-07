# -*- coding: utf-8 -*-
"""Rolka z promptu - budowanie promptu (scenariusz.py): tozsamosc i wlosy persony, wzrost, numeracja zdjec, katalog polskich
miejsc, wolny tekst po polsku, zamrozone losowe szczegoly, limity znakow, slowa ryzykowne i marki. Zero kredytow."""
import os
import random
import re

import pytest

import baza
import fabryka
import scenariusz as sc

PROMPT_A = """# 1. TASK
Complete character replacement.

# 2. NOEMI – EXACT IDENTITY

Preserve Noemi's recognizable individual characteristics exactly as shown in the reference images:

* Long blonde hair with warm golden and slightly peach tones
* Center part with long face-framing strands
* Fair skin with a natural warm complexion
* Light grey-blue eyes
* Silver nose piercings, including a septum ring

Her only tattoo is a small star on her wrist, shown in @[Image 2](image_2) (see section 4).

Do not change, invent, exaggerate, beautify or reinterpret her appearance.

# 3. OUTFIT
whatever
"""


@pytest.fixture
def persona(modelka):
    baza.zapisz_prompt(modelka, "stroj_z_filmu.txt", PROMPT_A)
    return modelka


def test_tozsamosc_bez_wlosow_i_wlosy_osobno(persona):
    toz = sc.tozsamosc(persona, bez_wlosow=True)
    assert "grey-blue eyes" in toz and "septum ring" in toz
    assert "hair" not in toz.lower() and "center part" not in toz.lower()
    # zdanie o tatuazu zostaje, @[Image 2](image_2) -> token Higgsfielda
    assert "<<<image_2>>>" in toz and "see section" not in toz
    wl = sc.wlosy_wlasne(persona)
    assert "warm golden" in wl and "center part" in wl and "reference photos" in wl


def test_profil_wlosy_wygrywa_z_promptem_i_tozsamosc_txt(persona):
    """Noemi: prompt A mowi o zlotych wlosach, a zdjecia sa platynowe -> profil.wlosy (user) wygrywa."""
    baza.zapisz_profil(persona, wlosy="long straight pale platinum blonde hair")
    assert sc.wlosy_wlasne(persona).startswith("long straight pale platinum blonde hair")
    with open(sc._plik_tozsamosci(persona), "w", encoding="utf-8") as f:
        f.write("Fair skin; light grey-blue eyes; long platinum hair; septum ring")
    assert sc.tozsamosc(persona) == "Fair skin; light grey-blue eyes; long platinum hair; septum ring"
    assert "platinum" not in sc.tozsamosc(persona, bez_wlosow=True)


def test_wzrost_skala_wzgledem_ludzi():
    noemi = sc.zdanie_wzrostu("158-160")
    assert "petite" in noemi and "158-160 cm" in noemi and "chin of an average man" in noemi
    alicja = sc.zdanie_wzrostu("170-172")
    assert "tall for a woman" in alicja and "forehead" in alicja
    assert "eyes" in sc.zdanie_wzrostu("168-170") and "mouth" in sc.zdanie_wzrostu([160, 162])
    assert sc.zdanie_wzrostu("") == "" and sc.zdanie_wzrostu("duzo") == "" and sc.zdanie_wzrostu("90") == ""


def test_numeracja_zdjec_stroj_ostatni_i_jeden_komentarz(persona):
    stroj = os.path.join(baza.folder_strojow(persona), "kurtka.png")
    open(stroj, "wb").write(b"img")
    w = sc.zbuduj(persona, {"pomysl_id": "galeria_fastfood", "dlugosc": 10, "stroj": "plik:kurtka.png"})
    tokeny = sorted({int(x) for x in re.findall(r"<<<image_(\d+)>>>", w["prompt"])})
    assert tokeny == [1, 2, 3] and len(w["obrazy"]) == 3 and w["obrazy"][-1] == stroj
    assert "<<<image_3>>> is only the outfit reference" in w["prompt"]
    assert "ignore the hair, face, skin, tattoos and body shape of the person or mannequin" in w["prompt"]
    assert "\n\n" not in w["prompt"]
    # 3.1: model wideo nic nie mowi - komentarz NIE jest w prompcie (dogrywa go ElevenLabs po generacji)
    assert "Dialogue language" not in w["prompt"] and not re.findall(r"\{[^}]+\}", w["prompt"])
    assert w["komentarz"] == "Jak ona wygląda." and w["glos"] == "tts" and "says nothing at all" in w["prompt"]
    assert "@[Image" not in w["prompt"]
    # zly plik stroju (spoza folderu Stroje) -> blad, nic nie zgadujemy
    with pytest.raises(ValueError):
        sc.zbuduj(persona, {"stroj": "plik:..\\referencje\\01_twarz.png"})


def test_rozdzielczosc_wg_dlugosci_i_modele(persona):
    assert sc.zbuduj(persona, {"dlugosc": 8})["rozdzielczosc"] == "1080p"
    assert sc.zbuduj(persona, {"dlugosc": 10})["rozdzielczosc"] == "720p"
    assert sc.zbuduj(persona, {"dlugosc": 15})["rozdzielczosc"] == "720p"
    assert sc.zbuduj(persona, {"dlugosc": 15, "rozdzielczosc": "1080p"})["rozdzielczosc"] == "1080p"   # user moze nadpisac
    with pytest.raises(ValueError, match="15 s"):
        sc.zbuduj(persona, {"model": "gemini_omni_flash_1_1", "dlugosc": 15})
    with pytest.raises(ValueError):
        sc.zbuduj(persona, {"model": "gemini_omni_flash_1_1", "dlugosc": 10, "rozdzielczosc": "480p"})
    with pytest.raises(ValueError):
        sc.zbuduj(persona, {"model": "kling_cos_tam"})
    w = sc.zbuduj(persona, {"model": "seedance_2_5", "dlugosc": 10})
    assert w["mode"] == "omni_reference" and w["parametry"] == {"bitrate_mode": "high"} and w["generate_audio"] is True


def test_wlosy_do_wyboru_nie_zmieniaja_twarzy(persona):
    wlasne = sc.zbuduj(persona, {"pomysl_id": "rynek_obwarzanek"})
    assert "skin, hair, piercings" in wlasne["prompt"] and not wlasne["wlosy_zmienione"]
    assert "warm golden" in wlasne["prompt"]          # jej wlosy z opisu persony
    miku = sc.zbuduj(persona, {"pomysl_id": "rynek_obwarzanek", "wlosy": {"kolor": "miku"}})
    p = miku["prompt"]
    assert miku["wlosy_zmienione"] and "turquoise-teal" in p and "twin tails" in p and "straight bangs" in p
    assert "only her hair is changed" in p and "skin, hair, piercings" not in p
    assert "warm golden" not in p and "grey-blue eyes" in p        # inne wlosy, ta sama twarz
    assert "miku" not in p.lower()                                  # nazwa postaci tylko w etykiecie panelu (filtr IP)
    kok = sc.zbuduj(persona, {"wlosy": {"kolor": "wlasne", "fryzura": "kok", "grzywka": "bez"}})["prompt"]
    assert "her own natural hair colour" in kok and "messy bun" in kok and "no bangs" in kok
    with pytest.raises(ValueError):
        sc.zbuduj(persona, {"wlosy": {"kolor": "tęczowe"}})


def test_wolny_tekst_po_polsku(persona):
    a = sc.pomysl_z_tekstu("Tańczy w tramwaju z kawą, babcia się krzywo patrzy")
    assert a["miejsce"] == "tramwaj" and a["reakcja"] == "krzywo"
    assert any("coffee" in c for c in a["czynnosci"]) and any("dances" in c for c in a["czynnosci"])
    assert sc.pomysl_z_tekstu("czeka na tramwaj na przystanku")["miejsce"] == "przystanek"
    assert sc.pomysl_z_tekstu("je zapiekankę na Kazimierzu")["miejsce"] == "plac_nowy"
    assert sc.pomysl_z_tekstu("w pociągu pokazuje bilet konduktorowi")["miejsce"] == "pociag"
    assert sc.pomysl_z_tekstu("kupuje bułki w Biedronce")["miejsce"] == "dyskont"
    w = sc.zbuduj(persona, {"tekst": "Tańczy w tramwaju z kawą, babcia się krzywo patrzy", "dlugosc": 8})
    assert w["miejsce"] == "tramwaj" and "„Tańczy w tramwaju z kawą, babcia się krzywo patrzy”" in w["prompt"]
    assert "disapproving frown" in w["prompt"] and w["pomysl_id"] is None
    # nierozpoznane miejsce -> losowe + ostrzezenie dla usera
    w = sc.zbuduj(persona, {"tekst": "robi coś dziwnego"})
    assert w["miejsce"] in sc.MIEJSCA and any("Nie rozpoznalem miejsca" in o for o in w["ostrzezenia"])
    # tekst slowo w slowo jak gotowy pomysl (bez pomysl_id, np. pole przywrocone po odswiezeniu) = ten gotowy pomysl
    w = sc.zbuduj(persona, {"tekst": sc.POMYSLY_PO_ID["kebab"]["pl"]})
    assert w["pomysl_id"] == "kebab" and "0-3 s:" in w["prompt"]
    # gotowy pomysl przeniesiony w inne miejsce = jego tekst jako wolny pomysl w tym miejscu
    w = sc.zbuduj(persona, {"pomysl_id": "galeria_fastfood", "miejsce": "molo_sopot"})
    assert w["miejsce"] == "molo_sopot" and "W galerii handlowej" in w["prompt"] and w["pomysl_id"] is None


def test_ustalone_daje_ten_sam_prompt(persona):
    """Losowe szczegoly (miejsce, komentarz, stroj, pora, kamera) wracaja jako 'ustalone' -> ten sam prompt przy wycenie i
    przy 'Zrob rolke' (user placi za to, co widzial)."""
    opcje = {"miejsce": "losowe", "tekst": "spaceruje", "stroj": "codzienny", "komentarz": "losowy"}
    w1 = sc.zbuduj(persona, opcje)
    w2 = sc.zbuduj(persona, dict(opcje, ustalone=w1["ustalone"]))
    assert w1["prompt"] == w2["prompt"]
    inne = {sc.zbuduj(persona, opcje, los=random.Random(i))["prompt"] for i in range(6)}
    assert len(inne) > 1                     # bez ustalonych - za kazdym razem cos innego


def test_cosplay_tylko_na_zyczenie_i_codzienny_wg_pory_roku(persona):
    for i in range(10):
        p = sc.zbuduj(persona, {"pomysl_id": "dworzec"}, los=random.Random(i))["prompt"]
        assert "costume" not in p and "the same outfit she wears in the reference photos" in p
    p = sc.zbuduj(persona, {"pomysl_id": "dworzec", "stroj": "cosplay"})["prompt"]
    assert "costume" in p or "uniform" in p or "onesie" in p or "dress with a big bow" in p
    zima = sc.zbuduj(persona, {"pomysl_id": "dworzec", "stroj": "codzienny", "sezon": "zima"})
    zimowe = [s for s, pory in sc.STROJE_CODZIENNE if "zima" in pory]
    assert zima["ustalone"]["stroj_opis"] in zimowe and "winter" in zima["prompt"]


def test_losowanie_bez_powtorek_i_plaza_tylko_latem(persona):
    wszystkie = [p["id"] for p in sc.POMYSLY]
    p = sc.losuj_pomysl(persona, sezon="jesien", uzyte=[x for x in wszystkie if x != "poczta"])
    assert p["id"] == "poczta"
    for i in range(30):
        assert sc.losuj_pomysl(persona, sezon="jesien", los=random.Random(i))["miejsce"] != "plaza"
    w = sc.zbuduj(persona, {"pomysl_id": "parawany", "sezon": "auto"})
    assert w["sezon"] == "lato"           # plaza z parawanami zawsze latem


def test_katalog_prawdziwych_miejsc_bez_marek_i_slow_ryzykownych(persona):
    assert len(sc.MIEJSCA) >= 40 and len(sc.POMYSLY) >= 30
    for mid, m in sc.MIEJSCA.items():
        for pole in ("nazwa", "kat", "krotko", "opis", "detale", "swiatlo", "dzwieki", "akcje", "streszczenie", "reakcje", "kamera"):
            assert m.get(pole), (mid, pole)
        assert m["kat"] in sc.KATEGORIE and m["kamera"] in sc.KAMERY and len(m["akcje"]) == 3
    for p in sc.POMYSLY:
        assert p["miejsce"] in sc.MIEJSCA, p["id"]
    for p in sc.POMYSLY:
        for opcje in ({}, {"stroj": "codzienny", "dlugosc": 15}, {"stroj": "cosplay", "dlugosc": 8, "pora": "wieczor"}):
            w = sc.zbuduj(persona, dict(opcje, pomysl_id=p["id"]))
            uwagi = " ".join(w["ostrzezenia"])
            assert "filtr NSFW" not in uwagi and "marek" not in uwagi, (p["id"], uwagi)
            assert w["znaki"] <= sc.MODELE["seedance_2_5"]["zalecane_znaki"], (p["id"], w["znaki"])
            assert "Poland" in w["prompt"] and "iPhone" in w["prompt"] and "no colour grading" in w["prompt"]


def test_krotki_szablon_bez_numerow_zdjec(persona):
    for model in ("wan3_0_prime", "gemini_omni_flash_1_1"):
        w = sc.zbuduj(persona, {"pomysl_id": "kebab", "model": model, "dlugosc": 10, "wlosy": {"kolor": "czarno_rozowe"}})
        assert "<<<image" not in w["prompt"] and "@[Image" not in w["prompt"]
        assert "shown in the reference photos" in w["prompt"]          # tatuaz z @[Image 2] -> bez numeru
        assert w["znaki"] <= sc.MODELE[model]["limit_znakow"]
    assert sc.zbuduj(persona, {"model": "wan3_0_prime"})["mode"] is None
    assert sc.zbuduj(persona, {"model": "gemini_omni_flash_1_1"})["mode"] == "reference-to-video"


def test_sprawdz_wylapuje_bledy_promptu():
    bledy, _ = sc.sprawdz("x <<<image_3>>>", "seedance_2_5", 2)
    assert bledy and "nr 3" in bledy[0]
    bledy, _ = sc.sprawdz("x <<<image_1>>>", "wan3_0_prime", 2)
    assert bledy
    bledy, _ = sc.sprawdz("a" * 9000, "seedance_2_5", 2)
    assert bledy
    _, uwagi = sc.sprawdz("<<<image_1>>> sexy girl in a McDonald's", "seedance_2_5", 1)
    assert any("sexy" in u for u in uwagi) and any("mcdonald" in u for u in uwagi)
    _, uwagi = sc.sprawdz("<<<image_1>>> {Jak ona wygląda.} {O matko}", "seedance_2_5", 1)
    assert any("Komentarz" in u for u in uwagi)


def test_bez_zdjec_persony_nie_buduje(dane):
    slug = baza.utworz_modelke("Pusta")
    with pytest.raises(ValueError, match="zdjec"):
        sc.zbuduj(slug, {"pomysl_id": "dworzec"})


def test_slowa_ryzykowne_wspolne_z_fabryka():
    assert "sexy" in fabryka.SLOWA_RYZYKOWNE      # sprawdz() korzysta z listy fabryki (jedno zrodlo prawdy)
