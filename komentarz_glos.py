# -*- coding: utf-8 -*-
"""Komentarz zza kamery dograny PO generacji (rolki z promptu, glos "tts").

Feedback usera 2026-10-07: model wideo czyta polskie ą zle ("wyględa" zamiast "wygląda"). Najpewniej: wideo robimy TYLKO z
dzwiekiem otoczenia (scenariusz.DZWIEK_BEZ_MOWY), a krotki komentarz osoby nagrywajacej dogrywamy tutaj:
  ElevenLabs eleven_v3 (poprawna polszczyzna, tag [whispers]) -> glos "z telefonu zza kamery" (pasmo mikrofonu, krotkie odbicia)
  -> glosnosc dobrana do glosnosci otoczenia (ebur128) -> wejscie w sekundzie reakcji (komentarz_t) -> otoczenie lekko przycisza sie
  pod glosem (sidechaincompress) -> nowy plik wideo (obraz kopiowany 1:1).

3.1 (feedback usera: "mowi nie ta osoba" i zla polszczyzna): model wideo NIGDY nie mowi komentarza - glos "auto" to zawsze "tts".
Komentarz mowi osoba NAGRYWAJACA zza kamery (ustawienie persony `nagrywa`: chlopak / dziewczyna). Glos: Voice ID z ustawien
(`glos_chlopak` / `glos_dziewczyna`) > GLOSY_DOMYSLNE (tu: Max / Jessica) > zapas, gdy ID nie dziala: dobor z konta ElevenLabs -
TYLKO kategoria premade/professional, jezyk polski, plec zgodna z `nagrywa`; NIGDY glosy sklonowane (cloned - to klony person i
testy) ani o imieniu persony. Brzmienie: wyraznie nagrane telefonem, ktory filmuje (lancuch_telefonu). Tylko rolki z promptu -
w character swap nic nie dogrywamy.
Brak/zly klucz ElevenLabs = rolka bez komentarza (tylko otoczenie) + wpis w dzienniku; "Dograj glos" w panelu /
`fabryka.py dograj-glos`. Nic tutaj nie wysyla rolki drugi raz i nie wydaje kredytow Higgsfield - tylko znaki ElevenLabs (~40).
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
# Domyslne glosy osoby nagrywajacej (ElevenLabs Voice ID) dla wszystkich person - wybrane przez usera z probek 2026-10-07:
# chlopak = Max, dziewczyna = Jessica (jeszcze do potwierdzenia). Persona moze je nadpisac (Ustawienia -> Stroje i glos).
# Gdy ID nie dziala (glos zniknal z konta itp.), zapasem jest dobor z konta (polski premade/professional tej plci).
GLOSY_DOMYSLNE = {"chlopak": "wJmRkw9W1EUa95AGkMrg", "dziewczyna": "cgSgspJ2msm6clMCkdW9"}
NAZWY_GLOSOW_DOMYSLNYCH = {"chlopak": "Max", "dziewczyna": "Jessica"}
PLEC_GLOSU = {"chlopak": "male", "dziewczyna": "female"}


class BladGlosu(Exception):
    pass


def tts_dostepne():
    """(True, komunikat) gdy klucz ElevenLabs wyglada dobrze i dziala (sprawdzenie bez kosztu, cache 10 min)."""
    stan, kom = elevenlabs.stan_klucza()
    return stan == "ok", kom


def rozstrzygnij_glos(glos):
    """3.1: zawsze 'tts' ('auto' i stare 'model' tez) - model wideo nigdy nie mowi; bez dzialajacego ElevenLabs rolka wychodzi
    bez komentarza (nie wraca do mowy z modelu)."""
    return "tts"


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


# Brzmienie "nagrane telefonem, ktory filmuje" (user 2026-10-07: wyraznie mikrofon smartfona, osoba szepcze tuz przy telefonie,
# naturalnie - nie lektor, nie radio, nie telefon stacjonarny): mocno przyciete doly i gora, lekki nacisk 2,5-3,5 kHz (charakter
# malego mikrofonu MEMS), kompresja jak automatyka glosnosci telefonu, krotkie odbicia, bardzo cichy szum toru mikrofonu.
TELEFON_DOLY_HZ = 250            # highpass x2 (stromo) - maly mikrofon nie lapie basu, a szept tuz przy nim nie dudni
TELEFON_GORA_HZ = 6800           # lowpass x2 - gora jak z kompresji telefonu (nie 3,4 kHz jak telefon stacjonarny)
TELEFON_OBECNOSC = "equalizer=f=3000:t=q:w=1.1:g=4"     # nacisk ~2,5-3,5 kHz
TELEFON_AGC = "acompressor=threshold=0.1:ratio=4:attack=4:release=180:knee=4:makeup=2"   # automatyka glosnosci telefonu
TELEFON_ODBICIA = "aecho=0.85:0.3:9|17:0.14|0.07"      # krotkie odbicia (otoczenie bliskie, nie pogłos sali)
TELEFON_SZUM = 0.0018            # amplituda szumu toru mikrofonu (anoisesrc, ok. -60 dBFS) - slychac tylko w ciszy


def lancuch_telefonu(lufs):
    """Filtr glosu (mono) -> brzmienie mikrofonu telefonu, ktory filmuje + glosnosc docelowa (LUFS). Przed kompresja glos jest
    wyrownany do -20 LUFS (szept z TTS bywa bardzo cichy - AGC telefonu i tak go podciaga)."""
    return (f"aresample=48000,aformat=channel_layouts=mono,highpass=f={TELEFON_DOLY_HZ},highpass=f={TELEFON_DOLY_HZ},"
            f"lowpass=f={TELEFON_GORA_HZ},lowpass=f={TELEFON_GORA_HZ},loudnorm=I=-20:TP=-2:LRA=11,aresample=48000,"
            f"{TELEFON_OBECNOSC},{TELEFON_AGC},{TELEFON_ODBICIA},loudnorm=I={lufs:.1f}:TP=-3:LRA=7,aresample=48000")


def filtr_miksu(t_s, lufs, wejscie_otoczenia="0:a"):
    """filter_complex: glos (wejscie 1) jak nagrany telefonem zza kamery, wchodzi w sekundzie t_s; otoczenie lekko sie przycisza
    pod nim; pod calosc bardzo cichy szum toru mikrofonu (anoisesrc - slyszalny tylko, gdy otoczenie jest ciche)."""
    ms = max(0, int(round(float(t_s or 0) * 1000)))
    return (f"[1:a]{lancuch_telefonu(lufs)},pan=stereo|c0=c0|c1=c0,"
            f"adelay={ms}|{ms},apad,asplit=2[g1][g2];"
            f"[{wejscie_otoczenia}]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a];"
            f"anoisesrc=color=pink:amplitude={TELEFON_SZUM}:sample_rate=48000,highpass=f=200,lowpass=f=6000,"
            f"pan=stereo|c0=c0|c1=c0,aformat=sample_fmts=fltp[szum];"
            f"[a][g1]sidechaincompress=threshold=0.02:ratio=3:attack=20:release=400[ad];"
            f"[ad][g2][szum]amix=inputs=3:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95[out]")


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


def probka(glos, cel, t_s=0.5, lufs=GLOSNOSC_DOMYSLNA, otoczenie="cisza", ogon_s=1.2):
    """Demo brzmienia (0 kr, bez TTS): gotowy plik glosu przez TEN SAM miks co w rolce (filtr_miksu), otoczenie = cisza
    (`anullsrc`) albo bardzo cichy szum ("szum"), glos wchodzi w t_s. Zapis mp3/wav wg rozszerzenia `cel`. Zwraca `cel`."""
    ffmpeg = _ffmpeg()
    dl = (czas_wideo(glos) or 3.0) + float(t_s or 0) + ogon_s
    tlo = "anullsrc=r=48000:cl=stereo" if otoczenie == "cisza" else "anoisesrc=color=brown:amplitude=0.004:sample_rate=48000"
    kodek = ["-c:a", "libmp3lame", "-b:a", "192k"] if cel.lower().endswith(".mp3") else ["-c:a", "pcm_s16le"]
    cmd = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-t", f"{dl:.2f}", "-i", tlo, "-i", glos,
           "-filter_complex", filtr_miksu(t_s, lufs, "0:a"), "-map", "[out]", *kodek, cel]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if out.returncode != 0 or not os.path.isfile(cel):
        raise BladGlosu(f"ffmpeg (probka glosu): {(out.stderr or '').strip()[-300:]}")
    return cel


def kto_nagrywa(slug, nagrywa=None):
    """'chlopak' | 'dziewczyna': podany (z rolki) albo ustawienie persony `nagrywa` (domyslnie chlopak)."""
    if nagrywa in PLEC_GLOSU:
        return nagrywa
    n = baza.ustawienia_modelki(slug).get("nagrywa")
    return n if n in PLEC_GLOSU else "chlopak"


def imiona_person():
    """Imiona i slugi WSZYSTKICH person - glos o takiej nazwie to klon persony, nie osoba nagrywajaca."""
    imiona = set()
    for s in baza.lista_modelek():
        imiona.add(s)
        try:
            imiona.add(str(baza.profil_modelki(s).get("nazwa") or "").strip())
        except (OSError, ValueError):
            pass
    return sorted(i for i in imiona if i)


def glosy_ustawione(slug, nagrywa=None):
    """Voice ID do proby po kolei (bez powtorzen): ustawienie persony glos_<nagrywa>, potem GLOSY_DOMYSLNE[nagrywa]."""
    kto = kto_nagrywa(slug, nagrywa)
    wynik = []
    for vid in ((baza.ustawienia_modelki(slug).get(f"glos_{kto}") or "").strip(), (GLOSY_DOMYSLNE.get(kto) or "").strip()):
        if vid and vid not in wynik:
            wynik.append(vid)
    return wynik


def glos_z_konta(slug, nagrywa=None):
    """Zapas: glos dobrany z konta ElevenLabs (tylko premade/professional, polski, plec zgodna z `nagrywa`; nigdy cloned ani o
    imieniu persony). Rzuca BladGlosu."""
    kto = kto_nagrywa(slug, nagrywa)
    try:
        lista = elevenlabs.glosy()
    except BladDostawcy as e:
        raise BladGlosu(f"nie moge pobrac listy glosow ElevenLabs ({e}) - wpisz Voice ID w Ustawienia -> Stroje i glos")
    v = elevenlabs.wybierz_glos(lista, pomin_nazwy=imiona_person() + [slug], plec=PLEC_GLOSU[kto])
    if not v:
        osoba = "meskiego" if kto == "chlopak" else "kobiecego"
        raise BladGlosu(f"na koncie ElevenLabs nie ma polskiego {osoba} glosu (gotowy albo z Voice Library; sklonowanych nie "
                        f"uzywam) - dodaj taki glos albo wpisz Voice ID w Ustawienia -> Stroje i glos")
    return v["voice_id"]


def glos_id(slug, nagrywa=None):
    """Voice ID osoby nagrywajacej: ustawienie persony glos_<nagrywa> > GLOSY_DOMYSLNE[nagrywa] (Max / Jessica) > dobor z konta."""
    ustawione = glosy_ustawione(slug, nagrywa)
    return ustawione[0] if ustawione else glos_z_konta(slug, nagrywa)


def _glos_nie_dziala(e):
    """Blad TTS, przy ktorym warto sprobowac innego glosu (glos zniknal z konta / zle ID), a nie np. zly klucz."""
    t = str(e).lower()
    return "voice" in t or "glos" in t or bool(re.search(r"elevenlabs (400|404|422)\b", t))


def tts_osoby(slug, tekst, mp3, nagrywa=None, log=None):
    """TTS komentarza: po kolei glosy ustawione (persona, domyslny), a gdy ID nie dziala - glos dobrany z konta (zapas).
    Zwraca voice_id, ktorym nagrano. Rzuca BladDostawcy/BladGlosu (np. zly klucz - wtedy bez dalszych prob)."""
    ostatni = None
    for vid in glosy_ustawione(slug, nagrywa):
        try:
            elevenlabs.tts(tekst, vid, mp3)
            return vid
        except BladDostawcy as e:
            if not _glos_nie_dziala(e):
                raise
            ostatni = e
            if log:
                log(f"glos {vid} nie dziala ({str(e)[:120]}) - probuje nastepnego")
    try:
        vid = glos_z_konta(slug, nagrywa)
    except BladGlosu as e:
        raise BladGlosu(f"ustawiony glos nie dziala ({ostatni}) i {e}" if ostatni else str(e))
    elevenlabs.tts(tekst, vid, mp3)
    return vid


def dograj(slug, pid, wideo, komentarz, t_s, log=None):
    """TTS + miks: zwraca sciezke NOWEGO pliku (modelki/<slug>/wyniki/NNN_<nazwa>.glos.mp4). Rzuca BladGlosu/BladDostawcy.
    Mowi osoba nagrywajaca z rolki (z_promptu.nagrywa) albo z ustawien persony."""
    tekst = tekst_dla_tts(komentarz)
    if not tekst:
        raise BladGlosu("rolka nie ma komentarza do dogrania")
    ok, kom = tts_dostepne()
    if not ok:
        raise BladGlosu(kom)
    try:
        nagrywa = (baza.pomysl(slug, int(pid)).get("z_promptu") or {}).get("nagrywa")
    except (ValueError, TypeError):
        nagrywa = None
    folder = os.path.join(baza.folder_audio(slug), "_komentarze")
    os.makedirs(folder, exist_ok=True)
    mp3 = os.path.join(folder, f"{int(pid):03d}_komentarz.mp3")
    tts_osoby(slug, tekst, mp3, nagrywa, log=log)
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
