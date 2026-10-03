# -*- coding: utf-8 -*-
"""fabryka.py na udawanym CLI Higgsfield, udawanym ffmpeg i bez Media Tool."""
import os

import pytest

import baza
import fabryka
import higgsfield_cli


@pytest.fixture(autouse=True)
def bez_ffmpeg_i_czekania(monkeypatch):
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 6.2, "szer": 720, "wys": 1280, "fps": 30.0})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    monkeypatch.setattr(fabryka.time, "sleep", lambda s: None)


def _wrzuc(slug, nazwa):
    sciezka = os.path.join(baza.folder_zrodel(slug), nazwa)
    with open(sciezka, "wb") as f:
        f.write(b"mp4")
    return sciezka


@pytest.fixture
def bez_mediatool(modelka):
    baza.zapisz_ustawienia(modelka, mediatool=False)
    return modelka


# ---------------- skanuj ----------------

def test_skanuj_wariant_a_i_b(modelka, capsys):
    _wrzuc(modelka, "klip1.mp4")
    _wrzuc(modelka, "klip2.mov")
    stroj = _wrzuc(modelka, "klip2.stroj.png")
    _wrzuc(modelka, "notatki.txt")
    assert fabryka.main(["skanuj"]) == 0
    p1, p2 = baza.lista_pomyslow(modelka)
    assert p1["prompt_higgsfield"].startswith("PROMPT A") and p1["stroj"] is None
    assert p2["prompt_higgsfield"].startswith("PROMPT B") and p2["stroj"] == stroj
    assert p1["info_zrodla"]["czas"] == 6.2
    # drugi skan nie dubluje
    assert fabryka.main(["skanuj"]) == 0
    assert len(baza.lista_pomyslow(modelka)) == 2
    assert "Brak nowych filmikow" in capsys.readouterr().out


def test_skanuj_stroj_domyslny(modelka):
    open(os.path.join(baza.folder_strojow(modelka), "mesh.png"), "wb").close()
    baza.zapisz_ustawienia(modelka, stroj_domyslny="stroje/mesh.png")
    _wrzuc(modelka, "klip.mp4")
    fabryka.main(["skanuj"])
    p = baza.pomysl(modelka, 1)
    assert p["prompt_higgsfield"].startswith("PROMPT B") and p["stroj"].endswith("mesh.png")


def test_skanuj_bez_prompt_auto(modelka, capsys):
    baza.zapisz_ustawienia(modelka, prompt_auto=False)
    _wrzuc(modelka, "klip.mp4")
    fabryka.main(["skanuj"])
    assert baza.pomysl(modelka, 1)["prompt_higgsfield"] == ""
    assert "BEZ PROMPTU" in capsys.readouterr().out


def test_skanuj_pomija_zepsuty_plik(modelka, monkeypatch):
    def zly(p):
        raise RuntimeError("ffprobe: zly plik")
    monkeypatch.setattr(fabryka.klatki, "info", zly)
    _wrzuc(modelka, "zly.mp4")
    assert fabryka.main(["skanuj"]) == 0
    assert baza.lista_pomyslow(modelka) == []


def test_skanuj_z_wrzutni_poza_projektem(modelka, tmp_path):
    przed = tmp_path / "ROLKI AI" / "przed" / "noemi"
    baza.zapisz_ustawienia(modelka, zrodla_dir=str(przed))
    _wrzuc(modelka, "klip.mp4")
    fabryka.main(["skanuj"])
    assert baza.pomysl(modelka, 1)["zrodlo"] == str(przed / "klip.mp4")


def test_brak_aktywnej_modelki(dane):
    assert fabryka.main(["status"]) == 1


# ---------------- prompt ----------------

def test_prompt_reczny(modelka):
    pid = baza.dodaj_pomysl(modelka, "x")
    assert fabryka.main(["prompt", str(pid), "nowy prompt"]) == 0
    assert baza.pomysl(modelka, pid)["prompt_higgsfield"] == "nowy prompt"


# ---------------- zlecenie ----------------

def test_zlecenie_kolejnosc_obrazow_i_duration(modelka):
    _wrzuc(modelka, "klip.mp4")
    stroj = _wrzuc(modelka, "klip.stroj.png")
    fabryka.main(["skanuj"])
    p = baza.pomysl(modelka, 1)
    model, params, media = fabryka._zlecenie(modelka, p, baza.ustawienia_modelki(modelka))
    assert model == "seedance_2_5"
    assert params["mode"] == "video_edit" and params["duration"] == 6
    assert [os.path.basename(i) for i in media["image"]] == ["01_twarz.png", "02_sylwetka.jpg", "klip.stroj.png"]
    assert media["image"][-1] == stroj
    assert media["video"] == p["zrodlo"]


@pytest.mark.parametrize("czas,oczekiwane", [(2.0, 4), (45.0, 30), (12.4, 12)])
def test_zlecenie_duration_w_zakresie_seedance(modelka, czas, oczekiwane):
    p = {"prompt_higgsfield": "x", "info_zrodla": {"czas": czas}}
    _, params, _ = fabryka._zlecenie(modelka, p, baza.ustawienia_modelki(modelka))
    assert params["duration"] == oczekiwane


def test_zlecenie_uzywa_uuid_z_cache(modelka):
    ref = baza.sciezki_referencji(modelka)[0]
    baza.zapisz_upload_id(modelka, ref, "uuid-ref1")
    _, _, media = fabryka._zlecenie(modelka, {"prompt_higgsfield": "x"}, baza.ustawienia_modelki(modelka))
    assert media["image"][0] == "uuid-ref1"


def test_wgraj(modelka, cli):
    assert fabryka.main(["wgraj"]) == 0
    ref = baza.sciezki_referencji(modelka)[0]
    assert baza.upload_id(modelka, ref) == "uuid-01_twarz.png"


# ---------------- koszt ----------------

def test_koszt_zapisuje_koszt(modelka, cli, capsys):
    _wrzuc(modelka, "a.mp4")
    _wrzuc(modelka, "b.mp4")
    fabryka.main(["skanuj"])
    assert fabryka.main(["koszt"]) == 0
    assert "razem: 90 kr" in capsys.readouterr().out
    assert [p["koszt"] for p in baza.lista_pomyslow(modelka)] == [45, 45]
    assert cli.generacje == []


def test_koszt_pomija_bez_promptu_i_bez_zrodla(modelka, cli, capsys):
    baza.dodaj_pomysl(modelka, "bez promptu", "", zrodlo="/x.mp4")
    baza.dodaj_pomysl(modelka, "bez zrodla", "prompt")
    fabryka.main(["koszt"])
    out = capsys.readouterr().out
    assert "Nic do policzenia" in out and "#2" in out


def test_generuj_id_bez_zrodla_odmawia(modelka, cli):
    pid = baza.dodaj_pomysl(modelka, "bez zrodla", "prompt")
    assert fabryka.main(["generuj", "--id", str(pid), "--tak"]) == 1
    assert cli.generacje == []


def test_generuj_id_tylko_nowy_albo_blad(modelka, cli):
    _wrzuc(modelka, "a.mp4")
    fabryka.main(["skanuj"])
    baza.aktualizuj_pomysl(modelka, 1, status="gotowe")
    assert fabryka.main(["generuj", "--id", "1", "--tak"]) == 1
    assert cli.generacje == []


# ---------------- generuj: szczesliwa sciezka ----------------

def test_generuj_pobiera_i_konczy_jako_gotowe(bez_mediatool, cli):
    slug = bez_mediatool
    _wrzuc(slug, "taniec.mp4")
    fabryka.main(["skanuj"])
    assert fabryka.main(["generuj", "--tak"]) == 0
    p = baza.pomysl(slug, 1)
    assert p["status"] == "gotowe"
    assert p["koszt"] == 45 and p["job_id"] == "job1"
    assert p["plik_wynikowy"] == os.path.join(baza.folder_gotowych(slug), "001_taniec.mp4")
    assert os.path.isfile(p["plik_wynikowy"])
    assert os.path.isfile(os.path.join(baza.folder_wynikow(slug), "001_taniec.raw.mp4"))
    assert baza.wydano_dzis() == 45
    assert cli.saldo == 955


def test_generuj_dry_run_nie_wydaje(modelka, cli, capsys):
    _wrzuc(modelka, "a.mp4")
    fabryka.main(["skanuj"])
    assert fabryka.main(["generuj", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "higgsfield generate create seedance_2_5" in out and "--image" in out
    assert cli.generacje == [] and baza.wydano_dzis() == 0


def test_generuj_bez_referencji_odmawia(modelka, cli):
    for n in os.listdir(baza.folder_referencji(modelka)):
        os.remove(os.path.join(baza.folder_referencji(modelka), n))
    _wrzuc(modelka, "a.mp4")
    fabryka.main(["skanuj"])
    assert fabryka.main(["generuj", "--tak"]) == 1
    assert cli.generacje == []


def test_generuj_pyta_bez_tak(bez_mediatool, cli, monkeypatch):
    _wrzuc(bez_mediatool, "a.mp4")
    fabryka.main(["skanuj"])
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    fabryka.main(["generuj"])
    assert cli.generacje == []
    monkeypatch.setattr("builtins.input", lambda *_: "t")
    fabryka.main(["generuj"])
    assert len(cli.generacje) == 1


def test_generuj_mediatool(modelka, cli, monkeypatch):
    import mediatool
    wywolania = []

    def udawane_pranie(plik, folder, nazwa_wyniku=None, log=None):
        wywolania.append(plik)
        cel = os.path.join(folder, nazwa_wyniku)
        open(cel, "wb").close()
        return cel
    monkeypatch.setattr(mediatool, "pierz_wideo", udawane_pranie)
    _wrzuc(modelka, "a.mp4")
    fabryka.main(["skanuj"])
    fabryka.main(["generuj", "--tak"])
    p = baza.pomysl(modelka, 1)
    assert p["status"] == "gotowe" and wywolania[0].endswith("001_a.raw.mp4")


def test_generuj_mediatool_padl_zostaje_wygenerowany(modelka, cli, monkeypatch):
    import mediatool

    def padl(*a, **k):
        raise mediatool.BrakMediaTool("brak exe")
    monkeypatch.setattr(mediatool, "pierz_wideo", padl)
    _wrzuc(modelka, "a.mp4")
    fabryka.main(["skanuj"])
    fabryka.main(["generuj", "--tak"])
    p = baza.pomysl(modelka, 1)
    assert p["status"] == "wygenerowany" and p["plik_wynikowy"].endswith(".raw.mp4")


# ---------------- bezpiecznik ----------------

def _trzy_klipy(slug):
    for n in ("a.mp4", "b.mp4", "c.mp4"):
        _wrzuc(slug, n)
    fabryka.main(["skanuj"])


def test_bezpiecznik_max_na_rolke_pomija(bez_mediatool, cli):
    cli.cena = 151
    _trzy_klipy(bez_mediatool)
    fabryka.main(["generuj", "--tak"])
    assert cli.generacje == []
    assert {p["status"] for p in baza.lista_pomyslow(bez_mediatool)} == {"nowy"}


def test_bezpiecznik_min_kredyty_stop(bez_mediatool, cli):
    cli.saldo = 300   # 300-45=255 ok, 255-45=210 ok, 210-45=165 < 200 STOP
    _trzy_klipy(bez_mediatool)
    fabryka.main(["generuj", "--tak"])
    assert len(cli.generacje) == 2
    assert baza.pomysl(bez_mediatool, 3)["status"] == "nowy"


def test_bezpiecznik_limit_dzienny(bez_mediatool, cli):
    baza.zapisz_budzet(max_kredyty_dziennie=100)
    _trzy_klipy(bez_mediatool)
    fabryka.main(["generuj", "--tak"])
    assert len(cli.generacje) == 2        # 45+45=90, trzecia dalaby 135 > 100
    assert baza.wydano_dzis() == 90


def test_bezpiecznik_limit_dzienny_liczy_wczesniejsze_wydatki(bez_mediatool, cli):
    baza.dopisz_wydatek(280)
    _trzy_klipy(bez_mediatool)
    fabryka.main(["generuj", "--tak"])
    assert cli.generacje == []


def test_koszt_nieznany_zaklada_max(bez_mediatool, cli):
    cli.cena = None
    cli.saldo = 340   # zakladamy 150 -> 340-150=190 < 200 STOP
    _trzy_klipy(bez_mediatool)
    fabryka.main(["generuj", "--tak"])
    assert cli.generacje == []


def test_blad_kosztu_oznacza_blad(bez_mediatool, cli):
    cli.blad_koszt = higgsfield_cli.HiggsfieldBlad("cost padl")
    _wrzuc(bez_mediatool, "a.mp4")
    fabryka.main(["skanuj"])
    fabryka.main(["generuj", "--tak"])
    p = baza.pomysl(bez_mediatool, 1)
    assert p["status"] == "blad" and "cost padl" in p["notatki"]
    assert cli.generacje == []


def test_brak_salda_nie_generuje(bez_mediatool, cli):
    cli.blad_kredyty = True
    _wrzuc(bez_mediatool, "a.mp4")
    fabryka.main(["skanuj"])
    assert fabryka.main(["generuj", "--tak"]) == 1
    assert cli.generacje == []


# ---------------- powtorki ----------------

def test_powtorka_po_odrzuceniu(bez_mediatool, cli):
    cli.wyniki = [higgsfield_cli.HiggsfieldBlad("rejected: nsfw")]   # druga proba = sukces
    _wrzuc(bez_mediatool, "a.mp4")
    fabryka.main(["skanuj"])
    fabryka.main(["generuj", "--tak"])
    assert len(cli.generacje) == 2
    assert baza.pomysl(bez_mediatool, 1)["status"] == "gotowe"
    assert baza.wydano_dzis() == 45   # odrzucenie nic nie kosztowalo


def test_wszystkie_proby_nieudane(bez_mediatool, cli):
    cli.wyniki = [{"id": "j", "status": "failed"}] * 3
    _wrzuc(bez_mediatool, "a.mp4")
    fabryka.main(["skanuj"])
    fabryka.main(["generuj", "--tak"])
    assert len(cli.generacje) == 3      # 1 + powtorki=2
    p = baza.pomysl(bez_mediatool, 1)
    assert p["status"] == "blad" and p["koszt"] == 0
    assert baza.wydano_dzis() == 0


def test_powtorki_zero(bez_mediatool, cli):
    baza.zapisz_ustawienia(bez_mediatool, powtorki=0)
    cli.wyniki = [higgsfield_cli.HiggsfieldBlad("rejected")]
    _wrzuc(bez_mediatool, "a.mp4")
    fabryka.main(["skanuj"])
    fabryka.main(["generuj", "--tak"])
    assert len(cli.generacje) == 1


def test_completed_bez_url_nie_powtarza(bez_mediatool, cli, monkeypatch):
    """Job sie udal, tylko parser nie widzi linku - powtorka spalilaby kredyty."""
    def completed_bez_url(model, params=None, media=None, **k):
        cli.generacje.append(model)
        cli.saldo -= 45
        return {"id": "jobX", "status": "completed", "result": {}}
    monkeypatch.setattr(higgsfield_cli, "generuj", completed_bez_url)
    odpytania = []
    monkeypatch.setattr(higgsfield_cli, "job", lambda jid: odpytania.append(jid) or {"id": jid, "status": "completed", "result_url": None})
    _wrzuc(bez_mediatool, "a.mp4")
    fabryka.main(["skanuj"])
    fabryka.main(["generuj", "--tak"])
    assert len(cli.generacje) == 1          # zadnej powtorki (spalilaby kredyty)
    assert len(odpytania) == 5              # tylko darmowe `generate get`
    p = baza.pomysl(bez_mediatool, 1)
    assert p["status"] == "blad" and p["job_id"] == "jobX" and p["koszt"] == 45
    assert baza.wydano_dzis() == 45


# ---------------- budzet / ustaw / podpis ----------------

def test_cmd_budzet(dane, capsys):
    assert fabryka.main(["budzet", "max_kredyty_dziennie=250"]) == 0
    assert baza.budzet()["max_kredyty_dziennie"] == 250


def test_cmd_ustaw(modelka):
    assert fabryka.main(["ustaw", "resolution=1080p", "powtorki=3", "mediatool=false"]) == 0
    ust = baza.ustawienia_modelki(modelka)
    assert ust["resolution"] == "1080p" and ust["powtorki"] == 3 and ust["mediatool"] is False
    assert fabryka.main(["ustaw", "zly_klucz=1"]) == 1


def test_podpis(modelka):
    pid = baza.dodaj_pomysl(modelka, "x")
    assert fabryka.main(["podpis", str(pid)]) == 1     # pusty bank
    baza.dodaj_teksty(modelka, ["hej ✨"])
    assert fabryka.main(["podpis", str(pid)]) == 0
    with open(os.path.join(baza.folder_wynikow(modelka), "001_podpis.txt"), encoding="utf-8") as f:
        assert f.read() == "hej ✨\n"


def test_completed_bez_url_doczytuje_generate_get(bez_mediatool, cli, monkeypatch):
    """Job completed z result_url=null: fabryka doczytuje `generate get` (0 kr) i konczy bez powtorki."""
    def completed_bez_url(model, params=None, media=None, **k):
        cli.generacje.append(model)
        cli.saldo -= 45
        return {"id": "jobX", "status": "completed", "result_url": None, "min_result_url": None}
    monkeypatch.setattr(higgsfield_cli, "generuj", completed_bez_url)
    monkeypatch.setattr(higgsfield_cli, "job", lambda jid: {"id": jid, "status": "completed", "result_url": "https://cdn/late.mp4"})
    _wrzuc(bez_mediatool, "a.mp4")
    fabryka.main(["skanuj"])
    fabryka.main(["generuj", "--tak"])
    assert len(cli.generacje) == 1
    p = baza.pomysl(bez_mediatool, 1)
    assert p["status"] == "gotowe" and p["wynik_url"] == "https://cdn/late.mp4" and p["koszt"] == 45


def test_zdjecia_soul_zamiast_referencji(modelka, cli):
    import zdjecia
    baza.zapisz_ustawienia(modelka, zdjecia_model="text2image_soul_v2", soul_id="soul-123")
    z = zdjecia.zlecenie(modelka, "portret")
    assert z["images"] == [] and z["soul_id"] == "soul-123"
    baza.zapisz_ustawienia(modelka, zdjecia_model="nano_banana_2")
    z = zdjecia.zlecenie(modelka, "portret")
    assert len(z["images"]) == 2 and z["soul_id"] == ""


def test_dlugi_filmik_ciety_na_kawalki(bez_mediatool, cli, monkeypatch):
    """dziel_dlugie: zrodlo > 30 s -> kawalki po 30 s jako osobne pomysly, oryginal pomijany przy nastepnym skanie."""
    slug = bez_mediatool
    zr = baza.folder_zrodel(slug)
    dlugi = _wrzuc(slug, "dlugi.mp4")
    _wrzuc(slug, "dlugi.stroj.png")
    _wrzuc(slug, "dlugi.audio.mp3")
    czasy = {dlugi: 70.0}
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": czasy.get(p, 30.0), "szer": 720, "wys": 1280, "fps": 30.0})

    def potnij(plik, folder, max_s=30, min_s=4):
        os.makedirs(folder, exist_ok=True)
        out = []
        for i in (1, 2, 3):
            p = os.path.join(folder, f"dlugi_cz{i:02d}.mp4")
            open(p, "wb").write(b"v")
            out.append(p)
        czasy[out[-1]] = 10.0
        return out
    monkeypatch.setattr(fabryka.klatki, "potnij", potnij)
    w = fabryka.skanuj(slug)
    assert w["nowe"] == [1, 2, 3]
    p1, p3 = baza.pomysl(slug, 1), baza.pomysl(slug, 3)
    assert p1["zrodlo"].endswith("dlugi_cz01.mp4") and p1["opis"].startswith("dlugi.mp4 cz. 1/3 (30.0s")
    assert p1["stroj"].endswith("dlugi.stroj.png") and p1["prompt_higgsfield"].startswith("PROMPT B")
    assert p1["audio"].endswith("dlugi.audio.mp3") and p3["audio"] is None
    assert p3["info_zrodla"]["czas"] == 10.0
    assert baza.jest_pociete(slug, dlugi) and fabryka.nowe_zrodla(slug) == []
    assert fabryka.skanuj(slug)["nowe"] == []
    # wylaczone ciecie: dlugi filmik idzie w calosci (Seedance utnie do 30 s)
    baza.zapisz_ustawienia(slug, dziel_dlugie=False)
    krotki = _wrzuc(slug, "krotki.mp4")
    czasy[krotki] = 45.0
    w = fabryka.skanuj(slug)
    assert len(w["nowe"]) == 1 and baza.pomysl(slug, w["nowe"][0])["zrodlo"] == krotki


def test_podpis_z_hashtagami(modelka):
    pid = baza.dodaj_pomysl(modelka, "x")
    baza.zapisz_profil(modelka, hashtagi="#ai #noemi")
    baza.dodaj_teksty(modelka, ["Sunset"])
    tekst, cel = fabryka.podpis(modelka, pid)
    assert tekst == "Sunset\n\n#ai #noemi"
    with open(cel, encoding="utf-8") as f:
        assert f.read() == "Sunset\n\n#ai #noemi\n"
    assert baza.pomysl(modelka, pid)["podpis"] == tekst


def test_tani_podglad_draft(bez_mediatool, cli):
    slug = bez_mediatool
    _wrzuc(slug, "a.mp4")
    fabryka.main(["skanuj"])
    cli.cena = 21
    cel = fabryka.podglad(slug, 1)
    assert cel.endswith("001_a.podglad.mp4") and os.path.isfile(cel)
    model, params, media = cli.generacje[0]
    assert params["draft"] is True and params["mode"] == "video_edit"
    p = baza.pomysl(slug, 1)
    assert p["status"] == "nowy" and p["podglad_plik"] == cel and p["podglad_koszt"] == 21
    assert baza.wydano_dzis() == 21
    # bezpiecznik dziala tez dla podgladu
    cli.saldo = 210
    with pytest.raises(ValueError, match="min_kredyty"):
        fabryka.podglad(slug, 1)
