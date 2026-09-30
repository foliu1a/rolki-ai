# -*- coding: utf-8 -*-
"""Klatki z wideo (ffmpeg/ffprobe w PATH) - zeby agent mogl obejrzec filmik zrodlowy i wynik.

    info(plik)                       -> {"czas": s, "szer": px, "wys": px, "fps": float}
    wytnij(plik, folder, ile=4)      -> [sciezki PNG]
    arkusz(plik, sciezka_jpg, ile=6) -> jedna siatka JPG z `ile` klatkami (najwygodniejsza do ogladania)
"""
import json
import os
import shutil
import subprocess


class BrakFFmpeg(Exception):
    pass


def _exe(nazwa):
    sciezka = shutil.which(nazwa)
    if not sciezka:
        raise BrakFFmpeg(f"Brak {nazwa} w PATH - zainstaluj ffmpeg (winget install Gyan.FFmpeg).")
    return sciezka


def info(plik):
    out = subprocess.run(
        [_exe("ffprobe"), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", plik],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe: {out.stderr.strip()[:300]}")
    dane = json.loads(out.stdout or "{}")
    wideo = next((s for s in dane.get("streams", []) if s.get("codec_type") == "video"), {})
    czas = float(dane.get("format", {}).get("duration") or wideo.get("duration") or 0)
    fps = 0.0
    r = wideo.get("avg_frame_rate") or wideo.get("r_frame_rate") or "0/1"
    try:
        licznik, mianownik = r.split("/")
        fps = float(licznik) / float(mianownik) if float(mianownik) else 0.0
    except (ValueError, ZeroDivisionError):
        pass
    return {
        "czas": round(czas, 2),
        "szer": int(wideo.get("width") or 0),
        "wys": int(wideo.get("height") or 0),
        "fps": round(fps, 2),
    }


def _momenty(czas, ile):
    if ile <= 1 or czas <= 0:
        return [max(czas / 2, 0)]
    # rownomiernie, z marginesem zeby nie brac czarnych pierwszych/ostatnich klatek
    start, koniec = czas * 0.04, czas * 0.96
    krok = (koniec - start) / (ile - 1)
    return [round(start + i * krok, 3) for i in range(ile)]


def wytnij(plik, folder, ile=4, wys_max=720):
    """Wycina `ile` klatek rownomiernie rozlozonych w czasie. Zwraca liste sciezek PNG."""
    os.makedirs(folder, exist_ok=True)
    czas = info(plik)["czas"]
    wyniki = []
    for i, t in enumerate(_momenty(czas, ile), 1):
        cel = os.path.join(folder, f"klatka_{i:02d}_{t:06.2f}s.png")
        subprocess.run(
            [_exe("ffmpeg"), "-v", "error", "-y", "-ss", str(t), "-i", plik,
             "-frames:v", "1", "-vf", f"scale=-2:'min({wys_max},ih)'", cel],
            capture_output=True, timeout=120,
        )
        if os.path.isfile(cel):
            wyniki.append(cel)
    return wyniki


def arkusz(plik, sciezka_jpg, ile=6, kolumny=3, szer_kafelka=360):
    """Jedna siatka JPG z `ile` klatkami - najszybszy sposob, zeby agent 'zobaczyl' caly klip."""
    os.makedirs(os.path.dirname(os.path.abspath(sciezka_jpg)), exist_ok=True)
    czas = info(plik)["czas"]
    if czas <= 0:
        raise RuntimeError("ffprobe nie podal dlugosci wideo")
    wiersze = max(1, -(-ile // kolumny))
    # fps = ile klatek na cala dlugosc; tile sklada je w siatke
    fps = ile / czas
    filtr = f"fps={fps:.6f},scale={szer_kafelka}:-2,tile={kolumny}x{wiersze}:padding=4:margin=4"
    out = subprocess.run(
        [_exe("ffmpeg"), "-v", "error", "-y", "-i", plik, "-vf", filtr,
         "-frames:v", "1", "-q:v", "3", sciezka_jpg],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )
    if out.returncode != 0 or not os.path.isfile(sciezka_jpg):
        raise RuntimeError(f"ffmpeg tile: {out.stderr.strip()[:300]}")
    return sciezka_jpg


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("uzycie: python klatki.py <plik.mp4> [folder_wyjsciowy]")
        sys.exit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + "_klatki"
    print(info(src))
    print(wytnij(src, dst))
    print(arkusz(src, os.path.join(dst, "arkusz.jpg")))
