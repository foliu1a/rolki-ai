# -*- coding: utf-8 -*-
"""Podwojne placenie: job wysylany BEZ czekania, job_id zapisany od razu, po bledzie/timeoucie/STOP/restarcie odpytujemy
TEN SAM job (nigdy nie wysylamy drugiego), koszt z joba (nie z salda), blokada miedzy procesami, /api/zamknij czeka."""
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

import baza
import fabryka
import higgsfield_cli


@pytest.fixture(autouse=True)
def bez_ffmpeg(monkeypatch):
    monkeypatch.setattr(fabryka.klatki, "info", lambda p: {"czas": 6.0, "szer": 720, "wys": 1280, "fps": 30.0})
    monkeypatch.setattr(fabryka.klatki, "wytnij", lambda *a, **k: [])
    monkeypatch.setattr(fabryka.klatki, "arkusz", lambda *a, **k: None)
    monkeypatch.setattr(fabryka.time, "sleep", lambda s: None)


@pytest.fixture
def slug(modelka):
    baza.zapisz_ustawienia(modelka, mediatool=False)
    return modelka


def _wrzuc(slug, nazwa="a.mp4"):
    p = os.path.join(baza.folder_zrodel(slug), nazwa)
    open(p, "wb").write(b"mp4")
    return p


def _ok(jid, n=1):
    return {"id": jid, "status": "completed", "result_url": f"https://cdn.example/w{n}.mp4"}


def test_wysylanie_bez_czekania_i_job_id_od_razu(slug, cli, monkeypatch):
    """generate create idzie BEZ --wait; job_id jest w pomysle, zanim zaczniemy czekac; filmik wgrany osobno (id do odnalezienia)."""
    _wrzuc(slug)
    fabryka.skanuj(slug)
    stan_przy_pierwszym_odpytaniu = {}
    prawdziwy_job = cli.job

    def job(jid):
        stan_przy_pierwszym_odpytaniu.setdefault("p", baza.pomysl(slug, 1))
        return prawdziwy_job(jid)
    monkeypatch.setattr(higgsfield_cli, "job", job)
    czekania = []
    prawdziwe_generuj = cli.generuj

    def generuj(m, p=None, media=None, wait=True, **k):
        czekania.append(wait)
        return prawdziwe_generuj(m, p, media, wait=wait)
    monkeypatch.setattr(higgsfield_cli, "generuj", generuj)
    w = fabryka.generuj(slug)
    assert w["wygenerowane"] == 1 and czekania == [False]
    p0 = stan_przy_pierwszym_odpytaniu["p"]
    assert p0["status"] == "w_toku" and p0["job_id"] == "job1" and p0["w_toku"]["etap"] == "czeka"
    assert p0["w_toku"]["wideo_id"] == "uuid-a.mp4" and p0["w_toku"]["wysylam"] is True
    assert cli.generacje[0][2]["video"] == "uuid-a.mp4"              # filmik jako UUID wgrany przed create
    p = baza.pomysl(slug, 1)
    assert p["status"] == "gotowe" and p["w_toku"] is None and p["proby"][0]["job_id"] == "job1"


def test_timeout_czekania_to_wznowienie_nie_powtorka(slug, cli):
    """Job dalej sie robi, gdy skonczy sie czas czekania -> rolka zostaje w_toku z job_id; nastepny przebieg (albo restart)
    dokancza TEN SAM job. Jedno `generate create`, koszt policzony raz."""
    _wrzuc(slug)
    fabryka.skanuj(slug)
    cli.wyniki = [{"status": "in_progress"}]
    w = fabryka.generuj(slug, timeout="0s")
    assert w["w_toku"] == [1] and w["wygenerowane"] == 0 and not w["bledy"]
    p = baza.pomysl(slug, 1)
    assert p["status"] == "w_toku" and p["job_id"] == "job1" and baza.wydano_dzis() == 0
    # drugi przebieg w tym samym procesie: job dalej trwa -> dalej w toku, nic nowego nie poszlo
    fabryka.generuj(slug, timeout="0s")
    assert len(cli.generacje) == 1
    # "restart panelu": job w miedzyczasie sie skonczyl -> wznow pobiera wynik
    cli.serwer["job1"] = dict(_ok("job1"), job_type="seedance_2_5")
    w = fabryka.wznow_w_toku(slug)
    assert w["wygenerowane"] == 1 and len(cli.generacje) == 1
    p = baza.pomysl(slug, 1)
    assert p["status"] == "gotowe" and p["koszt"] == 45 and p["w_toku"] is None
    assert baza.wydano_dzis() == 45
    assert fabryka.generuj(slug)["wygenerowane"] == 0 and len(cli.generacje) == 1


def test_blad_sieci_przy_odpytywaniu_nie_wysyla_drugi_raz(slug, cli, monkeypatch):
    _wrzuc(slug)
    fabryka.skanuj(slug)
    cli.wyniki = [{"status": "in_progress"}]
    bledy = {"n": 0}

    def job(jid):
        bledy["n"] += 1
        if bledy["n"] <= 3:
            raise higgsfield_cli.HiggsfieldBlad("request failed (no response received)")
        return _ok(jid)
    monkeypatch.setattr(higgsfield_cli, "job", job)
    w = fabryka.generuj(slug)
    assert w["wygenerowane"] == 1 and len(cli.generacje) == 1 and bledy["n"] == 4
    assert baza.wydano_dzis() == 45


def test_stop_w_trakcie_czekania_zostawia_job_w_toku(slug, cli, monkeypatch):
    _wrzuc(slug)
    fabryka.skanuj(slug)
    cli.wyniki = [{"status": "in_progress"}]
    stop = threading.Event()
    prawdziwy_job = cli.job
    monkeypatch.setattr(higgsfield_cli, "job", lambda jid: (stop.set(), prawdziwy_job(jid))[1])
    with pytest.raises(fabryka.Przerwano):
        fabryka.generuj(slug, stop=stop)
    p = baza.pomysl(slug, 1)
    assert p["status"] == "w_toku" and p["job_id"] == "job1"
    cli.serwer["job1"] = _ok("job1")
    monkeypatch.setattr(higgsfield_cli, "job", prawdziwy_job)
    assert fabryka.generuj(slug)["wygenerowane"] == 1 and len(cli.generacje) == 1


def test_rolka_w_toku_nie_jest_kandydatem(slug, cli):
    _wrzuc(slug)
    fabryka.skanuj(slug)
    baza.zacznij_w_toku(slug, 1, dostawca="higgsfield", model="seedance_2_5", krok=0, klucz="k", koszt=45)
    baza.ustaw_w_toku(slug, 1, job_id="jobX", etap="czeka")
    assert fabryka.kandydaci(slug) == []
    with pytest.raises(ValueError, match="w_toku"):
        fabryka.kandydaci(slug, ids=[1])


def _znacznik_wysylania(slug, pid, sekund_temu, wideo_id="uuid-a.mp4", start_wczesniej_s=0):
    """Znacznik przerwanego wysylania: create poszedl `sekund_temu` s temu (wysylam_od), proba zaczela sie jeszcze
    `start_wczesniej_s` s wczesniej (od - upload trwal)."""
    teraz = datetime.now(timezone.utc)
    od = (teraz - timedelta(seconds=sekund_temu + start_wczesniej_s)).isoformat()
    wysylam_od = (teraz - timedelta(seconds=sekund_temu)).isoformat()
    baza.zacznij_w_toku(slug, pid, dostawca="higgsfield", model="seedance_2_5", krok=0, klucz="k", koszt=45, od=od)
    baza.ustaw_w_toku(slug, pid, wysylam=True, wideo_id=wideo_id, wysylam_od=wysylam_od)


def test_restart_w_trakcie_wysylania_job_powstal(slug, cli):
    """Panel zamkniety w trakcie `generate create` (job_id nie zdazyl sie zapisac), a CLI i tak utworzylo job (Noemi #2, 92 kr):
    po restarcie job jest odnajdywany na `generate list` po wgranym filmiku - drugi nie idzie."""
    _wrzuc(slug)
    fabryka.skanuj(slug)
    _znacznik_wysylania(slug, 1, sekund_temu=40)
    cli.serwer["sierota"] = {"id": "sierota", "status": "completed", "job_type": "seedance_2_5",
                             "created_at": datetime.now(timezone.utc).isoformat(), "result_url": "https://cdn/s.mp4",
                             "params": {"medias": [{"role": "video", "data": {"id": "uuid-a.mp4"}}]}}
    cli.serwer["cudzy"] = {"id": "cudzy", "status": "completed", "job_type": "seedance_2_5",
                           "created_at": datetime.now(timezone.utc).isoformat(), "result_url": "https://cdn/c.mp4",
                           "params": {"medias": [{"role": "video", "data": {"id": "uuid-inny.mp4"}}]}}
    w = fabryka.generuj(slug)
    assert w["wygenerowane"] == 1 and cli.generacje == []
    p = baza.pomysl(slug, 1)
    assert p["job_id"] == "sierota" and p["wynik_url"] == "https://cdn/s.mp4" and baza.wydano_dzis() == 45


def test_restart_w_trakcie_wysylania_job_nie_powstal(slug, cli):
    """Znacznik 'wysylam' bez joba na liscie (Higgsfield nie ma klucza idempotencji): czekamy OKNO_NIEPEWNEGO_WYSLANIA_S
    (lista bywa opozniona, Seedance bywa wolny), a potem rolka 'nie wyszla' z prosba o sprawdzenie w apce - NIGDY nie
    wysylamy drugi raz sami. Okno liczy sie od wyslania (wysylam_od), nie od startu proby (upload potrafi trwac minuty)."""
    _wrzuc(slug)
    fabryka.skanuj(slug)
    _znacznik_wysylania(slug, 1, sekund_temu=30, start_wczesniej_s=600)        # upload 10 min, create 30 s temu
    w = fabryka.generuj(slug)
    assert w["w_toku"] == [1] and cli.generacje == [] and baza.pomysl(slug, 1)["status"] == "w_toku"
    _znacznik_wysylania(slug, 1, sekund_temu=fabryka.OKNO_NIEPEWNEGO_WYSLANIA_S - 120)
    w = fabryka.generuj(slug)
    assert w["w_toku"] == [1] and cli.generacje == []
    _znacznik_wysylania(slug, 1, sekund_temu=fabryka.OKNO_NIEPEWNEGO_WYSLANIA_S + 60)
    w = fabryka.generuj(slug)
    p = baza.pomysl(slug, 1)
    assert cli.generacje == [] and w["bledy"] == [1] and not w["odrzucone"]
    assert p["status"] == "blad" and "Sprawdz w apce Higgsfield" in p["notatki"] and p["w_toku"] is None
    assert baza.wydano_dzis() == 45                      # wycena wliczona do limitu na wszelki wypadek
    assert p["proby"][-1]["status"] == "niepewne"
    # dopiero user decyduje: 'Sprobuj jeszcze raz' -> normalne, nowe wyslanie
    baza.aktualizuj_pomysl(slug, 1, status="nowy")
    assert fabryka.generuj(slug)["wygenerowane"] == 1 and len(cli.generacje) == 1


def test_restart_przed_wyslaniem_wraca_do_kolejki(slug, cli):
    """Znacznik bez 'wysylam' = create nie zostal wolany -> od razu do kolejki (bez czekania)."""
    _wrzuc(slug)
    fabryka.skanuj(slug)
    baza.zacznij_w_toku(slug, 1, dostawca="higgsfield", model="seedance_2_5", krok=0, klucz="k", koszt=45)
    assert fabryka.generuj(slug)["wygenerowane"] == 1 and len(cli.generacje) == 1


def test_niedostepna_lista_jobow_nie_wysyla(slug, cli, monkeypatch):
    """Wyslanie padlo i nie da sie sprawdzic `generate list` - NIE wysylamy drugi raz (moze job jednak powstal)."""
    _wrzuc(slug)
    fabryka.skanuj(slug)
    cli.wyniki = [higgsfield_cli.HiggsfieldBlad("request failed (no response received)")]
    monkeypatch.setattr(higgsfield_cli, "joby", lambda *a, **k: (_ for _ in ()).throw(higgsfield_cli.HiggsfieldBlad("offline")))
    w = fabryka.generuj(slug)
    assert len(cli.generacje) == 1 and w["w_toku"] == [1]
    assert baza.pomysl(slug, 1)["status"] == "w_toku"


def test_koszt_z_joba_nie_z_salda(slug, cli, monkeypatch):
    """Saldo spada o wiecej niz job (user generuje recznie w apce) - limit dzienny fabryki liczy tylko job (wycena)."""
    _wrzuc(slug)
    fabryka.skanuj(slug)
    prawdziwe = cli.generuj

    def generuj(*a, **k):
        cli.saldo -= 500        # reczna generacja w apce w tym samym czasie
        return prawdziwe(*a, **k)
    monkeypatch.setattr(higgsfield_cli, "generuj", generuj)
    fabryka.generuj(slug)
    assert baza.wydano_dzis() == 45 and baza.pomysl(slug, 1)["koszt"] == 45


def test_rozliczenie_raz_na_job(dane):
    assert baza.dopisz_wydatek(45, "higgsfield", job_id="j1") == 45
    assert baza.dopisz_wydatek(45, "higgsfield", job_id="j1") == 45      # ten sam job drugi raz (wznowienie) - bez zmian
    assert baza.dopisz_wydatek(300, "yapper", job_id="j1") == 300        # inny dostawca, osobna lista
    assert baza.dopisz_wydatek(10, "higgsfield") == 55                    # bez job_id jak dawniej
    assert baza.wydano_dzis("higgsfield") == 55


def test_wznowienie_po_rozliczeniu_nie_liczy_drugi_raz(slug, cli, monkeypatch):
    """Awaria miedzy rozliczeniem a pobraniem (pobranie padlo) -> rolka zostaje w toku; wznowienie pobiera, koszt 1 raz."""
    _wrzuc(slug)
    fabryka.skanuj(slug)
    proby = {"n": 0}
    prawdziwe = cli.pobierz

    def pobierz(url, sciezka):
        proby["n"] += 1
        if proby["n"] == 1:
            raise OSError("siec padla")
        return prawdziwe(url, sciezka)
    monkeypatch.setattr(higgsfield_cli, "pobierz", pobierz)
    w = fabryka.generuj(slug)
    assert w["w_toku"] == [1] and baza.pomysl(slug, 1)["status"] == "w_toku" and baza.wydano_dzis() == 45
    w = fabryka.generuj(slug)
    assert w["wygenerowane"] == 1 and baza.wydano_dzis() == 45 and len(cli.generacje) == 1
    assert len(baza.pomysl(slug, 1)["proby"]) == 1


def test_blokada_w_tym_samym_procesie(slug, cli):
    _wrzuc(slug)
    fabryka.skanuj(slug)
    trzymam, puszczam = threading.Event(), threading.Event()

    def inny_watek():
        with baza.blokada_generacji(slug) as moge:
            assert moge
            trzymam.set()
            puszczam.wait(5)
    t = threading.Thread(target=inny_watek)
    t.start()
    assert trzymam.wait(5)
    try:
        w = fabryka.generuj(slug)
        assert w["stop"] == "zajete" and cli.generacje == []
        assert fabryka.wznow_w_toku(slug)["wygenerowane"] == 0
    finally:
        puszczam.set()
        t.join(5)
    assert fabryka.generuj(slug)["wygenerowane"] == 1


def test_blokada_miedzy_procesami(slug, cli, dane):
    """Drugi proces (np. `python fabryka.py generuj` obok panelu) trzyma blokade -> ten nie wysyla nic."""
    _wrzuc(slug)
    fabryka.skanuj(slug)
    korzen = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    kod = ("import sys, time, os; sys.path.insert(0, r'%s'); os.environ['ROLKI_MODELKI'] = r'%s'; import baza\n"
           "with baza.blokada_generacji('%s') as moge:\n    print('TRZYMAM' if moge else 'NIE', flush=True); time.sleep(20)\n"
           % (korzen, baza.KATALOG_MODELEK, slug))
    proc = subprocess.Popen([sys.executable, "-c", kod], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "TRZYMAM"
        with baza.blokada_generacji(slug) as moge:
            assert moge is False
        assert fabryka.generuj(slug)["stop"] == "zajete" and cli.generacje == []
    finally:
        proc.kill()
        proc.wait(10)
    with baza.blokada_generacji(slug) as moge:       # proces padl -> blokada zniknela sama
        assert moge is True


# ---------------- panel ----------------

@pytest.fixture
def panel(slug, cli):
    import app as panel
    panel.konsola.__init__()
    panel.app.config["TESTING"] = True
    return panel


def test_api_zamknij_czeka_na_wysylanie_i_zadanie(panel, monkeypatch):
    wyjscie = threading.Event()
    monkeypatch.setattr(panel.os, "_exit", lambda kod: wyjscie.set())
    assert panel.konsola.lock.acquire(blocking=False)
    panel.konsola.stan.update({"trwa": True, "typ": "generuj"})
    with fabryka._WYSYLANIE_LOCK:
        fabryka._WYSYLANIE.add(("noemi", 1))
    try:
        with panel.app.test_client() as c:
            d = c.post("/api/zamknij").get_json()
        assert d["ok"] and d["zamykam"] and d["czekam"] and "bez drugiej oplaty" in d["komunikat"]
        assert panel.konsola.stop.is_set()
        assert not wyjscie.wait(1.5)                                   # wysylanie trwa - proces zyje
        panel.konsola.stan.update({"trwa": False})
        assert not wyjscie.wait(1.0)                                   # zadanie skonczone, ale wysylanie dalej trwa
        with fabryka._WYSYLANIE_LOCK:
            fabryka._WYSYLANIE.discard(("noemi", 1))
        assert wyjscie.wait(5)                                         # dopiero teraz koniec
    finally:
        with fabryka._WYSYLANIE_LOCK:
            fabryka._WYSYLANIE.discard(("noemi", 1))
        panel.konsola.lock.release()


def test_api_ponow_i_usun_rolki_w_toku_odmawia(panel, slug):
    _wrzuc(slug)
    fabryka.skanuj(slug)
    baza.zacznij_w_toku(slug, 1, dostawca="higgsfield", model="seedance_2_5", krok=0, klucz="k", koszt=45)
    baza.ustaw_w_toku(slug, 1, job_id="jobX", etap="czeka")
    with panel.app.test_client() as c:
        r = c.post("/api/pomysly/1/ponow")
        assert r.status_code == 409 and "generuje" in r.get_json()["blad"]
        assert c.delete("/api/pomysly/1").status_code == 409
        assert c.patch("/api/pomysly/1", json={"status": "nowy"}).status_code == 409
        p = c.get("/api/pomysly").get_json()["pomysly"][0]
        assert p["status"] == "w_toku" and p["w_toku_opis"] == "higgsfield seedance_2_5, job jobX"
        assert c.get("/api/stan").get_json()["stan"]["w_toku"] == [1]


def test_wznow_przy_starcie_panelu(panel, slug, cli):
    _wrzuc(slug)
    fabryka.skanuj(slug)
    cli.wyniki = [{"status": "in_progress"}]
    fabryka.generuj(slug, timeout="0s")
    assert baza.pomysl(slug, 1)["status"] == "w_toku"
    cli.serwer["job1"] = _ok("job1")
    assert panel.wznow_przy_starcie()["typ"] == "wznow"
    panel.konsola.watek.join(10)
    assert baza.pomysl(slug, 1)["status"] == "gotowe" and len(cli.generacje) == 1
    assert panel.wznow_przy_starcie() is None                          # nic w toku -> nic nie startuje


def test_autopilot_dokancza_w_toku_takze_w_pauzie(slug, cli):
    import autopilot
    _wrzuc(slug)
    fabryka.skanuj(slug)
    cli.wyniki = [{"status": "in_progress"}]
    fabryka.generuj(slug, timeout="0s")
    baza.autopilot_pauza(slug, "test")
    cli.serwer["job1"] = _ok("job1")
    w = autopilot.przebieg(slug)
    assert w["wygenerowane"] == 1 and w["stop"].startswith("pauza") and baza.pomysl(slug, 1)["status"] == "gotowe"
    assert len(cli.generacje) == 1


def test_cli_wznow(slug, cli, capsys):
    _wrzuc(slug)
    fabryka.skanuj(slug)
    cli.wyniki = [{"status": "in_progress"}]
    fabryka.generuj(slug, timeout="0s")
    cli.serwer["job1"] = _ok("job1")
    assert fabryka.main(["wznow"]) == 0
    assert "gotowe 1" in capsys.readouterr().out and baza.pomysl(slug, 1)["status"] == "gotowe"
