# -*- coding: utf-8 -*-
"""Zdjecia 3.3 - kilka naraz (udawane CLI Higgsfield, zero kredytow i zero sieci): kazde klikniecie "Generuj" = osobne zlecenia od
razu (obok rolek), seria wysylana rownolegle, limit zdjec w toku + kolejka, atomowa rezerwacja limitu dnia i salda, odmowa "za duzo
naraz" -> z powrotem do kolejki tylko gdy job na pewno nie powstal, przy watpliwosci nigdy drugi raz, STOP strony Zdjecia,
dokonczenie po restarcie, jeden wlasciciel zdjecia (takze miedzy procesami), ustawienie "ile naraz"."""
import io
import os
import threading
import time

import pytest
from PIL import Image

import app as panel
import baza
import fabryka
import higgsfield_cli
import zdjecia_swap as zs


@pytest.fixture(autouse=True)
def czysty_cache():
    zs.wyczysc_cache()
    yield
    zs.wyczysc_cache()


@pytest.fixture
def src(modelka, tmp_path):
    plik = tmp_path / "IMG_1.jpg"
    Image.new("RGB", (1080, 1350), (90, 60, 40)).save(plik)
    return zs.zapisz_zrodlo(modelka, str(plik))


@pytest.fixture
def klient(modelka, cli):
    panel._saldo.clear()
    panel.konsola.__init__()
    panel.app.config["TESTING"] = True
    with panel.app.test_client() as c:
        yield c


def _chwila(s):
    threading.Event().wait(s)          # time.sleep jest w testach wylaczone (conftest)


def _az(warunek, limit_s=5):
    koniec = time.monotonic() + limit_s
    while time.monotonic() < koniec:
        if warunek():
            return True
        _chwila(0.01)
    raise AssertionError("warunek nie spelnil sie w czasie")


def czekaj_na_zdjecia(limit_s=10):
    """Dyspozytor zdjec panelu skonczyl: nic w toku, nic w kolejce, zaden watek zdjecia nie pracuje."""
    def koniec():
        s, o = zs.stan_kolejki(), zs.KOLEJKA.obsluga
        return not s["w_toku"] and not s["w_kolejce"] and not (o and o.aktywne())
    _az(koniec, limit_s)


def _wstaw(klient):
    buf = io.BytesIO()
    Image.new("RGB", (1080, 1920), (10, 20, 30)).save(buf, "JPEG")
    buf.seek(0)
    return klient.post("/api/swap/zdjecie", data={"plik": (buf, "foto.jpg")}, content_type="multipart/form-data").get_json()["zrodlo"]


def _bariera_na_create(monkeypatch, cli, ile):
    """Udawany Higgsfield przyjmuje create dopiero, gdy przyjdzie `ile` naraz - po kolei bariera peka (BrokenBarrierError)."""
    bariera = threading.Barrier(ile, timeout=5)
    prawdziwe = cli.generuj

    def generuj(model, params=None, media=None, wait=True, **k):
        bariera.wait()
        return prawdziwe(model, params, media, wait=wait)
    monkeypatch.setattr(higgsfield_cli, "generuj", generuj)


# ---------------- rownolegle i kolejka ----------------

def test_seria_wysylana_od_razu_rownolegle(modelka, src, cli, monkeypatch):
    """ile 3: wszystkie 3 zlecenia ida naraz (Higgsfield liczy je rownolegle), nie po kolei."""
    _bariera_na_create(monkeypatch, cli, 3)
    w = zs.generuj(modelka, src, {"ile": 3}, kr=45)
    assert w["zrobione"] == 3 and len(cli.generacje) == 3 and sorted(w["ids"]) == [1, 2, 3] and w["stop"] is None
    assert all(z["status"] == "gotowe" and z["w_toku"] is None for z in baza.lista_zdjec(modelka))
    assert baza.wydano_dzis("higgsfield") == 135 and baza.koszt_w_toku("higgsfield") == 0


def test_seria_rownolegle_kazde_zdjecie_ma_swoj_wynik(modelka, src, cli):
    """Wszystkie poszly naraz, filtr odrzucil jedno - pozostale sa gotowe, odrzucone nie idzie drugi raz (0 kr)."""
    cli.wyniki = [{"status": "nsfw"}]
    w = zs.generuj(modelka, src, {"ile": 3}, kr=45)
    assert len(cli.generacje) == 3 and len(w["odrzucone"]) == 1 and w["zrobione"] == 2
    assert baza.wydano_dzis("higgsfield") == 90 and baza.zdjecie(modelka, w["odrzucone"][0])["powod"] == "nsfw"


def test_kilka_klikniec_od_razu_kilka_zlecen_obok_rolek(klient, modelka, cli, monkeypatch):
    """Dwa szybkie klikniecia "Generuj", a konsola zajeta rolkami: oba przyjete od razu (karty sa od razu), oba create rownolegle."""
    zrodlo = _wstaw(klient)
    _bariera_na_create(monkeypatch, cli, 2)
    panel.konsola._start("generuj", modelka)
    try:
        r1 = klient.post("/api/swap", json={"zrodlo": zrodlo, "kr": 45})
        r2 = klient.post("/api/swap", json={"zrodlo": zrodlo, "kr": 45})
        assert r1.status_code == 200 and r2.status_code == 200
        ids = r1.get_json()["ids"] + r2.get_json()["ids"]
        karty = {z["id"]: z for z in klient.get("/api/zdjecia").get_json()["zdjecia"]}
        assert set(ids) <= set(karty) and all(karty[i]["status"] in ("w_kolejce", "w_toku", "gotowe") for i in ids)
        czekaj_na_zdjecia()
    finally:
        panel.konsola._koniec()
    assert len(cli.generacje) == 2 and all(baza.zdjecie(modelka, i)["status"] == "gotowe" for i in ids)


def test_limit_naraz_nadmiar_czeka_w_kolejce(modelka, src, cli, monkeypatch):
    """Ile naraz = 2, seria 4: dwa w toku, dwa czekaja w kolejce (rezerwacja liczy wszystkie 4); po skonczeniu - reszta."""
    baza.zapisz_ustawienia_globalne(zdjecia_rownolegle=2)
    puszczaj = threading.Event()
    prawdziwy_job = cli.job

    def job(jid):                      # `generate get`: joby "sie robia", az test puszcza
        puszczaj.wait(5)
        return prawdziwy_job(jid)
    monkeypatch.setattr(higgsfield_cli, "job", job)
    wynik = {}
    t = threading.Thread(target=lambda: wynik.update(zs.generuj(modelka, src, {"ile": 4}, kr=45)))
    t.start()
    try:
        _az(lambda: len(cli.generacje) >= 2)
        _chwila(0.3)                   # gdyby kolejne mialy pojsc ponad limit, poszlyby teraz
        statusy = sorted(z["status"] for z in baza.lista_zdjec(modelka))
        assert len(cli.generacje) == 2 and statusy == ["w_kolejce", "w_kolejce", "w_toku", "w_toku"]
        assert zs.stan_kolejki(modelka)["persona"] == {"w_toku": 2, "w_kolejce": 2}
        assert baza.koszt_w_toku("higgsfield") == 180              # 2 w toku + 2 w kolejce zarezerwowane
    finally:
        puszczaj.set()
        t.join(10)
    assert wynik["zrobione"] == 4 and len(cli.generacje) == 4 and baza.wydano_dzis("higgsfield") == 180


def test_cena_wzrosla_miedzy_kliknieciem_a_wyslaniem_nic_nie_idzie(modelka, src, cli):
    ids = zs.zlec(modelka, src, {"ile": 1}, kr=45, saldo=10000, obudz=False)
    assert baza.zdjecie(modelka, ids[0])["status"] == "w_kolejce" and cli.generacje == []
    cli.cena = 60
    zs._Obsluga(tylko={(modelka, ids[0])}).do_konca()
    z = baza.zdjecie(modelka, ids[0])
    assert z["status"] == "blad" and "cena wzrosla z 45 kr do 60 kr" in z["notatki"] and z["koszt"] == 0
    assert cli.generacje == [] and cli.uploady == [] and baza.koszt_w_toku("higgsfield") == 0


# ---------------- pieniadze: atomowa rezerwacja ----------------

def _klikaj_naraz(modelka, src, n, monkeypatch, **zlec):
    """n klikniec naraz (watki), kazde 1 zdjecie. Wolniejsze liczenie rezerwy poszerza okno wyscigu - bez blokady kilka watkow
    policzyloby te sama rezerwe i przepuscilo wiecej."""
    prawdziwy = baza.koszt_w_toku

    def wolno(d="higgsfield"):
        w = prawdziwy(d)
        _chwila(0.02)
        return w
    monkeypatch.setattr(baza, "koszt_w_toku", wolno)
    przyjete, odmowy = [], []

    def klik():
        try:
            przyjete.append(zs.zlec(modelka, src, {"ile": 1}, obudz=False, **zlec))
        except zs.Odmowa as e:
            odmowy.append(e.kod)
    watki = [threading.Thread(target=klik) for _ in range(n)]
    for t in watki:
        t.start()
    for t in watki:
        t.join(20)
    return przyjete, odmowy


def test_rezerwacja_atomowa_szybkie_klikniecia_nie_przebija_limitu_dnia(modelka, src, cli, monkeypatch):
    cli.cena = 2.5                                         # 3 kr do limitu (w gore)
    baza.dopisz_wydatek(285, "higgsfield", job_id="rano")  # w limicie 300 zostalo 15 kr = 5 zdjec
    przyjete, odmowy = _klikaj_naraz(modelka, src, 10, monkeypatch, kr=2.5, saldo=10000)
    assert len(przyjete) == 5 and odmowy == ["limit dzienny"] * 5
    assert len(baza.zdjecia_w_kolejce(modelka)) == 5 and baza.wydano_z_rezerwa("higgsfield") == 300 and cli.generacje == []


def test_rezerwacja_atomowa_szybkie_klikniecia_nie_przebija_min_kredyty(modelka, src, cli, monkeypatch):
    baza.zapisz_limit_dzienny(0)                           # bez limitu dnia - pilnuje saldo (min_kredyty 200)
    cli.cena = 2.5
    przyjete, odmowy = _klikaj_naraz(modelka, src, 10, monkeypatch, kr=2.5, saldo=220)    # 20 kr ponad minimum = 6 zdjec po 3
    assert len(przyjete) == 6 and odmowy == ["min_kredyty"] * 4 and cli.generacje == []


def test_kolejka_zdjec_liczy_sie_w_limicie_rolek(modelka, src, cli):
    zs.zlec(modelka, src, {"ile": 4}, kr=45, saldo=10000, obudz=False)          # 180 kr zarezerwowane, nic nie wyslane
    assert baza.wydano_z_rezerwa("higgsfield") == 180 and cli.generacje == []
    cli.cena = 130                                         # rolka z promptu za 130 kr: 180 + 130 > 300
    w = fabryka.wycena_z_promptu(modelka, {"pomysl_id": "galeria_fastfood", "dlugosc": 10, "model": "seedance_2_5"})
    assert not w["mozna"] and any("limit" in p for p in w["powody"]) and w["dzis"]["wydano"] == 180
    assert zs.wycena(modelka, {"ile": 1}, saldo=10000)["dzis"]["wydano"] == 180     # wycena zdjec widzi kolejke


# ---------------- odmowa "za duzo naraz" ----------------

@pytest.mark.parametrize("tekst,odmowa", [
    ("Higgsfield API error (HTTP 429).", True),
    ("Error: Too many concurrent generations. Please wait for your current jobs to finish.", True),
    ("rate limit exceeded, try again later", True),
    ("Maximum number of jobs in progress reached", True),
    ("You have reached the limit of 4 parallel generations", True),
    ("wgranie IMG_1.jpg nie wyszlo: Higgsfield API error (HTTP 429).", True),
    ("content flagged by moderation (nsfw)", False),
    ("too many requests: nsfw content detected", False),           # filtr, nie limit
    ("socket hang up", False),                                     # siec = nie wiadomo, czy dotarlo
    ("CLI nie odpowiedzialo w 900s: generate create seedream_v5_pro", False),
    ("Higgsfield API error (HTTP 429). context deadline exceeded", False),
    ("Insufficient credits: not enough credits", False),
    ("Higgsfield API error (HTTP 500).", False),
    ("", False),
])
def test_rozpoznaje_odmowe_za_duzo_naraz(tekst, odmowa):
    assert zs.za_duzo_naraz(tekst) is odmowa


def test_odmowa_za_duzo_naraz_wraca_do_kolejki_i_idzie_jeszcze_raz(modelka, src, cli, monkeypatch):
    """create odrzucony przez Higgsfield (HTTP 429) i joba na pewno nie ma na liscie -> zdjecie wraca do kolejki zamiast przepadac;
    druga proba przechodzi: 2 wyslania, 1 job, zaplacone raz."""
    monkeypatch.setattr(zs, "PONOW_PO_S", 0)
    cli.wyniki = [higgsfield_cli.HiggsfieldBlad("Higgsfield API error (HTTP 429).")]
    w = zs.generuj(modelka, src, {}, kr=45)
    z = baza.zdjecie(modelka, w["ids"][0])
    assert w["zrobione"] == 1 and len(cli.generacje) == 2 and len(cli.serwer) == 1
    assert z["status"] == "gotowe" and z["kolejka"]["ponowienia"] == 1 and baza.wydano_dzis("higgsfield") == 45
    assert any("wraca do kolejki" in x["tekst"] for x in baza.dziennik_ostatnie(50))


def test_odmowa_przy_wgrywaniu_wraca_do_kolejki(modelka, src, cli, monkeypatch):
    """Odmowa juz przy wgrywaniu zdjecia (przed 'wysylam') = create nawet nie ruszyl -> kolejka, potem normalnie."""
    monkeypatch.setattr(zs, "PONOW_PO_S", 0)
    prawdziwy = cli.upload
    licznik = {"n": 0}

    def upload(plik):
        licznik["n"] += 1
        if licznik["n"] == 1:
            raise higgsfield_cli.HiggsfieldBlad("Higgsfield API error (HTTP 429).")
        return prawdziwy(plik)
    monkeypatch.setattr(higgsfield_cli, "upload", upload)
    w = zs.generuj(modelka, src, {}, kr=45)
    assert w["zrobione"] == 1 and len(cli.generacje) == 1


def test_odmowa_ale_job_jednak_jest_bez_drugiego_wysylania(modelka, src, cli, monkeypatch):
    """Odmowa z create, a job z naszym zdjeciem jest na liscie (dziwna odpowiedz serwera) - bierzemy TEN job, nic nie wysylamy."""
    prawdziwe = cli.generuj

    def generuj(model, params=None, media=None, wait=True, **k):
        prawdziwe(model, params, media, wait=wait)                         # job POWSTAL...
        raise higgsfield_cli.HiggsfieldBlad("Higgsfield API error (HTTP 429).")   # ...a CLI zglosilo odmowe
    monkeypatch.setattr(higgsfield_cli, "generuj", generuj)
    w = zs.generuj(modelka, src, {}, kr=45)
    assert w["zrobione"] == 1 and len(cli.generacje) == 1 and baza.zdjecie(modelka, w["ids"][0])["job_id"] == "job1"


def test_odmowa_za_duzo_naraz_bez_listy_jobow_nigdy_drugi_raz(modelka, src, cli, monkeypatch):
    """Odmowa, ale listy jobow nie widac - nie wiadomo na pewno, czy job nie powstal: zdjecie czeka w toku (wznowienie szuka),
    NIGDY drugie wysylanie."""
    cli.wyniki = [higgsfield_cli.HiggsfieldBlad("Higgsfield API error (HTTP 429).")]

    def lista_padla(*a, **k):
        raise higgsfield_cli.HiggsfieldBlad("generate list: brak odpowiedzi")
    monkeypatch.setattr(higgsfield_cli, "joby", lista_padla)
    w = zs.generuj(modelka, src, {}, kr=45)
    zid = w["ids"][0]
    z = baza.zdjecie(modelka, zid)
    assert len(cli.generacje) == 1 and w["w_toku"] == [zid] and w["stop"] == "niepewne wysylanie"
    assert z["status"] == "w_toku" and z["w_toku"]["wysylam"] is True and baza.koszt_w_toku("higgsfield") == 45
    zs.wznow_w_toku(modelka)                               # nastepne sprawdzenie: dalej tylko szuka
    assert len(cli.generacje) == 1 and baza.zdjecie(modelka, zid)["status"] == "w_toku"


def test_odmowa_bez_konca_konczy_sie_bledem_bez_kosztu(modelka, src, cli, monkeypatch):
    monkeypatch.setattr(zs, "PONOW_PO_S", 0)
    monkeypatch.setattr(zs, "MAX_PONOWIEN", 2)
    cli.wyniki = [higgsfield_cli.HiggsfieldBlad("Higgsfield API error (HTTP 429).")] * 3
    w = zs.generuj(modelka, src, {}, kr=45)
    z = baza.zdjecie(modelka, w["ids"][0])
    assert len(cli.generacje) == 3 and z["status"] == "blad" and "odmowil" in z["notatki"] and z["koszt"] == 0
    assert baza.wydano_dzis("higgsfield") == 0 and baza.koszt_w_toku("higgsfield") == 0


# ---------------- STOP, restart, jeden wlasciciel ----------------

def test_stop_anuluje_kolejke_a_przyjety_job_dokancza_sie_pozniej(klient, modelka, cli, monkeypatch):
    baza.zapisz_ustawienia_globalne(zdjecia_rownolegle=1)
    zrodlo = _wstaw(klient)
    monkeypatch.setattr(fabryka, "_spij", lambda s, stop: threading.Event().wait(0.01))
    robi_sie = {"tak": True}
    prawdziwy_job = cli.job

    def job(jid):
        w = prawdziwy_job(jid)
        return dict(w, status="in_progress") if robi_sie["tak"] else w
    monkeypatch.setattr(higgsfield_cli, "job", job)
    ids = klient.post("/api/swap", json={"zrodlo": zrodlo, "ile": 3, "kr": 45}).get_json()["ids"]
    _az(lambda: (baza.zdjecie(modelka, ids[0]).get("w_toku") or {}).get("job_id"))     # pierwsze przyjete przez Higgsfield
    d = klient.post("/api/swap/stop").get_json()
    assert d["ok"] and d["anulowane"] == 2 and d["w_toku"] == 1
    _az(lambda: not zs.KOLEJKA.obsluga.aktywne())
    st = {i: baza.zdjecie(modelka, i)["status"] for i in ids}
    assert st == {ids[0]: "w_toku", ids[1]: "anulowane", ids[2]: "anulowane"} and len(cli.generacje) == 1
    assert baza.zdjecie(modelka, ids[1])["notatki"] == zs.NOTATKA_STOP and baza.koszt_w_toku("higgsfield") == 45
    # po STOP przyjety job czeka na nastepne sprawdzenie - sam sie nie dokancza...
    robi_sie["tak"] = False
    _chwila(0.3)
    assert baza.zdjecie(modelka, ids[0])["status"] == "w_toku"
    assert klient.get("/api/stan").get_json()["zdjecia_kolejka"]["zatrzymane"] is True
    # ...nastepne "Generuj" = nastepne sprawdzenie: ten sam job sie dokancza (bez drugiego wysylania), nowe zdjecie idzie
    nowe = klient.post("/api/swap", json={"zrodlo": zrodlo, "kr": 45}).get_json()["ids"]
    czekaj_na_zdjecia()
    assert baza.zdjecie(modelka, ids[0])["status"] == "gotowe" and baza.zdjecie(modelka, nowe[0])["status"] == "gotowe"
    assert len(cli.generacje) == 2 and baza.wydano_dzis("higgsfield") == 90


def test_restart_panelu_dokancza_w_toku_i_wysyla_kolejke(klient, modelka, src, cli):
    """Przed restartem: 1 zdjecie w toku (job wyslany), 2 czekaly w kolejce (nic nie poszlo). Po starcie panelu: tamten job
    dokonczony bez create, kolejka wyslana."""
    ids = zs.zlec(modelka, src, {"ile": 3}, kr=45, saldo=10000, obudz=False)
    assert baza.przejmij_zdjecie(modelka, ids[0])
    baza.ustaw_zdjecie_w_toku(modelka, ids[0], job_id="stary", etap="czeka", wysylam=True)
    cli.serwer["stary"] = {"id": "stary", "job_type": "seedream_v5_pro", "status": "completed",
                           "result": {"url": "https://cdn.example/stary.png"}}
    panel.start_kolejki_zdjec()
    czekaj_na_zdjecia()
    assert all(baza.zdjecie(modelka, i)["status"] == "gotowe" for i in ids)
    assert len(cli.generacje) == 2 and baza.zdjecie(modelka, ids[0])["job_id"] == "stary"
    assert any("start panelu: zdjecia w toku 1, w kolejce 2" in w["tekst"] for w in baza.dziennik_ostatnie(50))


def test_przerwane_przed_wysylam_wraca_do_kolejki_po_restarcie(klient, modelka, src, cli):
    """Panel zamkniety, gdy zdjecie z kolejki bylo przejete, ale przed 'wysylam' (nic nie poszlo) - po starcie wraca do kolejki i
    idzie raz (a nie przepada jako blad)."""
    ids = zs.zlec(modelka, src, {"ile": 1}, kr=45, saldo=10000, obudz=False)
    assert baza.przejmij_zdjecie(modelka, ids[0]) and not baza.zdjecie(modelka, ids[0])["w_toku"].get("wysylam")
    panel.start_kolejki_zdjec()
    czekaj_na_zdjecia()
    assert baza.zdjecie(modelka, ids[0])["status"] == "gotowe" and len(cli.generacje) == 1
    assert any("wraca do kolejki (nic nie zeszlo)" in w["tekst"] for w in baza.dziennik_ostatnie(30))


def test_zamykanie_panelu_przejete_niewyslane_wraca_do_kolejki(modelka, src, cli):
    """/api/zamknij (aktualizacja) -> KOLEJKA.wstrzymaj(): zdjecie przejete, a jeszcze nie wyslane nie zaczyna wysylania (panel nie
    zginie w polowie) - wraca do kolejki, pojdzie po starcie. Nic nie wgrane, nic nie wyslane."""
    ids = zs.zlec(modelka, src, {"ile": 1}, kr=45, saldo=10000, obudz=False)
    o = zs._Obsluga(tylko={(modelka, ids[0])})
    zs.KOLEJKA.zamykanie = True
    try:
        assert o.krok() == 1
        _az(lambda: not o.aktywne())
    finally:
        zs.KOLEJKA.zamykanie = False
    z = baza.zdjecie(modelka, ids[0])
    assert z["status"] == "w_kolejce" and z["w_toku"] is None and cli.generacje == [] and cli.uploady == []
    assert not fabryka.trwa_wysylanie()


def test_dwoch_obslugujacych_kazde_zdjecie_wysylane_raz(modelka, src, cli):
    """Dwie obslugi tej samej kolejki naraz (jak panel i drugi proces) - przejecie jest atomowe: kazde zdjecie idzie raz."""
    ids = zs.zlec(modelka, src, {"ile": 4}, kr=45, saldo=10000, obudz=False)
    a, b = zs._Obsluga(), zs._Obsluga()
    watki = [threading.Thread(target=lambda o=o: [o.krok() for _ in range(30)]) for o in (a, b)]
    for t in watki:
        t.start()
    for t in watki:
        t.join(10)
    _az(lambda: not a.aktywne() and not b.aktywne() and all(baza.zdjecie(modelka, i)["status"] == "gotowe" for i in ids))
    assert len(cli.generacje) == 4


def test_blokada_zdjecia_jeden_wlasciciel_takze_miedzy_procesami(modelka):
    zid = baza.dodaj_zdjecie(modelka, "p", status="w_kolejce", typ="swap")
    pierwsza, druga = baza.BlokadaZdjecia(modelka, zid), baza.BlokadaZdjecia(modelka, zid)
    assert pierwsza.zablokuj() and not druga.zablokuj()           # ten proces: rejestr
    with baza.BlokadaZdjecia._lock:
        baza.BlokadaZdjecia._trzymane.clear()                       # udajemy drugi proces: zostaje tylko blokada pliku
    assert not druga.zablokuj()
    pierwsza.odblokuj()
    assert druga.zablokuj()
    druga.odblokuj(usun=True)
    assert not os.path.exists(os.path.join(baza.folder_modelki(modelka), "blokady", f"zdjecie_{zid}.lock"))


def test_usun_z_kolejki_a_w_toku_409(klient, modelka, src, cli):
    ids = zs.zlec(modelka, src, {"ile": 2}, kr=45, saldo=10000, obudz=False)
    assert klient.delete(f"/api/zdjecia/{ids[0]}").status_code == 200
    assert not baza.przejmij_zdjecie(modelka, ids[0])               # usuniete - dyspozytor go juz nie wezmie
    assert baza.przejmij_zdjecie(modelka, ids[1])
    assert klient.delete(f"/api/zdjecia/{ids[1]}").status_code == 409
    assert [z["id"] for z in baza.lista_zdjec(modelka)] == [ids[1]] and baza.koszt_w_toku("higgsfield") == 45
    r = klient.post(f"/api/zdjecia/{ids[1]}/przerwij", json={"potwierdzam": True})
    assert r.status_code == 200 and baza.zdjecie(modelka, ids[1])["status"] == "blad"


def test_api_ile_naraz_i_stan_kolejki(klient, modelka, src):
    d = klient.get("/api/ustawienia/globalne").get_json()
    assert d["ok"] and d["ustawienia"]["zdjecia_rownolegle"] == 4 and d["max_rownolegle"] == zs.ROWNOLEGLE_MAX
    assert klient.post("/api/ustawienia/globalne", json={"zdjecia_rownolegle": 0}).status_code == 400
    assert klient.post("/api/ustawienia/globalne", json={"zdjecia_rownolegle": 9}).status_code == 400
    assert klient.post("/api/ustawienia/globalne", json={"cos": 1}).status_code == 400
    d = klient.post("/api/ustawienia/globalne", json={"zdjecia_rownolegle": 2}).get_json()
    assert d["ok"] and d["ustawienia"]["zdjecia_rownolegle"] == 2 and zs.rownolegle() == 2
    zs.zlec(modelka, src, {"ile": 3}, kr=45, saldo=10000, obudz=False)
    s = klient.get("/api/stan").get_json()
    k = s["zdjecia_kolejka"]
    assert s["wersja"] == panel.WERSJA and k["w_kolejce"] == 3 and k["limit"] == 2 and k["persona"] == {"w_toku": 0, "w_kolejce": 3}
    assert baza.budzet().get("max_kredyty_dziennie") == 300         # limity budzetu nietkniete
