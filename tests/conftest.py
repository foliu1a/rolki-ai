# -*- coding: utf-8 -*-
"""Wspolne fixtury: modelki w katalogu tymczasowym + udawane CLI Higgsfield (zero prawdziwych wywolan)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import baza  # noqa: E402
import higgsfield_cli  # noqa: E402
import sekrety  # noqa: E402


@pytest.fixture
def dane(tmp_path, monkeypatch):
    """Przekierowuje baza.py na tmp_path (modelki/, stan.json, budzet.json, dziennik, klucze)."""
    modelki = tmp_path / "modelki"
    modelki.mkdir()
    monkeypatch.setattr(baza, "KATALOG_MODELEK", str(modelki))
    monkeypatch.setattr(baza, "PLIK_STANU", str(tmp_path / "stan.json"))
    monkeypatch.setattr(baza, "PLIK_BUDZETU", str(tmp_path / "budzet.json"))
    monkeypatch.setattr(baza, "PLIK_DZIENNIKA", str(tmp_path / "dziennik.jsonl"))
    monkeypatch.setattr(sekrety, "PLIK_KLUCZY", str(tmp_path / "klucze.json"))
    monkeypatch.setenv("ROLKI_PULPIT", str(tmp_path / "pulpit" / "ROLKI AI"))   # foldery "na pulpicie" tez w tmp
    for env in ("YAPPER_API_KEY", "WAVESPEED_API_KEY", "SYNC_API_KEY", "ELEVENLABS_API_KEY", "TELEGRAM_BOT_TOKEN", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    from dostawcy import wavespeed, yapper
    yapper.wyczysc_cache()          # lista modeli/schematy yappera z poprzedniego testu
    from dostawcy import elevenlabs
    elevenlabs._stan_klucza.clear()  # cache "czy klucz ElevenLabs dziala" z poprzedniego testu
    wavespeed._ostatnia_wycena.clear()
    return tmp_path


@pytest.fixture
def modelka(dane):
    """Modelka 'noemi' (aktywna) z promptami A/B i dwiema referencjami."""
    slug = baza.utworz_modelke("Noemi")
    baza.ustaw_aktywna_modelke(slug)
    folder = baza.folder_modelki(slug)
    baza.zapisz_prompt(slug, "stroj_z_filmu.txt", "PROMPT A @[Image 1](image_1) @[Image 2](image_2)")
    baza.zapisz_prompt(slug, "stroj_ze_zdjecia.txt", "PROMPT B @[Image 1](image_1) @[Image 3](image_3)")
    for n in ("01_twarz.png", "02_sylwetka.jpg"):
        with open(os.path.join(folder, "referencje", n), "wb") as f:
            f.write(b"img")
    return slug


class UdawaneCLI:
    """Zastepuje funkcje higgsfield_cli uzywane przez fabryke. Udaje tez serwer: `generate create` (generuj) zapisuje job,
    `generate get` (job) go oddaje, `generate list` (joby) - liste. Saldo spada tylko przy udanym jobie."""

    def __init__(self, saldo=1000, koszt=45):
        self.saldo = saldo
        self.cena = koszt
        self.generacje = []      # (model, params, media) - kazde WYSLANIE (generate create)
        self.wyniki = []         # kolejka: dict (koncowy job) albo wyjatek (create padl - job NIE powstal); pusta = sukces z URL
        self.pobrane = []
        self.blad_koszt = None
        self.blad_kredyty = False
        self.serwer = {}         # job_id -> koncowy job (to, co widzi `generate get` / `generate list`)
        self.odpytania = []      # job_id kazdego `generate get`
        self.uploady = []

    def kredyty(self):
        if self.blad_kredyty:
            raise higgsfield_cli.HiggsfieldBlad("account status padl")
        return self.saldo

    def koszt(self, model, params=None, media=None):
        if self.blad_koszt:
            raise self.blad_koszt
        return self.cena

    def generuj(self, model, params=None, media=None, wait=True, wait_timeout="30m"):
        from datetime import datetime, timezone
        self.generacje.append((model, params, media))
        wynik = self.wyniki.pop(0) if self.wyniki else None
        if isinstance(wynik, Exception):
            raise wynik
        jid = f"job{len(self.generacje)}"
        if wynik is None:
            self.saldo -= self.cena
            wynik = {"id": jid, "status": "completed", "result": {"url": f"https://cdn.example/wynik{len(self.generacje)}.mp4"}}
        else:
            wynik = dict(wynik)
            wynik.setdefault("id", jid)
        wideo = (media or {}).get("video")
        wynik.setdefault("job_type", model)
        wynik.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        wynik.setdefault("params", {"prompt": (params or {}).get("prompt"),
                                    "medias": [{"role": "video", "data": {"id": wideo}}] if wideo else []})
        self.serwer[wynik["id"]] = wynik
        if wait:
            return wynik
        return {"id": wynik["id"], "status": "queued"}      # jak CLI bez --wait: samo id

    def job(self, jid):
        self.odpytania.append(jid)
        if jid not in self.serwer:
            raise higgsfield_cli.HiggsfieldBlad(f"job {jid} not found")
        return self.serwer[jid]

    def joby(self, typ=None, ile=20):
        return list(self.serwer.values())[::-1][:ile]

    def pobierz(self, url, sciezka):
        os.makedirs(os.path.dirname(sciezka), exist_ok=True)
        with open(sciezka, "wb") as f:
            f.write(b"mp4")
        self.pobrane.append((url, sciezka))
        return sciezka

    def upload(self, plik):
        self.uploady.append(plik)
        return {"id": "uuid-" + os.path.basename(plik)}


@pytest.fixture
def cli(monkeypatch):
    """Udawane CLI + brak prawdziwego subprocess (gdyby cos jednak siegnelo do _uruchom)."""
    u = UdawaneCLI()
    for nazwa in ("kredyty", "koszt", "generuj", "pobierz", "upload", "job", "joby"):
        monkeypatch.setattr(higgsfield_cli, nazwa, getattr(u, nazwa))

    def zakaz(*a, **k):
        raise AssertionError("test sięgnął do prawdziwego CLI Higgsfield")
    monkeypatch.setattr(higgsfield_cli, "_uruchom", zakaz)
    return u
