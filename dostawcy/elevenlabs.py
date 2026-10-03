# -*- coding: utf-8 -*-
"""ElevenLabs - tylko stan konta (ile znakow TTS zostalo w miesiacu) do paska w panelu. Glos z tekstu idzie przez sync.so.

  GET https://api.elevenlabs.io/v1/user/subscription   naglowek xi-api-key
      -> {"tier", "character_count", "character_limit", "next_character_count_reset_unix", ...}
Klucz: panel -> Konta -> ElevenLabs (albo ELEVENLABS_API_KEY).
"""
import json

import sekrety
from dostawcy import BladDostawcy, BrakKlucza
from dostawcy import http

NAZWA = "elevenlabs"
JEDNOSTKA = "zn"          # znaki (characters) TTS
BAZA_URL = "https://api.elevenlabs.io/v1"


def _naglowki():
    klucz = sekrety.klucz("elevenlabs")
    if not klucz:
        raise BrakKlucza("Brak klucza API ElevenLabs - wpisz go w panelu (Konta) albo ustaw ELEVENLABS_API_KEY.")
    return {"xi-api-key": klucz}


def _opis_bledu(e):
    try:
        d = json.loads(e.tekst)
        det = d.get("detail") if isinstance(d, dict) else None
        if isinstance(det, dict):
            return f"ElevenLabs {e.status}: {det.get('message') or det.get('status') or ''}".strip(": ")
        if isinstance(det, str):
            return f"ElevenLabs {e.status}: {det}"
    except (ValueError, AttributeError):
        pass
    if e.status == 401:
        return "ElevenLabs 401: zly klucz API"
    return f"ElevenLabs {e.status}: {e.tekst[:200]}"


def subskrypcja():
    """Surowe dane subskrypcji (tier, character_count, character_limit...)."""
    try:
        dane = http.zapytanie("GET", BAZA_URL + "/user/subscription", naglowki=_naglowki(), timeout=20, powtorki=1)
    except http.BladHTTP as e:
        raise BladDostawcy(_opis_bledu(e))
    if not isinstance(dane, dict):
        raise BladDostawcy(f"ElevenLabs: dziwna odpowiedz: {str(dane)[:200]}")
    return dane


def saldo_szczegoly():
    """{"kredyty": zostalo znakow | None, "limit": limit znakow w miesiacu, "plan": tier, "jednostka": "zn"}."""
    s = subskrypcja()
    limit = s.get("character_limit")
    uzyte = s.get("character_count")
    zostalo = None
    if isinstance(limit, (int, float)) and isinstance(uzyte, (int, float)):
        zostalo = max(0, int(limit) - int(uzyte))
    return {"kredyty": zostalo, "limit": int(limit) if isinstance(limit, (int, float)) else None,
            "plan": str(s.get("tier") or ""), "jednostka": JEDNOSTKA}


def saldo():
    """Ile znakow TTS zostalo w tym miesiacu (None, gdy API nie podaje)."""
    return saldo_szczegoly()["kredyty"]


def gotowy():
    if not sekrety.klucz("elevenlabs"):
        return False, "brak klucza API ElevenLabs (panel -> Konta)"
    try:
        s = saldo_szczegoly()
    except BladDostawcy as e:
        return False, str(e)
    if s["kredyty"] is None:
        return True, "klucz dziala"
    return True, f"klucz dziala, plan {s['plan'] or '?'}: zostalo {s['kredyty']} z {s['limit']} znakow w tym miesiacu"
