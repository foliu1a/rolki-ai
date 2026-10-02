# -*- coding: utf-8 -*-
"""sync.so (Sync Labs) - lipsync: wideo + glos -> wideo z dopasowanymi ustami. Osobny interfejs niz dostawcy wideo.

API (SDK syncsdk 0.3.0 / docs.sync.so): https://api.sync.so/v2, naglowek `x-api-key: <klucz>`.
  POST /v2/generate            JSON {"model": "lipsync-2", "input": [{"type":"video","url"|"assetId"}, {"type":"audio",...}], "options": {...}}
  POST /v2/generate            multipart: pola plikowe `video`, `audio` (<20 MB), tekstowe `model`, `options` (JSON)
  GET  /v2/generate/{id}       status PENDING|PROCESSING|COMPLETED|FAILED|REJECTED, outputUrl, error, errorCode
  POST /v2/analyze/cost        [{"estimatedFrameCount": n, "estimatedGenerationCost": usd}]
  GET  /v2/models              modele (lipsync-2, lipsync-2-pro, sync-3, lipsync-1.9.0-beta, react-1)
  POST /v2/tts                 {"script","voiceId","provider":"elevenlabs"} -> {"id","url","duration"}
  GET  /v2/voices              glosy do TTS

Klucz: https://sync.so/settings/api-keys -> panel Konta (klucze.json) albo SYNC_API_KEY.
Pliki lokalne idziemy multipartem (limit 20 MB); wieksze najpierw zmniejszamy ffmpegiem (lipsync.py).
Koszt liczymy w centach USD (budzet dostawcy "sync").
"""
import json
import os
import time

import sekrety
from dostawcy import BladDostawcy, BrakKlucza
from dostawcy import http

NAZWA = "sync"
JEDNOSTKA = "c"       # centy USD
BAZA_URL = "https://api.sync.so/v2"
LIMIT_MULTIPART = 20 * 1024 * 1024
ODSTEP_ODPYTYWANIA = 10
MODELE = ("lipsync-2", "lipsync-2-pro", "sync-3", "lipsync-1.9.0-beta")
TRYBY_SYNC = ("bounce", "loop", "cut_off", "silence", "remap")


def _naglowki():
    klucz = sekrety.klucz("sync")
    if not klucz:
        raise BrakKlucza("Brak klucza API sync.so - wpisz go w panelu (Konta) albo ustaw SYNC_API_KEY.")
    return {"x-api-key": klucz, "x-sync-source": "rolki-ai"}


def _opis_bledu(e):
    try:
        d = json.loads(e.tekst)
        if isinstance(d, dict):
            msg = d.get("message")
            if isinstance(msg, list):
                msg = "; ".join(str(m) for m in msg)
            kod = d.get("errorCode") or d.get("error") or ""
            return f"sync.so {e.status} {kod}: {msg or ''}".strip(": ")
    except (ValueError, AttributeError):
        pass
    if e.status == 401:
        return "sync.so 401: zly klucz API"
    if e.status == 402:
        return "sync.so 402: plan nie pozwala (darmowe generacje wyczerpane / za dlugie wideo / nieoplacona faktura)"
    if e.status == 429:
        return "sync.so 429: limit rownoleglych generacji - sprobuj za chwile"
    return f"sync.so {e.status}: {e.tekst[:300]}"


def _wywolaj(metoda, sciezka, dane=None, timeout=120, powtorki=http.POWTORKI):
    try:
        return http.zapytanie(metoda, BAZA_URL + sciezka, dane=dane, naglowki=_naglowki(), timeout=timeout, powtorki=powtorki)
    except http.BladHTTP as e:
        raise BladDostawcy(_opis_bledu(e))


def gotowy():
    if not sekrety.klucz("sync"):
        return False, "brak klucza API sync.so (panel -> Konta)"
    try:
        m = modele()
    except BladDostawcy as e:
        return False, str(e)
    return True, "klucz dziala, modele: " + ", ".join(x.get("id", "?") for x in m if isinstance(x, dict))


def saldo():
    """sync.so nie ma endpointu salda (rozliczenie z dolu) - None."""
    return None


def modele():
    dane = _wywolaj("GET", "/models", timeout=20, powtorki=1)
    return dane if isinstance(dane, list) else (dane or {}).get("items") or []


def glosy():
    dane = _wywolaj("GET", "/voices", timeout=20, powtorki=1)
    return dane if isinstance(dane, list) else (dane or {}).get("items") or []


def _wejscie(wideo, audio):
    """Element input[] z URL-a albo None dla plikow lokalnych (ida multipartem)."""
    wej = []
    if isinstance(wideo, str) and wideo.startswith("http"):
        wej.append({"type": "video", "url": wideo})
    if isinstance(audio, str) and audio.startswith("http"):
        wej.append({"type": "audio", "url": audio})
    return wej


def koszt(wideo, audio, model="lipsync-2", opcje=None):
    """Szacunek w centach USD (POST /analyze/cost) - dziala tylko z URL-ami; dla plikow lokalnych liczymy z dlugosci."""
    wej = _wejscie(wideo, audio)
    if len(wej) < 2:
        return None
    dane = _wywolaj("POST", "/analyze/cost", {"model": model, "input": wej, "options": opcje or {}})
    if isinstance(dane, list) and dane and isinstance(dane[0], dict):
        usd = dane[0].get("estimatedGenerationCost")
        if isinstance(usd, (int, float)):
            return int(round(usd * 100))
    return None


# orientacyjne ceny ($/s wyjscia, 25 fps) - do szacunku lokalnego, gdy /analyze/cost nie da rady
CENA_ZA_SEKUNDE = {"lipsync-1.9.0-beta": 0.025, "lipsync-2": 0.05, "lipsync-2-pro": 0.083, "sync-3": 0.133, "react-1": 0.167}


def koszt_szacunkowy(sekundy, model="lipsync-2"):
    return int(round(float(sekundy) * CENA_ZA_SEKUNDE.get(model, 0.05) * 100))


def generuj(wideo, audio, model="lipsync-2", opcje=None, timeout_s=1800, log=None):
    """Tworzy generacje (JSON z URL-ami albo multipart z plikami) i czeka. Zwraca {"job_id","status","url","blad","surowe","sekundy"}."""
    opcje = dict(opcje or {})
    wej = _wejscie(wideo, audio)
    pliki = {}
    if not (isinstance(wideo, str) and wideo.startswith("http")):
        if os.path.getsize(wideo) > LIMIT_MULTIPART:
            raise BladDostawcy(f"sync.so: {os.path.basename(wideo)} ma ponad 20 MB - multipart tego nie przyjmie (lipsync.py powinien zmniejszyc)")
        pliki["video"] = wideo
    if not (isinstance(audio, str) and audio.startswith("http")):
        if os.path.getsize(audio) > LIMIT_MULTIPART:
            raise BladDostawcy(f"sync.so: {os.path.basename(audio)} ma ponad 20 MB")
        pliki["audio"] = audio
    try:
        if pliki:
            pola = {"model": model, "options": json.dumps(opcje)}
            if wej:
                pola["input"] = json.dumps(wej)
            gen = http.multipart(BAZA_URL + "/generate", pola=pola, pliki=pliki, naglowki=_naglowki(), timeout=900)
        else:
            gen = http.zapytanie("POST", BAZA_URL + "/generate", dane={"model": model, "input": wej, "options": opcje},
                                 naglowki=_naglowki(), timeout=120)
    except http.BladHTTP as e:
        raise BladDostawcy(_opis_bledu(e))
    gid = (gen or {}).get("id")
    if not gid:
        raise BladDostawcy(f"sync.so: POST /generate bez id: {json.dumps(gen)[:300]}")
    if log:
        log(f"sync.so: generacja {gid} ({model}) w toku...")
    koniec = time.time() + timeout_s
    stan = str((gen or {}).get("status") or "PENDING").upper()
    while stan in ("PENDING", "PROCESSING") and time.time() < koniec:
        time.sleep(ODSTEP_ODPYTYWANIA)
        gen = _wywolaj("GET", f"/generate/{gid}")
        stan = str((gen or {}).get("status") or "").upper()
    if stan in ("PENDING", "PROCESSING"):
        raise BladDostawcy(f"sync.so: generacja {gid} nie skonczyla sie w {timeout_s}s")
    blad = ""
    if stan != "COMPLETED":
        blad = f"{gen.get('errorCode') or ''}: {gen.get('error') or ''}".strip(": ") or stan
    return {"job_id": str(gid), "status": stan.lower(), "url": gen.get("outputUrl"), "blad": blad, "surowe": gen,
            "sekundy": gen.get("outputDuration")}


def tts(tekst, voice_id, stabilnosc=None, podobienstwo=None):
    """Glos z tekstu (ElevenLabs przez sync.so). Zwraca {"id","url","duration"}."""
    cialo = {"script": tekst, "voiceId": voice_id, "provider": "elevenlabs"}
    if stabilnosc is not None:
        cialo["stability"] = float(stabilnosc)
    if podobienstwo is not None:
        cialo["similarityBoost"] = float(podobienstwo)
    dane = _wywolaj("POST", "/tts", cialo, timeout=300)
    if not isinstance(dane, dict) or not dane.get("url"):
        raise BladDostawcy(f"sync.so: /tts bez url: {json.dumps(dane)[:300]}")
    return dane


def pobierz(url, sciezka):
    return http.pobierz(url, sciezka)
