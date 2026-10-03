# -*- coding: utf-8 -*-
import os
from datetime import datetime, timedelta

import pytest

import baza


def test_utworz_modelke_zaklada_foldery_i_pliki(dane):
    slug = baza.utworz_modelke("Bianka Nowa!")
    assert slug == "bianka_nowa"
    folder = baza.folder_modelki(slug)
    for n in ("wyniki", "zrodla", "referencje", "stroje", "prompty"):
        assert os.path.isdir(os.path.join(folder, n))
    assert baza.lista_modelek() == ["bianka_nowa"]
    assert baza.lista_pomyslow(slug) == []
    with pytest.raises(ValueError):
        baza.utworz_modelke("bianka nowa")
    with pytest.raises(ValueError):
        baza.utworz_modelke("!!!")


def test_aktywna_modelka(dane):
    baza.utworz_modelke("alicja")
    assert baza.aktywna_modelka() is None
    baza.ustaw_aktywna_modelke("alicja")
    assert baza.aktywna_modelka() == "alicja"
    with pytest.raises(ValueError):
        baza.ustaw_aktywna_modelke("nie_ma")


def test_ustawienia_domyslne_i_zapis(modelka):
    ust = baza.ustawienia_modelki(modelka)
    assert ust["min_kredyty"] == 200 and ust["max_kredyty_na_rolke"] == 150 and ust["powtorki"] == 2
    baza.zapisz_ustawienia(modelka, resolution="1080p")
    assert baza.ustawienia_modelki(modelka)["resolution"] == "1080p"
    with pytest.raises(ValueError):
        baza.zapisz_ustawienia(modelka, literowka=1)


def test_ustawienia_starej_modelki_bez_nowych_kluczy(modelka):
    # stary ustawienia.json bez np. 'powtorki' - domyslne sie uzupelniaja
    baza._zapisz_json(baza._plik_ustawien(modelka), {"resolution": "480p"})
    ust = baza.ustawienia_modelki(modelka)
    assert ust["resolution"] == "480p" and ust["powtorki"] == 2


def test_prompty_z_plikow(modelka):
    assert baza.prompt_bazowy(modelka).startswith("PROMPT A")
    assert baza.prompt_stroj(modelka).startswith("PROMPT B")
    # prompt jako tekst wprost w ustawieniach
    baza.zapisz_ustawienia(modelka, prompt_bazowy="tekst wprost")
    assert baza.prompt_bazowy(modelka) == "tekst wprost"
    # brakujacy plik -> pusty prompt (nie zgadujemy)
    baza.zapisz_ustawienia(modelka, prompt_bazowy="prompty/nie_ma.txt")
    assert baza.prompt_bazowy(modelka) == ""


def test_prompt_z_bom(modelka):
    sciezka = os.path.join(baza.folder_modelki(modelka), "prompty", "stroj_z_filmu.txt")
    with open(sciezka, "w", encoding="utf-8-sig") as f:
        f.write("z BOM-em\n")
    assert baza.prompt_bazowy(modelka) == "z BOM-em"


def test_referencje_posortowane_i_tylko_obrazy(modelka):
    folder = baza.folder_referencji(modelka)
    open(os.path.join(folder, "notatka.txt"), "w").close()
    open(os.path.join(folder, "00_pierwsza.webp"), "w").close()
    nazwy = [os.path.basename(p) for p in baza.sciezki_referencji(modelka)]
    assert nazwy == ["00_pierwsza.webp", "01_twarz.png", "02_sylwetka.jpg"]


def test_referencje_z_ustawien_maja_pierwszenstwo(modelka):
    baza.zapisz_ustawienia(modelka, referencje=["referencje/02_sylwetka.jpg", "nie_ma.png"])
    assert [os.path.basename(p) for p in baza.sciezki_referencji(modelka)] == ["02_sylwetka.jpg"]


def test_foldery_zrodel_i_gotowych(modelka, tmp_path):
    folder = baza.folder_modelki(modelka)
    assert baza.folder_zrodel(modelka) == os.path.join(folder, "zrodla")
    assert baza.folder_gotowych(modelka) == os.path.join(folder, "wyniki")
    przed, po = tmp_path / "przed" / "noemi", tmp_path / "po" / "noemi"
    baza.zapisz_ustawienia(modelka, zrodla_dir=str(przed), wyniki_dir=str(po))
    assert baza.folder_zrodel(modelka) == str(przed) and przed.is_dir()
    assert baza.folder_gotowych(modelka) == str(po) and po.is_dir()


def test_stroj_domyslny(modelka):
    assert baza.stroj_domyslny(modelka) is None
    baza.zapisz_ustawienia(modelka, stroj_domyslny="stroje/mesh.png")
    assert baza.stroj_domyslny(modelka) is None  # pliku jeszcze nie ma
    sciezka = os.path.join(baza.folder_strojow(modelka), "mesh.png")
    open(sciezka, "wb").close()
    # na Windows ukosnik z ustawienia ma wyjsc jako backslash (normpath) - inaczej sciezki sie nie zgadzaja
    assert baza.stroj_domyslny(modelka) == os.path.normpath(sciezka)


def test_sciezka_w_modelce_normalizuje(modelka, monkeypatch):
    import ntpath
    monkeypatch.setattr(baza.os, "path", ntpath)
    monkeypatch.setattr(baza, "folder_modelki", lambda slug: r"C:\rolki\modelki\noemi")
    assert baza._sciezka_w_modelce(modelka, "stroje/mesh.png") == r"C:\rolki\modelki\noemi\stroje\mesh.png"
    assert baza._sciezka_w_modelce(modelka, r"D:\inne\x.png") == r"D:\inne\x.png"


# ---------------- pomysly ----------------

def test_kolejka_pomyslow(modelka):
    a = baza.dodaj_pomysl(modelka, "pierwszy", zrodlo="/x/a.mp4")
    b = baza.dodaj_pomysl(modelka, "drugi", "prompt")
    assert (a, b) == (1, 2)
    assert baza.pomysl(modelka, b)["prompt_higgsfield"] == "prompt"
    baza.aktualizuj_pomysl(modelka, a, status="blad")
    assert [p["id"] for p in baza.lista_pomyslow(modelka, "nowy")] == [b]
    st = baza.statystyki_pomyslow(modelka)
    assert st["nowy"] == 1 and st["blad"] == 1 and st["gotowe"] == 0
    with pytest.raises(ValueError):
        baza.aktualizuj_pomysl(modelka, a, status="zly_status")
    with pytest.raises(ValueError):
        baza.pomysl(modelka, 99)
    baza.usun_pomysl(modelka, a)
    with pytest.raises(ValueError):
        baza.usun_pomysl(modelka, a)
    # id nie wraca do zwolnionych numerow ponizej max
    assert baza.dodaj_pomysl(modelka, "trzeci") == 3


def test_pomysl_po_zrodle(modelka, tmp_path):
    z = str(tmp_path / "klip.mp4")
    baza.dodaj_pomysl(modelka, "klip", zrodlo=z)
    assert baza.pomysl_po_zrodle(modelka, z)["id"] == 1
    assert baza.pomysl_po_zrodle(modelka, str(tmp_path / "inny.mp4")) is None


# ---------------- budzet ----------------

def test_budzet_domyslny_i_wydatki(dane):
    assert baza.budzet()["max_kredyty_dziennie"] == 300
    assert baza.wydano_dzis() == 0
    assert baza.dopisz_wydatek(45) == 45
    assert baza.dopisz_wydatek(0) == 45
    assert baza.dopisz_wydatek(-10) == 45
    assert baza.dopisz_wydatek(72) == 117
    assert baza.wydano_dzis() == 117


def test_wydatki_nie_zmieniaja_domyslnego_budzetu(dane):
    baza.dopisz_wydatek(45)
    assert baza.BUDZET_DOMYSLNY["wydatki"] == {}
    # to samo dla list/dict w USTAWIENIA_DOMYSLNE
    slug = baza.utworz_modelke("x")
    baza.ustawienia_modelki(slug)["referencje"].append("zle.png")
    assert baza.USTAWIENIA_DOMYSLNE["referencje"] == []


def test_budzet_trzyma_60_dni(dane):
    dzis = datetime.now()
    stare = {(dzis - timedelta(days=i)).strftime("%Y-%m-%d"): 1 for i in range(1, 80)}
    baza.zapisz_budzet(wydatki=stare)
    baza.dopisz_wydatek(5)
    wydatki = baza.budzet()["wydatki"]
    assert len(wydatki) == 60
    assert wydatki[dzis.strftime("%Y-%m-%d")] == 5


# ---------------- uploady ----------------

def test_cache_uploadow(modelka):
    ref = baza.sciezki_referencji(modelka)[0]
    assert baza.upload_id(modelka, ref) is None
    baza.zapisz_upload_id(modelka, ref, "uuid-1")
    assert baza.upload_id(modelka, ref) == "uuid-1"
    assert baza.media_do_cli(modelka, [ref, "/inny.png"]) == ["uuid-1", "/inny.png"]
    # zmiana pliku (rozmiar) uniewaznia cache
    with open(ref, "ab") as f:
        f.write(b"wiecej")
    assert baza.upload_id(modelka, ref) is None


# ---------------- szablony i teksty ----------------

def test_szablony(modelka):
    baza.dodaj_szablon(modelka, "plaza", "{kto} na plazy, {pora}, {kto}")
    assert baza.placeholdery_szablonu("{kto} na plazy, {pora}, {kto}") == ["kto", "pora"]
    assert baza.wypelnij_szablon("{kto} na plazy, {pora}", {"kto": "noemi"}) == "noemi na plazy, {pora}"
    with pytest.raises(ValueError):
        baza.dodaj_szablon(modelka, "plaza", "x")
    baza.usun_szablon(modelka, "plaza")
    assert baza.lista_szablonow(modelka) == []


def test_bank_tekstow(modelka, tmp_path):
    assert baza.dodaj_teksty(modelka, ["a", " a ", "", "b"]) == 2
    plik = tmp_path / "teksty.txt"
    plik.write_text("c\nlinia 2\n---\nd", encoding="utf-8")
    assert baza.dodaj_teksty_z_pliku(modelka, str(plik)) == 2
    assert baza.statystyki_tekstow(modelka) == (4, 4)
    assert baza.losuj_tekst(modelka) == "a"
    assert baza.losuj_tekst(modelka) == "b"
    assert baza.losuj_tekst(modelka) == "c\nlinia 2"
    assert baza.losuj_tekst(modelka) == "d"
    assert baza.losuj_tekst(modelka) is None
    assert baza.statystyki_tekstow(modelka) == (0, 4)
