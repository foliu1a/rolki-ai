# -*- coding: utf-8 -*-
"""Komentarz zza kamery dograny PO generacji (rolki z promptu, glos "tts").

Feedback usera 2026-10-07: model wideo czyta polskie ą zle ("wyględa" zamiast "wygląda"). Najpewniej: wideo robimy TYLKO z
dzwiekiem otoczenia (scenariusz.DZWIEK_BEZ_MOWY), a krotki komentarz osoby nagrywajacej dogrywamy tutaj:
  ElevenLabs eleven_v3 (poprawna polszczyzna, tag [whispers]) -> glos "z telefonu zza kamery" (pasmo mikrofonu, krotkie odbicia)
  -> glosnosc dobrana do glosnosci otoczenia (ebur128) -> wejscie w sekundzie reakcji (komentarz_t) -> otoczenie lekko przycisza sie
  pod glosem (sidechaincompress) -> nowy plik wideo (obraz kopiowany 1:1).

Brak/zly klucz ElevenLabs: rozstrzygnij_glos("auto") daje "model" (komentarz mowi model wideo, z zapisem fonetycznym ą/ę).
Nic tutaj nie wysyla rolki drugi raz i nie wydaje kredytow Higgsfield - kosztuje tylko znaki ElevenLabs (~40 na komentarz).
Blad = rolka zostaje bez komentarza (tylko otoczenie) + wpis w dzienniku; "Dograj glos" w panelu / `fabryka.py dograj-glos`.
"""
import json
import os
import re
import shutil
import subprocess

import baza
from dostawcy import BladDostawcy, elevenlabs

GLOSNOSC_MIN, GLOSNOSC_MAX = -27.0, -15.0     # LUFS komentarza (szept zza kamery, nie lektor)
NAD_OTOCZENIEM_LU = 3.0                      # komentarz o tyle glosniej niz otoczenie (osoba nagrywajaca jest najblizej)
GLOSNOSC_DOMYSLNA = -21.0                    # gdy nie da sie zmierzyc otoczenia


class BladGlosu(Exception):
    pass


def tts_dostepne():
    """(True, komunikat) gdy klucz ElevenLabs wyglada dobrze i dziala (sprawdzenie bez kosztu, cache 10 min)."""
    stan, kom = elevenlabs.stan_klucza()
    return stan == "ok", kom


def rozstrzygnij_glos(glos):
    """'auto' -> 'tts' (dobry klucz ElevenLabs) albo 'model'; inne wartosci bez zmian."""
    glos = (glos or "auto").strip()
    if glos != "auto":
        return glos
    return "tts" if tts_dostepne()[0] else "model"


def tekst_dla_tts(komentarz):
    """eleven_v3: tag [whispers] = cichy komentarz osoby, ktora nagrywa z ukrycia (tagi nie sa czytane na glos)."""
    k = re.sub(r"\[[^\]]*\]", "", komentarz or "").strip()
    return f"[whispers] {k}" if k else ""


def _ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise BladGlosu("brak ffmpeg w PATH (winget install Gyan.FFmpeg)")
    return exe


def ma_dzwiek(plik):
    """Czy plik wideo ma sciezke audio (ffprobe). Brak ffprobe = zakladamy, ze ma."""
    exe = shutil.which("ffprobe")
    if not exe:
        return True
    out = subprocess.run([exe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "json", plik],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    try:
        return bool((json.loads(out.stdout or "{}") or {}).get("streams"))
    except ValueError:
        return True


def czas_wideo(plik):
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    out = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of", "json", plik],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    try:
        return float(json.loads(out.stdout)["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        return None


def glosnosc_lufs(plik):
    """Zintegrowana glosnosc sciezki audio (ffmpeg ebur128) albo None (cisza / brak audio / blad)."""
    out = subprocess.run([_ffmpeg(), "-hide_banner", "-nostats", "-i", plik, "-vn", "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    wyniki = re.findall(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", out.stderr or "")
    if not wyniki:
        return None
    v = float(wyniki[-1])
    return None if v <= -70 else v


def docelowa_glosnosc(otoczenie_lufs):
    if otoczenie_lufs is None:
        return GLOSNOSC_DOMYSLNA
    return max(GLOSNOSC_MIN, min(GLOSNOSC_MAX, otoczenie_lufs + NAD_OTOCZENIEM_LU))


def filtr_miksu(t_s, lufs, wejscie_otoczenia="0:a"):
    """filter_complex: glos (wejscie 1) jak z telefonu zza kamery, wchodzi w sekundzie t_s; otoczenie lekko sie przycisza pod nim."""
    ms = max(0, int(round(float(t_s or 0) * 1000)))
    return (f"[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0,highpass=f=170,lowpass=f=7200,"
            f"aecho=0.8:0.25:9|17:0.16|0.09,loudnorm=I={lufs:.1f}:TP=-3:LRA=7,aresample=48000,"
            f"adelay={ms}|{ms},apad,asplit=2[g1][g2];"
            f"[{wejscie_otoczenia}]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a];"
            f"[a][g1]sidechaincompress=threshold=0.02:ratio=3:attack=20:release=400[ad];"
            f"[ad][g2]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95[out]")


def zmiksuj(wideo, glos, cel, t_s):
    """Wideo + nagrany komentarz -> `cel` (obraz 1:1, audio AAC). Zwraca (cel, glosnosc otoczenia, glosnosc komentarza)."""
    ffmpeg = _ffmpeg()
    dzwiek = ma_dzwiek(wideo)
    otoczenie = glosnosc_lufs(wideo) if dzwiek else None
    lufs = docelowa_glosnosc(otoczenie)
    cmd = [ffmpeg, "-v", "error", "-y", "-i", wideo, "-i", glos]
    wej = "0:a"
    if not dzwiek:
        dl = czas_wideo(wideo) or 15
        cmd += ["-f", "lavfi", "-t", f"{dl:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
        wej = "2:a"
    tmp = cel + ".tmp.mp4"
    cmd += ["-filter_complex", filtr_miksu(t_s, lufs, wej), "-map", "0:v:0", "-map", "[out]", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", tmp]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    if out.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise BladGlosu(f"ffmpeg (miks komentarza): {(out.stderr or '').strip()[-300:]}")
    os.replace(tmp, cel)
    return cel, otoczenie, lufs


def glos_id(slug):
    """Voice ID komentarza: ustawienie persony `z_promptu_glos` (Ustawienia) albo glos dobrany z konta ElevenLabs (polski,
    kobiecy, nie o imieniu persony). Rzuca BladGlosu, gdy nie ma z czego wybrac."""
    ust = baza.ustawienia_modelki(slug)
    vid = (ust.get("z_promptu_glos") or "").strip()
    if vid:
        return vid
    try:
        lista = elevenlabs.glosy()
    except BladDostawcy as e:
        raise BladGlosu(f"nie moge pobrac listy glosow ElevenLabs ({e}) - wpisz Voice ID w Ustawienia -> Rolka z promptu")
    imie = (baza.profil_modelki(slug).get("nazwa") or slug)
    v = elevenlabs.wybierz_glos(lista, pomin_nazwy=[imie, slug])
    if not v:
        raise BladGlosu("na koncie ElevenLabs nie ma zadnego glosu - dodaj glos (np. polski z Voice Library) albo wpisz Voice ID")
    return v["voice_id"]


def dograj(slug, pid, wideo, komentarz, t_s, log=None):
    """TTS + miks: zwraca sciezke NOWEGO pliku (modelki/<slug>/wyniki/NNN_<nazwa>.glos.mp4). Rzuca BladGlosu/BladDostawcy."""
    tekst = tekst_dla_tts(komentarz)
    if not tekst:
        raise BladGlosu("rolka nie ma komentarza do dogrania")
    ok, kom = tts_dostepne()
    if not ok:
        raise BladGlosu(kom)
    vid = glos_id(slug)
    folder = os.path.join(baza.folder_audio(slug), "_komentarze")
    os.makedirs(folder, exist_ok=True)
    mp3 = os.path.join(folder, f"{int(pid):03d}_komentarz.mp3")
    elevenlabs.tts(tekst, vid, mp3)
    stem = os.path.basename(wideo)
    for koncowka in (".raw.mp4", ".mp4", ".mov", ".webm"):
        if stem.lower().endswith(koncowka):
            stem = stem[: -len(koncowka)]
            break
    cel = os.path.join(os.path.dirname(wideo), f"{stem}.glos.mp4")
    cel, otoczenie, lufs = zmiksuj(wideo, mp3, cel, t_s)
    if log:
        log(f"#{pid}: komentarz ElevenLabs „{komentarz}” dograny w {float(t_s or 0):.1f} s "
            f"(otoczenie {otoczenie if otoczenie is not None else '?'} LUFS, glos {lufs:.0f} LUFS) -> {os.path.basename(cel)}")
    return cel
