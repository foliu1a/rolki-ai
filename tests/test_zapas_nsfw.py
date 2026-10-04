# -*- coding: utf-8 -*-
"""Zapas po odrzuceniu NSFW/IP: Seedance (Higgsfield) -> yapper wan-3.0-prime -> wan-3.0. Jedna proba na krok, wlasny bezpiecznik
yappera (bez dziennego limitu = zero zapytan), proby w p['proby'], koszt raz, hamulec nie liczy NSFW. yapper na udawanym HTTP
z DOKLADNYMI adresami."""
import json
import os

import pytest

import autopilot
import baza
import fabryka
import sekrety
from dostawcy import http
from test_dostawcy import MODEL_WAN, SCHEMAT_WAN, Y, _bilety, _dry, udawany_http  # noqa: F401 - fixtura

ZAPAS = [{"dostawca": "yapper", "model": "wan-3.0-prime"}, {"dostawca": "yapper", "model": "wan-3.0"}]
MODEL_PRIME = dict(MODEL_WAN, id="wan-3.0-prime", displayName="WAN 3.0 Prime")
PROMPT_WAN = "Recreate the reference video, replacing the woman with the woman from the reference photos."
NSFW_HF = {"id": "hf1", "status": "nsfw", "result_url": None}


@pytest.fixture(autouse=True)
def bez_ffmpeg(monkeypatch):
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 6.0, "szer": 720, "wys": 1280, "fps": 30.0})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    monkeypatch.setattr(fabryka, "_plik_sie_zmienia", lambda p, odstep=0: False)


@pytest.fixture
def slug(modelka, cli, udawany_http):
    """Persona z zapasem po NSFW, kluczem yappera, promptem Wan i dziennym limitem yappera 500 (decyzja usera)."""
    sekrety.zapisz_klucz("yapper", "yk_test")
    baza.zapisz_ustawienia(modelka, mediatool=False, zapas_nsfw=ZAPAS)
    baza.zapisz_prompt(modelka, "wan.txt", PROMPT_WAN)
    baza.zapisz_limit_dzienny(500, "yapper")
    u = udawany_http
    u.ustaw("GET", Y + "/credits", {"totalCredits": 7000, "usedCredits": 0, "availableCredits": 7000})
    u.ustaw("GET", Y + "/models", [MODEL_PRIME, MODEL_WAN])
    u.ustaw("GET", Y + "/models/wan-3.0-prime/schema.json", SCHEMAT_WAN)
    u.ustaw("GET", Y + "/models/wan-3.0/schema.json", SCHEMAT_WAN)
    _bilety(u, "i1", "i2", "v1")
    return modelka


def _rolka(slug, nazwa="a.mp4"):
    open(os.path.join(baza.folder_zrodel(slug), nazwa), "wb").write(b"mp4")
    fabryka.skanuj(slug)


def _proc(pid, status="queued", **pola):
    return dict({"id": pid, "status": status, "type": "video-generation"}, **pola)


def _gotowy(pid, kr):
    return _proc(pid, "completed", creditsUsed=kr, refunded=False, outputs=[{"type": "video", "assetId": "o", "url": f"https://cdn.yapper/{pid}.mp4"}])


def _nsfw(pid, kr):
    return _proc(pid, "failed", creditsUsed=kr, refunded=True, error={"code": "content_moderation", "message": "flagged as NSFW by the safety filter"})


def _prawdziwe_posty(u):
    return [w for w in u.posty(Y + "/processes") if not (w[2] or {}).get("dryRun")]


def test_nsfw_potem_prime_ok(slug, cli, udawany_http):
    u = udawany_http
    _rolka(slug)
    cli.wyniki = [dict(NSFW_HF)]
    u.ustaw("POST", Y + "/processes", _dry(250, model="wan-3.0-prime"), _proc("p1"))
    u.ustaw("GET", Y + "/processes/p1", _proc("p1", "processing"), _gotowy("p1", 250))
    w = fabryka.generuj(slug)
    assert w["wygenerowane"] == 1 and not w["bledy"] and len(cli.generacje) == 1      # Seedance raz, bez powtorki
    p = baza.pomysl(slug, 1)
    assert p["status"] == "gotowe" and p["zapas"] is True and p["dostawca"] == "yapper" and p["model"] == "wan-3.0-prime"
    assert p["koszt"] == 250 and p["wynik_url"] == "https://cdn.yapper/p1.mp4" and p["w_toku"] is None
    assert [(x["dostawca"], x["model"], x["status"], x["powod"], x["kr"]) for x in p["proby"]] == [
        ("higgsfield", "seedance_2_5", "nsfw", "nsfw", 0), ("yapper", "wan-3.0-prime", "completed", None, 250)]
    assert baza.wydano_dzis("higgsfield") == 0 and baza.wydano_dzis("yapper") == 250      # bez podwojnego liczenia
    dry, real = u.posty(Y + "/processes")
    assert dry[2]["dryRun"] is True and dry[2]["model"] == "wan-3.0-prime"
    wej = real[2]["input"]
    assert wej["prompt"] == PROMPT_WAN and "generateAudio" not in wej and wej["durationMode"] == "auto" and wej["resolution"] == 1080
    assert real[3]["Idempotency-Key"] == f"rolki-{slug}-1-wan-3.0-prime-1"
    assert any("NSFW -> zapas wan-3.0-prime" in x["tekst"] for x in baza.dziennik_ostatnie(50))
    # drugi przebieg: nic nowego, koszty bez zmian
    assert fabryka.generuj(slug)["wygenerowane"] == 0
    assert baza.wydano_dzis("yapper") == 250 and len(_prawdziwe_posty(u)) == 1
    # panel: plakietka
    import app as panel
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        assert c.get("/api/pomysly").get_json()["pomysly"][0]["zapas_opis"] == "zrobione na wan-3.0-prime (zapas)"


def test_nsfw_prime_nsfw_potem_wan_ok(slug, cli, udawany_http):
    u = udawany_http
    _rolka(slug)
    cli.wyniki = [dict(NSFW_HF)]
    u.ustaw("POST", Y + "/processes", _dry(250, model="wan-3.0-prime"), _proc("p1"), _dry(300), _proc("p2"))
    u.ustaw("GET", Y + "/processes/p1", _nsfw("p1", 250))
    u.ustaw("GET", Y + "/processes/p2", _gotowy("p2", 300))
    w = fabryka.generuj(slug)
    assert w["wygenerowane"] == 1
    p = baza.pomysl(slug, 1)
    assert p["model"] == "wan-3.0" and p["zapas"] is True and p["koszt"] == 300
    assert [x["status"] for x in p["proby"]] == ["nsfw", "failed", "completed"] and p["proby"][1]["powod"] == "nsfw"
    assert baza.wydano_dzis("yapper") == 300                          # odrzucony prime oddal kredyty (refunded)
    assert [x[3]["Idempotency-Key"] for x in _prawdziwe_posty(u)] == [f"rolki-{slug}-1-wan-3.0-prime-1", f"rolki-{slug}-1-wan-3.0-1"]


def test_wszystko_nsfw_jeden_blad(slug, cli, udawany_http):
    u = udawany_http
    _rolka(slug)
    cli.wyniki = [dict(NSFW_HF)]
    u.ustaw("POST", Y + "/processes", _dry(250, model="wan-3.0-prime"), _proc("p1"), _dry(300), _proc("p2"))
    u.ustaw("GET", Y + "/processes/p1", _nsfw("p1", 250))
    u.ustaw("GET", Y + "/processes/p2", _nsfw("p2", 300))
    w = fabryka.generuj(slug)
    assert w["bledy"] == [1] and w["odrzucone"] == [1] and w["wygenerowane"] == 0
    p = baza.pomysl(slug, 1)
    assert p["status"] == "blad" and p["powod"] == "nsfw" and len(p["proby"]) == 3 and p["koszt"] == 0
    assert len(cli.generacje) == 1 and len(_prawdziwe_posty(u)) == 2
    assert baza.wydano_dzis("yapper") == 0 and baza.wydano_dzis("higgsfield") == 0
    assert len([x for x in baza.dziennik_ostatnie(80) if x["typ"] == "blad" and "ODRZUCONE" in x["tekst"]]) == 1


def test_bez_dziennego_limitu_yappera_zero_zapytan(slug, cli, udawany_http):
    baza.zapisz_limit_dzienny(0, "yapper")
    _rolka(slug)
    cli.wyniki = [dict(NSFW_HF)]
    w = fabryka.generuj(slug)
    assert udawany_http.wywolania == [] and w["odrzucone"] == [1]
    p = baza.pomysl(slug, 1)
    assert p["status"] == "blad" and p["powod"] == "nsfw" and "limit yappera nie jest ustawiony" in p["notatki"]
    assert any("zapas po NSFW pominiety" in x["tekst"] and "budzet max_kredyty_dziennie=500 --dostawca yapper" in x["tekst"]
               for x in baza.dziennik_ostatnie(50))


def test_wyczerpany_limit_yappera_zero_zapytan(slug, cli, udawany_http):
    baza.dopisz_wydatek(500, "yapper")
    _rolka(slug)
    cli.wyniki = [dict(NSFW_HF)]
    fabryka.generuj(slug)
    assert udawany_http.wywolania == [] and "wyczerpany (500/500 kr)" in baza.pomysl(slug, 1)["notatki"]


def test_wycena_canstart_false_pomija_krok(slug, cli, udawany_http):
    u = udawany_http
    _rolka(slug)
    cli.wyniki = [dict(NSFW_HF)]
    u.ustaw("POST", Y + "/processes", _dry(250, can_start=False, blocked="team_limit", model="wan-3.0-prime"), _dry(300), _proc("p2"))
    u.ustaw("GET", Y + "/processes/p2", _gotowy("p2", 300))
    assert fabryka.generuj(slug)["wygenerowane"] == 1
    p = baza.pomysl(slug, 1)
    assert [(x["model"], x["status"]) for x in p["proby"]] == [("seedance_2_5", "nsfw"), ("wan-3.0-prime", "pominiete"), ("wan-3.0", "completed")]
    assert "team_limit" in p["proby"][1]["info"] and len(_prawdziwe_posty(u)) == 1


def test_zapas_drozszy_niz_limit_dnia_pomija(slug, cli, udawany_http):
    baza.dopisz_wydatek(300, "yapper")
    _rolka(slug)
    cli.wyniki = [dict(NSFW_HF)]
    udawany_http.ustaw("POST", Y + "/processes", _dry(250, model="wan-3.0-prime"), _dry(300))
    fabryka.generuj(slug)
    p = baza.pomysl(slug, 1)
    assert [x["powod"] for x in p["proby"][1:]] == ["limit", "limit"] and not _prawdziwe_posty(udawany_http)
    assert p["status"] == "blad" and p["powod"] == "nsfw" and baza.wydano_dzis("yapper") == 300


def test_ten_sam_idempotency_key_przy_powtorce(slug, cli, udawany_http):
    """POST /processes padl (503, nie wiadomo, czy proces powstal) -> powtorka z TYM SAMYM kluczem: yapper odda ten sam proces."""
    u = udawany_http
    _rolka(slug)
    cli.wyniki = [dict(NSFW_HF)]
    u.ustaw("POST", Y + "/processes", _dry(250, model="wan-3.0-prime"), http.BladHTTP(503, "upstream timeout", Y + "/processes"), _proc("p1"))
    u.ustaw("GET", Y + "/processes/p1", _gotowy("p1", 250))
    assert fabryka.generuj(slug)["wygenerowane"] == 1
    posty = _prawdziwe_posty(u)
    assert len(posty) == 2 and posty[0][3]["Idempotency-Key"] == posty[1][3]["Idempotency-Key"] == f"rolki-{slug}-1-wan-3.0-prime-1"
    assert posty[0][2] == posty[1][2]                                  # to samo cialo (warunek idempotencji)
    assert len(u.posty(Y + "/assets/uploads")) == 3                    # pliki wgrane raz (cache), nie przy kazdej probie
    assert baza.wydano_dzis("yapper") == 250


def test_timeout_yappera_to_wznowienie(slug, cli, udawany_http):
    u = udawany_http
    _rolka(slug)
    cli.wyniki = [dict(NSFW_HF)]
    u.ustaw("POST", Y + "/processes", _dry(250, model="wan-3.0-prime"), _proc("p1"))
    u.ustaw("GET", Y + "/processes/p1", _proc("p1", "processing"))
    w = fabryka.generuj(slug, timeout="0s")
    p = baza.pomysl(slug, 1)
    assert w["w_toku"] == [1] and p["status"] == "w_toku" and p["w_toku"]["krok"] == 1 and p["job_id"] == "p1"
    u.ustaw("GET", Y + "/processes/p1", _gotowy("p1", 250))
    assert fabryka.wznow_w_toku(slug)["wygenerowane"] == 1
    assert len(_prawdziwe_posty(u)) == 1 and len(cli.generacje) == 1 and baza.wydano_dzis("yapper") == 250
    assert baza.pomysl(slug, 1)["model"] == "wan-3.0-prime"


def test_awaria_miedzy_krokami_rusza_od_zapasu(slug, cli, udawany_http, monkeypatch):
    """Proces pada po odrzuceniu Seedance, zanim ruszyl zapas -> rolka czeka jako 'nowy' z krok_startowy=1 i nastepny przebieg
    zaczyna od wan-3.0-prime (Seedance nie dostaje drugi raz tych samych wejsc)."""
    _rolka(slug)
    cli.wyniki = [dict(NSFW_HF)]
    prawdziwe = fabryka._przygotuj_zapas
    monkeypatch.setattr(fabryka, "_przygotuj_zapas", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("awaria procesu")))
    with pytest.raises(RuntimeError):
        fabryka.generuj(slug)
    p = baza.pomysl(slug, 1)
    assert p["status"] == "nowy" and p["krok_startowy"] == 1 and p["w_toku"] is None
    monkeypatch.setattr(fabryka, "_przygotuj_zapas", prawdziwe)
    udawany_http.ustaw("POST", Y + "/processes", _dry(250, model="wan-3.0-prime"), _proc("p1"))
    udawany_http.ustaw("GET", Y + "/processes/p1", _gotowy("p1", 250))
    assert fabryka.generuj(slug)["wygenerowane"] == 1 and len(cli.generacje) == 1
    assert baza.pomysl(slug, 1)["model"] == "wan-3.0-prime"


def test_ponow_po_nsfw_zaczyna_od_zapasu(slug, cli, udawany_http):
    """Rolka odrzucona (zapas wtedy wylaczony) -> user wlacza zapas i klika 'Sprobuj jeszcze raz' -> od razu wan-3.0-prime."""
    u = udawany_http
    baza.zapisz_ustawienia(slug, zapas_nsfw=[])
    _rolka(slug)
    cli.wyniki = [dict(NSFW_HF)]
    fabryka.generuj(slug)
    assert baza.pomysl(slug, 1)["powod"] == "nsfw" and u.wywolania == []
    baza.zapisz_ustawienia(slug, zapas_nsfw=ZAPAS)
    u.ustaw("POST", Y + "/processes", _dry(250, model="wan-3.0-prime"), _dry(250, model="wan-3.0-prime"), _proc("p1"))
    u.ustaw("GET", Y + "/processes/p1", _gotowy("p1", 250))
    import app as panel
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        d = c.post("/api/pomysly/1/ponow").get_json()
        assert d["ok"] and d["od_zapasu"] is True and d["pomysl"]["krok_startowy"] == 1
    k = fabryka.koszt(slug, ids=[1])                                   # wycena dla panelu = dryRun zapasu
    assert k["pozycje"] == [(1, 250, "yapper")]
    assert fabryka.generuj(slug, ids=[1])["wygenerowane"] == 1
    assert len(cli.generacje) == 1                                     # Seedance nie dostal drugi raz tych samych wejsc
    p = baza.pomysl(slug, 1)
    assert p["zapas"] is True and p["krok_startowy"] is None and p["proby"][-1]["model"] == "wan-3.0-prime"


def test_hamulec_nie_liczy_nsfw(slug, cli, udawany_http, monkeypatch):
    baza.zapisz_ustawienia(slug, autopilot=True, autopilot_stop_po_bledach=2, zapas_nsfw=[])
    for n in ("a.mp4", "b.mp4", "c.mp4"):
        open(os.path.join(baza.folder_zrodel(slug), n), "wb").write(b"v")
    cli.wyniki = [dict(NSFW_HF, id=f"hf{i}") for i in range(3)]
    w = autopilot.przebieg(slug)
    assert w["wygenerowane"] == 0 and len(w["bledy"]) == 3 and w["stop"] != "hamulec"
    ap = baza.autopilot_stan(slug)
    assert ap["pauza"] is None and ap["bledy_z_rzedu"] == 0
    # awaria techniczna (przed wyslaniem - wgranie filmiku padlo) liczy sie normalnie
    import higgsfield_cli
    baza.zapisz_ustawienia(slug, powtorki=0)
    for n in ("d.mp4", "e.mp4"):
        open(os.path.join(baza.folder_zrodel(slug), n), "wb").write(b"v")
    monkeypatch.setattr(higgsfield_cli, "upload", lambda *a, **k: (_ for _ in ()).throw(higgsfield_cli.HiggsfieldBlad("blad sieci")))
    assert autopilot.przebieg(slug)["stop"] == "hamulec"


def test_wan_dluzszy_niz_15s_przycinany(slug, cli, udawany_http, monkeypatch):
    u = udawany_http
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 15.5, "szer": 720, "wys": 1280, "fps": 30.0})
    przyciete = []

    def przytnij(plik, cel, max_s):
        przyciete.append((plik, max_s))
        os.makedirs(os.path.dirname(cel), exist_ok=True)
        open(cel, "wb").write(b"krotszy")
        return cel
    monkeypatch.setattr(fabryka.klatki, "przytnij", przytnij)
    _rolka(slug)
    cli.wyniki = [dict(NSFW_HF)]
    u.ustaw("POST", Y + "/processes", _dry(380, model="wan-3.0-prime"), _proc("p1"))
    u.ustaw("GET", Y + "/processes/p1", _gotowy("p1", 380))
    assert fabryka.generuj(slug)["wygenerowane"] == 1
    assert przyciete and przyciete[0][0].endswith("a.mp4") and abs(przyciete[0][1] - 14.9) < 1e-6
    wgrane = [w for w in u.posty(Y + "/assets/uploads")]
    assert any(w[2]["name"] == "a_max15s.mp4" for w in wgrane)
    real = _prawdziwe_posty(u)[0][2]["input"]
    assert real["resolution"] == 720                                   # 15,5 s -> 720p (zasada <= 8 s -> 1080p)
    assert os.path.isfile(os.path.join(baza.folder_zrodel(slug), "a.mp4"))   # oryginal zostaje


def test_diagnoza_yapper_i_prompt_wan(slug, cli, udawany_http):
    d = {w["co"]: w for w in fabryka.diagnoza()}
    assert d["yapper"]["ok"] is True and "7000" in d["yapper"]["info"]
    assert d["limit yappera"]["ok"] is True and "0/500" in d["limit yappera"]["info"]
    baza.zapisz_limit_dzienny(0, "yapper")
    d = {w["co"]: w for w in fabryka.diagnoza()}
    assert d["limit yappera"]["ok"] is False and "nie ustawiony" in d["limit yappera"]["info"]
    assert fabryka.sprawdz_prompt_wan(slug) == []
    baza.zapisz_prompt(slug, "wan.txt", "x @[Image 1](image_1) " + "y" * 5000)
    uwagi = fabryka.sprawdz_prompt_wan(slug)
    assert any("max 5000" in x for x in uwagi) and any("@[Image N]" in x for x in uwagi)
    assert any("prompt Wan" in x for x in fabryka.sprawdz_prompt(slug))


def test_ustawienie_zapas_nsfw_z_panelu(slug):
    import app as panel
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        r = c.post("/api/ustawienia", json={"zapas_nsfw": json.dumps(ZAPAS)})
        assert r.status_code == 200 and r.get_json()["ustawienia"]["zapas_nsfw"] == ZAPAS
        assert c.post("/api/ustawienia", json={"zapas_nsfw": "[]"}).get_json()["ustawienia"]["zapas_nsfw"] == []
        assert c.post("/api/ustawienia", json={"zapas_nsfw": '[{"model": "x"}]'}).status_code == 400
    assert baza.USTAWIENIA_DOMYSLNE["zapas_nsfw"] == [] and baza.USTAWIENIA_DOMYSLNE["yapper"]["max_kredyty_na_rolke"] == 400
