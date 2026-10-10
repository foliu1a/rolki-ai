# -*- coding: utf-8 -*-
"""Telegram - telefon jako pilot fabryki (bot API, stdlib).

  - uzytkownik wysyla botowi filmik (+ ewentualnie nazwe persony w podpisie) -> plik laduje we wrzutni persony
  - fabryka odsyla gotowa rolke z podpisem, alarmy ("3 rolki z rzedu nie wyszly") i raport dnia
  - komendy: /status, /pomoc

Token bota (od @BotFather) w kluczach jako "telegram" (panel -> Konta albo TELEGRAM_BOT_TOKEN).
Parowanie: pierwszy czat, ktory napisze do bota (np. /start), zostaje CZATEM GLOWNYM (telegram.json obok stan.json):
tam ida alarmy, raporty i gotowe rolki wszystkich person. Do tego (3.6.1):
  - DODATKOWE KONTA (ustawienie globalne `telegram_dodatkowe`, lista "@nazwa" albo id liczbowe) - dostaja to samo co czat
    glowny (gotowe rolki wszystkich person, zdjecia, alarmy, raport dnia); /stop i /wznow zostaja tylko dla czatu glownego,
  - KONTO PERSONY (ustawienie persony `telegram_czat`, np. "@huy7128") - dostaje gotowe rolki swojej persony.
Takie konto musi raz napisac /start do bota (Telegram nie pozwala botom pisac pierwszym); bot je paruje, bo jest na liscie
dozwolonych. Konto z listy NIE zostaje czatem glownym, nawet gdy napisze pierwsze. Obce czaty sa ignorowane (bez odpowiedzi).
Jedna wiadomosc na konto: to samo konto jako glowne i dodatkowe dostaje rolke raz (`adresaci`).
Limity Telegrama: pobieranie <= 20 MB, wysylka <= 50 MB.
"""
import json
import os
import re
import threading
import time
from contextlib import contextmanager

import baza
import sekrety
from dostawcy import BladDostawcy, BrakKlucza
from dostawcy import http

BAZA_URL = "https://api.telegram.org"
LIMIT_POBIERANIA = 20 * 1024 * 1024
LIMIT_WYSYLKI = 50 * 1024 * 1024
ROZSZERZENIA_WIDEO = (".mp4", ".mov", ".webm", ".m4v")
CACHE_BOTA_S = 600


class BladSieci(BladDostawcy):
    """Telegram nie odpowiada (brak sieci, timeout, 5xx, 429) - nie wiadomo nic o koncie; ponawiamy po cichu pozniej."""


def _token():
    t = sekrety.klucz("telegram")
    if not t:
        raise BrakKlucza("Brak tokena bota Telegram (panel -> Konta -> Telegram).")
    return t


def skonfigurowany():
    return bool(sekrety.klucz("telegram"))


def _url(metoda):
    return f"{BAZA_URL}/bot{_token()}/{metoda}"


def _blad(metoda, e):
    """BladHTTP -> BladSieci (siec / 5xx / 429 - sprobujemy pozniej) albo BladDostawcy (odpowiedz Telegrama, np. 403)."""
    tekst = f"Telegram {metoda}: {_opis(e)}"
    if e.status == 0 or e.status >= 500 or e.status == 429:
        return BladSieci(tekst)
    return BladDostawcy(tekst)


def _wywolaj(metoda, dane=None, timeout=30, powtorki=1):
    try:
        odp = http.zapytanie("POST", _url(metoda), dane=dane or {}, timeout=timeout, powtorki=powtorki)
    except http.BladHTTP as e:
        raise _blad(metoda, e)
    if not isinstance(odp, dict) or not odp.get("ok"):
        raise BladDostawcy(f"Telegram {metoda}: {_bez_tokena(str(odp)[:200])}")
    return odp.get("result")


def _bez_tokena(tekst):
    """Token bota nigdy nie trafia do komunikatu (siedzi w adresie URL)."""
    t = sekrety.klucz("telegram")
    return str(tekst).replace(t, "***") if t else str(tekst)


def _opis(e):
    try:
        d = json.loads(e.tekst)
        return _bez_tokena(d.get("description") or e.tekst[:200])
    except (ValueError, AttributeError):
        if getattr(e, "status", None) == 0 and getattr(e, "tekst", ""):
            return _bez_tokena(e.tekst[:200])          # "blad sieci: timed out"
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
    with baza._rmw(_plik_stanu()):
        s = stan()
        s.update(pola)
        baza._zapisz_json(_plik_stanu(), s)
    return s


def sparowany():
    return bool(stan().get("chat_id"))


def rozparuj():
    zapisz_stan(chat_id=None, czat="", czaty={})


def rozparuj_glowny():
    """Odlacza tylko czat glowny (np. glownym zostalo nie to konto) - nastepny czat spoza list, ktory napisze /start, zostanie
    glownym. Konta dodatkowe i konta person zostaja sparowane."""
    s = stan()
    czaty_ = dict(s.get("czaty") or {})
    cid = s.get("chat_id")
    if cid is not None:
        info = czaty_.get(str(cid)) or {}
        listy = set(dodatkowe_konta()) | set(konta_person())
        if not any(_pasuje(cid, info, k) for k in listy):      # konto z list zostaje sparowane w swojej roli
            czaty_.pop(str(cid), None)
    zapisz_stan(chat_id=None, czat="", czaty=czaty_)


def czaty():
    """Wszystkie sparowane czaty: {"<chat_id>": {"nazwa": "huy7128", "glowny": bool}} (czat glowny tez)."""
    s = stan()
    wynik = {c: dict(i) for c, i in (s.get("czaty") or {}).items()}
    if s.get("chat_id") and str(s["chat_id"]) not in wynik:
        wynik[str(s["chat_id"])] = {"nazwa": s.get("czat") or str(s["chat_id"])}
    for cid, info in wynik.items():
        info["glowny"] = bool(s.get("chat_id")) and str(cid) == str(s["chat_id"])
    return wynik


def _konto(konto):
    """"@Huy7128" / "huy7128" / "https://t.me/huy7128" / " 123 " -> "huy7128" / "123" (male litery, bez @)."""
    k = (konto or "").strip()
    k = re.sub(r"^(https?://)?(www\.)?(t|telegram)\.me/", "", k, flags=re.I)
    return k.strip().lstrip("@").strip().lower()


WZOR_KONTA = re.compile(r"^(?:[a-z][a-z0-9_]{2,31}|-?\d{3,20})$")


def normalizuj_konta(wartosc):
    """Lista kont z panelu ("@a\\n@b", "@a, @b" albo lista) -> ["a", "b"] (bez @, male litery, bez powtorek).
    ValueError, gdy cos nie wyglada na konto Telegrama (nazwa 3-32 znaki: litery, cyfry, _ albo id liczbowe)."""
    if wartosc is None:
        return []
    if isinstance(wartosc, str):
        linie = re.split(r"[\r\n,;]+", wartosc)
    elif isinstance(wartosc, (list, tuple)):
        linie = [str(x) for x in wartosc]
    else:
        raise ValueError("Dodatkowe konta: podaj liste kont (@nazwa albo id liczbowe).")
    wynik, zle = [], []
    for linia in linie:
        linia = linia.strip()
        if not linia:
            continue
        # "@a @b" w jednej linii - przyjmujemy, gdy kazdy kawalek jest kontem; inaczej zla jest cala linia ("zle konto!")
        kawalki = [_konto(c) for c in linia.split()]
        if not all(k and WZOR_KONTA.match(k) for k in kawalki):
            zle.append(linia)
            continue
        for k in kawalki:
            if k not in wynik:
                wynik.append(k)
    if zle:
        raise ValueError("To nie wyglada na konto Telegrama: " + ", ".join(f'"{z}"' for z in zle)
                         + " - wpisz @nazwe konta (litery, cyfry, _) albo jego id liczbowe, po jednym w linii.")
    if len(wynik) > 20:
        raise ValueError("Maksymalnie 20 dodatkowych kont.")
    return wynik


def dodatkowe_konta():
    """Konta z ustawienia globalnego `telegram_dodatkowe` (znormalizowane, zle wpisy pomijane)."""
    try:
        surowe = baza.ustawienia_globalne().get("telegram_dodatkowe") or []
    except Exception:
        return []
    wynik = []
    for c in (surowe if isinstance(surowe, (list, tuple)) else re.split(r"[\s,;]+", str(surowe))):
        k = _konto(str(c))
        if k and WZOR_KONTA.match(k) and k not in wynik:
            wynik.append(k)
    return wynik


def konta_person():
    """Konta Telegram person z ustawien telegram_czat -> {"huy7128": "noemi"} (bot paruje tylko te, dodatkowe i czat glowny)."""
    wynik = {}
    for slug in baza.lista_modelek():
        konto = _konto(baza.ustawienia_modelki(slug).get("telegram_czat"))
        if konto:
            wynik.setdefault(konto, slug)
    return wynik


def _pasuje(cid, info, k):
    """Czy sparowany czat (cid, info z czaty()) to konto `k` (znormalizowane)."""
    if not k:
        return False
    if str(cid) == k:
        return True
    nazwa = info.get("username") if "username" in info else info.get("nazwa")
    return (nazwa or "").lower() == k


def sparowany_czat(konto):
    """(chat_id, nazwa) sparowanego czatu tego konta albo (None, None) - konto nie napisalo jeszcze /start."""
    k = _konto(konto)
    for cid, info in czaty().items():
        if _pasuje(cid, info, k):
            return int(cid), info.get("nazwa") or str(cid)
    return None, None


def czat_dla(konto):
    """chat_id dla konta z ustawienia persony ("@huy7128", "huy7128" albo id liczbowe); "" = czat glowny.
    Zwraca (chat_id | None, opis) - None, gdy to konto nie napisalo jeszcze /start do bota."""
    s = stan()
    k = _konto(konto)
    if not k:
        return (s.get("chat_id") or None), (s.get("czat") or "czat glowny")
    cid, nazwa = sparowany_czat(k)
    if cid is not None:
        return cid, nazwa
    if k.lstrip("-").isdigit():
        return int(k), k      # user wpisal chat_id liczbowo - probujemy wprost
    return None, f"@{k} nie napisal jeszcze /start do bota"


def adresaci(konto_persony=None, dodatkowe=None):
    """Komu wyslac gotowa rolke/zdjecie/alarm: czat glowny + sparowane konta dodatkowe (+ konto persony, gdy podane).
    Kazde konto RAZ (to samo konto jako glowne i dodatkowe = jedna wiadomosc). Zwraca (lista, brak):
    lista = [{"chat_id": int, "nazwa": str, "rola": "glowny"|"dodatkowe"|"persona"}], brak = opis konta persony, ktore nie
    napisalo jeszcze /start (albo None). Konto dodatkowe bez /start jest pomijane (pokazuje je panel)."""
    s = stan()
    wynik, widziane = [], set()

    def dodaj(cid, nazwa, rola):
        if cid is None or str(cid) in widziane:
            return
        widziane.add(str(cid))
        wynik.append({"chat_id": int(cid), "nazwa": nazwa or str(cid), "rola": rola})

    if s.get("chat_id"):
        dodaj(s["chat_id"], s.get("czat") or str(s["chat_id"]), "glowny")
    for k in (dodatkowe if dodatkowe is not None else dodatkowe_konta()):
        cid, nazwa = sparowany_czat(k)
        dodaj(cid, nazwa, "dodatkowe")
    brak = None
    if _konto(konto_persony):
        cid, opis = czat_dla(konto_persony)
        if cid is None:
            brak = opis
        else:
            dodaj(cid, opis, "persona")
    return wynik, brak


def wszyscy_polaczeni():
    """Wszystkie sparowane konta, ktore cos dostaja (glowny, dodatkowe, konta person) - kazde raz. Do "Wyslij test"."""
    wynik, _ = adresaci()
    widziane = {str(a["chat_id"]) for a in wynik}
    for konto, slug in konta_person().items():
        cid, nazwa = sparowany_czat(konto)
        if cid is not None and str(cid) not in widziane:
            widziane.add(str(cid))
            wynik.append({"chat_id": cid, "nazwa": nazwa, "rola": "persona", "persona": slug})
    return wynik


def status_kont():
    """Dla panelu (Konta -> Telegram): czat glowny, kazde konto dodatkowe i konta person - polaczone / czeka na /start."""
    s = stan()
    glowny = {"nazwa": s.get("czat") or str(s["chat_id"]), "polaczone": True} if s.get("chat_id") else None
    dod = []
    for k in dodatkowe_konta():
        cid, nazwa = sparowany_czat(k)
        dod.append({"konto": k, "polaczone": cid is not None, "glowny": bool(glowny) and cid is not None
                    and str(cid) == str(s.get("chat_id"))})
    persony = []
    for slug in baza.lista_modelek():
        konto = _konto(baza.ustawienia_modelki(slug).get("telegram_czat"))
        if not konto:
            continue
        cid, _ = sparowany_czat(konto)
        persony.append({"slug": slug, "persona": (baza.profil_modelki(slug).get("nazwa") or slug), "konto": konto,
                        "polaczone": cid is not None})
    return {"glowny": glowny, "dodatkowe": dod, "persony": persony}


def _nazwa_czatu(czat_msg):
    return czat_msg.get("username") or czat_msg.get("first_name") or str(czat_msg.get("id"))


# ---------------- blokada: jeden krok telefonu naraz ----------------
# Watek odbioru w panelu (3.6.1, co 20 s) i autopilot (krok "telefon") nie moga naraz robic getUpdates z tym samym offsetem
# (ta sama wiadomosc obsluzona dwa razy) ani wysylac tej samej rolki. Blokada watkow (RLock - ten sam watek wchodzi ponownie)
# + plik telegram.lock obok telegram.json (msvcrt/fcntl - inny proces, np. `python autopilot.py`); znika sama z procesem.

_BLOKADA = threading.RLock()
_blokada_stan = {"glebokosc": 0, "plik": None}


def _plik_blokady():
    return os.path.join(os.path.dirname(baza.PLIK_STANU), "telegram.lock")


@contextmanager
def blokada(czekaj_s=0.0):
    """`with telegram.blokada(30) as moge:` - moge=False, gdy telefon obsluguje teraz ktos inny (czekalismy czekaj_s)."""
    czekaj_s = max(0.0, float(czekaj_s or 0))
    koniec = time.monotonic() + czekaj_s
    mam = _BLOKADA.acquire(timeout=czekaj_s) if czekaj_s else _BLOKADA.acquire(blocking=False)
    if not mam:
        yield False
        return
    moge = True
    try:
        if _blokada_stan["glebokosc"] == 0:
            os.makedirs(os.path.dirname(_plik_blokady()), exist_ok=True)
            f = open(_plik_blokady(), "a+")
            while not baza._zablokuj_plik(f):
                if time.monotonic() >= koniec:
                    f.close()
                    f, moge = None, False
                    break
                time.sleep(0.2)
            _blokada_stan["plik"] = f
        if moge:
            _blokada_stan["glebokosc"] += 1
        try:
            yield moge
        finally:
            if moge:
                _blokada_stan["glebokosc"] -= 1
                if _blokada_stan["glebokosc"] == 0 and _blokada_stan["plik"] is not None:
                    baza._odblokuj_plik(_blokada_stan["plik"])
                    _blokada_stan["plik"].close()
                    _blokada_stan["plik"] = None
    finally:
        _BLOKADA.release()


# ---------------- wysylanie ----------------

_bot_cache = {}


def bot_info(odswiez=False):
    """getMe (cache 10 min): {"username", "link": "https://t.me/<username>"}. BladDostawcy/BladSieci, gdy sie nie da."""
    t = _bot_cache.get("czas") or 0
    if not odswiez and _bot_cache.get("info") and time.time() - t < CACHE_BOTA_S and _bot_cache.get("token") == sekrety.klucz("telegram"):
        return dict(_bot_cache["info"])
    ja = _wywolaj("getMe", timeout=10)
    nazwa = (ja or {}).get("username") or ""
    info = {"username": nazwa, "link": f"https://t.me/{nazwa}" if nazwa else "", "imie": (ja or {}).get("first_name") or ""}
    _bot_cache.update(info=info, czas=time.time(), token=sekrety.klucz("telegram"))
    return dict(info)


def gotowy():
    if not skonfigurowany():
        return False, "brak tokena bota (panel -> Konta -> Telegram)"
    try:
        ja = _wywolaj("getMe")
    except BladDostawcy as e:
        return False, str(e)
    nazwa = ja.get("username") or ja.get("first_name") or "?"
    if sparowany():
        osoby = konta_person()
        dod = set(dodatkowe_konta())
        person, dodatkowe = [], []
        for c, i in czaty().items():
            if i.get("glowny"):
                continue
            n = (i.get("username") if "username" in i else i.get("nazwa")) or str(c)
            if any(_pasuje(c, i, k) for k in dod):
                dodatkowe.append(i.get("nazwa") or n)
            elif any(_pasuje(c, i, k) for k in osoby):
                person.append(i.get("nazwa") or n)
        return True, (f"bot @{nazwa}, sparowany z czatem {stan().get('czat') or stan().get('chat_id')}"
                      + (f" (+ konta person: {', '.join('@' + str(n) for n in person)})" if person else "")
                      + (f" (+ dodatkowe konta: {', '.join('@' + str(n) for n in dodatkowe)})" if dodatkowe else ""))
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
        raise _blad(metoda, e)
    if not isinstance(odp, dict) or not odp.get("ok"):
        raise BladDostawcy(f"Telegram {metoda}: {_bez_tokena(str(odp)[:200])}")
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


def odbierz(dozwolone=None, dodatkowe=None):
    """Nowe wiadomosci ze sparowanych czatow. Paruje: pierwszy czat spoza list, ktory napisze (= czat glowny), konta person
    z `dozwolone` ({"huy7128": "noemi"} - z ustawien telegram_czat) i konta dodatkowe (`dodatkowe`, domyslnie z ustawienia
    globalnego telegram_dodatkowe). Konto z listy nigdy nie zostaje czatem glownym. Obce czaty (i sparowane kiedys konta, ktore
    zniknely z list) sa pomijane - bez odpowiedzi.
    Zwraca liste slownikow z _rozpoznaj + "chat_id", "od", "glowny", "dodatkowe" (bool), "persona" (slug albo None),
    "rola" (glowny|dodatkowe|persona), "nowy" (czat wlasnie sparowany). Offset zapisuje w telegram.json.
    Wolac pod `blokada()` - inaczej dwa watki moglyby obsluzyc te sama wiadomosc."""
    s = stan()
    dozwolone = {_konto(k): v for k, v in (dozwolone or {}).items() if _konto(k)}
    dodatkowe = {_konto(k) for k in (dodatkowe if dodatkowe is not None else dodatkowe_konta())} - {""}
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
        uzytkownik = _konto(czat_msg.get("username"))
        klucze = {uzytkownik, str(cid)} - {""}
        persona = next((dozwolone[k] for k in klucze if k in dozwolone), None)
        dodatkowy = bool(klucze & dodatkowe)
        nowy = False
        if chat_id is None and not (persona or dodatkowy):
            chat_id, czat, nowy = cid, nazwa, True          # parowanie: pierwszy czat spoza list = glowny
        elif cid != chat_id:
            if not (persona or dodatkowy):
                continue                                    # obcy czat (albo konto usuniete z list) - ignorujemy
            nowy = str(cid) not in znane
        info = {"nazwa": nazwa, "username": uzytkownik}
        if znane.get(str(cid)) != info:
            znane[str(cid)] = info
        w = _rozpoznaj(msg)
        w["chat_id"] = cid
        w["od"] = (msg.get("from") or {}).get("username") or ""
        w["glowny"] = cid == chat_id
        w["dodatkowe"] = dodatkowy
        w["persona"] = persona
        w["rola"] = "glowny" if w["glowny"] else ("dodatkowe" if dodatkowy else "persona")
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
        raise _blad("pobieranie", e)
    return cel
