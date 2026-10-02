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
    for env in ("YAPPER_API_KEY", "SYNC_API_KEY", "ELEVENLABS_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
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
    """Zastepuje funkcje higgsfield_cli uzywane przez fabryke. Saldo spada tylko przy udanym jobie."""

    def __init__(self, saldo=1000, koszt=45):
        self.saldo = saldo
        self.cena = koszt
        self.generacje = []      # (model, params, media)
        self.wyniki = []         # kolejka: dict (job) albo wyjatek; pusta = sukces z URL
        self.pobrane = []
        self.blad_koszt = None
        self.blad_kredyty = False

    def kredyty(self):
        if self.blad_kredyty:
            raise higgsfield_cli.HiggsfieldBlad("account status padl")
        return self.saldo

    def koszt(self, model, params=None, media=None):
        if self.blad_koszt:
            raise self.blad_koszt
        return self.cena

    def generuj(self, model, params=None, media=None, wait=True, wait_timeout="30m"):
        self.generacje.append((model, params, media))
        wynik = self.wyniki.pop(0) if self.wyniki else None
        if isinstance(wynik, Exception):
            raise wynik
        if wynik is None:
            self.saldo -= self.cena
            wynik = {"id": f"job{len(self.generacje)}", "status": "completed",
                     "result": {"url": f"https://cdn.example/wynik{len(self.generacje)}.mp4"}}
        return wynik

    def pobierz(self, url, sciezka):
        os.makedirs(os.path.dirname(sciezka), exist_ok=True)
        with open(sciezka, "wb") as f:
            f.write(b"mp4")
        self.pobrane.append((url, sciezka))
        return sciezka

    def upload(self, plik):
        return {"id": "uuid-" + os.path.basename(plik)}


@pytest.fixture
def cli(monkeypatch):
    """Udawane CLI + brak prawdziwego subprocess (gdyby cos jednak siegnelo do _uruchom)."""
    u = UdawaneCLI()
    for nazwa in ("kredyty", "koszt", "generuj", "pobierz", "upload"):
        monkeypatch.setattr(higgsfield_cli, nazwa, getattr(u, nazwa))

    def zakaz(*a, **k):
        raise AssertionError("test sięgnął do prawdziwego CLI Higgsfield")
    monkeypatch.setattr(higgsfield_cli, "_uruchom", zakaz)
    return u
