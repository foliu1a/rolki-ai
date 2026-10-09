# -*- coding: utf-8 -*-
"""Lipsync: gotowa rolka + glos (mp3/wav) -> wideo z dopasowanymi ustami.

    zrob(slug, wideo, audio, pomysl_id=None, log=None) -> sciezka wyniku (w folderze gotowych) albo None

Dostawca z ustawien modelki (`lipsync_dostawca`): sync (sync.so API, domyslnie) albo higgsfield (model lipsync z CLI,
`lipsync_model` = job_type). Rejestr prob w modelki/<slug>/lipsync.json (panel pokazuje historie).
Glos: <nazwa>.audio.mp3 obok filmiku zrodlowego (lipsync_auto po generacji), plik z modelki/<slug>/audio/ (panel),
glosowka z Telegrama (.ogg) albo TTS z tekstu (tts_z_tekstu -> sync.so /tts z glosem ElevenLabs).
Przed wyslaniem glos jest przerabiany (przygotuj_glos, ffmpeg) wg `lipsync_glos_styl`: "telefon" = brzmi jak nagranie
z telefonu w pokoju (pasmo mikrofonu, krotkie odbicia, lekka kompresja, szum tla, glosnosc jak z glosowki), "czysty" =
tylko wyrownana glosnosc, "brak" = plik bez zmian. Wynik w modelki/<slug>/audio/_przygotowane/.
"""
import os
import shutil
import subprocess
import time

import baza
import dostawcy
from dostawcy import sync_so

LIMIT_MB = 19

STYLE_GLOSU = {
    "telefon": "jak nagranie z telefonu w pokoju (naturalnie, z lekkim poglosem i szumem tla)",
    "czysty": "czysty glos, tylko wyrownana glosnosc",
    "brak": "bez zmian - plik idzie taki, jaki jest",
}
# Lancuch ffmpeg dla "telefon": pasmo mikrofonu telefonu (150 Hz - 7,6 kHz), krotkie odbicia malego pokoju (11/23/37 ms),
# lekka kompresja jak w aplikacji nagrywania, ledwo slyszalny rozowy szum tla, glosnosc -16 LUFS (jak glosowka).
_FILTR_TELEFON = ("[0:a]aresample=48000,highpass=f=150,lowpass=f=7600,"
                  "aecho=0.9:0.3:11|23|37:0.22|0.14|0.09,"
                  "acompressor=threshold=-20dB:ratio=3:attack=8:release=140:makeup=4dB[g];"
                  "anoisesrc=color=pink:amplitude=0.004:sample_rate=48000[n];"
                  "[g][n]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                  "loudnorm=I=-16:TP=-1.5:LRA=9[out]")
_FILTR_CZYSTY = "[0:a]aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=11[out]"


def przygotuj_glos(slug, audio, styl="telefon", log=None):
    """Glos (mp3/wav/m4a/ogg) -> mp3 mono 48 kHz w stylu `styl` (STYLE_GLOSU), zapisany w modelki/<slug>/audio/_przygotowane/.
    Zwraca sciezke pliku do lipsyncu. Gdy styl == "brak", brak ffmpeg albo ffmpeg padl -> oryginal (z ostrzezeniem w dzienniku)."""
    log = log or _log
    styl = (styl or "telefon").strip().lower()
    if styl not in STYLE_GLOSU:
        raise ValueError(f"Nieznany styl glosu '{styl}' (dozwolone: {', '.join(STYLE_GLOSU)}).")
    if styl == "brak":
        return audio
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        _zdarzenie(log, slug, "uwaga", "glos: brak ffmpeg w PATH - wysylam oryginalne nagranie bez przerobki")
        return audio
    folder = os.path.join(baza.folder_audio(slug), "_przygotowane")
    os.makedirs(folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(audio))[0]
    filtr = _FILTR_TELEFON if styl == "telefon" else _FILTR_CZYSTY
    for rozsz, kodek in ((".mp3", ["-c:a", "libmp3lame", "-b:a", "160k"]), (".wav", ["-c:a", "pcm_s16le"])):
        cel = os.path.join(folder, f"{stem}.{styl}{rozsz}")
        out = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", audio, "-filter_complex", filtr, "-map", "[out]", "-ac", "1", *kodek, cel],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        if out.returncode == 0 and os.path.isfile(cel) and os.path.getsize(cel) > 0:
            log(f"glos: {os.path.basename(audio)} -> {os.path.basename(cel)} (styl: {styl})")
            return cel
        blad = (out.stderr or "").strip()[:300]
    _zdarzenie(log, slug, "uwaga", f"glos: nie udalo sie przerobic {os.path.basename(audio)} ({blad or 'ffmpeg'}) - wysylam oryginal")
    return audio


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


def zrob(slug, wideo, audio, pomysl_id=None, log=None, model=None, opcje=None, styl=None):
    """Caly obieg: rejestr -> glos w stylu (przygotuj_glos) -> (zmniejsz wideo) -> dostawca -> pobierz do folderu gotowych
    -> aktualizuj pomysl. `styl`: telefon | czysty | brak (None = ustawienie lipsync_glos_styl).
    Rzuca wyjatek przy bledzie (fabryka lapie); zwraca sciezke wyniku."""
    log = log or _log
    ust = baza.ustawienia_modelki(slug)
    dostawca = (ust.get("lipsync_dostawca") or "sync").strip().lower()
    model = model or ust.get("lipsync_model") or "lipsync-2"
    opcje = dict(ust.get("lipsync_parametry") or {}, **(opcje or {}))
    styl = (styl or ust.get("lipsync_glos_styl") or "telefon").strip().lower()
    if styl not in STYLE_GLOSU:
        raise ValueError(f"Nieznany styl glosu '{styl}' (dozwolone: {', '.join(STYLE_GLOSU)}).")
    if not os.path.isfile(wideo):
        raise FileNotFoundError(wideo)
    if not os.path.isfile(audio):
        raise FileNotFoundError(audio)
    lid = baza.dodaj_lipsync(slug, wideo, audio, dostawca, model, pomysl_id=pomysl_id)
    nazwa = _nazwa_wyniku(slug, wideo, pomysl_id)
    cel = os.path.join(baza.folder_gotowych(slug), nazwa)
    surowy = os.path.join(baza.folder_wynikow(slug), nazwa[:-4] + ".raw.mp4")   # wynik z API przed praniem
    _zdarzenie(log, slug, "info", f"lipsync #{lid}: {os.path.basename(wideo)} + {os.path.basename(audio)} ({dostawca} {model}, glos: {styl})", lipsync=lid)
    try:
        glos = przygotuj_glos(slug, audio, styl, log=log)
        if glos != audio:
            baza.aktualizuj_lipsync(slug, lid, audio_przygotowane=glos, styl=styl)
        if dostawca == "sync":
            wynik = _przez_sync(slug, wideo, glos, model, opcje, log)
        elif dostawca == "higgsfield":
            wynik = _przez_higgsfield(slug, wideo, glos, model, opcje, log)
        else:
            raise ValueError(f"nieznany lipsync_dostawca '{dostawca}' (sync | higgsfield)")
        if not wynik.get("url"):
            raise RuntimeError(wynik.get("blad") or f"brak URL wyniku (status {wynik.get('status')})")
        (sync_so if dostawca == "sync" else dostawcy.dostawca("higgsfield")).pobierz(wynik["url"], surowy)
        cel = _postprodukcja(slug, surowy, cel, ust, log)
    except Exception as e:
        baza.aktualizuj_lipsync(slug, lid, status="blad", notatki=str(e)[:1000])
        raise
    koszt = wynik.get("koszt")
    if koszt:
        baza.dopisz_wydatek(koszt, dostawca, job_id=wynik.get("job_id"))
    baza.aktualizuj_lipsync(slug, lid, status="gotowe", plik_wynikowy=cel, job_id=wynik.get("job_id"), koszt=koszt)
    if pomysl_id:
        try:
            baza.aktualizuj_pomysl(slug, pomysl_id, lipsync_plik=cel)
        except ValueError:
            pass
    _zdarzenie(log, slug, "ok", f"lipsync #{lid}: GOTOWE -> {cel}" + (f" ({koszt} c)" if koszt else ""), lipsync=lid, plik=cel)
    return cel


def _postprodukcja(slug, surowy, cel, ust, log):
    """Jak przy rolkach: plik z API (surowy, w wyniki/) -> Media Tool (pranie: metadane jak z telefonu) -> folder gotowych.
    Bez Media Tool (ustawienie mediatool=false) albo gdy padnie: kopia surowego pliku do gotowych."""
    if ust.get("mediatool"):
        import mediatool
        if not mediatool.dostepny():
            _zdarzenie(log, slug, "uwaga", "lipsync: Media Tool nie zainstalowany - plik bez prania")
        else:
            try:
                return mediatool.pierz_wideo(surowy, os.path.dirname(cel), nazwa_wyniku=os.path.basename(cel), log=log)
            except Exception as e:
                _zdarzenie(log, slug, "uwaga", f"lipsync: Media Tool nie wyszedl ({e}) - plik bez prania")
    shutil.copy2(surowy, cel)
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
    # koszt z wyceny joba (nie z roznicy salda - reczne generacje w apce nie zjadaja limitu) + limit dzienny z rezerwa rolek w toku
    try:
        k = d.koszt(z)
    except dostawcy.BladDostawcy:
        k = None
    limit, wydano = baza.limit_dzienny("higgsfield"), baza.wydano_z_rezerwa("higgsfield")
    if limit and wydano + (k or 0) > limit or (limit and wydano >= limit):
        raise ValueError(f"lipsync ({k if k is not None else '?'} kr) przekroczylby limit dzienny Higgsfield ({wydano}/{limit} kr)")
    saldo_przed = None
    if k is None:
        try:
            saldo_przed = d.saldo()
        except dostawcy.BladDostawcy:
            pass
    w = d.generuj(z, timeout="30m", log=log)
    koszt = None
    if k is not None:
        koszt = d.koszt_joba(w, k)
    else:
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
