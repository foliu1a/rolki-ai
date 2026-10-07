# -*- coding: utf-8 -*-
"""ElevenLabs - stan konta (ile znakow TTS zostalo w miesiacu) do paska w panelu + glos komentarza zza kamery w rolkach
z promptu (komentarz_glos.py: eleven_v3, poprawna polszczyzna zamiast "wyględa" z modelu wideo). Lipsync TTS nadal przez sync.so.

  GET  https://api.elevenlabs.io/v1/user/subscription   naglowek xi-api-key
       -> {"tier", "character_count", "character_limit", "next_character_count_reset_unix", ...}
  GET  /v1/voices -> {"voices": [{voice_id, name, category, labels{language, accent, gender, ...}}]}
  POST /v1/text-to-speech/{voice_id}?output_format=mp3_44100_128 {"text", "model_id": "eleven_v3"} -> mp3 (bajty)
Klucz: panel -> Konta -> ElevenLabs (albo ELEVENLABS_API_KEY). Klucz ElevenLabs zaczyna sie od "sk_". Klucz moze miec
ograniczone uprawnienia: 401 "missing_permissions" = klucz PRAWDZIWY (tylko bez tego zakresu), "invalid_api_key" = zly klucz.
"""
import json
import os
import re
import time

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
    if "key id used as api key" in (e.tekst or "").lower():
        return ("ElevenLabs: wklejone jest ID klucza, a nie sam klucz - prawdziwy klucz zaczyna sie od sk_ i ElevenLabs pokazuje go "
                "tylko raz, przy tworzeniu (elevenlabs.io -> Developers -> API Keys -> Create, skopiuj od razu)")
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


MODEL_TTS = "eleven_v3"          # user woli v3 (tg-glosowki: "V4 brzmi dziwnie")
PREFIKS_KLUCZA = "sk_"
PODPOWIEDZ_FORMATU = " - klucz ElevenLabs zaczyna sie od sk_: skopiuj go jeszcze raz (elevenlabs.io -> Developers -> API Keys)"
_stan_klucza = {}                 # cache: {"czas", "klucz" (ostatnie 6 znakow), "wynik"}
CACHE_STANU_S = 600


def klucz_wyglada_dobrze(klucz):
    """Klucz ElevenLabs ma postac sk_ + ~48 znakow. Inny ksztalt = na pewno nie ten klucz (np. wklejony Voice ID)."""
    k = (klucz or "").strip()
    return k.startswith(PREFIKS_KLUCZA) and len(k) >= 20 and " " not in k


def _status_401(e):
    try:
        det = (json.loads(e.tekst) or {}).get("detail")
        return (det.get("status") or "") if isinstance(det, dict) else ""
    except (ValueError, AttributeError):
        return ""


def stan_klucza(odswiez=False):
    """('ok' | 'brak' | 'zly' | 'nie_wiem', komunikat). Bez kosztu (GET subscription), cache 10 min.
    'nie_wiem' = blad sieci/5xx (nie oznaczamy klucza jako zlego)."""
    klucz = sekrety.klucz("elevenlabs")
    if not klucz:
        return "brak", "brak klucza API ElevenLabs (panel -> Ustawienia -> Konta)"
    c = _stan_klucza
    if not odswiez and c.get("klucz") == klucz[-6:] and time.time() - c.get("czas", 0) < CACHE_STANU_S:
        return c["wynik"]
    try:
        http.zapytanie("GET", BAZA_URL + "/user/subscription", naglowki=_naglowki(), timeout=15, powtorki=1)
        wynik = ("ok", "klucz dziala")
    except http.BladHTTP as e:
        if e.status == 401 and _status_401(e) == "missing_permissions":
            wynik = ("ok", "klucz dziala (bez uprawnienia do odczytu konta)")
        elif e.status in (401, 403) or (e.status == 400 and "api key" in (e.tekst or "").lower()):
            wynik = ("zly", _opis_bledu(e) + ("" if klucz_wyglada_dobrze(klucz) else PODPOWIEDZ_FORMATU))
        else:
            return "nie_wiem", _opis_bledu(e)
    _stan_klucza.update(czas=time.time(), klucz=klucz[-6:], wynik=wynik)
    return wynik


def glosy():
    """Glosy z konta (moje + dodane z biblioteki + gotowe): [{voice_id, name, category, labels}]."""
    try:
        dane = http.zapytanie("GET", BAZA_URL + "/voices", naglowki=_naglowki(), timeout=20, powtorki=1)
    except http.BladHTTP as e:
        raise BladDostawcy(_opis_bledu(e))
    wynik = []
    for v in (dane or {}).get("voices") or []:
        if isinstance(v, dict) and v.get("voice_id"):
            jezyki = [str(j.get("language") or "").lower() for j in (v.get("verified_languages") or []) if isinstance(j, dict)]
            wynik.append({"voice_id": v["voice_id"], "name": v.get("name") or "", "category": v.get("category") or "",
                          "labels": v.get("labels") if isinstance(v.get("labels"), dict) else {}, "jezyki": jezyki})
    return wynik


KATEGORIE_GLOSOW = ("premade", "professional")   # NIGDY "cloned" (klony person i testy - przez nie mowila nie ta osoba)


def glos_polski(v):
    """Czy glos mowi po polsku: labels.language/accent ('pl', 'polish', 'polski') albo verified_languages."""
    lab = {k: str(w).lower() for k, w in (v.get("labels") or {}).items()}
    slowa = re.split(r"[\s,;/()-]+", " ".join([lab.get("language", ""), lab.get("accent", "")]))
    return (any(s in ("pl", "polish", "polski", "polska") for s in slowa)
            or any(j in ("pl", "polish") or j.startswith("pl-") for j in (v.get("jezyki") or [])))


def wybierz_glos(lista, pomin_nazwy=(), plec=None):
    """Glos osoby, ktora nagrywa (zza kamery): TYLKO kategoria premade/professional (nigdy cloned/generated), jezyk polski,
    plec = `plec` ('male' / 'female', gdy podana - musi sie zgadzac), nazwa bez imienia ktorejkolwiek persony (to ona jest
    nagrywana, nie mowi). None = nie ma takiego glosu (wtedy rolka bez komentarza - nie zgadujemy)."""
    pomin = {n.strip().lower() for n in pomin_nazwy if n and n.strip()}
    kandydaci = []
    for v in lista or []:
        nazwa = (v.get("name") or "").strip().lower()
        lab = {k: str(w).lower() for k, w in (v.get("labels") or {}).items()}
        if (v.get("category") or "").lower() not in KATEGORIE_GLOSOW:
            continue
        if any(n in nazwa for n in pomin):
            continue
        if not glos_polski(v):
            continue
        if plec and lab.get("gender") != plec:
            continue
        kandydaci.append(v)
    if not kandydaci:
        return None
    # professional (glosy z Voice Library, zwykle natywni Polacy) przed premade
    return sorted(kandydaci, key=lambda v: (v.get("category") != "professional", v.get("name") or ""))[0]


def tts(tekst, voice_id, cel, model=MODEL_TTS, ustawienia=None):
    """Tekst -> mp3 (zapis do `cel`). Kosztuje znaki ElevenLabs (~30-60 na komentarz). Rzuca BladDostawcy."""
    if not voice_id:
        raise BladDostawcy("ElevenLabs: brak voice_id")
    cialo = {"text": tekst, "model_id": model}
    if ustawienia:
        cialo["voice_settings"] = dict(ustawienia)
    url = f"{BAZA_URL}/text-to-speech/{voice_id}?output_format=mp3_44100_128"
    try:
        bajty, typ = http.zapytanie_bajty("POST", url, dane=cialo, naglowki=dict(_naglowki(), Accept="audio/mpeg"),
                                          timeout=120, powtorki=2)
    except http.BladHTTP as e:
        raise BladDostawcy(_opis_bledu(e))
    if not bajty or "json" in (typ or "").lower() or len(bajty) < 512:
        raise BladDostawcy(f"ElevenLabs: zamiast dzwieku przyszlo: {bajty[:200]!r}")
    os.makedirs(os.path.dirname(os.path.abspath(cel)), exist_ok=True)
    with open(cel, "wb") as f:
        f.write(bajty)
    return cel


def gotowy():
    if not sekrety.klucz("elevenlabs"):
        return False, "brak klucza API ElevenLabs (panel -> Konta)"
    try:
        s = saldo_szczegoly()
    except BladDostawcy as e:
        stan, kom = stan_klucza(odswiez=True)
        if stan == "ok":
            return True, kom            # klucz dobry, tylko bez user_read (TTS dziala)
        return False, str(e) + ("" if klucz_wyglada_dobrze(sekrety.klucz("elevenlabs")) else PODPOWIEDZ_FORMATU)
    if s["kredyty"] is None:
        return True, "klucz dziala"
    return True, f"klucz dziala, plan {s['plan'] or '?'}: zostalo {s['kredyty']} z {s['limit']} znakow w tym miesiacu"
