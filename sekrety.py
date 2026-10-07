# -*- coding: utf-8 -*-
"""Klucze API dostawcow (yapper.so, sync.so, ...). Zrodla, w tej kolejnosci:

  1. zmienna srodowiskowa (YAPPER_API_KEY, WAVESPEED_API_KEY, SYNC_API_KEY, ELEVENLABS_API_KEY, OPENROUTER_API_KEY)
  2. plik klucze.json obok stan.json (w .gitignore - NIGDY nie trafia do gita)

Panel zapisuje klucze przez zapisz_klucz(); w odpowiedziach API pokazujemy tylko zamaskuj().
Higgsfield nie ma tu klucza - logowanie OAuth robi CLI (higgsfield auth login).
"""
import json
import os

import baza

PLIK_KLUCZY = os.path.join(os.path.dirname(baza.PLIK_STANU), "klucze.json")

DOSTAWCY = {
    "yapper": {"env": "YAPPER_API_KEY", "nazwa": "yapper.so", "opis": "klucz API z panelu yapper.so"},
    "wavespeed": {"env": "WAVESPEED_API_KEY", "nazwa": "WaveSpeed", "opis": "klucz API WaveSpeedAI (rolki Seedance 2.5 Edit Turbo)"},
    "sync": {"env": "SYNC_API_KEY", "nazwa": "sync.so", "opis": "klucz API z sync.so (Dashboard -> API keys)"},
    "elevenlabs": {"env": "ELEVENLABS_API_KEY", "nazwa": "ElevenLabs",
                   "opis": "glos komentarza zza kamery w rolkach z promptu (eleven_v3) + saldo znakow"},
    "telegram": {"env": "TELEGRAM_BOT_TOKEN", "nazwa": "Telegram", "opis": "token bota od @BotFather - telefon jako pilot fabryki"},
    "openrouter": {"env": "OPENROUTER_API_KEY", "nazwa": "OpenRouter",
                   "opis": "darmowe modele AI - asystent w zakladce Z promptu (bez klucza dobiera regulami)"},
}
# poczatek prawdziwego klucza - panel odrzuca wklejke, ktora na pewno nie jest kluczem (np. Voice ID zamiast klucza ElevenLabs)
PREFIKSY = {"elevenlabs": "sk_", "openrouter": "sk-or-"}


def _wczytaj():
    plik = PLIK_KLUCZY
    if os.path.isfile(plik):
        try:
            with open(plik, encoding="utf-8") as f:
                dane = json.load(f)
            return dane if isinstance(dane, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def klucz(dostawca):
    """Klucz API dostawcy albo None."""
    info = DOSTAWCY.get(dostawca, {})
    z_env = os.environ.get(info.get("env", ""), "").strip() if info.get("env") else ""
    if z_env:
        return z_env
    wartosc = (_wczytaj().get(dostawca) or "").strip()
    return wartosc or None


def zapisz_klucz(dostawca, wartosc):
    if dostawca not in DOSTAWCY:
        raise ValueError(f"Nieznany dostawca '{dostawca}'. Znam: {', '.join(DOSTAWCY)}")
    dane = _wczytaj()
    wartosc = (wartosc or "").strip()
    if wartosc:
        dane[dostawca] = wartosc
    else:
        dane.pop(dostawca, None)
    os.makedirs(os.path.dirname(PLIK_KLUCZY), exist_ok=True)
    with open(PLIK_KLUCZY, "w", encoding="utf-8") as f:
        json.dump(dane, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(PLIK_KLUCZY, 0o600)
    except OSError:
        pass
    return bool(wartosc)


def zamaskuj(wartosc):
    """'sk-abcdefghijkl' -> 'sk-a…ijkl' (nigdy nie pokazujemy calego klucza)."""
    if not wartosc:
        return ""
    if len(wartosc) <= 8:
        return "•" * len(wartosc)
    return wartosc[:4] + "…" + wartosc[-4:]


def stan():
    """{dostawca: {nazwa, opis, jest, maska, z_env}} dla panelu."""
    wynik = {}
    for d, info in DOSTAWCY.items():
        k = klucz(d)
        wynik[d] = {"nazwa": info["nazwa"], "opis": info["opis"], "jest": bool(k), "maska": zamaskuj(k),
                    "z_env": bool(os.environ.get(info["env"], "").strip())}
    return wynik
