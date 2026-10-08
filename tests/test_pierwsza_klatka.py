# -*- coding: utf-8 -*-
"""3.5: pierwsza klatka (start frame) rolek z promptu - udawane CLI Higgsfield i udawany OpenRouter, zero kredytow i sieci.
Prompt klatki (persona daleko, polskie realia, ceny z przecinkiem, bez marek i slow ryzykownych, tla usera jako baza),
wycena laczna (wideo + klatka), klatka -> wideo ze start_image + zdjecia persony, kontrola AI (max 2 dodatkowe klatki) i bez
OpenRouter, wznowienie bierze TE SAMA klatke, klatka wylaczona = stary sposob, NSFW klatki = bez wideo,
bezpieczniki, autopilot dokancza w_toku person bez autopilota, panel. 3.5.2: Wan/Gemini = tlo (zdjecie samego miejsca) jako
ostatnia referencja + zdjecia persony, bez start_image; prompt tla bez bohaterki; kontrola tla; Seedance 480p."""
import os
import re

import pytest

import app as panel
import autopilot
import baza
import fabryka
import higgsfield_cli
import instagram_rolki
import pierwsza_klatka
import scenariusz
import zdjecia_swap

CENY = {"seedance_2_5": 70, "wan3_0_prime": 30, "gemini_omni_flash_1_1": 30, "gpt_image_2_5": 2.75, "nano_banana_pro": 2,
        "gpt_image_2": 6.5, "seedream_v5_pro": 2.5}
OPCJE = {"miejsce": "sklep_osiedlowy", "dlugosc": 10, "model": "seedance_2_5", "pora": "popoludnie", "stroj": "zdjecia"}


@pytest.fixture(autouse=True)
def bez_ffmpeg(monkeypatch):
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 6.0, "szer": 720, "wys": 1280, "fps": 30.0})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    monkeypatch.setattr(fabryka.time, "sleep", lambda s: None)
    zdjecia_swap.wyczysc_cache()            # cena obrazu z cache poprzedniego testu
    yield
    zdjecia_swap.wyczysc_cache()


@pytest.fixture
def slug(modelka):
    baza.zapisz_ustawienia(modelka, mediatool=False)
    baza.zapisz_profil(modelka, wzrost_cm="158-160", sylwetka="petite hourglass figure with a big round butt")
    baza.zapisz_ustawienia_globalne(pierwsza_klatka={"wlaczona": True, "model": "gpt_image_2_5", "kontrola": True,
                                                     "max_dodatkowych": 2})
    return modelka


@pytest.fixture
def ceny(cli, monkeypatch):
    """Ceny per model jak z `generate cost` 2026-10-08 (wideo 70, klatka GPT Image 2.5 = 2,75); zapisuje zapytania."""
    zapytania = []

    def koszt(model, params=None, media=None):
        zapytania.append((model, dict(params or {}), dict(media or {})))
        return CENY.get(model, 45)
    monkeypatch.setattr(higgsfield_cli, "koszt", lambda m, p=None, me=None: int(koszt(m, p, me)))
    monkeypatch.setattr(higgsfield_cli, "koszt_dokladny", koszt)
    return zapytania


@pytest.fixture
def ai(monkeypatch):
    """Udawany OpenRouter (klucz + model wizyjny): kolejka ocen {ok, powod}; zapisuje kazde zapytanie."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(instagram_rolki, "modele_vision", lambda: ["darmowy/vision:free"])
    monkeypatch.setattr(pierwsza_klatka, "_jpg_data_url", lambda plik: "data:image/jpeg;base64,AAAA")
    stan = {"oceny": [], "pytania": [], "tresci": []}

    def zapytaj(model, data_url, pytanie=None):
        stan["pytania"].append(model)
        stan["tresci"].append(pytanie)          # 3.5.2: None = pytanie o klatke, PYTANIE_TLA = zdjecie samego miejsca
        return stan["oceny"].pop(0) if stan["oceny"] else {"ok": True, "powod": "daleko, napisy po polsku"}
    monkeypatch.setattr(pierwsza_klatka, "_zapytaj_vision", zapytaj)
    return stan


def _obrazy(cli):
    return [g for g in cli.generacje if g[0] in pierwsza_klatka.MODELE]


def _wideo(cli):
    return [g for g in cli.generacje if g[0] in scenariusz.MODELE]


def _zrob(slug, opcje=OPCJE, **kw):
    w = fabryka.wycena_z_promptu(slug, opcje)
    pid = fabryka.dodaj_z_promptu(slug, dict(opcje, ustalone=w["ustalone"]), kr=w["kr"])
    return w, pid


# ---------------- prompt klatki ----------------

def test_prompt_klatki_daleko_polskie_realia_ceny_z_przecinkiem(slug):
    sc = scenariusz.zbuduj(slug, OPCJE)
    kl = sc["klatka"]
    t = kl["prompt"]
    assert kl["model"] == "gpt_image_2_5" and kl["parametry"] == {"aspect_ratio": "9:16", "resolution": "2k", "quality": "high"}
    # daleko, mala w kadrze, zaslonieta, z telefonu, nie sesja
    for fraza in ("6-10 metres", "a quarter to a third of the frame height", "Not a photo shoot", "not a close-up",
                  "chest height", "no bokeh", "grain"):
        assert fraza in t, fraza
    assert "Blurred shoulders" in t            # kamera z kolejki = zasloniete brzegi kadru
    # prawdziwy polski sklepik: lada z kasa, papierosy, zdrapki, hot-dogi, lodowki, ceny z przecinkiem, napisy po polsku
    for fraza in ("cigarette packs", "scratch-off lottery cards", "hot-dog roller grill", "glass-door fridges", "'4,99 zł'",
                  "'OTWARTE'", "'PROMOCJA'", "'KAWA'", "'PIECZYWO'", "'ZAPRASZAMY'", "never with a dot",
                  "plain generic green sign"):
        assert fraza in t, fraza
    assert not re.search(r"\d+\.\d{2}\b", t)                     # zadnej ceny z kropka
    assert "image 1" not in t.split("[Noemi]")[0]                 # bez tla usera: obrazy 1-2 to persona
    assert "Images 1 and 2 are the only source" in t and kl["obrazy"] == baza.sciezki_referencji(slug)
    # sylwetka z profilu bez slow ryzykownych ("butt" -> "bottom"), wzrost jest
    assert zdjecia_swap.slowa_ryzykowne(t) == [] and "bottom" in t and "158-160 cm" in t
    # wideo z klatka: rusza od klatki, nie rusza napisow, kamera zostaje daleko; bez opisu [Place] od nowa
    v = sc["prompt"]
    assert "continues EXACTLY from the start frame" in v and "do not change, add, move, translate or animate any text" in v
    assert "[Place]" not in v and "never becomes a close-up" in v and "<<<image_1>>>" in v
    assert "Nobody in the clip speaks clearly" in v                # dzwiek bez mowy jak w 3.1


@pytest.mark.parametrize("miejsce", sorted(scenariusz.MIEJSCA))
def test_prompt_klatki_kazde_miejsce_bez_marek_i_slow_ryzykownych(slug, miejsce):
    sc = scenariusz.zbuduj(slug, dict(OPCJE, miejsce=miejsce, stroj="odwazny"))
    t = sc["klatka"]["prompt"]
    assert zdjecia_swap.slowa_ryzykowne(t) == [], (miejsce, zdjecia_swap.slowa_ryzykowne(t))
    norm = scenariusz._bez_ogonkow(t).lower()
    assert [m for m in scenariusz.MARKI if re.search(r"(?<![a-z])" + re.escape(m), norm)] == []
    assert not re.search(r"\d+\.\d{2}\b", t) and "6-10 metres" in t and "never with a dot" in t
    napisy = scenariusz.KLATKA_MIEJSC[miejsce][1]
    assert napisy and all(x.upper() == x for x in napisy)            # krotkie polskie napisy (wielkie litery)


def test_tlo_usera_jako_baza_kopia_bez_exif(slug, ceny):
    from PIL import Image
    folder = os.path.join(pierwsza_klatka.folder_tel(), "sklep_osiedlowy")
    os.makedirs(folder)
    tlo = os.path.join(folder, "IMG_0001.jpg")
    im = Image.new("RGB", (60, 100), (200, 200, 200))
    exif = Image.Exif()
    exif[0x010F] = "Apple"                      # producent (dane z telefonu) - kopia ma byc bez tego
    im.save(tlo, "JPEG", exif=exif)
    sc = scenariusz.zbuduj(slug, OPCJE)
    kl = sc["klatka"]
    assert kl["tlo"] == tlo and kl["obrazy"][0] == tlo and kl["obrazy"][1:] == baza.sciezki_referencji(slug)
    assert kl["prompt"].startswith("Insert Noemi into image 1") and "do not change, add, remove or re-write any text" in kl["prompt"]
    assert "Images 2 and 3 are the only source" in kl["prompt"] and sc["ustalone"]["tlo"] == "IMG_0001.jpg"
    # "Zrob": do Higgsfielda idzie KOPIA bez EXIF (GPS z telefonu nie wychodzi), oryginal zostaje
    w, pid = _zrob(slug)
    zkl = baza.pomysl(slug, pid)["z_promptu"]["klatka"]
    assert zkl["tlo_oryginal"] == tlo and zkl["tlo"] != tlo and zkl["obrazy"][0] == zkl["tlo"]
    assert os.path.dirname(zkl["tlo"]) == os.path.join(baza.folder_modelki(slug), "tla_kopie")
    with Image.open(zkl["tlo"]) as kopia:
        assert not dict(kopia.getexif())
    # tlo "bez" = scena generowana mimo zdjec w folderze
    assert scenariusz.zbuduj(slug, dict(OPCJE, tlo="bez"))["klatka"]["tlo"] is None


# ---------------- wycena ----------------

def test_wycena_laczna_wideo_plus_klatka(slug, ceny, cli):
    w = fabryka.wycena_z_promptu(slug, OPCJE)
    assert w["kr_wideo"] == 70 and w["kr_klatka"] == 2.75 and w["kr"] == 73 and w["kr_max"] == 73 and w["mozna"]
    assert w["klatka"]["model"] == "gpt_image_2_5" and w["klatka"]["kontrola"] is False      # bez klucza OpenRouter
    assert cli.generacje == [] and cli.uploady == [] and baza.lista_pomyslow(slug) == []        # wycena nic nie tworzy
    wideo = [z for z in ceny if z[0] == "seedance_2_5"]
    assert wideo and all("start_image" not in z[2] for z in wideo) and wideo[-1][1]["mode"] == "omni_reference"
    assert [z for z in ceny if z[0] == "gpt_image_2_5"][-1][2] == {}                            # cena klatki bez mediow


def test_wycena_z_kontrola_pokazuje_maksimum(slug, ceny, ai):
    w = fabryka.wycena_z_promptu(slug, OPCJE)
    assert w["kr"] == 73 and w["kr_max"] == 70 + 3 * 3 and w["klatka"]["kontrola"] and w["klatka"]["max_dodatkowych"] == 2


def test_bezpiecznik_limitu_liczy_klatke(slug, ceny, cli):
    w, pid = _zrob(slug)
    baza.dopisz_wydatek(228, "higgsfield", job_id="inny")      # 228 + 70 + 3 = 301 > 300
    wynik = fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: k <= 73)
    assert wynik["stop"] == "limit dzienny" and cli.generacje == [] and baza.pomysl(slug, pid)["status"] == "nowy"


# ---------------- klatka -> wideo ----------------

def test_klatka_potem_wideo_ze_start_image_i_zdjeciami(slug, ceny, cli):
    w, pid = _zrob(slug)
    p = baza.pomysl(slug, pid)
    assert p["koszt"] == 73 and p["z_promptu"]["klatka"]["wycena"] == 2.75 and p["z_promptu"]["wycena_wideo"] == 70
    zatwierdzone = []
    wynik = fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: zatwierdzone.append(k) or k <= 73)
    assert wynik["wygenerowane"] == 1 and zatwierdzone == [73]
    (m_kl, par_kl, med_kl), = _obrazy(cli)
    assert m_kl == "gpt_image_2_5" and par_kl["aspect_ratio"] == "9:16" and par_kl["resolution"] == "2k"
    assert par_kl["quality"] == "high" and "6-10 metres" in par_kl["prompt"] and len(med_kl["image"]) == 2
    (m_v, par_v, med_v), = _wideo(cli)
    assert m_v == "seedance_2_5" and par_v["mode"] == "omni_reference" and len(med_v["image"]) == 2
    assert ".klatka" in med_v["start_image"] and "continues EXACTLY from the start frame" in par_v["prompt"]
    p = baza.pomysl(slug, pid)
    plik = p["klatka"]["plik"]
    assert os.path.basename(plik) == f"{pid:03d}_prompt_sklep_osiedlowy.klatka.png" and os.path.isfile(plik)
    assert os.path.dirname(plik) == baza.folder_wynikow(slug)
    assert p["status"] == "gotowe" and p["koszt"] == 73 and baza.wydano_dzis("higgsfield") == 73
    assert p["job_id"] == "job2" and p["klatka"]["proby"][0]["job_id"] == "job1" and p["klatka"]["ok"] is None
    assert "job1" in baza.znane_job_id("higgsfield")
    assert any("bez kontroli AI" in x["tekst"] for x in baza.dziennik_ostatnie(50))     # bez OpenRouter - wpis w dzienniku


def test_kontrola_zla_klatka_robi_nowa(slug, ceny, cli, ai):
    ai["oceny"] = [{"ok": False, "powod": "zbliżenie, za blisko"}, {"ok": True, "powod": "daleko"}]
    w, pid = _zrob(slug)
    wynik = fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: k <= w["kr"])
    assert wynik["wygenerowane"] == 1 and len(_obrazy(cli)) == 2 and len(_wideo(cli)) == 1 and len(ai["pytania"]) == 2
    p = baza.pomysl(slug, pid)
    assert [x["ok"] for x in p["klatka"]["proby"]] == [False, True] and p["klatka"]["ok"] is True
    assert p["klatka"]["plik"].endswith(".klatka-2.png") and "klatka-2" in _wideo(cli)[0][2]["start_image"]
    assert baza.wydano_dzis("higgsfield") == 3 + 3 + 70 and p["koszt"] == 76


def test_kontrola_odrzuca_trzy_razy_bez_wideo_potem_uzyj_klatki(slug, ceny, cli, ai):
    ai["oceny"] = [{"ok": False, "powod": "dwie takie same"}] * 3
    w, pid = _zrob(slug)
    wynik = fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: k <= w["kr"])
    assert wynik["wygenerowane"] == 0 and wynik["bledy"] == [pid]
    assert len(_obrazy(cli)) == 3 and _wideo(cli) == []                       # max 2 dodatkowe klatki, wideo nie poszlo
    p = baza.pomysl(slug, pid)
    assert p["status"] == "blad" and p["powod"] == "klatka" and "0 kr na wideo" in p["notatki"] and p["w_toku"] is None
    assert baza.wydano_dzis("higgsfield") == 9 and p["klatka"]["ok"] is False
    assert panel._pomysl_dla_panelu(p)["mozna_uzyc_klatki"]
    # user: "Zrob wideo z tej klatki" -> wideo od OSTATNIEJ klatki, bez nowej klatki i bez kontroli
    pierwsza_klatka.akceptuj(slug, pid)
    assert baza.pomysl(slug, pid)["status"] == "nowy"
    wynik = fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: k <= 70)
    assert wynik["wygenerowane"] == 1 and len(_obrazy(cli)) == 3 and "klatka-3" in _wideo(cli)[0][2]["start_image"]


def test_bez_dodatkowych_klatek_w_ustawieniach(slug, ceny, cli, ai):
    baza.zapisz_ustawienia_globalne(pierwsza_klatka={"max_dodatkowych": 0})
    ai["oceny"] = [{"ok": False, "powod": "za blisko"}]
    w, pid = _zrob(slug)
    assert w["kr_max"] == 73
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True)
    assert len(_obrazy(cli)) == 1 and _wideo(cli) == [] and baza.pomysl(slug, pid)["powod"] == "klatka"


def test_klatka_odrzucona_przez_filtr_bez_wideo(slug, ceny, cli):
    # 3.5.1: filtr odrzuca wybrany model i OBA zapasy -> blad nsfw, wideo nie idzie, 0 kr
    cli.wyniki = [{"status": "nsfw"}] * 3
    w, pid = _zrob(slug)
    wynik = fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True)
    assert wynik["odrzucone"] == [pid] and _wideo(cli) == []
    assert [g[0] for g in _obrazy(cli)] == ["gpt_image_2_5", "seedream_v5_pro", "nano_banana_pro"]
    p = baza.pomysl(slug, pid)
    assert p["status"] == "blad" and p["powod"] == "nsfw" and baza.wydano_dzis("higgsfield") == 0
    assert "3 modelach" in p["notatki"] or "3 modelach" in "".join(x["tekst"] for x in baza.dziennik_ostatnie(50))
    # "Sprobuj jeszcze raz": nowa runda od wybranego modelu
    pierwsza_klatka.wyczysc_odrzucona(slug, pid)
    assert pierwsza_klatka.stan(baza.pomysl(slug, pid))["proby"] == []


def test_cena_klatki_wyzsza_niz_zatwierdzona_nic_nie_idzie(slug, ceny, cli, monkeypatch):
    w, pid = _zrob(slug)
    zdjecia_swap.wyczysc_cache()
    CENY_DROZEJ = dict(CENY, gpt_image_2_5=4.5)
    monkeypatch.setattr(higgsfield_cli, "koszt_dokladny", lambda m, p=None, me=None: CENY_DROZEJ.get(m, 45))
    # z panelu: suma 70 + 5 > 73 -> potwierdz odmawia, nic nie idzie
    assert fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: k <= 73)["pominiete"] == [pid]
    # bez potwierdzenia (CLI -y): klatka i tak sprawdza swoja zatwierdzona cene -> blad, 0 jobow
    fabryka.generuj(slug, ids=[pid])
    p = baza.pomysl(slug, pid)
    assert cli.generacje == [] and p["status"] == "blad" and "cena klatki wzrosla" in p["notatki"]


# ---------------- wznawianie: ta sama klatka ----------------

def test_wideo_przerwane_wznowienie_bez_nowej_klatki(slug, ceny, cli):
    w, pid = _zrob(slug)
    cli.wyniki = [None, {"status": "in_progress"}]          # klatka OK, wideo sie robi dluzej niz czekamy
    wynik = fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True, timeout="0s")
    assert wynik["w_toku"] == [pid] and len(_obrazy(cli)) == 1 and len(_wideo(cli)) == 1
    m = baza.pomysl(slug, pid)["w_toku"]
    assert m["job_id"] == "job2" and m.get("faza") is None and m["klatka_id"].startswith("uuid-") and m["koszt"] == 70
    cli.serwer["job2"] = {"id": "job2", "status": "completed", "result_url": "https://cdn.example/w2.mp4", "job_type": "seedance_2_5"}
    w2 = fabryka.wznow_w_toku(slug)
    assert w2["wygenerowane"] == 1 and len(cli.generacje) == 2                 # zadnej nowej klatki ani wideo
    assert baza.pomysl(slug, pid)["status"] == "gotowe" and baza.wydano_dzis("higgsfield") == 73


def test_ponow_po_bledzie_wideo_bierze_ta_sama_klatke(slug, ceny, cli, monkeypatch):
    w, pid = _zrob(slug)
    cli.wyniki = [None, {"status": "failed", "error": "server"}]
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True)
    assert baza.pomysl(slug, pid)["status"] == "blad" and len(_obrazy(cli)) == 1
    klient = panel.app.test_client()
    panel.konsola.__init__()
    assert klient.post(f"/api/pomysly/{pid}/ponow").get_json()["ok"]
    zatwierdzone = []
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: zatwierdzone.append(k) or True)
    assert zatwierdzone == [70] and len(_obrazy(cli)) == 1 and len(_wideo(cli)) == 2       # klatka juz zaplacona
    assert baza.pomysl(slug, pid)["status"] == "gotowe"


def test_restart_w_trakcie_klatki_konczy_klatke_wideo_czeka_na_zgode(slug, ceny, cli):
    w, pid = _zrob(slug)
    cli.wyniki = [{"status": "in_progress"}]
    wynik = fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True, timeout="0s")
    p = baza.pomysl(slug, pid)
    assert wynik["w_toku"] == [pid] and p["status"] == "w_toku" and p["w_toku"]["faza"] == "klatka"
    assert p["w_toku"]["job_id"] == "job1" and p["w_toku"]["obraz_id"].startswith("uuid-") and p["w_toku"]["koszt"] == 73
    assert baza.koszt_w_toku("higgsfield") == 73                               # rezerwa: klatka + wideo
    # "restart": klatka w miedzyczasie gotowa -> wznowienie konczy KLATKE, wideo nie rusza samo (~70 kr bez zgody)
    cli.serwer["job1"] = {"id": "job1", "status": "completed", "result_url": "https://cdn.example/k1.png", "job_type": "gpt_image_2_5"}
    fabryka.wznow_wszystkie()
    p = baza.pomysl(slug, pid)
    assert p["status"] == "nowy" and p["w_toku"] is None and p["klatka"]["plik"].endswith(".klatka.png")
    assert len(cli.generacje) == 1 and baza.wydano_dzis("higgsfield") == 3 and baza.koszt_w_toku("higgsfield") == 0
    # "Zrob te rolke": cena juz tylko wideo, ta sama klatka
    zatwierdzone = []
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: zatwierdzone.append(k) or True)
    assert zatwierdzone == [70] and len(_obrazy(cli)) == 1 and ".klatka.png" in _wideo(cli)[0][2]["start_image"]


def test_przerwane_wysylanie_klatki_szuka_joba_nie_wysyla_drugi_raz(slug, ceny, cli, monkeypatch):
    w, pid = _zrob(slug)
    prawdziwe = cli.generuj

    def z_bledem(model, params=None, media=None, wait=True, **k):
        prawdziwe(model, params, media, wait=wait)          # job POWSTAL...
        raise higgsfield_cli.HiggsfieldBlad("timeout po wyslaniu")     # ...a CLI zwrocilo blad
    monkeypatch.setattr(higgsfield_cli, "generuj", z_bledem)
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True, timeout="0s")
    monkeypatch.setattr(higgsfield_cli, "generuj", prawdziwe)
    # klatke odnalazl po obraz_id (swiezy upload pierwszego zdjecia), potem poszlo wideo - jedna klatka, jedno wideo
    assert len(_obrazy(cli)) == 1 and len(_wideo(cli)) == 1 and baza.pomysl(slug, pid)["status"] == "gotowe"


# ---------------- wylaczona klatka, Wan ----------------

def test_klatka_wylaczona_stary_sposob(slug, ceny, cli):
    baza.zapisz_ustawienia_globalne(pierwsza_klatka={"wlaczona": False})
    w, pid = _zrob(slug)
    assert w["kr"] == 70 and w["klatka"] is None and "start frame" not in w["prompt"]
    assert "6-10 m away the whole clip" in w["prompt"]                    # odleglosc w samym prompcie wideo
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True)
    (m, par, med), = cli.generacje
    assert m == "seedance_2_5" and "start_image" not in med and par["mode"] == "omni_reference"
    assert baza.pomysl(slug, pid).get("klatka") is None
    # per rolka: klatka "wyl" mimo wlaczonej w ustawieniach
    baza.zapisz_ustawienia_globalne(pierwsza_klatka={"wlaczona": True})
    assert fabryka.wycena_z_promptu(slug, dict(OPCJE, klatka="wyl"))["klatka"] is None


def test_wan_tlo_jako_ostatnia_referencja_bez_start_image(slug, ceny, cli):
    # 3.5.2 (platny test #9: "w ogole nie podobna"): Wan ze start_image nie dostawal zdjec persony -> teraz zdjecie SAMEGO
    # miejsca (tlo) jako OSTATNI obraz w image_references, przed nim zdjecia persony; start_image nie idzie wcale
    opcje = dict(OPCJE, model="wan3_0_prime")
    w, pid = _zrob(slug, opcje)
    assert w["kr"] == 33 and w["kr_wideo"] == 30 and w["kr_klatka"] == 2.75 and w["klatka"]["tryb"] == "tlo"
    assert w["klatka"]["obrazy"] == [] and not any("tylko z klatki" in u for u in w["ostrzezenia"])
    assert any("najpierw zdjecie samego miejsca" in u for u in w["ostrzezenia"])
    zatwierdzone = []
    wynik = fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: zatwierdzone.append(k) or k <= 33)
    assert wynik["wygenerowane"] == 1 and zatwierdzone == [33]
    (m_kl, par_kl, med_kl), = _obrazy(cli)
    assert m_kl == "gpt_image_2_5" and "image" not in med_kl and "Noemi" not in par_kl["prompt"]
    assert "nobody stands there yet" in par_kl["prompt"] and "'4,99 zł'" in par_kl["prompt"]
    p = baza.pomysl(slug, pid)
    plik_tla = p["klatka"]["plik"]
    assert os.path.basename(plik_tla) == f"{pid:03d}_prompt_sklep_osiedlowy.tlo.png" and os.path.isfile(plik_tla)
    (m, par, med), = _wideo(cli)
    assert m == "wan3_0_prime" and "start_image" not in med and par.get("mode") is None
    assert med["image"] == ["uuid-01_twarz.png", "uuid-02_sylwetka.jpg", "uuid-" + os.path.basename(plik_tla)]
    pr = par["prompt"]
    assert "Noemi is the young woman shown in reference images 1 and 2" in pr
    assert "the last reference image (image 3)" in pr and "Take only the place from image 3" in pr
    assert "continues EXACTLY from the start" not in pr and "6-10 m away" in pr and "do not invent new signs" in pr
    assert p["status"] == "gotowe" and p["koszt"] == 33 and baza.wydano_dzis("higgsfield") == 33
    assert p["klatka"]["proby"][0]["job_id"] == "job1" and p["job_id"] == "job2"


@pytest.mark.parametrize("miejsce", sorted(scenariusz.MIEJSCA))
def test_prompt_tla_bez_bohaterki_kazde_miejsce(slug, miejsce):
    sc = scenariusz.zbuduj(slug, dict(OPCJE, model="wan3_0_prime", miejsce=miejsce, stroj="odwazny"))
    kl = sc["klatka"]
    t = kl["prompt"]
    assert kl["tryb"] == "tlo" and kl["obrazy"] == [] and kl["refy_w_wideo"] and kl["mode_wideo"] is None
    assert "Noemi" not in t and "young woman" not in t and "her hair" not in t and "m behind her" not in t
    assert "It shows only the place itself" in t and "nobody stands there yet" in t and "never with a dot" in t
    assert zdjecia_swap.slowa_ryzykowne(t) == [], (miejsce, zdjecia_swap.slowa_ryzykowne(t))
    norm = scenariusz._bez_ogonkow(t).lower()
    assert [m for m in scenariusz.MARKI if re.search(r"(?<![a-z])" + re.escape(m), norm)] == []
    napisy = scenariusz.KLATKA_MIEJSC[miejsce][1]
    assert napisy[0] in t                                           # polskie napisy miejsca jak w klatce


def test_prompt_wan_tla_bez_slow_ryzykownych(slug):
    # sylwetka persony w fixturze ma "butt" (lista SLOWA_RYZYKOWNE) - prompt Wan w trybie tla zamienia je jak klatka
    for kamera in ("kolejka", "idzie_za", "zza_filaru"):
        sc = scenariusz.zbuduj(slug, dict(OPCJE, model="wan3_0_prime", kamera=kamera, stroj="odwazny",
                                          pomysl_id="sklep_osiedlowy"))
        assert zdjecia_swap.slowa_ryzykowne(sc["prompt"]) == [], (kamera, zdjecia_swap.slowa_ryzykowne(sc["prompt"]))
        assert any("W prompcie wideo zamienilem slowa" in u and "butt" in u for u in sc["ostrzezenia"])
        assert "big round bottom" in sc["prompt"] and scenariusz.AKCJA_JEDNO_UJECIE.strip() in sc["prompt"]
    for tekst in (scenariusz.KAMERA_TLO_KROTKA, scenariusz.SZABLON_KROTKI_TLO, scenariusz.TLO_SCENA,
                  pierwsza_klatka.PYTANIE_TLA):
        assert zdjecia_swap.slowa_ryzykowne(tekst) == [], tekst[:60]


def test_kontrola_tla_osobne_pytanie_zla_robi_nowe_tlo(slug, ceny, cli, ai):
    ai["oceny"] = [{"ok": False, "powod": "na srodku stoi dziewczyna"}]
    w, pid = _zrob(slug, dict(OPCJE, model="wan3_0_prime"))
    assert w["kr"] == 33 and w["kr_max"] == 30 + 3 * 3
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True)
    assert len(_obrazy(cli)) == 2 and len(_wideo(cli)) == 1
    assert ai["tresci"] == [pierwsza_klatka.PYTANIE_TLA] * 2           # pytanie o tlo, nie o klatke z persona
    for musi in ("NIE ma na nim głównej bohaterki", "w tle", "prawdziwe miejsce w Polsce", "„4,99 zł”", "zdjęcie z telefonu"):
        assert musi in pierwsza_klatka.PYTANIE_TLA, musi
    st = baza.pomysl(slug, pid)["klatka"]
    assert st["plik"].endswith(".tlo-2.png") and st["ok"] is True and st["kr"] == 6
    assert _wideo(cli)[0][2]["image"][-1] == "uuid-" + os.path.basename(st["plik"])
    assert baza.pomysl(slug, pid)["koszt"] == 36 and baza.wydano_dzis("higgsfield") == 36


def test_wan_wideo_przerwane_i_ponow_biora_to_samo_tlo(slug, ceny, cli):
    w, pid = _zrob(slug, dict(OPCJE, model="wan3_0_prime"))
    cli.wyniki = [None, {"status": "in_progress"}]          # tlo OK, wideo sie robi dluzej niz czekamy
    wynik = fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True, timeout="0s")
    p = baza.pomysl(slug, pid)
    plik_tla = p["klatka"]["plik"]
    assert wynik["w_toku"] == [pid] and p["w_toku"]["job_id"] == "job2" and p["w_toku"].get("faza") is None
    assert p["w_toku"]["klatka_id"] == "uuid-" + os.path.basename(plik_tla) and p["w_toku"]["koszt"] == 30
    cli.serwer["job2"] = {"id": "job2", "status": "failed", "error": "server", "job_type": "wan3_0_prime"}
    fabryka.wznow_w_toku(slug)
    assert baza.pomysl(slug, pid)["status"] == "blad" and len(cli.generacje) == 2      # TEN job, bez nowego wysylania
    # "Sprobuj jeszcze raz": to samo tlo (bez nowego zdjecia i bez oplaty za nie), wideo jeszcze raz za 30 kr
    klient = panel.app.test_client()
    panel.konsola.__init__()
    assert klient.post(f"/api/pomysly/{pid}/ponow").get_json()["ok"]
    zatwierdzone = []
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: zatwierdzone.append(k) or True)
    assert zatwierdzone == [30] and len(_obrazy(cli)) == 1 and len(_wideo(cli)) == 2
    assert _wideo(cli)[1][2]["image"][-1] == "uuid-" + os.path.basename(plik_tla) and "start_image" not in _wideo(cli)[1][2]
    assert baza.pomysl(slug, pid)["status"] == "gotowe" and baza.pomysl(slug, pid)["klatka"]["plik"] == plik_tla


def test_wan_przerwane_wysylanie_tla_i_wideo_szuka_joba_nie_wysyla_drugi_raz(slug, ceny, cli, monkeypatch):
    w, pid = _zrob(slug, dict(OPCJE, model="wan3_0_prime"))
    prawdziwe, listy = cli.generuj, []

    def z_bledem(model, params=None, media=None, wait=True, **k):
        prawdziwe(model, params, media, wait=wait)          # job POWSTAL...
        raise higgsfield_cli.HiggsfieldBlad("timeout po wyslaniu")     # ...a CLI zwrocilo blad
    monkeypatch.setattr(higgsfield_cli, "generuj", z_bledem)
    monkeypatch.setattr(higgsfield_cli, "joby", lambda typ=None, ile=20: listy.append(typ) or cli.joby(typ, ile))
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True, timeout="0s")
    # tlo bez zadnych zdjec (brak obraz_id) odnalezione po prompcie na liscie obrazow, wideo po id swiezo wgranego tla
    assert len(_obrazy(cli)) == 1 and len(_wideo(cli)) == 1 and baza.pomysl(slug, pid)["status"] == "gotowe"
    assert "image" in listy and "video" in listy


def test_wan_twoje_zdjecie_miejsca_jako_tlo_bez_generowania(slug, ceny, cli):
    from PIL import Image
    folder = os.path.join(pierwsza_klatka.folder_tel(), "sklep_osiedlowy")
    os.makedirs(folder)
    tlo = os.path.join(folder, "IMG_0002.jpg")
    Image.new("RGB", (60, 100), (200, 200, 200)).save(tlo, "JPEG")
    w, pid = _zrob(slug, dict(OPCJE, model="wan3_0_prime"))
    assert w["kr"] == 30 and w["kr_klatka"] == 0 and w["klatka"]["tlo"] == "IMG_0002.jpg" and w["klatka"]["obrazy"] == []
    zp = baza.pomysl(slug, pid)["z_promptu"]
    assert zp["klatka"]["tlo"] != tlo and zp["klatka"]["obrazy"] == [] and zp["wycena_wideo"] == 30
    zatwierdzone = []
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: zatwierdzone.append(k) or True)
    assert zatwierdzone == [30] and _obrazy(cli) == []                 # kopia zdjecia usera = tlo, nic do generowania
    (m, par, med), = _wideo(cli)
    assert "start_image" not in med and med["image"][-1] == "uuid-" + os.path.basename(zp["klatka"]["tlo"])
    assert baza.pomysl(slug, pid)["status"] == "gotowe" and baza.wydano_dzis("higgsfield") == 30


def test_gemini_tez_tlo_jako_referencja(slug, ceny, cli):
    w, pid = _zrob(slug, dict(OPCJE, model="gemini_omni_flash_1_1"))
    assert w["klatka"]["tryb"] == "tlo" and w["kr"] == 33
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True)
    (m, par, med), = _wideo(cli)
    assert m == "gemini_omni_flash_1_1" and par["mode"] == "reference-to-video" and "start_image" not in med
    assert len(med["image"]) == 3 and med["image"][-1].endswith(".tlo.png")


def test_seedance_480p_wariant_wycena_listy_i_start_image(slug, cli, monkeypatch):
    # 3.5.2: "Seedance 2.5 · 480p · 10 s" - twarz pewna (start_image + zdjecia persony jak Seedance 720p), tanio, mniej ostre
    def koszt(model, params=None, media=None):
        if model == "seedance_2_5":
            return {"480p": 30, "720p": 70, "1080p": 120}[params["resolution"]]
        return CENY.get(model, 45)
    monkeypatch.setattr(higgsfield_cli, "koszt", lambda m, p=None, me=None: int(koszt(m, p, me)))
    monkeypatch.setattr(higgsfield_cli, "koszt_dokladny", koszt)
    w, pid = _zrob(slug, dict(OPCJE, model="seedance_2_5_480p", dlugosc=15, rozdzielczosc="720p"))
    assert w["model"] == "seedance_2_5" and w["rozdzielczosc"] == "480p" and w["dlugosc"] == 10
    assert w["kr_wideo"] == 30 and w["kr"] == 33 and w["klatka"]["tryb"] == "start"
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: k <= 33)
    (m, par, med), = _wideo(cli)
    assert m == "seedance_2_5" and par["resolution"] == "480p" and par["duration"] == 10 and par["mode"] == "omni_reference"
    assert ".klatka" in med["start_image"] and len(med["image"]) == 2 and baza.pomysl(slug, pid)["status"] == "gotowe"
    # listy: Z promptu (katalog), autopilot (Start/Ustawienia), panel; asystent przyjmuje wariant jako reczny wybor
    kat = scenariusz.katalog(slug)
    assert [x["id"] for x in kat["modele"]][:2] == ["seedance_2_5", "seedance_2_5_480p"]
    m480 = kat["modele"][1]
    assert m480["rozdzielczosci"] == ["480p"] and m480["dlugosci"] == [10] and "mniej ostre" in m480["opis"]
    assert autopilot.MODELE_Z_PROMPTU["seedance_2_5_480p"]["model"] == "seedance_2_5"
    folder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert 'value="seedance_2_5_480p"' in open(os.path.join(folder, "templates", "index.html"), encoding="utf-8").read()
    import asystent
    a = asystent.dobierz(slug, "Noemi kupuje hot-doga", zablokowane={"model": "seedance_2_5_480p"}, uzyj_llm=False)
    assert a["opcje"]["model"] == "seedance_2_5_480p" and a["opcje"]["dlugosc"] == 10 and "Seedance 2.5 · 480p" in a["podsumowanie"]


def test_model_klatki_do_wyboru_i_zly_model(slug, ceny):
    w = fabryka.wycena_z_promptu(slug, dict(OPCJE, klatka_model="nano_banana_pro"))
    assert w["klatka"]["model"] == "nano_banana_pro" and w["kr_klatka"] == 2 and w["kr"] == 72
    with pytest.raises(ValueError):
        scenariusz.zbuduj(slug, dict(OPCJE, klatka_model="midjourney"))


# ---------------- autopilot: w_toku WSZYSTKICH person ----------------

def test_autopilot_dokancza_rolki_i_zdjecia_w_toku_person_bez_autopilota(slug, cli, monkeypatch):
    """#7 Noemi: rolka z wyslanym jobem wisiala w_toku, bo persona nie ma autopilota. Teraz kazdy przebieg ja dokancza."""
    baza.zapisz_ustawienia_globalne(pierwsza_klatka={"wlaczona": False})
    assert not baza.ustawienia_modelki(slug).get("autopilot")
    pid = fabryka.dodaj_z_promptu(slug, OPCJE, kr=45)
    cli.wyniki = [{"status": "in_progress"}]
    fabryka.generuj(slug, ids=[pid], timeout="0s")
    assert baza.pomysl(slug, pid)["status"] == "w_toku"
    cli.serwer["job1"] = {"id": "job1", "status": "completed", "result_url": "https://cdn.example/w1.mp4", "job_type": "seedance_2_5"}
    zdjecia = []
    monkeypatch.setattr(baza, "zdjecia_w_toku", lambda s: [{"id": 7}] if s == slug and not zdjecia else [])
    import zdjecia_swap as zs
    monkeypatch.setattr(zs, "wznow_w_toku", lambda s, log=None, stop=None, **k: zdjecia.append(s) or {"zrobione": 1})
    assert autopilot.cos_w_toku()
    autopilot.przebieg_wszystkich()
    assert baza.pomysl(slug, pid)["status"] == "gotowe" and len(cli.generacje) == 1      # ten sam job, nic nowego
    assert zdjecia == [slug]


def test_petla_kreci_sie_gdy_cos_w_toku_bez_person_z_autopilotem(slug, monkeypatch):
    import threading
    monkeypatch.setattr(autopilot, "_telegram", lambda: None)
    monkeypatch.setattr(autopilot, "cos_w_toku", lambda tylko=None: True)
    stop = threading.Event()
    przebiegi = []

    def przebieg(log, st):
        przebiegi.append(1)
        stop.set()
    autopilot.petla(log=lambda *a: None, stop=stop, przebieg_fn=przebieg)
    assert przebiegi == [1]


# ---------------- panel ----------------

@pytest.fixture
def klient(slug, cli):
    panel._saldo.clear()
    panel.konsola.__init__()
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        yield c


def test_api_ustawienia_klatki_katalog_wycena_i_karta(klient, slug, ceny, cli):
    d = klient.get("/api/ustawienia/globalne").get_json()
    assert d["ustawienia"]["pierwsza_klatka"]["model"] == "gpt_image_2_5"
    assert [m["id"] for m in d["modele_klatki"]] == ["gpt_image_2_5", "nano_banana_pro", "gpt_image_2", "seedream_v5_pro"]
    assert d["folder_tel"].endswith("tla")
    r = klient.post("/api/ustawienia/globalne", json={"pierwsza_klatka": {"model": "seedream_v5_pro", "max_dodatkowych": 1}})
    assert r.get_json()["ustawienia"]["pierwsza_klatka"] == {"wlaczona": True, "model": "seedream_v5_pro", "kontrola": True,
                                                             "max_dodatkowych": 1,
                                                             "zapas_nsfw": ["seedream_v5_pro", "nano_banana_pro"]}
    assert klient.post("/api/ustawienia/globalne", json={"pierwsza_klatka": {"model": "x"}}).status_code == 400
    assert klient.post("/api/ustawienia/globalne", json={"pierwsza_klatka": {"max_dodatkowych": 5}}).status_code == 400
    k = klient.get(f"/api/z-promptu?slug={slug}").get_json()
    assert k["klatka"]["domyslne"]["model"] == "seedream_v5_pro" and k["klatka"]["tla"]["folder"].endswith("tla")
    w = klient.post("/api/z-promptu/wycena", json=dict(OPCJE, slug=slug, klatka_model="gpt_image_2_5")).get_json()
    assert w["kr"] == 73 and w["kr_wideo"] == 70 and w["klatka"]["model"] == "gpt_image_2_5" and cli.generacje == []
    pid = fabryka.dodaj_z_promptu(slug, dict(OPCJE, ustalone=w["ustalone"], klatka_model="gpt_image_2_5"), kr=w["kr"])
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True)
    p = [x for x in klient.get("/api/pomysly").get_json()["pomysly"] if x["id"] == pid][0]
    assert p["ma_klatke"] and p["klatka_url"] and p["klatka_info"]["kr"] == 3 and not p["mozna_uzyc_klatki"]
    # "Zrob wideo z tej klatki": tylko gdy jest klatka i rolka nie jest w toku
    assert klient.post(f"/api/pomysly/{pid}/klatka", json={}).status_code == 400


# ---------------- 3.5.1: zapas po NSFW klatki, --klatka-model z CLI ----------------

def test_nsfw_klatki_od_razu_zapas_seedream_liczy_sie_tylko_udana(slug, ceny, cli):
    import asystent
    cli.wyniki = [{"status": "nsfw"}]
    w, pid = _zrob(slug)
    wynik = fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: k <= w["kr"])
    assert wynik["wygenerowane"] == 1 and wynik["odrzucone"] == []
    (m1, par1, _), (m2, par2, _) = _obrazy(cli)
    assert m1 == "gpt_image_2_5" and m2 == "seedream_v5_pro" and "quality" not in par2 and par2["prompt"] == par1["prompt"]
    p = baza.pomysl(slug, pid)
    assert [x.get("filtr") for x in p["klatka"]["proby"]] == ["nsfw", None] and p["klatka"]["model"] == "seedream_v5_pro"
    assert "klatka-2" in _wideo(cli)[0][2]["start_image"] and p["status"] == "gotowe"
    assert baza.wydano_dzis("higgsfield") == 3 + 70 and p["koszt"] == 73          # odrzucona klatka = 0 kr
    teksty = " | ".join(x["tekst"] for x in baza.dziennik_ostatnie(50))
    assert "klatka odrzucona przez filtr GPT Image 2.5" in teksty and "probuje Seedream 5.0 Pro" in teksty
    assert any(h.get("wynik") == "nsfw" and h.get("pid") == pid for h in asystent.historia(slug))   # asystent zapamietal
    karta = panel._pomysl_dla_panelu(p)
    assert karta["klatka_info"]["model"] == "Seedream 5.0 Pro" and karta["klatka_info"]["odrzucone_filtrem"] == 1


def test_nsfw_zapas_bez_powtorek_i_bez_drozszych(slug, ceny, cli):
    # wybrany Seedream -> zapas tylko Nano Banana Pro (Seedream sie nie powtarza)
    assert pierwsza_klatka.lancuch_modeli({"model": "seedream_v5_pro"}) == ["seedream_v5_pro", "nano_banana_pro"]
    assert pierwsza_klatka.lancuch_modeli({"model": "gpt_image_2"}) == ["gpt_image_2", "seedream_v5_pro", "nano_banana_pro"]
    cli.wyniki = [{"status": "nsfw"}, {"status": "nsfw"}]
    w, pid = _zrob(slug, dict(OPCJE, klatka_model="seedream_v5_pro"))
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True)
    assert [g[0] for g in _obrazy(cli)] == ["seedream_v5_pro", "nano_banana_pro"] and _wideo(cli) == []
    assert baza.pomysl(slug, pid)["powod"] == "nsfw" and baza.wydano_dzis("higgsfield") == 0
    # wybrany Nano Banana Pro (2 kr): Seedream (2,5 -> 3 kr) drozszy niz zatwierdzona klatka -> pominiety, nic wiecej nie idzie
    cli.generacje.clear()
    cli.wyniki = [{"status": "nsfw"}]
    w, pid = _zrob(slug, dict(OPCJE, klatka_model="nano_banana_pro"))
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True)
    assert [g[0] for g in _obrazy(cli)] == ["nano_banana_pro"] and baza.pomysl(slug, pid)["powod"] == "nsfw"
    assert any("zapas klatki Seedream 5.0 Pro pominiety" in x["tekst"] for x in baza.dziennik_ostatnie(50))


def test_nsfw_przy_wysylaniu_tez_zapas_a_kontrola_dalej_na_zapasie(slug, ceny, cli, ai):
    cli.wyniki = [higgsfield_cli.HiggsfieldBlad("request flagged by content policy")]   # create odrzucony, job nie powstal
    ai["oceny"] = [{"ok": False, "powod": "za blisko"}, {"ok": True, "powod": "daleko"}]
    w, pid = _zrob(slug)
    wynik = fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True)
    assert wynik["wygenerowane"] == 1
    assert [g[0] for g in _obrazy(cli)] == ["gpt_image_2_5", "seedream_v5_pro", "seedream_v5_pro"]
    p = baza.pomysl(slug, pid)
    assert [x.get("filtr") for x in p["klatka"]["proby"]] == ["nsfw", None, None] and p["klatka"]["proby"][0]["job_id"] is None
    assert baza.wydano_dzis("higgsfield") == 3 + 3 + 70


def test_zapas_nsfw_wylaczony(slug, ceny, cli):
    baza.zapisz_ustawienia_globalne(pierwsza_klatka={"zapas_nsfw": []})
    cli.wyniki = [{"status": "nsfw"}]
    w, pid = _zrob(slug)
    fabryka.generuj(slug, ids=[pid], potwierdz=lambda q, k, *a: True)
    assert len(_obrazy(cli)) == 1 and baza.pomysl(slug, pid)["powod"] == "nsfw"
    assert pierwsza_klatka.sprawdz_ustawienia({"zapas_nsfw": "nano_banana_pro, seedream_v5_pro"}) == {
        "zapas_nsfw": ["nano_banana_pro", "seedream_v5_pro"]}
    with pytest.raises(ValueError):
        pierwsza_klatka.sprawdz_ustawienia({"zapas_nsfw": ["x"]})


def test_cli_klatka_model_i_tlo_przezywaja_asystenta(slug, ceny, cli, capsys):
    assert fabryka.main(["--modelka", slug, "z-promptu", "--miejsce", "sklep_osiedlowy", "--asystent",
                         "--klatka-model", "nano_banana_pro", "--tlo", "bez", "--sucho"]) == 0
    out = capsys.readouterr().out
    assert "pierwsza klatka (Nano Banana Pro" in out and "klatka 2 kr" in out
    assert any(m == "nano_banana_pro" for m, _p, _me in ceny) and not any(m == "gpt_image_2_5" for m, _p, _me in ceny)
    assert fabryka.main(["--modelka", slug, "z-promptu", "--miejsce", "sklep_osiedlowy", "--asystent", "--klatka", "wyl",
                         "--sucho"]) == 0
    assert "pierwsza klatka (" not in capsys.readouterr().out
    # z generacja (-y): klatka naprawde z Nano Banana Pro, cena 70 + 2
    assert fabryka.main(["--modelka", slug, "z-promptu", "--miejsce", "sklep_osiedlowy", "--asystent",
                         "--klatka-model", "nano_banana_pro", "-y"]) == 0
    (m_kl, _par, _med), = _obrazy(cli)
    p = baza.lista_pomyslow(slug)[-1]
    assert m_kl == "nano_banana_pro" and p["z_promptu"]["klatka"]["model"] == "nano_banana_pro" and p["koszt"] == 72


@pytest.mark.parametrize("model", ["seedance_2_5", "wan3_0_prime"])
@pytest.mark.parametrize("kamera", ["kolejka", "idzie_za", "z_daleka_zoom", "mija"])
def test_wideo_z_klatka_jedno_ujecie_kamera_nie_podchodzi(slug, model, kamera):
    sc = scenariusz.zbuduj(slug, dict(OPCJE, model=model, kamera=kamera, pomysl_id="sklep_osiedlowy"))
    pr = sc["prompt"]
    assert sc["klatka"] and ("One single continuous shot" in pr or "one continuous shot with no cuts" in pr)
    for musi in ("no cuts", "never moves closer", "never zooms", "never follows her", "does not chase her",
                 "never becomes a close-up", "hand-held shake"):
        assert musi in pr, musi
    for nie in ("zoom towards", "walks slowly closer", "leans sideways", "2-3 m away", "walking past her"):
        assert nie not in pr, nie
    assert scenariusz.AKCJA_JEDNO_UJECIE.strip() in pr          # beaty z czasami = jedno ujecie, nie osobne ujecia
    if kamera in scenariusz.KAMERY_W_RUCHU:
        assert scenariusz.OPERATOR_KLATKI in pr
    kamera_txt = pr.split("amera")[-1].split("\n")[0] if model == "wan3_0_prime" else pr.split("[Camera]")[1].split("\n")[0]
    for tekst in (kamera_txt, scenariusz.KAMERA_KLATKA, scenariusz.KAMERA_KLATKA_KROTKA, scenariusz.AKCJA_JEDNO_UJECIE):
        slowa = set(re.findall(r"[a-z]+(?:[- ][a-z]+)?", tekst.lower())) | set(re.findall(r"[a-z]+", tekst.lower()))
        assert not [s for s in fabryka.SLOWA_RYZYKOWNE if s in slowa], tekst


def test_wideo_bez_klatki_dalej_z_ruchem_kamery(slug):
    sc = scenariusz.zbuduj(slug, dict(OPCJE, klatka="wyl", kamera="z_daleka_zoom", pomysl_id="sklep_osiedlowy"))
    assert sc["klatka"] is None and "zoom towards her" in sc["prompt"] and "One single continuous shot" not in sc["prompt"]
