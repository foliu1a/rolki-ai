# -*- coding: utf-8 -*-
"""Lipsync: gotowa rolka + glos (mp3/wav) -> wideo z dopasowanymi ustami.

    zrob(slug, wideo, audio, pomysl_id=None, log=None) -> sciezka wyniku (w folderze gotowych) albo None

Dostawca z ustawien modelki (`lipsync_dostawca`): sync (sync.so API, domyslnie) albo higgsfield (model lipsync z CLI,
`lipsync_model` = job_type). Rejestr prob w modelki/<slug>/lipsync.json (panel pokazuje historie).
Glos: <nazwa>.audio.mp3 obok filmiku zrodlowego (lipsync_auto po generacji), plik z modelki/<slug>/audio/ (panel),
albo TTS z tekstu (tts_z_tekstu -> sync.so /tts z glosem ElevenLabs).
"""
import os
import shutil
import subprocess
import time

import baza
import dostawcy
from dostawcy import sync_so

LIMIT_MB = 19


def _log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def _zdarzenie(log, slug, typ, tekst, **dane):
    (log or _log)(tekst)
    try:
        baza.dziennik_zapisz(typ, tekst, modelka=slug, **dane)
    except OSError:
        pass


def zmniejsz_do_limitu(wideo, folder_tmp, limit_mb=LIMIT_MB):
    """sync.so przyjmuje multipartem pliki < 20 MB. Wieksze przekodowujemy ffmpegiem (wynik i tak jest re-enkodowany)."""
    if os.path.getsize(wideo) <= limit_mb * 1024 * 1024:
        return wideo
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(f"{os.path.basename(wideo)} ma ponad {limit_mb} MB, a nie ma ffmpeg w PATH, zeby go zmniejszyc")
    os.makedirs(folder_tmp, exist_ok=True)
    cel = os.path.join(folder_tmp, os.path.splitext(os.path.basename(wideo))[0] + ".maly.mp4")
    for crf in (24, 28, 32):
        subprocess.run([ffmpeg, "-v", "error", "-y", "-i", wideo, "-vf", "scale=-2:'min(1080,ih)'",
                        "-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-c:a", "aac", "-b:a", "128k", cel],
                       capture_output=True, timeout=900)
        if os.path.isfile(cel) and os.path.getsize(cel) <= limit_mb * 1024 * 1024:
            return cel
    raise RuntimeError(f"nie udalo sie zmniejszyc {os.path.basename(wideo)} ponizej {limit_mb} MB")


def _nazwa_wyniku(slug, wideo, pomysl_id):
    stem = os.path.splitext(os.path.basename(wideo))[0]
    stem = stem.replace(".raw", "")
    return f"{stem}_lipsync.mp4"


def zrob(slug, wideo, audio, pomysl_id=None, log=None, model=None, opcje=None):
    """Caly obieg: rejestr -> (zmniejsz) -> dostawca -> pobierz do folderu gotowych -> aktualizuj pomysl.
    Rzuca wyjatek przy bledzie (fabryka lapie); zwraca sciezke wyniku."""
    log = log or _log
    ust = baza.ustawienia_modelki(slug)
    dostawca = (ust.get("lipsync_dostawca") or "sync").strip().lower()
    model = model or ust.get("lipsync_model") or "lipsync-2"
    opcje = dict(ust.get("lipsync_parametry") or {}, **(opcje or {}))
    if not os.path.isfile(wideo):
        raise FileNotFoundError(wideo)
    if not os.path.isfile(audio):
        raise FileNotFoundError(audio)
    lid = baza.dodaj_lipsync(slug, wideo, audio, dostawca, model, pomysl_id=pomysl_id)
    cel = os.path.join(baza.folder_gotowych(slug), _nazwa_wyniku(slug, wideo, pomysl_id))
    _zdarzenie(log, slug, "info", f"lipsync #{lid}: {os.path.basename(wideo)} + {os.path.basename(audio)} ({dostawca} {model})", lipsync=lid)
    try:
        if dostawca == "sync":
            wynik = _przez_sync(slug, wideo, audio, model, opcje, log)
        elif dostawca == "higgsfield":
            wynik = _przez_higgsfield(slug, wideo, audio, model, opcje, log)
        else:
            raise ValueError(f"nieznany lipsync_dostawca '{dostawca}' (sync | higgsfield)")
        if not wynik.get("url"):
            raise RuntimeError(wynik.get("blad") or f"brak URL wyniku (status {wynik.get('status')})")
        (sync_so if dostawca == "sync" else dostawcy.dostawca("higgsfield")).pobierz(wynik["url"], cel)
    except Exception as e:
        baza.aktualizuj_lipsync(slug, lid, status="blad", notatki=str(e)[:1000])
        raise
    koszt = wynik.get("koszt")
    if koszt:
        baza.dopisz_wydatek(koszt, dostawca)
    baza.aktualizuj_lipsync(slug, lid, status="gotowe", plik_wynikowy=cel, job_id=wynik.get("job_id"), koszt=koszt)
    if pomysl_id:
        try:
            baza.aktualizuj_pomysl(slug, pomysl_id, lipsync_plik=cel)
        except ValueError:
            pass
    _zdarzenie(log, slug, "ok", f"lipsync #{lid}: GOTOWE -> {cel}" + (f" ({koszt} c)" if koszt else ""), lipsync=lid, plik=cel)
    return cel


def _przez_sync(slug, wideo, audio, model, opcje, log):
    tmp = os.path.join(baza.folder_wynikow(slug), "_lipsync_tmp")
    maly = zmniejsz_do_limitu(wideo, tmp)
    try:
        w = sync_so.generuj(maly, audio, model=model, opcje=opcje, log=log)
    finally:
        if maly != wideo:
            shutil.rmtree(tmp, ignore_errors=True)
    sek = w.get("sekundy")
    w["koszt"] = sync_so.koszt_szacunkowy(sek, model) if sek else None
    return w


def _przez_higgsfield(slug, wideo, audio, model, opcje, log):
    """Model lipsync z Higgsfield (job_type w lipsync_model, np. z `model list --video`). Parametry z lipsync_parametry."""
    d = dostawcy.dostawca("higgsfield")
    z = {"slug": slug, "model": model, "prompt": opcje.pop("prompt", ""), "video": wideo, "audio": audio,
         "images": [], "parametry": opcje, "mode": None, "aspect_ratio": None, "resolution": None}
    saldo_przed = None
    try:
        saldo_przed = d.saldo()
    except dostawcy.BladDostawcy:
        pass
    w = d.generuj(z, timeout="30m", log=log)
    koszt = None
    try:
        if saldo_przed is not None:
            koszt = max(0, saldo_przed - d.saldo())
    except dostawcy.BladDostawcy:
        pass
    return {"job_id": w.get("job_id"), "status": w.get("status"), "url": (w.get("urls") or [None])[0],
            "blad": w.get("blad"), "koszt": koszt}


def tts_z_tekstu(slug, tekst, voice_id=None, nazwa=None, log=None):
    """Glos z tekstu przez sync.so (ElevenLabs). Zapisuje mp3 w modelki/<slug>/audio/. Zwraca sciezke."""
    log = log or _log
    ust = baza.ustawienia_modelki(slug)
    voice_id = voice_id or ust.get("tts_glos")
    if not voice_id:
        raise ValueError("Podaj voice id (ustawienie tts_glos albo z listy glosow sync.so).")
    dane = sync_so.tts(tekst, voice_id)
    nazwa = nazwa or f"tts_{time.strftime('%Y%m%d_%H%M%S')}"
    cel = os.path.join(baza.folder_audio(slug), f"{nazwa}.mp3")
    sync_so.pobierz(dane["url"], cel)
    _zdarzenie(log, slug, "ok", f"TTS -> {cel} ({dane.get('duration')} s)")
    return cel
