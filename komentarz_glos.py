# -*- coding: utf-8 -*-
"""Komentarz zza kamery dograny PO generacji (rolki z promptu, glos "tts").

Feedback usera 2026-10-07: model wideo czyta polskie ą zle ("wyględa" zamiast "wygląda"). Najpewniej: wideo robimy TYLKO z
dzwiekiem otoczenia (scenariusz.DZWIEK_BEZ_MOWY), a krotki komentarz osoby nagrywajacej dogrywamy tutaj:
  ElevenLabs eleven_v3 (poprawna polszczyzna) -> glos "z telefonu zza kamery" -> wejscie w sekundzie reakcji (komentarz_t) ->
  nowy plik wideo (obraz kopiowany 1:1).

3.1 (feedback usera: "mowi nie ta osoba" i zla polszczyzna): model wideo NIGDY nie mowi komentarza - glos "auto" to zawsze "tts".
Komentarz mowi osoba NAGRYWAJACA zza kamery (ustawienie persony `nagrywa`: chlopak / dziewczyna). Glos: Voice ID z ustawien
(`glos_chlopak` / `glos_dziewczyna`) > GLOSY_DOMYSLNE (tu: Max / Jessica) > zapas, gdy ID nie dziala: dobor z konta ElevenLabs -
TYLKO kategoria premade/professional, jezyk polski, plec zgodna z `nagrywa`; NIGDY glosy sklonowane (cloned - to klony person i
testy) ani o imieniu persony. Tylko rolki z promptu - w character swap nic nie dogrywamy.

3.6 (user 2026-10-10: "glos brzmi studyjnie", "kroki za glosno jak na odleglosc") - glos jak prawdziwy ziomek z telefonem:
  * BEZ przyciszania otoczenia pod glosem (sidechain usuniety) - w prawdziwym nagraniu nic sie nie przycisza; glos tylko troche
    glosniej niz otoczenie (NAD_OTOCZENIEM_LU), lekko nierowna glosnosc (NIEROWNO), lekkie pompowanie automatyki telefonu na calosci;
  * poglos wg miejsca (PRZESTRZENIE: sklep = krotki poglos pomieszczenia, galeria/dworzec = dluzszy, ulica = prawie nic + wiatr);
  * artefakty telefonu: glos przepuszczony przez niski bitrate (Opus ~24 kb/s albo AAC ~32 kb/s: zakoduj -> zdekoduj);
  * eleven_v3 z nizsza stabilnoscia (USTAWIENIA_TTS) i tagami [laughs]/[chuckles]/[whispers]/[sighs] dopasowanymi do linii,
    rotacja glosow z puli (GLOSY_PULA, ustawienie persony `glosy_rotuj`, domyslnie tak);
  * otoczenie: ujarzmienie transjentow (szybki kompresor na pikach - jej kroki/obcasy) + lekki lowpass "z daleka" bez zabijania
    gwaru (filtr_otoczenia) - takze w rolkach bez komentarza (obrob_otoczenie).
Poprawki z uwag usera (asystent.REGULY_UWAG): "glos" = surowiej (nizszy bitrate, glos ledwo nad otoczeniem), "kroki" = mocniej.
Brak/zly klucz ElevenLabs = rolka bez komentarza (tylko otoczenie) + wpis w dzienniku; "Dograj glos" w panelu /
`fabryka.py dograj-glos`. Nic tutaj nie wysyla rolki drugi raz i nie wydaje kredytow Higgsfield - tylko znaki ElevenLabs (~40).
"""
import json
import os
import random
import re
import shutil
import subprocess

import baza
from dostawcy import BladDostawcy, elevenlabs

GLOSNOSC_MIN, GLOSNOSC_MAX = -27.0, -15.0     # LUFS komentarza (osoba zza kamery, nie lektor)
NAD_OTOCZENIEM_LU = 1.5                      # 3.6: komentarz tylko troche glosniej niz otoczenie (nie "na wierzchu")
NAD_OTOCZENIEM_SUROWO_LU = 0.5               # poprawka "glos" z uwag usera: jeszcze mniej "na wierzchu"
GLOSNOSC_DOMYSLNA = -21.0                    # gdy nie da sie zmierzyc otoczenia
# Domyslne glosy osoby nagrywajacej (ElevenLabs Voice ID) dla wszystkich person - wybrane przez usera z probek 2026-10-07:
# chlopak = Max, dziewczyna = Jessica. Persona moze je nadpisac (Ustawienia -> Stroje i glos).
# Gdy ID nie dziala (glos zniknal z konta itp.), zapasem jest dobor z konta (polski premade/professional tej plci).
GLOSY_DOMYSLNE = {"chlopak": "wJmRkw9W1EUa95AGkMrg", "dziewczyna": "cgSgspJ2msm6clMCkdW9"}
NAZWY_GLOSOW_DOMYSLNYCH = {"chlopak": "Max", "dziewczyna": "Jessica"}
# 3.6: rotacja glosow (ustawienie persony `glosy_rotuj`, domyslnie tak) - zeby nie bylo zawsze tego samego. Meskie polskie glosy z
# probek usera 2026-10-07 (Max domyslny, Kris, Wiktor); dziewczyna na razie tylko Jessica.
GLOSY_PULA = {"chlopak": ["wJmRkw9W1EUa95AGkMrg", "jnAzri3VrjEtIf7MMQ4d", "Mmjvne5i15kUnfr4fQF3"],
              "dziewczyna": ["cgSgspJ2msm6clMCkdW9"]}
NAZWY_GLOSOW = {"wJmRkw9W1EUa95AGkMrg": "Max", "jnAzri3VrjEtIf7MMQ4d": "Kris", "Mmjvne5i15kUnfr4fQF3": "Wiktor",
                "cgSgspJ2msm6clMCkdW9": "Jessica"}
PLEC_GLOSU = {"chlopak": "male", "dziewczyna": "female"}
# eleven_v3: stabilnosc przyjmuje tylko 0.0 (Creative), 0.5 (Natural, domyslna), 1.0 (Robust) - nizej = naturalniej, bardziej
# emocjonalnie (user chcial ~0.3 -> najblizsza nizsza dozwolona to 0.0). Gdy API odrzuci ustawienia - druga proba bez nich.
USTAWIENIA_TTS = {"stability": 0.0}


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


# ---------------- tekst dla eleven_v3: tagi dopasowane do linii (3.6) ----------------

TAGI_V3 = ("[whispers]", "[laughs]", "[chuckles]", "[sighs]")
_SMIECH = re.compile(r"\b(?:ha){2,}h?\b|\bhehe\w*|\bhihi\w*", re.I)
_PRZEKLENSTWA = re.compile(r"kurw|pierdol|jaja|cyrk|pokemon|halloween|cosplay|wariat|przebier|kosmos", re.I)


def tag_v3(komentarz, los=None):
    """Tag eleven_v3 pasujacy do linii: smiech ("hahaha") -> [laughs]; przeklenstwa/drwina -> [chuckles]/[sighs]/[whispers];
    okrzyk ("nagrywaj!") -> bez szeptu; pytanie -> zwykle [whispers]; reszta losowo. '' = bez tagu."""
    los = los or random.Random()
    t = (komentarz or "").lower()
    if _SMIECH.search(t):
        return "[laughs]"
    if _PRZEKLENSTWA.search(t):
        return los.choice(["[chuckles]", "[chuckles]", "[sighs]", "[whispers]"])
    if t.rstrip(" .…").endswith("!"):
        return los.choice(["", "[chuckles]"])
    if "?" in t:
        return los.choice(["[whispers]", "[whispers]", "[chuckles]", ""])
    return los.choice(["[whispers]", "[whispers]", "[sighs]", "[chuckles]"])


def tekst_dla_tts(komentarz, los=None):
    """Komentarz -> tekst dla eleven_v3 z tagiem (tagi nie sa czytane na glos). [laughs] stoi tuz przed "hahaha"."""
    k = re.sub(r"\[[^\]]*\]", "", komentarz or "").strip()
    if not k:
        return ""
    tag = tag_v3(k, los)
    if tag == "[laughs]":
        m = _SMIECH.search(k)
        return re.sub(r"\s+", " ", f"{k[:m.start()]}[laughs] {k[m.start():]}").strip()
    return f"{tag} {k}".strip()


# ---------------- ffmpeg: pomiary ----------------

def _ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise BladGlosu("brak ffmpeg w PATH (winget install Gyan.FFmpeg)")
    return exe


_ENKODERY = {}


def ma_enkoder(nazwa):
    """Czy ffmpeg ma enkoder (np. libopus) - raz na proces."""
    if nazwa not in _ENKODERY:
        try:
            out = subprocess.run([_ffmpeg(), "-hide_banner", "-encoders"], capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=60)
            _ENKODERY[nazwa] = bool(re.search(r"\s" + re.escape(nazwa) + r"\s", out.stdout or ""))
        except (BladGlosu, OSError, subprocess.SubprocessError):
            _ENKODERY[nazwa] = False
    return _ENKODERY[nazwa]


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


def docelowa_glosnosc(otoczenie_lufs, surowo=False):
    """LUFS komentarza: otoczenie + NAD_OTOCZENIEM_LU (3.6: tylko troche glosniej), w granicach GLOSNOSC_MIN..MAX."""
    if otoczenie_lufs is None:
        return GLOSNOSC_DOMYSLNA
    nad = NAD_OTOCZENIEM_SUROWO_LU if surowo else NAD_OTOCZENIEM_LU
    return max(GLOSNOSC_MIN, min(GLOSNOSC_MAX, otoczenie_lufs + nad))


def _lin(db):
    """dBFS -> amplituda liniowa w granicach progu acompressor (0.000976563..1)."""
    return max(0.001, min(1.0, 10 ** (db / 20.0)))


# ---------------- brzmienie: telefon, ktory filmuje (3.1 + 3.6) ----------------
# Mocno przyciete doly i gora, lekki nacisk 2,5-3,5 kHz (maly mikrofon MEMS), kompresja jak automatyka glosnosci telefonu, poglos
# wg miejsca, lekko nierowna glosnosc, kodek o niskim bitrate, bardzo cichy szum toru mikrofonu.
TELEFON_DOLY_HZ = 250            # highpass x2 (stromo) - maly mikrofon nie lapie basu
TELEFON_GORA_HZ = 6800           # lowpass x2 - gora jak z kompresji telefonu (nie 3,4 kHz jak telefon stacjonarny)
TELEFON_OBECNOSC = "equalizer=f=3000:t=q:w=1.1:g=4"     # nacisk ~2,5-3,5 kHz
TELEFON_AGC = "acompressor=threshold=0.1:ratio=4:attack=4:release=180:knee=4:makeup=2"   # automatyka glosnosci telefonu
TELEFON_SZUM = 0.0018            # amplituda szumu toru mikrofonu (anoisesrc, ok. -60 dBFS) - slychac tylko w ciszy
# lekko nierowna glosnosc (glowa/telefon sie ruszaja) - dwie wolne sinusoidy, +-15%
NIEROWNO = "volume='1+0.10*sin(2*PI*t*0.7)+0.05*sin(2*PI*t*2.3)':eval=frame"
BITRATE_KB = 24                  # Opus (VoIP) - jak skompresowany glos z telefonu; AAC (gdy brak libopus) +8 kb/s
BITRATE_SUROWO_KB = 16
# poglos wg miejsca: (opis, aecho in_gain:out_gain:opoznienia ms:wygaszenia)
PRZESTRZENIE = {
    "maly": ("wnętrze sklepu – krótki pogłos pomieszczenia", "aecho=0.8:0.45:13|23|37|53:0.30|0.22|0.15|0.09"),
    "hala": ("galeria / dworzec / hala – dłuższy pogłos", "aecho=0.8:0.5:29|47|71|103|149:0.30|0.24|0.18|0.12|0.07"),
    "klatka": ("klatka schodowa – twarde echo", "aecho=0.8:0.55:19|41|67|97|131:0.34|0.27|0.20|0.14|0.09"),
    "pojazd": ("tramwaj / pociąg – ciasno", "aecho=0.85:0.4:7|13|21:0.25|0.15|0.08"),
    "zewnatrz": ("ulica / plac – prawie bez pogłosu, trochę wiatru", "aecho=0.9:0.2:7:0.05"),
}
HALE = ("galeria_foodcourt", "galeria_pasaz", "dworzec", "metro", "przejscie_podziemne", "dyskont")
POJAZDY = ("tramwaj", "pociag")
WIATR_PONIZEJ_OTOCZENIA_DB = 14  # wiatr w mikrofonie na zewnatrz: tyle dB ciszej niz otoczenie


def przestrzen_miejsca(miejsce_id):
    """Typ akustyki miejsca rolki: klatka | hala | pojazd | maly (wnetrze) | zewnatrz. Nieznane = maly."""
    if miejsce_id == "klatka":
        return "klatka"
    if miejsce_id in HALE:
        return "hala"
    if miejsce_id in POJAZDY:
        return "pojazd"
    import scenariusz
    m = scenariusz.MIEJSCA.get(miejsce_id or "")
    if not m:
        return "maly"
    return "maly" if m.get("wnetrze") else "zewnatrz"


def lancuch_telefonu(lufs, przestrzen="maly", surowo=False):
    """Filtr glosu (mono) -> mikrofon telefonu, ktory filmuje + poglos miejsca + glosnosc docelowa (LUFS) + lekko nierowna
    glosnosc. Przed kompresja glos wyrownany do -20 LUFS (TTS bywa bardzo cichy - AGC telefonu i tak go podciaga)."""
    poglos = PRZESTRZENIE.get(przestrzen, PRZESTRZENIE["maly"])[1]
    dol = TELEFON_DOLY_HZ + (60 if surowo else 0)
    gora = TELEFON_GORA_HZ - (1300 if surowo else 0)
    return (f"aresample=48000,aformat=channel_layouts=mono,highpass=f={dol},highpass=f={dol},lowpass=f={gora},lowpass=f={gora},"
            f"loudnorm=I=-20:TP=-2:LRA=11,aresample=48000,{TELEFON_OBECNOSC},{TELEFON_AGC},{poglos},"
            f"loudnorm=I={lufs:.1f}:TP=-3:LRA=7,aresample=48000,{NIEROWNO}")


def kodek_telefonu(surowo=False):
    """(argumenty ffmpeg, rozszerzenie) - glos zakodowany niskim bitrate jak z telefonu/IG (Opus VoIP albo AAC)."""
    kb = BITRATE_SUROWO_KB if surowo else BITRATE_KB
    if ma_enkoder("libopus"):
        return ["-c:a", "libopus", "-b:a", f"{kb}k", "-application", "voip"], ".ogg"
    return ["-c:a", "aac", "-b:a", f"{kb + 8}k"], ".m4a"


def komenda_glosu(glos, cel_bez_rozsz, lufs, przestrzen="maly", surowo=False):
    """(komenda ffmpeg, plik wyjsciowy): krok 1 - glos przez lancuch telefonu i kodek o niskim bitrate (dekoduje go krok 2)."""
    kodek, rozsz = kodek_telefonu(surowo)
    cel = cel_bez_rozsz + rozsz
    return ([_ffmpeg(), "-v", "error", "-y", "-i", glos, "-af", lancuch_telefonu(lufs, przestrzen, surowo), "-ac", "1",
             "-ar", "48000", *kodek, cel], cel)


def przygotuj_glos(glos, cel_bez_rozsz, lufs, przestrzen="maly", surowo=False):
    """Krok 1 miksu: glos jak nagrany telefonem (z kodekiem) -> plik tymczasowy. Zwraca jego sciezke. Rzuca BladGlosu."""
    cmd, cel = komenda_glosu(glos, cel_bez_rozsz, lufs, przestrzen, surowo)
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if out.returncode != 0 or not os.path.isfile(cel) or os.path.getsize(cel) == 0:
        raise BladGlosu(f"ffmpeg (glos telefonu): {(out.stderr or '').strip()[-300:]}")
    return cel


def filtr_otoczenia(otoczenie_lufs, mocniej=False):
    """3.6 (kroki/buty za glosno): szybki kompresor na PIKACH otoczenia (prog wzgledem jego glosnosci - gwar zostaje, wystajace
    stukniecia obcasow sie chowaja) + lagodny lowpass 6 dB/okt. "z daleka". mocniej = poprawka "kroki" z uwag usera."""
    if otoczenie_lufs is None:
        return "anull"
    prog = _lin(otoczenie_lufs + (6 if mocniej else 9))
    # makeup ~ +2 dB: gwar zostaje tak glosny jak przed obrobka (chowaja sie tylko wystajace piki)
    return (f"acompressor=threshold={prog:.5f}:ratio={10 if mocniej else 6}:attack=0.1:release=60:knee=2:detection=peak:"
            f"makeup={1.35 if mocniej else 1.25},lowpass=f={5200 if mocniej else 6500}:p=1")


def agc_calosci(otoczenie_lufs):
    """Lekkie pompowanie automatyki glosnosci telefonu na CALYM nagraniu (glos i otoczenie razem - nie sidechain)."""
    prog = _lin((otoczenie_lufs if otoczenie_lufs is not None else -30.0) + 4)
    return f"acompressor=threshold={prog:.5f}:ratio=2.2:attack=12:release=380:knee=4:makeup=1"


def filtr_miksu(t_s, wejscie_otoczenia="0:a", otoczenie_lufs=None, przestrzen="maly", kroki_mocniej=False,
                wejscie_glosu="1:a"):
    """filter_complex kroku 2: glos (juz przez telefon i kodek) wchodzi w sekundzie t_s, otoczenie z ujarzmionymi pikami (bez
    przyciszania pod glosem), szum toru mikrofonu, na zewnatrz wiatr, automatyka glosnosci na calosci, limiter."""
    ms = max(0, int(round(float(t_s or 0) * 1000)))
    czesci = [f"[{wejscie_glosu}]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,pan=stereo|c0=c0|c1=c0,"
              f"adelay={ms}|{ms},apad[g]",
              f"[{wejscie_otoczenia}]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
              f"{filtr_otoczenia(otoczenie_lufs, kroki_mocniej)}[a]",
              f"anoisesrc=color=pink:amplitude={TELEFON_SZUM}:sample_rate=48000,highpass=f=200,lowpass=f=6000,"
              f"pan=stereo|c0=c0|c1=c0,aformat=sample_fmts=fltp[szum]"]
    wejscia = "[a][g][szum]"
    if przestrzen == "zewnatrz":
        wiatr = _lin((otoczenie_lufs if otoczenie_lufs is not None else -30.0) - WIATR_PONIZEJ_OTOCZENIA_DB)
        czesci.append(f"anoisesrc=color=brown:amplitude={wiatr:.5f}:sample_rate=48000,lowpass=f=350,highpass=f=30,"
                      f"tremolo=f=0.35:d=0.7,pan=stereo|c0=c0|c1=c0,aformat=sample_fmts=fltp[wiatr]")
        wejscia += "[wiatr]"
    n = wejscia.count("[")
    czesci.append(f"{wejscia}amix=inputs={n}:duration=first:dropout_transition=0:normalize=0,{agc_calosci(otoczenie_lufs)},"
                  f"alimiter=limit=0.95[out]")
    return ";".join(czesci)


def _usun(plik):
    try:
        os.remove(plik)
    except OSError:
        pass


def zmiksuj(wideo, glos, cel, t_s, przestrzen="maly", surowo=False, kroki_mocniej=False):
    """Wideo + nagrany komentarz -> `cel` (obraz 1:1, audio AAC). Zwraca (cel, glosnosc otoczenia, glosnosc komentarza)."""
    ffmpeg = _ffmpeg()
    dzwiek = ma_dzwiek(wideo)
    otoczenie = glosnosc_lufs(wideo) if dzwiek else None
    lufs = docelowa_glosnosc(otoczenie, surowo)
    tel = przygotuj_glos(glos, cel + ".glos_tel", lufs, przestrzen, surowo)
    tmp = cel + ".tmp.mp4"
    try:
        cmd = [ffmpeg, "-v", "error", "-y", "-i", wideo, "-i", tel]
        wej = "0:a"
        if not dzwiek:
            dl = czas_wideo(wideo) or 15
            cmd += ["-f", "lavfi", "-t", f"{dl:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
            wej = "2:a"
        cmd += ["-filter_complex", filtr_miksu(t_s, wej, otoczenie, przestrzen, kroki_mocniej), "-map", "0:v:0", "-map", "[out]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", tmp]
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        if out.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
            _usun(tmp)
            raise BladGlosu(f"ffmpeg (miks komentarza): {(out.stderr or '').strip()[-300:]}")
        os.replace(tmp, cel)
    finally:
        _usun(tel)
    return cel, otoczenie, lufs


def obrob_otoczenie(wideo, cel, mocniej=False):
    """Rolka bez komentarza (3.6): samo ujarzmienie krokow w otoczeniu (filtr_otoczenia) -> `cel` (obraz 1:1). Zwraca (cel,
    glosnosc otoczenia) albo None, gdy nie ma czego obrabiac (brak dzwieku / cisza). Rzuca BladGlosu."""
    ffmpeg = _ffmpeg()
    if not ma_dzwiek(wideo):
        return None
    otoczenie = glosnosc_lufs(wideo)
    if otoczenie is None:
        return None
    tmp = cel + ".tmp.mp4"
    cmd = [ffmpeg, "-v", "error", "-y", "-i", wideo, "-af", f"aresample=48000,{filtr_otoczenia(otoczenie, mocniej)}",
           "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", tmp]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    if out.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
        _usun(tmp)
        raise BladGlosu(f"ffmpeg (otoczenie): {(out.stderr or '').strip()[-300:]}")
    os.replace(tmp, cel)
    return cel, otoczenie


def probka(glos, cel, t_s=0.5, lufs=None, otoczenie="cisza", ogon_s=1.2, przestrzen="maly", surowo=False,
           kroki_mocniej=False):
    """Demo brzmienia (0 kr, bez TTS): gotowy plik glosu przez TEN SAM miks co w rolce. otoczenie = "cisza" (anullsrc),
    "szum" (bardzo cichy szum) albo SCIEZKA pliku (np. surowa rolka - jej dzwiek otoczenia, cala dlugosc). Glos wchodzi w t_s.
    Zapis mp3/wav wg rozszerzenia `cel` (samo audio). Zwraca `cel`."""
    ffmpeg = _ffmpeg()
    plik_otoczenia = otoczenie if otoczenie not in ("cisza", "szum") and os.path.isfile(str(otoczenie)) else None
    L = glosnosc_lufs(plik_otoczenia) if plik_otoczenia else None
    if lufs is None:
        lufs = docelowa_glosnosc(L, surowo)
    kodek = ["-c:a", "libmp3lame", "-b:a", "192k"] if cel.lower().endswith(".mp3") else ["-c:a", "pcm_s16le"]
    tel = przygotuj_glos(glos, cel + ".glos_tel", lufs, przestrzen, surowo)
    try:
        if plik_otoczenia:
            wejscie = ["-i", plik_otoczenia]
        else:
            dl = (czas_wideo(glos) or 3.0) + float(t_s or 0) + ogon_s
            tlo = "anullsrc=r=48000:cl=stereo" if otoczenie == "cisza" else "anoisesrc=color=brown:amplitude=0.004:sample_rate=48000"
            wejscie = ["-f", "lavfi", "-t", f"{dl:.2f}", "-i", tlo]
        cmd = [ffmpeg, "-v", "error", "-y", *wejscie, "-i", tel,
               "-filter_complex", filtr_miksu(t_s, "0:a", L, przestrzen, kroki_mocniej), "-map", "[out]", *kodek, cel]
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        if out.returncode != 0 or not os.path.isfile(cel):
            raise BladGlosu(f"ffmpeg (probka glosu): {(out.stderr or '').strip()[-300:]}")
    finally:
        _usun(tel)
    return cel


# ---------------- kto mowi i jakim glosem ----------------

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


def rotuj_glosy(slug):
    """Ustawienie persony `glosy_rotuj` (3.6, domyslnie tak)."""
    v = baza.ustawienia_modelki(slug).get("glosy_rotuj")
    return True if v is None else bool(v)


def pula_glosow(slug, nagrywa=None):
    """Glosy do rotacji: ustawiony persony, domyslny i GLOSY_PULA tej osoby (bez powtorzen)."""
    kto = kto_nagrywa(slug, nagrywa)
    wynik = []
    for vid in glosy_ustawione(slug, kto) + list(GLOSY_PULA.get(kto) or []):
        if vid and vid not in wynik:
            wynik.append(vid)
    return wynik


def glosy_do_proby(slug, nagrywa=None, los=None):
    """Kolejnosc prob TTS: rotacja wl. = losowy glos z puli pierwszy, potem reszta puli; wyl. = ustawiony, domyslny."""
    if not rotuj_glosy(slug):
        return glosy_ustawione(slug, nagrywa)
    pula = pula_glosow(slug, nagrywa)
    if not pula:
        return []
    pierwszy = (los or random.Random()).choice(pula)
    return [pierwszy] + [v for v in pula if v != pierwszy]


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


def _tts(tekst, vid, mp3):
    """eleven_v3 z nizsza stabilnoscia (USTAWIENIA_TTS); gdy API odrzuci same ustawienia (400/422 o stability/voice_settings) -
    druga proba bez nich (odrzucone zapytanie nie zjada znakow)."""
    try:
        return elevenlabs.tts(tekst, vid, mp3, ustawienia=USTAWIENIA_TTS)
    except BladDostawcy as e:
        if re.search(r"stabil|voice_settings|voice settings|ttd", str(e).lower()):
            return elevenlabs.tts(tekst, vid, mp3)
        raise


def tts_osoby(slug, tekst, mp3, nagrywa=None, log=None, los=None):
    """TTS komentarza: po kolei glosy z rotacji (3.6) albo ustawione (persona, domyslny), a gdy ID nie dziala - glos dobrany z
    konta (zapas). Zwraca voice_id, ktorym nagrano. Rzuca BladDostawcy/BladGlosu (np. zly klucz - wtedy bez dalszych prob)."""
    ostatni = None
    for vid in glosy_do_proby(slug, nagrywa, los):
        try:
            _tts(tekst, vid, mp3)
            return vid
        except BladDostawcy as e:
            if not _glos_nie_dziala(e):
                raise
            ostatni = e
            if log:
                log(f"glos {NAZWY_GLOSOW.get(vid, vid)} nie dziala ({str(e)[:120]}) - probuje nastepnego")
    try:
        vid = glos_z_konta(slug, nagrywa)
    except BladGlosu as e:
        raise BladGlosu(f"ustawiony glos nie dziala ({ostatni}) i {e}" if ostatni else str(e))
    _tts(tekst, vid, mp3)
    return vid


def poprawki_miksu(slug, p):
    """Poprawki z uwag usera wazne dla miksu ("glos", "kroki"): zamrozone w rolce + aktualne (asystent pamieta)."""
    zp = (p or {}).get("z_promptu") or {}
    wynik = set(((zp.get("ustalone") or {}).get("poprawki")) or [])
    try:
        import asystent
        wynik |= set(asystent.poprawki_dla(slug))
    except Exception:           # zly plik uwag nie psuje dogrywania
        pass
    return wynik


def dograj(slug, pid, wideo, komentarz, t_s, log=None):
    """TTS + miks: zwraca sciezke NOWEGO pliku (modelki/<slug>/wyniki/NNN_<nazwa>.glos.mp4). Rzuca BladGlosu/BladDostawcy.
    Mowi osoba nagrywajaca z rolki (z_promptu.nagrywa) albo z ustawien persony; poglos wg miejsca rolki; glos i tag losowane
    z ziarnem rolki (ponowne "Dograj glos" = ten sam glos i tag)."""
    try:
        p = baza.pomysl(slug, int(pid))
    except (ValueError, TypeError):
        p = {}
    zp = p.get("z_promptu") or {}
    los = random.Random(f"{slug}-{pid}-{komentarz}")
    tekst = tekst_dla_tts(komentarz, los)
    if not tekst:
        raise BladGlosu("rolka nie ma komentarza do dogrania")
    ok, kom = tts_dostepne()
    if not ok:
        raise BladGlosu(kom)
    poprawki = poprawki_miksu(slug, p)
    przestrzen = przestrzen_miejsca(zp.get("miejsce"))
    folder = os.path.join(baza.folder_audio(slug), "_komentarze")
    os.makedirs(folder, exist_ok=True)
    mp3 = os.path.join(folder, f"{int(pid):03d}_komentarz.mp3")
    vid = tts_osoby(slug, tekst, mp3, zp.get("nagrywa"), log=log, los=los)
    stem = os.path.basename(wideo)
    for koncowka in (".raw.mp4", ".mp4", ".mov", ".webm"):
        if stem.lower().endswith(koncowka):
            stem = stem[: -len(koncowka)]
            break
    cel = os.path.join(os.path.dirname(wideo), f"{stem}.glos.mp4")
    cel, otoczenie, lufs = zmiksuj(wideo, mp3, cel, t_s, przestrzen, surowo="glos" in poprawki,
                                   kroki_mocniej="kroki" in poprawki)
    if p:
        try:
            baza.aktualizuj_pomysl(slug, int(pid), glos_id=vid, glos_tekst=tekst, glos_przestrzen=przestrzen)
        except (ValueError, OSError):
            pass
    if log:
        tag = re.search(r"\[\w+\]", tekst)
        log(f"#{pid}: komentarz ElevenLabs „{komentarz}” ({NAZWY_GLOSOW.get(vid, vid)}, {tag.group(0) if tag else 'bez tagu'}) "
            f"dograny w {float(t_s or 0):.1f} s ({PRZESTRZENIE[przestrzen][0]}; otoczenie "
            f"{otoczenie if otoczenie is not None else '?'} LUFS, glos {lufs:.0f} LUFS"
            + (", surowiej" if "glos" in poprawki else "") + f") -> {os.path.basename(cel)}")
    return cel
