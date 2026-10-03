# -*- coding: utf-8 -*-
"""Telegram - telefon jako pilot fabryki (bot API, stdlib).

  - uzytkownik wysyla botowi filmik (+ ewentualnie nazwe persony w podpisie) -> plik laduje we wrzutni persony
  - fabryka odsyla gotowa rolke z podpisem, alarmy ("3 rolki z rzedu nie wyszly") i raport dnia
  - komendy: /status, /pomoc

Token bota (od @BotFather) w kluczach jako "telegram" (panel -> Konta albo TELEGRAM_BOT_TOKEN).
Parowanie: pierwszy czat, ktory napisze do bota (np. /start), zostaje CZATEM GLOWNYM (telegram.json obok stan.json):
tam ida alarmy, raporty i rolki person bez wlasnego konta. Osobne konto per persona: ustawienie `telegram_czat`
("@huy7128") - to konto musi raz napisac /start do bota (Telegram nie pozwala botom pisac pierwszym); bot paruje je,
bo jest na liscie dozwolonych (odbierz(dozwolone=...)), i od tej pory gotowe rolki tej persony leca tam.
Obce czaty sa ignorowane. Limity Telegrama: pobieranie <= 20 MB, wysylka <= 50 MB.
"""
import json
import os

import baza
import sekrety
from dostawcy import BladDostawcy, BrakKlucza
from dostawcy import http

BAZA_URL = "https://api.telegram.org"
LIMIT_POBIERANIA = 20 * 1024 * 1024
LIMIT_WYSYLKI = 50 * 1024 * 1024
ROZSZERZENIA_WIDEO = (".mp4", ".mov", ".webm", ".m4v")


def _token():
    t = sekrety.klucz("telegram")
    if not t:
        raise BrakKlucza("Brak tokena bota Telegram (panel -> Konta -> Telegram).")
    return t


def skonfigurowany():
    return bool(sekrety.klucz("telegram"))


def _url(metoda):
    return f"{BAZA_URL}/bot{_token()}/{metoda}"


def _wywolaj(metoda, dane=None, timeout=30, powtorki=1):
    try:
        odp = http.zapytanie("POST", _url(metoda), dane=dane or {}, timeout=timeout, powtorki=powtorki)
    except http.BladHTTP as e:
        raise BladDostawcy(f"Telegram {metoda}: {_opis(e)}")
    if not isinstance(odp, dict) or not odp.get("ok"):
        raise BladDostawcy(f"Telegram {metoda}: {str(odp)[:200]}")
    return odp.get("result")


def _opis(e):
    try:
        d = json.loads(e.tekst)
        return d.get("description") or e.tekst[:200]
    except (ValueError, AttributeError):
        return f"HTTP {e.status}"


# ---------------- stan (czat, offset) ----------------

def _plik_stanu():
    return os.path.join(os.path.dirname(baza.PLIK_STANU), "telegram.json")


def stan():
    s = {"chat_id": None, "offset": 0, "czat": "", "ostatni_raport": "", "czaty": {}}
    s.update(baza._wczytaj_json(_plik_stanu(), {}))
    if not isinstance(s.get("czaty"), dict):
        s["czaty"] = {}
    return s


def zapisz_stan(**pola):
    s = stan()
    s.update(pola)
    baza._zapisz_json(_plik_stanu(), s)
    return s


def sparowany():
    return bool(stan().get("chat_id"))


def rozparuj():
    zapisz_stan(chat_id=None, czat="", czaty={})


def czaty():
    """Wszystkie sparowane czaty: {"<chat_id>": {"nazwa": "huy7128", "glowny": bool}} (czat glowny tez)."""
    s = stan()
    wynik = dict(s.get("czaty") or {})
    if s.get("chat_id") and str(s["chat_id"]) not in wynik:
        wynik[str(s["chat_id"])] = {"nazwa": s.get("czat") or str(s["chat_id"])}
    for cid, info in wynik.items():
        info["glowny"] = bool(s.get("chat_id")) and str(cid) == str(s["chat_id"])
    return wynik


def _konto(konto):
    return (konto or "").strip().lstrip("@").lower()


def czat_dla(konto):
    """chat_id dla konta z ustawienia persony ("@huy7128", "huy7128" albo id liczbowe); "" = czat glowny.
    Zwraca (chat_id | None, opis) - None, gdy to konto nie napisalo jeszcze /start do bota."""
    s = stan()
    k = _konto(konto)
    if not k:
        return (s.get("chat_id") or None), (s.get("czat") or "czat glowny")
    for cid, info in czaty().items():
        if (info.get("nazwa") or "").lower() == k or str(cid) == k:
            return int(cid), info.get("nazwa") or str(cid)
    if k.lstrip("-").isdigit():
        return int(k), k      # user wpisal chat_id liczbowo - probujemy wprost
    return None, f"@{k} nie napisal jeszcze /start do bota"


def _nazwa_czatu(czat_msg):
    return czat_msg.get("username") or czat_msg.get("first_name") or str(czat_msg.get("id"))


# ---------------- wysylanie ----------------

def gotowy():
    if not skonfigurowany():
        return False, "brak tokena bota (panel -> Konta -> Telegram)"
    try:
        ja = _wywolaj("getMe")
    except BladDostawcy as e:
        return False, str(e)
    nazwa = ja.get("username") or ja.get("first_name") or "?"
    if sparowany():
        inne = [i.get("nazwa") for c, i in czaty().items() if not i.get("glowny")]
        return True, (f"bot @{nazwa}, sparowany z czatem {stan().get('czat') or stan().get('chat_id')}"
                      + (f" (+ konta person: {', '.join('@' + str(n) for n in inne)})" if inne else ""))
    return True, f"bot @{nazwa} dziala - napisz do niego /start na telefonie, zeby sparowac"


def wyslij_tekst(tekst, chat_id=None):
    cid = chat_id or stan().get("chat_id")
    if not cid:
        raise BladDostawcy("Telegram: brak sparowanego czatu (napisz /start do bota)")
    return _wywolaj("sendMessage", {"chat_id": cid, "text": str(tekst)[:4000]})


def _wyslij_plik(metoda, pole, plik, podpis="", chat_id=None):
    cid = chat_id or stan().get("chat_id")
    if not cid:
        raise BladDostawcy("Telegram: brak sparowanego czatu (napisz /start do bota)")
    if os.path.getsize(plik) > LIMIT_WYSYLKI:
        return wyslij_tekst(f"{podpis}\n(plik za duzy dla Telegrama, lezy w: {plik})".strip(), cid)
    pola = {"chat_id": str(cid)}
    if podpis:
        pola["caption"] = str(podpis)[:1000]
    try:
        odp = http.multipart(_url(metoda), pola=pola, pliki={pole: plik}, timeout=600)
    except http.BladHTTP as e:
        raise BladDostawcy(f"Telegram {metoda}: {_opis(e)}")
    if not isinstance(odp, dict) or not odp.get("ok"):
        raise BladDostawcy(f"Telegram {metoda}: {str(odp)[:200]}")
    return odp.get("result")


def wyslij_wideo(plik, podpis="", chat_id=None):
    return _wyslij_plik("sendVideo", "video", plik, podpis, chat_id)


def wyslij_zdjecie(plik, podpis="", chat_id=None):
    return _wyslij_plik("sendPhoto", "photo", plik, podpis, chat_id)


# ---------------- odbieranie ----------------

def _rozpoznaj(msg):
    """Wiadomosc Telegrama -> {"typ": wideo|audio|zdjecie|tekst, "file_id", "nazwa", "rozmiar", "tekst"}."""
    tekst = (msg.get("caption") or msg.get("text") or "").strip()
    if msg.get("video"):
        v = msg["video"]
        return {"typ": "wideo", "file_id": v.get("file_id"), "nazwa": v.get("file_name") or "", "rozmiar": v.get("file_size") or 0, "tekst": tekst}
    if msg.get("document"):
        d = msg["document"]
        nazwa = d.get("file_name") or ""
        typ = "wideo" if nazwa.lower().endswith(ROZSZERZENIA_WIDEO) else ("audio" if nazwa.lower().endswith(baza.ROZSZERZENIA_AUDIO) else "plik")
        return {"typ": typ, "file_id": d.get("file_id"), "nazwa": nazwa, "rozmiar": d.get("file_size") or 0, "tekst": tekst}
    if msg.get("audio") or msg.get("voice"):
        a = msg.get("audio") or msg.get("voice")
        nazwa = a.get("file_name") or ("glos.ogg" if msg.get("voice") else "audio.mp3")
        return {"typ": "audio", "file_id": a.get("file_id"), "nazwa": nazwa, "rozmiar": a.get("file_size") or 0, "tekst": tekst}
    if msg.get("photo"):
        najwieksze = msg["photo"][-1]
        return {"typ": "zdjecie", "file_id": najwieksze.get("file_id"), "nazwa": "zdjecie.jpg", "rozmiar": najwieksze.get("file_size") or 0, "tekst": tekst}
    return {"typ": "tekst", "file_id": None, "nazwa": "", "rozmiar": 0, "tekst": tekst}


def odbierz(dozwolone=None):
    """Nowe wiadomosci ze sparowanych czatow. Paruje: pierwszy czat, ktory napisze (= czat glowny), oraz konta z
    `dozwolone` ({"huy7128": "noemi"} - z ustawien telegram_czat person). Obce czaty sa pomijane.
    Zwraca liste slownikow z _rozpoznaj + "chat_id", "od", "glowny", "persona" (slug z dozwolonych albo None),
    "nowy" (czat wlasnie sparowany). Offset zapisuje w telegram.json."""
    s = stan()
    dozwolone = {_konto(k): v for k, v in (dozwolone or {}).items() if _konto(k)}
    wynik = _wywolaj("getUpdates", {"offset": int(s.get("offset") or 0), "timeout": 0, "allowed_updates": ["message"]}, timeout=30)
    wiadomosci = []
    offset = int(s.get("offset") or 0)
    chat_id = s.get("chat_id")
    czat = s.get("czat") or ""
    znane = dict(s.get("czaty") or {})
    for u in wynik or []:
        offset = max(offset, int(u.get("update_id", 0)) + 1)
        msg = u.get("message") or {}
        czat_msg = msg.get("chat") or {}
        cid = czat_msg.get("id")
        if cid is None:
            continue
        nazwa = _nazwa_czatu(czat_msg)
        klucze = {_konto(czat_msg.get("username")), str(cid)} - {""}
        nowy = False
        if chat_id is None:
            chat_id, czat, nowy = cid, nazwa, True          # parowanie: pierwszy czat = glowny
        elif cid != chat_id and str(cid) not in znane:
            if not (klucze & set(dozwolone)):
                continue                                    # obcy czat - ignorujemy
            nowy = True
        if str(cid) not in znane or znane[str(cid)].get("nazwa") != nazwa:
            znane[str(cid)] = {"nazwa": nazwa}
        w = _rozpoznaj(msg)
        w["chat_id"] = cid
        w["od"] = (msg.get("from") or {}).get("username") or ""
        w["glowny"] = cid == chat_id
        w["persona"] = next((dozwolone[k] for k in klucze if k in dozwolone), None)
        w["nowy"] = nowy
        wiadomosci.append(w)
    zapisz_stan(offset=offset, chat_id=chat_id, czat=czat, czaty=znane)
    return wiadomosci


def pobierz_plik(file_id, cel):
    """getFile -> sciezka na serwerze Telegrama -> pobranie do `cel`."""
    info = _wywolaj("getFile", {"file_id": file_id})
    sciezka = (info or {}).get("file_path")
    if not sciezka:
        raise BladDostawcy("Telegram getFile: brak file_path (plik ponad 20 MB?)")
    try:
        http.pobierz(f"{BAZA_URL}/file/bot{_token()}/{sciezka}", cel)
    except http.BladHTTP as e:
        raise BladDostawcy(f"Telegram pobieranie: {_opis(e)}")
    return cel
