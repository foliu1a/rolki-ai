# -*- coding: utf-8 -*-
"""Most do Media Tool (Electron, C:\\claude programy\\Media Tool) - "pranie" filmikow bez klikania w GUI.

Media Tool forkuje desktop/worker.cjs z zadaniem w argv[1] (JSON) i srodowiskiem z narzedziami.
Robimy dokladnie to samo, tylko przez ELECTRON_RUN_AS_NODE=1 (Electron jako zwykly Node, zeby
natywny sharp z paczki sie zaladowal). Worker bez parentPort drukuje komunikaty JSON na stdout.

    pierz_wideo(plik_mp4, folder_wyjsciowy) -> sciezka do IMG_0001.mp4 (iPhone 17 Pro Max meta + GPS + spoof)
"""
import json
import os
import shutil
import subprocess
import sys

MT_DIR = os.environ.get("MEDIA_TOOL_DIR") or next(
    (d for d in (r"C:\claude programy\Media Tool",  # od 2026-10-03; wczesniej lezal na pulpicie
                 os.path.join(os.path.expanduser("~"), "Desktop", "Media Tool"))
     if os.path.isfile(os.path.join(d, "Media Tool.exe"))),
    r"C:\claude programy\Media Tool",
)


class BrakMediaTool(Exception):
    pass


def _sciezki():
    exe = os.path.join(MT_DIR, "Media Tool.exe")
    app = os.path.join(MT_DIR, "resources", "app")
    worker = os.path.join(app, "desktop", "worker.cjs")
    tools = os.path.join(app, "tools")
    env = {
        "MEDIA_ASSETS_DIR": os.path.join(app, "lib", "assets"),
        "MEDIA_FFMPEG": os.path.join(tools, "ffmpeg.exe"),
        "MEDIA_FFPROBE": os.path.join(tools, "ffprobe.exe"),
        "MEDIA_EXIFTOOL": os.path.join(tools, "exiftool", "exiftool.exe"),
    }
    for p in (exe, worker, *env.values()):
        if not os.path.exists(p):
            raise BrakMediaTool(f"Media Tool niekompletny: brak {p}")
    return exe, worker, env


def dostepny():
    try:
        _sciezki()
        return True
    except BrakMediaTool:
        return False


def pierz(wejscia, folder_wyjsciowy, synthid=False, strength=0.2, gps=True, vary=True, log=None, timeout=3600):
    """Odpala worker Media Tool na liscie plikow. Zwraca (folder_z_wynikami, raport[list]).

    Wideo: spoofReel (ffmpeg, AMF jesli jest, iPhone meta + GPS). Zdjecia: tylko gdy synthid=True
    i paczka ma folder synthid/ (na tej maszynie zdjecia i tak ida przez Suczkowatke).
    """
    exe, worker, env_mt = _sciezki()
    wejscia = [os.path.abspath(w) for w in (wejscia if isinstance(wejscia, (list, tuple)) else [wejscia])]
    os.makedirs(folder_wyjsciowy, exist_ok=True)
    job = {
        "inputs": wejscia,
        "output": os.path.abspath(folder_wyjsciowy),
        "gps": bool(gps),
        "vary": bool(vary),
        "synthid": bool(synthid),
        "strength": strength,
    }
    env = dict(os.environ)
    env.update(env_mt)
    env["ELECTRON_RUN_AS_NODE"] = "1"
    if synthid:
        env["MEDIA_SYNTHID_HOME"] = os.path.join(MT_DIR, "resources", "app", "synthid")
        env["MEDIA_SYNTHID_STRENGTH"] = str(strength)

    proc = subprocess.Popen(
        [exe, worker, json.dumps(job)],
        cwd=os.path.dirname(worker),
        env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    out_dir, done, fatal = None, None, None
    try:
        for linia in proc.stdout:
            linia = linia.strip()
            if not linia.startswith("{"):
                continue
            try:
                msg = json.loads(linia)
            except json.JSONDecodeError:
                continue
            typ = msg.get("type")
            if typ == "log" and log:
                log(msg.get("text", ""))
            elif typ == "done":
                done, out_dir = msg, msg.get("outDir")
            elif typ == "fatal":
                fatal = msg.get("text", "fatal")
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"Media Tool nie skonczyl w {timeout}s")
    if fatal:
        raise RuntimeError(f"Media Tool: {fatal}")
    if not out_dir:
        err = (proc.stderr.read() or "")[-800:]
        raise RuntimeError(f"Media Tool nie zwrocil wyniku (kod {proc.returncode}). {err}")
    raport_p = os.path.join(out_dir, "raport.json")
    raport = []
    if os.path.isfile(raport_p):
        with open(raport_p, encoding="utf-8") as f:
            raport = json.load(f)
    return out_dir, raport


def pierz_wideo(plik, folder_wyjsciowy, nazwa_wyniku=None, log=None):
    """Jeden filmik -> wyprany mp4. Zwraca sciezke wyniku (przeniesiona do folder_wyjsciowy/nazwa_wyniku)."""
    tmp = os.path.join(folder_wyjsciowy, "_mediatool")
    out_dir, raport = pierz([plik], tmp, synthid=False, log=log)
    ok = [r for r in raport if r.get("status") == "ok" and r.get("output")]
    if not ok:
        bledy = "; ".join(r.get("error", "?") for r in raport if r.get("status") != "ok")
        raise RuntimeError(f"Media Tool nie wyprał {os.path.basename(plik)}: {bledy or 'brak raportu'}")
    wynik = ok[0]["output"]
    if nazwa_wyniku:
        cel = os.path.join(folder_wyjsciowy, nazwa_wyniku)
        shutil.move(wynik, cel)
        shutil.rmtree(out_dir, ignore_errors=True)
        try:
            os.rmdir(tmp)
        except OSError:
            pass
        return cel
    return wynik


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(errors="replace")
    if len(sys.argv) < 3:
        print("uzycie: python mediatool.py <plik.mp4> <folder_wyjsciowy>")
        sys.exit(1)
    print(pierz_wideo(sys.argv[1], sys.argv[2], nazwa_wyniku="test_mt.mp4", log=print))
