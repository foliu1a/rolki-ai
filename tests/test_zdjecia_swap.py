# -*- coding: utf-8 -*-
"""Zdjecia z podmiana postaci (swap, panel 3.2) - udawane CLI Higgsfield, zero kredytow i zero wysylania: proporcje "jak
zdjecie" (takze z obrotem EXIF), chipy wg schematu modelu, prompt (sylwetka, wlosy, wzrost, tatuaze persony, stroj ze zdjecia vs
z biblioteki, kolejnosc obrazow), brak slow z SLOWA_RYZYKOWNE (takze dla prawdziwych person z modelki/), pieniadze (job_id
zapisany przed czekaniem, nigdy drugi create po 'wysylam', limit dzienny wspolny z rezerwa, cena wyzsza = nic, blokada
generacji, NSFW bez powtorki), wycena bez mediow z cache, endpointy /api/swap*, CLI --sucho."""
import io
import os
import threading

import pytest
from PIL import Image

import app as panel
import baza
import fabryka
import higgsfield_cli
import zdjecia_swap as zs
from dostawcy import higgsfield as dh

PRAWDZIWE_MODELKI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modelki")

PROMPT_A = """# 1. TASK
Replace the woman in the source video with Noemi.
# 2. EXACT IDENTITY
* Fair skin with a natural warm complexion
* light grey-blue eyes
* long straight golden hair with a center part
* silver septum ring
Her only tattoos are two small stars on her left wrist, shown in @[Image 3](image_3) (see section 4).
# 3. OUTFIT
Wear the outfit from the video.
"""


@pytest.fixture(autouse=True)
def czysty_cache():
    zs.wyczysc_cache()
    yield
    zs.wyczysc_cache()


def _zdjecie(sciezka, w=1080, h=1350, orientacja=None, alfa=False):
    """Prawdziwe male zdjecie (PIL) - opcjonalnie z EXIF Orientation (telefon zapisuje pion jako poziom + znacznik)."""
    im = Image.new("RGBA" if alfa else "RGB", (w, h), (200, 120, 90, 255) if alfa else (200, 120, 90))
    if orientacja:
        exif = Image.Exif()
        exif[0x0112] = orientacja
        exif[0x010F] = "Apple"           # producent aparatu - nie moze trafic do kopii
        im.save(sciezka, "JPEG", exif=exif.tobytes())
    else:
        im.save(sciezka)
    return str(sciezka)


@pytest.fixture
def persona(modelka):
    """Noemi: prompt A z sekcja IDENTITY (tatuaz na @[Image 3]), profil (wlosy, sylwetka, wzrost) i 3 referencje."""
    baza.zapisz_prompt(modelka, "stroj_z_filmu.txt", PROMPT_A)
    baza.zapisz_profil(modelka, wlosy="long straight pale platinum blonde hair, center part",
                       sylwetka="petite hourglass figure with a large, full natural bust and a big, round, lifted bottom. Her bust "
                                "and bottom must look at least as big as in the reference photos.",
                       wzrost_cm="158-160")
    with open(os.path.join(baza.folder_referencji(modelka), "03_profil.png"), "wb") as f:
        f.write(b"img")
    return modelka


@pytest.fixture
def zrodlo(persona, tmp_path):
    return _zdjecie(tmp_path / "IMG_1234.jpg", 1080, 1350)


# ---------------- proporcje i chipy ----------------

@pytest.mark.parametrize("w,h,model,oczekiwane", [
    (1080, 1920, "seedream_v5_pro", "9:16"), (1080, 1350, "gpt_image_2_5", "4:5"), (1080, 1350, "nano_banana_pro", "4:5"),
    (1080, 1350, "seedream_v5_pro", "3:4"),           # Seedream nie ma 4:5 -> najblizsze 3:4
    (4000, 3000, "seedream_v5_pro", "4:3"), (1000, 1000, "gpt_image_2_5", "1:1"), (1920, 1080, "nano_banana_pro", "16:9"),
    (2560, 1080, "seedream_v5_pro", "21:9"), (1170, 2532, "gpt_image_2_5", "9:16"), (1200, 1800, "nano_banana_pro", "2:3"),
])
def test_proporcje_jak_zdjecie(w, h, model, oczekiwane):
    dostepne = zs.chipy(zs.MODELE[model]["schemat"])["proporcje"]
    assert zs.najblizsze_proporcje(w, h, dostepne) == oczekiwane


def test_wymiary_z_exif_i_kopia_bez_metadanych(persona, tmp_path):
    # telefon: piksele 1600x1200 + Orientation 6 = zdjecie w pionie 1200x1600
    plik = _zdjecie(tmp_path / "z telefonu.jpg", 1600, 1200, orientacja=6)
    assert zs.wymiary(plik) == (1200, 1600)
    sw = zs.zbuduj(persona, plik, {"model": "gpt_image_2_5"})
    assert sw["parametry"]["aspect_ratio"] == "3:4" and sw["proporcje_jak_zdjecie"]
    kopia = zs.zapisz_zrodlo(persona, plik)
    assert os.path.dirname(kopia) == baza.folder_swap_zrodel(persona) and kopia.endswith("_z_telefonu.jpg")
    with Image.open(kopia) as im:
        assert im.size == (1200, 1600) and not dict(im.getexif())      # obrocona, bez EXIF (GPS, aparat, data)
    assert zs.nazwa_zrodla(kopia) == "z_telefonu"
    # PNG z przezroczystoscia zostaje PNG; nie-zdjecie -> ValueError
    png = zs.zapisz_zrodlo(persona, _zdjecie(tmp_path / "naklejka.png", 300, 300, alfa=True))
    assert png.endswith(".png")
    with pytest.raises(ValueError):
        zs.zapisz_zrodlo(persona, io.BytesIO(b"to nie obraz"), "x.jpg")
    # duze zdjecie: dluzszy bok max MAX_BOK_ZRODLA
    duze = zs.zapisz_zrodlo(persona, _zdjecie(tmp_path / "duze.jpg", 4000, 3000))
    assert max(zs.wymiary(duze)) == zs.MAX_BOK_ZRODLA


def test_chipy_wg_schematu_modelu():
    sd = zs.chipy(zs.MODELE["seedream_v5_pro"]["schemat"])
    assert sd["jakosc"] == [] and sd["rozdzielczosc"] == ["1k", "1.5k", "2k"] and sd["max_obrazow"] == 10
    assert "4:5" not in sd["proporcje"] and sd["domyslne"] == {"jakosc": None, "rozdzielczosc": "2k"}
    gpt = zs.chipy(zs.MODELE["gpt_image_2_5"]["schemat"])
    assert gpt["jakosc"] == ["low", "medium", "high", "xhigh", "max"] and gpt["domyslne"] == {"jakosc": "high", "rozdzielczosc": "2k"}
    assert "4k" in gpt["rozdzielczosc"] and "auto" not in gpt["proporcje"] and "16:27" not in gpt["proporcje"]
    assert gpt["max_obrazow"] is None
    nb = zs.chipy(zs.MODELE["nano_banana_pro"]["schemat"])
    assert nb["jakosc"] == [] and nb["rozdzielczosc"] == ["1k", "2k", "4k"] and nb["max_obrazow"] == 14 and "4:5" in nb["proporcje"]
    # schemat prosto z `model get --json`: bez jakosci i rozdzielczosci -> te chipy znikaja; regula inpaint nie jest limitem
    surowy = {"params": [{"name": "aspect_ratio", "type": "string", "default": "auto", "enum": ["auto", "1:1", "9:16", "4:1"]},
                         {"name": "thinking_level", "enum": ["minimal", "high"]}, {"name": "prompt", "type": "string"}],
              "rules": [{"cel": "!params.is_inpaint || size(params.image_references) <= 13"}]}
    c = zs.chipy(surowy)
    assert c["proporcje"] == ["9:16", "1:1"] and c["jakosc"] == [] and c["rozdzielczosc"] == [] and c["max_obrazow"] is None
    assert c["domyslne"] == {"jakosc": None, "rozdzielczosc": None}


def test_katalog_i_walidacja_opcji(persona, zrodlo):
    k = zs.katalog(persona)
    assert k["model_domyslny"] == "seedream_v5_pro" and [m["id"] for m in k["modele"]] == list(zs.MODELE)
    assert k["domyslne"] == {"model": "seedream_v5_pro", "proporcje": "jak_zdjecie", "ile": 1, "stroj": "ze_zdjecia"}
    gpt = [m for m in k["modele"] if m["id"] == "gpt_image_2_5"][0]
    assert ["high", "Wysoka"] in gpt["jakosc"] and ["4k", "4K"] in gpt["rozdzielczosc"]
    sd = [m for m in k["modele"] if m["id"] == "seedream_v5_pro"][0]
    assert sd["jakosc"] == [] and ["1.5k", "1,5K"] in sd["rozdzielczosc"]
    assert k["persona"]["referencje"] == 3 and k["persona"]["sylwetka"]
    # jakosc dla modelu bez jakosci nie idzie do Higgsfielda; wartosci spoza schematu = ValueError (nic nie wysylamy)
    assert "quality" not in zs.zbuduj(persona, zrodlo, {"model": "seedream_v5_pro", "jakosc": "high"})["parametry"]
    assert zs.zbuduj(persona, zrodlo, {"model": "gpt_image_2_5", "jakosc": "max", "rozdzielczosc": "4k", "proporcje": "9:16"})[
        "parametry"] == {"aspect_ratio": "9:16", "resolution": "4k", "quality": "max"}
    for zle in ({"model": "seedream_v5_pro", "rozdzielczosc": "4k"}, {"model": "seedream_v5_pro", "proporcje": "4:5"},
                {"model": "gpt_image_2_5", "jakosc": "ultra"}, {"model": "nano_banana_flash"}):
        with pytest.raises(ValueError):
            zs.zbuduj(persona, zrodlo, zle)
    with pytest.raises(ValueError):
        zs.zbuduj(persona, None, {})


def test_odswiez_schematy_z_cli(monkeypatch):
    nowy = {"params": [{"name": "aspect_ratio", "enum": ["9:16", "1:1"]}, {"name": "resolution", "enum": ["1k", "2k", "4k"]}],
            "rules": []}

    def model(jst):
        if jst == "seedream_v5_pro":
            return nowy
        raise higgsfield_cli.HiggsfieldBlad("nie zalogowane")
    monkeypatch.setattr(higgsfield_cli, "model", model)
    assert zs.odswiez_schematy() == 1
    sd = [m for m in zs.katalog()["modele"] if m["id"] == "seedream_v5_pro"][0]
    assert sd["proporcje"] == ["9:16", "1:1"] and ["4k", "4K"] in sd["rozdzielczosc"]
    nb = [m for m in zs.katalog()["modele"] if m["id"] == "nano_banana_pro"][0]
    assert nb["max_obrazow"] == 14          # blad CLI = zostaje kopia z kodu


# ---------------- prompt ----------------

def test_prompt_pelna_podmiana_postaci(persona, zrodlo):
    sw = zs.zbuduj(persona, zrodlo, {})
    refy = baza.sciezki_referencji(persona)
    assert sw["obrazy"] == [os.path.abspath(zrodlo)] + refy            # 1 = wstawione zdjecie, potem wszystkie referencje
    assert sw["model"] == "seedream_v5_pro" and sw["parametry"] == {"aspect_ratio": "3:4", "resolution": "2k"}
    p = sw["prompt"]
    assert p.startswith("Edit image 1 (the first image) into a photo of Noemi - a complete character replacement.")
    assert "framing and crop, camera angle" in p and "the pose" in p and "the facial expression" in p and "the background" in p
    assert "the lighting, shadows and colours" in p and "the young woman shown in images 2-4" in p
    assert "Nothing of the original person's look may stay" in p and "tattoos, moles, birthmarks, piercings or body shape" in p
    # tozsamosc bez wlosow (wlosy osobno z profilu), tatuaz persony z numerem zdjecia przesunietym o wstawione zdjecie
    assert "light grey-blue eyes" in p and "silver septum ring" in p and "golden hair" not in p
    assert "two small stars on her left wrist, shown in image 4" in p
    assert "Hair: long straight pale platinum blonde hair, center part, exact colour and shade as in images 2-4." in p
    assert "She is petite, about 158-160 cm tall" in p
    assert ("Body shape (highest priority after her face): petite hourglass figure with a large, full natural bust and a big, "
            "round, lifted bottom. Her bust and bottom must look at least as big as in images 2-4.") in p
    assert "even where the person in image 1 is slimmer or flatter" in p and "her figure matches the body shape above" in p
    assert "exactly the clothes, shoes and accessories the person in image 1 is wearing" in p and "the last image" not in p
    assert "Remove everything that was added on top of image 1" in p and "watermarks" in p and "stickers" in p
    assert "Photorealistic, like a real unedited phone photo" in p and "No beauty filter" in p and "not prettier" in p
    assert "\n\n" not in p and sw["znaki"] == len(p)
    assert sw["opis"] == "Podmiana postaci: IMG_1234 · Seedream 5.0 Pro · 3:4 · 2K · strój: ze zdjęcia"
    # bez sylwetki w profilu: figura z referencji, nigdy z osoby ze zdjecia (+ ostrzezenie)
    baza.zapisz_profil(persona, sylwetka="")
    sw = zs.zbuduj(persona, zrodlo, {"dopisek": "  lekki usmiech  "})
    assert "Body: her own figure and proportions from images 2-4" in sw["prompt"] and "Body shape" not in sw["prompt"]
    assert any("sylwetki" in u for u in sw["ostrzezenia"]) and "[Extra] lekki usmiech\n" in sw["prompt"]


def test_stroj_z_biblioteki_jako_ostatni_obraz(persona, zrodlo, biblioteka):
    sw = zs.zbuduj(persona, zrodlo, {"stroj": "ulub_a", "model": "nano_banana_pro"})
    assert sw["obrazy"][-1] == os.path.join(baza.KATALOG_BIBLIOTEKI, "ulub_a.png") and len(sw["obrazy"]) == 5
    assert sw["obrazy"][1:4] == baza.sciezki_referencji(persona) and sw["stroj_id"] == "ulub_a"
    p = sw["prompt"]
    assert "a black corset top and a short black pleated skirt - exactly the clothing shown in image 5 (the last image)" in p
    assert "instead of the clothes from image 1" in p
    assert ("Image 5 shows ONLY the outfit: ignore the hair, face, skin, tattoos and body shape of the person or mannequin "
            "wearing it - her hair, face and body come only from images 2-4.") in p
    assert "the person in image 1 is wearing" not in p and "strój: Ulubiony A" in sw["opis"]
    for zly in ("opis_e", "nie_ma"):              # stroj bez zdjecia / nieznany -> ValueError, nic nie idzie
        with pytest.raises(ValueError):
            zs.zbuduj(persona, zrodlo, {"stroj": zly})


def test_limit_zdjec_modelu_obcina_referencje(persona, zrodlo, biblioteka):
    for i in range(4, 12):                        # 11 referencji + zdjecie + stroj > 10 (Seedream)
        with open(os.path.join(baza.folder_referencji(persona), f"{i:02d}_x.png"), "wb") as f:
            f.write(b"img")
    sw = zs.zbuduj(persona, zrodlo, {"stroj": "ulub_a"})
    assert len(sw["obrazy"]) == 10 and sw["obrazy"][1:9] == baza.sciezki_referencji(persona)[:8]
    assert "images 2-9" in sw["prompt"] and "image 10 (the last image)" in sw["prompt"]
    assert any("max 10" in u for u in sw["ostrzezenia"])
    assert len(zs.zbuduj(persona, zrodlo, {"model": "nano_banana_pro"})["obrazy"]) == 12     # 14 miesci wszystkie


def test_brak_slow_ryzykownych_w_prompcie(persona, zrodlo, biblioteka):
    baza.zapisz_prompt(persona, "stroj_z_filmu.txt", PROMPT_A.replace("* silver septum ring", "* sheer make-up\n* deep cleavage"))
    baza.zapisz_profil(persona, sylwetka="curvy figure with big breasts and a round butt; sexy curves", wlosy="lace-up braids, see-through clips")
    for model in zs.MODELE:
        for stroj in ("ze_zdjecia", "ulub_a"):
            sw = zs.zbuduj(persona, zrodlo, {"model": model, "stroj": stroj, "dopisek": "bikini, kiss to the camera, Lingerie"})
            assert zs.slowa_ryzykowne(sw["prompt"]) == [], (model, stroj, zs.slowa_ryzykowne(sw["prompt"]))
            t = f" {''.join(c if c.isalnum() or c in ' -' else ' ' for c in sw['prompt'].lower())} "
            assert not [w for w in fabryka.SLOWA_RYZYKOWNE if f" {w} " in t or f" {w}s " in t]
    p = sw["prompt"]
    assert "big bust and a round bottom" in p and "lace-up braids" in p        # lace-up to nie lace
    assert any("dopisku" in u for u in sw["ostrzezenia"]) and any("opisu persony" in u for u in sw["ostrzezenia"])
    assert zs.bez_slow_ryzykownych("Sexy, curvy; bra-strap. Kisses") == ("striking, full-figured; bra-strap. smile", ["curvy", "sexy", "kiss"])


def test_prawdziwe_persony_bez_slow_ryzykownych(monkeypatch, tmp_path):
    """Wszystkie prawdziwe persony (modelki/ - poza gitem, tylko odczyt) x modele x stroj ze zdjecia / z biblioteki: prompt bez slow,
    ktore filtr NSFW lubi blokowac."""
    if not os.path.isdir(PRAWDZIWE_MODELKI):
        pytest.skip("brak folderu modelki/ (jest poza gitem)")
    monkeypatch.setattr(baza, "KATALOG_MODELEK", PRAWDZIWE_MODELKI)
    slugi = [s for s in baza.lista_modelek() if baza.sciezki_referencji(s)]
    if not slugi:
        pytest.skip("brak person ze zdjeciami")
    zrodlo = _zdjecie(tmp_path / "x.jpg")
    stroje = ["ze_zdjecia"] + [s["id"] for s in baza.stroje_biblioteki(tylko_ze_zdjeciem=True)]
    for slug in slugi:
        for model in zs.MODELE:
            for stroj in stroje:
                sw = zs.zbuduj(slug, zrodlo, {"model": model, "stroj": stroj})
                assert zs.slowa_ryzykowne(sw["prompt"]) == [], (slug, model, stroj)
                assert "image 1 (the first image)" in sw["prompt"] and len(sw["prompt"]) < 5000


# ---------------- pieniadze ----------------

def test_pelna_sciezka_job_id_przed_czekaniem_i_plik(persona, zrodlo, cli, monkeypatch):
    cli.cena = 2.5
    src = zs.zapisz_zrodlo(persona, zrodlo)
    widziane = []
    prawdziwy_job = cli.job

    def job(jid):
        z = baza.lista_zdjec(persona)[-1]
        widziane.append((z["status"], (z.get("w_toku") or {}).get("job_id"), (z.get("w_toku") or {}).get("wysylam")))
        return prawdziwy_job(jid)
    monkeypatch.setattr(higgsfield_cli, "job", job)
    w = zs.generuj(persona, src, {"ile": 1}, kr=2.5)
    assert w["zrobione"] == 1 and len(cli.generacje) == 1 and w["ids"] == [1]
    assert widziane[0] == ("w_toku", "job1", True)             # job_id zapisany PRZED pierwszym odpytaniem
    model, params, media = cli.generacje[0]
    assert model == "seedream_v5_pro" and params["aspect_ratio"] == "3:4" and params["resolution"] == "2k" and "quality" not in params
    assert media["image"][0] == "uuid-" + os.path.basename(src)                    # wstawione zdjecie: swiezy upload, pierwsze
    assert media["image"][1:] == ["uuid-" + os.path.basename(r) for r in baza.sciezki_referencji(persona)]
    assert params["prompt"].startswith("Edit image 1")
    z = baza.lista_zdjec(persona)[-1]
    assert z["status"] == "gotowe" and z["typ"] == "swap" and z["w_toku"] is None and z["job_id"] == "job1" and z["koszt"] == 3
    assert z["wycena"] == 2.5 and z["zrodlo"] == src and z["zrodlo_nazwa"] == "IMG_1234" and z["model"] == "seedream_v5_pro"
    assert os.path.basename(z["plik"]) == "001_swap_IMG_1234.png" and os.path.dirname(z["plik"]) == baza.folder_zdjec(persona)
    assert os.path.isfile(z["plik"])
    assert baza.wydano_dzis("higgsfield") == 3 and baza.koszt_w_toku("higgsfield") == 0       # 2,5 kr -> do limitu w gore
    assert cli.wyceny and all(m == {} for _, _, m in cli.wyceny)                             # wycena bez mediow (zero uploadu)
    assert "job1" in baza.znane_job_id("higgsfield")
    assert baza.zdjecia_z_dnia(persona) and not baza.zdjecia_z_dnia(persona, bez_swap=True)   # autopilot nie liczy swapow


def test_ile_4_osobne_zlecenia_ze_swiezym_uploadem(persona, zrodlo, cli):
    cli.cena = 2.75
    src = zs.zapisz_zrodlo(persona, zrodlo)
    w = zs.generuj(persona, src, {"ile": 4, "model": "gpt_image_2_5"}, kr=2.75)
    assert w["zrobione"] == 4 and len(cli.generacje) == 4 and len(baza.lista_zdjec(persona)) == 4
    assert cli.uploady.count(src) == 4                  # kazde zlecenie = swiezy upload zdjecia (id odnajduje job)
    assert all(p["quality"] == "high" for _, p, _ in cli.generacje)
    assert baza.wydano_dzis("higgsfield") == 12
    assert sorted(os.path.basename(z["plik"]) for z in baza.lista_zdjec(persona)) == [f"00{i}_swap_IMG_1234.png" for i in range(1, 5)]
    assert zs.generuj(persona, src, {"ile": 9}, kr=2.75)["zrobione"] == 4              # max 4 naraz


def test_blad_po_wysylam_znajduje_job_bez_drugiego_create(persona, zrodlo, cli, monkeypatch):
    src = zs.zapisz_zrodlo(persona, zrodlo)
    prawdziwe = cli.generuj

    def generuj_z_bledem(model, params=None, media=None, wait=True, **k):
        prawdziwe(model, params, media, wait=wait)             # job POWSTAL na serwerze...
        raise higgsfield_cli.HiggsfieldBlad("socket hang up")  # ...ale odpowiedz nie dotarla
    monkeypatch.setattr(higgsfield_cli, "generuj", generuj_z_bledem)
    w = zs.generuj(persona, src, {}, kr=45)
    assert len(cli.generacje) == 1 and w["zrobione"] == 1
    z = baza.lista_zdjec(persona)[-1]
    assert z["status"] == "gotowe" and z["job_id"] == "job1"


def test_blad_po_wysylam_bez_joba_czeka_i_nigdy_nie_wysyla_drugi_raz(persona, zrodlo, cli, monkeypatch):
    src = zs.zapisz_zrodlo(persona, zrodlo)

    def padl(*a, **k):
        cli.generacje.append(a)
        raise higgsfield_cli.HiggsfieldBlad("timeout po wyslaniu")
    monkeypatch.setattr(higgsfield_cli, "generuj", padl)
    w = zs.generuj(persona, src, {}, kr=45)
    zid = w["ids"][0]
    assert w["w_toku"] == [zid] and len(cli.generacje) == 1
    z = baza.zdjecie(persona, zid)
    assert z["status"] == "w_toku" and z["w_toku"]["wysylam"] is True and z["w_toku"]["obraz_id"] == "uuid-" + os.path.basename(src)
    assert not z["w_toku"]["job_id"] and baza.koszt_w_toku("higgsfield") == 45          # rezerwa w limicie dnia (wspolnym)
    assert baza.wydano_z_rezerwa("higgsfield") == 45
    # kolejne przebiegi (restart panelu, wznow) tylko szukaja - zero nowych create
    zs.wznow_w_toku(persona)
    assert len(cli.generacje) == 1 and baza.zdjecie(persona, zid)["status"] == "w_toku"
    # po 60 min bez joba: blad z prosba o sprawdzenie w apce, wycena w limicie na wszelki wypadek, NIGDY drugi create
    baza.ustaw_zdjecie_w_toku(persona, zid, wysylam_od="2020-01-01T00:00:00+00:00")
    zs.wznow_w_toku(persona)
    z = baza.zdjecie(persona, zid)
    assert z["status"] == "blad" and "Sprawdz w apce Higgsfield" in z["notatki"] and z["w_toku"] is None
    assert baza.wydano_dzis("higgsfield") == 45 and baza.koszt_w_toku("higgsfield") == 0 and len(cli.generacje) == 1


def test_wznowienie_znajduje_job_po_id_zdjecia(persona, zrodlo, cli, monkeypatch):
    """Przerwanie miedzy create a zapisem job_id (zamkniety panel): restart szuka joba na `generate list --image` po id
    wstawionego zdjecia, pomija cudze joby i dokancza TEN - bez drugiego create."""
    src = zs.zapisz_zrodlo(persona, zrodlo)
    zid = baza.dodaj_zdjecie(persona, "p", status="w_toku", typ="swap", zrodlo=src, zrodlo_nazwa="IMG_1234",
                             w_toku={"dostawca": "higgsfield", "model": "seedream_v5_pro", "koszt": 3, "od": fabryka._teraz_iso(),
                                     "etap": "wysylanie", "job_id": None, "wysylam": True, "wysylam_od": fabryka._teraz_iso(),
                                     "obraz_id": "uuid-moje"})
    cli.serwer["cudzy"] = {"id": "cudzy", "job_type": "seedream_v5_pro", "status": "completed", "result": {"url": "https://cdn/x.png"},
                           "params": {"medias": [{"role": "image", "data": {"id": "uuid-inne"}}]}}
    cli.serwer["moj"] = {"id": "moj", "job_type": "seedream_v5_pro", "status": "completed", "result": {"url": "https://cdn/m.png"},
                         "params": {"medias": [{"role": "image", "data": {"id": "uuid-moje"}}]}}
    w = zs.wznow_w_toku(persona)
    z = baza.zdjecie(persona, zid)
    assert w["zrobione"] == 1 and z["status"] == "gotowe" and z["job_id"] == "moj" and cli.generacje == []
    assert os.path.basename(z["plik"]) == f"{zid:03d}_swap_IMG_1234.png" and baza.wydano_dzis("higgsfield") == 3


def test_przerwane_przed_wysylam_nic_nie_zeszlo(persona, zrodlo, cli):
    zid = baza.dodaj_zdjecie(persona, "p", status="w_toku", typ="swap", zrodlo=zrodlo,
                             w_toku={"dostawca": "higgsfield", "model": "seedream_v5_pro", "koszt": 3, "od": fabryka._teraz_iso(),
                                     "etap": "wysylanie", "job_id": None})
    zs.wznow_w_toku(persona)
    z = baza.zdjecie(persona, zid)
    assert z["status"] == "blad" and "nic nie zeszlo" in z["notatki"] and cli.generacje == []
    assert baza.wydano_dzis("higgsfield") == 0 and baza.koszt_w_toku("higgsfield") == 0


def test_job_trwa_zostaje_w_toku_i_dokanczamy_ten_sam(persona, zrodlo, cli):
    src = zs.zapisz_zrodlo(persona, zrodlo)
    cli.wyniki = [{"status": "in_progress"}]
    w = zs.generuj(persona, src, {}, kr=45, timeout="10s")
    zid = w["ids"][0]
    assert w["w_toku"] == [zid] and baza.zdjecie(persona, zid)["w_toku"]["job_id"] == "job1"
    cli.serwer["job1"] = dict(cli.serwer["job1"], status="completed", result={"url": "https://cdn/gotowe.webp"})
    zs.wznow_w_toku(persona)
    z = baza.zdjecie(persona, zid)
    assert z["status"] == "gotowe" and len(cli.generacje) == 1 and z["plik"].endswith("_swap_IMG_1234.webp")


def test_nsfw_jasny_komunikat_bez_powtorki(persona, zrodlo, cli):
    src = zs.zapisz_zrodlo(persona, zrodlo)
    # 3.3: seria idzie rownolegle - tu jedno naraz (ustawienie), wiec 2. i 3. czekaja w kolejce, gdy filtr odrzuca 1.
    baza.zapisz_ustawienia_globalne(zdjecia_rownolegle=1)
    cli.wyniki = [{"status": "nsfw"}]
    w = zs.generuj(persona, src, {"ile": 3}, kr=45)
    # odrzucone pierwsze = pozostale z tej serii (to samo zdjecie) nie ida z kolejki - dostalyby to samo
    assert len(cli.generacje) == 1 and w["odrzucone"] == [1] and w["zrobione"] == 0 and w["stop"] == "odrzucone przez filtr"
    z = baza.zdjecie(persona, 1)
    assert z["status"] == "blad" and z["powod"] == "nsfw" and z["notatki"].startswith(zs.NOTATKA_NSFW) and z["koszt"] == 0
    assert [baza.zdjecie(persona, i)["status"] for i in (2, 3)] == ["anulowane", "anulowane"]
    assert baza.zdjecie(persona, 2)["notatki"] == zs.NOTATKA_SERIA_FILTR
    assert baza.wydano_dzis("higgsfield") == 0 and baza.koszt_w_toku("higgsfield") == 0     # rezerwacje zwolnione
    # odrzucenie juz przy wysylaniu (create zwraca blad filtra) - jeden create, zero powtorek
    for x in baza.lista_zdjec(persona):
        baza.usun_zdjecie(persona, x["id"])
    n = len(cli.generacje)
    cli.wyniki = [higgsfield_cli.HiggsfieldBlad("Error: content flagged by moderation (nsfw)")]
    w = zs.generuj(persona, src, {}, kr=45)
    assert len(cli.generacje) == n + 1 and w["odrzucone"] == w["ids"]
    assert baza.zdjecie(persona, w["ids"][0])["powod"] == "nsfw"


def test_bezpieczniki_limit_saldo_cena(persona, zrodlo, cli):
    src = zs.zapisz_zrodlo(persona, zrodlo)
    cli.cena = 2.5
    # cena wyzsza niz zatwierdzona -> nic nie idzie
    w = zs.generuj(persona, src, {}, kr=2)
    assert w["stop"] == "cena wzrosla" and cli.generacje == [] and baza.lista_zdjec(persona) == []
    # limit dzienny wspolny (rolki + zdjecia, z rezerwa w toku)
    baza.dopisz_wydatek(298, "higgsfield", job_id="rolka")
    w = zs.generuj(persona, src, {}, kr=2.5)
    assert w["stop"] == "limit dzienny" and cli.generacje == [] and baza.lista_zdjec(persona) == []
    wy = zs.wycena(persona, {"ile": 1}, zrodlo=src, saldo=1000)
    assert not wy["mozna"] and any("limit" in p for p in wy["powody"]) and wy["dzis"] == {"wydano": 298, "limit": 300}
    # saldo ponizej minimum
    baza.zapisz_limit_dzienny(0)
    cli.saldo = 201
    w = zs.generuj(persona, src, {}, kr=2.5)
    assert w["stop"] == "min_kredyty" and cli.generacje == []


def test_zdjecia_nie_czekaja_na_rolki_persony(persona, zrodlo, cli):
    """3.3: zdjecia nie biora blokady generacji persony (rolki) - rolka, ktora sie wlasnie generuje, nie zatrzymuje zdjec. Jedno
    zdjecie = jeden wlasciciel pilnuje baza.BlokadaZdjecia (test_zdjecia_rownolegle.py)."""
    src = zs.zapisz_zrodlo(persona, zrodlo)
    trzyma, puszczaj = threading.Event(), threading.Event()

    def rolka_w_innym_watku():
        with baza.blokada_generacji(persona):
            trzyma.set()
            puszczaj.wait(5)
    t = threading.Thread(target=rolka_w_innym_watku)
    t.start()
    trzyma.wait(5)
    try:
        w = zs.generuj(persona, src, {}, kr=45)
        assert w["zrobione"] == 1 and len(cli.generacje) == 1 and w["stop"] is None
    finally:
        puszczaj.set()
        t.join(5)


def test_wycena_bez_mediow_z_cache(persona, zrodlo, cli):
    cli.cena = 2.75
    w = zs.wycena(persona, {"model": "gpt_image_2_5", "ile": 2}, zrodlo=zrodlo, saldo=1000)
    assert w["kr_sztuka"] == 2.75 and w["kr"] == 5.5 and w["kr_limit"] == 6 and w["mozna"] and w["parametry"]["quality"] == "high"
    assert cli.generacje == [] and cli.uploady == [] and len(cli.wyceny) == 1
    model, params, media = cli.wyceny[0]
    assert model == "gpt_image_2_5" and media == {} and params["prompt"] == zs.PROMPT_WYCENY and params["resolution"] == "2k"
    zs.wycena(persona, {"model": "gpt_image_2_5", "ile": 3}, zrodlo=zrodlo, saldo=1000)
    assert len(cli.wyceny) == 1                                           # te same parametry = cache
    zs.wycena(persona, {"model": "gpt_image_2_5", "rozdzielczosc": "4k"}, zrodlo=zrodlo, saldo=1000)
    assert len(cli.wyceny) == 2 and cli.wyceny[1][1]["resolution"] == "4k"
    assert zs.wycena(persona, {}, saldo=1000)["parametry"]["aspect_ratio"] == "3:4"        # bez zdjecia: cena i tak ta sama
    assert higgsfield_cli._wyciagnij_koszt({"credits": 2.5}, dokladnie=True) == 2.5
    assert higgsfield_cli._wyciagnij_koszt({"credits": 2.5}) == 2 and higgsfield_cli._wyciagnij_koszt({"credits": 46.0}, True) == 46


def test_znajdz_po_id_obrazu(cli):
    cli.serwer["v"] = {"id": "v", "job_type": "seedance_2_5", "params": {"medias": [{"role": "video", "data": {"id": "u1"}}]}}
    cli.serwer["a"] = {"id": "a", "job_type": "nano_banana_pro", "status": "completed",
                       "params": {"medias": [{"role": "image", "data": {"id": "u1"}}]}}
    assert dh.znajdz("nano_banana_pro", obraz_id="u1")["job_id"] == "a"
    assert dh.znajdz("seedream_v5_pro", obraz_id="u1") is None            # inny model
    assert dh.znajdz("nano_banana_pro", obraz_id="u2") is None


def test_cli_zdjecie_swap_sucho(persona, zrodlo, cli, capsys):
    cli.cena = 2.5
    assert fabryka.main(["--modelka", persona, "zdjecie-swap", zrodlo, "--sucho"]) == 0
    out = capsys.readouterr().out
    assert "Edit image 1 (the first image)" in out and "cena: 2,5 kr za zdjecie x 1" in out and "--sucho" in out
    assert "Seedream 5.0 Pro · 3:4 · 2K" in out
    assert cli.generacje == [] and cli.uploady == [] and baza.lista_zdjec(persona) == []
    assert os.listdir(baza.folder_swap_zrodel(persona)) == []
    assert fabryka.main(["--modelka", persona, "zdjecie-swap", zrodlo, "--model", "seedream_v5_pro", "--rozdzielczosc", "4k",
                         "--sucho"]) == 1


# ---------------- panel ----------------

@pytest.fixture
def klient(persona, cli):
    panel._saldo.clear()
    panel.konsola.__init__()
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        yield c


def _czekaj():
    w = panel.konsola.watek
    if w:
        w.join(10)
    assert not panel.konsola.stan["trwa"]


def czekaj_na_zdjecia(limit_s=10):
    """Dyspozytor zdjec panelu (watek w tle) skonczyl: nic w toku, nic w kolejce, zaden watek zdjecia nie pracuje."""
    import time as _t
    koniec = _t.monotonic() + limit_s
    while _t.monotonic() < koniec:
        s, o = zs.stan_kolejki(), zs.KOLEJKA.obsluga
        if not s["w_toku"] and not s["w_kolejce"] and not (o and o.aktywne()):
            return
        threading.Event().wait(0.02)            # time.sleep jest w testach wylaczone (conftest)
    raise AssertionError(f"zdjecia nie skonczyly sie w {limit_s} s: {zs.stan_kolejki()}")


def _wstaw(klient, w=1080, h=1920, nazwa="Moje zdjęcie.jpg"):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 20, 30)).save(buf, "JPEG")
    buf.seek(0)
    return klient.post("/api/swap/zdjecie", data={"plik": (buf, nazwa)}, content_type="multipart/form-data")


def test_api_wstaw_zdjecie_i_katalog(klient, persona, cli, biblioteka):
    d = _wstaw(klient).get_json()
    assert d["ok"] and d["szer"] == 1080 and d["wys"] == 1920 and d["url"].startswith("/api/plik?s=")
    assert d["proporcje"] == {m: "9:16" for m in zs.MODELE}          # kazdy model z listy (od 2026-10-08 tez GPT Image 2)
    assert os.path.isfile(os.path.join(baza.folder_swap_zrodel(persona), d["zrodlo"])) and cli.uploady == []
    assert klient.get(d["url"]).status_code == 200
    r = klient.post("/api/swap/zdjecie", data={"plik": (io.BytesIO(b"nie obraz"), "x.jpg")}, content_type="multipart/form-data")
    assert r.status_code == 400
    assert klient.post("/api/swap/zdjecie", data={}, content_type="multipart/form-data").status_code == 400
    k = klient.get("/api/swap").get_json()
    assert k["ok"] and k["model_domyslny"] == "seedream_v5_pro" and [m["id"] for m in k["modele"]] == list(zs.MODELE)
    assert [s["id"] for s in k["stroje"]] == ["ulub_a", "ulub_b", "zwykly_c", "zwykly_d"]     # tylko ze zdjeciem, ulubione najpierw
    assert all(s["url"] for s in k["stroje"]) and k["folder"] == baza.folder_zdjec(persona)


def test_api_wycena_i_generuj(klient, persona, cli):
    zrodlo = _wstaw(klient).get_json()["zrodlo"]
    w = klient.post("/api/swap/wycena", json={"zrodlo": zrodlo, "model": "nano_banana_pro", "ile": 2}).get_json()
    assert w["ok"] and w["kr_sztuka"] == 45 and w["kr"] == 90 and w["parametry"] == {"aspect_ratio": "9:16", "resolution": "2k"}
    assert w["mozna"] and cli.generacje == [] and cli.uploady == []
    r = klient.post("/api/swap/wycena", json={"zrodlo": zrodlo, "model": "seedream_v5_pro", "rozdzielczosc": "4k"})
    assert r.status_code == 400
    r = klient.post("/api/swap", json={"zrodlo": zrodlo, "model": "nano_banana_pro"})
    assert r.status_code == 400 and "cene" in r.get_json()["blad"] and baza.lista_zdjec(persona) == []
    assert klient.post("/api/swap", json={"zrodlo": "nie_ma.jpg", "kr": 45}).status_code == 400
    d = klient.post("/api/swap", json={"zrodlo": zrodlo, "model": "nano_banana_pro", "ile": 2, "kr": 45}).get_json()
    assert d["ok"] and len(d["ids"]) == 2 and d["kolejka"]["limit"] == 4 and not panel.konsola.stan["trwa"]   # bez zadania konsoli
    czekaj_na_zdjecia()
    lista = klient.get("/api/zdjecia").get_json()["zdjecia"]
    assert len(lista) == 2 and all(z["status"] == "gotowe" and z["typ"] == "swap" and z["url"] and z["zrodlo_url"] for z in lista)
    assert len(cli.generacje) == 2 and baza.wydano_dzis("higgsfield") == 90


def test_api_generuj_cena_wzrosla_i_bez_409_przy_rolkach(klient, persona, cli):
    zrodlo = _wstaw(klient).get_json()["zrodlo"]
    cli.cena = 60
    r = klient.post("/api/swap", json={"zrodlo": zrodlo, "kr": 45})
    assert r.status_code == 400 and r.get_json()["kod"] == "cena wzrosla" and "Cena wzrosla z 45 kr do 60 kr" in r.get_json()["blad"]
    assert cli.generacje == [] and baza.lista_zdjec(persona) == []
    # konsola zajeta (rolki, autopilot) - zdjecia i tak ida od razu (bez "Cos juz sie dzieje")
    panel.konsola._start("skanuj", persona)
    try:
        r = klient.post("/api/swap", json={"zrodlo": zrodlo, "kr": 60})
        assert r.status_code == 200 and len(r.get_json()["ids"]) == 1
        czekaj_na_zdjecia()
        assert len(cli.generacje) == 1 and baza.lista_zdjec(persona)[0]["status"] == "gotowe"
    finally:
        panel.konsola._koniec()


def test_api_zdjecie_w_toku_nie_do_usuniecia_i_przerwij(klient, persona, cli):
    zid = baza.dodaj_zdjecie(persona, "p", status="w_toku", typ="swap",
                             w_toku={"dostawca": "higgsfield", "model": "seedream_v5_pro", "koszt": 3, "job_id": "j9"})
    assert klient.delete(f"/api/zdjecia/{zid}").status_code == 409
    assert klient.post(f"/api/zdjecia/{zid}/przerwij", json={}).status_code == 400
    d = klient.post(f"/api/zdjecia/{zid}/przerwij", json={"potwierdzam": True}).get_json()
    assert d["ok"] and d["zdjecie"]["status"] == "blad" and "job j9" in d["zdjecie"]["notatki"]
    assert klient.delete(f"/api/zdjecia/{zid}").status_code == 200 and baza.lista_zdjec(persona) == []


def test_panel_wznawia_zdjecia_przy_starcie(klient, persona, cli):
    cli.serwer["j1"] = {"id": "j1", "job_type": "seedream_v5_pro", "status": "completed", "result": {"url": "https://cdn/w.png"}}
    zid = baza.dodaj_zdjecie(persona, "p", status="w_toku", typ="swap", zrodlo_nazwa="foto",
                             w_toku={"dostawca": "higgsfield", "model": "seedream_v5_pro", "koszt": 3, "job_id": "j1",
                                     "od": fabryka._teraz_iso()})
    assert panel.wznow_przy_starcie() is None           # 3.3: zdjecia dokancza dyspozytor zdjec, nie zadanie konsoli
    panel.start_kolejki_zdjec()
    czekaj_na_zdjecia()
    z = baza.zdjecie(persona, zid)
    assert z["status"] == "gotowe" and os.path.basename(z["plik"]) == f"{zid:03d}_swap_foto.png" and cli.generacje == []


def test_gpt_image_2_do_wyboru_z_jakoscia_obok_reszty():
    """User 2026-10-08: dodaj GPT Image 2 (tego uzywa w apce Higgsfield) - jakosc low/medium/high, do 4K; domyslny bez zmian."""
    ch = zs.chipy(zs.MODELE["gpt_image_2"]["schemat"])
    assert ch["jakosc"] == ["low", "medium", "high"] and ch["rozdzielczosc"] == ["1k", "2k", "4k"]
    assert ch["domyslne"] == {"jakosc": "high", "rozdzielczosc": "2k"}
    assert set(zs.MODELE) >= {"seedream_v5_pro", "nano_banana_pro", "gpt_image_2_5", "gpt_image_2"}
    assert zs.MODEL_DOMYSLNY == "seedream_v5_pro"
