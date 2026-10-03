# -*- coding: utf-8 -*-
"""Przerobka glosu przed lipsynciem (lipsync.przygotuj_glos, ffmpeg): styl telefon / czysty / brak, awarie, API."""
import os
import shutil
import subprocess

import pytest

import baza
import lipsync

FFMPEG = shutil.which("ffmpeg")
bez_ffmpeg_tu = pytest.mark.skipif(not FFMPEG, reason="brak ffmpeg w PATH")


def _ton(sciezka, sekundy=1.5):
    """Krotki ton testowy (mp3) - udaje nagranie glosu."""
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={sekundy}:sample_rate=44100",
                    "-c:a", "libmp3lame", "-b:a", "96k", sciezka], check=True, capture_output=True)
    return sciezka


def _czas(sciezka):
    out = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", sciezka], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


@bez_ffmpeg_tu
def test_przygotuj_glos_telefon_i_czysty(modelka):
    glos = _ton(os.path.join(baza.folder_audio(modelka), "glos.mp3"))
    tel = lipsync.przygotuj_glos(modelka, glos, "telefon")
    assert tel != glos and tel.endswith("glos.telefon.mp3") and os.path.isfile(tel)
    assert os.path.dirname(tel) == os.path.join(baza.folder_audio(modelka), "_przygotowane")
    assert abs(_czas(tel) - 1.5) < 0.3          # dlugosc bez zmian (szum konczy sie z glosem)
    czysty = lipsync.przygotuj_glos(modelka, glos, "czysty")
    assert czysty.endswith("glos.czysty.mp3") and os.path.isfile(czysty) and abs(_czas(czysty) - 1.5) < 0.3
    assert lipsync.przygotuj_glos(modelka, glos, "brak") == glos
    with pytest.raises(ValueError):
        lipsync.przygotuj_glos(modelka, glos, "dziwny")
    assert baza.USTAWIENIA_DOMYSLNE["lipsync_glos_styl"] == "telefon"


@bez_ffmpeg_tu
def test_przygotuj_glos_ogg_z_telegrama(modelka):
    ogg = os.path.join(baza.folder_audio(modelka), "glosowka.ogg")
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=1:sample_rate=48000",
                    "-c:a", "libopus", "-b:a", "32k", ogg], check=True, capture_output=True)
    tel = lipsync.przygotuj_glos(modelka, ogg, "telefon")
    assert tel.endswith("glosowka.telefon.mp3") and os.path.isfile(tel)


def test_przygotuj_glos_zepsuty_plik_oddaje_oryginal(modelka):
    zly = os.path.join(baza.folder_audio(modelka), "zly.mp3")
    open(zly, "wb").write(b"to nie jest audio")
    assert lipsync.przygotuj_glos(modelka, zly, "telefon") == zly
    assert any("nie udalo sie przerobic" in w["tekst"] or "brak ffmpeg" in w["tekst"] for w in baza.dziennik_ostatnie(5, typ="uwaga"))


def test_przygotuj_glos_bez_ffmpeg(modelka, monkeypatch):
    monkeypatch.setattr(lipsync.shutil, "which", lambda n: None)
    glos = os.path.join(baza.folder_audio(modelka), "g.mp3")
    open(glos, "wb").write(b"x")
    assert lipsync.przygotuj_glos(modelka, glos, "telefon") == glos
    assert "brak ffmpeg" in baza.dziennik_ostatnie(1, typ="uwaga")[-1]["tekst"]


def test_zrob_uzywa_przygotowanego_glosu(modelka, monkeypatch):
    """lipsync.zrob: glos przechodzi przez przygotuj_glos (styl z ustawien albo parametru) i do dostawcy idzie przerobiony plik."""
    baza.zapisz_ustawienia(modelka, lipsync_dostawca="sync")
    wideo = os.path.join(baza.folder_gotowych(modelka), "001_a.mp4"); open(wideo, "wb").write(b"v")
    audio = os.path.join(baza.folder_audio(modelka), "a.mp3"); open(audio, "wb").write(b"a")
    uzyte = []
    monkeypatch.setattr(lipsync, "przygotuj_glos", lambda slug, a, styl, log=None: uzyte.append(styl) or (a + "." + styl if styl != "brak" else a))
    wyslane = []

    def generuj(w, a, model="lipsync-2", opcje=None, log=None):
        wyslane.append(a)
        return {"job_id": "g1", "status": "COMPLETED", "url": "https://cdn/x.mp4", "sekundy": 5}
    monkeypatch.setattr(lipsync.sync_so, "generuj", generuj)
    monkeypatch.setattr(lipsync.sync_so, "pobierz", lambda url, cel: open(cel, "wb").write(b"v") and cel)
    lipsync.zrob(modelka, wideo, audio)
    assert uzyte == ["telefon"] and wyslane == [audio + ".telefon"]
    assert baza.lista_lipsync(modelka)[0]["audio_przygotowane"] == audio + ".telefon" and baza.lista_lipsync(modelka)[0]["styl"] == "telefon"
    lipsync.zrob(modelka, wideo, audio, styl="brak")
    assert uzyte[-1] == "brak" and wyslane[-1] == audio and "audio_przygotowane" not in baza.lista_lipsync(modelka)[1]
    baza.zapisz_ustawienia(modelka, lipsync_glos_styl="czysty")
    lipsync.zrob(modelka, wideo, audio)
    assert uzyte[-1] == "czysty"
    with pytest.raises(ValueError):
        lipsync.zrob(modelka, wideo, audio, styl="xxx")


def test_lipsync_przechodzi_przez_media_tool(modelka, monkeypatch):
    """Wynik z sync.so laduje w wyniki/ jako .raw.mp4, a do folderu gotowych idzie po Media Tool (gdy mediatool=true)."""
    import mediatool
    wideo = os.path.join(baza.folder_gotowych(modelka), "001_a.mp4"); open(wideo, "wb").write(b"v")
    audio = os.path.join(baza.folder_audio(modelka), "a.mp3"); open(audio, "wb").write(b"a")
    monkeypatch.setattr(lipsync, "przygotuj_glos", lambda slug, a, styl, log=None: a)
    monkeypatch.setattr(lipsync.sync_so, "generuj", lambda *a, **k: {"job_id": "g1", "status": "COMPLETED", "url": "https://cdn/x.mp4", "sekundy": 5})
    monkeypatch.setattr(lipsync.sync_so, "pobierz", lambda url, cel: open(cel, "wb").write(b"surowe") and cel)
    prane = []

    def pierz_wideo(plik, folder, nazwa_wyniku=None, log=None):
        prane.append(plik)
        cel = os.path.join(folder, nazwa_wyniku)
        open(cel, "wb").write(b"wyprane")
        return cel
    monkeypatch.setattr(mediatool, "pierz_wideo", pierz_wideo)
    baza.zapisz_ustawienia(modelka, mediatool=True)
    cel = lipsync.zrob(modelka, wideo, audio)
    assert cel == os.path.join(baza.folder_gotowych(modelka), "001_a_lipsync.mp4") and open(cel, "rb").read() == b"wyprane"
    assert prane == [os.path.join(baza.folder_wynikow(modelka), "001_a_lipsync.raw.mp4")] and os.path.isfile(prane[0])
    # Media Tool pada -> kopia surowego pliku, lipsync nadal "gotowe", ostrzezenie w dzienniku
    monkeypatch.setattr(mediatool, "pierz_wideo", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("brak Media Tool")))
    cel = lipsync.zrob(modelka, wideo, audio)
    assert open(cel, "rb").read() == b"surowe" and baza.lista_lipsync(modelka)[-1]["status"] == "gotowe"
    assert any("Media Tool nie wyszedl" in w["tekst"] for w in baza.dziennik_ostatnie(5, typ="uwaga"))
    # mediatool wylaczony -> kopia bez prania, bez ostrzezenia
    baza.zapisz_ustawienia(modelka, mediatool=False)
    ile_uwag = len(baza.dziennik_ostatnie(50, typ="uwaga"))
    assert open(lipsync.zrob(modelka, wideo, audio), "rb").read() == b"surowe"
    assert len(baza.dziennik_ostatnie(50, typ="uwaga")) == ile_uwag


def test_api_lipsync_styl(modelka, monkeypatch):
    import app as panel
    panel.konsola.__init__()
    panel.app.config["TESTING"] = True
    wideo = os.path.join(baza.folder_gotowych(modelka), "001_a.mp4"); open(wideo, "wb").write(b"v")
    audio = os.path.join(baza.folder_audio(modelka), "a.mp3"); open(audio, "wb").write(b"a")
    style = []
    monkeypatch.setattr(lipsync, "zrob", lambda slug, w, a, pomysl_id=None, log=None, model=None, opcje=None, styl=None: style.append(styl) or w)
    with panel.app.test_client() as c:
        assert c.post("/api/akcja", json={"typ": "lipsync", "wideo": wideo, "audio": audio, "styl": "czysty"}).status_code == 200
        panel.konsola.watek.join(5)
        assert c.post("/api/akcja", json={"typ": "lipsync", "wideo": wideo, "audio": audio}).status_code == 200
        panel.konsola.watek.join(5)
        assert c.post("/api/akcja", json={"typ": "lipsync", "wideo": wideo, "audio": audio, "styl": "zly"}).status_code == 400
    assert style == ["czysty", None]
