# -*- coding: utf-8 -*-
"""3.6 (feedback usera 2026-10-10), zero kredytow, zero TTS i zero sieci (mocki):
oceny z komentarzem ("Co wyszlo zle?") -> uwagi asystenta (reguly bez LLM = stale poprawki promptu, ostatnie uwagi w prompcie LLM,
"Asystent pamieta" z usuwaniem), ostre komentarze zza kamery (domyslne, zgodne z plcia mowiacego, NIGDY w prompcie wideo/klatki),
odniesienia skali wg wzrostu persony (klatka, tlo, wideo, kontrola AI), glos jak z telefonu (bez sidechain, poglos wg miejsca,
kodek o niskim bitrate, tagi eleven_v3, nizsza stabilnosc, rotacja glosow), ciche kroki (prompt dzwieku + filtr otoczenia)."""
import json
import os
import random
import re
import shutil
import subprocess

import pytest

import app as panel
import asystent
import baza
import fabryka
import komentarz_glos
import pierwsza_klatka
import scenariusz as sc
import sekrety
import zdjecia_swap
from dostawcy import BladDostawcy, elevenlabs

MA_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@pytest.fixture(autouse=True)
def bez_ffmpeg_fabryki(monkeypatch):
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 6.0, "szer": 720, "wys": 1280, "fps": 30.0})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    monkeypatch.setattr(fabryka.time, "sleep", lambda s: None)
    asystent._cache_modeli.update(czas=0.0, modele=None)
    zdjecia_swap.wyczysc_cache()


@pytest.fixture
def slug(modelka):
    baza.zapisz_ustawienia(modelka, mediatool=False)
    baza.zapisz_profil(modelka, wzrost_cm="158-160")
    return modelka


OPCJE = {"pomysl_id": "galeria_fastfood", "dlugosc": 10, "stroj": "odwazny:krata_futerko", "reakcja": "para_kreci_glowa",
         "nazwy": "prawdziwe", "obiekt": "posnania", "pora": "popoludnie", "glos": "tts"}


def _gotowa_rolka(slug, **opcje):
    pid = fabryka.dodaj_z_promptu(slug, dict(OPCJE, **opcje), kr=70)
    baza.aktualizuj_pomysl(slug, pid, status="gotowe")
    return pid


def _slowa_ryzykowne(tekst):
    t = " " + re.sub(r"[^a-z0-9 -]+", " ", sc._bez_ogonkow(tekst)) + " "
    return [s for s in fabryka.SLOWA_RYZYKOWNE if f" {s} " in t or f" {s}s " in t]


# ---------------- 1) oceny z komentarzem -> uwagi i reguly ----------------

def test_rozpoznawanie_typowych_uwag_po_slowach_z_ogonkami_i_bez():
    r = asystent.rozpoznaj_uwage
    assert r("za blisko, wypełnia cały kadr") == ["dystans"] and r("zbliżenie na twarz") == ["dystans", "tozsamosc"]
    assert r("za wysoka") == ["wzrost"] and r("wyszla jak tyczka") == ["wzrost"] and r("ZA WYSOKA!!") == ["wzrost"]
    assert r("nie podobna, to nie ona") == ["tozsamosc"] and r("niepodobna") == ["tozsamosc"]
    assert r("napisy krzywe, literki bełkot") == ["napisy"]
    assert r("głos jak lektor, studyjny") == ["glos"] and r("glos jak z radia") == ["glos"]
    assert r("kroki za głośno, stukanie butów") == ["kroki"] and r("glosno") == ["kroki"]
    assert r("tło nierealne") == ["tlo"] and r("tlo wymyslone") == ["tlo"]
    assert r("głos za głośny") == ["glos"]                          # o komentarzu, nie o krokach
    assert r("twarz ok, ale za blisko") == ["dystans"]               # pochwala po slowie = nie skarga
    assert r("fajny klimat, smieszne") == []                         # nieznana uwaga -> tylko do LLM
    # przy "Dobra" reguly tylko, gdy tekst brzmi jak skarga
    assert r("super twarz i glos", "dobra") == [] and r("dobra, ale za wysoka", "dobra") == ["wzrost"]


def test_ocena_z_komentarzem_zapis_i_reguly_zmieniaja_prompt(slug):
    przed = sc.zbuduj(slug, OPCJE)
    assert przed["poprawki"] == [] and sc.WZROST_MOCNIEJ not in przed["prompt"]
    pid = _gotowa_rolka(slug)
    p = asystent.ocen(slug, pid, "slaba", "  za wysoka   i za blisko ")
    assert p["ocena"] == "slaba" and p["ocena_komentarz"] == "za wysoka i za blisko" and p["ocena_poprawki"] == ["dystans", "wzrost"]
    u = asystent.uwagi_aktywne()[-1]
    for k in ("persona", "pid", "model", "miejsce", "stroj", "kamera", "reakcja", "komentarz", "tekst_usera", "data", "ocena", "tekst"):
        assert k in u, k
    assert u["persona"] == slug and u["pid"] == pid and u["miejsce"] == "galeria_foodcourt" and u["stroj"] == "krata_futerko"
    assert u["tekst"] == "za wysoka i za blisko" and u["model"] == "seedance_2_5" and u["kamera"]
    # nastepna rolka: mocniejsze skalowanie wzrostu i dystans - w wideo i w zdjeciu (klatka)
    baza.zapisz_ustawienia_globalne(pierwsza_klatka={"wlaczona": True})
    po = sc.zbuduj(slug, OPCJE)
    assert po["poprawki"] == ["dystans", "wzrost"] and po["ustalone"]["poprawki"] == ["dystans", "wzrost"]
    assert sc.WZROST_MOCNIEJ in po["prompt"] and sc.POPRAWKI_PROMPTU["dystans"][0] in po["prompt"]
    assert sc.WZROST_MOCNIEJ in po["klatka"]["prompt"] and "Distance check" in po["klatka"]["prompt"]
    assert not _slowa_ryzykowne(po["prompt"]) and not _slowa_ryzykowne(po["klatka"]["prompt"])
    # Wan (tryb tla): krotki prompt wideo z poprawkami, tlo z dalszym wolnym miejscem
    wan = sc.zbuduj(slug, dict(OPCJE, model="wan3_0_prime"))
    assert "Distance check" in wan["prompt"] and "8-12 metres" in wan["klatka"]["prompt"]
    assert "[Must]" not in wan["klatka"]["prompt"]               # tlo: bez zdan o niej (na zdjeciu tla jej nie ma)
    # zamrozone w ustalonych: ta sama wycena = ten sam prompt, nawet gdy user usunie poprawke
    asystent.usun_z_pamieci(poprawka="dystans")
    assert asystent.poprawki_dla(slug) == ["wzrost"]
    assert sc.zbuduj(slug, dict(OPCJE, ustalone=po["ustalone"]))["prompt"] == po["prompt"]
    assert "Distance check" not in sc.zbuduj(slug, OPCJE)["prompt"]
    # cofniecie oceny = uwaga znika (i poprawka z niej)
    asystent.ocen(slug, pid, None)
    assert asystent.poprawki_dla(slug) == [] and asystent.uwagi_aktywne() == []
    assert baza.pomysl(slug, pid)["ocena_komentarz"] is None


def test_kazda_regula_ma_swoj_efekt(slug):
    pid = _gotowa_rolka(slug)
    asystent.ocen(slug, pid, "slaba", "nie podobna, napisy belkot, tlo nierealne, kroki glosno, glos jak lektor")
    w = sc.zbuduj(slug, OPCJE)
    assert set(w["poprawki"]) == {"tozsamosc", "napisy", "tlo", "kroki", "glos"}
    for tekst in ("Face check", "Text check", "Place check", sc.KROKI_MOCNIEJ):
        assert tekst in w["prompt"], tekst
    # glos i kroki dzialaja tez w miksie po generacji
    assert {"glos", "kroki"} <= komentarz_glos.poprawki_miksu(slug, baza.pomysl(slug, pid))


def test_zakres_persona_tylko_dla_niej_reszta_dla_wszystkich(slug):
    inna = baza.utworz_modelke("Alicja")
    pid = _gotowa_rolka(slug)
    asystent.ocen(slug, pid, "slaba", "za wysoka i za blisko")
    assert asystent.poprawki_dla(slug) == ["dystans", "wzrost"]
    assert asystent.poprawki_dla(inna) == ["dystans"]                      # wzrost Noemi nie dotyczy Alicji
    m = asystent.pamiec(inna)
    wz = [x for x in m["poprawki"] if x["klucz"] == "wzrost"][0]
    assert wz["dotyczy"] is False and wz["persony"] == ["Noemi"] and m["uwagi"][0]["tekst"] == "za wysoka i za blisko"
    # usuniecie calej uwagi = znika z regul i z LLM
    asystent.usun_z_pamieci(uwaga=m["uwagi"][0]["id"])
    assert asystent.poprawki_dla(slug) == [] and asystent.uwagi_dla_llm() == []
    with pytest.raises(ValueError):
        asystent.usun_z_pamieci(uwaga="nie-ma")
    # ocena bez tekstu nie tworzy uwagi; dobra z pochwala - uwaga dla LLM bez regul
    asystent.ocen(slug, pid, "dobra")
    assert asystent.uwagi_aktywne() == []
    asystent.ocen(slug, pid, "dobra", "świetna twarz i tło")
    assert asystent.uwagi_aktywne()[-1]["poprawki"] == [] and asystent.poprawki_dla(slug) == []
    with pytest.raises(ValueError):
        asystent.ocen(slug, pid, "super", "x")


class UdawanyOpenRouter:
    def __init__(self, odpowiedzi):
        self.odpowiedzi = list(odpowiedzi)
        self.zapytania = []

    def __call__(self, metoda, url, cialo=None, timeout=25):
        self.zapytania.append((metoda, url, cialo))
        if url.endswith("/models"):
            return {"data": [{"id": m} for m in asystent.MODELE_LLM]}
        return {"choices": [{"message": {"content": self.odpowiedzi.pop(0)}}]}


def test_uwagi_usera_ida_do_promptu_llm_a_lagodny_ton_odrzuca_wulgarne(slug, monkeypatch):
    for i, tekst in enumerate(["za wysoka", "fajny klimat ale smutna muzyka w tle"]):
        asystent.ocen(slug, _gotowa_rolka(slug), "slaba", tekst)
    sekrety.zapisz_klucz("openrouter", "sk-or-v1-test")
    odp = '{"miejsce": "metro", "stroj": "neon", "kamera": "zza_filaru", "reakcja": "szturcha_kolege", ' \
          '"komentarz": "Kurwa, patrz na nią.", "dlaczego": "Metro."}'
    u = UdawanyOpenRouter([odp])
    monkeypatch.setattr(asystent, "_http_json", u)
    w = asystent.dobierz(slug, "", zablokowane={"sezon": "jesien"})
    tresc = [z for z in u.zapytania if z[1].endswith("/chat/completions")][0][2]["messages"][1]["content"]
    assert "„za wysoka”" in tresc and "„fajny klimat ale smutna muzyka w tle”" in tresc and "disliked Noemi" in tresc
    assert "swearing" in tresc and "Co za pokemon, ja pierdolę." in tresc       # ton ostre: styl i przyklady
    assert w["opcje"]["komentarz"] == "Kurwa, patrz na nią." and w["opcje"]["komentarze_ton"] == "ostre"
    # lagodny ton: wulgarna linia z LLM odrzucona (zostaje linia regul)
    baza.zapisz_ustawienia(slug, komentarze_ton="lagodne")
    monkeypatch.setattr(asystent, "_http_json", UdawanyOpenRouter([odp]))
    w = asystent.dobierz(slug, "", zablokowane={"sezon": "jesien"})
    assert w["opcje"]["komentarz"] != "Kurwa, patrz na nią." and not sc.WULGARNE.search(sc._bez_ogonkow(w["opcje"]["komentarz"]))


# ---------------- 2) ostre komentarze ----------------

def test_pula_ostrych_komentarzy_i_zgodnosc_plci(slug):
    assert len(sc.KOMENTARZE_OSTRE) >= 20 and sc.KOMENTARZE_TON_DOMYSLNY == "ostre"
    for linia in ("Co za pokemon, ja pierdolę.", "Ja pierdolę, patrz na to.", "Kurwa, co ona ma na sobie?",
                  "Ty, zobacz to, hahaha.", "Cyrk przyjechał, ja nie mogę.", "Halloween był wczoraj czy co?",
                  "No chyba sobie jaja robisz.", "Ej, nagrywaj, nagrywaj!", "To jest jakiś cosplay, kurwa?",
                  "Matko jedyna, gdzie ona tak idzie?"):
        assert linia in sc.KOMENTARZE_OSTRE, linia
    for kto in sc.NAGRYWA:
        for linia in sc.komentarze_dla(kto, "ostre"):
            assert sc.pasuje_do_mowiacego(linia, kto), (kto, linia)
    for linia in sc.KOMENTARZE_OSTRE:                               # neutralne wzgledem mowiacego
        assert sc.pasuje_do_mowiacego(linia, "chlopak") and sc.pasuje_do_mowiacego(linia, "dziewczyna"), linia
    assert "Pierwszy raz widziałam takiego pokemona." not in sc.komentarze_dla("chlopak", "ostre")
    assert sc.dopasuj_do_mowiacego("Ja bym się tak nie odważyła, kurwa.", "chlopak") == "Ja bym się tak nie odważył, kurwa."
    w = sc.zbuduj(slug, dict(OPCJE, komentarz="Myślałem, że już wszystko widziałem.", nagrywa="dziewczyna"))
    assert w["komentarz"] == "Myślałam, że już wszystko widziałam."
    baza.zapisz_ustawienia(slug, nagrywa="dziewczyna")
    for i in range(25):
        w = sc.zbuduj(slug, dict(OPCJE, komentarz="losowy"), los=random.Random(i))
        assert w["komentarz"] in sc.komentarze_dla("dziewczyna", "ostre") and sc.pasuje_do_mowiacego(w["komentarz"], "dziewczyna")
    assert sc.zbuduj(slug, dict(OPCJE, komentarze_ton="lagodne"))["komentarz"] in sc.komentarze_dla("dziewczyna", "lagodne") + ["Jak ona wygląda."]


def test_komentarz_nigdy_w_prompcie_wideo_ani_klatki(slug, cli):
    """Filtr NSFW/IP wideo: tekst komentarza (przeklenstwa, "pokemon") idzie TYLKO do ElevenLabs."""
    baza.zapisz_ustawienia_globalne(pierwsza_klatka={"wlaczona": True})
    linie = sc.KOMENTARZE_OSTRE + sc.komentarze_dla("chlopak", "ostre")[-3:]
    for model in ("seedance_2_5", "wan3_0_prime", "gemini_omni_flash_1_1"):
        for linia in linie:
            w = sc.zbuduj(slug, dict(OPCJE, model=model, komentarz=linia))
            assert w["komentarz"] == linia
            for prompt in (w["prompt"], (w["klatka"] or {}).get("prompt") or ""):
                assert linia not in prompt and not sc.WULGARNE.search(sc._bez_ogonkow(prompt)), (model, linia)
                assert "pokemon" not in prompt.lower() and "cosplay" not in prompt.lower(), (model, linia)
    # pelna sciezka: zapisany pomysl i zlecenie dla Higgsfielda tez bez komentarza
    pid = fabryka.dodaj_z_promptu(slug, dict(OPCJE, komentarz="Co za pokemon, ja pierdolę."), kr=73)
    p = baza.pomysl(slug, pid)
    assert p["z_promptu"]["komentarz"] == "Co za pokemon, ja pierdolę."
    z = fabryka.zlecenie(slug, p)
    assert "pierdol" not in z["prompt"] and "pokemon" not in z["prompt"].lower()
    assert "pierdol" not in p["z_promptu"]["klatka"]["prompt"]


# ---------------- 3) wzrost: odniesienia skali ----------------

def test_odniesienia_skali_wg_wzrostu_w_klatce_tle_i_wideo(slug):
    baza.zapisz_ustawienia_globalne(pierwsza_klatka={"wlaczona": True})
    for wzrost, musi in (("158-160", "shoulder or chin of an average man"), ("160-162", "clearly shorter than people around her"),
                         ("168-170", "still shorter than most men"), ("170-172", "still shorter than most men")):
        baza.zapisz_profil(slug, wzrost_cm=wzrost)
        seed = sc.zbuduj(slug, OPCJE)
        wan = sc.zbuduj(slug, dict(OPCJE, model="wan3_0_prime"))
        for tekst in (seed["prompt"], seed["klatka"]["prompt"], wan["prompt"]):
            assert musi in tekst and "not a model" in tekst and "legs never lengthened" in tekst, (wzrost, tekst[:80])
        assert "platforms add only a few cm" in seed["prompt"] and "platforms add only a few cm" in seed["klatka"]["prompt"]
        assert sc.SKALA_TLA in wan["klatka"]["prompt"]                       # tlo: ludzie i rzeczy w prawdziwej skali
        for tekst in (seed["prompt"], seed["klatka"]["prompt"], wan["prompt"], wan["klatka"]["prompt"]):
            assert not _slowa_ryzykowne(tekst), _slowa_ryzykowne(tekst)
        assert "tall for a woman" not in seed["prompt"]
    for tekst in (sc.PROPORCJE, sc.PROPORCJE_KROTKO, sc.WZROST_MOCNIEJ, sc.SKALA_TLA):
        assert not _slowa_ryzykowne(tekst)
    # kontrola AI klatki i tla pyta o wzrost / proporcje
    assert "NIE jest wyższa od mężczyzn obok" in pierwsza_klatka.PYTANIE_OCENY and "proporcje" in pierwsza_klatka.PYTANIE_OCENY
    assert "normalne proporcje" in pierwsza_klatka.PYTANIE_TLA and "nienaturalnie wysoki" in pierwsza_klatka.PYTANIE_TLA


# ---------------- 4) glos jak z telefonu ----------------

def test_filtr_glosu_bez_sidechain_poglos_wg_miejsca_i_kodek(monkeypatch):
    assert komentarz_glos.przestrzen_miejsca("sklep_osiedlowy") == "maly"
    assert komentarz_glos.przestrzen_miejsca("galeria_foodcourt") == "hala"
    assert komentarz_glos.przestrzen_miejsca("przystanek") == "zewnatrz"
    assert komentarz_glos.przestrzen_miejsca("klatka") == "klatka" and komentarz_glos.przestrzen_miejsca("tramwaj") == "pojazd"
    assert komentarz_glos.przestrzen_miejsca(None) == "maly"
    sklep = komentarz_glos.lancuch_telefonu(-20, "maly")
    hala = komentarz_glos.lancuch_telefonu(-20, "hala")
    ulica = komentarz_glos.lancuch_telefonu(-20, "zewnatrz")
    assert komentarz_glos.PRZESTRZENIE["maly"][1] in sklep and komentarz_glos.PRZESTRZENIE["hala"][1] in hala
    assert komentarz_glos.PRZESTRZENIE["zewnatrz"][1] in ulica and sklep != hala != ulica
    assert "highpass=f=310" in komentarz_glos.lancuch_telefonu(-20, surowo=True)          # poprawka "glos" = surowiej
    f_ulica = komentarz_glos.filtr_miksu(2, otoczenie_lufs=-25, przestrzen="zewnatrz")
    assert "[wiatr]" in f_ulica and "amix=inputs=4" in f_ulica and "sidechain" not in f_ulica
    assert "sidechain" not in komentarz_glos.filtr_miksu(2, otoczenie_lufs=-25, przestrzen="hala")
    # kodek telefonu: Opus VoIP ~24 kb/s (albo AAC 32 kb/s), surowo 16 kb/s; krok 1 koduje glos tym kodekiem
    monkeypatch.setitem(komentarz_glos._ENKODERY, "libopus", True)
    assert komentarz_glos.kodek_telefonu() == (["-c:a", "libopus", "-b:a", "24k", "-application", "voip"], ".ogg")
    assert "16k" in komentarz_glos.kodek_telefonu(surowo=True)[0]
    monkeypatch.setitem(komentarz_glos._ENKODERY, "libopus", False)
    assert komentarz_glos.kodek_telefonu() == (["-c:a", "aac", "-b:a", "32k"], ".m4a")
    monkeypatch.setattr(komentarz_glos, "_ffmpeg", lambda: "ffmpeg")
    cmd, cel = komentarz_glos.komenda_glosu("g.mp3", "x", -21, "hala")
    assert cel == "x.m4a" and "32k" in cmd and komentarz_glos.PRZESTRZENIE["hala"][1] in cmd[cmd.index("-af") + 1]


def test_tagi_v3_dopasowane_do_linii():
    los = random.Random(1)
    assert komentarz_glos.tekst_dla_tts("Ty, zobacz to, hahaha.", los) == "Ty, zobacz to, [laughs] hahaha."
    assert komentarz_glos.tekst_dla_tts("Chyba jej się Halloween pomylił, hahaha.", los).count("[laughs]") == 1
    for i in range(20):
        r = random.Random(i)
        t = komentarz_glos.tekst_dla_tts("Kurwa, co ona ma na sobie?", r)
        assert t.split(" ")[0] in ("[chuckles]", "[sighs]", "[whispers]")
        assert not komentarz_glos.tekst_dla_tts("Ej, nagrywaj, nagrywaj!", r).startswith("[whispers]")
        t = komentarz_glos.tekst_dla_tts("Widziałaś to?", r)
        assert t.endswith("Widziałaś to?") and (t == "Widziałaś to?" or t.split(" ")[0] in komentarz_glos.TAGI_V3)
    assert komentarz_glos.tekst_dla_tts("[laughs] ") == "" and komentarz_glos.tekst_dla_tts("") == ""


def test_tts_nizsza_stabilnosc_z_zapasem_i_rotacja_glosow(slug, monkeypatch):
    wyslane = []

    def tts(tekst, vid, cel, model=None, ustawienia=None):
        wyslane.append((vid, ustawienia))
        if ustawienia:
            raise BladDostawcy("ElevenLabs 400: Invalid TTD stability value. Must be one of: [0.0, 0.5, 1.0]")
        open(cel, "wb").write(b"ID3")
        return cel
    monkeypatch.setattr(elevenlabs, "tts", tts)
    cel = os.path.join(baza.folder_audio(slug), "k.mp3")
    baza.zapisz_ustawienia(slug, glosy_rotuj=False)
    assert komentarz_glos.tts_osoby(slug, "[whispers] x", cel) == "wJmRkw9W1EUa95AGkMrg"
    assert wyslane == [("wJmRkw9W1EUa95AGkMrg", {"stability": 0.0}), ("wJmRkw9W1EUa95AGkMrg", None)]   # zapas bez ustawien
    # rotacja (domyslnie wl.): pula Max, Kris, Wiktor - rozne glosy dla roznych rolek, ten sam dla tej samej (ziarno)
    baza.zapisz_ustawienia(slug, glosy_rotuj=True)
    assert komentarz_glos.rotuj_glosy(slug) is True
    assert komentarz_glos.pula_glosow(slug) == komentarz_glos.GLOSY_PULA["chlopak"]
    pierwsze = {komentarz_glos.glosy_do_proby(slug, los=random.Random(i))[0] for i in range(30)}
    assert pierwsze == set(komentarz_glos.GLOSY_PULA["chlopak"])
    assert komentarz_glos.glosy_do_proby(slug, los=random.Random(5)) == komentarz_glos.glosy_do_proby(slug, los=random.Random(5))
    assert len(komentarz_glos.glosy_do_proby(slug, los=random.Random(5))) == 3
    assert komentarz_glos.pula_glosow(slug, "dziewczyna") == ["cgSgspJ2msm6clMCkdW9"]
    assert baza.USTAWIENIA_DOMYSLNE["glosy_rotuj"] is True and baza.USTAWIENIA_DOMYSLNE["komentarze_ton"] == "ostre"


def _wideo_testowe(sciezka, kroki=False):
    """4 s wideo z dzwiekiem otoczenia (szum) i - kroki=True - glosnymi stuknieciami co 0,5 s (jak obcasy blisko mikrofonu)."""
    audio = "anoisesrc=color=pink:amplitude=0.03:duration=4:sample_rate=48000"
    if kroki:
        audio = (f"{audio}[n];aevalsrc='0.9*sin(2*PI*900*t)*exp(-60*mod(t,0.5))':d=4:s=48000[k];"
                 f"[n][k]amix=inputs=2:normalize=0")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=180x320:rate=15:duration=4",
                    "-filter_complex", audio, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", sciezka],
                   check=True, timeout=120)


def _szczyt_db(plik):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", plik, "-vn", "-af", "astats=metadata=0", "-f", "null", "-"],
                         capture_output=True, text=True, timeout=120)
    return float(re.findall(r"Peak level dB:\s*(-?[\d.]+)", out.stderr)[-1])


# ---------------- 5) kroki/buty ciszej ----------------

def test_prompt_dzwieku_bez_glosnych_krokow(slug):
    for model in ("seedance_2_5", "wan3_0_prime", "gemini_omni_flash_1_1"):
        p = sc.zbuduj(slug, dict(OPCJE, model=model))["prompt"]
        assert "footsteps are almost inaudible" in p and "heel clicks" in p, model
        assert "distant footsteps" in p or "footsteps on tiles" not in p
    assert sc.dzwieki_z_daleka("echoing mall hall, footsteps on tiles") == "echoing mall hall, distant footsteps on tiles"
    assert not _slowa_ryzykowne(sc.DZWIEK_BEZ_MOWY + sc.DZWIEK_KROTKI_BEZ_MOWY + sc.KROKI_MOCNIEJ)
    pid = _gotowa_rolka(slug)
    asystent.ocen(slug, pid, "slaba", "buty stukaja za glosno")
    assert sc.KROKI_MOCNIEJ in sc.zbuduj(slug, OPCJE)["prompt"]


def test_filtr_otoczenia_ujarzmia_piki_bez_zabijania_gwaru():
    f = komentarz_glos.filtr_otoczenia(-24)
    assert "detection=peak" in f and "attack=0.1" in f and "ratio=6" in f and "lowpass=f=6500:p=1" in f
    prog = float(re.search(r"threshold=([\d.]+)", f).group(1))
    assert abs(prog - 10 ** ((-24 + 9) / 20)) < 0.001                        # prog wzgledem glosnosci otoczenia (gwar zostaje)
    m = komentarz_glos.filtr_otoczenia(-24, mocniej=True)
    assert "ratio=10" in m and "lowpass=f=5200" in m
    assert komentarz_glos.filtr_otoczenia(None) == "anull"


@pytest.mark.skipif(not MA_FFMPEG, reason="brak ffmpeg")
def test_obrobka_otoczenia_i_miks_naprawde(tmp_path):
    w = str(tmp_path / "kroki.mp4")
    _wideo_testowe(w, kroki=True)
    cel, otoczenie = komentarz_glos.obrob_otoczenie(w, str(tmp_path / "oto.mp4"))
    assert os.path.isfile(cel) and otoczenie is not None
    assert _szczyt_db(cel) < _szczyt_db(w) - 3                               # stukniecia przyciete
    gwar = str(tmp_path / "gwar.mp4")                                        # sam gwar (bez krokow) zostaje tak samo glosny
    _wideo_testowe(gwar)
    cel2, L2 = komentarz_glos.obrob_otoczenie(gwar, str(tmp_path / "gwar_po.mp4"))
    assert abs(komentarz_glos.glosnosc_lufs(cel2) - L2) < 1.5
    g = str(tmp_path / "g.mp3")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=1", "-c:a", "libmp3lame", g],
                   check=True, timeout=60)
    for przestrzen in ("maly", "zewnatrz"):
        out, L, lufs = komentarz_glos.zmiksuj(w, g, str(tmp_path / f"m_{przestrzen}.mp4"), 1.5, przestrzen)
        assert os.path.isfile(out) and abs(komentarz_glos.czas_wideo(out) - 4.0) < 0.3
        assert lufs == komentarz_glos.docelowa_glosnosc(L)
    assert not [n for n in os.listdir(tmp_path) if ".glos_tel" in n or n.endswith(".tmp.mp4")]   # bez smieci
    demo = komentarz_glos.probka(g, str(tmp_path / "demo.mp3"), t_s=1, otoczenie=w, przestrzen="maly")
    assert abs(komentarz_glos.czas_wideo(demo) - 4.0) < 0.3


def test_dograj_zapisuje_glos_i_uzywa_miejsca(slug, monkeypatch):
    monkeypatch.setattr(elevenlabs, "stan_klucza", lambda odswiez=False: ("ok", "klucz dziala"))
    teksty = []

    def tts(tekst, vid, cel, model=None, ustawienia=None):
        teksty.append((tekst, vid, ustawienia))
        open(cel, "wb").write(b"ID3")
        return cel
    monkeypatch.setattr(elevenlabs, "tts", tts)
    miksy = []
    monkeypatch.setattr(komentarz_glos, "zmiksuj", lambda wideo, glos, cel, t, przestrzen="maly", surowo=False,
                        kroki_mocniej=False: (miksy.append((przestrzen, surowo, kroki_mocniej)) or (cel, -24.0, -22.5)))
    pid = _gotowa_rolka(slug, komentarz="Ty, zobacz to, hahaha.")
    asystent.ocen(slug, pid, "slaba", "glos jak lektor")
    wideo = os.path.join(baza.folder_wynikow(slug), f"{pid:03d}_x.raw.mp4")
    open(wideo, "wb").write(b"mp4")
    cel = komentarz_glos.dograj(slug, pid, wideo, "Ty, zobacz to, hahaha.", 5)
    assert cel.endswith("_x.glos.mp4") and miksy == [("hala", True, False)]   # galeria = hala, poprawka "glos" = surowiej
    assert teksty[0][0] == "Ty, zobacz to, [laughs] hahaha." and teksty[0][2] == {"stability": 0.0}
    p = baza.pomysl(slug, pid)
    assert p["glos_id"] in komentarz_glos.GLOSY_PULA["chlopak"] and p["glos_przestrzen"] == "hala"


def test_rolka_bez_komentarza_ma_ciche_kroki_po_generacji(slug, cli, monkeypatch):
    wywolania = []

    def obrob(wideo, cel, mocniej=False):
        wywolania.append((wideo, cel, mocniej))
        open(cel, "wb").write(b"mp4-otoczenie")
        return cel, -24.0
    monkeypatch.setattr(komentarz_glos, "obrob_otoczenie", obrob)
    pid = fabryka.dodaj_z_promptu(slug, dict(OPCJE, komentarz="bez"), kr=45)
    assert fabryka.generuj(slug, ids=[pid])["wygenerowane"] == 1
    p = baza.pomysl(slug, pid)
    assert len(wywolania) == 1 and wywolania[0][0].endswith(".raw.mp4") and wywolania[0][1].endswith(".otoczenie.mp4")
    assert p["status"] == "gotowe" and open(p["plik_wynikowy"], "rb").read() == b"mp4-otoczenie"
    # blad obrobki nie psuje oplaconej rolki
    monkeypatch.setattr(komentarz_glos, "obrob_otoczenie", lambda *a, **k: (_ for _ in ()).throw(komentarz_glos.BladGlosu("x")))
    pid2 = fabryka.dodaj_z_promptu(slug, dict(OPCJE, komentarz="bez"), kr=45)
    fabryka.generuj(slug, ids=[pid2])
    assert baza.pomysl(slug, pid2)["status"] == "gotowe" and open(baza.pomysl(slug, pid2)["plik_wynikowy"], "rb").read() == b"mp4"


# ---------------- panel ----------------

@pytest.fixture
def klient(slug, cli):
    panel._saldo.clear()
    panel.konsola.__init__()
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        yield c


def test_api_ocena_z_komentarzem_pamiec_i_ustawienia(klient, slug):
    pid = _gotowa_rolka(slug)
    d = klient.post(f"/api/pomysly/{pid}/ocena", json={"ocena": "slaba", "komentarz": "za wysoka, glos jak lektor"}).get_json()
    assert d["ok"] and d["pomysl"]["ocena_komentarz"] == "za wysoka, glos jak lektor"
    assert d["pomysl"]["ocena_poprawki_nazwy"] == ["Mocniej pilnuje wzrostu", "Bardziej surowy głos (jak z telefonu)"]
    assert {x["klucz"] for x in d["pamiec"]["poprawki"]} == {"wzrost", "glos"}
    m = klient.get("/api/asystent/pamiec").get_json()
    assert m["ok"] and len(m["uwagi"]) == 1 and m["uwagi"][0]["persona_nazwa"] == "Noemi"
    m = klient.post("/api/asystent/pamiec/usun", json={"poprawka": "glos"}).get_json()
    assert m["ok"] and {x["klucz"] for x in m["poprawki"]} == {"wzrost"}
    assert klient.post("/api/asystent/pamiec/usun", json={"uwaga": "nie-ma"}).status_code == 400
    m = klient.post("/api/asystent/pamiec/usun", json={"uwaga": m["uwagi"][0]["id"]}).get_json()
    assert m["poprawki"] == [] and m["uwagi"] == []
    assert klient.post(f"/api/pomysly/{pid}/ocena", json={"ocena": "zla", "komentarz": "x"}).status_code == 400
    # ustawienia persony: ton komentarzy i rotacja glosow
    u = klient.post("/api/ustawienia", json={"komentarze_ton": "lagodne", "glosy_rotuj": False}).get_json()["ustawienia"]
    assert u["komentarze_ton"] == "lagodne" and u["glosy_rotuj"] is False
    assert klient.post("/api/ustawienia", json={"komentarze_ton": "brutalne"}).status_code == 400
    kat = klient.get("/api/z-promptu").get_json()
    assert kat["persona"]["komentarze_ton"] == "lagodne" and "Co za pokemon, ja pierdolę." in kat["komentarze_ostre"]
    assert dict(kat["komentarze_tony"]).keys() == {"ostre", "lagodne"}
    w = klient.post("/api/z-promptu/wycena", json=dict(OPCJE, komentarz="losowy")).get_json()
    assert w["ok"] and w["ustalone"]["komentarze_ton"] == "lagodne" and not sc.WULGARNE.search(sc._bez_ogonkow(w["komentarz"]))


def test_panel_bez_autoplay_i_z_polem_uwagi():
    """Statyczna kontrola panelu: filmy nie graja same (bez autoplay, start tylko z klikniecia), pole uwagi i Asystent pamieta."""
    katalog = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = open(os.path.join(katalog, "static", "app.js"), encoding="utf-8").read()
    html = open(os.path.join(katalog, "templates", "index.html"), encoding="utf-8").read()
    wideo = re.findall(r"<video\s[^>]*controls[^>]*>", js + html)
    assert len(wideo) >= 3 and not [v for v in wideo if "autoplay" in v] and ".autoplay" not in js
    assert all("data-wideo=" in v for v in wideo)
    assert "function zatrzymajWideo" in js and "function przerysujZWideo" in js and "odtworzWideo(" in js
    assert "Co wyszło źle?" in js and "data-ocena-tekst" in js and 'id="zp-pamiec"' in html
    assert 'name="komentarze_ton"' in html and 'name="glosy_rotuj"' in html
